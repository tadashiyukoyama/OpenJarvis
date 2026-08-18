from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_text(self, wire: str) -> None:
        frame = json.loads(wire)
        # Keep the socket awaitable so concurrent thread submissions contend
        # for the connection lock just as they do in production.
        await asyncio.sleep(0.001 if frame["sequence"] % 2 else 0)
        self.frames.append(frame)


def test_concurrent_thread_sends_preserve_wire_sequence(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = JarvisAgentStore(tmp_path / "agent.sqlite3")
        now = time.time()
        store.upsert_edge_device(
            {
                "device_id": "desktop-1",
                "status": "ONLINE",
                "capabilities": ["codex.status"],
                "metadata": {},
                "connected_at": now,
                "last_seen_at": now,
                "updated_at": now,
            }
        )
        socket = _RecordingWebSocket()
        connection = EdgeConnection(
            connection_id="edgec-test",
            device_id="desktop-1",
            credential_slot="current",
            capabilities=frozenset({"codex.status"}),
            websocket=socket,
            loop=asyncio.get_running_loop(),
            connected_at=now,
        )
        protocol = EdgeProtocol(store)

        await asyncio.gather(
            *(
                asyncio.to_thread(
                    protocol.send_from_thread,
                    connection,
                    "edge.heartbeat_ack",
                    {
                        "acknowledged_sequence": index,
                        "server_time": "2026-08-18T21:00:00Z",
                    },
                )
                for index in range(1, 41)
            )
        )

        wire_sequences = [frame["sequence"] for frame in socket.frames]
        assert wire_sequences == list(range(1, 41))
        stored = store.edge_sequences("desktop-1")
        assert stored["outbound_sequence"] == 40

    asyncio.run(exercise())
