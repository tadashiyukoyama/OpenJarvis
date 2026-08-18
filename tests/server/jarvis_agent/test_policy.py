from __future__ import annotations

import pytest

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


def test_policy_rejects_fields_outside_the_tool_schema(agent_core) -> None:
    orchestrator, _ = agent_core
    session = orchestrator.create_session(project_key="D:/project")

    with pytest.raises(JarvisAgentError) as raised:
        orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-extra",
            tool_name="fake_read",
            arguments={"value": "ok", "hidden": "not allowed"},
        )

    assert raised.value.code == "INVALID_REQUEST"


def test_policy_rejects_wrong_primitive_type(agent_core) -> None:
    orchestrator, _ = agent_core
    session = orchestrator.create_session(project_key="D:/project")

    with pytest.raises(JarvisAgentError) as raised:
        orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-type",
            tool_name="fake_read",
            arguments={"value": 42},
        )

    assert raised.value.code == "INVALID_REQUEST"
