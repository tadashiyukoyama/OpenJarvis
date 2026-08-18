"""Read-only Codex UI proxy backed by the authenticated Windows Edge."""

from __future__ import annotations

import ntpath
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from openjarvis.integrations.codex_protocol import (
    CodexCwdStatus,
    CodexHistoryMessage,
    CodexThreadHistory,
    CodexThreadHistoryPage,
    CodexThreadInfo,
    CodexThreadListResult,
)
from openjarvis.server.jarvis_agent.domain.models import payload_digest
from openjarvis.server.jarvis_agent.edge.service import EdgeService


class CodexEdgeRuntimeProxy:
    """Present the bounded Codex runtime reads expected by the existing PWA.

    The proxy never opens the local app-server from the VPS. Every read is a
    short-lived Edge job, and live synchronization deliberately uses bounded
    polling because app-server notifications stay on the Windows worker.
    """

    poll_history_only = True
    history_poll_interval_seconds = 10.0

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
        self._subscriptions: dict[int, Callable[[Any], None]] = {}
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
        del timeout_seconds
        if not thread_id.strip():
            raise ValueError("thread_id is required")
        if self._edge.select_connection("codex.history") is None:
            raise RuntimeError("DEVICE_OFFLINE")
        return {"thread_id": thread_id}

    def thread_is_busy(self, thread_id: str) -> bool:
        result = self._execute("codex.status", {}, codex_thread_id=thread_id.strip())
        data = result.get("data")
        return bool(isinstance(data, Mapping) and data.get("busy"))

    def subscribe_events(self, callback: Callable[[Any], None]) -> int:
        if not callable(callback):
            raise TypeError("conversation event callback must be callable")
        with self._lock:
            token = self._next_subscription
            self._next_subscription += 1
            self._subscriptions[token] = callback
            return token

    def unsubscribe_events(self, token: int) -> bool:
        with self._lock:
            return self._subscriptions.pop(token, None) is not None

    def close(self) -> None:
        with self._lock:
            self._subscriptions.clear()
            self._catalog_cache = None

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
