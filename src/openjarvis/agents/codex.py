"""Codex external agent backed by the local Codex app-server runtime."""

from __future__ import annotations

import math
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
from openjarvis.integrations.codex_conversation import CodexConversationRuntime

CODEX_CONVERSATION_CONTEXT_REQUIRED = "CODEX_CONVERSATION_CONTEXT_REQUIRED"
CODEX_CONVERSATION_IDENTITY_REQUIRED = "CODEX_CONVERSATION_IDENTITY_REQUIRED"
CODEX_CONVERSATION_BINDING_TIMEOUT = "CODEX_CONVERSATION_BINDING_TIMEOUT"
CODEX_CONVERSATION_THREAD_START_FAILED = "CODEX_CONVERSATION_THREAD_START_FAILED"
CODEX_CONVERSATION_TURN_FAILED = "CODEX_CONVERSATION_TURN_FAILED"
CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT = "CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT"


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
        workspace: str | Path | None = None,
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
        if turn_wait_timeout_seconds is not None:
            self._turn_wait_timeout_seconds = self._positive_number(
                turn_wait_timeout_seconds, "turn_wait_timeout_seconds"
            )
        else:
            self._turn_wait_timeout_seconds = None
        self._workspace = str(workspace) if workspace is not None else None
        self._binding_wait = threading.Event()

    @staticmethod
    def _positive_number(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a positive finite number")
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        return result

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
        self._emit_turn_start(input)
        thread_id = self._resolve_thread(key)
        try:
            turn_kwargs: dict[str, object] = {}
            if self._workspace is not None:
                turn_kwargs["cwd"] = self._workspace
            turn = self._runtime.turn_start(thread_id, input, **turn_kwargs)
            turn_id = getattr(turn, "turn_id", None)
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise ValueError("turn start returned no public turn")
            if self._turn_wait_timeout_seconds is None:
                completed = self._runtime.wait_turn(thread_id, turn_id)
            else:
                completed = self._runtime.wait_turn(
                    thread_id,
                    turn_id,
                    timeout_seconds=self._turn_wait_timeout_seconds,
                )
        except BaseException as exc:
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
        if not content:
            metadata["error_code"] = CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT
            self._emit_turn_end(turns=1, error=True, status=status_value)
            return AgentResult(
                content=CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT,
                turns=1,
                metadata=metadata,
            )
        self._emit_turn_end(turns=1, status=status_value)
        return AgentResult(content=content, turns=1, metadata=metadata)


__all__ = [
    "CODEX_CONVERSATION_BINDING_TIMEOUT",
    "CODEX_CONVERSATION_CONTEXT_REQUIRED",
    "CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT",
    "CODEX_CONVERSATION_IDENTITY_REQUIRED",
    "CODEX_CONVERSATION_THREAD_START_FAILED",
    "CODEX_CONVERSATION_TURN_FAILED",
    "CodexAgent",
    "CodexAgentError",
]
