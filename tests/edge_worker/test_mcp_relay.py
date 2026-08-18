from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

from openjarvis.edge_worker.mcp_relay import (
    MCPRelayConfig,
    MCPRelayServer,
    is_allowed_request,
)
from openjarvis.mcp.agent_pipe import AgentPipeTransport


def _environment() -> dict[str, str]:
    return {
        "OPENJARVIS_EDGE_LOCAL_MCP_PIPE": r"\\.\pipe\openjarvis-agent-mcp",
        "OPENJARVIS_EDGE_LOCAL_MCP_TOKEN": "local-test-token-0123456789abcdef",
        "OPENJARVIS_EDGE_AGENT_CORE_URL": "https://openjarvis.example/local-agent",
        "OPENJARVIS_EDGE_AGENT_CORE_TOKEN": "remote-test-token-0123456789abcde",
        "OPENJARVIS_EDGE_AGENT_CORE_TIMEOUT_SECONDS": "30",
    }


def test_mcp_relay_is_optional_but_partial_configuration_fails_closed() -> None:
    assert MCPRelayConfig.from_env({}) is None
    with pytest.raises(ValueError, match="incomplete"):
        MCPRelayConfig.from_env(
            {"OPENJARVIS_EDGE_LOCAL_MCP_PIPE": r"\\.\pipe\openjarvis-agent-mcp"}
        )


def test_mcp_relay_accepts_only_https_core_and_openjarvis_pipe() -> None:
    config = MCPRelayConfig.from_env(_environment())

    assert config is not None
    assert config.timeout_seconds == 30

    invalid = _environment()
    invalid["OPENJARVIS_EDGE_AGENT_CORE_URL"] = "http://openjarvis.example/local-agent"
    with pytest.raises(ValueError, match="HTTPS"):
        MCPRelayConfig.from_env(invalid)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/jarvis/agent/catalog"),
        ("POST", "/v1/jarvis/agent/sessions"),
        ("POST", "/v1/jarvis/agent/sessions/session-1/proposals"),
        ("POST", "/v1/jarvis/agent/sessions/session-1/close"),
        ("GET", "/v1/jarvis/agent/actions/action-1"),
    ],
)
def test_mcp_relay_allows_only_the_minimum_agent_surface(
    method: str, path: str
) -> None:
    assert is_allowed_request(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/jarvis/agent/actions/action-1/decision"),
        ("GET", "/v1/jarvis/agent/context"),
        ("POST", "/v1/chat/completions"),
        ("GET", "/v1/jarvis/agent/edge/devices"),
        ("GET", "/../../private"),
    ],
)
def test_mcp_relay_denies_decisions_admin_and_generic_paths(
    method: str, path: str
) -> None:
    assert not is_allowed_request(method, path)


@pytest.mark.asyncio
async def test_mcp_relay_preserves_gateway_prefix_and_bearer() -> None:
    config = MCPRelayConfig.from_env(_environment())
    assert config is not None
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"tools": []})

    server = MCPRelayServer(config)
    await server._client.aclose()
    server._client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {config.core_token}"},
        transport=httpx.MockTransport(handler),
    )

    response = await server._forward(
        "request-1", "GET", "/v1/jarvis/agent/catalog", None
    )
    await server.close()

    assert response["ok"] is True
    assert seen["url"] == (
        "https://openjarvis.example/local-agent/v1/jarvis/agent/catalog"
    )
    assert seen["authorization"] == ("Bearer remote-test-token-0123456789abcde")


@pytest.mark.skipif(os.name != "nt", reason="Windows named pipe integration")
@pytest.mark.asyncio
async def test_named_pipe_round_trip_is_authenticated_json_not_pickle() -> None:
    config = MCPRelayConfig(
        pipe_name=rf"\\.\pipe\openjarvis-test-{uuid.uuid4().hex}",
        local_token="local-test-token-0123456789abcdef",
        core_url="https://openjarvis.example/local-agent",
        core_token="remote-test-token-0123456789abcde",
        timeout_seconds=5,
    )
    server = MCPRelayServer(config)

    async def forward(
        request_id: str, method: str, path: str, body: object
    ) -> dict[str, object]:
        return {
            "request_id": request_id,
            "ok": True,
            "status_code": 200,
            "body": {"method": method, "path": path, "json": body},
        }

    server._forward = forward  # type: ignore[method-assign]
    await server.start()
    transport = AgentPipeTransport(config.pipe_name, config.local_token)

    result = await asyncio.to_thread(
        transport.request,
        "GET",
        "/v1/jarvis/agent/catalog",
    )
    await server.close()

    assert result["method"] == "GET"
    assert result["path"] == "/v1/jarvis/agent/catalog"
