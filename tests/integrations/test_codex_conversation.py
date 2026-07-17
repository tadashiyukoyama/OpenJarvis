"""Offline contract tests for the sanitized Codex conversation runtime."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

from openjarvis.integrations import (
    CodexAppServerClient,
    CodexAppServerConfig,
    CodexAppServerState,
    CodexConcurrentTurnError,
    CodexConversationClientFailed,
    CodexConversationClosed,
    CodexConversationRuntime,
    CodexConversationTimeout,
    CodexInvalidStateError,
    CodexTurnStatus,
    JsonRpcNotification,
)

FAKE_CONVERSATION_SERVER = r"""
import json
import sys

turn_number = 0

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {}})
    elif method == "initialized":
        pass
    elif method in ("thread/start", "thread/resume"):
        thread_id = request.get("params", {}).get("threadId", "fake-thread")
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "thread": {"id": thread_id, "status": "idle", "cwd": "D:/fake"}
        }})
    elif method == "thread/read":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "thread": {"id": request["params"]["threadId"], "status": "idle"}
        }})
    elif method == "thread/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "data": [{"id": "fake-thread", "status": "idle"}],
            "nextCursor": None,
        }})
    elif method == "turn/start":
        turn_number += 1
        turn_id = "fake-turn-" + str(turn_number)
        thread_id = request["params"]["threadId"]
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "turn": {"id": turn_id, "status": "inProgress", "items": []}
        }})
        send({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {
            "threadId": thread_id, "turnId": turn_id, "delta": "fake-public"
        }})
        send({"jsonrpc": "2.0", "method": "turn/completed", "params": {
            "threadId": thread_id,
            "turn": {"id": turn_id, "status": "completed", "items": []}
        }})
    elif method == "turn/interrupt":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {}})
