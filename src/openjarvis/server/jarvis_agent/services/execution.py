"""One-attempt dispatcher with canonical result and error transitions."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext, JarvisAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import ActionState
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import (
    JarvisToolCatalog,
    ProviderCapabilities,
)
from openjarvis.server.jarvis_agent.services.context import (
    ContextService,
    context_partition,
)
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.safety import durable_summary


class ExecutionService:
    def __init__(
        self,
        *,
        store: JarvisAgentStore,
        catalog: JarvisToolCatalog,
        adapters: Mapping[str, JarvisAdapter],
        context: ContextService,
        events: EventService,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._adapters = dict(adapters)
        self._context = context
        self._events = events

    def provider_capabilities(self) -> dict[str, ProviderCapabilities]:
        values: dict[str, ProviderCapabilities] = {}
        for adapter in self._adapters.values():
            values.update(adapter.provider_capabilities())
        values.setdefault(
            "hackernews",
            ProviderCapabilities(
                "hackernews",
                "preserved",
                frozenset(),
                True,
                "excluded_from_jarvis_manifest",
            ),
        )
        return values

    def execute(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        *,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        tool = self._catalog.resolve(str(action["tool_id"]))
        if tool is None or tool.adapter not in self._adapters:
            return self._fail(
                action,
                JarvisAgentError("TOOL_UNAVAILABLE", "Executor indisponível."),
                job_id=job_id,
            )
        payload = action.get("payload")
        if not isinstance(payload, Mapping):
            return self._fail(
                action,
                JarvisAgentError(
                    "APPROVAL_PAYLOAD_MISMATCH",
                    "O payload aprovado não está disponível.",
                ),
                job_id=job_id,
            )
        adapter_context = self._begin(action, session, tool, job_id)
        try:
            result = self._adapters[tool.adapter].execute(
                tool.tool_id, payload, adapter_context
            )
        except JarvisAgentError as exc:
            return self._fail(action, exc, job_id=job_id)
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            return self._fail(
                action,
                JarvisAgentError(
                    "EXTERNAL_RESULT_UNKNOWN",
                    "O executor não confirmou o resultado.",
                    status_code=502,
                ),
                job_id=job_id,
                cause=exc,
            )
        return self._complete(action, session, tool, payload, result, job_id)

    def _begin(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        tool: ToolDefinition,
        job_id: str | None,
    ) -> AdapterContext:
        self._store.update_action(
            action["action_id"], ActionState.DISPATCHING.value, now=time.time()
        )
        self._events.emit(
            "dispatch_started",
            session_id=action["session_id"],
            action_id=action["action_id"],
            job_id=job_id,
            payload={"tool_id": tool.tool_id, "payload_hash": action["payload_hash"]},
        )
        return AdapterContext(
            session_id=str(session["session_id"]),
            project_key=str(session["project_key"]),
            codex_thread_id=str(session.get("codex_thread_id") or ""),
            partition_key=context_partition(
                str(session["project_key"]), str(session.get("codex_thread_id") or "")
            ),
            request_id=str(action["action_id"]),
            job_id=job_id,
        )

    def _complete(
        self,
        action: Mapping[str, Any],
        session: Mapping[str, Any],
        tool: ToolDefinition,
        payload: Mapping[str, Any],
        result: AdapterResult,
        job_id: str | None,
    ) -> dict[str, Any]:
        result_data = result.as_dict()
        summary = durable_summary(result.summary, payload)
        persisted_result = result.persistence_dict(summary=summary)
        now = time.time()
        if result.action_state is ActionState.ACCEPTED:
            external = result.external_operation
            if external is None:
                return self._fail(
                    action,
                    JarvisAgentError(
                        "PROVIDER_RESPONSE_INVALID",
                        "O executor não informou a operação externa aceita.",
                    ),
                    job_id=job_id,
                )
            updated = self._store.accept_external_operation(
                action_id=str(action["action_id"]),
                provider=external.provider,
                resource_type=external.resource_type,
                resource_id=external.resource_id,
                result=persisted_result,
                summary=summary,
                now=now,
            )
        else:
            updated = self._store.update_action(
                action["action_id"],
                result.action_state.value,
                now=now,
                result=persisted_result,
                summary=summary,
                clear_sensitive=True,
            )
        effective_state = str((updated or {}).get("state") or result.action_state.value)
        effective_result = (updated or {}).get("result")
        effective_summary = str((updated or {}).get("result_summary") or summary)
        effective_status = result.status
        effective_references = result.references
        if isinstance(effective_result, Mapping):
            effective_status = str(effective_result.get("status") or effective_status)
            stored_references = effective_result.get("references")
            if isinstance(stored_references, Mapping):
                effective_references = {
                    str(key): str(value) for key, value in stored_references.items()
                }
        self._context.merge_result(
            project_key=str(session["project_key"]),
            codex_thread_id=str(session.get("codex_thread_id") or ""),
            tool_id=tool.tool_id,
            summary=effective_summary,
            status=effective_status,
            trust=(
                "external_untrusted_data"
                if tool.source in {"email", "gmail", "whatsapp", "codex"}
                else "internal_metadata"
            ),
            references=effective_references,
        )
        if job_id is None:
            event_type = (
                "dispatch_accepted"
                if effective_state == ActionState.ACCEPTED.value
                else (
                    "dispatch_failed"
                    if effective_state == ActionState.FAILED.value
                    else "dispatch_completed"
                )
            )
            self._events.emit(
                event_type,
                session_id=action["session_id"],
                action_id=action["action_id"],
                payload={
                    "tool_id": tool.tool_id,
                    "status": effective_status,
                    "summary": effective_summary[:500],
                },
            )
        response = dict(updated or action)
        reconciled_during_accept = (
            result.action_state is ActionState.ACCEPTED
            and effective_state != ActionState.ACCEPTED.value
        )
        response["result"] = (
            dict(effective_result)
            if reconciled_during_accept and isinstance(effective_result, Mapping)
            else result_data
        )
        response["_persisted_result"] = persisted_result
        return response

    def _fail(
        self,
        action: Mapping[str, Any],
        error: JarvisAgentError,
        *,
        job_id: str | None,
        cause: Exception | None = None,
    ) -> dict[str, Any]:
        del cause
        if error.code == "CODEX_BUSY":
            state = ActionState.BUSY
        elif error.code in {"EXTERNAL_RESULT_UNKNOWN", "CODEX_DISPATCH_TIMEOUT"}:
            state = ActionState.UNKNOWN
        else:
            state = ActionState.FAILED
        updated = self._store.update_action(
            action["action_id"],
            state.value,
            now=time.time(),
            summary=error.message,
            error_code=error.code,
            clear_sensitive=True,
        )
        if job_id is None:
            self._events.emit(
                "dispatch_failed",
                session_id=action.get("session_id"),
                action_id=action.get("action_id"),
                payload={"code": error.code, "state": state.value},
            )
        return updated or dict(action)
