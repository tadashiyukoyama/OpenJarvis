"""MCP facade for canonical non-Codex Jarvis Agent tools."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.mcp.agent_client import AgentCoreClient
from openjarvis.mcp.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MCPRequest,
    MCPResponse,
)


class JarvisAgentMCPServer:
    """Expose tools only through the canonical Agent Core path."""

    SERVER_NAME = "openjarvis-agent"
    SERVER_VERSION = "1.0.0"
    PROTOCOL_VERSION = "2025-11-25"
    INSTRUCTIONS = (
        "Ferramentas Jarvis de leitura podem ser executadas diretamente. "
        "Mutações exigem aprovação visual no OpenJarvis e podem expirar; "
        "não repita automaticamente chamadas com erro, timeout ou resultado "
        "desconhecido. Ferramentas Codex são excluídas para impedir recursão."
    )

    def __init__(self, client: AgentCoreClient) -> None:
        self._client = client
        self._tools: dict[str, dict[str, Any]] = {}

    def handle(self, request: MCPRequest) -> MCPResponse:
        if request.id is None and request.method != "notifications/initialized":
            return MCPResponse.error_response(
                0, INVALID_REQUEST, "MCP tool calls require a request id"
            )
        if request.method == "initialize":
            return self._initialize(request)
        if request.method == "notifications/initialized":
            return MCPResponse(result={}, id=request.id or 0)
        if request.method == "tools/list":
            return self._list(request)
        if request.method == "tools/call":
            return self._call(request)
        return MCPResponse.error_response(
            request.id or 0, METHOD_NOT_FOUND, "Unknown MCP method"
        )

    def close(self) -> None:
        self._client.close()

    def _initialize(self, request: MCPRequest) -> MCPResponse:
        return MCPResponse(
            result={
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {
                    "name": self.SERVER_NAME,
                    "version": self.SERVER_VERSION,
                    "title": "OpenJarvis Agent Tools",
                },
                "instructions": self.INSTRUCTIONS,
            },
            id=request.id or 0,
        )

    def _list(self, request: MCPRequest) -> MCPResponse:
        try:
            values = [
                item
                for item in self._client.catalog()
                if item.get("source") != "codex"
                and not str(item.get("id") or "").startswith("codex.")
            ]
            if len(values) > 13:
                raise RuntimeError("Agent Core exposed more than 13 local tools")
            self._tools = {str(item["name"]): item for item in values}
            tools = [self._mcp_tool(item) for item in values]
            return MCPResponse(result={"tools": tools}, id=request.id or 0)
        except Exception:
            return MCPResponse.error_response(
                request.id or 0,
                INTERNAL_ERROR,
                "Jarvis Agent tool catalog is unavailable",
            )

    def _call(self, request: MCPRequest) -> MCPResponse:
        name = request.params.get("name")
        arguments = request.params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return MCPResponse.error_response(
                request.id or 0, INVALID_PARAMS, "Invalid MCP tool call"
            )
        if not self._tools:
            listed = self._list(MCPRequest(method="tools/list", id=request.id))
            if listed.error is not None:
                return listed
        if name not in self._tools:
            return MCPResponse.error_response(
                request.id or 0, INVALID_PARAMS, "Unknown Jarvis Agent tool"
            )
        try:
            result = self._client.call_tool(
                name,
                arguments,
                request_key=str(request.id),
            )
            failed = result.get("state") in {
                "DENIED",
                "EXPIRED",
                "BUSY",
                "UNKNOWN",
                "FAILED",
            }
            return MCPResponse(
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                result, ensure_ascii=False, separators=(",", ":")
                            ),
                        }
                    ],
                    "isError": failed,
                },
                id=request.id or 0,
            )
        except Exception:
            return MCPResponse.error_response(
                request.id or 0, INTERNAL_ERROR, "Jarvis Agent tool call failed"
            )

    @staticmethod
    def _mcp_tool(item: dict[str, Any]) -> dict[str, Any]:
        read_only = item.get("effect") == "read"
        return {
            "name": item["name"],
            "description": item["description"],
            "inputSchema": item["input_schema"],
            "annotations": {
                "readOnlyHint": read_only,
                "destructiveHint": not read_only,
                "idempotentHint": read_only,
            },
        }


__all__ = ["JarvisAgentMCPServer"]
