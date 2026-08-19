"""Local Edge job lifecycle, separate from WebSocket transport."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from openjarvis.edge_worker.executor import CodexEdgeExecutor
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.edge_worker.spool_errors import (
    EdgeSpoolCapacityError,
    EdgeTerminalPayloadError,
)
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame

logger = logging.getLogger(__name__)


class FrameEmitter(Protocol):
    async def __call__(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str | None = None,
    ) -> EdgeFrame: ...


class TerminalFrameEmitter(Protocol):
    async def __call__(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str,
        state: str,
    ) -> EdgeFrame: ...


class JobAcceptor(Protocol):
    async def __call__(
        self,
        *,
        job_id: str,
        attempt_id: str,
        tool_id: str,
        payload_hash: str,
    ) -> bool: ...


class EdgeJobRunner:
    def __init__(
        self,
        *,
        spool: EdgeWorkerSpool,
        executor: CodexEdgeExecutor,
        emit: FrameEmitter,
        emit_terminal: TerminalFrameEmitter,
        accept_job: JobAcceptor,
    ) -> None:
        self._spool = spool
        self._executor = executor
        self._emit = emit
        self._emit_terminal = emit_terminal
        self._accept_job = accept_job
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: dict[str, threading.Event] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def accept_offer(self, frame: EdgeFrame, payload: Mapping[str, Any]) -> None:
        job_id = str(frame.job_id)
        attempt_id = str(payload["attempt_id"])
        rejection = self._rejection(payload)
        if rejection is not None:
            code, message = rejection
            await self._emit(
                "job.rejected",
                {"attempt_id": attempt_id, "code": code, "message": message},
                job_id=job_id,
            )
            return
        try:
            created = await self._accept_job(
                job_id=job_id,
                attempt_id=attempt_id,
                tool_id=str(payload["tool_id"]),
                payload_hash=str(payload["payload_hash"]),
            )
        except EdgeSpoolCapacityError:
            await self._emit(
                "job.rejected",
                {
                    "attempt_id": attempt_id,
                    "code": "TOOL_UNAVAILABLE",
                    "message": "O worker não pode aceitar outro job com segurança.",
                },
                job_id=job_id,
            )
            return
        if not created or job_id in self._tasks:
            return
        cancelled = threading.Event()
        self._cancelled[job_id] = cancelled
        task = asyncio.create_task(self._run(job_id, payload, cancelled))
        self._tasks[job_id] = task
        task.add_done_callback(lambda completed: self._task_done(job_id, completed))

    async def publish_recovered(self, recovered: list[dict[str, Any]]) -> None:
        for item in recovered:
            await self._failed(
                str(item["job_id"]),
                str(item["attempt_id"]),
                "EXTERNAL_RESULT_UNKNOWN",
                "O worker reiniciou durante a operação; o resultado é desconhecido.",
                result_unknown=True,
            )

    def cancel(self, job_id: str, attempt_id: str) -> None:
        del attempt_id
        cancelled = self._cancelled.get(job_id)
        if cancelled is not None:
            cancelled.set()

    async def _run(
        self,
        job_id: str,
        payload: Mapping[str, Any],
        cancelled: threading.Event,
    ) -> None:
        attempt_id = str(payload["attempt_id"])
        self._spool.transition(job_id, "RUNNING")
        try:
            await self._emit_progress(
                job_id,
                attempt_id,
                "running",
                "O worker iniciou a operação local.",
            )
            try:
                result = await asyncio.to_thread(
                    self._executor.execute,
                    tool_id=str(payload["tool_id"]),
                    arguments=dict(payload["arguments"]),
                    context=dict(payload["context"]),
                    job_id=job_id,
                    attempt_id=attempt_id,
                    progress=lambda stage, summary: self._progress_from_thread(
                        job_id, attempt_id, stage, summary
                    ),
                )
            except Exception as exc:
                code = str(exc) if str(exc).isupper() else "EXTERNAL_RESULT_UNKNOWN"
                await self._failed(
                    job_id,
                    attempt_id,
                    code,
                    "A operação local não foi concluída.",
                    result_unknown=code == "EXTERNAL_RESULT_UNKNOWN",
                )
                return
            if cancelled.is_set():
                await self._failed(
                    job_id,
                    attempt_id,
                    "SESSION_CLOSED",
                    "A operação foi cancelada; o resultado local é desconhecido.",
                    result_unknown=True,
                )
                return
            try:
                await self._emit_terminal(
                    "job.succeeded",
                    self._success_payload(attempt_id, result),
                    job_id=job_id,
                    state="SUCCEEDED",
                )
            except EdgeTerminalPayloadError:
                logger.warning(
                    "Edge job result exceeded the safe terminal protocol boundary: %s",
                    job_id,
                )
                await self._failed(
                    job_id,
                    attempt_id,
                    "EXTERNAL_RESULT_UNKNOWN",
                    "A operação local terminou, mas o resultado não pôde ser "
                    "representado com segurança.",
                    result_unknown=True,
                )
        finally:
            self._cancelled.pop(job_id, None)

    async def _failed(
        self,
        job_id: str,
        attempt_id: str,
        code: str,
        message: str,
        *,
        result_unknown: bool,
    ) -> None:
        state = "UNKNOWN" if result_unknown else "FAILED"
        await self._emit_terminal(
            "job.failed",
            {
                "attempt_id": attempt_id,
                "code": code,
                "message": message,
                "result_unknown": result_unknown,
            },
            job_id=job_id,
            state=state,
        )

    @staticmethod
    def _success_payload(attempt_id: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise EdgeTerminalPayloadError("Edge executor returned an invalid result")
        try:
            data = result.get("data")
            references = result.get("references")
            return {
                "attempt_id": attempt_id,
                "status": str(result.get("status") or "completed"),
                "summary": str(result.get("summary") or "Concluído.")[:20_000],
                "data": dict(data) if isinstance(data, Mapping) else {},
                "references": (
                    dict(references) if isinstance(references, Mapping) else {}
                ),
            }
        except Exception as exc:
            raise EdgeTerminalPayloadError(
                "Edge executor result could not be normalized"
            ) from exc

    async def _emit_progress(
        self,
        job_id: str,
        attempt_id: str,
        stage: str,
        summary: str,
    ) -> None:
        try:
            await self._emit(
                "job.progress",
                {
                    "attempt_id": attempt_id,
                    "stage": stage[:64],
                    "summary": summary[:1_000],
                },
                job_id=job_id,
            )
        except Exception as exc:
            logger.warning(
                "Edge progress was not delivered; terminal execution continues: %s",
                type(exc).__name__,
            )

    def _progress_from_thread(
        self, job_id: str, attempt_id: str, stage: str, summary: str
    ) -> None:
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._emit_progress(job_id, attempt_id, stage, summary), self._loop
        )
        future.add_done_callback(self._consume_progress_result)

    @staticmethod
    def _consume_progress_result(completed: Any) -> None:
        if not completed.cancelled():
            completed.exception()

    def _task_done(self, job_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(job_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Edge job terminal persistence failed for %s: %s",
                job_id,
                type(error).__name__,
            )

    def _rejection(self, payload: Mapping[str, Any]) -> tuple[str, str] | None:
        expires = datetime.fromisoformat(
            str(payload["lease_expires_at"]).replace("Z", "+00:00")
        )
        if expires.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            return "EDGE_JOB_TIMEOUT", "A oferta Edge expirou antes de ser aceita."
        if str(payload["tool_id"]) not in self._executor.capabilities:
            return "TOOL_UNAVAILABLE", "A capacidade local não está disponível."
        return None

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._executor.close()


__all__ = [
    "EdgeJobRunner",
    "FrameEmitter",
    "JobAcceptor",
    "TerminalFrameEmitter",
]
