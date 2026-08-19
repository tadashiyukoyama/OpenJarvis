from __future__ import annotations

from types import SimpleNamespace

import pytest

from openjarvis.agents.codex import (
    CODEX_CONVERSATION_BUSY,
    CODEX_CONVERSATION_THREAD_NOT_FOUND,
    CodexAgentError,
)
from openjarvis.edge_worker.executor import CodexEdgeExecutor


@pytest.mark.parametrize(
    ("agent_error", "public_error"),
    (
        (CODEX_CONVERSATION_BUSY, "CODEX_BUSY"),
        (CODEX_CONVERSATION_THREAD_NOT_FOUND, "CODEX_THREAD_INVALID"),
    ),
)
def test_delegate_maps_agent_codes_to_the_edge_contract(
    tmp_path, agent_error: str, public_error: str
) -> None:
    class FailingAgent:
        @staticmethod
        def run(command, context):
            del command, context
            raise CodexAgentError(agent_error)

    executor = object.__new__(CodexEdgeExecutor)
    executor._config = SimpleNamespace(project_roots=(str(tmp_path),))

    with pytest.raises(RuntimeError, match=f"^{public_error}$"):
        executor._delegate(
            FailingAgent(),
            {
                "project_cwd": str(tmp_path),
                "thread_id": "thread-1",
                "command": "Diagnosticar sem mutacoes externas.",
            },
            {
                "session_id": "session-1",
                "partition_key": "project::thread-1",
                "request_id": "request-1",
            },
        )
