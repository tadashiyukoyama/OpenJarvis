from __future__ import annotations

from types import SimpleNamespace

import pytest

from openjarvis.agents.codex import (
    CODEX_CONVERSATION_BUSY,
    CODEX_CONVERSATION_THREAD_NOT_FOUND,
    CodexAgentError,
)
from openjarvis.edge_worker.executor import CodexEdgeExecutor
from openjarvis.integrations.codex_conversation import CodexConversationClosed
from openjarvis.integrations.codex_protocol import (
    CodexRequestError,
    CodexRequestTimeout,
)


@pytest.mark.parametrize(
    ("agent_error", "public_error"),
    (
        (CODEX_CONVERSATION_BUSY, "CODEX_BUSY"),
        (CODEX_CONVERSATION_THREAD_NOT_FOUND, "CODEX_THREAD_INVALID"),
    ),
)
def test_delegate_maps_agent_codes_to_the_edge_contract(
    tmp_path, agent_error: str, public_error: str
) -> None:
    class FailingAgent:
        @staticmethod
        def run(command, context):
            del command, context
            raise CodexAgentError(agent_error)

    executor = object.__new__(CodexEdgeExecutor)
    executor._config = SimpleNamespace(project_roots=(str(tmp_path),))

    with pytest.raises(RuntimeError, match=f"^{public_error}$"):
        executor._delegate(
            FailingAgent(),
            {
                "project_cwd": str(tmp_path),
                "thread_id": "thread-1",
                "command": "Diagnosticar sem mutacoes externas.",
            },
            {
                "session_id": "session-1",
                "partition_key": "project::thread-1",
                "request_id": "request-1",
            },
        )


def test_subscribe_uses_selected_thread_without_starting_a_turn() -> None:
    calls: list[tuple[str, float]] = []

    class Runtime:
        @staticmethod
        def thread_subscribe(thread_id: str, *, timeout_seconds: float) -> None:
            calls.append((thread_id, timeout_seconds))

    result = CodexEdgeExecutor._subscribe(  # noqa: SLF001 - contract unit test
        Runtime(), {}, {"codex_thread_id": "thread-1"}
    )

    assert calls == [("thread-1", 10.0)]
    assert result["data"] == {"subscribed": True}
    assert result["references"] == {"thread_id": "thread-1"}


@pytest.mark.parametrize(
    ("failure", "public_error"),
    (
        (CodexRequestTimeout("late"), "CODEX_THREAD_RESUME_TIMEOUT"),
        (
            CodexRequestError(
                "thread thread-1 already has an active writer",
                code=-32600,
            ),
            "CODEX_BUSY",
        ),
        (CodexRequestError("missing", code=-1), "CODEX_THREAD_INVALID"),
        (CodexConversationClosed("closed"), "SESSION_CLOSED"),
    ),
)
def test_subscribe_maps_runtime_failures_to_public_edge_codes(
    failure: Exception,
    public_error: str,
) -> None:
    class Runtime:
        @staticmethod
        def thread_subscribe(thread_id: str, *, timeout_seconds: float) -> None:
            del thread_id, timeout_seconds
            raise failure

    with pytest.raises(RuntimeError, match=f"^{public_error}$"):
        CodexEdgeExecutor._subscribe(  # noqa: SLF001
            Runtime(), {}, {"codex_thread_id": "thread-1"}
        )


def test_desktop_refresh_validates_subscription_before_dispatch(monkeypatch) -> None:
    calls: list[tuple[str, float] | str] = []

    class Runtime:
        @staticmethod
        def thread_subscribe(thread_id: str, *, timeout_seconds: float) -> None:
            calls.append((thread_id, timeout_seconds))

    monkeypatch.setattr(
        "openjarvis.integrations.codex_desktop.open_codex_thread_in_desktop",
        lambda thread_id: calls.append(thread_id) or f"codex://threads/{thread_id}",
    )

    result = CodexEdgeExecutor._desktop_refresh(  # noqa: SLF001
        Runtime(), {"codex_thread_id": "thread-1"}
    )

    assert calls == [("thread-1", 10.0), "thread-1"]
    assert result["data"] == {
        "refreshed": True,
        "uri": "codex://threads/thread-1",
    }


def test_history_is_paginated_and_bounded_by_utf8_bytes() -> None:
    class Runtime:
        received_limit = 0

        @classmethod
        def thread_history_page(cls, thread_id: str, **kwargs):
            assert thread_id == "thread-1"
            cls.received_limit = kwargs["limit"]
            messages = [
                SimpleNamespace(
                    message_id=f"message-{index}",
                    role="assistant",
                    content="á" * 8_000,
                    timestamp=float(index),
                )
                for index in range(100)
            ]
            return SimpleNamespace(
                history=SimpleNamespace(messages=messages),
                next_cursor="next-page",
                backwards_cursor="previous-page",
            )

    result = CodexEdgeExecutor._history(  # noqa: SLF001
        Runtime(), {"limit": 100}, {"codex_thread_id": "thread-1"}
    )

    messages = result["data"]["messages"]
    content_bytes = sum(len(item["content"].encode("utf-8")) for item in messages)
    assert Runtime.received_limit == 30
    assert len(messages) == 30
    assert content_bytes <= 128 * 1024
    assert any(item["content_truncated"] for item in messages)
    assert result["data"]["next_cursor"] == "next-page"
