from __future__ import annotations

from typing import Any

from openjarvis.server.jarvis_agent.edge.codex_runtime import CodexEdgeRuntimeProxy


class _Edge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.subscriptions: dict[int, Any] = {}
        self.next_subscription = 1

    def select_connection(self, capability: str) -> object | None:
        return object() if capability == "codex.history" else None

    def execute_job(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs["tool_id"] == "codex.catalog":
            return {
                "data": {
                    "threads": [
                        {
                            "thread_id": "thread-1",
                            "cwd": r"D:\dev\one",
                            "status": "idle",
                            "metadata": {"name": "One"},
                        },
                        {
                            "thread_id": "thread-2",
                            "cwd": r"D:\dev\two",
                            "status": "active",
                            "metadata": {"name": "Two"},
                        },
                    ]
                }
            }
        if kwargs["tool_id"] == "codex.history":
            return {
                "data": {
                    "messages": [
                        {
                            "message_id": "item-1",
                            "role": "user",
                            "content": "olá",
                            "timestamp": 10.0,
                        }
                    ],
                    "next_cursor": "older",
                    "backwards_cursor": None,
                }
            }
        if kwargs["tool_id"] == "codex.subscribe":
            return {"data": {"subscribed": True}}
        if kwargs["tool_id"] == "codex.desktop_refresh":
            return {
                "data": {
                    "refreshed": True,
                    "uri": "codex://threads/thread-1",
                }
            }
        return {"data": {"busy": True}}

    def subscribe_codex_events(self, callback: Any) -> int:
        token = self.next_subscription
        self.next_subscription += 1
        self.subscriptions[token] = callback
        return token

    def unsubscribe_codex_events(self, token: int) -> bool:
        return self.subscriptions.pop(token, None) is not None


def test_edge_runtime_pages_cached_catalog_and_maps_history() -> None:
    edge = _Edge()
    runtime = CodexEdgeRuntimeProxy(edge, catalog_ttl_seconds=60)  # type: ignore[arg-type]

    first = runtime.thread_list(limit=1)
    second = runtime.thread_list(cursor=first.next_cursor, limit=1)
    history = runtime.thread_history_page(
        "thread-1", cursor="older", limit=12, items_view="full"
    )

    assert [item.thread_id for item in first.threads] == ["thread-1"]
    assert [item.thread_id for item in second.threads] == ["thread-2"]
    assert len([call for call in edge.calls if call["tool_id"] == "codex.catalog"]) == 1
    assert history.history.messages[0].message_id == "item-1"
    assert history.next_cursor == "older"
    history_call = next(
        call for call in edge.calls if call["tool_id"] == "codex.history"
    )
    assert history_call["arguments"] == {
        "limit": 12,
        "cursor": "older",
        "items_view": "full",
    }
    assert history_call["context"]["codex_thread_id"] == "thread-1"
    assert runtime.poll_history_only is False


def test_edge_runtime_subscribe_fails_closed_when_worker_is_offline() -> None:
    edge = _Edge()
    edge.execute_job = lambda **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("DEVICE_OFFLINE")
    )
    runtime = CodexEdgeRuntimeProxy(edge)  # type: ignore[arg-type]

    try:
        runtime.thread_subscribe("thread-1")
    except RuntimeError as exc:
        assert str(exc) == "DEVICE_OFFLINE"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("offline Edge must fail closed")


def test_edge_runtime_subscribes_maps_and_unsubscribes_live_events() -> None:
    edge = _Edge()
    runtime = CodexEdgeRuntimeProxy(edge)  # type: ignore[arg-type]
    received = []

    assert runtime.thread_subscribe("thread-1") == {"thread_id": "thread-1"}
    subscribe_call = edge.calls[-1]
    assert subscribe_call["arguments"] == {"timeout_seconds": 10.0}
    token = runtime.subscribe_events(received.append)
    next(iter(edge.subscriptions.values()))(
        {
            "method": "turn/completed",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "event_type": "turn_completed",
            "terminal_status": "COMPLETED",
            "public_message": {
                "message_id": "message-1",
                "role": "assistant",
                "content": "Concluído.",
                "timestamp": 15.0,
            },
            "metadata": {},
        }
    )

    assert received[0].thread_id == "thread-1"
    assert received[0].public_message.content == "Concluído."
    assert received[0].terminal_status.value == "COMPLETED"
    assert runtime.unsubscribe_events(token) is True
    assert edge.subscriptions == {}


def test_edge_runtime_dispatches_desktop_refresh_on_the_windows_worker() -> None:
    edge = _Edge()
    runtime = CodexEdgeRuntimeProxy(edge)  # type: ignore[arg-type]

    assert runtime.desktop_refresh("thread-1") == "codex://threads/thread-1"
    call = edge.calls[-1]
    assert call["tool_id"] == "codex.desktop_refresh"
    assert call["capability"] == "codex.desktop_refresh"
    assert call["context"]["codex_thread_id"] == "thread-1"


def test_edge_runtime_dispatches_idempotent_turn_to_exact_thread() -> None:
    edge = _Edge()
    edge.execute_job = lambda **kwargs: (  # type: ignore[method-assign]
        edge.calls.append(kwargs)
        or {"status": "completed", "summary": "Resposta real."}
    )
    runtime = CodexEdgeRuntimeProxy(edge)  # type: ignore[arg-type]

    result = runtime.start_turn(
        "thread-1",
        project_cwd=r"D:\dev\one",
        command="Execute a auditoria.",
        request_id="message-1",
        conversation_id="conversation-1",
    )
    first = edge.calls[-1]
    runtime.start_turn(
        "thread-1",
        project_cwd=r"D:\dev\one",
        command="Execute a auditoria.",
        request_id="message-1",
        conversation_id="conversation-1",
    )
    second = edge.calls[-1]

    assert result["summary"] == "Resposta real."
    assert first["tool_id"] == "codex.delegate"
    assert first["capability"] == "codex.delegate"
    assert first["arguments"] == {
        "project_cwd": r"D:\dev\one",
        "thread_id": "thread-1",
        "command": "Execute a auditoria.",
    }
    assert first["context"]["codex_thread_id"] == "thread-1"
    assert first["context"]["request_id"] == "message-1"
    assert first["job_id"] == second["job_id"]
    assert first["payload_hash"] == second["payload_hash"]
