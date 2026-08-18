"""Bounded asynchronous jobs for long Codex turns."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from openjarvis.server.jarvis_agent.domain.states import JobState
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.execution import ExecutionService


class JobService:
    def __init__(
        self,
        store: JarvisAgentStore,
        execution: ExecutionService,
        events: EventService,
        *,
        max_workers: int = 2,
    ) -> None:
        self._store = store
        self._execution = execution
        self._events = events
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="jarvis-agent-job"
        )
        self._closed = threading.Event()

    def start(
        self, action: Mapping[str, Any], session: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self._closed.is_set():
            raise RuntimeError("Jarvis job service is closed")
        now = time.time()
        job_id = f"job_{uuid.uuid4().hex}"
        self._store.create_job(
            {
                "job_id": job_id,
                "action_id": action["action_id"],
                "state": JobState.ACCEPTED.value,
                "created_at": now,
            }
        )
        self._events.emit(
            "job_accepted",
            session_id=action["session_id"],
            action_id=action["action_id"],
            job_id=job_id,
            payload={"tool_id": action["tool_id"]},
        )
        self._pool.submit(self._run, job_id, dict(action), dict(session))
        return self._store.get_job(job_id) or {"job_id": job_id}

    def _run(
        self, job_id: str, action: Mapping[str, Any], session: Mapping[str, Any]
    ) -> None:
        self._store.update_job(job_id, JobState.RUNNING.value, now=time.time())
        completed = self._execution.execute(action, session, job_id=job_id)
        action_state = str(completed.get("state") or "FAILED")
        if action_state == "COMPLETED":
            state = JobState.COMPLETED
        elif action_state == "BUSY":
            state = JobState.BUSY
        elif action_state == "UNKNOWN":
            state = JobState.UNKNOWN
        elif action_state == "CANCELLED":
            state = JobState.CANCELLED
        else:
            state = JobState.FAILED
        self._store.update_job(
            job_id,
            state.value,
            now=time.time(),
            result=completed.get("_persisted_result") or completed.get("result"),
            summary=str(completed.get("result_summary") or ""),
            error_code=completed.get("error_code"),
        )
        self._events.emit(
            "job_completed" if state is JobState.COMPLETED else "job_failed",
            session_id=action["session_id"],
            action_id=action["action_id"],
            job_id=job_id,
            payload={
                "state": state.value,
                "error_code": completed.get("error_code"),
                "summary": str(completed.get("result_summary") or "")[:2_000],
            },
        )

    def close(self) -> None:
        self._closed.set()
        self._pool.shutdown(wait=False, cancel_futures=False)
