"""Public SSE contracts for Codex conversation synchronization."""

from __future__ import annotations

import hashlib
import json
from typing import Any

HISTORY_PAGE_LIMIT = 100
MAX_INITIAL_HISTORY_PAGES = 5
SUBSCRIBE_TIMEOUT_SECONDS = 5.0

_EXECUTION_STATES = {
    "STARTING": "starting",
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "INTERRUPTED": "interrupted",
    "CANCELLED": "cancelled",
    "UNKNOWN": "unknown",
}


def codex_history_payload(
    history: Any,
    *,
    complete: bool = True,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    """Return the public, JSON-compatible representation of thread history."""

    return {
        "thread_id": history.thread_id,
        "messages": [
            {
                "message_id": message.message_id,
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp,
            }
            for message in history.messages
        ],
        "complete": complete,
        "next_cursor": next_cursor,
    }


def history_snapshot(
    history: Any,
    *,
    complete: bool,
    next_cursor: str | None,
) -> tuple[dict[str, Any], str]:
    payload = codex_history_payload(
        history,
        complete=complete,
        next_cursor=next_cursor,
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return payload, hashlib.sha256(canonical).hexdigest()


def sse_event(
    event_type: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event_type}\ndata: {encoded}\n\n"


def status_event(
    thread_id: str,
    state: str,
    *,
    detail: str | None = None,
    retry_in_seconds: float | None = None,
) -> str:
    payload: dict[str, Any] = {"thread_id": thread_id, "state": state}
    if detail is not None:
        payload["detail"] = detail
    if retry_in_seconds is not None:
        payload["retry_in_seconds"] = round(retry_in_seconds, 3)
    return sse_event("status", payload)


def codex_execution_payload(event: Any, thread_id: str) -> dict[str, Any] | None:
    event_type = getattr(event, "event_type", None)
    if event_type not in {
        "turn_started",
        "turn_completed",
        "item_started",
        "item_completed",
        "status_changed",
    }:
        return None
    terminal = getattr(event, "terminal_status", None)
    terminal_value = getattr(terminal, "value", terminal)
    state = _EXECUTION_STATES.get(str(terminal_value or ""))
    if state is None:
        if event_type == "turn_completed":
            state = "unknown"
        elif event_type == "turn_started":
            state = "starting"
        elif event_type.startswith("item_"):
            state = "working"
        else:
            state = "running"
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "turn_id": getattr(event, "turn_id", None),
        "item_id": getattr(event, "item_id", None),
        "event_type": event_type,
        "state": state,
    }
    action = getattr(event, "public_action_summary", None)
    if isinstance(action, str) and action.strip():
        payload["action_summary"] = action.strip()[:1_000]
    event_id = getattr(event, "event_id", None)
    if isinstance(event_id, str) and event_id:
        payload["event_id"] = event_id
    sequence = getattr(event, "sequence", None)
    if isinstance(sequence, int) and sequence > 0:
        payload["sequence"] = sequence
    return payload


def public_event_is_relevant(event: Any, thread_id: str) -> bool:
    if getattr(event, "thread_id", None) != thread_id:
        return False
    return bool(
        getattr(event, "public_text_delta", None)
        or getattr(event, "public_message", None)
        or getattr(event, "event_type", None)
        in {
            "turn_started",
            "turn_completed",
            "turn_reconciled",
            "item_started",
            "item_completed",
            "status_changed",
        }
    )


def merge_public_messages(
    history_messages: tuple[Any, ...],
    live_messages: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Overlay live canonical messages on a possibly older history page.

    History requests and Desktop notifications run concurrently.  A history
    response can therefore have been captured before a message that already
    crossed the live channel.  Merging by the canonical item ID prevents that
    slower response from rolling the UI back to an older state.
    """

    merged = list(history_messages)
    positions = {message.message_id: index for index, message in enumerate(merged)}
    for message in live_messages:
        index = positions.get(message.message_id)
        if index is None:
            positions[message.message_id] = len(merged)
            merged.append(message)
        else:
            merged[index] = message
    return tuple(merged)


__all__ = [
    "HISTORY_PAGE_LIMIT",
    "MAX_INITIAL_HISTORY_PAGES",
    "SUBSCRIBE_TIMEOUT_SECONDS",
    "codex_history_payload",
    "codex_execution_payload",
    "history_snapshot",
    "merge_public_messages",
    "public_event_is_relevant",
    "sse_event",
    "status_event",
]
