"""Codex external agent backed by the local Codex app-server runtime."""

from __future__ import annotations

import math
import ntpath
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.conversation_identity import (
    ConversationBindingKey,
    ConversationBindingState,
    ConversationBindingStore,
)
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentExecutionMode, AgentRegistry
from openjarvis.integrations.codex_conversation import (
    CodexConcurrentTurnError,
    CodexConversationClosed,
    CodexConversationRuntime,
    CodexConversationTimeout,
)
from openjarvis.integrations.codex_protocol import (
    CodexInvalidStateError,
    CodexRequestError,
    CodexRequestTimeout,
    is_codex_active_writer_error,
)

CODEX_CONVERSATION_CONTEXT_REQUIRED = "CODEX_CONVERSATION_CONTEXT_REQUIRED"
CODEX_CONVERSATION_IDENTITY_REQUIRED = "CODEX_CONVERSATION_IDENTITY_REQUIRED"
CODEX_CONVERSATION_BINDING_TIMEOUT = "CODEX_CONVERSATION_BINDING_TIMEOUT"
CODEX_CONVERSATION_THREAD_START_FAILED = "CODEX_CONVERSATION_THREAD_START_FAILED"
CODEX_CONVERSATION_THREAD_SELECTION_INVALID = (
    "CODEX_CONVERSATION_THREAD_SELECTION_INVALID"
)
CODEX_CONVERSATION_CLIENT_MESSAGE_INVALID = "CODEX_CONVERSATION_CLIENT_MESSAGE_INVALID"
CODEX_CONVERSATION_BUSY = "CODEX_BUSY"
CODEX_CONVERSATION_DUPLICATE_REQUEST = "CODEX_DUPLICATE_REQUEST"
CODEX_CONVERSATION_THREAD_NOT_FOUND = "CODEX_THREAD_NOT_FOUND"
CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT = "CODEX_THREAD_RESUME_TIMEOUT"
CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT = "CODEX_THREAD_STATUS_TIMEOUT"
CODEX_CONVERSATION_DISPATCH_TIMEOUT = "CODEX_DISPATCH_TIMEOUT"
CODEX_CONVERSATION_PROJECT_INVALID = "CODEX_PROJECT_INVALID"
CODEX_CONVERSATION_SESSION_CLOSED = "CODEX_SESSION_CLOSED"
CODEX_CONVERSATION_TURN_FAILED = "CODEX_CONVERSATION_TURN_FAILED"
CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT = "CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT"
_CODEX_APPROVAL_POLICIES = frozenset({"untrusted", "on-request", "never"})


class CodexAgentError(RuntimeError):
    """Sanitized, stable failure from the Codex agent boundary."""


def _default_owner_token() -> str:
    return secrets.token_urlsafe(24)


