"""Typed local Codex app-server executor used only by the Edge Worker."""

from __future__ import annotations

import ntpath
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.codex import (
    CODEX_CONVERSATION_BUSY,
    CODEX_CONVERSATION_DISPATCH_TIMEOUT,
    CODEX_CONVERSATION_DUPLICATE_REQUEST,
    CODEX_CONVERSATION_PROJECT_INVALID,
    CODEX_CONVERSATION_SESSION_CLOSED,
    CODEX_CONVERSATION_THREAD_NOT_FOUND,
    CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT,
    CODEX_CONVERSATION_THREAD_SELECTION_INVALID,
    CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT,
    CodexAgent,
    CodexAgentError,
)
from openjarvis.core.conversation_identity import (
    ConversationIdentity,
    SQLiteConversationBindingStore,
)
from openjarvis.edge_worker.approvals import CodexApprovalBridge
from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.integrations.codex_app_server import CodexAppServerClient
from openjarvis.integrations.codex_conversation import CodexConversationRuntime
from openjarvis.integrations.codex_protocol import CodexAppServerConfig

_ERROR_MAP = {
    CODEX_CONVERSATION_BUSY: "CODEX_BUSY",
    CODEX_CONVERSATION_THREAD_NOT_FOUND: "CODEX_THREAD_INVALID",
    CODEX_CONVERSATION_THREAD_SELECTION_INVALID: "CODEX_THREAD_INVALID",
    CODEX_CONVERSATION_PROJECT_INVALID: "CODEX_THREAD_INVALID",
    CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT: "CODEX_THREAD_RESUME_TIMEOUT",
    CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT: "CODEX_THREAD_STATUS_TIMEOUT",
    CODEX_CONVERSATION_DISPATCH_TIMEOUT: "CODEX_DISPATCH_TIMEOUT",
    CODEX_CONVERSATION_DUPLICATE_REQUEST: "DUPLICATE_ACTION",
    CODEX_CONVERSATION_SESSION_CLOSED: "SESSION_CLOSED",
}


