from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.edge_worker.worker import EdgeWorker
from openjarvis.server.jarvis_agent.edge.frames import (
    make_edge_frame,
    parse_edge_frame,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, wire_json: str) -> None:
        self.sent.append(wire_json)


class _FakeExecutor:
    capabilities = frozenset({"codex.delegate"})


def _config(tmp_path: Path) -> EdgeWorkerConfig:
    return EdgeWorkerConfig(
        edge_url="wss://openjarvis.example.test/edge",
        device_id="desktop-1",
        token="x" * 32,
        app_server_url="ws://127.0.0.1:8131",
        state_path=tmp_path / "edge.sqlite3",
        binding_path=tmp_path / "bindings.sqlite3",
        project_roots=(r"D:\dev\workspaces",),
        replay_batch_size=1,
    )


def _queue_heartbeat(spool: EdgeWorkerSpool) -> None:
    sequence = spool.next_outbound_sequence()
    frame = make_edge_frame(
        frame_type="edge.heartbeat",
        device_id="desktop-1",
        sequence=sequence,
        payload={"active_job_ids": []},
        from_client=True,
    )
    spool.queue_outbound(str(frame.event_id), sequence, frame.wire_json())


@pytest.mark.asyncio
async def test_registration_does_not_ack_offline_frames_before_replay(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "edge.sqlite3")
    _queue_heartbeat(spool)
    _queue_heartbeat(spool)
    worker = EdgeWorker(
        _config(tmp_path), spool=spool, executor=_FakeExecutor()  # type: ignore[arg-type]
    )
    connection = _FakeConnection()
    worker._connection = connection  # type: ignore[assignment]
    worker._send_lock = asyncio.Lock()

    registration = await worker._send_registration()
    assert registration.type == "edge.register"
    assert [item.sequence for item in spool.pending_frames()] == [1, 2]

    registered = make_edge_frame(
        frame_type="edge.registered",
        device_id="desktop-1",
        sequence=1,
        payload={
            "connection_id": "connection-1",
            "heartbeat_interval_seconds": 15,
            "acknowledged_sequence": 0,
            "server_time": "2026-08-19T12:00:00Z",
        },
        from_client=False,
    )
    await worker._handle_core(registered)
    await worker._replay_and_resume()

    sent = [parse_edge_frame(item, from_client=True) for item in connection.sent]
    assert [item.type for item in sent] == [
        "edge.register",
        "edge.heartbeat",
        "edge.heartbeat",
        "edge.resume",
    ]
    assert [item.sequence for item in sent] == [3, 1, 2, 4]
    assert worker._handshake_complete is True


@pytest.mark.asyncio
async def test_core_ack_prunes_only_confirmed_frames_and_advances_sequence(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "edge.sqlite3")
    _queue_heartbeat(spool)
    _queue_heartbeat(spool)
    worker = EdgeWorker(
        _config(tmp_path), spool=spool, executor=_FakeExecutor()  # type: ignore[arg-type]
    )

    registered = make_edge_frame(
        frame_type="edge.registered",
        device_id="desktop-1",
        sequence=1,
        payload={
            "connection_id": "connection-1",
            "heartbeat_interval_seconds": 15,
            "acknowledged_sequence": 1,
            "server_time": "2026-08-19T12:00:00Z",
        },
        from_client=False,
    )
    await worker._handle_core(registered)

    assert [item.sequence for item in spool.pending_frames()] == [2]
    spool.reconcile_outbound_sequence(10)
    assert spool.next_outbound_sequence() == 11
