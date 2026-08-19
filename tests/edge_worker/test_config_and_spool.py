from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.spool import EdgeSpoolCapacityError, EdgeWorkerSpool


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

    assert spool.accept_job(
        job_id="job-1",
        attempt_id="attempt-1",
        tool_id="codex.delegate",
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
