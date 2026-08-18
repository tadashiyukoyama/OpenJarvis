"""Bearer authentication for the gateway-marked local MCP facade path."""

from __future__ import annotations

import hmac
import os

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from openjarvis.server.jarvis_agent.api.mcp_relay_contract import (
    is_mcp_relay_request_allowed,
)


class MCPAgentBearerMiddleware:
    """Authenticate requests marked by the trusted reverse proxy."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._token = os.environ.get("OPENJARVIS_MCP_AUTH_TOKEN", "").strip()
        if self._token and len(self._token) < 32:
            raise RuntimeError("MCP Agent credential is too short")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("x-openjarvis-mcp-gateway") != "1":
            await self.app(scope, receive, send)
            return
        authorization = headers.get("authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not self._token or not hmac.compare_digest(supplied, self._token):
            response = JSONResponse(
                {"detail": "MCP Agent authentication failed"},
                status_code=401,
            )
            await response(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "")
        if not is_mcp_relay_request_allowed(method, path):
            response = JSONResponse(
                {"detail": "MCP Agent method or path is not allowed"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


__all__ = ["MCPAgentBearerMiddleware"]