class CodexEdgeExecutor:
    capabilities = frozenset(
        {"codex.status", "codex.history", "codex.catalog", "codex.delegate"}
    )

    def __init__(
        self,
        config: EdgeWorkerConfig,
        approvals: CodexApprovalBridge,
    ) -> None:
        self._config = config
        self._approvals = approvals
        self._lock = threading.RLock()
        self._client: CodexAppServerClient | None = None
        self._runtime: CodexConversationRuntime | None = None
        self._agent: CodexAgent | None = None

    def start(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            client = CodexAppServerClient(
                CodexAppServerConfig(
                    websocket_url=self._config.app_server_url,
                    reject_unhandled_server_requests=True,
                    experimental_api=True,
                    request_timeout_seconds=30.0,
                )
            )
            client.set_server_request_handler(self._approvals.handle)
            client.start()
            runtime = CodexConversationRuntime(client)
            bindings = SQLiteConversationBindingStore(self._config.binding_path)
            self._client = client
            self._runtime = runtime
            self._agent = CodexAgent(
                runtime,
                bindings,
                approval_policy="untrusted",
                turn_wait_timeout_seconds=self._config.job_timeout_seconds,
                turn_queue_timeout_seconds=self._config.job_timeout_seconds,
            )

    def close(self) -> None:
        with self._lock:
            runtime, client = self._runtime, self._client
            self._runtime = None
            self._agent = None
            self._client = None
        if runtime is not None:
            runtime.close()
        if client is not None:
            client.close()

    def execute(
        self,
        *,
        tool_id: str,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
        job_id: str,
        attempt_id: str,
        progress: Callable[[str, str], None],
    ) -> dict[str, Any]:
        self.start()
        runtime, agent = self._require_runtime()
        if tool_id == "codex.status":
            return self._status(runtime, context)
        if tool_id == "codex.history":
            return self._history(runtime, arguments, context)
        if tool_id == "codex.catalog":
            return self._catalog(runtime)
        if tool_id == "codex.delegate":
            progress("validating", "Validando projeto e conversa Codex.")
            with self._approvals.activate(job_id, attempt_id):
                return self._delegate(agent, arguments, context)
        raise ValueError("unsupported Edge capability")

    def _require_runtime(self) -> tuple[CodexConversationRuntime, CodexAgent]:
        with self._lock:
            if self._runtime is None or self._agent is None:
                raise RuntimeError("Codex app-server is not ready")
            return self._runtime, self._agent

    @staticmethod
    def _status(
        runtime: CodexConversationRuntime, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        thread_id = str(context.get("codex_thread_id") or "").strip()
        busy = runtime.thread_is_busy(thread_id) if thread_id else False
        return {
            "status": "completed",
            "summary": "Estado do Codex Desktop consultado.",
            "data": {"connected": True, "busy": busy},
            "references": {},
        }

    @staticmethod
    def _history(
        runtime: CodexConversationRuntime,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(context.get("codex_thread_id") or "").strip()
        if not thread_id:
            raise ValueError("Codex thread is required")
        limit = min(100, max(1, int(arguments.get("limit") or 16)))
        cursor = arguments.get("cursor")
        cursor = cursor if isinstance(cursor, str) and cursor else None
        items_view = arguments.get("items_view")
        items_view = items_view if items_view in {"summary", "full"} else "summary"
        page = runtime.thread_history_page(
            thread_id,
            cursor=cursor,
            limit=limit,
            items_view=items_view,
            timeout_seconds=10.0,
        )
        messages = [
            {
                "message_id": item.message_id,
                "role": item.role,
                "content": item.content[:8_000],
                "timestamp": item.timestamp,
            }
            for item in page.history.messages[-limit:]
        ]
        return {
            "status": "completed",
            "summary": "Histórico Codex carregado.",
            "data": {
                "messages": messages,
                "next_cursor": page.next_cursor,
                "backwards_cursor": page.backwards_cursor,
            },
            "references": {"thread_id": thread_id},
        }

    @staticmethod
    def _catalog(runtime: CodexConversationRuntime) -> dict[str, Any]:
        threads: list[Any] = []
        cursor: str | None = None
        for _ in range(20):
            page = runtime.thread_list(cursor=cursor, limit=100)
            threads.extend(page.threads)
            if not page.next_cursor or page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        data = [
            {
                "thread_id": item.thread_id,
                "cwd": item.cwd,
                "status": item.status,
                "metadata": dict(item.metadata),
            }
            for item in threads
            if item.cwd
        ]
        return {
            "status": "completed",
            "summary": "Catálogo Codex carregado.",
            "data": {"threads": data},
            "references": {},
        }

    def _delegate(
        self,
        agent: CodexAgent,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        project = str(arguments.get("project_cwd") or "").strip()
        thread_id = str(arguments.get("thread_id") or "").strip()
        command = str(arguments.get("command") or "").strip()
        self._validate_project(project)
        if not thread_id or not command:
            raise ValueError("Codex thread and command are required")
        identity = ConversationIdentity(
            conversation_id=str(context.get("session_id") or "edge"),
            scope_id=str(context.get("partition_key") or "edge"),
        )
        try:
            result = agent.run(
                command,
                AgentContext(
                    conversation_identity=identity,
                    metadata={
                        "codex_thread_id": thread_id,
                        "codex_project_cwd": project,
                        "codex_client_user_message_id": str(
                            context.get("request_id") or ""
                        ),
                    },
                ),
            )
        except CodexAgentError as exc:
            raise RuntimeError(
                _ERROR_MAP.get(str(exc), "EXTERNAL_RESULT_UNKNOWN")
            ) from exc
        return {
            "status": "completed",
            "summary": str(result.content)[:20_000],
            "data": {"provider": "codex"},
            "references": {"thread_id": thread_id},
        }

    def _validate_project(self, project: str) -> None:
        normalized = ntpath.normcase(ntpath.normpath(project))
        allowed = any(
            normalized == ntpath.normcase(ntpath.normpath(root))
            or normalized.startswith(ntpath.normcase(ntpath.normpath(root)) + "\\")
            for root in self._config.project_roots
        )
        if not allowed or not Path(project).is_dir():
            raise ValueError("Codex project is outside the allowed roots")


__all__ = ["CodexEdgeExecutor"]
