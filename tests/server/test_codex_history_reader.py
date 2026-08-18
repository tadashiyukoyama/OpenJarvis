from __future__ import annotations

import asyncio
import gc
import threading

import pytest

from openjarvis.integrations.codex_protocol import (
    CodexHistoryMessage,
    CodexThreadHistory,
    CodexThreadHistoryPage,
)
from openjarvis.server.codex_history_reader import (
    CodexHistoryReader,
    CodexHistoryReadTimeout,
)


class _Runtime:
    def __init__(self) -> None:
        self.calls = 0

    def thread_history(self, thread_id: str, *, timeout_seconds: float):
        self.calls += 1
        return {"thread_id": thread_id, "timeout": timeout_seconds}


@pytest.mark.asyncio
async def test_concurrent_consumers_share_one_history_read() -> None:
    runtime = _Runtime()
    reader = CodexHistoryReader(cache_ttl_seconds=2)

    results = await asyncio.gather(
        *(reader.read(runtime, "thread-a") for _ in range(20))
    )

    assert runtime.calls == 1
    assert all(result["thread_id"] == "thread-a" for result in results)


@pytest.mark.asyncio
async def test_stalled_history_read_has_a_bounded_deadline() -> None:
    release = threading.Event()

    class SlowRuntime:
        def thread_history(self, thread_id: str, *, timeout_seconds: float):
            del thread_id, timeout_seconds
            release.wait(1)

    reader = CodexHistoryReader(request_timeout_seconds=0.01)
    try:
        with pytest.raises(CodexHistoryReadTimeout):
            await reader.read(SlowRuntime(), "thread-a")
    finally:
        release.set()


@pytest.mark.asyncio
async def test_invalidation_forces_a_new_canonical_read() -> None:
    runtime = _Runtime()
    reader = CodexHistoryReader(cache_ttl_seconds=60)

    await reader.read(runtime, "thread-a")
    reader.invalidate("thread-a")
    await reader.read(runtime, "thread-a")

    assert runtime.calls == 2


@pytest.mark.asyncio
async def test_paginated_consumers_are_coalesced_by_cursor() -> None:
    class PagedRuntime:
        def __init__(self) -> None:
            self.calls = []

        def thread_history_page(self, thread_id: str, **kwargs):
            self.calls.append((thread_id, kwargs["cursor"]))
            return CodexThreadHistoryPage(
                history=CodexThreadHistory(thread_id=thread_id),
                next_cursor="older" if kwargs["cursor"] is None else None,
            )

    runtime = PagedRuntime()
    reader = CodexHistoryReader(cache_ttl_seconds=60)

    first, duplicate = await asyncio.gather(
        reader.read_page(runtime, "thread-a"),
        reader.read_page(runtime, "thread-a"),
    )
    older = await reader.read_page(runtime, "thread-a", cursor="older")

    assert first is duplicate
    assert older.next_cursor is None
    assert runtime.calls == [("thread-a", None), ("thread-a", "older")]


@pytest.mark.asyncio
async def test_head_page_recovers_messages_omitted_from_active_turn_summary() -> None:
    class ActiveTurnRuntime:
        def __init__(self) -> None:
            self.calls = []

        def thread_history_page(self, thread_id: str, **kwargs):
            self.calls.append((kwargs["limit"], kwargs["items_view"]))
            base = CodexHistoryMessage(
                message_id="user-original",
                role="user",
                content="pedido original",
            )
            messages = (base,)
            if kwargs["items_view"] == "full":
                messages += (
                    CodexHistoryMessage(
                        message_id="user-steering",
                        role="user",
                        content="complemento durante o turno",
                    ),
                )
            return CodexThreadHistoryPage(
                history=CodexThreadHistory(
                    thread_id=thread_id,
                    messages=messages,
                ),
                next_cursor="older",
            )

    runtime = ActiveTurnRuntime()
    page = await CodexHistoryReader(cache_ttl_seconds=0).read_reconciled_page(
        runtime,
        "thread-a",
    )

    assert [message.message_id for message in page.history.messages] == [
        "user-original",
        "user-steering",
    ]
    assert sorted(runtime.calls) == [(1, "full"), (100, "summary")]
    assert page.next_cursor == "older"


@pytest.mark.asyncio
async def test_disconnected_consumer_does_not_leave_unretrieved_failure() -> None:
    started = threading.Event()
    release = threading.Event()

    class FailingRuntime:
        def thread_history(self, thread_id: str, *, timeout_seconds: float):
            del thread_id, timeout_seconds
            started.set()
            release.wait(1)
            raise RuntimeError("history backend failed")

    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    reader = CodexHistoryReader(request_timeout_seconds=1)
    consumer = asyncio.create_task(reader.read(FailingRuntime(), "thread-a"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        shared_read = next(iter(reader._inflight.values()))

        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

        release.set()
        while not shared_read.done():
            await asyncio.sleep(0)
        del shared_read
        gc.collect()
        await asyncio.sleep(0)

        assert unhandled == []
    finally:
        release.set()
        loop.set_exception_handler(previous_handler)
