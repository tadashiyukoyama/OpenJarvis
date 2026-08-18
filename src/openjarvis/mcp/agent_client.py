"""Authenticated client for the canonical Jarvis Agent Core API."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from openjarvis.mcp.agent_pipe import AgentPipeTransport

_TERMINAL = {"COMPLETED", "DENIED", "EXPIRED", "BUSY", "UNKNOWN", "FAILED"}


@dataclass(frozen=True, slots=True)
class AgentCoreClientConfig:
    project_key: str
    pipe_name: str = ""
    pipe_token: str = ""
    base_url: str = ""
    token: str = ""
    codex_thread_id: str = ""
    timeout_seconds: float = 30.0
    approval_wait_seconds: float = 310.0

    @classmethod
    def from_env(cls) -> "AgentCoreClientConfig":
        return cls(
            project_key=os.environ.get("OPENJARVIS_MCP_PROJECT_KEY", "").strip(),
            pipe_name=os.environ.get("OPENJARVIS_MCP_PIPE", "").strip(),
            pipe_token=os.environ.get("OPENJARVIS_MCP_PIPE_TOKEN", "").strip(),
            base_url=os.environ.get("OPENJARVIS_MCP_AGENT_CORE_URL", "").strip(),
            token=os.environ.get("OPENJARVIS_MCP_AUTH_TOKEN", "").strip(),
            codex_thread_id=os.environ.get(
                "OPENJARVIS_MCP_CODEX_THREAD_ID", ""
            ).strip(),
            timeout_seconds=float(
                os.environ.get("OPENJARVIS_MCP_HTTP_TIMEOUT_SECONDS", "30")
            ),
            approval_wait_seconds=float(
                os.environ.get("OPENJARVIS_MCP_APPROVAL_WAIT_SECONDS", "310")
            ),
        ).validated()

    def validated(self) -> "AgentCoreClientConfig":
        has_pipe = bool(self.pipe_name or self.pipe_token)
        has_http = bool(self.base_url or self.token)
        if has_pipe == has_http:
            raise ValueError("MCP requires exactly one local transport")
        if has_pipe:
            if (
                not self.pipe_name.startswith(r"\\.\pipe\openjarvis-")
                or len(self.pipe_token) < 32
            ):
                raise ValueError("MCP named-pipe configuration is invalid")
        else:
            parsed = urlparse(self.base_url)
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if parsed.scheme != "http" or not loopback:
                raise ValueError("MCP HTTP fallback must remain on loopback")
            if parsed.username or parsed.password or len(self.token) < 32:
                raise ValueError("MCP loopback configuration is invalid")
        if not self.project_key:
            raise ValueError("MCP project is required")
        if self.timeout_seconds <= 0 or self.approval_wait_seconds <= 0:
            raise ValueError("MCP timeouts must be positive")
        return self


class AgentCoreClient:
    def __init__(
        self,
        config: AgentCoreClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config.validated()
        self._pipe = (
            AgentPipeTransport(self.config.pipe_name, self.config.pipe_token)
            if self.config.pipe_name
            else None
        )
        self._client = (
            httpx.Client(
                base_url=self.config.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=self.config.timeout_seconds,
                transport=transport,
            )
            if self.config.base_url
            else None
        )
        self._session: dict[str, Any] | None = None

    def catalog(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v1/jarvis/agent/catalog")
        tools = payload.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("Agent Core returned no tool catalog")
        return [
            dict(item)
            for item in tools
            if isinstance(item, Mapping)
            and item.get("available") is True
            and item.get("source") != "codex"
            and not str(item.get("id") or "").startswith("codex.")
        ]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        request_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._ensure_session()
        function_call_id = self._function_call_id(
            session_id=str(session["session_id"]),
            name=name,
            arguments=arguments,
            request_key=request_key,
        )
        response = self._request(
            "POST",
            f"/v1/jarvis/agent/sessions/{session['session_id']}/proposals",
            json={
                "generation": session["generation"],
                "function_call_id": function_call_id,
                "name": name,
                "arguments": dict(arguments),
            },
        )
        action = response.get("result")
        if not isinstance(action, Mapping):
            raise RuntimeError("Agent Core returned no action")
        if action.get("state") == "AWAITING_APPROVAL":
            return self._wait_action(str(action["action_id"]))
        return dict(action)

    @staticmethod
    def _function_call_id(
        *,
        session_id: str,
        name: str,
        arguments: Mapping[str, Any],
        request_key: str | None,
    ) -> str:
        if request_key is None:
            return f"mcp_{uuid.uuid4().hex}"
        material = json.dumps(
            {
                "session_id": session_id,
                "request_key": request_key,
                "name": name,
                "arguments": dict(arguments),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"mcp_{hashlib.sha256(material.encode('utf-8')).hexdigest()}"

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                self._request(
                    "POST",
                    f"/v1/jarvis/agent/sessions/{session['session_id']}/close",
                    json={"generation": session["generation"]},
                )
            except Exception:
                pass
        if self._client is not None:
            self._client.close()

    def _ensure_session(self) -> dict[str, Any]:
        if self._session is None:
            self._session = self._request(
                "POST",
                "/v1/jarvis/agent/sessions",
                json={
                    "project_key": self.config.project_key,
                    "codex_thread_id": self.config.codex_thread_id,
                },
            )
        return self._session

    def _wait_action(self, action_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.approval_wait_seconds
        while time.monotonic() < deadline:
            payload = self._request("GET", f"/v1/jarvis/agent/actions/{action_id}")
            action = payload.get("result")
            if isinstance(action, Mapping) and action.get("state") in _TERMINAL:
                return dict(action)
            time.sleep(0.5)
        return {
            "action_id": action_id,
            "state": "AWAITING_APPROVAL",
            "status": "approval_required",
            "summary": "A ação continua aguardando aprovação visual no Jarvis.",
        }

    def _request(
        self, method: str, path: str, *, json: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._pipe is not None:
            return self._pipe.request(
                method,
                path,
                json_body=dict(json) if json is not None else None,
            )
        if self._client is None:
            raise RuntimeError("MCP transport is unavailable")
        try:
            response = self._client.request(method, path, json=json)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise RuntimeError(
                f"Agent Core rejected the request with HTTP {code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                "Agent Core is unavailable or returned invalid data"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Agent Core returned an invalid response")
        return payload


__all__ = ["AgentCoreClient", "AgentCoreClientConfig"]