"""


class FakeConversationClient:
    """Deterministic in-memory stand-in for an already-ready app-server client."""

    is_ready = True
    state = CodexAppServerState.READY

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.callback = None
        self.next_turn = 1
        self.emit_before_turn_response = False

    def subscribe_notifications(self, callback):
        self.callback = callback
        return 1

    def unsubscribe_notifications(self, token):
        del token
        self.callback = None
        return True

    def request(self, method, params=None, *, timeout_seconds=None):
        del timeout_seconds
        self.calls.append((method, params))
        if method in {"thread/start", "thread/resume"}:
            return {
                "thread": {
                    "id": params.get("threadId", "thread-1"),
                    "status": "idle",
                    "cwd": params.get("cwd", "D:/project"),
                    "modelProvider": "codex",
                    "name": "private thread name",
                },
                "model": None,
            }
        if method == "thread/read":
            return {
                "thread": {
                    "id": params["threadId"],
                    "status": "idle",
                    "cwd": "D:/private/other",
                    "turns": [{"items": [{"type": "reasoning", "content": ["x"]}]}],
                }
            }
        if method == "thread/list":
            return {
                "data": [{"id": "thread-1", "status": "idle", "cwd": "D:/project"}],
                "nextCursor": "next-1",
            }
        if method == "turn/start":
            turn_id = f"turn-{self.next_turn}"
            self.next_turn += 1
            if self.emit_before_turn_response and self.callback is not None:
                self.emit(
                    "item/agentMessage/delta",
                    {
                        "threadId": params["threadId"],
                        "turnId": turn_id,
                        "itemId": "item-1",
                        "delta": "early ",
                    },
                )
            return {"turn": {"id": turn_id, "status": "inProgress", "items": []}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(f"unexpected method: {method}")

    def emit(self, method, params):
        if self.callback is not None:
            self.callback(JsonRpcNotification(method, params))


class CodexConversationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeConversationClient()
        self.runtime = CodexConversationRuntime(self.client)
        self.waiter_threads: list[threading.Thread] = []

    def tearDown(self) -> None:
        closed = threading.Event()

        def close() -> None:
            self.runtime.close()
            closed.set()

        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        self.assertTrue(closed.wait(timeout=1))
        for thread in self.waiter_threads:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

    def _wait_for(self, predicate, timeout_seconds: float = 1) -> bool:
        deadline = time.monotonic() + timeout_seconds
        pulse = threading.Event()
        while time.monotonic() < deadline:
            if predicate():
                return True
            pulse.wait(0.005)
        return predicate()

    def _start_waiter(
        self, info, timeout_seconds: float | None = None, expected_waiters: int = 1
    ):
        state = self.runtime._turns[(info.thread_id, info.turn_id)]
        started = threading.Event()
        outcome: dict[str, object] = {}

        def wait() -> None:
            started.set()
            try:
                outcome["result"] = self.runtime.wait_turn(
                    info.thread_id,
                    info.turn_id,
                    timeout_seconds=timeout_seconds,
                )
            except BaseException as exc:
                outcome["error"] = exc

        thread = threading.Thread(target=wait, daemon=True)
        self.waiter_threads.append(thread)
        thread.start()
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(
            self._wait_for(lambda: state.waiters >= expected_waiters),
            "waiter did not enter the condition",
        )
        return thread, outcome, state

    def _emit_completed(
        self, info, *, text: str | None = None, status: str = "completed"
    ):
        items = []
        if text is not None:
            items.append(
                {"type": "agentMessage", "phase": "final_answer", "text": text}
            )
        self.client.emit(
            "turn/completed",
            {
                "threadId": info.thread_id,
                "turn": {"id": info.turn_id, "status": status, "items": items},
            },
        )

    def _emit_item_completed(self, info, text: str) -> None:
        self.client.emit(
            "item/completed",
            {
                "threadId": info.thread_id,
                "turnId": info.turn_id,
                "item": {
                    "id": "item-final",
                    "type": "agentMessage",
                    "text": text,
                },
            },
        )

    def test_thread_start_uses_stable_fields_and_fail_closed_defaults(self) -> None:
        info = self.runtime.thread_start(cwd="D:\\Project", model=None)
        method, params = self.client.calls[-1]
        self.assertEqual(method, "thread/start")
        self.assertEqual(params["cwd"], "D:\\Project")
        self.assertEqual(params["approvalPolicy"], "untrusted")
        self.assertNotIn("sandbox", params)
        self.assertNotIn("model", params)
        self.assertEqual(info.cwd_status.value, "EXPECTED")
        self.assertNotIn("D:\\Project", repr(info))

    def test_runtime_requires_ready_and_does_not_make_catalog_calls(self) -> None:
        not_ready = FakeConversationClient()
        not_ready.is_ready = False
        with self.assertRaises(CodexInvalidStateError):
            CodexConversationRuntime(not_ready)
        self.assertEqual(not_ready.calls, [])
        self.assertEqual(self.client.calls, [])

    def test_resume_read_list_are_explicit_and_sanitized(self) -> None:
        resumed = self.runtime.thread_resume("thread-9")
        self.assertEqual(resumed.thread_id, "thread-9")
        read = self.runtime.thread_read("thread-9")
        self.assertEqual(read.thread_id, "thread-9")
        self.assertNotIn("turns", read.metadata)
        page = self.runtime.thread_list(cursor="old", limit=10)
        self.assertEqual(page.next_cursor, "next-1")
        self.assertEqual(page.threads[0].thread_id, "thread-1")
        methods = [method for method, _ in self.client.calls]
        self.assertEqual(methods, ["thread/resume", "thread/read", "thread/list"])
        self.assertEqual(
            self.client.calls[1][1],
            {"threadId": "thread-9", "includeTurns": False},
        )

    def test_early_delta_is_rehydrated_after_turn_start(self) -> None:
        self.client.emit_before_turn_response = True
        info = self.runtime.turn_start("thread-1", "hello")
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-1",
                "turn": {"id": info.turn_id, "status": "completed", "items": []},
            },
        )
        result = self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=1)
        self.assertEqual(result.final_content, "early ")
        self.assertEqual(result.status, CodexTurnStatus.COMPLETED)

    def test_interleaved_turns_are_correlated_by_both_ids(self) -> None:
        first = self.runtime.turn_start("thread-a", "one")
        second = self.runtime.turn_start("thread-b", "two")
        self.client.emit(
            "item/agentMessage/delta",
            {"threadId": "thread-b", "turnId": second.turn_id, "delta": "B"},
        )
        self.client.emit(
            "item/agentMessage/delta",
            {"threadId": "thread-a", "turnId": first.turn_id, "delta": "A"},
        )
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-b",
                "turn": {
                    "id": second.turn_id,
                    "status": "completed",
                    "items": [],
                },
            },
        )
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-a",
                "turn": {
                    "id": first.turn_id,
                    "status": "completed",
                    "items": [],
                },
            },
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-a", first.turn_id).final_content, "A"
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-b", second.turn_id).final_content, "B"
        )

    def test_same_thread_concurrency_is_explicit(self) -> None:
        self.runtime.turn_start("thread-1", "one")
        with self.assertRaises(CodexConcurrentTurnError):
            self.runtime.turn_start("thread-1", "two")

    def test_wait_turn_blocks_and_notification_thread_can_complete_it(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        waiter, outcome, state = self._start_waiter(info)
        completed = threading.Event()

        def notify() -> None:
            self._emit_completed(info, text="done")
            completed.set()

        notifier = threading.Thread(target=notify, daemon=True)
        notifier.start()
        self.assertTrue(completed.wait(timeout=1))
        notifier.join(timeout=1)
        self.assertFalse(notifier.is_alive())
        waiter.join(timeout=1)
        self.assertFalse(waiter.is_alive())
        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["result"].final_content, "done")
        self.assertTrue(state.done)

    def test_wait_timeout_is_bounded_and_does_not_complete_or_interrupt(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        started = time.monotonic()
        with self.assertRaises(CodexConversationTimeout):
            self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=0.05)
        self.assertLess(time.monotonic() - started, 0.5)
        state = self.runtime._turns[(info.thread_id, info.turn_id)]
        self.assertFalse(state.done)
        self.assertEqual(state.waiters, 0)
        self.assertFalse(any(call[0] == "turn/interrupt" for call in self.client.calls))

    def test_late_terminal_event_allows_a_later_waiter_to_finish(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        with self.assertRaises(CodexConversationTimeout):
            self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=0.01)
        self.assertFalse(self.runtime._turns[(info.thread_id, info.turn_id)].done)
        self._emit_completed(info, text="late")
        result = self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=0.5)
        self.assertEqual(result.final_content, "late")

    def test_two_waiters_are_released_by_one_terminal_event(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        first, first_outcome, state = self._start_waiter(info)
        second, second_outcome, _ = self._start_waiter(info, expected_waiters=2)
        self.assertTrue(self._wait_for(lambda: state.waiters == 2))
        self._emit_completed(info, text="done")
        first.join(timeout=1)
        second.join(timeout=1)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertNotIn("error", first_outcome)
        self.assertNotIn("error", second_outcome)
        self.assertEqual(first_outcome["result"].final_content, "done")
        self.assertEqual(second_outcome["result"].final_content, "done")

    def test_interrupt_is_exact_and_never_kills_process(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        self.runtime.turn_interrupt("thread-1", info.turn_id)
        self.runtime.turn_interrupt("thread-1", info.turn_id)
        calls = [call for call in self.client.calls if call[0] == "turn/interrupt"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0],
            ("turn/interrupt", {"threadId": "thread-1", "turnId": info.turn_id}),
        )

    def test_timeout_does_not_interrupt_or_cross_route(self) -> None:
        first = self.runtime.turn_start("thread-a", "one")
        second = self.runtime.turn_start("thread-b", "two")
        with self.assertRaises(CodexConversationTimeout):
            self.runtime.wait_turn("thread-a", first.turn_id, timeout_seconds=0.01)
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-b",
                "turn": {
                    "id": second.turn_id,
                    "status": "completed",
                    "items": [],
                },
            },
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-b", second.turn_id).status,
            CodexTurnStatus.COMPLETED,
        )
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-a",
                "turn": {
                    "id": first.turn_id,
                    "status": "completed",
                    "items": [],
                },
            },
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-a", first.turn_id).status,
            CodexTurnStatus.COMPLETED,
        )
        self.assertFalse(any(call[0] == "turn/interrupt" for call in self.client.calls))

    def test_failed_interrupted_and_cancelled_statuses_are_mapped(self) -> None:
        failed = self.runtime.turn_start("thread-failed", "one")
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-failed",
                "turn": {
                    "id": failed.turn_id,
                    "status": "failed",
                    "items": [],
                    "error": {
                        "code": 17,
                        "message": "Bearer private-value",
                    },
                },
            },
        )
        failed_result = self.runtime.wait_turn("thread-failed", failed.turn_id)
        self.assertEqual(failed_result.status, CodexTurnStatus.FAILED)
        self.assertEqual(failed_result.error_code, 17)
        self.assertNotIn("private-value", repr(failed_result))

        interrupted = self.runtime.turn_start("thread-interrupted", "two")
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-interrupted",
                "turn": {
                    "id": interrupted.turn_id,
                    "status": "interrupted",
                    "items": [],
                },
            },
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-interrupted", interrupted.turn_id).status,
            CodexTurnStatus.INTERRUPTED,
        )

        cancelled = self.runtime.turn_start("thread-cancelled", "three")
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-cancelled",
                "turn": {
                    "id": cancelled.turn_id,
                    "status": "cancelled",
                    "items": [],
                },
            },
        )
        self.assertEqual(
            self.runtime.wait_turn("thread-cancelled", cancelled.turn_id).status,
            CodexTurnStatus.CANCELLED,
        )

    def test_missing_ids_use_safe_general_or_unique_routing(self) -> None:
        first = self.runtime.turn_start("thread-a", "one")
        self.client.emit(
            "turn/status/changed",
            {"threadId": "thread-a", "status": "inProgress"},
        )
        self.assertEqual(self.runtime.get_event(timeout_seconds=0.01), None)
        self.client.emit(
            "item/agentMessage/delta",
            {"turnId": first.turn_id, "delta": "unique"},
        )
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-a",
                "turn": {"id": first.turn_id, "status": "completed", "items": []},
            },
        )
        result = self.runtime.wait_turn("thread-a", first.turn_id)
        self.assertEqual(result.final_content, "unique")

        self.client.emit("server/unknown", {"secret": "not-public"})
        event = self.runtime.get_event(timeout_seconds=0.1)
        self.assertIsNotNone(event)
        self.assertNotIn("not-public", repr(event))

    def test_reasoning_is_ignored_and_final_text_is_deduplicated(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        private_fragment = "opaque-" + "fragment"
        self.client.emit(
            "item/reasoning/textDelta",
            {"threadId": "thread-1", "turnId": info.turn_id, "delta": private_fragment},
        )
        self.client.emit(
            "item/agentMessage/delta",
            {"threadId": "thread-1", "turnId": info.turn_id, "delta": "public"},
        )
        self.client.emit(
            "turn/completed",
            {
                "threadId": "thread-1",
                "turn": {
                    "id": info.turn_id,
                    "status": "completed",
                    "items": [
                        {
                            "type": "agentMessage",
                            "phase": "final_answer",
                            "text": "public",
                        }
                    ],
                },
            },
        )
        result = self.runtime.wait_turn("thread-1", info.turn_id)
        self.assertEqual(result.final_content, "public")
        self.assertNotIn(private_fragment, repr(result))
        self.assertNotIn(private_fragment, repr(result.public_events))
        self.assertEqual(
            [event.event_type for event in result.public_events],
            ["text_delta", "turn_completed"],
        )

    def test_final_text_reconciliation_never_duplicates_public_stream(self) -> None:
        cases = (
            (("Hel", "lo"), "Hello", None, "Hello"),
            (("Hel",), "Hello world", "lo world", "Hello world"),
            (("rascunho",), "resposta", None, "resposta"),
            ((), "Hello", "Hello", "Hello"),
        )
        for deltas, final_text, expected_delta, expected_final in cases:
            with self.subTest(deltas=deltas, final_text=final_text):
                client = FakeConversationClient()
                runtime = CodexConversationRuntime(client)
                try:
                    info = runtime.turn_start("thread-text", "hello")
                    for delta in deltas:
                        client.emit(
                            "item/agentMessage/delta",
                            {
                                "threadId": info.thread_id,
                                "turnId": info.turn_id,
                                "delta": delta,
                            },
                        )
                    client.emit(
                        "item/completed",
                        {
                            "threadId": info.thread_id,
                            "turnId": info.turn_id,
                            "item": {
                                "type": "agentMessage",
                                "text": final_text,
                            },
                        },
                    )
                    self._emit_completed_for(client, info)
                    result = runtime.wait_turn(
                        info.thread_id, info.turn_id, timeout_seconds=0.5
                    )
                    self.assertEqual(result.final_content, expected_final)
                    self.assertEqual(
                        result.public_events[-2].public_text_delta, expected_delta
                    )
                finally:
                    runtime.close()

        info = self.runtime.turn_start("thread-turn-final", "hello")
        for delta in ("Hel", "lo"):
            self.client.emit(
                "item/agentMessage/delta",
                {
                    "threadId": info.thread_id,
                    "turnId": info.turn_id,
                    "delta": delta,
                },
            )
        self._emit_completed(info, text="Hello")
        result = self.runtime.wait_turn(
            info.thread_id, info.turn_id, timeout_seconds=0.5
        )
        self.assertEqual(result.final_content, "Hello")
        self.assertEqual(
            [event.event_type for event in result.public_events],
            ["text_delta", "text_delta", "turn_completed"],
        )
        self.assertIsNone(result.public_events[-1].public_text_delta)

    @staticmethod
    def _emit_completed_for(client, info) -> None:
        client.emit(
            "turn/completed",
            {
                "threadId": info.thread_id,
                "turn": {
                    "id": info.turn_id,
                    "status": "completed",
                    "items": [],
                },
            },
        )

    def test_close_releases_waiter_without_closing_client(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        thread, outcome, _ = self._start_waiter(info, timeout_seconds=2)
        closed = threading.Event()

        def close() -> None:
            self.runtime.close()
            closed.set()

        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        self.assertTrue(closed.wait(timeout=1))
        closer.join(timeout=1)
        self.assertFalse(closer.is_alive())
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcome["error"], CodexConversationClosed)
        self.assertTrue(self.client.is_ready)

    def test_client_failure_releases_waiter(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        thread, outcome, _ = self._start_waiter(info, timeout_seconds=1)
        self.client.state = CodexAppServerState.FAILED
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcome["error"], CodexConversationClientFailed)

    def test_completed_retention_skips_protected_turns_and_removes_later_ones(
        self,
    ) -> None:
        protected = self.runtime.turn_start("thread-protected", "hello")
        self._emit_completed(protected, text="protected")
        protected_state = self.runtime._turns[
            (protected.thread_id, protected.turn_id)
        ]
        with protected_state.condition:
            protected_state.waiters = 1

        for index in range(128):
            info = self.runtime.turn_start(f"thread-{index}", "hello")
            self._emit_completed(info, text=str(index))

        self.assertIn((protected.thread_id, protected.turn_id), self.runtime._turns)
        self.assertLessEqual(len(self.runtime._completed_order), 128)

        active = self.runtime.turn_start("thread-active", "hello")
        self.assertIn((active.thread_id, active.turn_id), self.runtime._turns)


def test_fake_app_server_covers_stable_thread_and_turn_flow(tmp_path: Path) -> None:
    script = tmp_path / "fake_conversation_app_server.py"
    script.write_text(FAKE_CONVERSATION_SERVER, encoding="utf-8")
    client = CodexAppServerClient(
        CodexAppServerConfig(
            command=(sys.executable, "-u", str(script)),
            startup_timeout_seconds=1,
            request_timeout_seconds=1,
            shutdown_timeout_seconds=0.2,
        )
    )
    client.start()
    runtime = CodexConversationRuntime(client)
    try:
        thread = runtime.thread_start()
        turn = runtime.turn_start(thread.thread_id, "public input")
        result = runtime.wait_turn(thread.thread_id, turn.turn_id, 1)
        assert result.status is CodexTurnStatus.COMPLETED
        assert result.final_content == "fake-public"
    finally:
        runtime.close()
        assert client.is_ready
        client.close()


if __name__ == "__main__":
    unittest.main()
