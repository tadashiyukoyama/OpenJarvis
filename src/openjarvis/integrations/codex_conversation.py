"""Stable conversation contracts layered over an already-ready Codex client.

This module intentionally does not own a process, credentials, or a client
lifecycle.  It accepts only an already-started ``CodexAppServerClient`` and
keeps the app-server's raw JSON-RPC envelopes behind sanitized immutable
objects.  Reasoning notifications and private item fields are ignored.
"""

from __future__ import annotations

import ntpath
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from .codex_app_server import CodexAppServerClient
from .codex_protocol import (
    CodexAppServerError,
    CodexAppServerState,
    CodexConversationEvent,
    CodexCwdStatus,
    CodexInvalidStateError,
    CodexThreadInfo,
    CodexThreadListResult,
    CodexTurnInfo,
    CodexTurnResult,
    CodexTurnStatus,
    JsonRpcNotification,
)


class CodexConversationError(CodexAppServerError):
    """Base error for the conversation layer."""


class CodexConversationProtocolError(CodexConversationError):
    """The stable conversation response did not match its schema."""


class CodexConversationTimeout(CodexConversationError):
    """A targeted turn did not reach a terminal event before its deadline."""


class CodexConversationClosed(CodexConversationError):
    """The conversation runtime was closed while a caller was waiting."""


class CodexConversationClientFailed(CodexConversationError):
    """The underlying client failed while a caller was waiting."""


class CodexConcurrentTurnError(CodexConversationError):
    """The server-facing contract does not permit same-thread concurrency."""


_KNOWN_EVENT_METHOD = re.compile(r"^[A-Za-z0-9_./-]{1,96}$")
_KNOWN_ITEM_TYPES = frozenset(
    {
        "agentMessage",
        "commandExecution",
        "fileChange",
        "reasoning",
        "userMessage",
        "webSearch",
    }
)
_PUBLIC_USAGE_KEYS = frozenset(
    {
        "cachedInputTokens",
        "inputTokens",
        "outputTokens",
        "reasoningTokens",
        "totalTokens",
        "cached_input_tokens",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    }
)
_PUBLIC_THREAD_METADATA = frozenset(
    {
        "createdAt",
        "ephemeral",
        "modelProvider",
        "name",
        "preview",
        "source",
        "updatedAt",
    }
)
_PUBLIC_TURN_METADATA = frozenset({"completedAt", "durationMs", "startedAt"})
_MAX_EVENTS_PER_TURN = 256
_MAX_EARLY_EVENTS = 256
_MAX_COMPLETED_TURNS = 128


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_method(method: object) -> str:
    if (
        isinstance(method, str)
        and _KNOWN_EVENT_METHOD.fullmatch(method)
        and method.startswith(("thread/", "turn/", "item/"))
    ):
        return method
    return "unknown"


def _safe_metadata(
    source: Mapping[str, object], allowlist: frozenset[str]
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in allowlist:
        value = source.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[key] = value
        elif isinstance(value, dict) and key == "source":
            source_type = value.get("type")
            if isinstance(source_type, str) and source_type:
                metadata[key] = {"type": source_type[:64]}
    return metadata


def _normalize_windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value.replace("/", "\\")))


def _cwd_status(value: object, expected: str | None) -> CodexCwdStatus:
    if value is None:
        return CodexCwdStatus.ABSENT
    if not isinstance(value, str) or not value:
        return CodexCwdStatus.UNVERIFIED
    if expected is None:
        return CodexCwdStatus.UNVERIFIED
    if _normalize_windows_path(value) == _normalize_windows_path(expected):
        return CodexCwdStatus.EXPECTED
    return CodexCwdStatus.UNEXPECTED


