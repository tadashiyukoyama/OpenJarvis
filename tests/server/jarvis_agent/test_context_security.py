from __future__ import annotations

import sqlite3


def _session(orchestrator):
    return orchestrator.create_session(
        project_key="D:/dev/project", codex_thread_id="thread-context"
    )


def test_external_result_data_is_transient_and_context_survives_sessions(
    agent_core,
) -> None:
    orchestrator, _ = agent_core
    session = _session(orchestrator)
    response = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-transient-read",
        tool_name="fake_read",
        arguments={"value": "raw external content"},
    )

    assert response["result"]["data"]["echo"] == "raw external content"
    persisted = orchestrator.store.get_action(response["action_id"])
    assert "data" not in persisted["result"]
    assert persisted["preview"] == {}

    next_session = _session(orchestrator)
    context = next_session["context"]
    assert context["objective"].startswith("fake.read")
    assert context["results"][-1]["summary"] == "completed:[redacted]"
    assert context["results"][-1]["trust"] == "internal_metadata"


def test_terminal_mutation_retains_only_hash_summary_and_decision(agent_core) -> None:
    orchestrator, adapter = agent_core
    session = _session(orchestrator)
    secret_payload = "exact payload that must become transient"
    pending = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="fc-transient-write",
        tool_name="fake_write",
        arguments={"value": secret_payload},
    )
    completed = orchestrator.decide(
        action_id=pending["action_id"],
        session_id=session["session_id"],
        payload_hash=pending["payload_hash"],
        decision="approve",
    )

    assert completed["state"] == "COMPLETED"
    assert adapter.calls == [("fake.write", {"value": secret_payload})]
    record = orchestrator.store.get_action(pending["action_id"])
    assert record["payload"] is None
    assert record["preview"] == {}
    assert "data" not in record["result"]

    connection = sqlite3.connect(orchestrator.store.path)
    try:
        serialized = " ".join(
            str(row[0] or "")
            for table, column in (
                ("jarvis_actions", "payload_json"),
                ("jarvis_actions", "preview_json"),
                ("jarvis_context", "context_json"),
            )
            for row in connection.execute(f"SELECT {column} FROM {table}")
        )
    finally:
        connection.close()
    assert secret_payload not in serialized
    context = _session(orchestrator)["context"]
    assert context["decisions"][-1]["decision"] == "approved"


def test_context_keeps_one_decision_per_action(agent_core) -> None:
    orchestrator, _ = agent_core
    service = orchestrator.context
    values = {
        "project_key": "D:/dev/project",
        "codex_thread_id": "thread-context",
        "action_id": "act-once",
        "tool_id": "fake.write",
    }

    service.record_decision(**values, decision="approved")
    service.record_decision(**values, decision="denied")

    decisions = service.read(values["project_key"], values["codex_thread_id"])[
        "decisions"
    ]
    assert decisions == [
        {
            "action_id": "act-once",
            "tool_id": "fake.write",
            "decision": "denied",
            "at": decisions[0]["at"],
        }
    ]
