"""Local Edge job lifecycle, separate from WebSocket transport."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from openjarvis.edge_worker.executor import CodexEdgeExecutor
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame


class FrameEmitter(Protocol):
    async def __call__(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str | None = None,
    ) -> EdgeFrame: ...


class EdgeJobRunner:
    def __init__(
        self,
        *,
        spool: EdgeWorkerSpool,
        executor: CodexEdgeExecutor,
        emit: FrameEmitter,
    ) -> None:
        self._spool = spool
        self._executor = executor
        self._emit = emit
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
        created = self._spool.accept_job(
            job_id=job_id,
            attempt_id=attempt_id,
            tool_id=str(payload["tool_id"]),
            payload_hash=str(payload["payload_hash"]),
        )
        await self._emit("job.accepted", {"attempt_id": attempt_id}, job_id=job_id)
        if not created or job_id in self._tasks:
            return
        cancelled = threading.Event()
        self._cancelled[job_id] = cancelled
        task = asyncio.create_task(self._run(job_id, payload, cancelled))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

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
        await self._emit(
            "job.progress",
            {
                "attempt_id": attempt_id,
                "stage": "running",
                "summary": "O worker iniciou a operação local.",
            },
            job_id=job_id,
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
            if cancelled.is_set():
                await self._failed(
                    job_id,
                    attempt_id,
                    "SESSION_CLOSED",
                    "A operação foi cancelada; o resultado local é desconhecido.",
                    result_unknown=True,
                )
                return
            frame = await self._emit(
                "job.succeeded",
                {
                    "attempt_id": attempt_id,
                    "status": str(result.get("status") or "completed"),
                    "summary": str(result.get("summary") or "Concluído.")[:20_000],
                    "data": dict(result.get("data") or {}),
                    "references": dict(result.get("references") or {}),
                },
                job_id=job_id,
            )
            self._spool.transition(job_id, "SUCCEEDED", str(frame.event_id))
        except Exception as exc:
            code = str(exc) if str(exc).isupper() else "EXTERNAL_RESULT_UNKNOWN"
            await self._failed(
                job_id,
                attempt_id,
                code,
                "A operação local não foi concluída.",
                result_unknown=code == "EXTERNAL_RESULT_UNKNOWN",
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
        frame = await self._emit(
            "job.failed",
            {
                "attempt_id": attempt_id,
                "code": code,
                "message": message,
                "result_unknown": result_unknown,
            },
            job_id=job_id,
        )
        state = "UNKNOWN" if result_unknown else "FAILED"
        self._spool.transition(job_id, state, str(frame.event_id))

    def _progress_from_thread(
        self, job_id: str, attempt_id: str, stage: str, summary: str
    ) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._emit(
                "job.progress",
                {
                    "attempt_id": attempt_id,
                    "stage": stage[:64],
                    "summary": summary[:2_000],
                },
                job_id=job_id,
            ),
            self._loop,
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


__all__ = ["EdgeJobRunner", "FrameEmitter"]
