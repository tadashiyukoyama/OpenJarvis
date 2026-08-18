"""Authenticated in-memory Edge connection registry."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.events import EventService


class EdgeRegistry:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        events: EventService,
        protocol: EdgeProtocol,
        config: EdgeCoreConfig,
    ) -> None:
        self._store = store
        self._events = events
        self._protocol = protocol
        self._config = config
        self._connections: dict[str, EdgeConnection] = {}
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            connections = list(self._connections.values())
        return {
            "configured": self._config.configured,
            "connected_devices": len(connections),
            "devices": [
                {
                    "device_id": item.device_id,
                    "status": "ONLINE",
                    "capabilities": sorted(item.capabilities),
                    "connected_at": item.connected_at,
                }
                for item in connections
            ],
        }

    def capabilities(self) -> frozenset[str]:
        with self._lock:
            values = {
                capability
                for connection in self._connections.values()
                for capability in connection.capabilities
            }
        return frozenset(values)

    def select(self, capability: str) -> EdgeConnection | None:
        with self._lock:
            candidates = [
                connection
                for connection in self._connections.values()
                if capability in connection.capabilities
            ]
        return (
            min(candidates, key=lambda item: item.connected_at) if candidates else None
        )

    def get(self, device_id: str) -> EdgeConnection | None:
        with self._lock:
            return self._connections.get(device_id)

    async def register(
        self,
        *,
        websocket: Any,
        credential_slot: str,
        frame: EdgeFrame,
        payload: dict[str, Any],
    ) -> EdgeConnection:
        existing = self._store.get_edge_device(frame.device_id)
        if existing is not None and existing.get("revoked"):
            raise JarvisAgentError(
                "DEVICE_REVOKED", "O dispositivo Edge foi revogado.", status_code=403
            )
        now = time.time()
        self._store.upsert_edge_device(
            {
                "device_id": frame.device_id,
                "status": "ONLINE",
                "capabilities": payload["capabilities"],
                "metadata": {
                    "worker_version": payload["worker_version"],
                    "platform": payload["platform"],
                    "credential_slot": credential_slot,
                },
                **self._config.credential_metadata(),
                "connected_at": now,
                "last_seen_at": now,
                "updated_at": now,
            }
        )
        self._protocol.record_inbound(
            frame, metadata=self._protocol.safe_metadata(frame, payload)
        )
        connection = EdgeConnection(
            connection_id=f"edgec_{uuid.uuid4().hex}",
            device_id=frame.device_id,
            credential_slot=credential_slot,
            capabilities=frozenset(payload["capabilities"]),
            websocket=websocket,
            loop=asyncio.get_running_loop(),
            connected_at=now,
        )
        with self._lock:
            previous = self._connections.get(frame.device_id)
            self._connections[frame.device_id] = connection
        if previous is not None and previous is not connection:
            await previous.close(code=4009, reason="superseded")
        cursor = self._store.edge_sequences(frame.device_id)["inbound_sequence"]
        await self._protocol.send(
            connection,
            "edge.registered",
            {
                "connection_id": connection.connection_id,
                "heartbeat_interval_seconds": int(
                    self._config.heartbeat_interval_seconds
                ),
                "acknowledged_sequence": cursor,
                "server_time": self._protocol.utc_now(),
            },
        )
        self._events.emit(
            "edge_device_connected",
            payload={
                "device_id": frame.device_id,
                "capability_count": len(connection.capabilities),
            },
        )
        return connection

    def unregister(self, connection: EdgeConnection, *, error_code: str | None) -> bool:
        with self._lock:
            if self._connections.get(connection.device_id) is not connection:
                return False
            self._connections.pop(connection.device_id, None)
        self._store.mark_edge_device_offline(
            connection.device_id, now=time.time(), error_code=error_code
        )
        self._events.emit(
            "edge_device_disconnected",
            payload={"device_id": connection.device_id, "error_code": error_code},
        )
        return True

    async def close(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        await asyncio.gather(
            *(
                connection.close(code=1001, reason="core_shutdown")
                for connection in connections
            ),
            return_exceptions=True,
        )

    async def revoke(self, device_id: str) -> bool:
        if not self._store.revoke_edge_device(device_id, now=time.time()):
            return False
        with self._lock:
            connection = self._connections.pop(device_id, None)
        if connection is not None:
            await connection.close(code=4403, reason="device_revoked")
        self._events.emit(
            "edge_device_revoked",
            payload={"device_id": device_id},
        )
        return True


__all__ = ["EdgeRegistry"]
