"""One authenticated WebSocket connection owned by the Core."""

from __future__ import annotations

import asyncio
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

    async def send(self, frame: EdgeFrame) -> None:
        async with self._send_lock:
            await self.websocket.send_text(frame.wire_json())

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        try:
            await self.websocket.close(code=code, reason=reason[:120])
        except Exception:
            pass


__all__ = ["EdgeConnection"]
