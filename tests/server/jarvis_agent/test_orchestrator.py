from __future__ import annotations

import sqlite3

import pytest

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


def _session(orchestrator):
    return orchestrator.create_session(
        project_key="D:/dev/project", codex_thread_id="t1"
    )


def test_read_executes_once_without_approval(agent_core) -> None:
    orchestrator, adapter = agent_core
    session = _session(orchestrator)

    result = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-read-1",
        tool_name="fake_read",
        arguments={"value": "hello"},
    )

    assert result["status"] == "completed"
    assert result["result"]["data"]["echo"] == "hello"
    assert adapter.calls == [("fake.read", {"value": "hello"})]
    events = orchestrator.events.after(0, 100)
    assert [event["event_type"] for event in events].count("dispatch_started") == 1


def test_session_generation_is_exact_in_javascript(agent_core) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)

    generation = session["generation"]
    assert 0 < generation <= (2**53 - 1)
    assert int(float(generation)) == generation


def test_mutation_is_bound_to_visual_hash_and_single_use(agent_core) -> None:
    orchestrator, adapter = agent_core
    session = _session(orchestrator)
    pending = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-write-1",
        tool_name="fake_write",
        arguments={"value": "exact payload"},
    )

    assert pending["status"] == "approval_required"
    assert adapter.calls == []

    completed = orchestrator.decide(
        action_id=pending["action_id"],
        session_id=session["session_id"],
        payload_hash=pending["payload_hash"],
        decision="approve",
    )
    duplicate_click = orchestrator.decide(
        action_id=pending["action_id"],
        session_id=session["session_id"],
        payload_hash=pending["payload_hash"],
        decision="approve",
    )

    assert completed["status"] == "completed"
    assert duplicate_click["status"] == "completed"
    assert adapter.calls == [("fake.write", {"value": "exact payload"})]
    assert orchestrator.store.get_action(pending["action_id"])["payload"] is None


def test_wrong_hash_cannot_approve(agent_core) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)
    pending = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-write-2",
        tool_name="fake_write",
        arguments={"value": "safe"},
    )

    with pytest.raises(JarvisAgentError, match="payload") as error:
        orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash="0" * 64,
            decision="approve",
        )

    assert error.value.code == "APPROVAL_PAYLOAD_MISMATCH"


def test_duplicate_function_call_returns_existing_action(agent_core) -> None:
    orchestrator, adapter = agent_core
    session = _session(orchestrator)
    kwargs = {
        "session_id": session["session_id"],
        "generation": session["generation"],
        "function_call_id": "fc-duplicate",
        "tool_name": "fake_write",
        "arguments": {"value": "once"},
    }

    first = orchestrator.propose(**kwargs)
    second = orchestrator.propose(**kwargs)

    assert first["action_id"] == second["action_id"]
    assert adapter.calls == []


def test_one_pending_action_per_session(agent_core) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)
    orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-pending-1",
        tool_name="fake_write",
        arguments={"value": "one"},
    )

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-pending-2",
            tool_name="fake_write",
            arguments={"value": "two"},
        )

    assert error.value.code == "ACTION_PENDING"


def test_committed_transcript_is_redacted_after_proposal(agent_core) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)
    orchestrator.commit_turn(
        session_id=session["session_id"],
        generation=session["generation"],
        turn_id="turn-1",
        transcript="Do not retain this complete transcript",
    )
    orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-redact",
        tool_name="fake_read",
        arguments={"value": "read"},
        turn_id="turn-1",
    )

    connection = sqlite3.connect(orchestrator.store.path)
    try:
        row = connection.execute(
            """
            SELECT transcript_text, transcript_hash
            FROM jarvis_turns WHERE turn_id = ?
            """,
            ("turn-1",),
        ).fetchone()
    finally:
        connection.close()
    assert row[0] is None
    assert len(row[1]) == 64


def test_closed_session_rejects_late_callback(agent_core) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)
    orchestrator.close_session(session["session_id"], session["generation"])

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.commit_turn(
            session_id=session["session_id"],
            generation=session["generation"],
            turn_id="late",
            transcript="late callback",
        )

    assert error.value.code == "SESSION_CLOSED"


def test_manifest_change_is_explicit_not_silent_fallback(agent_core) -> None:
    orchestrator, adapter = agent_core
    session = _session(orchestrator)
    adapter.available = False

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-stale",
            tool_name="fake_read",
            arguments={"value": "x"},
        )

    assert error.value.code == "MANIFEST_STALE"
