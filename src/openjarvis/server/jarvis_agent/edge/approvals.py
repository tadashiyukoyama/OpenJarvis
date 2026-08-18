"""Nested approval lifecycle for local Codex app-server requests."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.edge.registry import EdgeRegistry
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.events import EventService


class EdgeApprovalService:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        events: EventService,
        registry: EdgeRegistry,
        protocol: EdgeProtocol,
    ) -> None:
        self._store = store
        self._events = events
        self._registry = registry
        self._protocol = protocol

    def record(self, assignment: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        now = time.time()
        action = self._action(assignment)
        approval = self._store.create_edge_approval(
            {
                "approval_id": payload["approval_id"],
                "job_id": assignment["job_id"],
                "attempt_id": assignment["attempt_id"],
                "preview": payload["preview"],
                "payload_hash": payload["payload_hash"],
                "created_at": now,
                "expires_at": now + 300,
            }
        )
        self._store.transition_edge_assignment(
            job_id=str(assignment["job_id"]),
            attempt_id=str(assignment["attempt_id"]),
            expected_states=("ACCEPTED", "RUNNING", "WAITING_APPROVAL"),
            next_state="WAITING_APPROVAL",
            now=now,
        )
        self._events.emit(
            "edge_approval_required",
            session_id=str(action["session_id"]) if action else None,
            action_id=assignment.get("action_id"),
            job_id=str(assignment["job_id"]),
            payload={
                "approval_id": approval["approval_id"],
                "payload_hash": approval["payload_hash"],
                "preview": approval["preview"],
                "expires_at": approval["expires_at"],
            },
        )

    def decide(
        self, *, approval_id: str, payload_hash: str, decision: str
    ) -> dict[str, Any]:
        try:
            approval = self._store.decide_edge_approval(
                approval_id=approval_id,
                payload_hash=payload_hash,
                decision=decision,
                now=time.time(),
            )
        except sqlite3.IntegrityError as exc:
            raise JarvisAgentError(
                "APPROVAL_PAYLOAD_MISMATCH",
                "A aprovação não corresponde ao conteúdo exibido.",
                status_code=409,
            ) from exc
        if approval is None:
            raise JarvisAgentError(
                "EDGE_APPROVAL_NOT_FOUND",
                "A aprovação Edge não existe.",
                status_code=404,
            )
        if approval["state"] == "EXPIRED":
            raise JarvisAgentError(
                "EDGE_APPROVAL_EXPIRED", "A aprovação Edge expirou.", status_code=409
            )
        assignment = self._store.get_edge_assignment(str(approval["job_id"]))
        delivered = bool(assignment and self._send_if_online(assignment, approval))
        action = self._action(assignment or {})
        self._events.emit(
            "edge_approval_decided",
            session_id=str(action["session_id"]) if action else None,
            action_id=assignment.get("action_id") if assignment else None,
            job_id=str(approval["job_id"]),
            payload={
                "approval_id": approval["approval_id"],
                "decision": decision,
                "delivery": "sent" if delivered else "pending_reconnect",
            },
        )
        return {**approval, "delivery": "sent" if delivered else "pending_reconnect"}

    async def resume(
        self, connection: EdgeConnection, active_job_ids: list[str]
    ) -> None:
        approvals = self._store.edge_approvals_for_jobs(
            active_job_ids, states=("APPROVED", "DENIED")
        )
        for approval in approvals:
            assignment = self._store.get_edge_assignment(str(approval["job_id"]))
            if assignment is None or assignment["device_id"] != connection.device_id:
                continue
            await connection.send(
                self._resolved_frame(connection, assignment, approval)
            )

    def _send_if_online(
        self, assignment: Mapping[str, Any], approval: Mapping[str, Any]
    ) -> bool:
        connection = self._registry.get(str(assignment["device_id"]))
        if connection is None:
            return False
        self._protocol.send_from_thread(
            connection, self._resolved_frame(connection, assignment, approval)
        )
        return True

    def _resolved_frame(
        self,
        connection: EdgeConnection,
        assignment: Mapping[str, Any],
        approval: Mapping[str, Any],
    ):
        return self._protocol.outbound_frame(
            connection.device_id,
            "approval.resolved",
            {
                "attempt_id": assignment["attempt_id"],
                "approval_id": approval["approval_id"],
                "decision": "approve" if approval["state"] == "APPROVED" else "deny",
            },
            job_id=str(assignment["job_id"]),
        )

    def _action(self, assignment: Mapping[str, Any]) -> Mapping[str, Any] | None:
        action_id = assignment.get("action_id")
        return self._store.get_action(str(action_id)) if action_id else None


__all__ = ["EdgeApprovalService"]
