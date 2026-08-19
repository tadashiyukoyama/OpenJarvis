from __future__ import annotations

from openjarvis.server.jarvis_agent.registry.execution_gates import (
    ToolExecutionGates,
)

_GATE_ENV = (
    "OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED",
    "OPENJARVIS_ACELERACHAT_MUTATIONS_ENABLED",
    "OPENJARVIS_WHATSAPP_MUTATIONS_ENABLED",
    "OPENJARVIS_EMAIL_MUTATIONS_ENABLED",
    "OPENJARVIS_CODEX_DELEGATION_ENABLED",
)


def test_vps_execution_gates_fail_closed(monkeypatch) -> None:
    for name in _GATE_ENV:
        monkeypatch.delenv(name, raising=False)

    gates = ToolExecutionGates.from_environment("vps")

    assert gates == ToolExecutionGates(False, False, False, False, False)


def test_specific_execution_gates_override_the_legacy_default(monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED", "false")
    monkeypatch.setenv("OPENJARVIS_ACELERACHAT_MUTATIONS_ENABLED", "true")
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_MUTATIONS_ENABLED", "true")
    monkeypatch.setenv("OPENJARVIS_EMAIL_MUTATIONS_ENABLED", "false")
    monkeypatch.setenv("OPENJARVIS_CODEX_DELEGATION_ENABLED", "true")

    gates = ToolExecutionGates.from_environment("vps")

    assert gates.default_mutations is False
    assert gates.acelerachat_mutations is True
    assert gates.whatsapp_mutations is True
    assert gates.email_mutations is False
    assert gates.codex_delegation is True
