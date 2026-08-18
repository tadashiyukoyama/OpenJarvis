"""Bounded, coalesced reads of paginated public Codex history."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from openjarvis.integrations.codex_protocol import (
    CodexThreadHistory,
    CodexThreadHistoryPage,
)
from openjarvis.server.codex_sync_events import merge_public_messages

logger = logging.getLogger(__name__)


class CodexHistoryReadTimeout(RuntimeError):
    """The app-server did not return public history within its deadline."""


@dataclass(frozen=True)
class _CachedHistory:
    value: Any
    read_at: float


class CodexHistoryReader:
    """Share expensive ``thread/turns/list`` calls across HTTP/SSE consumers.

    A tablet, desktop browser and installed PWA may all subscribe to the same
    task. Without coalescing, every subscriber polls the complete Codex thread
    independently. One slow app-server request then amplifies into a backlog.
    """

    def __init__(
        self,
        *,
        request_timeout_seconds: float = 10.0,
        cache_ttl_seconds: float = 5.0,
        max_cached_threads: int = 128,
    ) -> None:
        if request_timeout_seconds <= 0 or cache_ttl_seconds < 0:
            raise ValueError("history reader timeouts must be positive")
        if max_cached_threads <= 0:
            raise ValueError("max_cached_threads must be positive")
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._max_cached_threads = int(max_cached_threads)
        self._cache: dict[tuple[str, str | None, int, str], _CachedHistory] = {}
        self._inflight: dict[
            tuple[str, str | None, int, str], asyncio.Task[CodexThreadHistoryPage]
        ] = {}

    async def read(
        self,
        runtime: Any,
        thread_id: str,
        *,
        max_age_seconds: float | None = None,
    ) -> Any:
        """Compatibility helper returning the latest bounded history window."""

        page = await self.read_page(
            runtime,
            thread_id,
            max_age_seconds=max_age_seconds,
        )
        return page.history

    async def read_page(
        self,
        runtime: Any,
        thread_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        items_view: str = "summary",
        max_age_seconds: float | None = None,
    ) -> CodexThreadHistoryPage:
        """Return one page, coalescing identical reads across all clients."""

        normalized_thread = thread_id.strip()
        if not normalized_thread:
            raise ValueError("thread_id is required")
        max_age = (
            self._cache_ttl_seconds
            if max_age_seconds is None
            else max(0.0, float(max_age_seconds))
        )
        normalized_cursor = cursor.strip() if isinstance(cursor, str) else None
        key = (normalized_thread, normalized_cursor, int(limit), items_view)
        cached = self._fresh_cache(key, max_age)
        if cached is not None:
            return cached

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(
                self._read_page_uncached(
                    runtime,
                    normalized_thread,
                    cursor=normalized_cursor,
                    limit=limit,
                    items_view=items_view,
                ),
                name=f"codex-history-{normalized_thread[:24]}",
            )
            self._inflight[key] = task

            def discard_inflight(completed: asyncio.Task[Any]) -> None:
                if self._inflight.get(key) is completed:
                    self._inflight.pop(key, None)
                # If every HTTP/SSE consumer disconnected, ``shield`` keeps
                # this shared read alive. Retrieve a later failure here so the
                # event loop does not report "Task exception was never
                # retrieved". Awaiting consumers still receive the same
                # exception because inspecting it does not consume its value.
                if completed.cancelled():
                    return
                completed.exception()

            task.add_done_callback(discard_inflight)

        # A browser disconnect must not cancel the shared app-server request
        # while another tablet/PWA subscriber is awaiting the same result.
        return await asyncio.shield(task)

    async def read_reconciled_page(
        self,
        runtime: Any,
        thread_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        max_age_seconds: float | None = None,
    ) -> CodexThreadHistoryPage:
        """Read summary history plus the full active turn when at the head.

        The app-server summary intentionally omits steering messages added to
        an in-progress turn.  Live events normally carry them, but a backend
        restart can occur after those notifications.  One bounded ``full``
        read of only the newest turn recovers that gap without returning the
        reasoning and tool payloads of the entire conversation.
        """

        if cursor is not None:
            return await self.read_page(
                runtime,
                thread_id,
                cursor=cursor,
                limit=limit,
                items_view="summary",
                max_age_seconds=max_age_seconds,
            )

        summary_result, head_result = await asyncio.gather(
            self.read_page(
                runtime,
                thread_id,
                limit=limit,
                items_view="summary",
                max_age_seconds=max_age_seconds,
            ),
            self.read_page(
                runtime,
                thread_id,
                limit=1,
                items_view="full",
                max_age_seconds=max_age_seconds,
            ),
            return_exceptions=True,
        )
        if isinstance(summary_result, BaseException):
            raise summary_result
        if isinstance(head_result, BaseException):
            logger.warning(
                "Codex active-turn reconciliation failed for %s: %s",
                thread_id,
                head_result,
            )
            return summary_result

        return CodexThreadHistoryPage(
            history=CodexThreadHistory(
                thread_id=thread_id,
                messages=merge_public_messages(
                    summary_result.history.messages,
                    head_result.history.messages,
                ),
            ),
            next_cursor=summary_result.next_cursor,
            backwards_cursor=summary_result.backwards_cursor,
        )

    def invalidate(self, thread_id: str) -> None:
        normalized = thread_id.strip()
        for key in tuple(self._cache):
            if key[0] == normalized:
                self._cache.pop(key, None)

    def _fresh_cache(
        self,
        key: tuple[str, str | None, int, str],
        max_age_seconds: float,
    ) -> CodexThreadHistoryPage | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        if time.monotonic() - cached.read_at > max_age_seconds:
            return None
        return cached.value

    def _trim_cache(self) -> None:
        while len(self._cache) > self._max_cached_threads:
            oldest = min(self._cache, key=lambda key: self._cache[key].read_at)
            self._cache.pop(oldest, None)

    async def _read_page_uncached(
        self,
        runtime: Any,
        thread_id: str,
        *,
        cursor: str | None,
        limit: int,
        items_view: str,
    ) -> CodexThreadHistoryPage:
        try:
            page_reader = getattr(runtime, "thread_history_page", None)
            if callable(page_reader):
                operation = asyncio.to_thread(
                    page_reader,
                    thread_id,
                    cursor=cursor,
                    limit=limit,
                    items_view=items_view,
                    timeout_seconds=self._request_timeout_seconds,
                )
            else:
                operation = asyncio.to_thread(
                    runtime.thread_history,
                    thread_id,
                    timeout_seconds=self._request_timeout_seconds,
                )
            result = await asyncio.wait_for(
                operation,
                timeout=self._request_timeout_seconds + 0.25,
            )
        except TimeoutError as exc:
            raise CodexHistoryReadTimeout(
                "Codex public history read timed out"
            ) from exc

        page = (
            result
            if isinstance(result, CodexThreadHistoryPage)
            else CodexThreadHistoryPage(history=result)
        )
        key = (thread_id, cursor, int(limit), items_view)
        self._cache[key] = _CachedHistory(
            value=page,
            read_at=time.monotonic(),
        )
        self._trim_cache()
        return page


__all__ = ["CodexHistoryReader", "CodexHistoryReadTimeout"]
