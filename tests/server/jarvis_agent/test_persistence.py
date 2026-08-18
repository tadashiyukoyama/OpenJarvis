from __future__ import annotations

import time
from pathlib import Path

from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore


def test_sqlite_integrity_wal_and_context_expiry(tmp_path: Path) -> None:
    store = JarvisAgentStore(tmp_path / "agent.sqlite3")
    store.put_context(
        {
            "partition_key": "p",
            "project_key": "D:/project",
            "codex_thread_id": "t1",
            "context": {"objective": "test"},
            "updated_at": 1.0,
            "expires_at": 2.0,
        }
    )

    assert store.integrity_check() == "ok"
    assert store.get_context("p", 1.5)["context"]["objective"] == "test"
    store.expire(2.0)
    assert store.get_context("p", time.time()) is None


def test_restart_marks_inflight_work_unknown_without_retry(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    store = JarvisAgentStore(path)
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

    recovered = JarvisAgentStore(path)

    action = recovered.get_action("action-1")
    job = recovered.get_job("job-1")
    assert action["state"] == "UNKNOWN"
    assert action["payload"] is None
    assert action["error_code"] == "EXTERNAL_RESULT_UNKNOWN"
    assert job["state"] == "UNKNOWN"
    assert job["error_code"] == "EXTERNAL_RESULT_UNKNOWN"
    assert recovered.get_session("session-1")["state"] == "CLOSED"


def test_restart_preserves_accepted_external_operation_for_webhook_reconciliation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accepted.sqlite3"
    store = JarvisAgentStore(path)
    store.create_session(
        {
            "session_id": "session-accepted",
            "generation": 1,
            "project_key": "D:/project",
            "codex_thread_id": "thread-1",
            "manifest_version": "v1",
            "state": "CLOSED",
            "created_at": 1.0,
        }
    )
    store.create_action(
        {
            "action_id": "action-accepted",
            "session_id": "session-accepted",
            "generation": 1,
            "function_call_id": "function-accepted",
            "tool_id": "whatsapp.send_text",
            "payload_hash": "b" * 64,
            "payload": {"text": "temporary"},
            "preview": {"message": "temporary"},
            "state": "DISPATCHING",
            "created_at": 1.0,
        }
    )
    store.accept_external_operation(
        action_id="action-accepted",
        provider="acelerachat",
        resource_type="Message",
        resource_id="901",
        result={"status": "accepted"},
        summary="accepted",
        now=2.0,
    )

    recovered = JarvisAgentStore(path)

    assert recovered.get_action("action-accepted")["state"] == "ACCEPTED"
