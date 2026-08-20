"""Immutable tool proposal creation and read dispatch."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext, JarvisAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import ToolDefinition, payload_digest
from openjarvis.server.jarvis_agent.domain.states import ActionState, Effect
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.registry.policy import JarvisToolPolicy
from openjarvis.server.jarvis_agent.services.context import (
    ContextService,
    context_partition,
)
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.execution import ExecutionService
from openjarvis.server.jarvis_agent.services.intent_routing import (
    validate_voice_tool_intent,
)
from openjarvis.server.jarvis_agent.services.presentation import public_action

_APPROVAL_TTL_SECONDS = 5 * 60


class ProposalService:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        catalog: JarvisToolCatalog,
        adapters: Mapping[str, JarvisAdapter],
        policy: JarvisToolPolicy,
        context: ContextService,
        events: EventService,
        execution: ExecutionService,
    ) -> None:
        self._store = store
        self._adapters = dict(adapters)
        self._policy = policy
        self._context = context
        self._events = events
        self._execution = execution

    def propose(
        self,
        *,
        session: Mapping[str, Any],
        function_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        turn_id: str | None,
        current_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            tool = self._policy.validate_call(
                name=tool_name,
                arguments=arguments,
                session_manifest_version=str(session["manifest_version"]),
                current_snapshot=current_snapshot,
            )
        except JarvisAgentError as error:
            self._record_rejection(session, code=error.code, requested_name=tool_name)
            raise
        adapter = self._adapters.get(tool.adapter)
        if adapter is None:
            raise JarvisAgentError("TOOL_UNAVAILABLE", "Executor indisponível.")
        prepared = adapter.prepare(
            tool.tool_id,
            arguments,
            self._adapter_context(session, function_call_id),
        )
        digest = payload_digest(
            {"tool_id": tool.tool_id, "arguments": dict(prepared.arguments)}
        )
        duplicate = self._store.get_action_by_request(
            session_id=str(session["session_id"]),
            function_call_id=function_call_id,
            payload_hash=digest,
        )
        turn = self._voice_turn(
            session,
            turn_id,
            allow_consumed=duplicate is not None,
        )
        if turn is not None:
            transcript = str(turn.get("transcript_text") or "")
            if transcript:
                try:
                    validate_voice_tool_intent(tool, transcript)
                except JarvisAgentError as error:
                    self._record_rejection(
                        session,
                        code=error.code,
                        requested_name=tool.gemini_name,
                        tool_id=tool.tool_id,
                    )
                    raise
        if duplicate is not None:
            if turn_id and turn and turn.get("transcript_text"):
                self._store.redact_turn(turn_id, time.time())
            self._emit_duplicate(session, duplicate, digest)
            return public_action(duplicate)
        action, created = self._create_action(
            session,
            function_call_id,
            tool,
            prepared.arguments,
            prepared.preview,
            digest,
        )
        if turn_id:
            self._store.redact_turn(turn_id, time.time())
        if not created:
            self._emit_duplicate(session, action, digest)
            return public_action(action)
        self._record_created(session, action, tool, digest)
        if tool.effect is Effect.READ:
            action = self._execution.execute(action, session)
        return public_action(action)

    def _voice_turn(
        self,
        session: Mapping[str, Any],
        turn_id: str | None,
        *,
        allow_consumed: bool = False,
    ) -> Mapping[str, Any] | None:
        if not turn_id:
            return None
        turn = self._store.get_turn(turn_id)
        if (
            turn is None
            or turn.get("session_id") != session.get("session_id")
            or turn.get("generation") != session.get("generation")
            or (not allow_consumed and not turn.get("transcript_text"))
        ):
            raise JarvisAgentError(
                "INVALID_REQUEST",
                "O turno final nao pertence a esta sessao ou ja foi consumido.",
            )
        return turn

    def _create_action(
        self,
        session: Mapping[str, Any],
        function_call_id: str,
        tool: ToolDefinition,
        arguments: Mapping[str, Any],
        preview: Mapping[str, Any],
        digest: str,
    ) -> tuple[dict[str, Any], bool]:
        now = time.time()
        state = (
            ActionState.AWAITING_APPROVAL
            if tool.requires_approval
            else ActionState.DISPATCHING
        )
        try:
            action, created = self._store.create_action(
                {
                    "action_id": f"act_{uuid.uuid4().hex}",
                    "session_id": session["session_id"],
                    "generation": session["generation"],
                    "function_call_id": function_call_id,
                    "tool_id": tool.tool_id,
                    "payload_hash": digest,
                    "payload": dict(arguments),
                    "preview": dict(preview),
                    "state": state.value,
                    "created_at": now,
                    "expires_at": now + _APPROVAL_TTL_SECONDS
                    if tool.requires_approval
                    else None,
                }
            )
        except sqlite3.IntegrityError as exc:
            if str(exc) == "ACTION_PENDING":
                raise JarvisAgentError(
                    "ACTION_PENDING",
                    "Já existe uma ação aguardando decisão visual.",
                    status_code=409,
                ) from exc
            raise
        return action, created

    def _record_created(
        self,
        session: Mapping[str, Any],
        action: Mapping[str, Any],
        tool: ToolDefinition,
        digest: str,
    ) -> None:
        project = str(session["project_key"])
        thread = str(session.get("codex_thread_id") or "")
        self._context.set_objective(
            project_key=project,
            codex_thread_id=thread,
            tool_id=tool.tool_id,
            action_id=str(action["action_id"]),
        )
        if tool.requires_approval:
            self._events.emit(
                "confirmation_requested",
                session_id=str(session["session_id"]),
                action_id=str(action["action_id"]),
                payload={"tool_id": tool.tool_id, "payload_hash": digest},
            )
            self._context.set_pending(
                project_key=project,
                codex_thread_id=thread,
                action_id=str(action["action_id"]),
                tool_id=tool.tool_id,
                status=ActionState.AWAITING_APPROVAL.value,
            )

    def _emit_duplicate(
        self,
        session: Mapping[str, Any],
        action: Mapping[str, Any],
        digest: str,
    ) -> None:
        self._events.emit(
            "duplicate_action",
            session_id=str(session["session_id"]),
            action_id=str(action["action_id"]),
            payload={"payload_hash": digest},
        )

    def _record_rejection(
        self,
        session: Mapping[str, Any],
        *,
        code: str,
        requested_name: str,
        tool_id: str = "",
    ) -> None:
        self._events.emit(
            "tool_call_rejected",
            session_id=str(session["session_id"]),
            payload={
                "code": code,
                "requested_name": requested_name[:128],
                **({"tool_id": tool_id} if tool_id else {}),
            },
        )

    @staticmethod
    def _adapter_context(session: Mapping[str, Any], request_id: str) -> AdapterContext:
        project = str(session["project_key"])
        thread = str(session.get("codex_thread_id") or "")
        return AdapterContext(
            session_id=str(session["session_id"]),
            project_key=project,
            codex_thread_id=thread,
            partition_key=context_partition(project, thread),
            request_id=request_id,
        )
