"""Sanitized connection diagnostics and bounded reconnect timing."""

from __future__ import annotations

import asyncio
import random
import re

_SAFE_VALUE_ERRORS = {
    "Core did not acknowledge Edge registration": "registration_not_acknowledged",
    "Core frame targets another device": "device_identity_mismatch",
    "Core frame sequence moved backwards": "core_sequence_moved_backwards",
    "Edge job identity mismatch": "job_identity_mismatch",
}
_SAFE_CLOSE_REASON = re.compile(r"^[a-z0-9_.:-]{1,80}$")


def safe_connection_failure(exc: Exception) -> str:
    """Return protocol diagnostics without logging URLs, tokens or payloads."""
    if isinstance(exc, ValueError):
        return f"ValueError:{_SAFE_VALUE_ERRORS.get(str(exc), 'protocol_value_error')}"
    received = getattr(exc, "rcvd", None)
    code = getattr(received, "code", None)
    reason = str(getattr(received, "reason", "") or "")
    details = [type(exc).__name__]
    if isinstance(code, int):
        details.append(f"code={code}")
    if reason and _SAFE_CLOSE_REASON.fullmatch(reason):
        details.append(f"reason={reason}")
    return ":".join(details)


async def wait_for_reconnect(
    stop: asyncio.Event,
    delay: float,
    *,
    max_seconds: float,
) -> None:
    """Wait for a jittered bounded delay unless shutdown is requested."""
    duration = min(max_seconds, delay + random.uniform(0, max(0.1, delay * 0.2)))
    try:
        await asyncio.wait_for(stop.wait(), timeout=duration)
    except asyncio.TimeoutError:
        pass


__all__ = ["safe_connection_failure", "wait_for_reconnect"]
