"""Contract tests for the external Codex agent composition."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.codex import (
    CODEX_CONVERSATION_BINDING_TIMEOUT,
    CODEX_CONVERSATION_BUSY,
    CODEX_CONVERSATION_DISPATCH_TIMEOUT,
    CODEX_CONVERSATION_EMPTY_PUBLIC_TEXT,
    CODEX_CONVERSATION_IDENTITY_REQUIRED,
    CODEX_CONVERSATION_PROJECT_INVALID,
    CODEX_CONVERSATION_SESSION_CLOSED,
    CODEX_CONVERSATION_THREAD_NOT_FOUND,
    CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT,
    CODEX_CONVERSATION_THREAD_START_FAILED,
    CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT,
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
from openjarvis.integrations.codex_conversation import (
    CodexConcurrentTurnError,
    CodexConversationClosed,
    CodexConversationTimeout,
)
from openjarvis.integrations.codex_protocol import (
    CodexRequestError,
    CodexRequestTimeout,
    CodexTurnStatus,
)
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
        self.turn_start_options: list[dict[str, object]] = []
        self.thread_subscribe_calls: list[tuple[str, dict[str, object]]] = []
        self.wait_calls: list[tuple[str, str]] = []
        self.wait_available_calls: list[tuple[str, float]] = []
        self.interrupt_calls: list[tuple[str, str]] = []
        self.thread_lock = threading.Lock()

    def thread_start(self, **kwargs):
        del kwargs
        with self.thread_lock:
            self.thread_start_calls += 1
            number = self.thread_start_calls
        return SimpleNamespace(thread_id=f"private-thread-{number}")

    def turn_start(self, thread_id, input_text, **kwargs):
        self.turn_start_calls.append((thread_id, input_text))
        self.turn_start_options.append(kwargs)
        return SimpleNamespace(turn_id=f"private-turn-{len(self.turn_start_calls)}")

    def thread_subscribe(self, thread_id, **kwargs):
        self.thread_subscribe_calls.append((thread_id, kwargs))
        return SimpleNamespace(
            thread_id=thread_id,
            cwd="D:\\dev\\workspaces\\openjarvis",
        )

    def wait_turn(self, thread_id, turn_id, **kwargs):
        del kwargs
        self.wait_calls.append((thread_id, turn_id))
        return SimpleNamespace(
            status=CodexTurnStatus.COMPLETED,
            final_content=self.content,
        )

    def wait_thread_available(self, thread_id, *, timeout_seconds):
        self.wait_available_calls.append((thread_id, timeout_seconds))

    def turn_interrupt(self, thread_id, turn_id):
        self.interrupt_calls.append((thread_id, turn_id))


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
    assert runtime.turn_start_options == [{"approval_policy": "untrusted"}]
    assert reservation.state is ConversationBindingState.RESERVED


def test_explicit_codex_thread_is_subscribed_without_starting_one(
    tmp_path: Path,
) -> None:
    agent, runtime, store = _agent(tmp_path)
    context = _context()
    context.metadata.update(
        {
            "codex_thread_id": "desktop-thread-1",
            "codex_project_cwd": "D:\\dev\\workspaces\\openjarvis",
            "codex_client_user_message_id": "openjarvis-message-1",
        }
    )

    result = agent.run("ola", context=context)

    assert result.content == "public answer"
    assert runtime.thread_start_calls == 0
    assert runtime.thread_subscribe_calls == [
        (
            "desktop-thread-1",
            {"timeout_seconds": 5.0},
        )
    ]
    assert runtime.turn_start_calls == [("desktop-thread-1", "ola")]
    assert runtime.wait_available_calls == []
    assert runtime.turn_start_options == [
        {
            "approval_policy": "untrusted",
            "cwd": "D:\\dev\\workspaces\\openjarvis",
            "client_user_message_id": "openjarvis-message-1",
        }
    ]
    assert store.lookup(_key()) is None


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (CodexRequestTimeout("late"), CODEX_CONVERSATION_THREAD_RESUME_TIMEOUT),
        (CodexRequestError("missing", code=-1), CODEX_CONVERSATION_THREAD_NOT_FOUND),
        (CodexConversationClosed("closed"), CODEX_CONVERSATION_SESSION_CLOSED),
    ],
)
def test_selected_thread_resume_failures_have_stable_codes(
    tmp_path: Path,
    failure: Exception,
    expected: str,
) -> None:
    class FailingResumeRuntime(FakeRuntime):
        def thread_subscribe(self, thread_id, **kwargs):
            del thread_id, kwargs
            raise failure

    agent, _, _ = _agent(tmp_path, runtime=FailingResumeRuntime())
    context = _context()
    context.metadata["codex_thread_id"] = "desktop-thread-1"

    with pytest.raises(CodexAgentError, match=expected):
        agent.run("ola", context=context)


def test_selected_project_mismatch_has_stable_code(tmp_path: Path) -> None:
    class WrongProjectRuntime(FakeRuntime):
        def thread_subscribe(self, thread_id, **kwargs):
            del kwargs
            return SimpleNamespace(
                thread_id=thread_id,
                cwd="D:\\another-project",
            )

    agent, _, _ = _agent(tmp_path, runtime=WrongProjectRuntime())
    context = _context()
    context.metadata.update(
        {
            "codex_thread_id": "desktop-thread-1",
            "codex_project_cwd": "D:\\wrong-project",
        }
    )

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_PROJECT_INVALID):
        agent.run("ola", context=context)


def test_repeated_client_message_id_reuses_completed_result(tmp_path: Path) -> None:
    agent, runtime, _ = _agent(tmp_path)
    context = _context()
    context.metadata.update(
        {
            "codex_thread_id": "desktop-thread-1",
            "codex_project_cwd": "D:\\dev\\workspaces\\openjarvis",
            "codex_client_user_message_id": "request-1",
        }
    )

    first = agent.run("ola", context=context)
    second = agent.run("ola", context=context)

    assert first.content == second.content == "public answer"
    assert runtime.thread_subscribe_calls == [
        ("desktop-thread-1", {"timeout_seconds": 5.0})
    ]
    assert runtime.turn_start_calls == [("desktop-thread-1", "ola")]


def test_busy_codex_is_rejected_without_waiting_or_retrying(tmp_path: Path) -> None:
    class BusyRuntime(FakeRuntime):
        def turn_start(self, thread_id, input_text, **kwargs):
            del thread_id, input_text, kwargs
            raise CodexConcurrentTurnError("active turn")

    agent, runtime, _ = _agent(tmp_path, runtime=BusyRuntime())
    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_BUSY):
        agent.run("ola", context=_context())
    assert runtime.wait_available_calls == []
    assert runtime.turn_start_calls == []


def test_desktop_owned_busy_turn_is_rejected_before_dispatch(tmp_path: Path) -> None:
    class DesktopBusyRuntime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.busy_checks: list[str] = []

        def thread_is_busy(self, thread_id):
            self.busy_checks.append(thread_id)
            return True

    agent, runtime, _ = _agent(tmp_path, runtime=DesktopBusyRuntime())

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_BUSY):
        agent.run("ola", context=_context())

    assert runtime.busy_checks == ["private-thread-1"]
    assert runtime.turn_start_calls == []


def test_busy_status_timeout_is_distinct_from_a_started_turn_timeout(
    tmp_path: Path,
) -> None:
    class StatusTimeoutRuntime(FakeRuntime):
        def thread_is_busy(self, thread_id):
            del thread_id
            raise CodexRequestTimeout("status read timed out")

    agent, runtime, _ = _agent(tmp_path, runtime=StatusTimeoutRuntime())

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_THREAD_STATUS_TIMEOUT):
        agent.run("ola", context=_context())

    assert runtime.turn_start_calls == []


def test_closed_runtime_during_turn_has_stable_code(tmp_path: Path) -> None:
    class ClosedRuntime(FakeRuntime):
        def wait_turn(self, thread_id, turn_id, **kwargs):
            del thread_id, turn_id, kwargs
            raise CodexConversationClosed("closed")

    agent, _, _ = _agent(tmp_path, runtime=ClosedRuntime())

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_SESSION_CLOSED):
        agent.run("ola", context=_context())


def test_dispatch_timeout_interrupts_only_the_started_turn(tmp_path: Path) -> None:
    class TimeoutRuntime(FakeRuntime):
        def wait_turn(self, thread_id, turn_id, **kwargs):
            del thread_id, turn_id, kwargs
            raise CodexConversationTimeout("late")

    agent, runtime, _ = _agent(
        tmp_path,
        runtime=TimeoutRuntime(),
        turn_wait_timeout_seconds=0.1,
    )

    with pytest.raises(CodexAgentError, match=CODEX_CONVERSATION_DISPATCH_TIMEOUT):
        agent.run("ola", context=_context())

    assert runtime.interrupt_calls == [("private-thread-1", "private-turn-1")]


def test_launcher_can_opt_in_to_no_approval_prompts(tmp_path: Path) -> None:
    agent, runtime, _ = _agent(tmp_path, approval_policy="never")

    result = agent.run("hello", context=_context())

    assert result.content == "public answer"
    assert runtime.turn_start_options == [{"approval_policy": "never"}]


def test_rejects_unknown_approval_policy(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="approval_policy is not supported"):
        _agent(tmp_path, approval_policy="always")


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

        def __init__(self, client_config=None):
            self.config = client_config
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
    assert client.config.experimental_api is True
    system.close()
    system.close()
    assert client.closed == 1
