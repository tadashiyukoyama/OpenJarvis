"""A process-safe JSONL client for the official Codex app-server binary.

This module deliberately stops at transport and read-only catalog/account
operations.  It does not create Codex threads or turns and is not registered
with the OpenJarvis runtime in this phase.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, IO, Mapping, cast

from .codex_protocol import (
    CodexAccountInfo,
    CodexAppServerConfig,
    CodexAppServerError,
    CodexAppServerState,
    CodexHandshakeInfo,
    CodexHomeStatus,
    CodexInvalidStateError,
    CodexModelInfo,
    CodexProcessExitedError,
    CodexProcessStartError,
    CodexProtocolError,
    CodexRequestError,
    CodexRequestTimeout,
    JsonRpcId,
    JsonRpcNotification,
    JsonRpcResponse,
    JsonRpcServerRequest,
    encode_jsonrpc,
    parse_jsonrpc_envelope,
)


NotificationCallback = Callable[[JsonRpcNotification], None]
ServerRequestHandler = Callable[[JsonRpcServerRequest], object]

_REDACTION_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(
        r"(?i)((?:authorization|cookie|set-cookie|api[_-]?key|token|secret)\s*[:=]\s*)[^\s,;]+"
    ),
)
_SAFE_MODEL_METADATA = frozenset(
    {
        "displayName",
        "description",
        "contextWindow",
        "capabilities",
        "vendor",
        "version",
    }
)


def _sanitize_text(value: str) -> str:
    sanitized = value
    for pattern in _REDACTION_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    return sanitized


@dataclass
class _PendingRequest:
    event: threading.Event
    response: JsonRpcResponse | None = None
    failure: CodexAppServerError | None = None


class CodexAppServerClient:
    """Thread-safe lifecycle and JSON-RPC client for one owned process."""

    _NOTIFICATION_QUEUE_SIZE = 100
    _SERVER_REQUEST_QUEUE_SIZE = 100

    def __init__(self, config: CodexAppServerConfig | None = None) -> None:
        self._config = config or CodexAppServerConfig()
        self._state = CodexAppServerState.NEW
        self._state_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._handler_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._next_request_id = 1
        self._pending: dict[JsonRpcId, _PendingRequest] = {}
        self._process: subprocess.Popen[str] | None = None
        self._pid: int | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._wait_thread: threading.Thread | None = None
        self._notification_thread: threading.Thread | None = None
        self._server_request_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stderr_lines: deque[str] = deque(maxlen=self._config.stderr_max_lines)
        self._notifications: queue.Queue[JsonRpcNotification] = queue.Queue(
            maxsize=self._NOTIFICATION_QUEUE_SIZE
        )
        self._callback_notifications: queue.Queue[JsonRpcNotification] = queue.Queue(
            maxsize=self._NOTIFICATION_QUEUE_SIZE
        )
        self._server_requests: queue.Queue[JsonRpcServerRequest] = queue.Queue(
            maxsize=self._SERVER_REQUEST_QUEUE_SIZE
        )
        self._notification_callback: NotificationCallback | None = None
        self._server_request_handler: ServerRequestHandler | None = None
        self._last_error: str | None = None
        self._handshake_info: CodexHandshakeInfo | None = None
        self._initialize_sent = False

    @property
    def state(self) -> CodexAppServerState:
        with self._state_lock:
            return self._state

    @property
    def pid(self) -> int | None:
        with self._state_lock:
            return self._pid

    @property
    def is_ready(self) -> bool:
        return self.state is CodexAppServerState.READY

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            return self._last_error

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        with self._state_lock:
            return tuple(self._stderr_lines)

    @property
    def handshake_info(self) -> CodexHandshakeInfo | None:
        with self._state_lock:
            return self._handshake_info

    @property
    def notification_overflow_policy(self) -> str:
        """The bounded notification queue drops its oldest item on overflow."""

        return "drop_oldest"

    def start(self) -> None:
        """Start the owned process and complete exactly one initialize handshake."""

        with self._state_lock:
            if self._state not in (
                CodexAppServerState.NEW,
                CodexAppServerState.CLOSED,
            ):
                raise CodexInvalidStateError(
                    f"cannot start from state {self._state.value}"
                )
            self._state = CodexAppServerState.STARTING
            self._last_error = None
            self._handshake_info = None
            self._stderr_lines.clear()
            self._stop_event.clear()
            self._initialize_sent = False
            self._drain_queue(self._notifications)
            self._drain_queue(self._callback_notifications)
            self._drain_queue(self._server_requests)

        environment = os.environ.copy()
        environment.update(self._config.environment_overrides)
        try:
            process = subprocess.Popen(
                list(self._config.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._config.cwd,
                env=environment,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            error = CodexProcessStartError("unable to start Codex app-server")
            self._set_failure(error)
            raise error from exc

        with self._state_lock:
            self._process = process
            self._pid = process.pid

        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(process.stdout,),
            name="openjarvis-codex-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(process.stderr,),
            name="openjarvis-codex-stderr",
            daemon=True,
        )
        self._wait_thread = threading.Thread(
            target=self._wait_for_process,
            args=(process,),
            name="openjarvis-codex-wait",
            daemon=True,
        )
        self._notification_thread = threading.Thread(
            target=self._dispatch_notification_callbacks,
            name="openjarvis-codex-notifications",
            daemon=True,
        )
        self._server_request_thread = threading.Thread(
            target=self._dispatch_server_requests,
            name="openjarvis-codex-server-requests",
            daemon=True,
        )
        for thread in (
            self._stdout_thread,
            self._stderr_thread,
            self._wait_thread,
            self._notification_thread,
            self._server_request_thread,
        ):
            thread.start()

        try:
            with self._state_lock:
                if self._initialize_sent:
                    raise CodexProtocolError("initialize already sent")
                self._initialize_sent = True
            result = self._send_request(
                "initialize",
                {
                    "clientInfo": {
                        "name": self._config.client_name,
                        "title": self._config.client_title,
                        "version": self._config.client_version,
                    }
                },
                timeout_seconds=self._config.startup_timeout_seconds,
                allow_starting=True,
            )
            handshake_info = self._sanitize_handshake(result)
            with self._state_lock:
                self._handshake_info = handshake_info
            self._send_notification("initialized", {})
            with self._state_lock:
                if self._state is not CodexAppServerState.STARTING:
                    raise CodexProcessExitedError("Codex app-server exited during startup")
                self._state = CodexAppServerState.READY
        except CodexAppServerError as exc:
            self._set_failure(exc)
            self._terminate_owned_process(process)
            raise
        except BaseException as exc:
            error = CodexProtocolError("Codex app-server handshake failed")
            self._set_failure(error)
            self._terminate_owned_process(process)
            raise error from exc

    def close(self) -> None:
        """Close only the process created by this client instance."""

        with self._state_lock:
            if self._state is CodexAppServerState.CLOSED:
                return
            if self._state is CodexAppServerState.CLOSING:
                return
            self._state = CodexAppServerState.CLOSING
            process = self._process
            self._stop_event.set()

        self._fail_pending(CodexProcessExitedError("Codex app-server is closing"))
        close_error: BaseException | None = None
        if process is not None:
            try:
                with self._write_lock:
                    if process.stdin is not None:
                        process.stdin.close()
            except OSError as exc:
                close_error = exc
            try:
                process.wait(timeout=self._config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=self._config.shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=self._config.shutdown_timeout_seconds)
                    except BaseException as exc:
                        close_error = exc
                except BaseException as exc:
                    close_error = exc
            except BaseException as exc:
                close_error = exc

        self._join_reader_threads()
        with self._state_lock:
            self._process = None
            self._pid = None
            self._stdout_thread = None
            self._stderr_thread = None
            self._wait_thread = None
            self._notification_thread = None
            self._server_request_thread = None
            if close_error is None:
                self._state = CodexAppServerState.CLOSED
            else:
                self._state = CodexAppServerState.FAILED
                self._last_error = _sanitize_text(str(close_error))

    def request(
        self,
        method: str,
        params: object | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        """Send one request after the handshake and return its result."""

        self._require_ready()
        return self._send_request(
            method,
            params,
            timeout_seconds=(
                self._config.request_timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
            allow_starting=False,
        )

    def notify(self, method: str, params: object | None = None) -> None:
        """Send a notification after the handshake."""

        self._require_ready()
        self._send_notification(method, params)

    def account_read(self) -> CodexAccountInfo:
        """Read only sanitized account status without refreshing credentials."""

        result = self.request("account/read", {"refreshToken": False})
        if not isinstance(result, dict):
            raise CodexProtocolError("account/read result must be an object")
        authenticated = result.get("authenticated")
        if not isinstance(authenticated, bool):
            authenticated = None
        auth_mode = result.get("authMode", result.get("auth_mode"))
        if not isinstance(auth_mode, str):
            auth_mode = None
        account = result.get("account")
        if isinstance(account, dict):
            if auth_mode is None and isinstance(account.get("type"), str):
                auth_mode = cast(str, account["type"])
            plan_present = "planType" in account
        else:
            plan_present = False
        return CodexAccountInfo(
            authenticated=authenticated,
            auth_mode=auth_mode,
            plan_type_present=plan_present or "planType" in result,
            rate_limits_present=(
                "rateLimits" in result
                or "rate_limits" in result
                or (isinstance(account, dict) and "rateLimits" in account)
            ),
        )

    def model_list(self) -> tuple[CodexModelInfo, ...]:
        """Read the public model catalog without selection or downloading."""

        result = self.request("model/list", {})
        if not isinstance(result, dict):
            raise CodexProtocolError("model/list result must be an object")
        raw_models = result.get("data", result.get("models", []))
        if not isinstance(raw_models, list):
            raise CodexProtocolError("model/list data must be an array")
        models: list[CodexModelInfo] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            model_id = raw_model.get("id", raw_model.get("model"))
            if not isinstance(model_id, str) or not model_id:
                continue
            metadata = {
                key: value
                for key, value in raw_model.items()
                if key in _SAFE_MODEL_METADATA
            }
            models.append(CodexModelInfo(model_id=model_id, metadata=metadata))
        return tuple(models)

    def get_notification(self, timeout_seconds: float | None = None) -> JsonRpcNotification | None:
        """Consume the next retained notification without blocking forever."""

        try:
            return self._notifications.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        """Register or clear a callback serviced outside the stdout reader."""

        with self._handler_lock:
            self._notification_callback = callback

    def set_server_request_handler(self, handler: ServerRequestHandler | None) -> None:
        """Register or clear the fail-closed server-request handler."""

        with self._handler_lock:
            self._server_request_handler = handler

    register_server_request_handler = set_server_request_handler

    def _require_ready(self) -> None:
        with self._state_lock:
            if self._state is not CodexAppServerState.READY:
                raise CodexInvalidStateError(
                    f"operation requires READY, current state is {self._state.value}"
                )

    def _next_id(self) -> int:
        with self._id_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            return request_id

    def _send_request(
        self,
        method: str,
        params: object | None,
        *,
        timeout_seconds: float,
        allow_starting: bool,
    ) -> object:
        with self._state_lock:
            allowed = self._state is CodexAppServerState.READY or (
                allow_starting and self._state is CodexAppServerState.STARTING
            )
            if not allowed:
                raise CodexInvalidStateError(
                    f"cannot request in state {self._state.value}"
                )
        request_id = self._next_id()
        pending = _PendingRequest(event=threading.Event())
        with self._pending_lock:
            self._pending[request_id] = pending
        message: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        try:
            self._write(message)
        except BaseException as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            error = CodexProcessExitedError("unable to write to Codex app-server")
            self._set_failure(error)
            raise error from exc
        if not pending.event.wait(timeout_seconds):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise CodexRequestTimeout(f"request {request_id} timed out")
        with self._pending_lock:
            self._pending.pop(request_id, None)
        if pending.failure is not None:
            raise pending.failure
        if pending.response is None:
            raise CodexProtocolError("request completed without a response")
        if pending.response.error is not None:
            rpc_error = pending.response.error
            raise CodexRequestError(
                _sanitize_text(rpc_error.message),
                code=rpc_error.code,
            )
        return pending.response.result

    def _send_notification(self, method: str, params: object | None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _write(self, message: Mapping[str, object]) -> None:
        with self._write_lock:
            with self._state_lock:
                process = self._process
            if process is None or process.stdin is None:
                raise CodexProcessExitedError("Codex app-server stdin is unavailable")
            process.stdin.write(encode_jsonrpc(message))
            process.stdin.flush()

    def _read_stdout(self, stream: IO[str] | None) -> None:
        if stream is None:
            self._set_failure(CodexProtocolError("Codex app-server stdout is unavailable"))
            return
        try:
            for line in stream:
                if self._stop_event.is_set():
                    break
                try:
                    payload = json.loads(line)
                    envelope = parse_jsonrpc_envelope(payload)
                except (json.JSONDecodeError, CodexProtocolError) as exc:
                    error = (
                        exc
                        if isinstance(exc, CodexProtocolError)
                        else CodexProtocolError("invalid JSON-RPC JSON")
                    )
                    self._set_failure(error)
                    break
                if isinstance(envelope, JsonRpcResponse):
                    self._complete_response(envelope)
                elif isinstance(envelope, JsonRpcNotification):
                    self._queue_notification(envelope)
                else:
                    self._queue_server_request(envelope)
        except (OSError, ValueError):
            if not self._stop_event.is_set():
                self._set_failure(CodexProcessExitedError("Codex app-server stdout closed"))
        finally:
            if not self._stop_event.is_set():
                self._set_failure(CodexProcessExitedError("Codex app-server stdout reached EOF"))

    def _read_stderr(self, stream: IO[str] | None) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                clean_line = _sanitize_text(line.rstrip("\r\n"))
                with self._state_lock:
                    self._stderr_lines.append(clean_line)
        except (OSError, ValueError):
            return

    def _wait_for_process(self, process: subprocess.Popen[str]) -> None:
        try:
            return_code = process.wait()
        except (OSError, ValueError):
            return_code = None
        if self._stop_event.is_set():
            return
        if return_code not in (0, None):
            self._set_failure(
                CodexProcessExitedError(
                    f"Codex app-server exited with code {return_code}"
                )
            )
        else:
            self._set_failure(CodexProcessExitedError("Codex app-server exited"))

    def _complete_response(self, response: JsonRpcResponse) -> None:
        with self._pending_lock:
            pending = self._pending.get(response.request_id)
            if pending is None:
                return
            pending.response = response
            pending.event.set()

    def _queue_notification(self, notification: JsonRpcNotification) -> None:
        self._bounded_put(self._notifications, notification)
        self._bounded_put(self._callback_notifications, notification)

    def _queue_server_request(self, request: JsonRpcServerRequest) -> None:
        try:
            self._server_requests.put_nowait(request)
        except queue.Full:
            self._send_error_response(request.request_id, -32001, "server request queue full")

    @staticmethod
    def _bounded_put(
        target: queue.Queue[JsonRpcNotification],
        item: JsonRpcNotification,
    ) -> None:
        try:
            target.put_nowait(item)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            try:
                target.put_nowait(item)
            except queue.Full:
                pass

    @staticmethod
    def _drain_queue(target: queue.Queue[object]) -> None:
        while True:
            try:
                target.get_nowait()
            except queue.Empty:
                return

    def _dispatch_notification_callbacks(self) -> None:
        while not self._stop_event.is_set():
            try:
                notification = self._callback_notifications.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._handler_lock:
                callback = self._notification_callback
            if callback is None:
                continue
            try:
                callback(notification)
            except BaseException:
                continue

    def _dispatch_server_requests(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._server_requests.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._handler_lock:
                handler = self._server_request_handler
            if handler is None:
                self._send_error_response(
                    request.request_id,
                    -32601,
                    "no server request handler registered",
                )
                continue
            try:
                result = handler(request)
            except BaseException:
                self._send_error_response(
                    request.request_id,
                    -32000,
                    "server request handler failed",
                )
            else:
                try:
                    self._write(
                        {
                            "jsonrpc": "2.0",
                            "id": request.request_id,
                            "result": result,
                        }
                    )
                except CodexAppServerError as exc:
                    self._set_failure(exc)

    def _send_error_response(self, request_id: JsonRpcId, code: int, message: str) -> None:
        try:
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": code, "message": message},
                }
            )
        except CodexAppServerError as exc:
            self._set_failure(exc)

    def _sanitize_handshake(self, result: object) -> CodexHandshakeInfo:
        if not isinstance(result, dict):
            raise CodexProtocolError("initialize result must be an object")
        codex_home = result.get("codexHome")
        if codex_home is None:
            home_status = CodexHomeStatus.ABSENT
        elif not isinstance(codex_home, str) or not codex_home:
            home_status = CodexHomeStatus.UNVERIFIED
        else:
            expected_home = os.environ.get("CODEX_HOME")
            if expected_home is None:
                home_status = CodexHomeStatus.UNVERIFIED
            elif os.path.normcase(codex_home) == os.path.normcase(expected_home):
                home_status = CodexHomeStatus.EXPECTED
            else:
                home_status = CodexHomeStatus.UNEXPECTED
        platform_family = result.get("platformFamily")
        platform_os = result.get("platformOs")
        capabilities_value = result.get("capabilities")
        capabilities: tuple[str, ...] = ()
        if isinstance(capabilities_value, dict):
            capabilities = tuple(sorted(str(key) for key in capabilities_value))
        return CodexHandshakeInfo(
            codex_home_status=home_status,
            platform_family=platform_family if isinstance(platform_family, str) else None,
            platform_os=platform_os if isinstance(platform_os, str) else None,
            user_agent_present=isinstance(result.get("userAgent"), str),
            capabilities=capabilities,
        )

    def _set_failure(self, error: CodexAppServerError) -> None:
        with self._state_lock:
            if self._state not in (
                CodexAppServerState.CLOSING,
                CodexAppServerState.CLOSED,
            ):
                self._state = CodexAppServerState.FAILED
                self._last_error = _sanitize_text(str(error))
        self._fail_pending(error)

    def _fail_pending(self, error: CodexAppServerError) -> None:
        with self._pending_lock:
            for pending in self._pending.values():
                pending.failure = error
                pending.event.set()

    def _terminate_owned_process(self, process: subprocess.Popen[str]) -> None:
        self._stop_event.set()
        try:
            with self._write_lock:
                if process.stdin is not None:
                    process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=self._config.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=self._config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=self._config.shutdown_timeout_seconds)
                except BaseException:
                    pass
            except BaseException:
                pass
        except BaseException:
            pass
        self._join_reader_threads()
        with self._state_lock:
            self._process = None
            self._pid = None

    def _join_reader_threads(self) -> None:
        current = threading.current_thread()
        for thread in (
            self._stdout_thread,
            self._stderr_thread,
            self._wait_thread,
            self._notification_thread,
            self._server_request_thread,
        ):
            if thread is not None and thread is not current:
                thread.join(timeout=self._config.shutdown_timeout_seconds)


__all__ = [
    "CodexAppServerClient",
    "NotificationCallback",
    "ServerRequestHandler",
]
