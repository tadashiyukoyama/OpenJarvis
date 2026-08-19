from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.spool import EdgeSpoolCapacityError, EdgeWorkerSpool
from openjarvis.server.jarvis_agent.edge.frames import make_edge_frame


def _accept_job(
    spool: EdgeWorkerSpool,
    *,
    job_id: str,
    attempt_id: str,
    payload_hash: str,
    acknowledge: bool = True,
) -> bool:
    sequence = spool.next_outbound_sequence()
    frame = make_edge_frame(
        frame_type="job.accepted",
        device_id="desktop-1",
        sequence=sequence,
        job_id=job_id,
        payload={"attempt_id": attempt_id},
        from_client=True,
    )
    created = spool.accept_job_with_frame(
        job_id=job_id,
        attempt_id=attempt_id,
        tool_id="codex.delegate",
        payload_hash=payload_hash,
        event_id=str(frame.event_id),
        sequence=sequence,
        wire_json=frame.wire_json(),
    )
    if acknowledge:
        spool.acknowledge(sequence)
    return created


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "OPENJARVIS_EDGE_WSS_URL": "wss://openjarvis.example.test/edge",
        "OPENJARVIS_EDGE_DEVICE_ID": "cesar-desktop",
        "OPENJARVIS_EDGE_TOKEN_CURRENT": "edge-test-token-0123456789abcdef",
        "OPENJARVIS_CODEX_APP_SERVER_URL": "ws://127.0.0.1:8131",
        "OPENJARVIS_RUNTIME_ROOT": str(tmp_path),
        "OPENJARVIS_EDGE_PROJECT_ROOTS": r"D:\dev\workspaces",
    }


def test_worker_config_requires_secure_edge_and_loopback_codex(tmp_path: Path) -> None:
    config = EdgeWorkerConfig.from_env(_environment(tmp_path))

    assert config.device_id == "cesar-desktop"
    assert config.app_server_url == "ws://127.0.0.1:8131"
    assert config.state_path.parent == tmp_path / "edge-worker"
    assert config.spool_max_frames == 10_000
    assert config.spool_max_bytes == 64 * 1024 * 1024
    assert config.replay_batch_size == 100

    invalid = _environment(tmp_path)
    invalid["OPENJARVIS_EDGE_WSS_URL"] = "ws://public.example.test/edge"
    with pytest.raises(ValueError, match="wss"):
        EdgeWorkerConfig.from_env(invalid)

    invalid = _environment(tmp_path)
    invalid["OPENJARVIS_CODEX_APP_SERVER_URL"] = "ws://10.0.0.8:8131"
    with pytest.raises(ValueError, match="loopback"):
        EdgeWorkerConfig.from_env(invalid)

    invalid = _environment(tmp_path)
    invalid["OPENJARVIS_EDGE_TOKEN_CURRENT"] = "short"
    with pytest.raises(ValueError, match="too short"):
        EdgeWorkerConfig.from_env(invalid)


def test_spool_preserves_sequences_deduplicates_and_recovers(tmp_path: Path) -> None:
    path = tmp_path / "edge.sqlite3"
    spool = EdgeWorkerSpool(path)

    assert spool.next_outbound_sequence() == 1
    spool.queue_outbound("event-1", 1, '{"event_id":"event-1"}')
    pending = spool.pending_frames()
    assert [(item.sequence, item.wire_json) for item in pending] == [
        (1, '{"event_id":"event-1"}')
    ]
    spool.acknowledge(1)
    assert spool.pending_frames() == []

    assert spool.record_inbound("core-1", 1) is True
    assert spool.record_inbound("core-1", 1) is False
    with pytest.raises(ValueError, match="backwards"):
        spool.record_inbound("core-old", 1)

    assert _accept_job(
        spool,
        job_id="job-1",
        attempt_id="attempt-1",
        payload_hash="a" * 64,
    )
    spool.transition("job-1", "RUNNING")
    recovered = EdgeWorkerSpool(path).recover_interrupted()
    assert recovered == [
        {
            "job_id": "job-1",
            "attempt_id": "attempt-1",
            "tool_id": "codex.delegate",
        }
    ]
    assert EdgeWorkerSpool(path).active_job_ids() == []


def test_spool_is_bounded_and_replays_in_stable_pages(tmp_path: Path) -> None:
    spool = EdgeWorkerSpool(tmp_path / "bounded.sqlite3", max_frames=2, max_bytes=80)
    spool.queue_outbound("event-1", 1, '{"event_id":"event-1"}')
    spool.queue_outbound("event-2", 2, '{"event_id":"event-2"}')

    first = spool.pending_frames(limit=1)
    second = spool.pending_frames(after_sequence=first[-1].sequence, limit=1)
    assert [item.sequence for item in first + second] == [1, 2]
    with pytest.raises(EdgeSpoolCapacityError, match="capacity"):
        spool.queue_outbound("event-3", 3, '{"event_id":"event-3"}')


