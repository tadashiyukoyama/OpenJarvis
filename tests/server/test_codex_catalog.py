"""Tests for the Codex project/thread catalog exposed to the UI."""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi.testclient import TestClient
from starlette.requests import Request

from openjarvis.integrations.codex_protocol import (
    CodexConversationEvent,
    CodexHistoryMessage,
    CodexThreadHistory,
    CodexThreadHistoryPage,
    CodexThreadInfo,
    CodexThreadListResult,
)
from openjarvis.server import api_routes
from openjarvis.server.api_routes import (
    _codex_history_event_stream,
    codex_thread_events,
)
from openjarvis.server.app import create_app
from openjarvis.server.codex_history_reader import CodexHistoryReader


class FakeCodexRuntime:
    extra_messages = ()

    def __init__(self) -> None:
        self.callbacks = {}
        self.next_callback = 1
        self.resumed_threads = []

    def thread_resume(self, thread_id, *, timeout_seconds=None):
        assert timeout_seconds is None or timeout_seconds > 0
        self.resumed_threads.append(thread_id)

    def thread_subscribe(self, thread_id, *, timeout_seconds=None):
        assert timeout_seconds is None or timeout_seconds > 0
        self.resumed_threads.append(thread_id)
        return CodexThreadInfo(thread_id=thread_id, status="idle")

    def subscribe_events(self, callback):
        token = self.next_callback
        self.next_callback += 1
        self.callbacks[token] = callback
        return token

    def unsubscribe_events(self, token):
        return self.callbacks.pop(token, None) is not None

    def emit(self, event):
        for callback in tuple(self.callbacks.values()):
            callback(event)

    def thread_history(self, thread_id, *, timeout_seconds=None):
        assert timeout_seconds is None or timeout_seconds > 0
        return CodexThreadHistory(
            thread_id=thread_id,
            messages=(
                CodexHistoryMessage(
                    message_id="user-1",
                    role="user",
                    content="ola",
                    timestamp=100.0,
                ),
                CodexHistoryMessage(
                    message_id="assistant-1",
                    role="assistant",
                    content="resposta",
                    timestamp=100.0,
                ),
            )
            + self.extra_messages,
        )

    def thread_history_page(
        self,
        thread_id,
        *,
        cursor=None,
        limit=100,
        items_view="summary",
        timeout_seconds=None,
    ):
        assert cursor is None
        assert (limit, items_view) in {(100, "summary"), (1, "full")}
        return CodexThreadHistoryPage(
            history=self.thread_history(thread_id, timeout_seconds=timeout_seconds)
        )

    def thread_list(self, *, cursor=None, limit=None):
        assert cursor is None
        assert limit == 100
        return CodexThreadListResult(
            threads=(
                CodexThreadInfo(
                    thread_id="thread-a",
                    cwd="D:\\dev\\workspaces\\openjarvis",
                    status="idle",
                    metadata={
                        "name": "Execute fase OJ0",
                        "preview": "Execute fase OJ0",
                        "updatedAt": 10,
                    },
                ),
                CodexThreadInfo(
                    thread_id="thread-b",
                    cwd="D:\\dev\\workspaces\\openjarvis",
                    status="idle",
                    metadata={"preview": "ola", "updatedAt": 20},
                ),
            ),
            next_cursor=None,
        )


def test_codex_catalog_groups_threads_by_project() -> None:
    app = create_app(
        None,
        "codex",
        codex_runtime=FakeCodexRuntime(),
    )

    response = TestClient(app).get("/v1/codex/catalog")

    assert response.status_code == 200
    assert response.json() == {
        "projects": [
            {
                "cwd": "D:\\dev\\workspaces\\openjarvis",
                "name": "openjarvis",
                "threads": [
                    {
                        "thread_id": "thread-b",
                        "project_cwd": "D:\\dev\\workspaces\\openjarvis",
                        "project_name": "openjarvis",
                        "name": "ola",
                        "preview": "ola",
                        "status": "idle",
                        "updated_at": 20,
                    },
                    {
                        "thread_id": "thread-a",
                        "project_cwd": "D:\\dev\\workspaces\\openjarvis",
                        "project_name": "openjarvis",
                        "name": "Execute fase OJ0",
                        "preview": "Execute fase OJ0",
                        "status": "idle",
                        "updated_at": 10,
                    },
                ],
            }
        ]
    }


