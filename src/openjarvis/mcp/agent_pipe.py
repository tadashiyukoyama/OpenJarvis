"""Synchronous JSON client for the Edge Worker's authenticated named pipe."""

from __future__ import annotations

import json
import uuid
from multiprocessing.connection import Client
from typing import Any

_MAX_MESSAGE_BYTES = 256 * 1024


class AgentPipeTransport:
    def __init__(self, pipe_name: str, token: str) -> None:
        self.pipe_name = pipe_name
        self._authkey = token.encode("utf-8")

    def request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        wire = json.dumps(
            {
                "request_id": request_id,
                "method": method,
                "path": path,
                "json": json_body,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(wire) > _MAX_MESSAGE_BYTES:
            raise RuntimeError("Local Agent request is too large")
        try:
            with Client(
                self.pipe_name,
                family="AF_PIPE",
                authkey=self._authkey,
            ) as connection:
                connection.send_bytes(wire)
                response = json.loads(connection.recv_bytes(_MAX_MESSAGE_BYTES))
        except (OSError, EOFError, ValueError) as exc:
            raise RuntimeError("OpenJarvis Edge Worker is unavailable") from exc
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            raise RuntimeError("OpenJarvis Edge Worker returned an invalid response")
        if response.get("ok") is not True:
            error = str(response.get("error") or "LOCAL_RELAY_FAILED")
            raise RuntimeError(f"OpenJarvis Edge Worker rejected the request: {error}")
        payload = response.get("body")
        if not isinstance(payload, dict):
            raise RuntimeError("Agent Core returned an invalid response")
        return payload


__all__ = ["AgentPipeTransport"]
