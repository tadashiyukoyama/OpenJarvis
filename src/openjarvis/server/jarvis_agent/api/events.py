"""Authenticated SSE stream over the canonical event ledger."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import Request

from openjarvis.server.jarvis_agent.services.events import EventService


async def event_stream(
    request: Request,
    events: EventService,
    *,
    after: int,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    cursor = max(0, after)
    last_emit = time.monotonic()
    while not await request.is_disconnected():
        records = await asyncio.to_thread(events.after, cursor, 100)
        if records:
            for record in records:
                cursor = int(record["sequence"])
                payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                yield (
                    f"id: {cursor}\nevent: {record['event_type']}\ndata: {payload}\n\n"
                )
            last_emit = time.monotonic()
        elif time.monotonic() - last_emit >= heartbeat_seconds:
            yield ": heartbeat\n\n"
            last_emit = time.monotonic()
        await asyncio.sleep(0.35)
