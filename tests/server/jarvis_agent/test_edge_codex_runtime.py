from __future__ import annotations

from typing import Any

from openjarvis.server.jarvis_agent.edge.codex_runtime import CodexEdgeRuntimeProxy


class _Edge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
        return {"data": {"busy": True}}


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
    assert runtime.poll_history_only is True
    assert runtime.history_poll_interval_seconds == 10.0


def test_edge_runtime_subscribe_fails_closed_when_worker_is_offline() -> None:
    edge = _Edge()
    edge.select_connection = lambda _capability: None  # type: ignore[method-assign]
    runtime = CodexEdgeRuntimeProxy(edge)  # type: ignore[arg-type]

    try:
        runtime.thread_subscribe("thread-1")
    except RuntimeError as exc:
        assert str(exc) == "DEVICE_OFFLINE"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("offline Edge must fail closed")
