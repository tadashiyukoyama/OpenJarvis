"""Gemini Live token provisioning and safe failover policy tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from openjarvis.server.app import create_app
from openjarvis.server.gemini_live import (
    FALLBACK_KEY_ENV,
    HOME_ENV,
    PRIMARY_KEY_ENV,
    GeminiLiveProvisioningError,
    GeminiLiveTokenBroker,
)
from openjarvis.server.jarvis_operational_log import JarvisOperationalLogStore


def _client_with_broker(
    broker: GeminiLiveTokenBroker,
    *,
    operational_log: JarvisOperationalLogStore | None = None,
) -> TestClient:
    app = create_app(None, "codex")
    app.state.gemini_live_token_broker = broker
    if operational_log is not None:
        app.state.jarvis_operational_log = operational_log
    return TestClient(app)


def test_status_never_exposes_credentials() -> None:
    broker = GeminiLiveTokenBroker()
    with patch.dict(
        "os.environ",
        {PRIMARY_KEY_ENV: "primary-secret", FALLBACK_KEY_ENV: "fallback-secret"},
        clear=False,
    ):
        response = _client_with_broker(broker).get("/v1/jarvis/live/status")

    assert response.status_code == 200
    assert response.json()["primary_configured"] is True
    assert response.json()["fallback_configured"] is True
    assert "primary-secret" not in response.text
    assert "fallback-secret" not in response.text


@pytest.mark.asyncio
async def test_primary_credential_mints_single_use_token() -> None:
    calls: list[tuple[str, dict]] = []

    async def requester(key: str, payload: dict) -> dict:
        calls.append((key, payload))
        return {"name": "ephemeral-primary"}

    broker = GeminiLiveTokenBroker(requester=requester)
    with patch.dict("os.environ", {PRIMARY_KEY_ENV: "primary-secret"}, clear=False):
        token = await broker.create_token()

    assert token.token == "ephemeral-primary"
    assert token.slot == "primary"
    assert calls[0][0] == "primary-secret"
    assert calls[0][1]["uses"] == 1


@pytest.mark.asyncio
async def test_auth_failure_uses_technical_fallback() -> None:
    calls: list[str] = []

    async def requester(key: str, payload: dict) -> dict:
        calls.append(key)
        if key == "primary-secret":
            raise GeminiLiveProvisioningError("refused", kind="auth", status_code=403)
        return {"name": "ephemeral-fallback"}

    broker = GeminiLiveTokenBroker(requester=requester)
    with patch.dict(
        "os.environ",
        {PRIMARY_KEY_ENV: "primary-secret", FALLBACK_KEY_ENV: "fallback-secret"},
        clear=False,
    ):
        token = await broker.create_token()

    assert token.slot == "fallback"
    assert token.token == "ephemeral-fallback"
    assert calls == ["primary-secret", "fallback-secret"]


@pytest.mark.asyncio
async def test_quota_failure_never_rotates_to_fallback() -> None:
    calls: list[str] = []

    async def requester(key: str, payload: dict) -> dict:
        calls.append(key)
        raise GeminiLiveProvisioningError(
            "quota", kind="quota", status_code=429, retry_after_seconds=30
        )

    broker = GeminiLiveTokenBroker(requester=requester)
    with patch.dict(
        "os.environ",
        {PRIMARY_KEY_ENV: "primary-secret", FALLBACK_KEY_ENV: "fallback-secret"},
        clear=False,
    ):
        with pytest.raises(GeminiLiveProvisioningError) as caught:
            await broker.create_token()

    assert caught.value.kind == "quota"
    assert calls == ["primary-secret"]


def test_quota_response_marks_command_preserved() -> None:
    class QuotaBroker:
        async def create_token(self):
            raise GeminiLiveProvisioningError(
                "quota reached",
                kind="quota",
                status_code=429,
                retry_after_seconds=12,
            )

        def status(self):
            return {}

    response = _client_with_broker(QuotaBroker()).post("/v1/jarvis/live/token")

    assert response.status_code == 429
    assert response.json()["detail"] == {
        "message": "quota reached",
        "kind": "quota",
        "command_preserved": True,
        "retry_after_seconds": 12,
    }


def test_operational_log_is_durable_idempotent_and_sanitized(tmp_path) -> None:
    database_path = tmp_path / "jarvis" / "events.sqlite3"
    store = JarvisOperationalLogStore(database_path)
    client = _client_with_broker(GeminiLiveTokenBroker(), operational_log=store)
    payload = {
        "event_id": "event-1",
        "thread_id": "thread-a",
        "project_cwd": "D:\\dev\\workspaces\\openjarvis",
        "event_type": "codex",
        "text": f"Enviado com token={'AQ.' + ('a' * 40)}",
        "occurred_at": 1_000,
    }

    first = client.post("/v1/jarvis/live/events", json=payload)
    duplicate = client.post("/v1/jarvis/live/events", json=payload)
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert "AQ." not in first.text
    assert "[credencial omitida]" in first.text
    store.close()

    reopened = JarvisOperationalLogStore(database_path)
    second_client = _client_with_broker(
        GeminiLiveTokenBroker(), operational_log=reopened
    )
    response = second_client.get(
        "/v1/jarvis/live/events", params={"thread_id": "thread-a", "limit": 20}
    )
    assert response.status_code == 200
    assert response.json()["events"] == [first.json()]
    reopened.close()


def test_operational_log_is_scoped_to_selected_thread(tmp_path) -> None:
    store = JarvisOperationalLogStore(tmp_path / "events.sqlite3")
    client = _client_with_broker(GeminiLiveTokenBroker(), operational_log=store)
    for thread_id in ("thread-a", "thread-b"):
        response = client.post(
            "/v1/jarvis/live/events",
            json={
                "event_id": f"event-{thread_id}",
                "thread_id": thread_id,
                "project_cwd": "D:\\repo",
                "event_type": "system",
                "text": f"evento {thread_id}",
                "occurred_at": 2_000,
            },
        )
        assert response.status_code == 200

    response = client.get("/v1/jarvis/live/events", params={"thread_id": "thread-a"})
    assert [event["thread_id"] for event in response.json()["events"]] == ["thread-a"]
    store.close()


def test_operational_log_uses_persistent_openjarvis_home(tmp_path) -> None:
    database_path = tmp_path / "operational-events.sqlite3"
    with patch.dict("os.environ", {HOME_ENV: str(tmp_path)}, clear=False):
        client = _client_with_broker(GeminiLiveTokenBroker())
        response = client.post(
            "/v1/jarvis/live/events",
            json={
                "event_id": "home-event",
                "thread_id": "thread-home",
                "project_cwd": "D:\\repo",
                "event_type": "dispatch",
                "text": "codex.delegate · approval_required",
                "occurred_at": 3_000,
            },
        )
        assert response.status_code == 200
        client.app.state.jarvis_operational_log.close()

    assert database_path.is_file()
    reopened = JarvisOperationalLogStore(database_path)
    assert [event.event_id for event in reopened.list("thread-home")] == ["home-event"]
    reopened.close()


def _client_diagnostic(session_id: str, sequence: int) -> dict:
    return {
        "schema_version": "1.0",
        "session_id": session_id,
        "sequence": sequence,
        "occurred_at": 1_000 + sequence,
        "voice_state": "speaking",
        "socket_state": 1,
        "transport": "worklet",
        "transport_reason": "audio-worklet-active",
        "audio_context_state": "running",
        "audio_context_sample_rate": 48_000,
        "base_latency_ms": 10,
        "output_latency_ms": 20,
        "audio_chunks": sequence,
        "audio_bytes": sequence * 4_800,
        "last_chunk_gap_ms": 40,
        "max_chunk_gap_ms": 80,
        "chunk_gaps_over_250_ms": 0,
        "message_queue_max_delay_ms": 3,
        "queued_ms": 240,
        "prebuffer_ms": 180,
        "underruns": 0,
        "dropped_samples": 0,
        "interruptions": 0,
        "go_away_events": 0,
        "websocket_buffered_amount": 0,
    }


def test_client_audio_diagnostics_are_bounded_scoped_and_content_free() -> None:
    client = _client_with_broker(GeminiLiveTokenBroker())
    for session_id, sequence in (("session-a", 1), ("session-b", 1), ("session-a", 2)):
        response = client.post(
            "/v1/jarvis/live/diagnostics",
            json=_client_diagnostic(session_id, sequence),
        )
        assert response.status_code == 202

    response = client.get(
        "/v1/jarvis/live/diagnostics",
        params={"session_id": "session-a", "limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True
    assert [record["sequence"] for record in body["records"]] == [2]
    assert "received_at" in body["records"][0]
    assert "transcript" not in response.text
    assert "token" not in response.text


def test_client_audio_diagnostics_reject_content_and_invalid_values() -> None:
    client = _client_with_broker(GeminiLiveTokenBroker())
    payload = _client_diagnostic("session-a", 1)
    payload["transcript"] = "conteúdo proibido"
    assert client.post("/v1/jarvis/live/diagnostics", json=payload).status_code == 422

    invalid = _client_diagnostic("session-a", 1)
    invalid["underruns"] = -1
    assert client.post("/v1/jarvis/live/diagnostics", json=invalid).status_code == 422
