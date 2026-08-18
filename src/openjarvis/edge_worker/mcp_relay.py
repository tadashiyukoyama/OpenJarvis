"""Authenticated local named-pipe relay from MCP STDIO to Agent Core."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from multiprocessing.connection import Client, Connection, Listener, wait
from urllib.parse import urlparse

import httpx

from openjarvis.server.jarvis_agent.api.mcp_relay_contract import (
    is_mcp_relay_request_allowed,
)

_MAX_MESSAGE_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class MCPRelayConfig:
    pipe_name: str
    local_token: str
    core_url: str
    core_token: str
    timeout_seconds: float = 330.0

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "MCPRelayConfig | None":
        values = os.environ if environment is None else environment
        raw = {
            "pipe_name": values.get("OPENJARVIS_EDGE_LOCAL_MCP_PIPE", "").strip(),
            "local_token": values.get("OPENJARVIS_EDGE_LOCAL_MCP_TOKEN", "").strip(),
            "core_url": values.get("OPENJARVIS_EDGE_AGENT_CORE_URL", "").strip(),
            "core_token": values.get("OPENJARVIS_EDGE_AGENT_CORE_TOKEN", "").strip(),
        }
        if not any(raw.values()):
            return None
        if not all(raw.values()):
            raise ValueError("Edge MCP relay configuration is incomplete")
        timeout = float(values.get("OPENJARVIS_EDGE_AGENT_CORE_TIMEOUT_SECONDS", "330"))
        config = cls(**raw, timeout_seconds=timeout)
        return config.validated()

    def validated(self) -> "MCPRelayConfig":
        parsed = urlparse(self.core_url)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("Edge Agent Core URL must use HTTPS")
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/local-agent"
        ):
            raise ValueError("Edge Agent Core URL is invalid")
        if not self.pipe_name.startswith(r"\\.\pipe\openjarvis-"):
            raise ValueError("Edge MCP pipe must use the OpenJarvis namespace")
        if len(self.local_token) < 32 or len(self.core_token) < 32:
            raise ValueError("Edge MCP relay tokens are too short")
        if self.timeout_seconds <= 0:
            raise ValueError("Edge MCP relay timeout must be positive")
        return self


def is_allowed_request(method: str, path: str) -> bool:
    return is_mcp_relay_request_allowed(method, path)


class MCPRelayServer:
    """Serve one bounded JSON request per authenticated pipe connection."""

    def __init__(self, config: MCPRelayConfig) -> None:
        self.config = config.validated()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.config.core_token}"},
            timeout=self.config.timeout_seconds,
        )

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._serve,
            name="openjarvis-mcp-pipe",
            daemon=True,
        )
        self._thread.start()
        if not await asyncio.to_thread(self._ready.wait, 5.0):
            raise RuntimeError("Edge MCP relay did not start")
        if self._startup_error is not None:
            raise RuntimeError("Edge MCP relay could not bind") from self._startup_error

    async def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            try:
                await asyncio.to_thread(self._wake_listener)
            except Exception:
                pass
            await asyncio.to_thread(self._thread.join, 5.0)
        await self._client.aclose()

    def _serve(self) -> None:
        try:
            with Listener(
                self.config.pipe_name,
                family="AF_PIPE",
                authkey=self.config.local_token.encode("utf-8"),
            ) as listener:
                self._ready.set()
                while not self._stop.is_set():
                    connection = listener.accept()
                    with connection:
                        if self._stop.is_set():
                            break
                        self._handle_connection(connection)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()

    def _handle_connection(self, connection: Connection) -> None:
        try:
            if not wait([connection], timeout=5.0):
                raise TimeoutError("local relay client did not send a request")
            raw = connection.recv_bytes(_MAX_MESSAGE_BYTES)
            request = json.loads(raw)
            response = self._dispatch(request)
        except Exception:
            response = {"ok": False, "error": "LOCAL_RELAY_INVALID_REQUEST"}
        connection.send_bytes(
            json.dumps(response, separators=(",", ":")).encode("utf-8")
        )

    def _dispatch(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            return {"ok": False, "error": "LOCAL_RELAY_INVALID_REQUEST"}
        request_id = str(request.get("request_id") or "")
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "")
        body = request.get("json")
        if not request_id or not is_allowed_request(method, path):
            return {
                "request_id": request_id,
                "ok": False,
                "error": "LOCAL_RELAY_PATH_DENIED",
            }
        loop = self._loop
        if loop is None:
            return {
                "request_id": request_id,
                "ok": False,
                "error": "LOCAL_RELAY_OFFLINE",
            }
        future = asyncio.run_coroutine_threadsafe(
            self._forward(request_id, method, path, body), loop
        )
        try:
            return future.result(timeout=self.config.timeout_seconds + 5.0)
        except Exception:
            future.cancel()
            return {
                "request_id": request_id,
                "ok": False,
                "error": "LOCAL_RELAY_TIMEOUT",
            }

    async def _forward(
        self, request_id: str, method: str, path: str, body: object
    ) -> dict[str, object]:
        url = f"{self.config.core_url.rstrip('/')}{path}"
        try:
            response = await self._client.request(method, url, json=body)
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "request_id": request_id,
                "ok": False,
                "error": "AGENT_CORE_UNAVAILABLE",
            }
        if not isinstance(payload, dict):
            return {
                "request_id": request_id,
                "ok": False,
                "error": "AGENT_CORE_INVALID_RESPONSE",
            }
        return {
            "request_id": request_id,
            "ok": response.is_success,
            "status_code": response.status_code,
            "body": payload,
            **(
                {}
                if response.is_success
                else {"error": f"AGENT_CORE_HTTP_{response.status_code}"}
            ),
        }

    def _wake_listener(self) -> None:
        with Client(
            self.config.pipe_name,
            family="AF_PIPE",
            authkey=self.config.local_token.encode("utf-8"),
        ):
            pass


__all__ = ["MCPRelayConfig", "MCPRelayServer", "is_allowed_request"]