def test_job_admission_and_acceptance_frame_commit_together(tmp_path: Path) -> None:
    path = tmp_path / "atomic-admission.sqlite3"
    spool = EdgeWorkerSpool(path)

    assert _accept_job(
        spool,
        job_id="job-1",
        attempt_id="attempt-1",
        payload_hash="a" * 64,
        acknowledge=False,
    )

    reopened = EdgeWorkerSpool(path)
    pending = reopened.pending_frames()
    assert reopened.job_state("job-1") == "ACCEPTED"
    assert len(pending) == 1
    assert '"type":"job.accepted"' in pending[0].wire_json


def test_spool_reconciles_high_water_and_removes_legacy_registration(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "migration.sqlite3")
    spool.queue_outbound(
        "register-1", 1, '{"type":"edge.register","event_id":"register-1"}'
    )
    spool.queue_outbound("event-2", 2, '{"type":"edge.heartbeat","event_id":"event-2"}')

    assert spool.discard_legacy_registration_frames() == 1
    assert [item.sequence for item in spool.pending_frames()] == [2]
    spool.reconcile_outbound_sequence(7)
    assert spool.next_outbound_sequence() == 8


def test_terminal_outcome_uses_bounded_reserve_and_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "terminal.sqlite3"
    spool = EdgeWorkerSpool(
        path, max_frames=1, max_bytes=1_024, terminal_reserve_frames=1
    )
    assert _accept_job(
        spool,
        job_id="job-1",
        attempt_id="attempt-1",
        payload_hash="a" * 64,
    )
    spool.transition("job-1", "RUNNING")
    spool.queue_outbound("event-1", 1, '{"event_id":"event-1"}')

    with pytest.raises(EdgeSpoolCapacityError, match="capacity"):
        spool.queue_outbound("event-2", 2, '{"event_id":"event-2"}')

    terminal_wire = '{"event_id":"terminal-1","type":"job.succeeded"}'
    spool.queue_terminal(
        job_id="job-1",
        state="SUCCEEDED",
        event_id="terminal-1",
        sequence=3,
        wire_json=terminal_wire,
    )

    assert spool.job_state("job-1") == "SUCCEEDED"
    assert [item.sequence for item in spool.pending_frames()] == [1, 3]
    reopened = EdgeWorkerSpool(
        path, max_frames=1, max_bytes=1_024, terminal_reserve_frames=1
    )
    assert reopened.job_state("job-1") == "SUCCEEDED"
    reopened.queue_terminal(
        job_id="job-1",
        state="SUCCEEDED",
        event_id="terminal-1",
        sequence=3,
        wire_json=terminal_wire,
    )


def test_terminal_reserve_blocks_admission_until_delivery_is_acknowledged(
    tmp_path: Path,
) -> None:
    spool = EdgeWorkerSpool(tmp_path / "reserve.sqlite3", terminal_reserve_frames=1)
    assert _accept_job(
        spool,
        job_id="job-1",
        attempt_id="attempt-1",
        payload_hash="a" * 64,
    )
    with pytest.raises(EdgeSpoolCapacityError, match="new job"):
        _accept_job(
            spool,
            job_id="job-2",
            attempt_id="attempt-2",
            payload_hash="b" * 64,
        )

    spool.queue_terminal(
        job_id="job-1",
        state="SUCCEEDED",
        event_id="terminal-1",
        sequence=1,
        wire_json='{"event_id":"terminal-1"}',
    )
    with pytest.raises(EdgeSpoolCapacityError, match="new job"):
        _accept_job(
            spool,
            job_id="job-2",
            attempt_id="attempt-2",
            payload_hash="b" * 64,
        )

    spool.acknowledge(1)
    assert _accept_job(
        spool,
        job_id="job-2",
        attempt_id="attempt-2",
        payload_hash="b" * 64,
    )


def test_interrupted_job_remains_recoverable_until_terminal_frame_is_durable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recovery.sqlite3"
    spool = EdgeWorkerSpool(path)
    assert _accept_job(
        spool,
        job_id="job-1",
        attempt_id="attempt-1",
        payload_hash="a" * 64,
    )
    spool.transition("job-1", "RUNNING")

    expected = [
        {
            "job_id": "job-1",
            "attempt_id": "attempt-1",
            "tool_id": "codex.delegate",
        }
    ]
    assert spool.recover_interrupted() == expected
    assert spool.job_state("job-1") == "RECOVERY_PENDING"
    assert EdgeWorkerSpool(path).recover_interrupted() == expected

    spool.queue_terminal(
        job_id="job-1",
        state="UNKNOWN",
        event_id="terminal-1",
        sequence=1,
        wire_json='{"event_id":"terminal-1","type":"job.failed"}',
    )
    assert spool.job_state("job-1") == "UNKNOWN"
    assert EdgeWorkerSpool(path).recover_interrupted() == []


def test_existing_spool_schema_adds_terminal_marker_without_data_loss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE outbound_frames (event_id TEXT PRIMARY KEY, "
            "sequence INTEGER NOT NULL UNIQUE, wire_json TEXT NOT NULL, "
            "created_at REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO outbound_frames VALUES (?, ?, ?, ?)",
            ("legacy-1", 1, '{"event_id":"legacy-1"}', 1.0),
        )

    spool = EdgeWorkerSpool(path)

    assert [item.sequence for item in spool.pending_frames()] == [1]
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(outbound_frames)")
        }
    assert "terminal_job_id" in columns
