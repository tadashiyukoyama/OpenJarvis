"""Contract tests for the external Codex agent composition."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.codex import (
    CODEX_CONVERSATION_BINDING_TIMEOUT,
    CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT,
    CODEX_CONVERSATION_IDENTITY_REQUIRED,
    CODEX_CONVERSATION_THREAD_START_FAILED,
    CodexAgent,
    CodexAgentError,
)
from openjarvis.core.config import JarvisConfig
from openjarvis.core.conversation_identity import (
    ConversationBindingKey,
    ConversationBindingState,
    ConversationIdentity,
    SQLiteConversationBindingStore,
)
from openjarvis.core.registry import AgentExecutionMode, AgentRegistry
from openjarvis.integrations.codex_protocol import CodexTurnStatus
from openjarvis.system import SystemBuilder


@pytest.fixture(autouse=True)
def _register_codex_after_registry_clear() -> None:
    if not AgentRegistry.contains("codex"):
        AgentRegistry.register_value(
            "codex",
            CodexAgent,
            execution_mode=AgentExecutionMode.EXTERNAL,
            requires_engine=False,
            requires_model=False,
            external_runtime="codex_app_server",
        )


class FakeRuntime:
    def __init__(self, *, content: str = "public answer") -> None:
        self.content = content
        self.thread_start_calls = 0
        self.turn_start_calls: list[tuple[str, str]] = []
        self.wait_calls: list[tuple[str, str]] = []
        self.thread_lock = threading.Lock()

    def thread_start(self, **kwargs):
        del kwargs
        with self.thread_lock:
            self.thread_start_calls += 1
            number = self.thread_start_calls
        return SimpleNamespace(thread_id=f"private-thread-{number}")

    def turn_start(self, thread_id, input_text, **kwargs):
        del kwargs
        self.turn_start_calls.append((thread_id, input_text))
        return SimpleNamespace(turn_id=f"private-turn-{len(self.turn_start_calls)}")

    def wait_turn(self, thread_id, turn_id, **kwargs):
        del kwargs
        self.wait_calls.append((thread_id, turn_id))
        return SimpleNamespace(
            status=CodexTurnStatus.COMPLETED,
            final_content=self.content,
        )


def _identity() -> ConversationIdentity:
    return ConversationIdentity("conversation-1", "scope-1")


def _context() -> AgentContext:
    return AgentContext(conversation_identity=_identity())


def _agent(tmp_path: Path, runtime=None, **kwargs):
    runtime = runtime or FakeRuntime()
    store = SQLiteConversationBindingStore(tmp_path / "bindings.sqlite3")
    owner_token_factory = kwargs.pop("owner_token_factory", lambda: "owner-token")
    return (
        CodexAgent(
            runtime,
            store,
            owner_token_factory=owner_token_factory,
            **kwargs,
        ),
        runtime,
        store,
    )


def _key() -> ConversationBindingKey:
    return ConversationBindingKey(
        identity=_identity(),
        agent_name="codex",
        external_runtime="codex_app_server",
    )


def test_codex_is_registered_as_external_without_engine_or_model() -> None:
    descriptor = AgentRegistry.descriptor("codex")
    assert descriptor.name == "codex"
    assert descriptor.execution_mode is AgentExecutionMode.EXTERNAL
    assert descriptor.requires_engine is False
    assert descriptor.requires_model is False
    assert descriptor.external_runtime == "codex_app_server"


def test_codex_requires_context_and_identity(tmp_path: Path) -> None:
    agent, _, _ = _agent(tmp_path)
    with pytest.raises(ValueError, match="CODEX_CONVERSATION_CONTEXT_REQUIRED"):
        agent.run("hello")
    with pytest.raises(ValueError, match=CODEX_CONVERSATION_IDENTITY_REQUIRED):
        agent.run("hello", context=AgentContext())


def test_bound_binding_reuses_existing_thread(tmp_path: Path) -> None:
    agent, runtime, store = _agent(tmp_path)
    key = _key()
    reservation = store.reserve(key, "existing-owner", 30)
    store.complete_reservation(key, "existing-owner", "private-existing-thread")

    result = agent.run("hello", context=_context())

    assert result.content == "public answer"
    assert runtime.thread_start_calls == 0
    assert runtime.turn_start_calls == [("private-existing-thread", "hello")]
    assert reservation.state is ConversationBindingState.RESERVED


def test_unbound_binding_starts_exactly_one_thread_and_completes(
    tmp_path: Path,
) -> None:
    agent, runtime, store = _agent(tmp_path)

    result = agent.run("hello", context=_context())

    assert result.content == "public answer"
    assert runtime.thread_start_calls == 1
    binding = store.lookup(_key())
    assert binding is not None
    assert binding.state is ConversationBindingState.BOUND
    assert binding.external_conversation_id == "private-thread-1"


def test_thread_start_failure_releases_reservation(tmp_path: Path) -> None:
    class FailingRuntime(FakeRuntime):
        def thread_start(self, **kwargs):
            del kwargs
            raise RuntimeError("private-thread-id must not escape")

    agent, _, store = _agent(tmp_path, runtime=FailingRuntime())
    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_THREAD_START_FAILED):
        agent.run("hello", context=_context())
    assert store.lookup(_key()) is None


def test_busy_reservation_waits_for_bound(tmp_path: Path) -> None:
    agent, runtime, store = _agent(
        tmp_path,
        binding_wait_timeout_seconds=1.0,
    )
    key = _key()
    store.reserve(key, "blocking-owner", 30)

    busy_seen = threading.Event()

    class TrackingStore:
        def lookup(self, binding_key):
            return store.lookup(binding_key)

        def reserve(self, binding_key, owner_token, lease_seconds):
            reservation = store.reserve(binding_key, owner_token, lease_seconds)
            if reservation.state is ConversationBindingState.BUSY:
                busy_seen.set()
            return reservation

        def complete_reservation(self, *args):
            return store.complete_reservation(*args)

        def release_reservation(self, *args):
            return store.release_reservation(*args)

    agent._binding_store = TrackingStore()

    def bind_later() -> None:
        busy_seen.wait(timeout=1)
        store.complete_reservation(key, "blocking-owner", "private-bound-thread")

    worker = threading.Thread(target=bind_later)
    worker.start()
    result = agent.run("hello", context=_context())
    worker.join(timeout=1)

    assert result.content == "public answer"
    assert runtime.thread_start_calls == 0


def test_busy_reservation_has_bounded_timeout(tmp_path: Path) -> None:
    agent, runtime, store = _agent(
        tmp_path,
        binding_wait_timeout_seconds=0.1,
    )
    store.reserve(_key(), "blocking-owner", 30)

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_BINDING_TIMEOUT):
        agent.run("hello", context=_context())
    assert runtime.thread_start_calls == 0


@pytest.mark.parametrize("repetition", range(20))
def test_concurrent_same_identity_starts_at_most_one_thread(
    tmp_path: Path, repetition: int
) -> None:
    tmp_path = tmp_path / str(repetition)
    runtime = FakeRuntime()
    owner_counter = iter(range(20))
    owner_lock = threading.Lock()

    def owner_token() -> str:
        with owner_lock:
            return f"owner-token-{next(owner_counter)}"

    agent, _, store = _agent(
        tmp_path,
        runtime=runtime,
        binding_wait_timeout_seconds=3.0,
        owner_token_factory=owner_token,
    )
    start = threading.Barrier(20)
    results = []
    failures = []
    lock = threading.Lock()

    def run_one() -> None:
        try:
            start.wait(timeout=2)
            result = agent.run("hello", context=_context())
            with lock:
                results.append(result)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            with lock:
                failures.append(exc)

    workers = [threading.Thread(target=run_one) for _ in range(20)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)

    assert all(not worker.is_alive() for worker in workers)
    assert failures == []
    assert len(results) == 20
    assert runtime.thread_start_calls == 1
    assert store.lookup(_key()).state is ConversationBindingState.BOUND


def test_public_result_excludes_reasoning_and_private_ids(tmp_path: Path) -> None:
    agent, _, _ = _agent(
        tmp_path,
        runtime=FakeRuntime(content="<think>private reasoning</think>public answer"),
    )
    result = agent.run("hello", context=_context())

    rendered = repr(result)
    assert result.content == "public answer"
    assert "private reasoning" not in rendered
    assert "private-thread" not in rendered
    assert "private-turn" not in rendered
    assert "thread_id" not in result.metadata
    assert "turn_id" not in result.metadata
    assert "reasoning" not in result.metadata


def test_empty_public_text_returns_stable_error_without_reasoning(
    tmp_path: Path,
) -> None:
    agent, _, _ = _agent(tmp_path, runtime=FakeRuntime(content=""))
    result = agent.run("hello", context=_context())
    assert result.content == CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT
    assert result.metadata["error_code"] == CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT


def test_builder_composes_codex_without_engine_and_closes_client_once(
    monkeypatch, tmp_path: Path
) -> None:
    import openjarvis.integrations.codex_app_server as app_server
    import openjarvis.integrations.codex_conversation as conversation

    class FakeClient:
        is_ready = True

        def __init__(self):
            self.started = 0
            self.closed = 0

        def start(self):
            self.started += 1

        def close(self):
            self.closed += 1

    class FakeConversationRuntime:
        def __init__(self, client):
            self.client = client
            self.closed = 0

        def close(self):
            self.closed += 1

        def thread_start(self, **kwargs):
            del kwargs
            return SimpleNamespace(thread_id="private-thread")

        def turn_start(self, thread_id, input_text, **kwargs):
            del thread_id, input_text, kwargs
            return SimpleNamespace(turn_id="private-turn")

        def wait_turn(self, thread_id, turn_id, **kwargs):
            del thread_id, turn_id, kwargs
            return SimpleNamespace(
                status=CodexTurnStatus.COMPLETED,
                final_content="public",
            )

    monkeypatch.setattr(app_server, "CodexAppServerClient", FakeClient)
    monkeypatch.setattr(
        conversation, "CodexConversationRuntime", FakeConversationRuntime
    )
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "state"))

    config = JarvisConfig()
    config.agent.default_agent = "codex"
    config.security.enabled = False
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.skills.enabled = False
    config.agent_manager.enabled = False
    config.learning.enabled = False
    config.learning.training_enabled = False
    config.proactive.enabled = False
    config.memory.db_path = str(tmp_path / "memory.db")
    builder = SystemBuilder(config).agent("codex").speech(False)
    monkeypatch.setattr(
        builder,
        "_resolve_engine",
        lambda config: (_ for _ in ()).throw(AssertionError("engine resolved")),
    )
    monkeypatch.setattr(
        builder,
        "_resolve_model",
        lambda config, engine: (_ for _ in ()).throw(AssertionError("model resolved")),
    )

    system = builder.build()
    client = system.codex_client
    assert system.engine is None
    assert system.model is None
    assert system.agent is not None
    assert client.started == 1
    system.close()
    system.close()
    assert client.closed == 1
