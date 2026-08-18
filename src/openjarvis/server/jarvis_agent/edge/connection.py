"""One authenticated WebSocket connection owned by the Core."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame


@dataclass(slots=True)
class EdgeConnection:
    connection_id: str
    device_id: str
    credential_slot: str
    capabilities: frozenset[str]
    websocket: Any
    loop: asyncio.AbstractEventLoop
    connected_at: float
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def create_and_send(self, factory: Callable[[], EdgeFrame]) -> EdgeFrame:
        """Allocate and transmit one frame under the same per-socket lock.

        Sequence allocation must happen inside this critical section. Allocating
        before awaiting the send lock lets concurrent callers put N+1 on the
        wire before N, which correctly makes the Edge worker fail closed.
        """

        async with self._send_lock:
            frame = factory()
            await self.websocket.send_text(frame.wire_json())
            return frame

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        try:
            await self.websocket.close(code=code, reason=reason[:120])
        except Exception:
            pass


__all__ = ["EdgeConnection"]
