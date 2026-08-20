from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.jarvis_agent.api.router import router


def test_visual_header_is_required_for_decision(agent_core) -> None:
    orchestrator, adapter = agent_core
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    client = TestClient(app)
    session = client.post(
        "/v1/jarvis/agent/sessions",
        json={"project_key": "D:/dev/project", "codex_thread_id": "t1"},
    ).json()
    proposal = client.post(
        f"/v1/jarvis/agent/sessions/{session['session_id']}/proposals",
        json={
            "generation": session["generation"],
            "function_call_id": "fc-api",
            "name": "fake_write",
            "arguments": {"value": "api exact"},
        },
    ).json()["result"]

    denied_channel = client.post(
        f"/v1/jarvis/agent/actions/{proposal['action_id']}/decision",
        json={
            "session_id": session["session_id"],
            "payload_hash": proposal["payload_hash"],
            "decision": "approve",
        },
    )
    approved = client.post(
        f"/v1/jarvis/agent/actions/{proposal['action_id']}/decision",
        headers={"X-Jarvis-Decision-Channel": "visual"},
        json={
            "session_id": session["session_id"],
            "payload_hash": proposal["payload_hash"],
            "decision": "approve",
        },
    )

    assert denied_channel.status_code == 403
    assert denied_channel.json()["detail"]["code"] == "APPROVAL_REQUIRED"
    assert approved.status_code == 200
    assert approved.json()["result"]["status"] == "completed"
    assert adapter.calls == [("fake.write", {"value": "api exact"})]


def test_partial_transcript_is_rejected_by_contract(agent_core) -> None:
    orchestrator, _ = agent_core
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    client = TestClient(app)
    session = client.post(
        "/v1/jarvis/agent/sessions", json={"project_key": "D:/dev/project"}
    ).json()

    response = client.post(
        f"/v1/jarvis/agent/sessions/{session['session_id']}/turns",
        json={
            "generation": session["generation"],
            "turn_id": "partial-1",
            "transcript": "Mas ele fica",
            "final": False,
        },
    )

    assert response.status_code == 422


def test_finite_event_poll_preserves_cursor(agent_core) -> None:
    orchestrator, _ = agent_core
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    client = TestClient(app)
    session = client.post(
        "/v1/jarvis/agent/sessions", json={"project_key": "D:/dev/project"}
    ).json()

    first = client.get("/v1/jarvis/agent/events/poll?after=0&limit=100")
    assert first.status_code == 200
    payload = first.json()
    assert payload["events"][-1]["event_type"] == "session_opened"
    assert payload["events"][-1]["session_id"] == session["session_id"]
    assert payload["next_after"] == payload["events"][-1]["sequence"]

    second = client.get(
        f"/v1/jarvis/agent/events/poll?after={payload['next_after']}&limit=100"
    )
    assert second.status_code == 200
    assert second.json() == {"events": [], "next_after": payload["next_after"]}


def test_event_history_is_durable_ordered_and_scoped_to_codex_target(
    agent_core,
) -> None:
    orchestrator, _ = agent_core
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    client = TestClient(app)
    first = client.post(
        "/v1/jarvis/agent/sessions",
        json={"project_key": "D:/dev/project", "codex_thread_id": "thread-a"},
    ).json()
    client.post(
        "/v1/jarvis/agent/sessions",
        json={"project_key": "D:/dev/project", "codex_thread_id": "thread-b"},
    )
    client.post(
        f"/v1/jarvis/agent/sessions/{first['session_id']}/proposals",
        json={
            "generation": first["generation"],
            "function_call_id": "history-read",
            "name": "fake_read",
            "arguments": {"value": "history"},
        },
    )

    response = client.get(
        "/v1/jarvis/agent/events/history",
        params={
            "project_key": "D:/dev/project",
            "codex_thread_id": "thread-a",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["sequence"] for event in events] == sorted(
        event["sequence"] for event in events
    )
    assert {event["session_id"] for event in events} == {first["session_id"]}
    assert [event["event_type"] for event in events] == [
        "session_opened",
        "dispatch_started",
        "dispatch_completed",
    ]
    assert response.json()["next_after"] == events[-1]["sequence"]


def test_webhook_body_is_bounded_before_service_dispatch(agent_core) -> None:
    orchestrator, _ = agent_core

    class NeverCalled:
        def receive(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("oversized webhook reached the service")

    original = orchestrator.acelerachat_webhooks
    orchestrator.acelerachat_webhooks = NeverCalled()
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/jarvis/agent/providers/acelerachat/webhooks",
                content=b"x" * (1024 * 1024 + 1),
            )
    finally:
        orchestrator.acelerachat_webhooks = original

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "WEBHOOK_INVALID_PAYLOAD"
