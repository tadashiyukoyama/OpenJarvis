"""Durable-data guards applied after adapter execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _payload_strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _payload_strings(child)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for child in value for item in _payload_strings(child)]
    if isinstance(value, str) and len(value.strip()) >= 4:
        return [value.strip()]
    return []


def durable_summary(
    value: object,
    payload: Mapping[str, Any],
    *,
    limit: int = 2_000,
) -> str:
    """Remove approved/provider values before a summary reaches durable storage."""

    summary = " ".join(str(value or "").split())
    for sensitive in sorted(set(_payload_strings(payload)), key=len, reverse=True):
        summary = summary.replace(sensitive, "[redacted]")
    return summary[:limit]


__all__ = ["durable_summary"]
