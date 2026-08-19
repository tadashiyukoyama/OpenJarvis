from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.codex_turn_dispatch import router


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure: BaseException | None = None

    def start_turn(self, thread_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"thread_id": thread_id, **kwargs})
        if self.failure is not None:
            raise self.failure
        return {"status": "completed", "summary": "Resposta canônica."}


def _app(runtime: Any | None) -> FastAPI:
    app = FastAPI()
    app.state.codex_runtime = runtime
    app.include_router(router)
    return app


def _payload() -> dict[str, str]:
    return {
        "project_cwd": r"D:\dev\workspaces\openjarvis",
        "message": "Faça a auditoria.",
        "client_user_message_id": "message-1",
        "conversation_id": "conversation-1",
    }


def test_codex_turn_streams_real_result_and_exact_identity() -> None:
    runtime = _Runtime()
    with TestClient(_app(runtime)) as client:
        response = client.post("/v1/codex/threads/thread-1/turns", json=_payload())

    assert response.status_code == 200
    assert "event: agent_turn_start" in response.text
    assert "Resposta canônica." in response.text
    assert response.text.endswith("data: [DONE]\n\n")
    assert runtime.calls == [
        {
            "thread_id": "thread-1",
            "project_cwd": r"D:\dev\workspaces\openjarvis",
            "command": "Faça a auditoria.",
            "request_id": "message-1",
            "conversation_id": "conversation-1",
        }
    ]


def test_codex_turn_returns_stable_sse_error_without_internal_details() -> None:
    runtime = _Runtime()
    runtime.failure = RuntimeError("private stack detail")
    with TestClient(_app(runtime)) as client:
        response = client.post("/v1/codex/threads/thread-1/turns", json=_payload())

    assert response.status_code == 200
    assert '"code":"EXTERNAL_RESULT_UNKNOWN"' in response.text
    assert "private stack detail" not in response.text


def test_codex_turn_fails_closed_without_runtime_or_valid_contract() -> None:
    with TestClient(_app(None)) as client:
        unavailable = client.post(
            "/v1/codex/threads/thread-1/turns", json=_payload()
        )
        invalid = client.post(
            "/v1/codex/threads/invalid%20thread/turns", json=_payload()
        )
        extra = client.post(
            "/v1/codex/threads/thread-1/turns",
            json={**_payload(), "source_id": "forbidden"},
        )

    assert unavailable.status_code == 503
    assert invalid.status_code == 422
    assert extra.status_code == 422
