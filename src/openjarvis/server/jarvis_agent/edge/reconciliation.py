"""Reconcile terminal Edge results after a Core restart."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService


class EdgeResultReconciler:
    def __init__(
        self,
        store: JarvisAgentStore,
        context: ContextService,
        events: EventService,
    ) -> None:
        self._store = store
        self._context = context
        self._events = events

    def reconcile(
        self, assignment: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> None:
        action_id = assignment.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            return
        action = self._store.get_action(action_id)
        if action is None or action.get("state") != "DISPATCHING":
            self._events.emit(
                "edge_late_result_ignored",
                action_id=action_id,
                job_id=str(assignment["job_id"]),
                payload={"edge_state": terminal.get("state")},
            )
            return
        session = self._store.get_session(str(action["session_id"]))
        if session is None:
            return
        state = str(terminal.get("state") or "FAILED")
        action_state, job_state = self._canonical_states(state)
        summary = str(terminal.get("summary") or "")[:2_000]
        error_code = terminal.get("error_code")
        result = {
            "status": str(terminal.get("status") or state.lower()),
            "summary": summary,
            "references": dict(terminal.get("references") or {}),
        }
        now = time.time()
        self._store.update_action(
            action_id,
            action_state,
            now=now,
            result=result if action_state == "COMPLETED" else None,
            summary=summary,
            error_code=str(error_code) if error_code else None,
            clear_sensitive=True,
        )
        if self._store.get_job(str(assignment["job_id"])) is not None:
            self._store.update_job(
                str(assignment["job_id"]),
                job_state,
                now=now,
                result=result if job_state == "COMPLETED" else None,
                summary=summary,
                error_code=str(error_code) if error_code else None,
            )
        self._context.merge_result(
            project_key=str(session["project_key"]),
            codex_thread_id=str(session.get("codex_thread_id") or ""),
            tool_id=str(action["tool_id"]),
            summary=summary,
            status=str(result["status"]),
            trust="external_untrusted_data",
            references=result["references"],
        )
        self._events.emit(
            "job_completed" if action_state == "COMPLETED" else "job_failed",
            session_id=str(session["session_id"]),
            action_id=action_id,
            job_id=str(assignment["job_id"]),
            payload={
                "state": job_state,
                "error_code": error_code,
                "summary": summary[:500],
                "reconciled_after_restart": True,
            },
        )

    @staticmethod
    def _canonical_states(edge_state: str) -> tuple[str, str]:
        if edge_state == "SUCCEEDED":
            return "COMPLETED", "COMPLETED"
        if edge_state == "CANCELLED":
            return "CANCELLED", "CANCELLED"
        if edge_state == "UNKNOWN":
            return "UNKNOWN", "UNKNOWN"
        return "FAILED", "FAILED"


__all__ = ["EdgeResultReconciler"]
