"""Codex UI proxy backed by the authenticated Windows Edge."""

from __future__ import annotations

import ntpath
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openjarvis.integrations.codex_protocol import (
    CodexConversationEvent,
    CodexCwdStatus,
    CodexHistoryMessage,
    CodexThreadHistory,
    CodexThreadHistoryPage,
    CodexThreadInfo,
    CodexThreadListResult,
    CodexTurnStatus,
)
from openjarvis.server.jarvis_agent.domain.models import payload_digest
from openjarvis.server.jarvis_agent.edge.service import EdgeService


class CodexEdgeRuntimeProxy:
    """Present the bounded Codex runtime reads expected by the existing PWA.

    The proxy never opens the local app-server from the VPS. Reads and thread
    subscriptions are Edge jobs; sanitized notifications arrive through the
    ordered Edge event relay and history remains the reconciliation authority.
    """

    poll_history_only = False

    def __init__(
        self,
        edge: EdgeService,
        *,
        catalog_ttl_seconds: float = 5.0,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._edge = edge
        self._catalog_ttl_seconds = catalog_ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._catalog_cache: tuple[float, tuple[CodexThreadInfo, ...]] | None = None
        self._subscriptions: dict[int, int] = {}
        self._next_subscription = 1

    def thread_list(
        self,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        cwd: str | Path | None = None,
    ) -> CodexThreadListResult:
        offset = self._cursor_offset(cursor)
        page_size = 100 if limit is None else int(limit)
        if not 1 <= page_size <= 500:
            raise ValueError("limit must be between 1 and 500")
        threads = self._catalog()
        if cwd is not None:
            expected = ntpath.normcase(ntpath.normpath(str(cwd)))
            threads = tuple(
                item
                for item in threads
                if item.cwd and ntpath.normcase(ntpath.normpath(item.cwd)) == expected
            )
        values = threads[offset : offset + page_size]
        next_offset = offset + len(values)
        return CodexThreadListResult(
            threads=values,
            next_cursor=str(next_offset) if next_offset < len(threads) else None,
        )

    def thread_history_page(
        self,
        thread_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        items_view: str = "summary",
        timeout_seconds: float | None = None,
    ) -> CodexThreadHistoryPage:
        normalized = thread_id.strip()
        if not normalized:
            raise ValueError("thread_id is required")
        result = self._execute(
            "codex.history",
            {
                "limit": limit,
                "cursor": cursor,
                "items_view": items_view,
            },
            codex_thread_id=normalized,
            timeout_seconds=timeout_seconds,
        )
        data = result.get("data")
        data = data if isinstance(data, Mapping) else {}
        raw_messages = data.get("messages")
        messages = tuple(
            self._history_message(item)
            for item in (raw_messages if isinstance(raw_messages, list) else [])
            if isinstance(item, Mapping)
        )
        return CodexThreadHistoryPage(
            history=CodexThreadHistory(thread_id=normalized, messages=messages),
            next_cursor=self._optional_string(data.get("next_cursor")),
            backwards_cursor=self._optional_string(data.get("backwards_cursor")),
        )

    def thread_subscribe(
        self, thread_id: str, *, timeout_seconds: float | None = None
    ) -> dict[str, str]:
        normalized = thread_id.strip()
        if not normalized:
            raise ValueError("thread_id is required")
        outer_timeout = timeout_seconds or self._timeout_seconds
        worker_timeout = max(1.0, min(10.0, outer_timeout - 1.0))
        result = self._execute(
            "codex.subscribe",
            {"timeout_seconds": worker_timeout},
            codex_thread_id=normalized,
            timeout_seconds=outer_timeout,
        )
        data = result.get("data")
        if not isinstance(data, Mapping) or data.get("subscribed") is not True:
            raise RuntimeError("CODEX_SUBSCRIPTION_FAILED")
        return {"thread_id": normalized}

    def thread_is_busy(self, thread_id: str) -> bool:
        result = self._execute("codex.status", {}, codex_thread_id=thread_id.strip())
        data = result.get("data")
        return bool(isinstance(data, Mapping) and data.get("busy"))

    def desktop_refresh(
        self, thread_id: str, *, timeout_seconds: float | None = None
    ) -> str:
        normalized = thread_id.strip()
        if not normalized:
            raise ValueError("thread_id is required")
        result = self._execute(
            "codex.desktop_refresh",
            {},
            codex_thread_id=normalized,
            timeout_seconds=timeout_seconds,
        )
        data = result.get("data")
        uri = data.get("uri") if isinstance(data, Mapping) else None
        if not isinstance(uri, str) or not uri.startswith("codex://threads/"):
            raise RuntimeError("CODEX_DESKTOP_REFRESH_FAILED")
        return uri

    def subscribe_events(self, callback: Callable[[Any], None]) -> int:
        if not callable(callback):
            raise TypeError("conversation event callback must be callable")
        with self._lock:
            token = self._next_subscription
            self._next_subscription += 1
            edge_token = self._edge.subscribe_codex_events(
                lambda payload: callback(self._conversation_event(payload))
            )
            self._subscriptions[token] = edge_token
            return token

    def unsubscribe_events(self, token: int) -> bool:
        with self._lock:
            edge_token = self._subscriptions.pop(token, None)
        return edge_token is not None and self._edge.unsubscribe_codex_events(
            edge_token
        )

    def close(self) -> None:
        with self._lock:
            edge_tokens = tuple(self._subscriptions.values())
            self._subscriptions.clear()
            self._catalog_cache = None
        for edge_token in edge_tokens:
            self._edge.unsubscribe_codex_events(edge_token)

    def _catalog(self) -> tuple[CodexThreadInfo, ...]:
        now = time.monotonic()
        with self._lock:
            cached = self._catalog_cache
            if cached is not None and cached[0] >= now:
                return cached[1]
        result = self._execute("codex.catalog", {})
        data = result.get("data")
        data = data if isinstance(data, Mapping) else {}
        raw_threads = data.get("threads")
        threads = tuple(
            self._thread_info(item)
            for item in (raw_threads if isinstance(raw_threads, list) else [])
            if isinstance(item, Mapping)
            and isinstance(item.get("thread_id"), str)
            and bool(item["thread_id"].strip())
        )
        with self._lock:
            self._catalog_cache = (now + self._catalog_ttl_seconds, threads)
        return threads

    def _execute(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        *,
        codex_thread_id: str = "",
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        request_id = f"edgeui_{uuid.uuid4().hex}"
        return self._edge.execute_job(
            tool_id=tool_id,
            arguments=dict(arguments),
            context={
                "session_id": "edge-ui",
                "partition_key": "codex-ui",
                "project_key": "remote-codex",
                "codex_thread_id": codex_thread_id,
                "request_id": request_id,
            },
            payload_hash=payload_digest(
                {
                    "tool_id": tool_id,
                    "arguments": dict(arguments),
                    "request_id": request_id,
                }
            ),
            capability=tool_id,
            timeout_seconds=timeout_seconds or self._timeout_seconds,
        )

    @staticmethod
    def _thread_info(value: Mapping[str, Any]) -> CodexThreadInfo:
        metadata = value.get("metadata")
        return CodexThreadInfo(
            thread_id=str(value.get("thread_id") or ""),
            cwd=CodexEdgeRuntimeProxy._optional_string(value.get("cwd")),
            status=CodexEdgeRuntimeProxy._optional_string(value.get("status")),
            model_id=CodexEdgeRuntimeProxy._optional_string(value.get("model_id")),
            cwd_status=CodexCwdStatus.UNVERIFIED,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @staticmethod
    def _history_message(value: Mapping[str, Any]) -> CodexHistoryMessage:
        timestamp = value.get("timestamp")
        return CodexHistoryMessage(
            message_id=str(value.get("message_id") or ""),
            role=str(value.get("role") or ""),
            content=str(value.get("content") or ""),
            timestamp=float(timestamp) if isinstance(timestamp, (int, float)) else None,
        )

    @staticmethod
    def _conversation_event(value: Mapping[str, Any]) -> CodexConversationEvent:
        raw_message = value.get("public_message")
        message = (
            CodexEdgeRuntimeProxy._history_message(raw_message)
            if isinstance(raw_message, Mapping)
            else None
        )
        raw_status = value.get("terminal_status")
        status = CodexTurnStatus(raw_status) if isinstance(raw_status, str) else None
        metadata = value.get("metadata")
        return CodexConversationEvent(
            method=str(value.get("method") or "codex/event"),
            thread_id=CodexEdgeRuntimeProxy._optional_string(value.get("thread_id")),
            turn_id=CodexEdgeRuntimeProxy._optional_string(value.get("turn_id")),
            item_id=CodexEdgeRuntimeProxy._optional_string(value.get("item_id")),
            event_type=str(value.get("event_type") or "other"),
            public_text_delta=CodexEdgeRuntimeProxy._optional_string(
                value.get("public_text_delta")
            ),
            public_message=message,
            public_action_summary=CodexEdgeRuntimeProxy._optional_string(
                value.get("public_action_summary")
            ),
            terminal_status=status,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _cursor_offset(cursor: str | None) -> int:
        if cursor is None:
            return 0
        if not cursor.isdigit():
            raise ValueError("cursor is invalid")
        return int(cursor)


__all__ = ["CodexEdgeRuntimeProxy"]
