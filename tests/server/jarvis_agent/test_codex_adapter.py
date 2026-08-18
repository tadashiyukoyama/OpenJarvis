from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openjarvis.agents.codex import CodexAgentError
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.codex import CodexAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


class _Runtime:
    def __init__(self, *, busy: bool = False, history_error: Exception | None = None):
        self.busy = busy
        self.history_error = history_error

    def thread_is_busy(self, thread_id: str) -> bool:
        assert thread_id == "thread-1"
        return self.busy

    def thread_history_page(self, thread_id: str, **kwargs):
        assert thread_id == "thread-1"
        assert kwargs == {
            "limit": 1,
            "items_view": "summary",
            "timeout_seconds": 10.0,
        }
        if self.history_error:
            raise self.history_error
        return SimpleNamespace(
            history=SimpleNamespace(
                messages=[
                    SimpleNamespace(
                        role="assistant", content="resultado", timestamp=1.0
                    )
                ]
            )
        )


class _Agent:
    def __init__(self) -> None:
        self.calls = []

    def run(self, command, context):
        self.calls.append((command, context))
        return SimpleNamespace(content="Resposta completa do Codex")


class _ErrorAgent:
    def __init__(self, code: str) -> None:
        self.code = code

    def run(self, command, context):
        del command, context
        raise CodexAgentError(self.code)


def _context(project: Path) -> AdapterContext:
    return AdapterContext(
        "session-1", str(project), "thread-1", "partition", "request-1"
    )


def test_codex_reads_and_exact_delegation_use_the_selected_target(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    agent = _Agent()
    adapter = CodexAdapter(lambda: runtime, lambda: agent)
    context = _context(tmp_path)

    capabilities = adapter.provider_capabilities()["codex_desktop"].capabilities
    assert capabilities == frozenset(
        {"codex.status", "codex.history", "codex.delegate"}
    )
    assert adapter.execute("codex.status", {}, context).data == {"busy": False}
    history = adapter.execute("codex.history", {"limit": 1}, context)
    assert history.data["messages"][0]["content"] == "resultado"

    prepared = adapter.prepare(
        "codex.delegate", {"command": "Execute exatamente"}, context
    )
    assert prepared.arguments == {
        "project_cwd": str(tmp_path.resolve()),
        "thread_id": "thread-1",
        "command": "Execute exatamente",
    }
    adapter.preflight_delegate(prepared.arguments)
    result = adapter.execute("codex.delegate", prepared.arguments, context)
    assert result.summary == "Resposta completa do Codex"
    assert agent.calls[0][0] == "Execute exatamente"


def test_codex_busy_fails_before_dispatch(tmp_path: Path) -> None:
    agent = _Agent()
    adapter = CodexAdapter(lambda: _Runtime(busy=True), lambda: agent)
    prepared = adapter.prepare(
        "codex.delegate", {"command": "Não deve executar"}, _context(tmp_path)
    )

    with pytest.raises(JarvisAgentError) as error:
        adapter.preflight_delegate(prepared.arguments)

    assert error.value.code == "CODEX_BUSY"
    assert agent.calls == []


def test_codex_history_timeout_has_a_stable_public_error(tmp_path: Path) -> None:
    adapter = CodexAdapter(
        lambda: _Runtime(history_error=TimeoutError("late")), lambda: _Agent()
    )

    with pytest.raises(JarvisAgentError) as error:
        adapter.execute("codex.history", {"limit": 1}, _context(tmp_path))

    assert error.value.code == "CODEX_THREAD_RESUME_TIMEOUT"


@pytest.mark.parametrize(
    ("raw_code", "public_code", "status"),
    (
        ("CODEX_BUSY", "CODEX_BUSY", 409),
        ("CODEX_DUPLICATE_REQUEST", "DUPLICATE_ACTION", 409),
        ("CODEX_PROJECT_INVALID", "CODEX_THREAD_INVALID", 409),
        ("CODEX_THREAD_RESUME_TIMEOUT", "CODEX_THREAD_RESUME_TIMEOUT", 504),
        ("CODEX_CONVERSATION_BINDING_TIMEOUT", "CODEX_DISPATCH_TIMEOUT", 504),
        ("CODEX_DISPATCH_TIMEOUT", "CODEX_DISPATCH_TIMEOUT", 504),
        ("CODEX_CONVERSATION_TURN_FAILED", "EXTERNAL_RESULT_UNKNOWN", 502),
    ),
)
def test_codex_agent_errors_are_mapped_to_stable_public_contracts(
    tmp_path: Path,
    raw_code: str,
    public_code: str,
    status: int,
) -> None:
    adapter = CodexAdapter(lambda: _Runtime(), lambda: _ErrorAgent(raw_code))
    prepared = adapter.prepare(
        "codex.delegate", {"command": "teste"}, _context(tmp_path)
    )

    with pytest.raises(JarvisAgentError) as error:
        adapter.execute("codex.delegate", prepared.arguments, _context(tmp_path))

    assert error.value.code == public_code
    assert error.value.status_code == status
