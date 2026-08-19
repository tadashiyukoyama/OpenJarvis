from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.edge_worker.worker import EdgeWorker
from openjarvis.server.jarvis_agent.edge.frames import make_edge_frame, parse_edge_frame


class _SuccessfulExecutor:
    capabilities = frozenset({"codex.delegate"})

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "status": "completed",
            "summary": "Concluído.",
            "data": {},
            "references": {},
        }

    def close(self) -> None:
        return None


class _FailingExecutor(_SuccessfulExecutor):
    def execute(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError("local failure")


class _FailingConnection:
    async def send(self, _: str) -> None:
        raise ConnectionError("offline")


def _config(tmp_path: Path) -> EdgeWorkerConfig:
    return EdgeWorkerConfig(
        edge_url="wss://openjarvis.example.test/edge",
        device_id="desktop-1",
        token="x" * 32,
        app_server_url="ws://127.0.0.1:8131",
        state_path=tmp_path / "edge.sqlite3",
        binding_path=tmp_path / "bindings.sqlite3",
        project_roots=(r"D:\dev\workspaces",),
    )


def _accept_job(spool: EdgeWorkerSpool) -> None:
    assert spool.accept_job(
        job_id="job-1",
        attempt_id="attempt-1",
        tool_id="codex.delegate",
        payload_hash="a" * 64,
    )


def _fill_normal_spool(spool: EdgeWorkerSpool) -> None:
    sequence = spool.next_outbound_sequence()
    frame = make_edge_frame(
        frame_type="edge.heartbeat",
        device_id="desktop-1",
        sequence=sequence,
        payload={"active_job_ids": []},
        from_client=True,
    )
    spool.queue_outbound(str(frame.event_id), sequence, frame.wire_json())


def _job_payload() -> dict[str, Any]:
    return {
        "attempt_id": "attempt-1",
        "tool_id": "codex.delegate",
        "arguments": {"command": "read only"},
        "context": {
            "session_id": "session-1",
            "partition_key": "partition-1",
            "project_key": "project-1",
            "codex_thread_id": "thread-1",
            "request_id": "request-1",
        },
        "payload_hash": "a" * 64,
        "lease_expires_at": "2099-08-20T12:00:00Z",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executor_type", "expected_state", "expected_frame_type"),
    [
        (_SuccessfulExecutor, "SUCCEEDED", "job.succeeded"),
        (_FailingExecutor, "UNKNOWN", "job.failed"),
    ],
)
async def test_full_normal_spool_cannot_leave_completed_job_running(
    tmp_path: Path,
    executor_type: type[_SuccessfulExecutor],
    expected_state: str,
    expected_frame_type: str,
) -> None:
    spool = EdgeWorkerSpool(
        tmp_path / "edge.sqlite3", max_frames=1, terminal_reserve_frames=1
    )
    executor = executor_type()
    worker = EdgeWorker(_config(tmp_path), spool=spool, executor=executor)  # type: ignore[arg-type]
    _accept_job(spool)
    _fill_normal_spool(spool)

    await worker.jobs._run("job-1", _job_payload(), threading.Event())

    frames = [
        parse_edge_frame(item.wire_json, from_client=True)
        for item in spool.pending_frames()
    ]
    assert executor.calls == 1
    assert spool.job_state("job-1") == expected_state
    assert spool.active_job_ids() == []
    assert [frame.type for frame in frames] == ["edge.heartbeat", expected_frame_type]


@pytest.mark.asyncio
async def test_terminal_send_failure_keeps_durable_outcome_for_replay(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "edge.sqlite3")
    worker = EdgeWorker(
        _config(tmp_path),
        spool=spool,
        executor=_SuccessfulExecutor(),  # type: ignore[arg-type]
    )
    _accept_job(spool)
    spool.transition("job-1", "RUNNING")
    worker._connection = _FailingConnection()  # type: ignore[assignment]
    worker._send_lock = asyncio.Lock()
    worker._handshake_complete = True

    frame = await worker._emit_terminal(
        "job.succeeded",
        {
            "attempt_id": "attempt-1",
            "status": "completed",
            "summary": "Concluído.",
            "data": {},
            "references": {},
        },
        job_id="job-1",
        state="SUCCEEDED",
    )

    pending = spool.pending_frames()
    assert spool.job_state("job-1") == "SUCCEEDED"
    assert [item.sequence for item in pending] == [frame.sequence]
    assert worker._handshake_complete is False


@pytest.mark.asyncio
async def test_exhausted_terminal_reserve_rejects_offer_before_execution(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "edge.sqlite3", terminal_reserve_frames=1)
    executor = _SuccessfulExecutor()
    worker = EdgeWorker(_config(tmp_path), spool=spool, executor=executor)  # type: ignore[arg-type]
    _accept_job(spool)
    payload = _job_payload()
    payload["attempt_id"] = "attempt-2"
    offer = make_edge_frame(
        frame_type="job.offer",
        device_id="desktop-1",
        sequence=1,
        job_id="job-2",
        payload=payload,
        from_client=False,
    )

    await worker.jobs.accept_offer(
        offer,
        offer.validated_payload(from_client=False).model_dump(mode="json"),
    )

    frames = [
        parse_edge_frame(item.wire_json, from_client=True)
        for item in spool.pending_frames()
    ]
    assert executor.calls == 0
    assert spool.job_state("job-2") is None
    assert [frame.type for frame in frames] == ["job.rejected"]
    assert frames[0].payload["code"] == "TOOL_UNAVAILABLE"
