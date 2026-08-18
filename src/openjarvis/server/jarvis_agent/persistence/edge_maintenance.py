"""Restart recovery and bounded retention for the Edge boundary."""

from __future__ import annotations


class EdgeMaintenanceStoreMixin:
    def recover_edge_after_restart(self, now: float) -> dict[str, int]:
        with self._transaction() as connection:
            offline_devices = connection.execute(
                """
                UPDATE jarvis_edge_devices SET status = 'OFFLINE',
                    disconnected_at = ?, updated_at = ?
                WHERE status = 'ONLINE'
                """,
                (now, now),
            ).rowcount
            abandoned_rows = connection.execute(
                """
                SELECT job_id, action_id FROM jarvis_edge_assignments
                WHERE state = 'OFFERED'
                """
            ).fetchall()
            for row in abandoned_rows:
                if row["action_id"] is not None:
                    connection.execute(
                        """
                        UPDATE jarvis_actions SET state = 'FAILED',
                            payload_json = NULL, preview_json = '{}',
                            updated_at = ?, result_summary =
                                'O worker ficou offline antes de aceitar o job.',
                            error_code = 'DEVICE_OFFLINE'
                        WHERE action_id = ? AND state = 'DISPATCHING'
                        """,
                        (now, row["action_id"]),
                    )
                connection.execute(
                    """
                    UPDATE jarvis_jobs SET state = 'FAILED', updated_at = ?,
                        result_summary =
                            'O worker ficou offline antes de aceitar o job.',
                        error_code = 'DEVICE_OFFLINE'
                    WHERE job_id = ? AND state IN ('ACCEPTED', 'RUNNING')
                    """,
                    (now, row["job_id"]),
                )
            abandoned = connection.execute(
                """
                UPDATE jarvis_edge_assignments
                SET state = 'FAILED', updated_at = ?, error_code = 'DEVICE_OFFLINE',
                    result_summary = 'O worker ficou offline antes de aceitar o job.'
                WHERE state = 'OFFERED'
                """,
                (now,),
            ).rowcount
            connection.execute(
                """
                UPDATE jarvis_edge_attempts SET state = 'FAILED', updated_at = ?
                WHERE state = 'OFFERED'
                """,
                (now,),
            )
            return {"offline_devices": offline_devices, "abandoned_offers": abandoned}

    def purge_edge_retention(
        self, *, event_before: float, terminal_before: float, now: float
    ) -> dict[str, int]:
        with self._transaction() as connection:
            redacted = connection.execute(
                """
                UPDATE jarvis_edge_assignments SET result_json = NULL,
                    sensitive_purge_at = NULL, updated_at = ?
                WHERE sensitive_purge_at IS NOT NULL AND sensitive_purge_at <= ?
                """,
                (now, now),
            ).rowcount
            events = connection.execute(
                "DELETE FROM jarvis_edge_events WHERE received_at < ?",
                (event_before,),
            ).rowcount
            transient_job_ids = [
                str(row["job_id"])
                for row in connection.execute(
                    """
                    SELECT job_id FROM jarvis_edge_assignments
                    WHERE updated_at < ? AND state IN
                        ('SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'UNKNOWN')
                      AND action_id IS NULL
                    """,
                    (terminal_before,),
                ).fetchall()
            ]
            for job_id in transient_job_ids:
                connection.execute(
                    "DELETE FROM jarvis_edge_approvals WHERE job_id = ?",
                    (job_id,),
                )
                connection.execute(
                    "DELETE FROM jarvis_edge_attempts WHERE job_id = ?",
                    (job_id,),
                )
            assignments = connection.execute(
                """
                DELETE FROM jarvis_edge_assignments
                WHERE updated_at < ? AND state IN
                    ('SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED', 'UNKNOWN')
                  AND action_id IS NULL
                """,
                (terminal_before,),
            ).rowcount
            return {
                "redacted_results": redacted,
                "events": events,
                "transient_assignments": assignments,
            }


__all__ = ["EdgeMaintenanceStoreMixin"]
