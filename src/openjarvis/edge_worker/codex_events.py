"""Bounded, ordered relay for sanitized Codex app-server notifications."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from openjarvis.integrations.codex_protocol import CodexConversationEvent

logger = logging.getLogger(__name__)

CodexEventEmitter = Callable[[Mapping[str, Any]], Awaitable[Any]]


def _public_scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, int, bool))


def public_codex_event_payload(
    event: CodexConversationEvent,
) -> dict[str, Any] | None:
    """Serialize only the public allowlisted part of an app-server event."""

    thread_id = event.thread_id.strip() if event.thread_id else ""
    if not thread_id or event.event_type not in {
        "text_delta",
        "turn_started",
        "turn_completed",
        "item_started",
        "item_completed",
        "status_changed",
    }:
        return None
    message = event.public_message
    metadata: dict[str, str | int | float | bool | None] = {}
    for key, value in list(event.metadata.items())[:16]:
        if not _public_scalar(value):
            continue
        metadata[str(key)[:64]] = value[:512] if isinstance(value, str) else value
    payload: dict[str, Any] = {
        "event_schema_version": "1.0",
        "method": event.method[:128],
        "thread_id": thread_id[:256],
        "event_type": event.event_type,
        "metadata": metadata,
    }
    if event.turn_id:
        payload["turn_id"] = event.turn_id[:256]
    if event.item_id:
        payload["item_id"] = event.item_id[:256]
    if event.public_text_delta:
        payload["public_text_delta"] = event.public_text_delta[:16_384]
    if message is not None and message.role in {"user", "assistant"}:
        payload["public_message"] = {
            "message_id": message.message_id[:256],
            "role": message.role,
            "content": message.content[:20_000],
            "timestamp": (
                message.timestamp
                if message.timestamp is None or math.isfinite(message.timestamp)
                else None
            ),
        }
    if event.public_action_summary:
        payload["public_action_summary"] = event.public_action_summary[:1_000]
    if event.terminal_status is not None:
        payload["terminal_status"] = event.terminal_status.value
    if not (
        payload.get("public_text_delta")
        or payload.get("public_message")
        or payload.get("public_action_summary")
        or event.event_type in {"turn_started", "turn_completed", "status_changed"}
    ):
        return None
    return payload


class CodexEventRelay:
    """Coalesce text deltas and serialize all outgoing events in order."""

    def __init__(
        self,
        emit: CodexEventEmitter,
        *,
        coalesce_seconds: float = 0.05,
        max_delta_chars: int = 4_096,
        max_backlog: int = 512,
    ) -> None:
        self._emit = emit
        self._coalesce_seconds = coalesce_seconds
        self._max_delta_chars = max_delta_chars
        self._max_backlog = max_backlog
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_delta: dict[str, Any] | None = None
        self._delta_timer: asyncio.TimerHandle | None = None
        self._outgoing: deque[dict[str, Any]] = deque()
        self._wake: asyncio.Event | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._inflight = False
        self._closed = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is loop and self._pump_task is not None:
            return
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Codex event relay cannot move between event loops")
        self._loop = loop
        self._wake = asyncio.Event()
        self._pump_task = loop.create_task(
            self._pump(), name="openjarvis-codex-event-relay"
        )

    def submit(self, event: CodexConversationEvent) -> None:
        payload = public_codex_event_payload(event)
        loop = self._loop
        if payload is None or loop is None or self._closed:
            return
        loop.call_soon_threadsafe(self._accept, payload)

    def _accept(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        if payload["event_type"] == "text_delta":
            if self._can_merge_delta(payload):
                assert self._pending_delta is not None
                self._pending_delta["public_text_delta"] += payload["public_text_delta"]
                if (
                    len(self._pending_delta["public_text_delta"])
                    >= self._max_delta_chars
                ):
                    self._flush_delta()
                return
            self._flush_delta()
            self._pending_delta = payload
            self._delta_timer = self._required_loop().call_later(
                self._coalesce_seconds, self._flush_delta
            )
            return
        self._flush_delta()
        self._enqueue(payload)

    def _can_merge_delta(self, payload: Mapping[str, Any]) -> bool:
        pending = self._pending_delta
        if pending is None:
            return False
        return (
            pending.get("thread_id") == payload.get("thread_id")
            and pending.get("turn_id") == payload.get("turn_id")
            and pending.get("item_id") == payload.get("item_id")
            and len(str(pending.get("public_text_delta") or ""))
            + len(str(payload.get("public_text_delta") or ""))
            <= 16_384
        )

    def _flush_delta(self) -> None:
        timer, self._delta_timer = self._delta_timer, None
        if timer is not None:
            timer.cancel()
        payload, self._pending_delta = self._pending_delta, None
        if payload is not None:
            self._enqueue(payload)

    def _enqueue(self, payload: dict[str, Any]) -> None:
        if len(self._outgoing) >= self._max_backlog:
            removable = next(
                (
                    index
                    for index, candidate in enumerate(self._outgoing)
                    if candidate.get("event_type") == "text_delta"
                ),
                None,
            )
            if removable is None and payload.get("event_type") != "text_delta":
                removable = next(
                    (
                        index
                        for index, candidate in enumerate(self._outgoing)
                        if candidate.get("event_type")
                        in {"item_started", "item_completed", "turn_started"}
                    ),
                    None,
                )
            if removable is not None:
                del self._outgoing[removable]
            elif payload.get("event_type") == "text_delta":
                logger.warning("Codex event relay dropped one excess text delta")
                return
            else:
                # Keep the newest terminal/control signal bounded. Canonical
                # history remains authoritative if this pathological limit is
                # ever reached.
                self._outgoing.popleft()
                logger.warning("Codex event relay replaced one stale control event")
        self._outgoing.append(payload)
        wake = self._wake
        if wake is not None:
            wake.set()

    async def _pump(self) -> None:
        wake = self._wake
        assert wake is not None
        while not self._closed or self._outgoing:
            if not self._outgoing:
                wake.clear()
                await wake.wait()
                continue
            payload = self._outgoing.popleft()
            self._inflight = True
            try:
                await self._emit(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Codex event relay could not queue an event: %s",
                    type(exc).__name__,
                )
            finally:
                self._inflight = False

    def flush_from_thread(self, timeout_seconds: float = 5.0) -> None:
        loop = self._loop
        if loop is None or self._closed:
            return
        future = asyncio.run_coroutine_threadsafe(self._drain(), loop)
        future.result(timeout=timeout_seconds)

    async def _drain(self) -> None:
        self._flush_delta()
        deadline = time.monotonic() + 4.5
        while (self._outgoing or self._inflight) and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        if self._outgoing or self._inflight:
            raise TimeoutError("Codex event relay did not drain")

    async def close(self) -> None:
        if self._closed:
            return
        self._flush_delta()
        self._closed = True
        if self._wake is not None:
            self._wake.set()
        task = self._pump_task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._pump_task = None

    def _required_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("Codex event relay is not started")
        return self._loop


__all__ = ["CodexEventRelay", "CodexEventEmitter", "public_codex_event_payload"]
