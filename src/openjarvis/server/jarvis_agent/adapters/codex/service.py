"""Codex status, public history and exact task delegation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.codex import CodexAgentError
from openjarvis.core.conversation_identity import ConversationIdentity
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(default="", max_length=20_000)
    limit: int = Field(default=16, ge=1, le=30)


_CODE_MAP = {
    "CODEX_BUSY": "CODEX_BUSY",
    "CODEX_DUPLICATE_REQUEST": "DUPLICATE_ACTION",
    "CODEX_THREAD_NOT_FOUND": "CODEX_THREAD_INVALID",
    "CODEX_CONVERSATION_THREAD_SELECTION_INVALID": "CODEX_THREAD_INVALID",
    "CODEX_PROJECT_INVALID": "CODEX_THREAD_INVALID",
    "CODEX_THREAD_RESUME_TIMEOUT": "CODEX_THREAD_RESUME_TIMEOUT",
    "CODEX_THREAD_STATUS_TIMEOUT": "CODEX_THREAD_RESUME_TIMEOUT",
    "CODEX_CONVERSATION_BINDING_TIMEOUT": "CODEX_DISPATCH_TIMEOUT",
    "CODEX_CONVERSATION_THREAD_START_FAILED": "CODEX_DISPATCH_TIMEOUT",
    "CODEX_DISPATCH_TIMEOUT": "CODEX_DISPATCH_TIMEOUT",
    "CODEX_SESSION_CLOSED": "SESSION_CLOSED",
}

_CODE_STATUS = {
    "CODEX_BUSY": 409,
    "DUPLICATE_ACTION": 409,
    "CODEX_THREAD_INVALID": 409,
    "SESSION_CLOSED": 409,
    "CODEX_THREAD_RESUME_TIMEOUT": 504,
    "CODEX_DISPATCH_TIMEOUT": 504,
    "EXTERNAL_RESULT_UNKNOWN": 502,
}


class CodexAdapter:
    adapter_id = "codex"

    def __init__(
        self,
        runtime_getter: Callable[[], Any | None],
        agent_getter: Callable[[], Any | None],
    ) -> None:
        self._runtime_getter = runtime_getter
        self._agent_getter = agent_getter

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        runtime = self._runtime_getter()
        agent = self._agent_getter()
        available = bool(
            runtime is not None
            and callable(getattr(runtime, "thread_history_page", None))
            and agent is not None
            and callable(getattr(agent, "run", None))
        )
        capabilities = (
            frozenset({"codex.status", "codex.history", "codex.delegate"})
            if available
            else frozenset()
        )
        return {
            "codex_desktop": ProviderCapabilities(
                "codex_desktop",
                "available" if available else "unavailable",
                capabilities,
                available,
                None if available else "codex_runtime_unavailable",
            )
        }

    @staticmethod
    def _parse(arguments: Mapping[str, Any]) -> _Arguments:
        try:
            return _Arguments.model_validate(dict(arguments))
        except ValidationError as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Os argumentos da ferramenta Codex são inválidos."
            ) from exc

    def _require_runtime(self) -> tuple[Any, Any]:
        runtime = self._runtime_getter()
        agent = self._agent_getter()
        if runtime is None or agent is None:
            raise JarvisAgentError(
                "TOOL_UNAVAILABLE",
                "O Codex Desktop não está disponível.",
                status_code=503,
            )
        return runtime, agent

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        args = self._parse(arguments)
        if tool_id != "codex.delegate":
            return PreparedToolCall(args.model_dump(), {})
        if not args.command.strip() or not context.codex_thread_id.strip():
            raise JarvisAgentError(
                "INVALID_REQUEST", "Conversa e comando Codex são obrigatórios."
            )
        project = Path(context.project_key).expanduser()
        if not project.is_absolute() or not project.exists() or not project.is_dir():
            raise JarvisAgentError(
                "INVALID_REQUEST", "O projeto Codex selecionado é inválido."
            )
        payload = {
            "project_cwd": str(project.resolve()),
            "thread_id": context.codex_thread_id.strip(),
            "command": args.command.strip(),
        }
        preview = {
            "destination": "Codex Desktop",
            "project": str(project.resolve()),
            "thread_id": context.codex_thread_id.strip(),
            "command": args.command.strip(),
            "risk": "Inicia uma tarefa real no Codex Desktop selecionado.",
        }
        return PreparedToolCall(payload, preview)

    def preflight_delegate(self, arguments: Mapping[str, Any]) -> None:
        """Fail closed before accepting an asynchronous Codex job."""

        runtime, _ = self._require_runtime()
        thread_id = str(arguments.get("thread_id") or "").strip()
        try:
            if runtime.thread_is_busy(thread_id):
                raise JarvisAgentError(
                    "CODEX_BUSY",
                    "O Codex já está executando outra tarefa nesta conversa.",
                    status_code=409,
                )
        except JarvisAgentError:
            raise
        except Exception as exc:
            raise JarvisAgentError(
                "CODEX_THREAD_INVALID",
                "Não foi possível validar a conversa Codex.",
                status_code=409,
            ) from exc

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        runtime, agent = self._require_runtime()
        if tool_id == "codex.status":
            return self._status(arguments, context, runtime)
        if tool_id == "codex.history":
            return self._history(arguments, context, runtime)
        if tool_id == "codex.delegate":
            return self._delegate(arguments, context, agent)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta Codex desconhecida.")

    def _status(
        self, arguments: Mapping[str, Any], context: AdapterContext, runtime: Any
    ) -> AdapterResult:
        self._parse(arguments)
        if not context.codex_thread_id.strip():
            return AdapterResult("completed", "Codex Desktop disponível.")
        try:
            busy = bool(runtime.thread_is_busy(context.codex_thread_id.strip()))
        except Exception as exc:
            raise JarvisAgentError(
                "CODEX_THREAD_INVALID",
                "Não foi possível validar a conversa Codex.",
                status_code=409,
            ) from exc
        return AdapterResult(
            "completed", "Estado da conversa Codex consultado.", {"busy": busy}
        )

    def _history(
        self, arguments: Mapping[str, Any], context: AdapterContext, runtime: Any
    ) -> AdapterResult:
        args = self._parse(arguments)
        if not context.codex_thread_id.strip():
            raise JarvisAgentError(
                "CODEX_THREAD_INVALID",
                "Nenhuma conversa Codex está selecionada.",
                status_code=409,
            )
        try:
            page = runtime.thread_history_page(
                context.codex_thread_id.strip(),
                limit=args.limit,
                items_view="summary",
                timeout_seconds=10.0,
            )
        except Exception as exc:
            raise JarvisAgentError(
                "CODEX_THREAD_RESUME_TIMEOUT",
                "O histórico Codex não respondeu no prazo.",
                status_code=504,
            ) from exc
        messages = [
            {
                "role": message.role,
                "content": message.content[:8000],
                "timestamp": message.timestamp,
            }
            for message in page.history.messages[-args.limit :]
        ]
        return AdapterResult(
            "completed", "Histórico Codex carregado.", {"messages": messages}
        )

    @staticmethod
    def _delegate(
        arguments: Mapping[str, Any], context: AdapterContext, agent: Any
    ) -> AdapterResult:
        try:
            identity = ConversationIdentity(
                conversation_id=context.session_id,
                scope_id=context.partition_key,
            )
            result = agent.run(
                str(arguments["command"]),
                AgentContext(
                    conversation_identity=identity,
                    metadata={
                        "codex_thread_id": str(arguments["thread_id"]),
                        "codex_project_cwd": str(arguments["project_cwd"]),
                        "codex_client_user_message_id": context.request_id,
                    },
                ),
            )
            return AdapterResult(
                "completed",
                str(result.content)[:20_000],
                {"provider": "codex", "request_id": context.request_id},
            )
        except CodexAgentError as exc:
            code = _CODE_MAP.get(str(exc), "EXTERNAL_RESULT_UNKNOWN")
            raise JarvisAgentError(
                code,
                "O Codex não aceitou ou não concluiu a tarefa.",
                status_code=_CODE_STATUS[code],
            ) from exc
        except JarvisAgentError:
            raise
        except Exception as exc:
            raise JarvisAgentError(
                "EXTERNAL_RESULT_UNKNOWN",
                "O resultado da tarefa Codex é desconhecido.",
                status_code=502,
            ) from exc
