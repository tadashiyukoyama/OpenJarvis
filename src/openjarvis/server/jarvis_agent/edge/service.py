"""Small Core-side facade for authenticated Edge connections and jobs."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.approvals import EdgeApprovalService
from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame
from openjarvis.server.jarvis_agent.edge.jobs import EdgeJobBroker
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.edge.reconciliation import EdgeResultReconciler
from openjarvis.server.jarvis_agent.edge.registry import EdgeRegistry
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService


class EdgeService:
    """Coordinate protocol components without owning implementation details."""

    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        events: EventService,
        context: ContextService,
        config: EdgeCoreConfig | None = None,
    ) -> None:
        self.store = store
        self.events = events
        self.context = context
        self.config = config or EdgeCoreConfig.from_env()
        self.protocol = EdgeProtocol(store)
        self.registry = EdgeRegistry(
            store=store,
            events=events,
            protocol=self.protocol,
            config=self.config,
        )
        self.jobs = EdgeJobBroker(
            store=store,
            events=events,
            registry=self.registry,
            protocol=self.protocol,
            reconciler=EdgeResultReconciler(store, context, events),
            config=self.config,
        )
        self.approvals = EdgeApprovalService(
            store=store,
            events=events,
            registry=self.registry,
            protocol=self.protocol,
        )

    def status(self) -> dict[str, Any]:
        return self.registry.status()

    def capabilities(self) -> frozenset[str]:
        return self.registry.capabilities()

    def select_connection(self, capability: str) -> EdgeConnection | None:
        return self.registry.select(capability)

    async def register(
        self,
        *,
        websocket: Any,
        credential_slot: str,
        frame: EdgeFrame,
    ) -> EdgeConnection:
        if frame.type != "edge.register":
            raise JarvisAgentError(
                "EDGE_FRAME_INVALID", "O primeiro evento deve registrar o worker."
            )
        payload = frame.validated_payload(from_client=True).model_dump(mode="json")
        return await self.registry.register(
            websocket=websocket,
            credential_slot=credential_slot,
            frame=frame,
            payload=payload,
        )

    async def handle(self, connection: EdgeConnection, frame: EdgeFrame) -> bool:
        if frame.device_id != connection.device_id:
            raise JarvisAgentError(
                "EDGE_AUTH_FAILED", "Identidade Edge divergente.", status_code=403
            )
        payload = frame.validated_payload(from_client=True).model_dump(mode="json")
        created = self.protocol.record_inbound(
            frame, metadata=self.protocol.safe_metadata(frame, payload)
        )
        if created:
            self.store.touch_edge_device(connection.device_id, now=time.time())
            if frame.type == "edge.resume":
                await self.approvals.resume(connection, payload["active_job_ids"])
            elif frame.type == "edge.goodbye":
                return False
            elif frame.type == "approval.required":
                self.approvals.record(
                    self._assignment(connection, frame, payload), payload
                )
            elif frame.job_id:
                self.jobs.handle(connection, frame, payload)
        await connection.send(
            self.protocol.outbound_frame(
                connection.device_id,
                "edge.heartbeat_ack",
                {
                    "acknowledged_sequence": self.store.edge_sequences(
                        connection.device_id
                    )["inbound_sequence"],
                    "server_time": self.protocol.utc_now(),
                },
            )
        )
        return True

    def unregister(self, connection: EdgeConnection, *, error_code: str | None) -> None:
        if self.registry.unregister(connection, error_code=error_code):
            self.jobs.device_disconnected(connection.device_id)

    def execute_job(self, **kwargs: Any) -> dict[str, Any]:
        return self.jobs.execute(**kwargs)

    def decide_approval(
        self, *, approval_id: str, payload_hash: str, decision: str
    ) -> dict[str, Any]:
        return self.approvals.decide(
            approval_id=approval_id,
            payload_hash=payload_hash,
            decision=decision,
        )

    async def close(self) -> None:
        await self.registry.close()

    async def revoke_device(self, device_id: str) -> bool:
        revoked = await self.registry.revoke(device_id)
        if revoked:
            self.jobs.device_disconnected(device_id)
        return revoked

    def _assignment(
        self,
        connection: EdgeConnection,
        frame: EdgeFrame,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assignment = self.store.get_edge_assignment(str(frame.job_id))
        if assignment is None or assignment["device_id"] != connection.device_id:
            raise JarvisAgentError(
                "EDGE_JOB_INVALID", "O job Edge não pertence ao dispositivo."
            )
        if payload.get("attempt_id") != assignment["attempt_id"]:
            raise JarvisAgentError(
                "EDGE_JOB_INVALID", "A tentativa Edge não corresponde ao job."
            )
        return assignment


__all__ = ["EdgeService"]
