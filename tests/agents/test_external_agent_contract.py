"""Contract tests for engine-backed and external agent registration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentResult, BaseAgent, ExternalAgent
from openjarvis.core.config import CapabilitiesConfig, JarvisConfig
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import (
    AgentDescriptor,
    AgentExecutionMode,
    AgentRegistry,
    EngineRegistry,
)
from openjarvis.security import GuardrailsEngine, setup_security
from openjarvis.system import QueryOrchestrator, SystemBuilder


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

    replacement = AgentDescriptor("fake_external", external_runtime="replacement")
    AgentRegistry._descriptors()["fake_external"] = replacement
    assert snapshot["fake_external"] is descriptor


def test_descriptor_validation_rejects_invalid_combinations() -> None:
    invalid = [
        (
            "external requires engine",
            dict(
                execution_mode="external",
                requires_engine=True,
                external_runtime="runtime",
            ),
        ),
        (
            "external requires model",
            dict(
                execution_mode="external",
                requires_model=True,
                external_runtime="runtime",
            ),
        ),
        ("external missing runtime", dict(execution_mode="external")),
        (
            "engine external runtime",
            dict(execution_mode="engine", external_runtime="runtime"),
        ),
        (
            "engine without engine",
            dict(execution_mode="engine", requires_engine=False),
        ),
        (
            "engine requires model with no engine",
            dict(execution_mode="engine", requires_engine=False, requires_model=True),
        ),
    ]
    for label, kwargs in invalid:
        with pytest.raises(ValueError, match=""):
            AgentDescriptor(label, **kwargs)

    with pytest.raises(ValueError, match="nonempty"):
        AgentDescriptor("  ")


def test_registry_rejects_descriptor_name_mismatch_and_whitespace_key() -> None:
    class _Candidate:
        pass

    descriptor = AgentDescriptor("other", external_runtime="runtime")
    with pytest.raises(ValueError, match="match registry key"):
        AgentRegistry.register_value(
            "candidate",
            _Candidate,
            descriptor=descriptor,
        )
    with pytest.raises(ValueError, match="surrounding whitespace"):
        AgentRegistry.register_value(" candidate", _Candidate)
    assert AgentRegistry.keys() == ()
    assert AgentRegistry.descriptors() == {}


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


def test_orphan_descriptor_blocks_registration_without_overwrite() -> None:
    class _Candidate:
        agent_id = "original"

    original = AgentDescriptor("orphan", external_runtime="original-runtime")
    AgentRegistry._descriptors()["orphan"] = original

    with pytest.raises(ValueError, match="entry or descriptor"):
        AgentRegistry.register_value(
            "orphan",
            _Candidate,
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="replacement-runtime",
        )

    assert AgentRegistry._descriptors()["orphan"] is original
    assert not AgentRegistry.contains("orphan")
    assert _Candidate.agent_id == "original"


def test_orphan_entry_blocks_registration_without_creating_descriptor() -> None:
    class _Orphan:
        pass

    class _Candidate:
        pass

    AgentRegistry._entries()["orphan"] = _Orphan
    with pytest.raises(ValueError, match="entry or descriptor"):
        AgentRegistry.register_value(
            "orphan",
            _Candidate,
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="runtime",
        )

    assert AgentRegistry._entries()["orphan"] is _Orphan
    assert "orphan" not in AgentRegistry._descriptors()
    assert "agent_id" not in vars(_Candidate)


class _FailingDescriptorStorage(dict):
    def __setitem__(self, key, value):
        raise RuntimeError("descriptor write failure")


def test_descriptor_write_failure_rolls_back_class_and_agent_id(monkeypatch) -> None:
    descriptor_storage = _FailingDescriptorStorage()
    monkeypatch.setattr(
        AgentRegistry,
        "_descriptors",
        classmethod(lambda cls: descriptor_storage),
    )

    class _Candidate:
        pass

    with pytest.raises(RuntimeError, match="descriptor write failure"):
        AgentRegistry.register_value(
            "broken",
            _Candidate,
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="runtime",
        )

    assert "broken" not in AgentRegistry._entries()
    assert "broken" not in descriptor_storage
    assert "agent_id" not in vars(_Candidate)


def test_descriptor_write_failure_restores_existing_agent_id(monkeypatch) -> None:
    descriptor_storage = _FailingDescriptorStorage()
    monkeypatch.setattr(
        AgentRegistry,
        "_descriptors",
        classmethod(lambda cls: descriptor_storage),
    )

    class _Candidate:
        agent_id = ""

    with pytest.raises(RuntimeError, match="descriptor write failure"):
        AgentRegistry.register_value(
            "broken",
            _Candidate,
            execution_mode=AgentExecutionMode.EXTERNAL,
            external_runtime="runtime",
        )

    assert _Candidate.agent_id == ""
    assert "agent_id" in vars(_Candidate)
    assert "broken" not in AgentRegistry._entries()


def test_agent_registry_clear_removes_entries_and_descriptors() -> None:
    _register_external()
    AgentRegistry.clear()
    assert AgentRegistry.keys() == ()
    assert AgentRegistry.descriptors() == {}


def test_registry_create_works_for_legacy_and_external_agents() -> None:
    class _Legacy:
        def __init__(self, value):
            self.value = value

    AgentRegistry.register("legacy")(_Legacy)
    assert AgentRegistry.create("legacy", 7).value == 7

    external_cls = _register_external("created_external")
    instance = AgentRegistry.create("created_external", bus=EventBus())
    assert isinstance(instance, external_cls)
    assert instance._engine is None
    assert instance._model is None


def test_engine_and_model_must_be_supplied_as_a_pair() -> None:
    class _EngineAgent(BaseAgent):
        def run(self, input, context=None, **kwargs):
            return AgentResult(content=input)

    AgentRegistry.register("engine_pair")(_EngineAgent)
    with pytest.raises(TypeError, match="provided together"):
        _EngineAgent(engine=object())
    with pytest.raises(TypeError, match="provided together"):
        _EngineAgent(model="model")


def test_unregistered_external_agent_has_no_implicit_permission() -> None:
    class _Unregistered(ExternalAgent):
        def run(self, input, context=None, **kwargs):
            return AgentResult(content=input)

    _Unregistered.agent_id = "unregistered"
    with pytest.raises(TypeError, match="ENGINE_REQUIRED_FOR_SELECTED_AGENT"):
        _Unregistered()


def test_external_agent_rejects_positional_engine_and_model() -> None:
    agent_cls = _register_external()
    with pytest.raises(TypeError):
        agent_cls(object(), "model")


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


def test_external_agent_generate_error_is_stable() -> None:
    agent = _register_external()(bus=EventBus())
    with pytest.raises(RuntimeError, match="ENGINE_REQUIRED_FOR_SELECTED_AGENT"):
        agent._generate([])


def test_agent_registry_isolated_from_other_registries() -> None:
    _register_external()
    assert not EngineRegistry.contains("fake_external")


def _minimal_builder_config(tmp_path, *, external: bool = True) -> JarvisConfig:
    config = JarvisConfig()
    config.agent.default_agent = "fake_external" if external else "engine_agent"
    config.security.enabled = False
    config.telemetry.enabled = True
    config.telemetry.db_path = str(tmp_path / "telemetry.db")
    config.traces.enabled = True
    config.traces.db_path = str(tmp_path / "traces.db")
    config.skills.enabled = False
    config.agent_manager.enabled = False
    config.learning.enabled = False
    config.learning.training_enabled = False
    config.proactive.enabled = False
    return config


def test_external_builder_uses_real_system_builder_without_engine_stack(
    monkeypatch, tmp_path
) -> None:
    _register_external()
    config = _minimal_builder_config(tmp_path)

    class _ForbiddenEngine:
        def health(self):
            raise AssertionError("external agent called engine.health")

        def list_models(self):
            raise AssertionError("external agent called engine.list_models")

    builder = (
        SystemBuilder(config)
        .agent("fake_external")
        .engine_instance(_ForbiddenEngine())
        .speech(False)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("external agent resolved local engine state")

    monkeypatch.setattr(builder, "_resolve_engine", forbidden)
    monkeypatch.setattr(builder, "_resolve_model", forbidden)
    monkeypatch.setattr(builder, "_setup_telemetry", forbidden)
    monkeypatch.setattr(builder, "_resolve_tools", forbidden)

    import openjarvis.engine._discovery as discovery
    import openjarvis.telemetry.instrumented_engine as instrumented_engine
    import openjarvis.traces.store as trace_store

    monkeypatch.setattr(discovery, "get_engine", forbidden)
    monkeypatch.setattr(instrumented_engine, "InstrumentedEngine", forbidden)
    monkeypatch.setattr(trace_store, "TraceStore", forbidden)

    system = builder.build()
    assert system.agent_name == "fake_external"
    assert system.engine is None
    assert system.engine_key is None
    assert system.model is None
    assert system.tools == []
    assert system.tool_executor is None
    assert system.telemetry_store is None
    assert system.trace_store is None
    assert system.trace_collector is None
    system.close()


def _mock_engine(content: str = "ok", models=None) -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "test-engine"
    engine.health.return_value = True
    engine.list_models.return_value = models or ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def test_engine_builder_and_orchestrator_contracts_remain_unchanged(
    monkeypatch,
    tmp_path,
) -> None:
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.agents.simple import SimpleAgent

    if not AgentRegistry.contains("simple"):
        AgentRegistry.register_value("simple", SimpleAgent)
    if not AgentRegistry.contains("orchestrator"):
        AgentRegistry.register_value("orchestrator", OrchestratorAgent)
    engine = _mock_engine()
    config = _minimal_builder_config(tmp_path, external=False)
    config.intelligence.default_model = ""
    builder = (
        SystemBuilder(config)
        .agent("simple")
        .engine_instance(engine, key="test-engine")
        .speech(False)
        .telemetry(False)
        .traces(False)
    )
    engine_calls = []
    model_calls = []
    resolve_engine = builder._resolve_engine
    resolve_model = builder._resolve_model

    def tracked_engine(config):
        engine_calls.append(True)
        return resolve_engine(config)

    def tracked_model(config, selected_engine):
        model_calls.append(True)
        return resolve_model(config, selected_engine)

    monkeypatch.setattr(builder, "_resolve_engine", tracked_engine)
    monkeypatch.setattr(builder, "_resolve_model", tracked_model)
    system = builder.build()

    assert engine_calls == [True]
    assert model_calls == [True]
    assert system.engine is engine
    assert system.model == "test-model"
    assert engine.health.called
    assert engine.list_models.called
    assert system.ask("hello", context=False)["content"] == "ok"

    orchestrator_result = system.ask("hello", context=False, agent="orchestrator")
    assert orchestrator_result["content"] == "ok"
    system.close()


def test_direct_query_without_engine_has_stable_error() -> None:
    system = _external_system()
    system.agent_name = "none"
    result = QueryOrchestrator(system).ask("hello", context=False)
    assert result["error_code"] == "ENGINE_REQUIRED_FOR_SELECTED_AGENT"


def test_external_builder_never_falls_back_to_injected_engine(tmp_path) -> None:
    _register_external()
    system = (
        SystemBuilder(_minimal_builder_config(tmp_path))
        .agent("fake_external")
        .engine_instance(_mock_engine(), key="injected")
        .speech(False)
        .build()
    )
    assert system.engine is None
    assert system.engine_key is None
    assert system.model is None
    system.close()


def test_security_without_engine_keeps_capability_and_audit(
    monkeypatch,
    tmp_path,
) -> None:
    import openjarvis.security as security

    config = JarvisConfig()
    config.security.enabled = True
    config.security.audit_log_path = str(tmp_path / "audit.db")
    config.security.capabilities = CapabilitiesConfig(
        enabled=True,
        policy_path=str(tmp_path / "policy.json"),
    )

    def forbidden_guardrails(*args, **kwargs):
        raise AssertionError("GuardrailsEngine must not wrap a missing engine")

    monkeypatch.setattr(security, "GuardrailsEngine", forbidden_guardrails)
    sec = setup_security(config, None, EventBus())
    assert sec.engine is None
    assert sec.capability_policy is not None
    assert sec.audit_logger is not None
    sec.audit_logger.close()


def test_security_with_engine_still_wraps_guardrails(tmp_path) -> None:
    config = JarvisConfig()
    config.security.enabled = True
    config.security.audit_log_path = str(tmp_path / "audit.db")
    config.security.capabilities = CapabilitiesConfig(enabled=False)
    engine = _mock_engine()

    sec = setup_security(config, engine, EventBus())
    assert isinstance(sec.engine, GuardrailsEngine)
    assert sec.engine._engine is engine
    assert sec.audit_logger is not None
    sec.audit_logger.close()


def test_external_agent_does_not_build_tools_or_subscribe_inference_telemetry(
    monkeypatch,
) -> None:
    _register_external()
    system = _external_system()
    system.tools = [object()]

    def forbidden_tools(*args, **kwargs):
        raise AssertionError("external agent requested engine-backed tools")

    monkeypatch.setattr(system, "_build_tools", forbidden_tools, raising=False)
    assert not system.bus._subscribers.get(EventType.INFERENCE_END, [])
    result = QueryOrchestrator(system).ask(
        "hello",
        context=False,
        tools=["llm"],
    )
    assert result["model"] is None
    assert result["engine"] is None
    assert not system.bus._subscribers.get(EventType.INFERENCE_END, [])


def test_external_trace_store_is_not_used(monkeypatch) -> None:
    _register_external()
    system = _external_system()
    system.trace_store = object()

    class _ForbiddenCollector:
        def __init__(self, *args, **kwargs):
            raise AssertionError("external agent must not use TraceCollector")

    import openjarvis.traces.collector as collector_module

    monkeypatch.setattr(collector_module, "TraceCollector", _ForbiddenCollector)
    result = QueryOrchestrator(system).ask("hello", context=False)
    assert result["content"] == "external:hello"


def test_external_constructor_type_error_is_not_reinterpreted() -> None:
    class _ConstructorFailure(ExternalAgent):
        def __init__(self, **kwargs):
            raise TypeError("constructor failure")

        def run(self, input, context=None, **kwargs):
            return AgentResult(content=input)

    AgentRegistry.register(
        "constructor_failure",
        execution_mode=AgentExecutionMode.EXTERNAL,
        external_runtime="runtime",
    )(_ConstructorFailure)
    system = _external_system()
    with pytest.raises(TypeError, match="constructor failure"):
        QueryOrchestrator(system).ask(
            "hello",
            context=False,
            agent="constructor_failure",
        )


def test_external_run_type_error_is_not_reinterpreted() -> None:
    class _RunFailure(ExternalAgent):
        def run(self, input, context=None, **kwargs):
            raise TypeError("run failure")

    AgentRegistry.register(
        "run_failure",
        execution_mode=AgentExecutionMode.EXTERNAL,
        external_runtime="runtime",
    )(_RunFailure)
    system = _external_system()
    with pytest.raises(TypeError, match="run failure"):
        QueryOrchestrator(system).ask(
            "hello",
            context=False,
            agent="run_failure",
        )


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
