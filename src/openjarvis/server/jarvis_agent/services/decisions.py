"""Visual approval decisions and their single execution transition."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import JarvisAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.states import ActionState, Effect
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.services.approvals import ApprovalService
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.execution import ExecutionService
from openjarvis.server.jarvis_agent.services.jobs import JobService
from openjarvis.server.jarvis_agent.services.presentation import (
    public_action,
    public_job,
)


class DecisionService:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        catalog: JarvisToolCatalog,
        adapters: Mapping[str, JarvisAdapter],
        approvals: ApprovalService,
        context: ContextService,
        events: EventService,
        execution: ExecutionService,
        jobs: JobService,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._adapters = dict(adapters)
        self._approvals = approvals
        self._context = context
        self._events = events
        self._execution = execution
        self._jobs = jobs

    def decide(
        self,
        *,
        action_id: str,
        session_id: str,
        payload_hash: str,
        decision: str,
    ) -> dict[str, Any]:
        action = self._approvals.decide(
            action_id=action_id,
            session_id=session_id,
            payload_hash=payload_hash,
            decision=decision,
        )
        session = self._store.get_session(session_id)
        if session is None:
            raise JarvisAgentError(
                "SESSION_NOT_FOUND", "A sessão não existe.", status_code=404
            )
        if action["state"] in {
            ActionState.DENIED.value,
            ActionState.EXPIRED.value,
        }:
            return self._reject(action, session)
        if action["state"] != ActionState.APPROVED.value:
            return public_action(action)
        return self._dispatch_approved(action, session, payload_hash)

    def _dispatch_approved(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        self._remember_decision(action, session, "approved")
        tool = self._catalog.resolve(str(action["tool_id"]))
        if tool is None:
            raise JarvisAgentError("TOOL_UNAVAILABLE", "Executor indisponível.")
        preflight_failure = self._preflight_codex(action, session, tool.tool_id)
        if preflight_failure is not None:
            return public_action(preflight_failure)
        claimed = self._store.transition_action(
            str(action["action_id"]),
            expected_state=ActionState.APPROVED.value,
            next_state=ActionState.DISPATCHING.value,
            now=time.time(),
        )
        if claimed is None:
            return public_action(
                self._store.get_action(str(action["action_id"])) or action
            )
        self._events.emit(
            "confirmation_accepted",
            session_id=str(session["session_id"]),
            action_id=str(action["action_id"]),
            payload={"payload_hash": payload_hash},
        )
        if tool.effect is Effect.DELEGATION:
            job = self._jobs.start(claimed, session)
            result = public_action(claimed)
            result["job"] = public_job(job)
            result["status"] = "accepted"
            return result
        return public_action(self._execution.execute(claimed, session))

    def _preflight_codex(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        tool_id: str,
    ) -> dict[str, Any] | None:
        if tool_id != "codex.delegate":
            return None
        preflight = getattr(self._adapters.get("codex"), "preflight_delegate", None)
        if not callable(preflight):
            return None
        try:
            preflight(action.get("payload") or {})
            return None
        except JarvisAgentError as exc:
            state = ActionState.BUSY if exc.code == "CODEX_BUSY" else ActionState.FAILED
            failed = self._store.update_action(
                str(action["action_id"]),
                state.value,
                now=time.time(),
                summary=exc.message,
                error_code=exc.code,
                clear_sensitive=True,
            )
            self._events.emit(
                "dispatch_rejected_busy"
                if state is ActionState.BUSY
                else "dispatch_failed",
                session_id=str(session["session_id"]),
                action_id=str(action["action_id"]),
                payload={"code": exc.code, "state": state.value},
            )
            return failed or dict(action)

    def _reject(
        self, action: Mapping[str, Any], session: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._remember_decision(action, session, str(action["state"]).lower())
        self._events.emit(
            "confirmation_rejected",
            session_id=str(session["session_id"]),
            action_id=str(action["action_id"]),
            payload={"state": action["state"]},
        )
        return public_action(action)

    def _remember_decision(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        decision: str,
    ) -> None:
        project = str(session["project_key"])
        thread = str(session.get("codex_thread_id") or "")
        self._context.record_decision(
            project_key=project,
            codex_thread_id=thread,
            action_id=str(action["action_id"]),
            tool_id=str(action["tool_id"]),
            decision=decision,
        )
        self._context.clear_pending(project, thread, str(action["action_id"]))