def _turn_status(value: object, *, starting: bool = False) -> CodexTurnStatus:
    if not isinstance(value, str):
        return CodexTurnStatus.STARTING if starting else CodexTurnStatus.UNKNOWN
    return {
        "pending": CodexTurnStatus.STARTING,
        "starting": CodexTurnStatus.STARTING,
        "inProgress": CodexTurnStatus.RUNNING,
        "running": CodexTurnStatus.RUNNING,
        "completed": CodexTurnStatus.COMPLETED,
        "failed": CodexTurnStatus.FAILED,
        "interrupted": CodexTurnStatus.INTERRUPTED,
        "cancelled": CodexTurnStatus.CANCELLED,
    }.get(value, CodexTurnStatus.UNKNOWN)


def _is_terminal(status: CodexTurnStatus) -> bool:
    return status in {
        CodexTurnStatus.COMPLETED,
        CodexTurnStatus.FAILED,
        CodexTurnStatus.INTERRUPTED,
        CodexTurnStatus.CANCELLED,
    }


def _safe_error_message(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    # Error text is public operational metadata only; do not retain large or
    # credential-shaped values in the domain result.
    sanitized = re.sub(
        r"(?i)(bearer\s+|(?:token|secret|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        value,
    )
    return sanitized[:512]


def _public_usage(source: object) -> dict[str, object]:
    if not isinstance(source, dict):
        return {}
    usage: dict[str, object] = {}
    candidates = [source]
    for key in ("usage", "tokenUsage", "token_usage"):
        value = source.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        for key in _PUBLIC_USAGE_KEYS:
            value = candidate.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = value
    return usage


def _item_from_params(params: Mapping[str, object]) -> dict[str, object] | None:
    item = params.get("item")
    return item if isinstance(item, dict) else None


def _item_summary(item: Mapping[str, object] | None) -> str | None:
    if item is None:
        return None
    item_type = item.get("type")
    if not isinstance(item_type, str):
        return None
    public_type = item_type if item_type in _KNOWN_ITEM_TYPES else "other"
    status = item.get("status")
    if isinstance(status, str) and status:
        return f"{public_type}:{status[:48]}"
    return public_type


def _message_text(item: Mapping[str, object] | None) -> str | None:
    if item is None or item.get("type") != "agentMessage":
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


def _final_item_text(turn: Mapping[str, object]) -> str | None:
    items = turn.get("items")
    if not isinstance(items, list):
        return None
    final_texts: list[str] = []
    all_texts: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "agentMessage":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        all_texts.append(text)
        if item.get("phase") == "final_answer":
            final_texts.append(text)
    if final_texts:
        return final_texts[-1]
    return all_texts[-1] if all_texts else None


@dataclass
class _ParsedEvent:
    event: CodexConversationEvent
    final_candidate: str | None = None
    terminal_status: CodexTurnStatus | None = None
    error_code: int | None = None
    error_message: str | None = None
    usage: dict[str, object] = field(default_factory=dict)


@dataclass
class _TurnState:
    info: CodexTurnInfo
    started_at: float | None = None
    started_monotonic: float = field(default_factory=time.monotonic)
    duration_seconds: float | None = None
    events: deque[CodexConversationEvent] = field(
        default_factory=lambda: deque(maxlen=_MAX_EVENTS_PER_TURN)
    )
    public_text: str = ""
    final_candidate: str | None = None
    usage: dict[str, object] = field(default_factory=dict)
    terminal_status: CodexTurnStatus | None = None
    error_code: int | None = None
    error_message: str | None = None
    done: bool = False
    waiters: int = 0
    wait_error: CodexConversationError | None = None
    condition: threading.Condition = field(default_factory=threading.Condition)


class CodexConversationRuntime:
    """Conversation lifecycle over a caller-owned, already-ready client."""

    event_overflow_policy = "drop_oldest"

    def __init__(self, client: CodexAppServerClient) -> None:
        is_ready = getattr(client, "is_ready", None)
        state = getattr(client, "state", None)
        if is_ready is False or (
            is_ready is not True and state is not CodexAppServerState.READY
        ):
            raise CodexInvalidStateError("conversation runtime requires a READY client")
        self._client = client
        self._lock = threading.RLock()
        self._closed = False
        self._turns: dict[tuple[str, str], _TurnState] = {}
        self._turn_by_id: dict[str, tuple[str, str]] = {}
        self._active_threads: set[str] = set()
        self._early_events: dict[tuple[str, str], deque[_ParsedEvent]] = {}
        self._early_event_order: deque[tuple[str, str]] = deque()
        self._completed_order: deque[tuple[str, str]] = deque()
        self._general_events: queue.Queue[CodexConversationEvent] = queue.Queue(
            maxsize=256
        )
        self._subscription_token = client.subscribe_notifications(self._on_notification)

    def thread_start(
        self,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = "untrusted",
        sandbox: str | None = None,
    ) -> CodexThreadInfo:
        """Start one thread with only schema-confirmed stable options."""

        self._ensure_open()
        params: dict[str, object] = {}
        expected_cwd = self._add_thread_options(
            params,
            cwd=cwd,
            model=model,
            model_provider=model_provider,
            approval_policy=approval_policy,
            sandbox=sandbox,
        )
        result = self._client.request("thread/start", params)
        return self._thread_info_from_result(result, expected_cwd=expected_cwd)

    def thread_resume(
        self,
        thread_id: str,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
    ) -> CodexThreadInfo:
        """Resume exactly the supplied thread ID; there is no fallback thread."""

        self._ensure_open()
        thread_id = _non_empty_string(thread_id, "thread_id")
        params: dict[str, object] = {"threadId": thread_id}
        expected_cwd = self._add_thread_options(
            params,
            cwd=cwd,
            model=model,
            model_provider=model_provider,
            approval_policy=approval_policy,
            sandbox=sandbox,
        )
        result = self._client.request("thread/resume", params)
        return self._thread_info_from_result(result, expected_cwd=expected_cwd)

    def thread_read(self, thread_id: str) -> CodexThreadInfo:
        """Read metadata only; turn items and reasoning are never returned."""

        self._ensure_open()
        thread_id = _non_empty_string(thread_id, "thread_id")
        result = self._client.request(
            "thread/read", {"threadId": thread_id, "includeTurns": False}
        )
        return self._thread_info_from_result(result, expected_cwd=None)

    def thread_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        cwd: str | Path | None = None,
    ) -> CodexThreadListResult:
        """Read one schema-defined page without inventing pagination."""

        self._ensure_open()
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool)
        ):
            raise ValueError("limit must be an integer")
        params: dict[str, object] = {}
        if cursor is not None:
            params["cursor"] = _non_empty_string(cursor, "cursor")
        expected_cwd = None
        if cwd is not None:
            expected_cwd = self._cwd_value(cwd)
            params["cwd"] = expected_cwd
        if limit is not None:
            params["limit"] = limit
        result = self._client.request("thread/list", params)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise CodexConversationProtocolError(
                "thread/list result does not contain data"
            )
        threads = tuple(
            self._thread_info_from_thread(item, expected_cwd=expected_cwd)
            for item in result["data"]
            if isinstance(item, dict)
        )
        return CodexThreadListResult(
            threads=threads,
            next_cursor=_optional_string(result.get("nextCursor")),
            backwards_cursor=_optional_string(result.get("backwardsCursor")),
        )

    def turn_start(
        self,
        thread_id: str,
        input_text: str,
        *,
        model: str | None = None,
        cwd: str | Path | None = None,
        approval_policy: str | None = "untrusted",
        sandbox_policy: Mapping[str, object] | None = None,
        effort: str | None = None,
        summary: str | None = None,
        client_user_message_id: str | None = None,
        personality: str | None = None,
        service_tier: str | None = None,
    ) -> CodexTurnInfo:
        """Start a turn on an existing thread without starting another process."""

        self._ensure_open()
        thread_id = _non_empty_string(thread_id, "thread_id")
        _non_empty_string(input_text, "input_text")
        with self._lock:
            if thread_id in self._active_threads:
                raise CodexConcurrentTurnError(
                    "same-thread concurrent turns are not supported by this runtime"
                )
            self._active_threads.add(thread_id)
        params: dict[str, object] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": input_text}],
        }
        if model is not None:
            params["model"] = model
        if cwd is not None:
            params["cwd"] = self._cwd_value(cwd)
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox_policy is not None:
            params["sandboxPolicy"] = dict(sandbox_policy)
        for key, value in (
            ("effort", effort),
            ("summary", summary),
            ("clientUserMessageId", client_user_message_id),
            ("personality", personality),
            ("serviceTier", service_tier),
        ):
            if value is not None:
                params[key] = value
        try:
            result = self._client.request("turn/start", params)
            info, state = self._turn_state_from_result(thread_id, result)
        except BaseException:
            with self._lock:
                self._active_threads.discard(thread_id)
            raise
        with self._lock:
            if self._closed:
                self._active_threads.discard(thread_id)
                raise CodexConversationClosed("conversation runtime is closed")
            key = (thread_id, info.turn_id)
            self._turns[key] = state
            self._turn_by_id[info.turn_id] = key
            early = self._early_events.pop(key, ())
            try:
                self._early_event_order.remove(key)
            except ValueError:
                pass
        for parsed in early:
            self._apply_parsed_event(state, parsed)
        if state.done:
            with self._lock:
                self._active_threads.discard(thread_id)
                if key not in self._completed_order:
                    self._completed_order.append(key)
                self._trim_completed_locked()
        return info

    def turn_interrupt(self, thread_id: str, turn_id: str) -> None:
        """Interrupt one target turn; a local wait timeout never interrupts it."""

        self._ensure_open()
        thread_id = _non_empty_string(thread_id, "thread_id")
        turn_id = _non_empty_string(turn_id, "turn_id")
        self._client.request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
        )

    def wait_turn(
        self,
        thread_id: str,
        turn_id: str,
        timeout_seconds: float | None = None,
    ) -> CodexTurnResult:
        """Wait only for the requested ``(thread_id, turn_id)`` pair."""

        thread_id = _non_empty_string(thread_id, "thread_id")
        turn_id = _non_empty_string(turn_id, "turn_id")
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")
        with self._lock:
            state = self._turns.get((thread_id, turn_id))
        if state is None:
            raise CodexConversationProtocolError("unknown turn")
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        result: CodexTurnResult | None = None
        pending_error: BaseException | None = None
        should_trim = False
        with state.condition:
            state.waiters += 1
            try:
                while not state.done:
                    if self._client.state in (
                        CodexAppServerState.FAILED,
                        CodexAppServerState.CLOSED,
                    ):
                        state.done = True
                        state.wait_error = CodexConversationClientFailed(
                            "Codex app-server client failed"
                        )
                        state.condition.notify_all()
                        break
                    if self._closed:
                        state.done = True
                        state.wait_error = CodexConversationClosed(
                            "conversation runtime is closed"
                        )
                        state.condition.notify_all()
                        break
                    remaining = (
                        None if deadline is None else deadline - time.monotonic()
                    )
                    if remaining is not None and remaining <= 0:
                        raise CodexConversationTimeout("turn wait timed out")
                    state.condition.wait(
                        timeout=0.1 if remaining is None else min(remaining, 0.1)
                    )
                if state.wait_error is not None:
                    pending_error = state.wait_error
                else:
                    result = self._turn_result(state)
            except BaseException as exc:
                pending_error = exc
            finally:
                state.waiters -= 1
                should_trim = state.done and state.waiters == 0
        if should_trim:
            with self._lock:
                self._trim_completed_locked()
        if pending_error is not None:
            raise pending_error
        if result is None:
            raise CodexConversationProtocolError("turn wait produced no result")
        return result

    def close(self) -> None:
        """Release conversation waiters and subscriptions without closing client."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            states = tuple(self._turns.values())
            token = self._subscription_token
        self._client.unsubscribe_notifications(token)
        for state in states:
            with state.condition:
                if not state.done:
                    state.done = True
                    state.wait_error = CodexConversationClosed(
                        "conversation runtime is closed"
                    )
                    state.condition.notify_all()

    def get_event(
        self, timeout_seconds: float | None = None
    ) -> CodexConversationEvent | None:
        """Consume a general sanitized event not safely attributable to a turn."""

        try:
            return self._general_events.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def _add_thread_options(
        self,
        params: dict[str, object],
        *,
        cwd: str | Path | None,
        model: str | None,
        model_provider: str | None,
        approval_policy: str | None,
        sandbox: str | None,
    ) -> str | None:
        expected_cwd = None
        if cwd is not None:
            expected_cwd = self._cwd_value(cwd)
            params["cwd"] = expected_cwd
        if model is not None:
            params["model"] = model
        if model_provider is not None:
            params["modelProvider"] = model_provider
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox is not None:
            params["sandbox"] = sandbox
        return expected_cwd

    @staticmethod
    def _cwd_value(cwd: str | Path) -> str:
        value = str(cwd)
        if not value:
            raise ValueError("cwd must be non-empty")
        return value

    def _thread_info_from_result(
        self, result: object, *, expected_cwd: str | None
    ) -> CodexThreadInfo:
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise CodexConversationProtocolError(
                "thread response does not contain thread"
            )
        thread = result["thread"]
        model_id = _optional_string(result.get("model")) or _optional_string(
            thread.get("model")
        )
        return self._thread_info_from_thread(
            thread,
            expected_cwd=expected_cwd,
            model_id=model_id,
        )

    @staticmethod
    def _thread_info_from_thread(
        thread: Mapping[str, object],
        *,
        expected_cwd: str | None,
        model_id: str | None = None,
    ) -> CodexThreadInfo:
        thread_id = _optional_string(thread.get("id"))
        if thread_id is None:
            raise CodexConversationProtocolError("thread response has no thread ID")
        status = _optional_string(thread.get("status"))
        if status is not None:
            status = status[:64]
        if model_id is None:
            model_id = _optional_string(thread.get("model"))
        return CodexThreadInfo(
            thread_id=thread_id,
            status=status,
            model_id=model_id,
            cwd_status=_cwd_status(thread.get("cwd"), expected_cwd),
            metadata=_safe_metadata(thread, _PUBLIC_THREAD_METADATA),
        )

    def _turn_state_from_result(
        self, thread_id: str, result: object
    ) -> tuple[CodexTurnInfo, _TurnState]:
        if not isinstance(result, dict) or not isinstance(result.get("turn"), dict):
            raise CodexConversationProtocolError("turn response does not contain turn")
        turn = result["turn"]
        turn_id = _optional_string(turn.get("id"))
        if turn_id is None:
            raise CodexConversationProtocolError("turn response has no turn ID")
        status = _turn_status(turn.get("status"), starting=True)
        info = CodexTurnInfo(
            thread_id=thread_id,
            turn_id=turn_id,
            status=status,
            metadata=_safe_metadata(turn, _PUBLIC_TURN_METADATA),
        )
        started_at = turn.get("startedAt")
        started_at_value = (
            float(started_at)
            if isinstance(started_at, (int, float)) and not isinstance(started_at, bool)
            else None
        )
        duration = turn.get("durationMs")
        duration_seconds = (
            float(duration) / 1000.0
            if isinstance(duration, (int, float)) and not isinstance(duration, bool)
            else None
        )
        state = _TurnState(
            info=info,
            started_at=started_at_value,
            duration_seconds=duration_seconds,
            terminal_status=status if _is_terminal(status) else None,
            done=_is_terminal(status),
            public_text=_final_item_text(turn) or "",
            final_candidate=_final_item_text(turn),
            usage=_public_usage(turn),
        )
        if state.done:
            state.error_message = _safe_error_message(
                turn.get("error", {}).get("message")
                if isinstance(turn.get("error"), dict)
                else None
            )
        return info, state

    def _on_notification(self, notification: JsonRpcNotification) -> None:
        parsed = self._parse_notification(notification)
        if parsed is None:
            return
        event = parsed.event
        state: _TurnState | None = None
        buffer_event = False
        with self._lock:
            if event.turn_id is not None:
                key = (
                    (event.thread_id, event.turn_id)
                    if event.thread_id is not None
                    else self._turn_by_id.get(event.turn_id)
                )
                state = self._turns.get(key) if key is not None else None
            elif event.thread_id is not None:
                candidates = [
                    state
                    for (thread_id, _), state in self._turns.items()
                    if thread_id == event.thread_id and not state.done
                ]
                state = candidates[0] if len(candidates) == 1 else None
            if (
                state is None
                and event.turn_id is not None
                and event.thread_id is not None
            ):
                early_key = (event.thread_id, event.turn_id)
                buffer = self._early_events.get(early_key)
                if buffer is None:
                    if len(self._early_event_order) >= _MAX_EARLY_EVENTS:
                        oldest_key = self._early_event_order.popleft()
                        self._early_events.pop(oldest_key, None)
                    buffer = deque(maxlen=min(64, _MAX_EARLY_EVENTS))
                    self._early_events[early_key] = buffer
                    self._early_event_order.append(early_key)
                if len(buffer) == buffer.maxlen:
                    buffer.popleft()
                buffer.append(parsed)
                buffer_event = True
        if buffer_event:
            return
        if state is None:
            self._put_general_event(event)
            return
        self._apply_parsed_event(state, parsed)

    def _put_general_event(self, event: CodexConversationEvent) -> None:
        try:
            self._general_events.put_nowait(event)
        except queue.Full:
            try:
                self._general_events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._general_events.put_nowait(event)
            except queue.Full:
                pass

    def _parse_notification(
        self, notification: JsonRpcNotification
    ) -> _ParsedEvent | None:
        method = _safe_method(notification.method)
        params = notification.params if isinstance(notification.params, dict) else {}
        thread_id = _optional_string(params.get("threadId"))
        turn_id = _optional_string(params.get("turnId"))
        item_id = _optional_string(params.get("itemId"))
        turn = params.get("turn")
        if isinstance(turn, dict):
            thread_id = thread_id or _optional_string(turn.get("threadId"))
            turn_id = turn_id or _optional_string(turn.get("id"))
        event_type = "other"
        text_delta: str | None = None
        action_summary: str | None = None
        terminal_status: CodexTurnStatus | None = None
        final_candidate: str | None = None
        error_code: int | None = None
        error_message: str | None = None
        usage = _public_usage(params)
        metadata: dict[str, object] = {}
        if "reasoning" in method.lower():
            return None
        elif method == "item/agentMessage/delta":
            event_type = "text_delta"
            value = params.get("delta")
            text_delta = value if isinstance(value, str) else None
        elif method == "turn/started":
            event_type = "turn_started"
            terminal_status = (
                _turn_status(turn.get("status")) if isinstance(turn, dict) else None
            )
        elif method == "turn/completed":
            event_type = "turn_completed"
            if isinstance(turn, dict):
                terminal_status = _turn_status(turn.get("status"))
                final_candidate = _final_item_text(turn)
                error = turn.get("error")
                if isinstance(error, dict):
                    error_code = (
                        error.get("code")
                        if isinstance(error.get("code"), int)
                        else None
                    )
                    error_message = _safe_error_message(error.get("message"))
                metadata.update(_safe_metadata(turn, _PUBLIC_TURN_METADATA))
                usage.update(_public_usage(turn))
        elif method == "item/started":
            event_type = "item_started"
            item = _item_from_params(params)
            item_id = item_id or _optional_string(item.get("id")) if item else item_id
            action_summary = _item_summary(item)
        elif method == "item/completed":
            event_type = "item_completed"
            item = _item_from_params(params)
            item_id = item_id or _optional_string(item.get("id")) if item else item_id
            action_summary = _item_summary(item)
            final_candidate = _message_text(item)
        elif "status" in method.lower():
            event_type = "status_changed"
            candidate = params.get("status")
            if candidate is None and isinstance(turn, dict):
                candidate = turn.get("status")
            terminal_status = _turn_status(candidate)
            if isinstance(candidate, str):
                metadata["status"] = candidate[:64]
        elif "tokenusage" in method.lower() or "token_usage" in method.lower():
            event_type = "usage_updated"
        else:
            candidate = params.get("status")
            if isinstance(candidate, str):
                metadata["status"] = candidate[:64]
            item = _item_from_params(params)
            action_summary = _item_summary(item)
        event = CodexConversationEvent(
            method=method,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            event_type=event_type,
            public_text_delta=text_delta,
            public_action_summary=action_summary,
            terminal_status=terminal_status,
            metadata=metadata,
        )
        return _ParsedEvent(
            event=event,
            final_candidate=final_candidate,
            terminal_status=(
                terminal_status
                if _is_terminal(terminal_status or CodexTurnStatus.UNKNOWN)
                else (CodexTurnStatus.UNKNOWN if method == "turn/completed" else None)
            ),
            error_code=error_code,
            error_message=error_message,
            usage=usage,
        )

    def _apply_parsed_event(
        self, state: _TurnState | None, parsed: _ParsedEvent
    ) -> None:
        if state is None:
            return
        with state.condition:
            if state.done:
                return
            event = parsed.event
            if event.public_text_delta:
                state.public_text += event.public_text_delta
            if parsed.final_candidate is not None:
                existing_public_text = state.public_text
                state.final_candidate = parsed.final_candidate
                delta, state.public_text = self._reconcile_text(
                    existing_public_text, parsed.final_candidate
                )
                if event.event_type == "item_completed":
                    event = replace(event, public_text_delta=delta or None)
            state.events.append(event)
            state.usage.update(parsed.usage)
            if parsed.terminal_status is not None:
                state.terminal_status = parsed.terminal_status
                state.done = True
                state.error_code = parsed.error_code
                state.error_message = parsed.error_message
                if state.duration_seconds is None:
                    state.duration_seconds = max(
                        0.0, time.monotonic() - state.started_monotonic
                    )
            state.condition.notify_all()
        if parsed.terminal_status is not None:
            with self._lock:
                self._active_threads.discard(state.info.thread_id)
                key = (state.info.thread_id, state.info.turn_id)
                if key not in self._completed_order:
                    self._completed_order.append(key)
                self._trim_completed_locked()

    def _trim_completed_locked(self) -> None:
        while len(self._completed_order) > _MAX_COMPLETED_TURNS:
            removed = False
            for key in tuple(self._completed_order):
                state = self._turns.get(key)
                if state is None:
                    self._completed_order.remove(key)
                    removed = True
                    break
                with state.condition:
                    eligible = state.done and not state.waiters
                if not eligible:
                    continue
                self._completed_order.remove(key)
                self._turns.pop(key, None)
                if self._turn_by_id.get(key[1]) == key:
                    self._turn_by_id.pop(key[1], None)
                removed = True
                break
            if not removed:
                break

    @staticmethod
    def _reconcile_text(existing: str, candidate: str) -> tuple[str, str]:
        if not candidate:
            return "", existing
        if not existing:
            return candidate, candidate
        if candidate == existing:
            return "", existing
        if candidate.startswith(existing):
            return candidate[len(existing) :], candidate
        if existing.startswith(candidate):
            return "", candidate
        # A completed item is authoritative when it does not share a prefix
        # with deltas; it replaces the partial aggregate deterministically.
        return "", candidate

    @staticmethod
    def _turn_result(state: _TurnState) -> CodexTurnResult:
        status = state.terminal_status or state.info.status
        final_content = (
            state.final_candidate
            if state.final_candidate is not None
            else state.public_text
        )
        return CodexTurnResult(
            thread_id=state.info.thread_id,
            turn_id=state.info.turn_id,
            status=status,
            final_content=final_content,
            public_events=tuple(state.events),
            public_usage=state.usage,
            error_code=state.error_code,
            error_message=state.error_message,
            started_at=state.started_at,
            duration_seconds=state.duration_seconds,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise CodexConversationClosed("conversation runtime is closed")


__all__ = [
    "CodexConcurrentTurnError",
    "CodexConversationClientFailed",
    "CodexConversationClosed",
    "CodexConversationError",
    "CodexConversationEvent",
    "CodexConversationProtocolError",
    "CodexConversationRuntime",
    "CodexConversationTimeout",
]
