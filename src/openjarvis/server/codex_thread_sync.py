"""Live, paginated synchronization of one public Codex conversation.

The Codex app-server only forwards events from a Desktop-owned task after the
client rejoins it. Rejoining with ``excludeTurns`` is fast and does not load the
conversation. Public history is then reconciled through bounded
``thread/turns/list`` pages while live notifications remain the primary path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any

from openjarvis.integrations.codex_protocol import CodexThreadHistory
from openjarvis.server.codex_history_reader import CodexHistoryReader
from openjarvis.server.codex_sync_events import (
    HISTORY_PAGE_LIMIT,
    MAX_INITIAL_HISTORY_PAGES,
    SUBSCRIBE_TIMEOUT_SECONDS,
    codex_execution_payload,
    history_snapshot,
    merge_public_messages,
    public_event_is_relevant,
    sse_event,
    status_event,
)

logger = logging.getLogger(__name__)


async def stream_codex_thread_updates(
    runtime: Any,
    thread_id: str,
    request: Any,
    history_reader: CodexHistoryReader,
    initial_history: Any | None = None,
    *,
    poll_seconds: float = 2.0,
    heartbeat_seconds: float = 15.0,
    max_retry_seconds: float = 10.0,
):
    """Emit live public messages plus incrementally reconciled history."""

    event_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
    loop = asyncio.get_running_loop()

    def receive_event(event: Any) -> None:
        if not public_event_is_relevant(event, thread_id):
            return

        def enqueue() -> None:
            if event_queue.full():
                with suppress(asyncio.QueueEmpty):
                    event_queue.get_nowait()
            with suppress(asyncio.QueueFull):
                event_queue.put_nowait(event)

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(enqueue)

    subscribe_events = getattr(runtime, "subscribe_events", None)
    unsubscribe_events = getattr(runtime, "unsubscribe_events", None)
    event_token = (
        subscribe_events(receive_event) if callable(subscribe_events) else None
    )

    event_task: asyncio.Task[Any] | None = None
    subscribe_task: asyncio.Task[Any] | None = None
    history_task: asyncio.Task[Any] | None = None
    subscription_live = False
    retry_seconds = max(0.05, poll_seconds)
    next_subscribe_at = time.monotonic()
    next_history_at = float("inf")
    history_cursor: str | None = None
    accumulated_messages: tuple[Any, ...] = ()
    live_messages: dict[str, Any] = {}
    pages_loaded = 0
    refresh_requested = False
    refresh_only = False
    revision: str | None = None
    last_emit = time.monotonic()
    poll_history_only = bool(getattr(runtime, "poll_history_only", False))

    try:
        yield status_event(thread_id, "connecting")
        last_emit = time.monotonic()
        if initial_history is not None:
            payload, revision = history_snapshot(
                initial_history,
                complete=True,
                next_cursor=None,
            )
            payload["revision"] = revision
            yield sse_event("snapshot", payload, revision)
            last_emit = time.monotonic()

        event_task = asyncio.create_task(event_queue.get(), name="codex-sync-event")

        while True:
            if await request.is_disconnected():
                return

            now = time.monotonic()
            if (
                not subscription_live
                and subscribe_task is None
                and now >= next_subscribe_at
            ):
                thread_subscribe = getattr(runtime, "thread_subscribe", None)
                if not callable(thread_subscribe):
                    raise RuntimeError(
                        "Codex runtime cannot subscribe to Desktop tasks"
                    )
                subscribe_task = asyncio.create_task(
                    asyncio.to_thread(
                        thread_subscribe,
                        thread_id,
                        timeout_seconds=SUBSCRIBE_TIMEOUT_SECONDS,
                    ),
                    name=f"codex-live-subscribe-{thread_id[:24]}",
                )

            if refresh_requested and history_task is None:
                history_reader.invalidate(thread_id)
                history_cursor = None
                accumulated_messages = ()
                pages_loaded = 0
                refresh_only = True
                refresh_requested = False
                next_history_at = now

            if subscription_live and history_task is None and now >= next_history_at:
                page_reader = (
                    history_reader.read_reconciled_page
                    if history_cursor is None
                    else history_reader.read_page
                )
                history_task = asyncio.create_task(
                    page_reader(
                        runtime,
                        thread_id,
                        cursor=history_cursor,
                        limit=HISTORY_PAGE_LIMIT,
                        max_age_seconds=0.0 if history_cursor is None else None,
                    ),
                    name=f"codex-history-page-{thread_id[:24]}",
                )
                next_history_at = float("inf")

            wait_for = {event_task}
            if subscribe_task is not None:
                wait_for.add(subscribe_task)
            if history_task is not None:
                wait_for.add(history_task)
            until_heartbeat = max(0.05, heartbeat_seconds - (now - last_emit))
            until_scheduled = min(
                max(0.05, next_subscribe_at - now)
                if not subscription_live and subscribe_task is None
                else until_heartbeat,
                max(0.05, next_history_at - now)
                if subscription_live and history_task is None
                else until_heartbeat,
            )
            done, _ = await asyncio.wait(
                wait_for,
                timeout=min(until_heartbeat, until_scheduled),
                return_when=asyncio.FIRST_COMPLETED,
            )

            if subscribe_task is not None and subscribe_task in done:
                completed = subscribe_task
                subscribe_task = None
                try:
                    completed.result()
                except Exception as exc:
                    logger.warning(
                        "Codex live subscription failed for %s: %s", thread_id, exc
                    )
                    yield status_event(
                        thread_id,
                        "degraded",
                        detail="Codex live synchronization is retrying",
                        retry_in_seconds=retry_seconds,
                    )
                    next_subscribe_at = time.monotonic() + retry_seconds
                    retry_seconds = min(max_retry_seconds, retry_seconds * 2)
                else:
                    subscription_live = True
                    retry_seconds = max(0.05, poll_seconds)
                    next_history_at = time.monotonic()
                    yield status_event(thread_id, "live")
                last_emit = time.monotonic()

            if event_task in done:
                event = event_task.result()
                event_task = asyncio.create_task(
                    event_queue.get(), name="codex-sync-event"
                )
                public_message = getattr(event, "public_message", None)
                if public_message is not None:
                    live_messages[public_message.message_id] = public_message
                    yield sse_event(
                        "message",
                        {
                            "thread_id": thread_id,
                            "turn_id": getattr(event, "turn_id", None),
                            "message": {
                                "message_id": public_message.message_id,
                                "role": public_message.role,
                                "content": public_message.content,
                                "timestamp": public_message.timestamp,
                            },
                        },
                    )
                    last_emit = time.monotonic()
                public_delta = getattr(event, "public_text_delta", None)
                if public_delta:
                    yield sse_event(
                        "delta",
                        {
                            "thread_id": thread_id,
                            "turn_id": getattr(event, "turn_id", None),
                            "delta": public_delta,
                        },
                    )
                    last_emit = time.monotonic()
                execution = codex_execution_payload(event, thread_id)
                if execution is not None:
                    yield sse_event(
                        "execution",
                        execution,
                        execution.get("event_id"),
                    )
                    last_emit = time.monotonic()
                if getattr(event, "event_type", None) in {
                    "turn_completed",
                    "turn_reconciled",
                }:
                    refresh_requested = True

            if history_task is not None and history_task in done:
                completed = history_task
                history_task = None
                try:
                    page = completed.result()
                except Exception as exc:
                    logger.warning(
                        "Codex history page failed for %s: %s", thread_id, exc
                    )
                    yield status_event(
                        thread_id,
                        "degraded",
                        detail="Live updates are active; history is retrying",
                        retry_in_seconds=retry_seconds,
                    )
                    next_history_at = time.monotonic() + retry_seconds
                    retry_seconds = min(max_retry_seconds, retry_seconds * 2)
                    last_emit = time.monotonic()
                else:
                    retry_seconds = max(0.05, poll_seconds)
                    accumulated_messages = page.history.messages + accumulated_messages
                    pages_loaded += 1
                    reached_limit = pages_loaded >= MAX_INITIAL_HISTORY_PAGES
                    complete = page.next_cursor is None
                    history = CodexThreadHistory(
                        thread_id=thread_id,
                        messages=merge_public_messages(
                            accumulated_messages,
                            tuple(live_messages.values()),
                        ),
                    )
                    payload, next_revision = history_snapshot(
                        history,
                        complete=complete,
                        next_cursor=page.next_cursor,
                    )
                    if next_revision != revision:
                        revision = next_revision
                        payload["revision"] = revision
                        yield sse_event("snapshot", payload, revision)
                        last_emit = time.monotonic()
                    if complete:
                        yield status_event(thread_id, "synchronized")
                    elif refresh_only or reached_limit:
                        yield status_event(
                            thread_id,
                            "live",
                            detail="Recent Codex history is synchronized",
                        )
                    else:
                        yield status_event(thread_id, "synchronizing")
                        history_cursor = page.next_cursor
                        next_history_at = time.monotonic()
                    if complete or refresh_only or reached_limit:
                        if poll_history_only:
                            history_cursor = None
                            accumulated_messages = ()
                            pages_loaded = 0
                            refresh_only = True
                            next_history_at = time.monotonic() + poll_seconds
                        else:
                            next_history_at = float("inf")
                    refresh_only = False
                    last_emit = time.monotonic()

            now = time.monotonic()
            if now - last_emit >= heartbeat_seconds:
                yield ": keep-alive\n\n"
                last_emit = now
    finally:
        pending = [
            task
            for task in (event_task, subscribe_task, history_task)
            if task is not None
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if event_token is not None and callable(unsubscribe_events):
            unsubscribe_events(event_token)


__all__ = ["stream_codex_thread_updates"]
