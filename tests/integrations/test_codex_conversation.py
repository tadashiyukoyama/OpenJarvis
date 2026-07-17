"""Offline contract tests for the sanitized Codex conversation runtime."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

from openjarvis.integrations.codex_conversation import (
    CodexConcurrentTurnError,
    CodexConversationClientFailed,
    CodexConversationClosed,
    CodexConversationRuntime,
    CodexConversationTimeout,
)
from openjarvis.integrations.codex_app_server import CodexAppServerClient
from openjarvis.integrations.codex_protocol import (
    CodexAppServerConfig,
    CodexAppServerState,
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
                "data": [
                    {"id": "thread-1", "status": "idle", "cwd": "D:/project"}
                ],
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

    def tearDown(self) -> None:
        self.runtime.close()

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
        self.assertEqual(
            self.runtime.get_event(timeout_seconds=0.01), None
        )
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
            ["reasoning", "text_delta", "turn_completed"],
        )

    def test_close_releases_waiter_without_closing_client(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        errors: list[BaseException] = []

        def wait() -> None:
            try:
                self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=2)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.05)
        self.runtime.close()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], CodexConversationClosed)
        self.assertTrue(self.client.is_ready)

    def test_client_failure_releases_waiter(self) -> None:
        info = self.runtime.turn_start("thread-1", "hello")
        self.client.state = CodexAppServerState.FAILED
        with self.assertRaises(Exception) as context:
            self.runtime.wait_turn("thread-1", info.turn_id, timeout_seconds=1)
        self.assertIn("client failed", str(context.exception))
        self.assertIsInstance(context.exception, CodexConversationClientFailed)


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
