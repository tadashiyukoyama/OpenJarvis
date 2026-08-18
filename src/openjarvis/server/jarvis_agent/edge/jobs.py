"""Exactly-once Edge job broker with bounded waits and no hidden queue."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame
from openjarvis.server.jarvis_agent.edge.job_results import EdgeJobResults
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.edge.reconciliation import EdgeResultReconciler
from openjarvis.server.jarvis_agent.edge.registry import EdgeRegistry
from openjarvis.server.jarvis_agent.edge.waiters import EdgeJobWaiter
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.events import EventService


class EdgeJobBroker:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        events: EventService,
        registry: EdgeRegistry,
        protocol: EdgeProtocol,
        reconciler: EdgeResultReconciler,
        config: EdgeCoreConfig,
    ) -> None:
        self._store = store
        self._events = events
        self._registry = registry
        self._protocol = protocol
        self._reconciler = reconciler
        self._config = config
        self._results = EdgeJobResults(store, protocol)
        self._waiters: dict[str, EdgeJobWaiter] = {}
        self._waiters_lock = threading.Lock()

    def execute(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
        payload_hash: str,
        capability: str,
        action_id: str | None = None,
        job_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        connection = self._registry.select(capability)
        if connection is None:
            raise JarvisAgentError(
                "DEVICE_OFFLINE",
                "O computador com Codex está offline.",
                status_code=503,
            )
        assignment, created = self._create_assignment(
            connection=connection,
            tool_id=tool_id,
            payload_hash=payload_hash,
            action_id=action_id,
            job_id=job_id,
        )
        if not created:
            return self._results.existing(assignment)
        resolved_job_id = str(assignment["job_id"])
        waiter = self._install_waiter(resolved_job_id)
        try:
            offer = self._offer_frame(connection, assignment, arguments, context)
            try:
                self._protocol.send_from_thread(connection, offer)
            except JarvisAgentError:
                terminal = self._results.finish(
                    assignment,
                    state="FAILED",
                    event_id=f"offer_failed_{uuid.uuid4().hex}",
                    summary="O worker ficou offline antes de receber o job.",
                    error_code="DEVICE_OFFLINE",
                )
                raise self._results.terminal_error(terminal)
            self._wait_for_acceptance(waiter, assignment)
            early = waiter.result()
            if early is not None and early.get("state") != "ACCEPTED":
                return self._results.result_or_raise(early)
            self._wait_for_result(
                waiter,
                connection,
                assignment,
                timeout_seconds or self._config.result_timeout_seconds,
            )
            return self._results.result_or_raise(waiter.result() or {})
        finally:
            with self._waiters_lock:
                self._waiters.pop(resolved_job_id, None)

    def handle(
        self,
        connection: EdgeConnection,
        frame: EdgeFrame,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        assignment = self._assignment_for(connection, frame, payload)
        if frame.type == "job.accepted":
            updated = self._store.transition_edge_assignment(
                job_id=str(frame.job_id),
                attempt_id=str(assignment["attempt_id"]),
                expected_states=("OFFERED",),
                next_state="ACCEPTED",
                now=time.time(),
                accepted_at=time.time(),
            )
            waiter = self._waiter(str(frame.job_id), required=False)
            if waiter is not None:
                waiter.mark_accepted()
            return updated or assignment
        if frame.type == "job.progress":
            self._progress(assignment, frame, payload)
            return assignment
        terminal = self._results.from_frame(assignment, frame, payload)
        if terminal is None:
            return assignment
        waiter = self._waiter(str(frame.job_id), required=False)
        if waiter is not None:
            waiter.finish(terminal)
        else:
            self._reconciler.reconcile(assignment, terminal)
        return terminal

    def device_disconnected(self, device_id: str) -> None:
        assignments = self._store.edge_assignments_for_device(
            device_id, states=("OFFERED",)
        )
        for assignment in assignments:
            terminal = self._results.finish(
                assignment,
                state="FAILED",
                event_id=f"disconnect_{uuid.uuid4().hex}",
                summary="O worker ficou offline antes de aceitar o job.",
                error_code="DEVICE_OFFLINE",
            )
            waiter = self._waiter(str(assignment["job_id"]), required=False)
            if waiter is not None:
                waiter.finish(terminal)

    def _create_assignment(
        self,
        *,
        connection: EdgeConnection,
        tool_id: str,
        payload_hash: str,
        action_id: str | None,
        job_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        now = time.time()
        return self._store.create_edge_assignment(
            {
                "job_id": job_id or f"edgejob_{uuid.uuid4().hex}",
                "action_id": action_id,
                "device_id": connection.device_id,
                "attempt_id": f"attempt_{uuid.uuid4().hex}",
                "tool_id": tool_id,
                "payload_hash": payload_hash,
                "offered_at": now,
                "lease_expires_at": now + self._config.lease_seconds,
            }
        )

    def _offer_frame(
        self,
        connection: EdgeConnection,
        assignment: Mapping[str, Any],
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> EdgeFrame:
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=self._config.lease_seconds
        )
        return self._protocol.outbound_frame(
            connection.device_id,
            "job.offer",
            {
                "attempt_id": assignment["attempt_id"],
                "tool_id": assignment["tool_id"],
                "arguments": dict(arguments),
                "context": dict(context),
                "payload_hash": assignment["payload_hash"],
                "lease_expires_at": expires.isoformat().replace("+00:00", "Z"),
            },
            job_id=str(assignment["job_id"]),
        )

    def _wait_for_acceptance(
        self, waiter: EdgeJobWaiter, assignment: Mapping[str, Any]
    ) -> None:
        if waiter.accepted.wait(self._config.offer_accept_timeout_seconds):
            return
        terminal = self._results.finish(
            assignment,
            state="FAILED",
            event_id=f"accept_timeout_{uuid.uuid4().hex}",
            summary="O worker não aceitou o job no prazo.",
            error_code="DEVICE_OFFLINE",
        )
        raise self._results.terminal_error(terminal)

    def _wait_for_result(
        self,
        waiter: EdgeJobWaiter,
        connection: EdgeConnection,
        assignment: Mapping[str, Any],
        timeout_seconds: float,
    ) -> None:
        if waiter.terminal.wait(timeout_seconds):
            return
        self._cancel_best_effort(connection, assignment, "result_timeout")
        terminal = self._results.finish(
            assignment,
            state="UNKNOWN",
            event_id=f"result_timeout_{uuid.uuid4().hex}",
            summary="O resultado do job Edge é desconhecido após o timeout.",
            error_code="EDGE_JOB_TIMEOUT",
        )
        raise self._results.terminal_error(terminal)

    def _assignment_for(
        self,
        connection: EdgeConnection,
        frame: EdgeFrame,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assignment = self._store.get_edge_assignment(str(frame.job_id))
        if assignment is None or assignment["device_id"] != connection.device_id:
            raise JarvisAgentError(
                "EDGE_JOB_INVALID", "O job Edge não pertence ao dispositivo."
            )
        if payload.get("attempt_id") != assignment["attempt_id"]:
            raise JarvisAgentError(
                "EDGE_JOB_INVALID", "A tentativa Edge não corresponde ao job."
            )
        return assignment

    def _progress(
        self,
        assignment: Mapping[str, Any],
        frame: EdgeFrame,
        payload: Mapping[str, Any],
    ) -> None:
        self._store.transition_edge_assignment(
            job_id=str(frame.job_id),
            attempt_id=str(assignment["attempt_id"]),
            expected_states=("ACCEPTED", "RUNNING", "WAITING_APPROVAL"),
            next_state="RUNNING",
            now=time.time(),
        )
        self._events.emit(
            "edge_job_progress",
            action_id=assignment.get("action_id"),
            job_id=str(frame.job_id),
            payload={"stage": payload["stage"], "summary": payload["summary"][:500]},
        )

    def _install_waiter(self, job_id: str) -> EdgeJobWaiter:
        waiter = EdgeJobWaiter()
        with self._waiters_lock:
            if job_id in self._waiters:
                raise JarvisAgentError(
                    "EDGE_JOB_INVALID",
                    "O job Edge já está em execução.",
                    status_code=409,
                )
            self._waiters[job_id] = waiter
        return waiter

    def _waiter(self, job_id: str, *, required: bool) -> EdgeJobWaiter | None:
        with self._waiters_lock:
            waiter = self._waiters.get(job_id)
        if waiter is None and required:
            raise JarvisAgentError(
                "EDGE_JOB_INVALID", "O job Edge não possui execução ativa."
            )
        return waiter

    def _cancel_best_effort(
        self, connection: EdgeConnection, assignment: Mapping[str, Any], reason: str
    ) -> None:
        try:
            frame = self._protocol.outbound_frame(
                connection.device_id,
                "job.cancel",
                {"attempt_id": assignment["attempt_id"], "reason": reason},
                job_id=str(assignment["job_id"]),
            )
            self._protocol.send_from_thread(connection, frame)
        except Exception:
            pass


__all__ = ["EdgeJobBroker"]
