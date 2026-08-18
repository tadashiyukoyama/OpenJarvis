from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.spool import EdgeWorkerSpool


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
    assert spool.pending_frames() == ['{"event_id":"event-1"}']
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
