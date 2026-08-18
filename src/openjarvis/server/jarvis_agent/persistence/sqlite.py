"""Composed transactional store for the Jarvis agent core."""

from __future__ import annotations

import time
from pathlib import Path

from openjarvis.server.jarvis_agent.persistence.actions import ActionStoreMixin
from openjarvis.server.jarvis_agent.persistence.database import SQLiteDatabase
from openjarvis.server.jarvis_agent.persistence.edge_approvals import (
    EdgeApprovalStoreMixin,
)
from openjarvis.server.jarvis_agent.persistence.edge_devices import (
    EdgeDeviceStoreMixin,
)
from openjarvis.server.jarvis_agent.persistence.edge_jobs import EdgeJobStoreMixin
from openjarvis.server.jarvis_agent.persistence.edge_maintenance import (
    EdgeMaintenanceStoreMixin,
)
from openjarvis.server.jarvis_agent.persistence.memory import MemoryStoreMixin
from openjarvis.server.jarvis_agent.persistence.providers import ProviderStoreMixin
from openjarvis.server.jarvis_agent.persistence.sessions import SessionStoreMixin


class JarvisAgentStore(
    SessionStoreMixin,
    ActionStoreMixin,
    EdgeApprovalStoreMixin,
    EdgeDeviceStoreMixin,
    EdgeJobStoreMixin,
    EdgeMaintenanceStoreMixin,
    MemoryStoreMixin,
    ProviderStoreMixin,
    SQLiteDatabase,
):
    """Public repository facade assembled from focused persistence modules."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        super().__init__(path, busy_timeout_ms=busy_timeout_ms)
        self._last_edge_purge = 0.0
        self.recover_after_restart()
        self.expire()

    def recover_after_restart(self, now: float | None = None) -> dict[str, int]:
        """Fail closed for work whose process-local executor no longer exists."""

        timestamp = time.time() if now is None else now
        edge_recovery = self.recover_edge_after_restart(timestamp)
        with self._transaction() as connection:
            unknown_actions = connection.execute(
                """
                UPDATE jarvis_actions
                SET state = 'UNKNOWN', payload_json = NULL,
                    preview_json = '{}', updated_at = ?,
                    result_summary = 'O serviço reiniciou durante a execução.',
                    error_code = 'EXTERNAL_RESULT_UNKNOWN'
                WHERE state = 'DISPATCHING'
                  AND action_id NOT IN (
                    SELECT action_id FROM jarvis_edge_assignments
                    WHERE action_id IS NOT NULL
                      AND state IN ('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL')
                  )
                """,
                (timestamp,),
            ).rowcount
            unknown_jobs = connection.execute(
                """
                UPDATE jarvis_jobs
                SET state = 'UNKNOWN', updated_at = ?,
                    result_summary = 'O serviço reiniciou durante o trabalho.',
                    error_code = 'EXTERNAL_RESULT_UNKNOWN'
                WHERE state IN ('ACCEPTED', 'RUNNING')
                  AND job_id NOT IN (
                    SELECT job_id FROM jarvis_edge_assignments
                    WHERE state IN ('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL')
                  )
                """,
                (timestamp,),
            ).rowcount
            cancelled_actions = connection.execute(
                """
                UPDATE jarvis_actions
                SET state = 'CANCELLED', payload_json = NULL,
                    preview_json = '{}', updated_at = ?,
                    error_code = 'SESSION_CLOSED'
                WHERE state IN ('PROPOSED', 'AWAITING_APPROVAL', 'APPROVED')
                """,
                (timestamp,),
            ).rowcount
            closed_sessions = connection.execute(
                """
                UPDATE jarvis_sessions
                SET state = 'CLOSED', closed_at = ?, updated_at = ?
                WHERE state = 'ACTIVE'
                """,
                (timestamp, timestamp),
            ).rowcount
        return {
            **edge_recovery,
            "unknown_actions": unknown_actions,
            "unknown_jobs": unknown_jobs,
            "cancelled_actions": cancelled_actions,
            "closed_sessions": closed_sessions,
        }

    def expire(self, now: float | None = None) -> None:
        timestamp = time.time() if now is None else now
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM jarvis_context WHERE expires_at <= ?", (timestamp,)
            )
            connection.execute(
                "DELETE FROM jarvis_references WHERE expires_at <= ?", (timestamp,)
            )
            connection.execute(
                """
                UPDATE jarvis_actions SET state = 'EXPIRED', payload_json = NULL,
                    preview_json = '{}', updated_at = ?
                WHERE state = 'AWAITING_APPROVAL' AND expires_at <= ?
                """,
                (timestamp, timestamp),
            )
            connection.execute(
                """
                UPDATE jarvis_edge_approvals
                SET state = 'EXPIRED', decision = 'expired', decided_at = ?
                WHERE state = 'AWAITING_APPROVAL' AND expires_at <= ?
                """,
                (timestamp, timestamp),
            )
        if timestamp - self._last_edge_purge >= 3_600:
            self.purge_edge_retention(
                event_before=timestamp - 90 * 86_400,
                terminal_before=timestamp - 30 * 86_400,
                now=timestamp,
            )
            self._last_edge_purge = timestamp
