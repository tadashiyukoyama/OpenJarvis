from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    PreparedToolCall,
    ToolDefinition,
)
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import (
    JarvisToolCatalog,
    ProviderCapabilities,
)
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)


class _CodexAdapter:
    adapter_id = "codex"

    def __init__(self, *, busy: bool = False, blocking: bool = False) -> None:
        self.busy = busy
        self.blocking = blocking
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        return {
            "codex_desktop": ProviderCapabilities(
                "codex_desktop",
                "available",
                frozenset({"codex.delegate"}),
                True,
            )
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        del tool_id
        return PreparedToolCall(
            {"command": str(arguments["command"])},
            {
                "destination": "Codex Desktop",
                "project": context.project_key,
                "thread_id": context.codex_thread_id,
                "command": str(arguments["command"]),
                "risk": "Executa no Codex.",
            },
        )

    def preflight_delegate(self, arguments: Mapping[str, Any]) -> None:
        del arguments
        if self.busy:
            raise JarvisAgentError("CODEX_BUSY", "Codex ocupado.", status_code=409)

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        del tool_id, context
        self.calls += 1
        self.started.set()
        if self.blocking:
            assert self.release.wait(2.0)
        return AdapterResult(
            "completed",
            f"Concluído: {arguments['command']}",
            {"full": "resultado transitório"},
        )


def _orchestrator(tmp_path: Path, adapter: _CodexAdapter) -> JarvisAgentOrchestrator:
    definition = ToolDefinition(
        "codex.delegate",
        "codex_delegate_task",
        "Delegar ao Codex.",
        "codex",
        "codex_desktop",
        "codex",
        "codex.delegate",
        Effect.DELEGATION,
        300.0,
        {
            "type": "object",
            "properties": {"command": {"type": "string", "maxLength": 20_000}},
            "required": ["command"],
            "additionalProperties": False,
        },
    )
    return JarvisAgentOrchestrator(
        store=JarvisAgentStore(tmp_path / "jobs.sqlite3"),
        catalog=JarvisToolCatalog((definition,)),
        adapters={"codex": adapter},
    )


def _approve(orchestrator: JarvisAgentOrchestrator, command: str) -> dict[str, Any]:
    session = orchestrator.create_session(
        project_key="D:/dev/project", codex_thread_id="thread-1"
    )
    pending = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id=f"function-{command}",
        tool_name="codex_delegate_task",
        arguments={"command": command},
    )
    result = orchestrator.decide(
        action_id=pending["action_id"],
        session_id=session["session_id"],
        payload_hash=pending["payload_hash"],
        decision="approve",
    )
    return {"session": session, "result": result}


def test_codex_busy_is_immediate_without_job_or_retry(tmp_path: Path) -> None:
    adapter = _CodexAdapter(busy=True)
    orchestrator = _orchestrator(tmp_path, adapter)
    try:
        response = _approve(orchestrator, "não executar")["result"]
        assert response["state"] == "BUSY"
        assert response["error_code"] == "CODEX_BUSY"
        assert "job" not in response
        assert adapter.calls == 0
        events = orchestrator.events.after(0)
        assert events[-1]["event_type"] == "dispatch_rejected_busy"
        assert events[-1]["payload"] == {"code": "CODEX_BUSY", "state": "BUSY"}
    finally:
        orchestrator.close()


def test_codex_job_survives_session_close_and_resumes_as_summary(
    tmp_path: Path,
) -> None:
    adapter = _CodexAdapter(blocking=True)
    orchestrator = _orchestrator(tmp_path, adapter)
    try:
        approved = _approve(orchestrator, "payload transitório")
        session = approved["session"]
        accepted = approved["result"]
        assert accepted["status"] == "accepted"
        assert adapter.started.wait(1.0)

        orchestrator.close_session(session["session_id"], session["generation"])
        adapter.release.set()
        job_id = accepted["job"]["job_id"]
        deadline = time.time() + 2.0
        while time.time() < deadline:
            job = orchestrator.store.get_job(job_id)
            if job and job["state"] == "COMPLETED":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("Codex job did not complete")

        assert "data" not in job["result"]
        assert "payload transitório" not in job["result_summary"]
        next_session = orchestrator.create_session(
            project_key="D:/dev/project", codex_thread_id="thread-1"
        )
        result = next_session["context"]["results"][-1]
        assert result["tool_id"] == "codex.delegate"
        assert result["trust"] == "external_untrusted_data"
    finally:
        adapter.release.set()
        orchestrator.close()
