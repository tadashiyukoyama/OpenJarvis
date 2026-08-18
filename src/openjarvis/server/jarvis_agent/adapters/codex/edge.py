"""Codex adapter that delegates execution to an authenticated Windows Edge."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    PreparedToolCall,
    payload_digest,
)
from openjarvis.server.jarvis_agent.edge.service import EdgeService
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(default="", max_length=20_000)
    limit: int = Field(default=16, ge=1, le=30)


class EdgeCodexAdapter:
    adapter_id = "codex"

    def __init__(self, edge: EdgeService) -> None:
        self._edge = edge

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        capabilities = self._edge.capabilities().intersection(
            {"codex.status", "codex.history", "codex.delegate"}
        )
        available = bool(capabilities)
        return {
            "codex_desktop": ProviderCapabilities(
                "codex_desktop",
                "available" if available else "unavailable",
                frozenset(capabilities),
                available,
                None if available else "edge_device_offline",
            )
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        args = self._parse(arguments)
        if tool_id != "codex.delegate":
            return PreparedToolCall(args.model_dump(), {})
        command = args.command.strip()
        thread_id = context.codex_thread_id.strip()
        project = context.project_key.strip()
        if not command or not thread_id or not self._absolute_project(project):
            raise JarvisAgentError(
                "INVALID_REQUEST", "Projeto, conversa e comando Codex são obrigatórios."
            )
        payload = {
            "project_cwd": project,
            "thread_id": thread_id,
            "command": command,
        }
        return PreparedToolCall(
            payload,
            {
                "destination": "Codex Desktop via Edge",
                "project": project,
                "thread_id": thread_id,
                "command": command,
                "risk": "Inicia uma tarefa real no Codex Desktop selecionado.",
            },
        )

    def preflight_delegate(self, arguments: Mapping[str, Any]) -> None:
        del arguments
        if self._edge.select_connection("codex.delegate") is None:
            raise JarvisAgentError(
                "DEVICE_OFFLINE",
                "O computador com Codex está offline.",
                status_code=503,
            )

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        if tool_id not in {"codex.status", "codex.history", "codex.delegate"}:
            raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta Codex desconhecida.")
        self._parse(arguments)
        result = self._edge.execute_job(
            tool_id=tool_id,
            arguments=arguments,
            context={
                "session_id": context.session_id,
                "partition_key": context.partition_key,
                "project_key": context.project_key,
                "codex_thread_id": context.codex_thread_id,
                "request_id": context.request_id,
            },
            payload_hash=payload_digest(
                {"tool_id": tool_id, "arguments": dict(arguments)}
            ),
            capability=tool_id,
            action_id=context.request_id,
            job_id=context.job_id,
        )
        data = result.get("data")
        references = result.get("references")
        return AdapterResult(
            str(result.get("status") or "completed"),
            str(result.get("summary") or "Operação Codex concluída."),
            dict(data) if isinstance(data, Mapping) else {},
            dict(references) if isinstance(references, Mapping) else {},
        )

    @staticmethod
    def _parse(arguments: Mapping[str, Any]) -> _Arguments:
        try:
            return _Arguments.model_validate(dict(arguments))
        except ValidationError as exc:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Os argumentos da ferramenta Codex são inválidos."
            ) from exc

    @staticmethod
    def _absolute_project(value: str) -> bool:
        return (
            PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()
        )


__all__ = ["EdgeCodexAdapter"]
