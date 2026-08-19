from __future__ import annotations

from pathlib import Path
from typing import Any

from openjarvis.mcp.agent_server import JarvisAgentMCPServer
from openjarvis.mcp.protocol import INTERNAL_ERROR, MCPRequest


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "email.search",
                "name": "email_search",
                "description": "Search email",
                "source": "email",
                "effect": "READ",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "id": "whatsapp.send",
                "name": "whatsapp_send",
                "description": "Send message",
                "source": "whatsapp",
                "effect": "MUTATION",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "id": "codex.delegate",
                "name": "codex_delegate_task",
                "description": "Recursive delegation",
                "source": "codex",
                "effect": "DELEGATION",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        request_key: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((name, arguments, request_key))
        return {"state": "COMPLETED", "name": name, "arguments": arguments}

    def close(self) -> None:
        pass


class _InvalidEffectClient(_Client):
    def catalog(self) -> list[dict[str, Any]]:
        values = super().catalog()
        values[0]["effect"] = "UNRECOGNIZED"
        return values


def test_agent_mcp_initialize_documents_safety_contract() -> None:
    server = JarvisAgentMCPServer(_Client())  # type: ignore[arg-type]

    response = server.handle(MCPRequest(method="initialize", id=1))

    assert response.error is None
    assert response.result["serverInfo"]["name"] == "openjarvis-agent"
    assert "aprovação visual" in response.result["instructions"]
    assert "recursão" in response.result["instructions"]


def test_agent_mcp_excludes_codex_and_exposes_annotations() -> None:
    server = JarvisAgentMCPServer(_Client())  # type: ignore[arg-type]

    response = server.handle(MCPRequest(method="tools/list", id=1))
    tools = response.result["tools"]

    assert [item["name"] for item in tools] == ["email_search", "whatsapp_send"]
    assert tools[0]["annotations"]["readOnlyHint"] is True
    assert tools[1]["annotations"]["destructiveHint"] is True


def test_agent_mcp_rejects_unknown_effect_without_caching_tools() -> None:
    client = _InvalidEffectClient()
    server = JarvisAgentMCPServer(client)  # type: ignore[arg-type]

    response = server.handle(MCPRequest(method="tools/list", id=1))
    tool_call = server.handle(
        MCPRequest(
            method="tools/call",
            params={"name": "email_search", "arguments": {}},
            id=2,
        )
    )

    assert response.error["code"] == INTERNAL_ERROR
    assert tool_call.error["code"] == INTERNAL_ERROR
    assert client.calls == []


def test_agent_mcp_calls_core_without_legacy_executor() -> None:
    client = _Client()
    server = JarvisAgentMCPServer(client)  # type: ignore[arg-type]
    server.handle(MCPRequest(method="tools/list", id=1))

    response = server.handle(
        MCPRequest(
            method="tools/call",
            params={"name": "email_search", "arguments": {"query": "is:unread"}},
            id=2,
        )
    )

    assert response.error is None
    assert response.result["isError"] is False
    assert client.calls == [("email_search", {"query": "is:unread"}, "2")]
    source = Path("src/openjarvis/mcp/agent_server.py").read_text(encoding="utf-8")
    assert "ToolExecutor" not in source


def test_mcp_notification_remains_response_free() -> None:
    notification = MCPRequest.from_json(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}'
    )

    assert notification.id is None


def test_mcp_tool_notification_is_not_executed() -> None:
    client = _Client()
    server = JarvisAgentMCPServer(client)  # type: ignore[arg-type]
    notification = MCPRequest(
        method="tools/call",
        params={"name": "whatsapp_send", "arguments": {"text": "never"}},
        id=None,
    )

    response = server.handle(notification)

    assert response.error["code"] == -32600
    assert client.calls == []
