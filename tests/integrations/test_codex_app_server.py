"""Fake-process tests for the Codex app-server transport boundary."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from openjarvis.integrations.codex_app_server import CodexAppServerClient
from openjarvis.integrations.codex_protocol import (
    CodexAppServerConfig,
    CodexAppServerState,
    CodexHomeStatus,
    CodexInvalidStateError,
    CodexProcessExitedError,
    CodexProtocolError,
    CodexRequestError,
    CodexRequestTimeout,
)

FAKE_SERVER = r"""
import json
import os
import sys
import threading
import time

MODE = os.environ.get("FAKE_MODE", "normal")
LOG = os.environ.get("FAKE_LOG")
WRITE_LOCK = threading.Lock()

def record(value):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

def send(value):
    with WRITE_LOCK:
        sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
        sys.stdout.flush()

def delayed_malformed():
    time.sleep(0.1)
    sys.stdout.write("not-json\n")
    sys.stdout.flush()

def response(request, delay=0):
    if delay:
        time.sleep(delay)
    method = request.get("method")
    if method == "echo":
        send({"jsonrpc": "2.0", "id": request["id"], "result": request.get("params")})
    elif method == "account/read":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "authenticated": True,
            "authMode": "managed",
            "planType": "pro",
            "rateLimits": {"primary": 1},
            "email": "must-not-cross-boundary@example.invalid",
            "token": "must-not-cross-boundary",
        }})
    elif method == "model/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "data": [{
                "id": "public-model",
                "displayName": "Public Model",
                "secret": "drop",
            }]
        }})
    elif method == "rpc-error":
        send({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": 400, "message": "Bearer secret-value"},
        })
    elif method == "late":
        response(request, 0.25)
    elif method == "slow":
        response(request, 2)
    else:
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"method": method}})

for raw in sys.stdin:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        continue
    record(request)
    method = request.get("method")
    if method == "initialize":
        if MODE == "reject":
            send({
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": -32000, "message": "rejected"},
            })
        elif MODE == "malformed":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
        else:
            send({"jsonrpc": "2.0", "id": request["id"], "result": {
                "codexHome": "D:/private/codex-home",
                "platformFamily": "windows",
                "platformOs": "windows",
                "userAgent": "private-agent-value",
                "capabilities": {"public": True},
            }})
            if MODE == "exit-after-handshake":
                sys.exit(7)
    elif method == "initialized":
        if MODE == "notification":
            for index in range(3):
                send({"jsonrpc": "2.0", "method": "event", "params": {"index": index}})
        elif MODE == "malformed-after-ready":
            threading.Thread(target=delayed_malformed, daemon=True).start()
        elif MODE == "overflow":
            for index in range(105):
                send({"jsonrpc": "2.0", "method": "event", "params": {"index": index}})
        elif MODE == "server-request":
            send({
                "jsonrpc": "2.0",
                "id": 700,
                "method": "approval/request",
                "params": {"secret": "private"},
            })
        elif MODE == "server-request-double":
            send({
                "jsonrpc": "2.0",
                "id": 700,
                "method": "approval/request",
                "params": {},
            })
            send({
                "jsonrpc": "2.0",
                "id": 701,
                "method": "approval/request",
                "params": {},
            })
        elif MODE == "server-request-no-handler":
            send({
                "jsonrpc": "2.0",
                "id": 701,
                "method": "approval/request",
                "params": {},
            })
        elif MODE == "stderr":
            sys.stderr.write("Bearer abc token=secret cookie=private\n")
            sys.stderr.flush()
        elif MODE == "ignore-close":
            pass
    elif method == "server-response":
        record({"server_response": request})
    elif "id" in request and "method" not in request:
        record({"server_response": request})
    elif "id" in request:
        if MODE == "out-of-order":
            delay = 0.15 if request.get("params", {}).get("order") == "first" else 0.01
            threading.Thread(
                target=response, args=(request, delay), daemon=True
            ).start()
        else:
            threading.Thread(target=response, args=(request,), daemon=True).start()

