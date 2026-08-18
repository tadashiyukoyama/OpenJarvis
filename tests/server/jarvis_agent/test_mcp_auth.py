from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.jarvis_agent.api.mcp_auth import MCPAgentBearerMiddleware

TOKEN = "mcp-test-token-0123456789abcdef0"


def _app(monkeypatch) -> FastAPI:
    monkeypatch.setenv("OPENJARVIS_MCP_AUTH_TOKEN", TOKEN)
    app = FastAPI()
    app.add_middleware(MCPAgentBearerMiddleware)

    @app.get("/v1/jarvis/agent/catalog")
    async def catalog() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/info")
    async def info() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/v1/jarvis/agent/actions/action-1/decision")
    async def decision() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_mcp_gateway_marker_requires_independent_bearer(monkeypatch) -> None:
    client = TestClient(_app(monkeypatch))
    marked = {"X-OpenJarvis-MCP-Gateway": "1"}

    assert client.get("/v1/jarvis/agent/catalog", headers=marked).status_code == 401
    response = client.get(
        "/v1/jarvis/agent/catalog",
        headers={**marked, "Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200


def test_mcp_gateway_marker_cannot_reach_non_agent_routes(monkeypatch) -> None:
    client = TestClient(_app(monkeypatch))

    response = client.get(
        "/v1/info",
        headers={
            "X-OpenJarvis-MCP-Gateway": "1",
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    assert response.status_code == 403


def test_mcp_gateway_bearer_cannot_reach_agent_decisions(monkeypatch) -> None:
    client = TestClient(_app(monkeypatch))

    response = client.post(
        "/v1/jarvis/agent/actions/action-1/decision",
        headers={
            "X-OpenJarvis-MCP-Gateway": "1",
            "Authorization": f"Bearer {TOKEN}",
        },
    )

    assert response.status_code == 403
