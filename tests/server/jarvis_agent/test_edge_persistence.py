from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


def _device(store: JarvisAgentStore, *, now: float = 1.0) -> None:
    store.upsert_edge_device(
        {
            "device_id": "workstation-1",
            "status": "ONLINE",
            "capabilities": ["codex.delegate"],
            "metadata": {"platform": "windows"},
            "connected_at": now,
            "last_seen_at": now,
            "updated_at": now,
        }
    )


def _canonical_job(store: JarvisAgentStore) -> None:
    store.create_session(
        {
            "session_id": "session-1",
            "generation": 1,
            "project_key": "D:/project",
            "codex_thread_id": "thread-1",
            "manifest_version": "v1",
            "state": "ACTIVE",
            "created_at": 1.0,
        }
    )
    store.create_action(
        {
            "action_id": "action-1",
            "session_id": "session-1",
            "generation": 1,
            "function_call_id": "function-1",
            "tool_id": "codex.delegate",
            "payload_hash": "a" * 64,
            "payload": {"command": "once"},
            "preview": {"command": "once"},
            "state": "DISPATCHING",
            "created_at": 1.0,
        }
    )
    store.create_job(
        {
            "job_id": "job-1",
            "action_id": "action-1",
            "state": "RUNNING",
            "created_at": 1.0,
        }
    )


def _assignment(store: JarvisAgentStore) -> None:
    store.create_edge_assignment(
        {
            "job_id": "job-1",
            "action_id": "action-1",
            "device_id": "workstation-1",
            "attempt_id": "attempt-1",
            "tool_id": "codex.delegate",
            "payload_hash": "a" * 64,
            "offered_at": 2.0,
            "lease_expires_at": 122.0,
        }
    )


def test_edge_event_ledger_deduplicates_and_rejects_out_of_order(
    tmp_path: Path,
) -> None:
    store = JarvisAgentStore(tmp_path / "edge.sqlite3")
    _device(store)
    event = {
        "event_id": "event-1",
        "device_id": "workstation-1",
        "direction": "inbound",
        "sequence": 1,
        "event_type": "edge.heartbeat",
        "job_id": None,
        "payload_hash": "a" * 64,
        "metadata": {"active_jobs": 0},
        "occurred_at": "2026-08-18T12:00:00Z",
        "received_at": 2.0,
    }
    assert store.record_edge_event(**event) is True
    assert store.record_edge_event(**event) is False
    with pytest.raises(sqlite3.IntegrityError, match="EDGE_SEQUENCE_INVALID"):
        store.record_edge_event(**{**event, "event_id": "event-2", "received_at": 3.0})
    assert store.edge_sequences("workstation-1")["inbound_sequence"] == 1


def test_restart_preserves_only_edge_jobs_already_accepted(tmp_path: Path) -> None:
    path = tmp_path / "accepted-edge.sqlite3"
    store = JarvisAgentStore(path)
    _device(store)
    _canonical_job(store)
    _assignment(store)
    store.transition_edge_assignment(
        job_id="job-1",
        attempt_id="attempt-1",
        expected_states=("OFFERED",),
        next_state="ACCEPTED",
        now=3.0,
        accepted_at=3.0,
    )

    recovered = JarvisAgentStore(path)

    assert recovered.get_edge_device("workstation-1")["status"] == "OFFLINE"
    assert recovered.get_edge_assignment("job-1")["state"] == "ACCEPTED"
    assert recovered.get_action("action-1")["state"] == "DISPATCHING"
    assert recovered.get_job("job-1")["state"] == "RUNNING"


def test_restart_fails_unaccepted_offer_without_hidden_queue(tmp_path: Path) -> None:
    path = tmp_path / "offered-edge.sqlite3"
    store = JarvisAgentStore(path)
    _device(store)
    _canonical_job(store)
    _assignment(store)

    recovered = JarvisAgentStore(path)

    assert recovered.get_edge_assignment("job-1")["state"] == "FAILED"
    assert recovered.get_action("action-1")["state"] == "FAILED"
    assert recovered.get_action("action-1")["error_code"] == "DEVICE_OFFLINE"
    assert recovered.get_job("job-1")["state"] == "FAILED"
