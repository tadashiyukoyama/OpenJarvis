"""Canonical Jarvis agent state machine and only tool dispatch authority."""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import JarvisAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.registry.policy import JarvisToolPolicy
from openjarvis.server.jarvis_agent.services.approvals import ApprovalService
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.decisions import DecisionService
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.execution import ExecutionService
from openjarvis.server.jarvis_agent.services.jobs import JobService
from openjarvis.server.jarvis_agent.services.proposals import ProposalService

if False:  # pragma: no cover - typing only, avoids a runtime import cycle
    from openjarvis.server.jarvis_agent.edge.service import EdgeService


class JarvisAgentOrchestrator:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        catalog: JarvisToolCatalog,
        adapters: Mapping[str, JarvisAdapter],
        context: ContextService | None = None,
        events: EventService | None = None,
        edge: "EdgeService | None" = None,
        mutations_enabled: bool = True,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.adapters = dict(adapters)
        self.context = context or ContextService(store)
        self.events = events or EventService(store)
        self.edge = edge
        self.mutations_enabled = mutations_enabled
        self.policy = JarvisToolPolicy(catalog)
        self.approvals = ApprovalService(store)
        self.execution = ExecutionService(
            store=store,
            catalog=catalog,
            adapters=adapters,
            context=self.context,
            events=self.events,
        )
        self.jobs = JobService(store, self.execution, self.events)
        self.proposals = ProposalService(
            store=store,
            catalog=catalog,
            adapters=adapters,
            policy=self.policy,
            context=self.context,
            events=self.events,
            execution=self.execution,
        )
        self.decisions = DecisionService(
            store=store,
            catalog=catalog,
            adapters=adapters,
            approvals=self.approvals,
            context=self.context,
            events=self.events,
            execution=self.execution,
            jobs=self.jobs,
        )
        self.acelerachat_webhooks: Any | None = None

    def catalog_snapshot(self) -> dict[str, Any]:
        self.store.expire()
        return self.catalog.snapshot(
            self.execution.provider_capabilities(),
            mutations_enabled=self.mutations_enabled,
        )

    def create_session(
        self, *, project_key: str, codex_thread_id: str = ""
    ) -> dict[str, Any]:
        project = project_key.strip()
        if not project or len(project) > 1024:
            raise JarvisAgentError(
                "INVALID_REQUEST", "O projeto selecionado é inválido."
            )
        snapshot = self.catalog_snapshot()
        now = time.time()
        session_id = f"jas_{uuid.uuid4().hex}"
        # JSON numbers are parsed as IEEE-754 doubles by browsers. Epoch
        # nanoseconds already exceed Number.MAX_SAFE_INTEGER and were rounded
        # by the frontend, so valid close/turn callbacks were rejected as
        # LATE_CALLBACK. Epoch microseconds remain exact and are sufficient
        # because session_id is the primary identity.
        generation = time.time_ns() // 1_000
        self.store.create_session(
            {
                "session_id": session_id,
                "generation": generation,
                "project_key": project,
                "codex_thread_id": codex_thread_id.strip(),
                "manifest_version": snapshot["version"],
                "state": "ACTIVE",
                "created_at": now,
            }
        )
        self.events.emit(
            "session_opened",
            session_id=session_id,
            payload={
                "generation": generation,
                "manifest_version": snapshot["version"],
            },
        )
        return {
            "session_id": session_id,
            "generation": generation,
            "state": "ACTIVE",
            "manifest_version": snapshot["version"],
            "manifest": snapshot["manifest"],
            "catalog": snapshot,
            "context": self.context.read(project, codex_thread_id),
        }

    def commit_turn(
        self,
        *,
        session_id: str,
        generation: int,
        turn_id: str,
        transcript: str,
    ) -> dict[str, Any]:
        self.store.expire()
        session = self._active_session(session_id, generation)
        text = transcript.strip()
        if not text or len(text) > 20_000:
            raise JarvisAgentError("INVALID_REQUEST", "A transcrição final é inválida.")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            self.store.add_turn(
                {
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "generation": generation,
                    "transcript_text": text,
                    "transcript_hash": digest,
                    "committed_at": time.time(),
                }
            )
        except sqlite3.IntegrityError:
            return {
                "turn_id": turn_id,
                "status": "duplicate",
                "transcript_hash": digest,
            }
        self.events.emit(
            "turn_committed",
            session_id=session_id,
            payload={
                "turn_id": turn_id,
                "transcript_hash": digest,
                "length": len(text),
            },
        )
        return {
            "turn_id": turn_id,
            "status": "committed",
            "transcript_hash": digest,
            "project_key": session["project_key"],
        }

    def propose(
        self,
        *,
        session_id: str,
        generation: int,
        function_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        self.store.expire()
        session = self._active_session(session_id, generation)
        return self.proposals.propose(
            session=session,
            function_call_id=function_call_id,
            tool_name=tool_name,
            arguments=arguments,
            turn_id=turn_id,
            current_snapshot=self.catalog_snapshot(),
        )

    def decide(
        self,
        *,
        action_id: str,
        session_id: str,
        payload_hash: str,
        decision: str,
    ) -> dict[str, Any]:
        self.store.expire()
        return self.decisions.decide(
            action_id=action_id,
            session_id=session_id,
            payload_hash=payload_hash,
            decision=decision,
        )

    def close_session(self, session_id: str, generation: int) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        pending_ids = self.store.pending_action_ids(session_id)
        if not self.store.close_session(session_id, generation, time.time()):
            if session is None:
                raise JarvisAgentError(
                    "SESSION_NOT_FOUND", "A sessão não existe.", status_code=404
                )
            if session["generation"] != generation:
                raise JarvisAgentError("LATE_CALLBACK", "Callback de sessão antiga.")
        if session is not None:
            for action_id in pending_ids:
                self.context.clear_pending(
                    str(session["project_key"]),
                    str(session.get("codex_thread_id") or ""),
                    action_id,
                )
        self.events.emit("session_closed", session_id=session_id)
        return {"session_id": session_id, "generation": generation, "state": "CLOSED"}

    def _active_session(self, session_id: str, generation: int) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if session is None:
            raise JarvisAgentError(
                "SESSION_NOT_FOUND", "A sessão não existe.", status_code=404
            )
        if session["generation"] != generation:
            self.events.emit(
                "late_callback_ignored",
                session_id=session_id,
                payload={"received_generation": generation},
            )
            raise JarvisAgentError("LATE_CALLBACK", "Callback de sessão antiga.")
        if session["state"] != "ACTIVE":
            raise JarvisAgentError("SESSION_CLOSED", "A sessão já foi encerrada.")
        return session

    def close(self) -> None:
        self.jobs.close()
        if self.acelerachat_webhooks is not None:
            self.acelerachat_webhooks.close()
        for adapter in self.adapters.values():
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    async def close_async(self) -> None:
        self.close()
        if self.edge is not None:
            await self.edge.close()