def test_codex_thread_history_returns_public_messages() -> None:
    app = create_app(
        None,
        "codex",
        codex_runtime=FakeCodexRuntime(),
    )

    response = TestClient(app).get("/v1/codex/threads/thread-a/history")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-a",
        "messages": [
            {
                "message_id": "user-1",
                "role": "user",
                "content": "ola",
                "timestamp": 100.0,
            },
            {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "resposta",
                "timestamp": 100.0,
            },
        ],
        "complete": True,
        "next_cursor": None,
    }


def test_codex_thread_history_accepts_a_bounded_pagination_cursor() -> None:
    class PaginatedRuntime(FakeCodexRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.requested_cursors = []

        def thread_history_page(
            self,
            thread_id,
            *,
            cursor=None,
            limit=100,
            items_view="summary",
            timeout_seconds=None,
        ):
            self.requested_cursors.append(cursor)
            assert cursor == "older-page"
            assert (limit, items_view) == (100, "summary")
            return CodexThreadHistoryPage(
                history=CodexThreadHistory(
                    thread_id=thread_id,
                    messages=(
                        CodexHistoryMessage(
                            message_id="older-user",
                            role="user",
                            content="older",
                            timestamp=50.0,
                        ),
                    ),
                )
            )

    runtime = PaginatedRuntime()
    app = create_app(None, "codex", codex_runtime=runtime)

    response = TestClient(app).get(
        "/v1/codex/threads/thread-a/history?cursor=older-page"
    )

    assert response.status_code == 200
    assert response.json()["messages"][0]["message_id"] == "older-user"
    assert runtime.requested_cursors == ["older-page"]


def test_codex_desktop_refresh_requires_local_action_header(monkeypatch) -> None:
    monkeypatch.setattr(api_routes, "_is_loopback_request", lambda _request: True)
    app = create_app(None, "codex", codex_runtime=FakeCodexRuntime())

    response = TestClient(app).post("/v1/codex/threads/thread-a/desktop-refresh")

    assert response.status_code == 403
    assert response.json() == {"detail": "Desktop refresh is not authorized"}


def test_codex_desktop_refresh_requires_loopback(monkeypatch) -> None:
    monkeypatch.setattr(api_routes, "_is_loopback_request", lambda _request: False)
    app = create_app(None, "codex", codex_runtime=FakeCodexRuntime())

    response = TestClient(app).post(
        "/v1/codex/threads/thread-a/desktop-refresh",
        headers={"X-OpenJarvis-Local-Action": "codex-desktop-refresh"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Desktop refresh requires loopback"}


def test_codex_desktop_refresh_validates_thread_and_dispatches(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(api_routes, "_is_loopback_request", lambda _request: True)
    monkeypatch.setattr(
        "openjarvis.integrations.codex_desktop.open_codex_thread_in_desktop",
        lambda thread_id: opened.append(thread_id) or f"codex://threads/{thread_id}",
    )
    app = create_app(None, "codex", codex_runtime=FakeCodexRuntime())
    client = TestClient(app)

    response = client.post(
        "/v1/codex/threads/thread-a/desktop-refresh",
        headers={"X-OpenJarvis-Local-Action": "codex-desktop-refresh"},
    )
    invalid = client.post(
        "/v1/codex/threads/bad:thread/desktop-refresh",
        headers={"X-OpenJarvis-Local-Action": "codex-desktop-refresh"},
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "thread_id": "thread-a",
        "uri": "codex://threads/thread-a",
    }
    assert opened == ["thread-a"]
    assert invalid.status_code == 400
    assert invalid.json() == {"detail": "Invalid Codex thread identifier"}


def test_codex_thread_events_starts_with_canonical_snapshot() -> None:
    app = create_app(
        None,
        "codex",
        codex_runtime=FakeCodexRuntime(),
    )

    async def receive_request():
        return {"type": "http.request"}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/codex/threads/thread-a/events",
            "headers": [],
            "app": app,
        },
        receive=receive_request,
    )

    async def read_initial_events():
        response = await codex_thread_events("thread-a", request)
        connecting = await anext(response.body_iterator)
        live = await anext(response.body_iterator)
        snapshot = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return response, connecting, live, snapshot

    response, connecting_chunk, live_chunk, snapshot_chunk = asyncio.run(
        read_initial_events()
    )
    connecting_text = (
        connecting_chunk.decode()
        if isinstance(connecting_chunk, bytes)
        else connecting_chunk
    )
    live_text = live_chunk.decode() if isinstance(live_chunk, bytes) else live_chunk
    text = (
        snapshot_chunk.decode() if isinstance(snapshot_chunk, bytes) else snapshot_chunk
    )
    lines = text.splitlines()
    event_id = next(line[4:] for line in lines if line.startswith("id: "))
    payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: status" in connecting_text
    assert '"state":"connecting"' in connecting_text
    assert '"state":"live"' in live_text
    assert lines[1] == "event: snapshot"
    assert len(event_id) == 64
    assert payload["revision"] == event_id
    assert payload["thread_id"] == "thread-a"
    assert app.state.codex_runtime.resumed_threads == ["thread-a"]
    assert [message["message_id"] for message in payload["messages"]] == [
        "user-1",
        "assistant-1",
    ]


def test_codex_thread_events_requires_runtime() -> None:
    app = create_app(None, "codex")

    response = TestClient(app).get("/v1/codex/threads/thread-a/events")

    assert response.status_code == 503
    assert response.json() == {"detail": "Codex synchronization is not available"}


def test_codex_thread_events_emits_only_changed_snapshot() -> None:
    runtime = FakeCodexRuntime()
    initial = runtime.thread_history("thread-a")

    class ConnectedRequest:
        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def read_two_events():
        stream = _codex_history_event_stream(
            runtime,
            "thread-a",
            ConnectedRequest(),
            CodexHistoryReader(cache_ttl_seconds=0),
            initial,
            poll_seconds=0,
            heartbeat_seconds=60,
        )
        await anext(stream)  # connecting
        first = await anext(stream)  # supplied canonical snapshot
        runtime.extra_messages = (
            CodexHistoryMessage(
                message_id="user-2",
                role="user",
                content="nova mensagem",
                timestamp=101.0,
            ),
        )
        runtime.emit(
            CodexConversationEvent(
                method="turn/completed",
                thread_id="thread-a",
                turn_id="turn-2",
                event_type="turn_completed",
            )
        )
        second = ""
        for _ in range(8):
            candidate = await anext(stream)
            if "event: snapshot" in candidate and "nova mensagem" in candidate:
                second = candidate
                break
        await stream.aclose()
        return first, second

    first, second = asyncio.run(read_two_events())

    first_id = next(line[4:] for line in first.splitlines() if line.startswith("id: "))
    second_id = next(
        line[4:] for line in second.splitlines() if line.startswith("id: ")
    )
    second_payload = json.loads(
        next(line[6:] for line in second.splitlines() if line.startswith("data: "))
    )
    assert first_id != second_id
    assert [message["message_id"] for message in second_payload["messages"]] == [
        "user-1",
        "assistant-1",
        "user-2",
    ]


def test_codex_thread_events_broadcasts_live_text_delta() -> None:
    runtime = FakeCodexRuntime()
    initial = runtime.thread_history("thread-a")

    class ConnectedRequest:
        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def read_delta():
        stream = _codex_history_event_stream(
            runtime,
            "thread-a",
            ConnectedRequest(),
            CodexHistoryReader(cache_ttl_seconds=0),
            initial,
            poll_seconds=60,
            heartbeat_seconds=60,
        )
        await anext(stream)  # connecting
        runtime.emit(
            CodexConversationEvent(
                method="item/agentMessage/delta",
                thread_id="thread-a",
                turn_id="turn-live",
                event_type="text_delta",
                public_text_delta="token",
            )
        )
        delta = ""
        for _ in range(8):
            candidate = await anext(stream)
            if "event: delta" in candidate:
                delta = candidate
                break
        await stream.aclose()
        return delta

    delta = asyncio.run(read_delta())

    assert "event: delta" in delta
    payload = json.loads(
        next(line[6:] for line in delta.splitlines() if line.startswith("data: "))
    )
    assert payload == {
        "thread_id": "thread-a",
        "turn_id": "turn-live",
        "delta": "token",
    }
    assert runtime.callbacks == {}


def test_codex_thread_events_broadcasts_canonical_public_message() -> None:
    runtime = FakeCodexRuntime()

    class ConnectedRequest:
        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def read_message():
        stream = _codex_history_event_stream(
            runtime,
            "thread-a",
            ConnectedRequest(),
            CodexHistoryReader(cache_ttl_seconds=0),
            None,
            poll_seconds=60,
            heartbeat_seconds=60,
        )
        await anext(stream)  # connecting
        runtime.emit(
            CodexConversationEvent(
                method="item/started",
                thread_id="thread-a",
                turn_id="turn-live",
                item_id="user-live",
                event_type="item_started",
                public_message=CodexHistoryMessage(
                    message_id="user-live",
                    role="user",
                    content="mensagem ao vivo",
                    timestamp=200.0,
                ),
            )
        )
        message = ""
        for _ in range(8):
            candidate = await anext(stream)
            if "event: message" in candidate:
                message = candidate
                break
        await stream.aclose()
        return message

    message = asyncio.run(read_message())
    payload = json.loads(
        next(line[6:] for line in message.splitlines() if line.startswith("data: "))
    )

    assert payload == {
        "thread_id": "thread-a",
        "turn_id": "turn-live",
        "message": {
            "message_id": "user-live",
            "role": "user",
            "content": "mensagem ao vivo",
            "timestamp": 200.0,
        },
    }
    assert runtime.callbacks == {}


def test_codex_thread_events_does_not_roll_back_a_live_message_with_slow_history() -> (
    None
):
    class SlowHistoryRuntime(FakeCodexRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.history_started = threading.Event()
            self.release_history = threading.Event()

        def thread_history_page(self, thread_id, **kwargs):
            self.history_started.set()
            assert self.release_history.wait(timeout=2)
            return super().thread_history_page(thread_id, **kwargs)

    runtime = SlowHistoryRuntime()

    class ConnectedRequest:
        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def read_live_then_snapshot():
        stream = _codex_history_event_stream(
            runtime,
            "thread-a",
            ConnectedRequest(),
            CodexHistoryReader(cache_ttl_seconds=0),
            None,
            poll_seconds=60,
            heartbeat_seconds=60,
        )
        await anext(stream)  # connecting
        await anext(stream)  # live
        next_chunk = asyncio.create_task(anext(stream))
        assert await asyncio.to_thread(runtime.history_started.wait, 1)
        runtime.emit(
            CodexConversationEvent(
                method="item/completed",
                thread_id="thread-a",
                turn_id="turn-live",
                item_id="assistant-live",
                event_type="item_completed",
                public_message=CodexHistoryMessage(
                    message_id="assistant-live",
                    role="assistant",
                    content="resposta mais nova",
                    timestamp=300.0,
                ),
            )
        )
        message = await asyncio.wait_for(next_chunk, timeout=1)
        runtime.release_history.set()
        snapshot = ""
        for _ in range(4):
            candidate = await asyncio.wait_for(anext(stream), timeout=1)
            if "event: snapshot" in candidate:
                snapshot = candidate
                break
        await stream.aclose()
        return message, snapshot

    message, snapshot = asyncio.run(read_live_then_snapshot())

    assert "event: message" in message
    payload = json.loads(
        next(line[6:] for line in snapshot.splitlines() if line.startswith("data: "))
    )
    assert payload["messages"][-1] == {
        "message_id": "assistant-live",
        "role": "assistant",
        "content": "resposta mais nova",
        "timestamp": 300.0,
    }


def test_codex_thread_events_keeps_stream_open_when_history_is_slow() -> None:
    class UnavailableHistoryRuntime(FakeCodexRuntime):
        def thread_history_page(self, thread_id, **kwargs):
            del thread_id, kwargs
            raise TimeoutError("history unavailable while Desktop task is active")

    runtime = UnavailableHistoryRuntime()

    class ConnectedRequest:
        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def read_status_and_delta():
        stream = _codex_history_event_stream(
            runtime,
            "thread-a",
            ConnectedRequest(),
            CodexHistoryReader(request_timeout_seconds=0.1, cache_ttl_seconds=0),
            None,
            poll_seconds=0.01,
            heartbeat_seconds=60,
        )
        connecting = await anext(stream)
        live = await anext(stream)
        degraded = await anext(stream)
        runtime.emit(
            CodexConversationEvent(
                method="item/agentMessage/delta",
                thread_id="thread-a",
                turn_id="turn-live",
                event_type="text_delta",
                public_text_delta="token after timeout",
            )
        )
        delta = await asyncio.wait_for(anext(stream), timeout=0.5)
        await stream.aclose()
        return connecting, live, degraded, delta

    connecting, live, degraded, delta = asyncio.run(read_status_and_delta())

    assert "event: status" in connecting
    assert '"state":"connecting"' in connecting
    assert '"state":"live"' in live
    assert "event: status" in degraded
    assert '"state":"degraded"' in degraded
    assert "event: error" not in degraded
    assert "event: delta" in delta
    assert "token after timeout" in delta
    assert runtime.resumed_threads == ["thread-a"]
    assert runtime.callbacks == {}
