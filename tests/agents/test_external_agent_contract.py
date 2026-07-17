"""Contract tests for engine-backed and external agent registration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from openjarvis.agents._stubs import AgentResult, BaseAgent, ExternalAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import (
    AgentDescriptor,
    AgentExecutionMode,
    AgentRegistry,
    EngineRegistry,
)
from openjarvis.system import QueryOrchestrator


def _register_external(name: str = "fake_external"):
    class _FakeExternalAgent(ExternalAgent):
        def run(self, input, context=None, **kwargs):
            return AgentResult(content=f"external:{input}", turns=1)

    AgentRegistry.register(
        name,
        execution_mode=AgentExecutionMode.EXTERNAL,
        external_runtime="test-runtime",
    )(_FakeExternalAgent)
    return _FakeExternalAgent


def test_legacy_agent_registration_is_engine_backed() -> None:
    class _LegacyAgent:
        pass

    AgentRegistry.register("legacy")(_LegacyAgent)

    descriptor = AgentRegistry.descriptor("legacy")
    assert descriptor.execution_mode is AgentExecutionMode.ENGINE
    assert descriptor.requires_engine is True
    assert descriptor.requires_model is True
    assert descriptor.external_runtime is None


def test_external_registration_is_engine_free_and_preserves_class() -> None:
    agent_cls = _register_external()

    assert AgentRegistry.get("fake_external") is agent_cls
    descriptor = AgentRegistry.descriptor("fake_external")
    assert descriptor.execution_mode is AgentExecutionMode.EXTERNAL
    assert descriptor.requires_engine is False
    assert descriptor.requires_model is False
    assert descriptor.external_runtime == "test-runtime"


def test_descriptors_are_immutable_read_only_snapshots() -> None:
    _register_external()
    descriptor = AgentRegistry.descriptor("fake_external")

    with pytest.raises(FrozenInstanceError):
        descriptor.external_runtime = "changed"  # type: ignore[misc]

    snapshot = AgentRegistry.descriptors()
    with pytest.raises(TypeError):
        snapshot["other"] = descriptor  # type: ignore[index]


def test_duplicate_agent_registration_is_atomic() -> None:
    _register_external()

    class _Replacement:
        pass

    with pytest.raises(ValueError, match="already has an entry"):
        AgentRegistry.register_value(
            "fake_external",
            _Replacement,
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="replacement",
        )

    assert AgentRegistry.get("fake_external") is not _Replacement
    assert AgentRegistry.descriptor("fake_external").external_runtime == "test-runtime"


@pytest.mark.parametrize(
    "descriptor",
    [
        AgentDescriptor(
            "valid-external",
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="runtime",
        ),
    ],
)
def test_descriptor_name_is_preserved(descriptor: AgentDescriptor) -> None:
    assert descriptor.name == "valid-external"


def test_invalid_external_invariants_are_rejected() -> None:
    with pytest.raises(ValueError):
        AgentDescriptor("missing-runtime", execution_mode="external")
    with pytest.raises(ValueError):
        AgentDescriptor(
            "needs-model",
            execution_mode="external",
            requires_model=True,
            external_runtime="runtime",
        )
    with pytest.raises(ValueError):
        AgentDescriptor(
            "needs-engine",
            execution_mode="external",
            requires_engine=True,
            external_runtime="runtime",
        )


def test_engine_backed_base_agent_rejects_missing_engine() -> None:
    class _EngineAgent(BaseAgent):
        def run(self, input, context=None, **kwargs):
            return AgentResult(content=input)

    AgentRegistry.register("engine_agent")(_EngineAgent)
    with pytest.raises(TypeError, match="ENGINE_REQUIRED_FOR_SELECTED_AGENT"):
        _EngineAgent()


def test_external_base_agent_runs_without_engine_and_cannot_generate() -> None:
    agent_cls = _register_external()
    agent = agent_cls(bus=EventBus())

    result = agent.run("ping")
    assert result.content == "external:ping"
    with pytest.raises(RuntimeError, match="ENGINE_REQUIRED_FOR_SELECTED_AGENT"):
        agent._generate([])


def test_agent_registry_isolated_from_other_registries() -> None:
    _register_external()
    assert not EngineRegistry.contains("fake_external")


def _external_system() -> SimpleNamespace:
    from openjarvis.core.config import JarvisConfig

    return SimpleNamespace(
        config=JarvisConfig(),
        bus=EventBus(record_history=True),
        engine=None,
        engine_key=None,
        model=None,
        agent_name="fake_external",
        tools=[],
        memory_backend=None,
        capability_policy=None,
        session_store=None,
        trace_store=None,
        trace_collector=None,
        _skill_few_shot_examples=None,
    )


def test_external_orchestrator_runs_without_engine_or_engine_tools() -> None:
    _register_external()
    system = _external_system()

    result = QueryOrchestrator(system).ask(
        "hello",
        context=False,
        tools=["llm"],
    )

    assert result["content"] == "external:hello"
    assert result["model"] is None
    assert result["engine"] is None
    assert result["_telemetry"] == {}
    assert not system.bus.history


def test_engine_agent_without_engine_returns_stable_error() -> None:
    class _EngineAgent:
        def run(self, input, context=None, **kwargs):
            raise AssertionError("must not instantiate")

    AgentRegistry.register("engine_agent")(_EngineAgent)
    system = _external_system()

    result = QueryOrchestrator(system).ask(
        "hello",
        context=False,
        agent="engine_agent",
    )

    assert result["error_code"] == "ENGINE_REQUIRED_FOR_SELECTED_AGENT"
    assert result["error"] is True
