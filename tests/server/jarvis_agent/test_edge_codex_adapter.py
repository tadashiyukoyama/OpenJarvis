from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.codex import EdgeCodexAdapter
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.registry.codex import codex_tools
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)


class _Edge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def capabilities(self) -> frozenset[str]:
        return frozenset({"codex.status", "codex.history", "codex.delegate"})

    def select_connection(self, capability: str) -> object | None:
        return object() if capability == "codex.delegate" else None

    def execute_job(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "status": "completed",
            "summary": "Comando entregue ao Codex.",
            "data": {"accepted": True},
            "references": {},
        }


def _context(project: Path) -> AdapterContext:
    return AdapterContext(
        session_id="session-1",
        project_key=str(project),
        codex_thread_id="thread-1",
        partition_key="partition-1",
        request_id="action-1",
        job_id="job-1",
    )


def test_edge_codex_delegate_accepts_the_server_resolved_payload(
    tmp_path: Path,
) -> None:
    edge = _Edge()
    adapter = EdgeCodexAdapter(edge)  # type: ignore[arg-type]
    context = _context(tmp_path)

    prepared = adapter.prepare(
        "codex.delegate", {"command": "  Execute o teste.  "}, context
    )
    adapter.preflight_delegate(prepared.arguments)
    result = adapter.execute("codex.delegate", prepared.arguments, context)

    assert result.status == "completed"
    assert edge.calls[0]["arguments"] == {
        "project_cwd": str(tmp_path),
        "thread_id": "thread-1",
        "command": "Execute o teste.",
    }


def test_approved_edge_codex_job_reaches_the_worker(tmp_path: Path) -> None:
    edge = _Edge()
    adapter = EdgeCodexAdapter(edge)  # type: ignore[arg-type]
    orchestrator = JarvisAgentOrchestrator(
        store=JarvisAgentStore(tmp_path / "agent.sqlite3"),
        catalog=JarvisToolCatalog(codex_tools()),
        adapters={"codex": adapter},
    )
    try:
        session = orchestrator.create_session(
            project_key=str(tmp_path), codex_thread_id="thread-1"
        )
        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="function-delegate-1",
            tool_name="codex_delegate_task",
            arguments={"command": "Execute o teste aprovado."},
        )
        accepted = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert accepted["status"] == "accepted"
        job_id = accepted["job"]["job_id"]
        deadline = time.time() + 2.0
        while time.time() < deadline:
            job = orchestrator.store.get_job(job_id)
            if job and job["state"] == "COMPLETED":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("approved Codex job did not reach the Edge adapter")

        assert edge.calls[0]["tool_id"] == "codex.delegate"
        assert edge.calls[0]["arguments"]["thread_id"] == "thread-1"
        assert edge.calls[0]["arguments"]["command"] == "Execute o teste aprovado."
    finally:
        orchestrator.close()