@AgentRegistry.register(
    "codex",
    execution_mode=AgentExecutionMode.EXTERNAL,
    requires_engine=False,
    requires_model=False,
    external_runtime="codex_app_server",
)
class CodexAgent(BaseAgent):
    """Run one public-text turn on a persistently bound Codex thread."""

    agent_id = "codex"
    accepts_tools = False

    def __init__(
        self,
        runtime: CodexConversationRuntime,
        binding_store: ConversationBindingStore,
        *,
        binding_wait_timeout_seconds: float = 5.0,
        binding_lease_seconds: float = 30.0,
        owner_token_factory: Callable[[], str] = _default_owner_token,
        turn_wait_timeout_seconds: float | None = None,
        turn_queue_timeout_seconds: float = 300.0,
        workspace: str | Path | None = None,
        approval_policy: str = "untrusted",
        bus: EventBus | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(
            None,
            None,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not isinstance(runtime, CodexConversationRuntime) and not all(
            hasattr(runtime, name)
            for name in ("thread_start", "turn_start", "wait_turn")
        ):
            raise TypeError("runtime must provide the Codex conversation contract")
        if not isinstance(binding_store, ConversationBindingStore) and not all(
            hasattr(binding_store, name)
            for name in (
                "lookup",
                "reserve",
                "complete_reservation",
                "release_reservation",
            )
        ):
            raise TypeError(
                "binding_store must provide the conversation binding contract"
            )
        self._runtime = runtime
        self._binding_store = binding_store
        self._binding_wait_timeout_seconds = self._positive_number(
            binding_wait_timeout_seconds, "binding_wait_timeout_seconds"
        )
        self._binding_lease_seconds = self._positive_number(
            binding_lease_seconds, "binding_lease_seconds"
        )
        if not callable(owner_token_factory):
            raise TypeError("owner_token_factory must be callable")
        self._owner_token_factory = owner_token_factory
        self._turn_queue_timeout_seconds = self._positive_number(
            turn_queue_timeout_seconds, "turn_queue_timeout_seconds"
        )
        self._turn_wait_timeout_seconds = (
            self._positive_number(
                turn_wait_timeout_seconds, "turn_wait_timeout_seconds"
            )
            if turn_wait_timeout_seconds is not None
            else self._turn_queue_timeout_seconds
        )
        self._workspace = str(workspace) if workspace is not None else None
        if approval_policy not in _CODEX_APPROVAL_POLICIES:
            raise ValueError("approval_policy is not supported")
        self._approval_policy = approval_policy
        self._binding_wait = threading.Event()
        self._validated_threads: set[tuple[str, str | None]] = set()
        self._thread_validation_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._active_requests: set[tuple[str, str, str, str]] = set()
        self._completed_requests: dict[
            tuple[str, str, str, str], tuple[float, AgentResult]
        ] = {}

    @staticmethod
    def _positive_number(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a positive finite number")
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        return result

    def _begin_idempotent_request(
        self,
        identity: object,
        thread_id: str,
        client_message_id: str | None,
    ) -> tuple[str, str, str, str] | None:
        if not isinstance(client_message_id, str) or not client_message_id.strip():
            return None
        conversation_id = getattr(identity, "conversation_id", "")
        scope_id = getattr(identity, "scope_id", "")
        key = (
            str(conversation_id),
            str(scope_id),
            thread_id,
            client_message_id.strip(),
        )
        now = time.monotonic()
        with self._request_lock:
            expired = [
                candidate
                for candidate, (expires_at, _) in self._completed_requests.items()
                if expires_at <= now
            ]
            for candidate in expired:
                self._completed_requests.pop(candidate, None)
            cached = self._completed_requests.get(key)
            if cached is not None:
                return key
            if key in self._active_requests:
                raise CodexAgentError(CODEX_CONVERSATION_DUPLICATE_REQUEST)
            self._active_requests.add(key)
        return key

    def _finish_idempotent_request(
        self,
        key: tuple[str, str, str, str] | None,
        result: AgentResult | None = None,
    ) -> None:
        if key is None:
            return
        with self._request_lock:
            self._active_requests.discard(key)
            if result is not None:
                self._completed_requests[key] = (time.monotonic() + 300.0, result)

    def _cached_idempotent_result(
        self, key: tuple[str, str, str, str] | None
    ) -> AgentResult | None:
        if key is None:
            return None
        with self._request_lock:
            cached = self._completed_requests.get(key)
            if cached is None:
                return None
            if cached[0] <= time.monotonic():
                self._completed_requests.pop(key, None)
                return None
            return cached[1]

    @staticmethod
    def _binding_id(binding: object) -> str | None:
        state = getattr(binding, "state", None)
        external_id = getattr(binding, "external_conversation_id", None)
        nested_binding = getattr(binding, "binding", None)
        if external_id is None and nested_binding is not None:
            external_id = getattr(nested_binding, "external_conversation_id", None)
        if state is ConversationBindingState.BOUND and isinstance(external_id, str):
            value = external_id.strip()
            return value or None
        return None

    def _resolve_thread(self, key: ConversationBindingKey) -> str:
        binding = self._binding_store.lookup(key)
        existing = self._binding_id(binding) if binding is not None else None
        if existing is not None:
            return existing

        owner_token = self._owner_token_factory()
        deadline = time.monotonic() + self._binding_wait_timeout_seconds
        while True:
            reservation = self._binding_store.reserve(
                key,
                owner_token,
                self._binding_lease_seconds,
            )
            existing = self._binding_id(reservation)
            if existing is not None:
                return existing

            if getattr(reservation, "acquired", False):
                try:
                    start_kwargs: dict[str, object] = {}
                    if self._workspace is not None:
                        start_kwargs["cwd"] = self._workspace
                    thread = self._runtime.thread_start(**start_kwargs)
                    started_id = getattr(thread, "thread_id", None)
                    if not isinstance(started_id, str) or not started_id.strip():
                        raise ValueError("thread start returned no public thread")
                    completed = self._binding_store.complete_reservation(
                        key,
                        owner_token,
                        started_id,
                    )
                    completed_id = self._binding_id(completed)
                    if completed_id is None:
                        raise ValueError("binding completion returned no bound thread")
                    return completed_id
                except BaseException as exc:
                    try:
                        self._binding_store.release_reservation(key, owner_token)
                    except BaseException:
                        pass
                    if isinstance(exc, CodexAgentError):
                        raise
                    raise CodexAgentError(
                        CODEX_CONVERSATION_THREAD_START_FAILED
                    ) from exc

            if getattr(reservation, "state", None) is not ConversationBindingState.BUSY:
                raise CodexAgentError(CODEX_CONVERSATION_THREAD_START_FAILED)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAgentError(CODEX_CONVERSATION_BINDING_TIMEOUT)
            self._binding_wait.wait(min(0.05, remaining))

            binding = self._binding_store.lookup(key)
            existing = self._binding_id(binding) if binding is not None else None
            if existing is not None:
                return existing
            if time.monotonic() >= deadline:
                raise CodexAgentError(CODEX_CONVERSATION_BINDING_TIMEOUT)

    def _validate_selected_thread(
        self,
        selected_thread_id: object,
        selected_project_cwd: object,
    ) -> str:
        """Validate a selected thread once through the lightweight live join."""
        if not isinstance(selected_thread_id, str) or not selected_thread_id.strip():
            raise CodexAgentError(CODEX_CONVERSATION_THREAD_NOT_FOUND)
        if selected_project_cwd is not None and (
            not isinstance(selected_project_cwd, str)
            or not selected_project_cwd.strip()
        ):
            raise CodexAgentError(CODEX_CONVERSATION_PROJECT_INVALID)

        thread_id = selected_thread_id.strip()
        project_cwd = selected_project_cwd or self._workspace
        validation_key = (thread_id, project_cwd)
        with self._thread_validation_lock:
            if validation_key in self._validated_threads:
                return thread_id

            subscribe_thread = getattr(self._runtime, "thread_subscribe", None)
            if not callable(subscribe_thread):
                raise CodexAgentError(CODEX_CONVERSATION_THREAD_NOT_FOUND)
            try:
                resumed = subscribe_thread(
                    thread_id,
                    timeout_seconds=self._binding_wait_timeout_seconds,
                )
            except (CodexConversationClosed, CodexInvalidStateError) as exc:
                raise CodexAgentError(CODEX_CONVERSATION_SESSION_CLOSED) from exc
            except (CodexRequestTimeout, CodexConversationTimeout) as exc:
                raise CodexAgentError(CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT) from exc
            except CodexRequestError as exc:
                if is_codex_active_writer_error(exc):
                    raise CodexAgentError(CODEX_CONVERSATION_BUSY) from exc
                raise CodexAgentError(CODEX_CONVERSATION_THREAD_NOT_FOUND) from exc
            except Exception as exc:
                raise CodexAgentError(
                    CODEX_CONVERSATION_THREAD_SELECTION_INVALID
                ) from exc

            if selected_project_cwd:
                actual_cwd = getattr(resumed, "cwd", None)
                if not isinstance(actual_cwd, str) or (
                    ntpath.normcase(ntpath.normpath(actual_cwd))
                    != ntpath.normcase(ntpath.normpath(project_cwd))
                ):
                    raise CodexAgentError(CODEX_CONVERSATION_PROJECT_INVALID)
            self._validated_threads.add(validation_key)
        return thread_id

    def run(
        self,
        input: str,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Send one input and return only the sanitized public Codex text."""
        del kwargs
        if not isinstance(input, str) or not input.strip():
            raise ValueError("CODEX_INPUT_REQUIRED")
        if context is None:
            raise ValueError(CODEX_CONVERSATION_CONTEXT_REQUIRED)
        identity = context.conversation_identity
        if identity is None:
            raise ValueError(CODEX_CONVERSATION_IDENTITY_REQUIRED)

        key = ConversationBindingKey(
            identity=identity,
            agent_name="codex",
            external_runtime="codex_app_server",
        )
        selected_thread_id = context.metadata.get("codex_thread_id")
        selected_project_cwd = context.metadata.get("codex_project_cwd")
        selected_client_message_id = context.metadata.get(
            "codex_client_user_message_id"
        )
        if selected_client_message_id is not None and (
            not isinstance(selected_client_message_id, str)
            or not selected_client_message_id.strip()
        ):
            raise CodexAgentError(CODEX_CONVERSATION_CLIENT_MESSAGE_INVALID)
        if selected_thread_id is not None:
            thread_id = self._validate_selected_thread(
                selected_thread_id,
                selected_project_cwd,
            )
        else:
            thread_id = self._resolve_thread(key)
        request_key = self._begin_idempotent_request(
            identity,
            thread_id,
            selected_client_message_id,
        )
        cached_result = self._cached_idempotent_result(request_key)
        if cached_result is not None:
            return cached_result
        turn_id: str | None = None
        status_check_completed = False
        try:
            thread_is_busy = getattr(self._runtime, "thread_is_busy", None)
            busy = callable(thread_is_busy) and thread_is_busy(thread_id)
            status_check_completed = True
            if busy:
                raise CodexAgentError(CODEX_CONVERSATION_BUSY)
            self._emit_turn_start(input)
            turn_kwargs: dict[str, object] = {
                "approval_policy": self._approval_policy,
            }
            turn_cwd = selected_project_cwd or self._workspace
            if turn_cwd is not None:
                turn_kwargs["cwd"] = turn_cwd
            if selected_client_message_id is not None:
                turn_kwargs["client_user_message_id"] = (
                    selected_client_message_id.strip()
                )
            try:
                turn = self._runtime.turn_start(thread_id, input, **turn_kwargs)
            except CodexConcurrentTurnError as exc:
                raise CodexAgentError(CODEX_CONVERSATION_BUSY) from exc
            turn_id = getattr(turn, "turn_id", None)
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("turn start returned no public turn")
            completed = self._runtime.wait_turn(
                thread_id,
                turn_id,
                timeout_seconds=self._turn_wait_timeout_seconds,
            )
        except (CodexConversationClosed, CodexInvalidStateError) as exc:
            self._finish_idempotent_request(request_key)
            self._emit_turn_end(turns=1, error=True)
            raise CodexAgentError(CODEX_CONVERSATION_SESSION_CLOSED) from exc
        except CodexRequestError as exc:
            self._finish_idempotent_request(request_key)
            self._emit_turn_end(turns=1, error=True)
            if is_codex_active_writer_error(exc):
                raise CodexAgentError(CODEX_CONVERSATION_BUSY) from exc
            raise CodexAgentError(CODEX_CONVERSATION_THREAD_NOT_FOUND) from exc
        except (CodexRequestTimeout, CodexConversationTimeout) as exc:
            if turn_id:
                interrupt_turn = getattr(self._runtime, "turn_interrupt", None)
                if callable(interrupt_turn):
                    try:
                        interrupt_turn(thread_id, turn_id)
                    except Exception:
                        pass
            self._finish_idempotent_request(request_key)
            self._emit_turn_end(turns=1, error=True)
            code = (
                CODEX_CONVERSATION_DISPATCH_TIMEOUT
                if status_check_completed
                else CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT
            )
            raise CodexAgentError(code) from exc
        except BaseException as exc:
            self._finish_idempotent_request(request_key)
            self._emit_turn_end(turns=1, error=True)
            if isinstance(exc, CodexAgentError):
                raise
            raise CodexAgentError(CODEX_CONVERSATION_TURN_FAILED) from exc

        status = getattr(completed, "status", "UNKNOWN")
        status_value = getattr(status, "value", status)
        status_value = str(status_value).upper()[:32]
        content = getattr(completed, "final_content", "")
        if not isinstance(content, str):
            content = ""
        content = self._strip_think_tags(content)
        metadata = {
            "provider": "codex",
            "external_runtime": "codex_app_server",
            "status": status_value,
        }
        if selected_client_message_id is not None:
            metadata["request_id"] = selected_client_message_id.strip()
        if not content:
            metadata["error_code"] = CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT
            self._emit_turn_end(turns=1, error=True, status=status_value)
            result = AgentResult(
                content=CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT,
                turns=1,
                metadata=metadata,
            )
            self._finish_idempotent_request(request_key, result)
            return result
        self._emit_turn_end(turns=1, status=status_value)
        result = AgentResult(content=content, turns=1, metadata=metadata)
        self._finish_idempotent_request(request_key, result)
        return result


__all__ = [
    "CODEX_CONVERSATION_BINDING_TIMEOUT",
    "CODEX_CONVERSATION_BUSY",
    "CODEX_CONVERSATION_CLIENT_MESSAGE_INVALID",
    "CODEX_CONVERSATION_CONTEXT_REQUIRED",
    "CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT",
    "CODEX_CONVERSATION_IDENTITY_REQUIRED",
    "CODEX_CONVERSATION_THREAD_START_FAILED",
    "CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT",
    "CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT",
    "CODEX_CONVERSATION_THREAD_SELECTION_INVALID",
    "CODEX_CONVERSATION_DISPATCH_TIMEOUT",
    "CODEX_CONVERSATION_DUPLICATE_REQUEST",
    "CODEX_CONVERSATION_PROJECT_INVALID",
    "CODEX_CONVERSATION_SESSION_CLOSED",
    "CODEX_CONVERSATION_THREAD_NOT_FOUND",
    "CODEX_CONVERSATION_TURN_FAILED",
    "CodexAgent",
    "CodexAgentError",
]
