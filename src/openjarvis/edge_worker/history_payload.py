"""Bounded public serialization for Codex history results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from openjarvis.integrations.codex_protocol import CodexHistoryMessage

_HISTORY_MAX_ITEMS = 30
_HISTORY_CONTENT_BUDGET_BYTES = 128 * 1024
_HISTORY_MESSAGE_MAX_BYTES = 8 * 1024


def bounded_history_limit(value: Any) -> int:
    """Normalize the requested page size to the public Edge contract."""
    return min(_HISTORY_MAX_ITEMS, max(1, int(value or 16)))


def serialize_bounded_history(
    messages: Sequence[CodexHistoryMessage],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Serialize recent messages without exceeding the response content budget."""
    remaining = _HISTORY_CONTENT_BUDGET_BYTES
    serialized: list[dict[str, Any]] = []
    for item in messages[-limit:]:
        content, truncated = _bounded_utf8(
            item.content,
            min(_HISTORY_MESSAGE_MAX_BYTES, remaining),
        )
        remaining -= len(content.encode("utf-8"))
        serialized.append(
            {
                "message_id": item.message_id,
                "role": item.role,
                "content": content,
                "content_truncated": truncated,
                "timestamp": item.timestamp,
            }
        )
    return serialized


def _bounded_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    if max_bytes <= 0:
        return "", True
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


__all__ = ["bounded_history_limit", "serialize_bounded_history"]