if MODE == "ignore-close":
    while True:
        time.sleep(1)
"""


def _write_fake_server(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "fake_app_server.py"
    log = tmp_path / "fake_app_server.log"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return script, log


def _client(
    tmp_path: Path, mode: str = "normal", **kwargs: Any
) -> CodexAppServerClient:
    script, log = _write_fake_server(tmp_path)
    environment = {"FAKE_MODE": mode, "FAKE_LOG": str(log)}
    environment.update(kwargs.pop("environment_overrides", {}))
    config = CodexAppServerConfig(
        command=(sys.executable, "-u", str(script)),
        environment_overrides=environment,
        startup_timeout_seconds=1,
        request_timeout_seconds=kwargs.pop("request_timeout_seconds", 1),
        shutdown_timeout_seconds=kwargs.pop("shutdown_timeout_seconds", 0.2),
        **kwargs,
    )
    return CodexAppServerClient(config)


def _wait_for_log(
    log: Path, predicate: Any, timeout: float = 2
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists():
            rows = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
            ]
            if predicate(rows):
                return rows
        time.sleep(0.01)
    rows = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    return rows


def test_constructor_and_import_do_not_start_a_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def fail_if_started(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("process started unexpectedly")

    monkeypatch.setattr(subprocess, "Popen", fail_if_started)
    client = CodexAppServerClient()
    assert client.state is CodexAppServerState.NEW
    assert client.pid is None
    assert not calls


def test_default_command_is_typed_and_shell_safe() -> None:
    config = CodexAppServerConfig()
    assert config.command == ("codex", "app-server", "--listen", "stdio://")
    assert config.cwd is None


def test_handshake_order_and_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    client = _client(tmp_path)
    client.start()
    try:
        assert client.is_ready
        assert client.handshake_info is not None
        assert client.handshake_info.codex_home_status is CodexHomeStatus.UNVERIFIED
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(log, lambda values: len(values) >= 2)
        assert [row["method"] for row in rows[:2]] == ["initialize", "initialized"]
        assert rows[0]["params"]["clientInfo"] == {
            "name": "openjarvis",
            "title": "OpenJarvis",
            "version": "0.1.0",
        }
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["reject", "malformed"])
def test_handshake_failure_has_no_orphan(tmp_path: Path, mode: str) -> None:
    client = _client(tmp_path, mode)
    with pytest.raises((CodexProtocolError, CodexRequestError)):
        client.start()
    assert client.state is CodexAppServerState.FAILED
    assert client.pid is None
    client.close()


def test_request_response_and_monotonic_ids(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        assert client.request("echo", {"value": 1}) == {"value": 1}
        assert client.request("echo", {"value": 2}) == {"value": 2}
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(log, lambda values: len(values) >= 4)
        ids = [row["id"] for row in rows if row.get("method") == "echo"]
        assert ids == sorted(ids)
        assert len(set(ids)) == 2
    finally:
        client.close()


def test_out_of_order_responses_are_correlated(tmp_path: Path) -> None:
    client = _client(tmp_path, "out-of-order")
    client.start()
    results: dict[str, object] = {}

    def call(name: str, order: str) -> None:
        results[name] = client.request("echo", {"order": order})

    try:
        first = threading.Thread(target=call, args=("first", "first"))
        second = threading.Thread(target=call, args=("second", "second"))
        first.start()
        second.start()
        first.join()
        second.join()
        assert results == {"first": {"order": "first"}, "second": {"order": "second"}}
    finally:
        client.close()


def test_timeout_removes_pending_and_late_response_is_ignored(tmp_path: Path) -> None:
    client = _client(tmp_path, request_timeout_seconds=0.05)
    client.start()
    try:
        with pytest.raises(CodexRequestTimeout):
            client.request("late")
        time.sleep(0.35)
        assert client.request("echo", {"after": True}) == {"after": True}
    finally:
        client.close()


def test_account_read_is_explicit_and_sanitized(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        account = client.account_read()
        assert account.authenticated is True
        assert account.auth_mode == "managed"
        assert account.plan_type_present
        assert account.rate_limits_present
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log,
            lambda values: any(v.get("method") == "account/read" for v in values),
        )
        request = next(v for v in rows if v.get("method") == "account/read")
        assert request["params"] == {"refreshToken": False}
    finally:
        client.close()


def test_account_read_and_model_list_are_not_automatic(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        time.sleep(0.05)
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = (
            json.loads("[]")
            if not log.exists()
            else [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
            ]
        )
        assert [row.get("method") for row in rows] == ["initialize", "initialized"]
    finally:
        client.close()


def test_model_list_returns_public_metadata_only(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        models = client.model_list()
        assert models[0].model_id == "public-model"
        assert models[0].metadata == {"displayName": "Public Model"}
    finally:
        client.close()


def test_notifications_preserve_order_and_callback_is_outside_reader(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "notification")
    received: list[int] = []
    callback_event = threading.Event()
    client.set_notification_callback(
        lambda notification: (
            received.append(notification.params["index"]),
            callback_event.set(),
        )
    )
    client.start()
    try:
        values = [client.get_notification(timeout_seconds=1) for _ in range(3)]
        assert [value.params["index"] for value in values if value is not None] == [
            0,
            1,
            2,
        ]
        assert callback_event.wait(1)
        assert received[0] == 0
    finally:
        client.close()


def test_notification_overflow_policy_is_bounded_and_explicit(tmp_path: Path) -> None:
    client = _client(tmp_path, "overflow")
    client.start()
    try:
        time.sleep(0.1)
        values: list[int] = []
        while True:
            value = client.get_notification(timeout_seconds=0.01)
            if value is None:
                break
            values.append(value.params["index"])
        assert len(values) <= 100
        assert client.notification_overflow_policy == "drop_oldest"
        assert values[-1] == 104
    finally:
        client.close()


def test_server_request_handler_uses_same_id(tmp_path: Path) -> None:
    client = _client(tmp_path, "server-request")
    client.set_server_request_handler(lambda request: {"approved": False})
    client.start()
    try:
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log, lambda values: any("server_response" in v for v in values)
        )
        response = next(v["server_response"] for v in rows if "server_response" in v)
        assert response["id"] == 700
        assert response["result"] == {"approved": False}
    finally:
        client.close()


def test_server_request_without_handler_fails_closed(tmp_path: Path) -> None:
    client = _client(tmp_path, "server-request-no-handler")
    client.start()
    try:
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log, lambda values: any("server_response" in v for v in values)
        )
        response = next(v["server_response"] for v in rows if "server_response" in v)
        assert response["id"] == 701
        assert response["error"]["code"] == -32601
        assert "allow" not in json.dumps(response).lower()
    finally:
        client.close()


def test_rpc_error_does_not_leak_bearer_value(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        with pytest.raises(CodexRequestError, match="REDACTED"):
            client.request("rpc-error")
    finally:
        client.close()


def test_stderr_is_bounded_and_sanitized(tmp_path: Path) -> None:
    client = _client(tmp_path, "stderr", stderr_max_lines=1)
    client.start()
    try:
        time.sleep(0.05)
        assert len(client.stderr_tail) <= 1
        assert "[REDACTED]" in client.stderr_tail[0]
        assert "secret" not in client.stderr_tail[0]
        assert "private" not in client.stderr_tail[0]
    finally:
        client.close()


def test_close_is_idempotent_and_clears_owned_pid(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    pid = client.pid
    assert pid is not None
    client.close()
    client.close()
    assert client.state is CodexAppServerState.CLOSED
    assert client.pid is None


def test_close_terminates_only_owned_process_when_server_ignores_stdin(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "ignore-close", shutdown_timeout_seconds=0.05)
    client.start()
    assert client.pid is not None
    client.close()
    assert client.state is CodexAppServerState.CLOSED
    assert client.pid is None


def test_pending_request_fails_when_process_exits(tmp_path: Path) -> None:
    client = _client(tmp_path, request_timeout_seconds=2)
    client.start()
    error: list[BaseException] = []

    def call() -> None:
        try:
            client.request("slow")
        except BaseException as exc:
            error.append(exc)

    worker = threading.Thread(target=call)
    worker.start()
    time.sleep(0.05)
    client.close()
    worker.join(1)
    assert error
    assert isinstance(error[0], CodexProcessExitedError)


def test_generation_contexts_have_private_events_queues_and_pending(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    client.start()
    first = client._active_lifecycle
    assert first is not None
    first_generation = client.generation_id
    client.close()

    client.start()
    second = client._active_lifecycle
    try:
        assert second is not None
        assert client.generation_id == first_generation + 1
        assert first is not second
        assert first.stop_event is not second.stop_event
        assert first.notifications is not second.notifications
        assert first.callback_notifications is not second.callback_notifications
        assert first.server_requests is not second.server_requests
        assert first.pending is not second.pending
    finally:
        client.close()


def test_old_waiter_cannot_fail_a_new_generation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    client.close()
    client.start()
    try:
        time.sleep(0.2)
        assert client.state is CodexAppServerState.READY
        assert client.request("echo", {"generation": 2}) == {"generation": 2}
    finally:
        client.close()


def test_old_notification_queue_and_callback_cannot_consume_new_generation(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "notification", shutdown_timeout_seconds=0.05)
    entered = threading.Event()
    release = threading.Event()
    new_generation_values: list[int] = []

    def callback(notification: Any) -> None:
        if not entered.is_set():
            entered.set()
            release.wait(1)
        else:
            new_generation_values.append(notification.params["index"])

    client.set_notification_callback(callback)
    client.start()
    assert entered.wait(1)
    first = client._active_lifecycle
    assert first is not None
    client.close()

    client.start()
    try:
        second = client._active_lifecycle
        assert second is not None and second is not first
        value = client.get_notification(timeout_seconds=1)
        assert value is not None and value.params["index"] == 0
        release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not new_generation_values:
            time.sleep(0.01)
        assert new_generation_values
    finally:
        release.set()
        client.close()


def test_old_handler_cannot_answer_new_generation(tmp_path: Path) -> None:
    client = _client(tmp_path, "server-request", shutdown_timeout_seconds=0.05)
    entered = threading.Event()
    release = threading.Event()

    def handler(request: Any) -> object:
        if not entered.is_set():
            entered.set()
            release.wait(1)
            return {"generation": "old"}
        return {"generation": "new"}

    client.set_server_request_handler(handler)
    client.start()
    assert entered.wait(1)
    client.close()
    client.start()
    try:
        release.set()
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log,
            lambda values: any(
                v.get("server_response", {}).get("result") == {"generation": "new"}
                for v in values
            ),
        )
        assert any(
            v.get("server_response", {}).get("result") == {"generation": "new"}
            for v in rows
        )
        assert client.state is CodexAppServerState.READY
    finally:
        release.set()
        client.close()


def test_malformed_protocol_after_ready_fails_closed_without_retry(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "malformed-after-ready")
    client.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if client.state is CodexAppServerState.FAILED:
                break
            time.sleep(0.01)
        assert client.state is CodexAppServerState.FAILED
        assert client.pid is None
        assert client.last_error == "invalid JSON-RPC JSON"
        with pytest.raises(CodexInvalidStateError):
            client.request("echo")
    finally:
        client.close()
    assert client.state is CodexAppServerState.CLOSED


def test_nonserializable_request_does_not_orphan_pending_or_kill_process(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    client.start()
    try:
        with pytest.raises(CodexProtocolError, match="not JSON serializable"):
            client.request("echo", {"bad": object()})
        assert client.state is CodexAppServerState.READY
        lifecycle = client._active_lifecycle
        assert lifecycle is not None and not lifecycle.pending
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = [
            json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
        ]
        assert not any(row.get("params", {}).get("bad") for row in rows)
        assert client.request("echo", {"after": True}) == {"after": True}
    finally:
        client.close()


def test_nonserializable_handler_result_is_jsonrpc_error_and_dispatch_continues(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "server-request-double")
    client.set_server_request_handler(
        lambda request: object() if request.request_id == 700 else {"approved": False}
    )
    client.start()
    try:
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log,
            lambda values: (
                len([value for value in values if "server_response" in value]) >= 2
            ),
        )
        responses = {
            value["server_response"]["id"]: value["server_response"]
            for value in rows
            if "server_response" in value
        }
        assert responses[700]["error"] == {
            "code": -32603,
            "message": "server request handler returned an invalid result",
        }
        assert responses[701]["result"] == {"approved": False}
        assert client.state is CodexAppServerState.READY
    finally:
        client.close()


def test_handler_exception_is_safe_and_does_not_fail_reader(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "server-request")

    def handler(request: Any) -> object:
        raise RuntimeError("private handler details")

    client.set_server_request_handler(handler)
    client.start()
    try:
        log = next(path for path in tmp_path.iterdir() if path.name.endswith(".log"))
        rows = _wait_for_log(
            log, lambda values: any("server_response" in value for value in values)
        )
        response = next(
            value["server_response"] for value in rows if "server_response" in value
        )
        assert response["error"] == {
            "code": -32000,
            "message": "server request handler failed",
        }
        assert "private handler details" not in json.dumps(response)
        assert client.state is CodexAppServerState.READY
    finally:
        client.close()


def test_concurrent_close_waits_for_one_generation_and_is_idempotent(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, "ignore-close", shutdown_timeout_seconds=0.05)
    client.start()
    barrier = threading.Barrier(2)

    def close_client() -> None:
        barrier.wait()
        client.close()

    callers = [threading.Thread(target=close_client) for _ in range(2)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(2)
    assert all(not caller.is_alive() for caller in callers)
    assert client.state is CodexAppServerState.CLOSED
    assert client.pid is None
    client.close()


def test_operations_after_close_are_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.start()
    client.close()
    with pytest.raises(CodexInvalidStateError):
        client.request("echo")


def test_config_environment_override_is_not_printed_or_persisted(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, environment_overrides={"SAFE_TEST_VALUE": "present"})
    client.start()
    try:
        assert client.request("echo", {"ok": True}) == {"ok": True}
        assert all("SAFE_TEST_VALUE" not in line for line in client.stderr_tail)
    finally:
        client.close()


def test_effective_codex_home_precedence_and_sanitization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", r"D:\Parent\Codex")
    parent_client = CodexAppServerClient(CodexAppServerConfig())
    parent_info = parent_client._sanitize_handshake({"codexHome": "d:/parent/codex"})
    assert parent_info.codex_home_status is CodexHomeStatus.EXPECTED

    override_client = CodexAppServerClient(
        CodexAppServerConfig(environment_overrides={"CODEX_HOME": "D:/Override/Codex"})
    )
    override_info = override_client._sanitize_handshake(
        {"codexHome": r"d:\override\CODEX"}
    )
    assert override_info.codex_home_status is CodexHomeStatus.EXPECTED
    assert "Override" not in repr(override_info)

    monkeypatch.delenv("CODEX_HOME")
    override_only = CodexAppServerClient(
        CodexAppServerConfig(environment_overrides={"CODEX_HOME": "D:/Override/Only"})
    )
    override_only_info = override_only._sanitize_handshake(
        {"codexHome": "D:/Override/Only"}
    )
    assert override_only_info.codex_home_status is CodexHomeStatus.EXPECTED

    divergent = CodexAppServerClient(
        CodexAppServerConfig(environment_overrides={"CODEX_HOME": "D:/expected"})
    )
    divergent_info = divergent._sanitize_handshake({"codexHome": "D:/different/codex"})
    assert divergent_info.codex_home_status is CodexHomeStatus.UNEXPECTED

    absent = divergent._sanitize_handshake({})
    assert absent.codex_home_status is CodexHomeStatus.ABSENT
