from __future__ import annotations

import json

import httpx
import pytest

from openjarvis.mcp.agent_client import AgentCoreClient, AgentCoreClientConfig
from openjarvis.mcp.agent_pipe import AgentPipeTransport


def test_agent_client_reuses_stable_function_call_id_for_same_mcp_request() -> None:
    proposals: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        proposals.append(payload)
        return httpx.Response(
            200,
            json={"result": {"state": "COMPLETED", "summary": "ok"}},
        )

    client = AgentCoreClient(
        AgentCoreClientConfig(
            base_url="http://127.0.0.1:8127",
            token="loopback-test-token-0123456789abc",
            project_key="D:\\dev\\workspaces\\openjarvis",
        ),
        transport=httpx.MockTransport(handler),
    )
    client._session = {"session_id": "session-1", "generation": 1}

    first = client.call_tool("email_search", {"b": 2, "a": 1}, request_key="7")
    second = client.call_tool("email_search", {"a": 1, "b": 2}, request_key="7")

    assert first["state"] == second["state"] == "COMPLETED"
    assert proposals[0]["function_call_id"] == proposals[1]["function_call_id"]
    assert proposals[0]["function_call_id"].startswith("mcp_")
    client.close()


def test_agent_client_rejects_direct_remote_http_transport() -> None:
    with pytest.raises(ValueError, match="loopback"):
        AgentCoreClientConfig(
            project_key=r"D:\dev\workspaces\openjarvis",
            base_url="https://openjarvis.example/local-agent",
            token="remote-test-token-0123456789abcde",
        ).validated()


def test_agent_client_accepts_authenticated_openjarvis_pipe() -> None:
    config = AgentCoreClientConfig(
        project_key=r"D:\dev\workspaces\openjarvis",
        pipe_name=r"\\.\pipe\openjarvis-agent-mcp",
        pipe_token="local-test-token-0123456789abcdef",
    )

    assert config.validated() is config


def test_named_pipe_transport_uses_json_bytes_and_correlates_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        request: dict | None = None

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def send_bytes(self, wire: bytes) -> None:
            self.request = json.loads(wire)

        def recv_bytes(self, _maximum: int) -> bytes:
            assert self.request is not None
            return json.dumps(
                {
                    "request_id": self.request["request_id"],
                    "ok": True,
                    "body": {"tools": []},
                }
            ).encode("utf-8")

    connection = Connection()
    monkeypatch.setattr(
        "openjarvis.mcp.agent_pipe.Client",
        lambda *_args, **_kwargs: connection,
    )
    transport = AgentPipeTransport(
        r"\\.\pipe\openjarvis-agent-mcp", "local-test-token-0123456789abcdef"
    )

    result = transport.request("GET", "/v1/jarvis/agent/catalog")

    assert result == {"tools": []}
    assert connection.request is not None
    assert connection.request["method"] == "GET"
