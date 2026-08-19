"""Typed local Codex app-server executor used only by the Edge Worker."""

from __future__ import annotations

import logging
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
from openjarvis.integrations.codex_conversation import (
    CodexConversationClosed,
    CodexConversationRuntime,
    CodexConversationTimeout,
)
from openjarvis.integrations.codex_protocol import (
    CodexAppServerConfig,
    CodexConversationEvent,
    CodexInvalidStateError,
    CodexRequestError,
    CodexRequestTimeout,
    is_codex_active_writer_error,
)

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

logger = logging.getLogger(__name__)

_HISTORY_MAX_ITEMS = 30
_HISTORY_CONTENT_BUDGET_BYTES = 128 * 1024
_HISTORY_MESSAGE_MAX_BYTES = 8 * 1024


def _bounded_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    if max_bytes <= 0:
        return "", True
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _subscribe_thread_or_raise(
    runtime: CodexConversationRuntime,
    thread_id: str,
    *,
    timeout_seconds: float,
) -> None:
    try:
        runtime.thread_subscribe(thread_id, timeout_seconds=timeout_seconds)
    except (CodexConversationClosed, CodexInvalidStateError) as exc:
        raise RuntimeError("SESSION_CLOSED") from exc
    except (CodexRequestTimeout, CodexConversationTimeout) as exc:
        raise RuntimeError("CODEX_THREAD_RESUME_TIMEOUT") from exc
    except CodexRequestError as exc:
        code = (
            "CODEX_BUSY"
            if is_codex_active_writer_error(exc)
            else "CODEX_THREAD_INVALID"
        )
        raise RuntimeError(code) from exc
    except ValueError as exc:
        raise RuntimeError("CODEX_THREAD_INVALID") from exc


class CodexEdgeExecutor:
    capabilities = frozenset(
        {
            "codex.status",
            "codex.history",
            "codex.catalog",
            "codex.subscribe",
            "codex.desktop_refresh",
            "codex.delegate",
        }
    )

    def __init__(
        self,
        config: EdgeWorkerConfig,
        approvals: CodexApprovalBridge,
        event_sink: Callable[[CodexConversationEvent], None] | None = None,
        event_flush: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._approvals = approvals
        self._lock = threading.RLock()
        self._client: CodexAppServerClient | None = None
        self._runtime: CodexConversationRuntime | None = None
        self._agent: CodexAgent | None = None
        self._event_sink = event_sink
        self._event_flush = event_flush
        self._event_subscription: int | None = None

    def set_event_sink(
        self,
        event_sink: Callable[[CodexConversationEvent], None],
        event_flush: Callable[[], None] | None = None,
    ) -> None:
        if not callable(event_sink):
            raise TypeError("Codex event sink must be callable")
        with self._lock:
            if self._client is not None:
                raise RuntimeError("Codex event sink must be set before startup")
            self._event_sink = event_sink
            self._event_flush = event_flush

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
            if self._event_sink is not None:
                self._event_subscription = runtime.subscribe_events(self._event_sink)

    def close(self) -> None:
        with self._lock:
            runtime, client = self._runtime, self._client
            subscription = self._event_subscription
            self._runtime = None
            self._agent = None
            self._client = None
            self._event_subscription = None
        if runtime is not None:
            if subscription is not None:
                runtime.unsubscribe_events(subscription)
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
        if tool_id == "codex.subscribe":
            return self._subscribe(runtime, arguments, context)
        if tool_id == "codex.desktop_refresh":
            return self._desktop_refresh(runtime, context)
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
        limit = min(_HISTORY_MAX_ITEMS, max(1, int(arguments.get("limit") or 16)))
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
        remaining = _HISTORY_CONTENT_BUDGET_BYTES
        messages: list[dict[str, Any]] = []
        for item in page.history.messages[-limit:]:
            content, truncated = _bounded_utf8(
                item.content,
                min(_HISTORY_MESSAGE_MAX_BYTES, remaining),
            )
            remaining -= len(content.encode("utf-8"))
            messages.append(
                {
                    "message_id": item.message_id,
                    "role": item.role,
                    "content": content,
                    "content_truncated": truncated,
                    "timestamp": item.timestamp,
                }
            )
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

    @staticmethod
    def _subscribe(
        runtime: CodexConversationRuntime,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(context.get("codex_thread_id") or "").strip()
        if not thread_id:
            raise ValueError("Codex thread is required")
        timeout_seconds = min(
            10.0,
            max(1.0, float(arguments.get("timeout_seconds") or 10.0)),
        )
        _subscribe_thread_or_raise(
            runtime,
            thread_id,
            timeout_seconds=timeout_seconds,
        )
        return {
            "status": "completed",
            "summary": "Conversa Codex assinada no worker.",
            "data": {"subscribed": True},
            "references": {"thread_id": thread_id},
        }

    @staticmethod
    def _desktop_refresh(
        runtime: CodexConversationRuntime, context: Mapping[str, Any]
    ) -> dict[str, Any]:
        from openjarvis.integrations.codex_desktop import (
            open_codex_thread_in_desktop,
        )

        thread_id = str(context.get("codex_thread_id") or "").strip()
        if not thread_id:
            raise ValueError("Codex thread is required")
        _subscribe_thread_or_raise(runtime, thread_id, timeout_seconds=10.0)
        uri = open_codex_thread_in_desktop(thread_id)
        return {
            "status": "completed",
            "summary": "Conversa remontada no Codex Desktop.",
            "data": {"refreshed": True, "uri": uri},
            "references": {"thread_id": thread_id},
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
        finally:
            event_flush = getattr(self, "_event_flush", None)
            if event_flush is not None:
                try:
                    event_flush()
                except Exception as exc:
                    logger.warning(
                        "Codex public event flush failed; history will reconcile: %s",
                        type(exc).__name__,
                    )
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
