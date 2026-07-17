"""A process-safe JSONL client for the official Codex app-server binary.

This module deliberately stops at transport and read-only catalog/account
operations. It does not create Codex threads or turns and is not registered
with the OpenJarvis runtime in this phase.

Every started process owns a complete lifecycle context. Reader, waiter,
callback, and server-request workers receive that context explicitly, so a
late worker from an older generation can only observe its own stop event,
queues, pending requests, and process. Callbacks and handlers run outside the
stdout reader; shutdown never holds a client lock while waiting or joining.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import IO, Callable, Mapping

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
        r"(?i)((?:authorization|cookie|set-cookie|api[_-]?key|token|secret)"
        r"\s*[:=]\s*)[^\s,;]+"
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


@dataclass
class _Lifecycle:
    """All mutable process state belonging to one client generation."""

    generation_id: int
    process: subprocess.Popen[str] | None = None
    pid: int | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    completion_event: threading.Event = field(default_factory=threading.Event)
    pending: dict[JsonRpcId, _PendingRequest] = field(default_factory=dict)
    pending_lock: threading.Lock = field(default_factory=threading.Lock)
    stderr_lines: deque[str] = field(default_factory=deque)
    notifications: queue.Queue[JsonRpcNotification] = field(
        default_factory=lambda: queue.Queue(maxsize=100)
    )
    callback_notifications: queue.Queue[JsonRpcNotification] = field(
        default_factory=lambda: queue.Queue(maxsize=100)
    )
    server_requests: queue.Queue[JsonRpcServerRequest] = field(
        default_factory=lambda: queue.Queue(maxsize=100)
    )
    threads: list[threading.Thread] = field(default_factory=list)
    shutdown_lock: threading.Lock = field(default_factory=threading.Lock)
    shutdown_started: bool = False
    failure_started: bool = False
    initialize_sent: bool = False
    handshake_info: CodexHandshakeInfo | None = None
    last_error: str | None = None


class CodexAppServerClient:
    """Thread-safe lifecycle and JSON-RPC client for one owned process."""

    _NOTIFICATION_QUEUE_SIZE = 100
    _SERVER_REQUEST_QUEUE_SIZE = 100

    def __init__(self, config: CodexAppServerConfig | None = None) -> None:
        self._config = config or CodexAppServerConfig()
        self._state = CodexAppServerState.NEW
        self._state_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._handler_lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._next_request_id = 1
        self._generation_counter = 0
        self._active_lifecycle: _Lifecycle | None = None
        self._notification_callback: NotificationCallback | None = None
        self._server_request_handler: ServerRequestHandler | None = None

    @property
    def state(self) -> CodexAppServerState:
        with self._state_lock:
            return self._state

    @property
    def pid(self) -> int | None:
        with self._state_lock:
            lifecycle = self._active_lifecycle
            return None if lifecycle is None else lifecycle.pid

    @property
    def generation_id(self) -> int | None:
        """Return the active generation identifier, if one exists."""

        with self._state_lock:
            lifecycle = self._active_lifecycle
            return None if lifecycle is None else lifecycle.generation_id

    @property
    def is_ready(self) -> bool:
        return self.state is CodexAppServerState.READY

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            lifecycle = self._active_lifecycle
            return None if lifecycle is None else lifecycle.last_error

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        with self._state_lock:
            lifecycle = self._active_lifecycle
            if lifecycle is None:
                return ()
            return tuple(lifecycle.stderr_lines)

    @property
    def handshake_info(self) -> CodexHandshakeInfo | None:
        with self._state_lock:
            lifecycle = self._active_lifecycle
            return None if lifecycle is None else lifecycle.handshake_info

    @property
    def notification_overflow_policy(self) -> str:
        """The bounded notification queue drops its oldest item on overflow."""

        return "drop_oldest"

    def start(self) -> None:
        """Start a new isolated generation and complete one initialize handshake."""

        with self._state_lock:
            if self._state not in (
                CodexAppServerState.NEW,
                CodexAppServerState.CLOSED,
            ):
                raise CodexInvalidStateError(
                    f"cannot start from state {self._state.value}"
                )
            self._generation_counter += 1
            lifecycle = _Lifecycle(self._generation_counter)
            lifecycle.stderr_lines = deque(maxlen=self._config.stderr_max_lines)
            self._active_lifecycle = lifecycle
            self._state = CodexAppServerState.STARTING

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
            self._set_failure(lifecycle, error)
            raise error from exc

        with self._state_lock:
            if (
                self._active_lifecycle is not lifecycle
                or self._state is not CodexAppServerState.STARTING
            ):
                lifecycle.stop_event.set()
                process_to_stop = process
            else:
                lifecycle.process = process
                lifecycle.pid = process.pid
                process_to_stop = None

        if process_to_stop is not None:
            self._terminate_process(process_to_stop)
            lifecycle.completion_event.set()
            raise CodexProcessExitedError("Codex app-server generation was replaced")

        lifecycle.threads = [
            threading.Thread(
                target=self._read_stdout,
                args=(
                    lifecycle,
                    lifecycle.generation_id,
                    lifecycle.stop_event,
                    process,
                    process.stdout,
                ),
                name=f"openjarvis-codex-stdout-{lifecycle.generation_id}",
                daemon=True,
            ),
            threading.Thread(
                target=self._read_stderr,
                args=(
                    lifecycle,
                    lifecycle.generation_id,
                    lifecycle.stop_event,
                    process,
                    process.stderr,
                ),
                name=f"openjarvis-codex-stderr-{lifecycle.generation_id}",
                daemon=True,
            ),
            threading.Thread(
                target=self._wait_for_process,
                args=(
                    lifecycle,
                    lifecycle.generation_id,
                    lifecycle.stop_event,
                    process,
                ),
                name=f"openjarvis-codex-wait-{lifecycle.generation_id}",
                daemon=True,
            ),
            threading.Thread(
                target=self._dispatch_notification_callbacks,
                args=(
                    lifecycle,
                    lifecycle.generation_id,
                    lifecycle.stop_event,
                    process,
                ),
                name=f"openjarvis-codex-notifications-{lifecycle.generation_id}",
                daemon=True,
            ),
            threading.Thread(
                target=self._dispatch_server_requests,
                args=(
                    lifecycle,
                    lifecycle.generation_id,
                    lifecycle.stop_event,
                    process,
                ),
                name=f"openjarvis-codex-server-requests-{lifecycle.generation_id}",
                daemon=True,
            ),
        ]
        for thread in lifecycle.threads:
            thread.start()

        try:
            with self._state_lock:
                if self._active_lifecycle is not lifecycle:
                    raise CodexProcessExitedError(
                        "Codex app-server generation was replaced"
                    )
                if lifecycle.initialize_sent:
                    raise CodexProtocolError("initialize already sent")
                lifecycle.initialize_sent = True
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
                if self._active_lifecycle is not lifecycle:
                    raise CodexProcessExitedError(
                        "Codex app-server generation was replaced"
                    )
                lifecycle.handshake_info = handshake_info
            self._send_notification("initialized", {}, allow_starting=True)
            with self._state_lock:
                if self._active_lifecycle is not lifecycle:
                    raise CodexProcessExitedError(
                        "Codex app-server generation was replaced"
                    )
                if self._state is not CodexAppServerState.STARTING:
                    raise CodexProcessExitedError(
                        "Codex app-server exited during startup"
                    )
                self._state = CodexAppServerState.READY
        except CodexAppServerError as exc:
            self._set_failure(lifecycle, exc)
            raise
        except BaseException as exc:
            error = CodexProtocolError("Codex app-server handshake failed")
            self._set_failure(lifecycle, error)
            raise error from exc

    def close(self) -> None:
        """Close the active generation; a concurrent caller waits boundedly."""

        lifecycle: _Lifecycle | None
        owner = False
        wait_for_failure = False
        with self._state_lock:
            lifecycle = self._active_lifecycle
            if self._state in (
                CodexAppServerState.NEW,
                CodexAppServerState.CLOSED,
            ) or lifecycle is None:
                return
            if self._state is CodexAppServerState.CLOSING:
                pass
            elif self._state is CodexAppServerState.FAILED:
                wait_for_failure = True
            else:
                self._state = CodexAppServerState.CLOSING
                owner = True

        if wait_for_failure:
            lifecycle.completion_event.wait(self._close_wait_timeout())
            with self._state_lock:
                if (
                    self._active_lifecycle is lifecycle
                    and lifecycle.completion_event.is_set()
                ):
                    self._state = CodexAppServerState.CLOSED
            return
        if not owner:
            lifecycle.completion_event.wait(self._close_wait_timeout())
            return

        self._shutdown_generation(
            lifecycle,
            final_state=CodexAppServerState.CLOSED,
            failure=None,
        )

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
        self._send_notification(method, params, allow_starting=False)

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
            account_type = account.get("type")
            if auth_mode is None and isinstance(account_type, str):
                auth_mode = account_type
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

    def get_notification(
        self, timeout_seconds: float | None = None
    ) -> JsonRpcNotification | None:
        """Consume a notification from the generation active at call time."""

        with self._state_lock:
            lifecycle = self._active_lifecycle
        if lifecycle is None:
            return None
        try:
            return lifecycle.notifications.get(timeout=timeout_seconds)
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
            lifecycle = self._active_lifecycle
            if (
                self._state is not CodexAppServerState.READY
                or lifecycle is None
                or lifecycle.failure_started
            ):
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
            lifecycle = self._active_lifecycle
            allowed = (
                self._state is CodexAppServerState.READY
                and lifecycle is not None
                and not lifecycle.failure_started
            ) or (
                allow_starting
                and self._state is CodexAppServerState.STARTING
                and lifecycle is not None
                and not lifecycle.failure_started
            )
            if not allowed or lifecycle is None:
                raise CodexInvalidStateError(
                    f"cannot request in state {self._state.value}"
                )

        request_id = self._next_id()
        message: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        encoded = self._encode_message(
            message,
            "request parameters are not JSON serializable",
        )
        pending = _PendingRequest(event=threading.Event())
        with lifecycle.pending_lock:
            lifecycle.pending[request_id] = pending
        try:
            self._write_encoded(lifecycle, encoded)
        except BaseException as exc:
            with lifecycle.pending_lock:
                lifecycle.pending.pop(request_id, None)
            error = CodexProcessExitedError("unable to write to Codex app-server")
            self._set_failure(lifecycle, error)
            raise error from exc
        if not pending.event.wait(timeout_seconds):
            with lifecycle.pending_lock:
                lifecycle.pending.pop(request_id, None)
            raise CodexRequestTimeout(f"request {request_id} timed out")
        with lifecycle.pending_lock:
            lifecycle.pending.pop(request_id, None)
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

    def _send_notification(
        self,
        method: str,
        params: object | None,
        *,
        allow_starting: bool,
    ) -> None:
        with self._state_lock:
            lifecycle = self._active_lifecycle
            allowed = (
                self._state is CodexAppServerState.READY
                and lifecycle is not None
                and not lifecycle.failure_started
            ) or (
                allow_starting
                and self._state is CodexAppServerState.STARTING
                and lifecycle is not None
                and not lifecycle.failure_started
            )
            if not allowed or lifecycle is None:
                raise CodexInvalidStateError(
                    f"cannot notify in state {self._state.value}"
                )
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        encoded = self._encode_message(
            message,
            "notification parameters are not JSON serializable",
        )
        self._write_encoded(lifecycle, encoded)

    @staticmethod
    def _encode_message(message: Mapping[str, object], error_message: str) -> str:
        try:
            return encode_jsonrpc(message)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise CodexProtocolError(error_message) from exc

    def _write_encoded(
        self,
        lifecycle: _Lifecycle,
        encoded: str,
        *,
        process: subprocess.Popen[str] | None = None,
    ) -> None:
        with self._write_lock:
            owned_process = process if process is not None else lifecycle.process
            if owned_process is None or owned_process.stdin is None:
                raise CodexProcessExitedError(
                    "Codex app-server stdin is unavailable"
                )
            try:
                owned_process.stdin.write(encoded)
                owned_process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise CodexProcessExitedError(
                    "Codex app-server stdin is unavailable"
                ) from exc

    def _read_stdout(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        process: subprocess.Popen[str],
        stream: IO[str] | None,
    ) -> None:
        del process
        if stream is None:
            self._set_failure(
                lifecycle,
                CodexProtocolError("Codex app-server stdout is unavailable"),
            )
            return
        try:
            for line in stream:
                if not self._worker_is_active(lifecycle, generation_id, stop_event):
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
                    self._set_failure(lifecycle, error)
                    break
                if isinstance(envelope, JsonRpcResponse):
                    self._complete_response(lifecycle, envelope)
                elif isinstance(envelope, JsonRpcNotification):
                    self._queue_notification(lifecycle, envelope)
                else:
                    self._queue_server_request(
                        lifecycle, generation_id, stop_event, envelope
                    )
        except (OSError, ValueError):
            if not stop_event.is_set():
                self._set_failure(
                    lifecycle,
                    CodexProcessExitedError("Codex app-server stdout closed"),
                )
        finally:
            if not stop_event.is_set():
                self._set_failure(
                    lifecycle,
                    CodexProcessExitedError("Codex app-server stdout reached EOF"),
                )

    def _read_stderr(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        process: subprocess.Popen[str],
        stream: IO[str] | None,
    ) -> None:
        del generation_id, process
        if stream is None:
            return
        try:
            for line in stream:
                if stop_event.is_set():
                    break
                clean_line = _sanitize_text(line.rstrip("\r\n"))
                lifecycle.stderr_lines.append(clean_line)
        except (OSError, ValueError):
            return

    def _wait_for_process(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        process: subprocess.Popen[str],
    ) -> None:
        try:
            return_code = process.wait()
        except (OSError, ValueError):
            return_code = None
        if stop_event.is_set() or not self._worker_is_active(
            lifecycle, generation_id, stop_event
        ):
            return
        if return_code not in (0, None):
            self._set_failure(
                lifecycle,
                CodexProcessExitedError(
                    f"Codex app-server exited with code {return_code}"
                ),
            )
        else:
            self._set_failure(
                lifecycle,
                CodexProcessExitedError("Codex app-server exited"),
            )

    @staticmethod
    def _complete_response(
        lifecycle: _Lifecycle, response: JsonRpcResponse
    ) -> None:
        with lifecycle.pending_lock:
            pending = lifecycle.pending.get(response.request_id)
            if pending is None:
                return
            pending.response = response
            pending.event.set()

    def _queue_notification(
        self, lifecycle: _Lifecycle, notification: JsonRpcNotification
    ) -> None:
        self._bounded_put(lifecycle.notifications, notification)
        self._bounded_put(lifecycle.callback_notifications, notification)

    def _queue_server_request(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        request: JsonRpcServerRequest,
    ) -> None:
        try:
            lifecycle.server_requests.put_nowait(request)
        except queue.Full:
            self._send_error_response(
                lifecycle,
                request.request_id,
                -32001,
                "server request queue full",
                generation_id=generation_id,
                stop_event=stop_event,
            )

    @staticmethod
    def _worker_is_active(
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
    ) -> bool:
        return (
            lifecycle.generation_id == generation_id
            and lifecycle.stop_event is stop_event
            and not stop_event.is_set()
        )

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

    def _dispatch_notification_callbacks(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        process: subprocess.Popen[str],
    ) -> None:
        del process
        while self._worker_is_active(lifecycle, generation_id, stop_event):
            try:
                notification = lifecycle.callback_notifications.get(timeout=0.1)
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

    def _dispatch_server_requests(
        self,
        lifecycle: _Lifecycle,
        generation_id: int,
        stop_event: threading.Event,
        process: subprocess.Popen[str],
    ) -> None:
        while self._worker_is_active(lifecycle, generation_id, stop_event):
            try:
                request = lifecycle.server_requests.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._handler_lock:
                handler = self._server_request_handler
            if handler is None:
                self._send_error_response(
                    lifecycle,
                    request.request_id,
                    -32601,
                    "no server request handler registered",
                    generation_id=generation_id,
                    stop_event=stop_event,
                    process=process,
                )
                continue
            try:
                result = handler(request)
            except BaseException:
                self._send_error_response(
                    lifecycle,
                    request.request_id,
                    -32000,
                    "server request handler failed",
                    generation_id=generation_id,
                    stop_event=stop_event,
                    process=process,
                )
                continue
            try:
                encoded = self._encode_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request.request_id,
                        "result": result,
                    },
                    "server request handler returned an invalid result",
                )
            except CodexProtocolError:
                self._send_error_response(
                    lifecycle,
                    request.request_id,
                    -32603,
                    "server request handler returned an invalid result",
                    generation_id=generation_id,
                    stop_event=stop_event,
                    process=process,
                )
                continue
            try:
                self._write_encoded(lifecycle, encoded, process=process)
            except CodexAppServerError as exc:
                self._set_failure(lifecycle, exc)

    def _send_error_response(
        self,
        lifecycle: _Lifecycle,
        request_id: JsonRpcId,
        code: int,
        message: str,
        *,
        generation_id: int | None = None,
        stop_event: threading.Event | None = None,
        process: subprocess.Popen[str] | None = None,
    ) -> None:
        if generation_id is not None and stop_event is not None:
            if not self._worker_is_active(lifecycle, generation_id, stop_event):
                return
        try:
            encoded = self._encode_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": code, "message": message},
                },
                "server request error could not be serialized",
            )
            self._write_encoded(lifecycle, encoded, process=process)
        except CodexAppServerError as exc:
            self._set_failure(lifecycle, exc)

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
            platform_family=(
                platform_family if isinstance(platform_family, str) else None
            ),
            platform_os=platform_os if isinstance(platform_os, str) else None,
            user_agent_present=isinstance(result.get("userAgent"), str),
            capabilities=capabilities,
        )

    def _set_failure(
        self, lifecycle: _Lifecycle, error: CodexAppServerError
    ) -> None:
        should_shutdown = False
        with self._state_lock:
            if self._active_lifecycle is lifecycle:
                if self._state not in (
                    CodexAppServerState.CLOSING,
                    CodexAppServerState.CLOSED,
                ):
                    lifecycle.last_error = _sanitize_text(str(error))
                    lifecycle.failure_started = True
                    should_shutdown = True
            else:
                lifecycle.stop_event.set()
        self._fail_pending(lifecycle, error)
        if should_shutdown:
            self._shutdown_generation(
                lifecycle,
                final_state=CodexAppServerState.FAILED,
                failure=error,
            )

    @staticmethod
    def _fail_pending(lifecycle: _Lifecycle, error: CodexAppServerError) -> None:
        with lifecycle.pending_lock:
            for pending in lifecycle.pending.values():
                pending.failure = error
                pending.event.set()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except (OSError, ValueError):
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

    def _shutdown_generation(
        self,
        lifecycle: _Lifecycle,
        *,
        final_state: CodexAppServerState,
        failure: CodexAppServerError | None,
    ) -> None:
        with lifecycle.shutdown_lock:
            if lifecycle.shutdown_started:
                owner = False
            else:
                lifecycle.shutdown_started = True
                owner = True
        if not owner:
            lifecycle.completion_event.wait(self._close_wait_timeout())
            return

        close_error: BaseException | None = None
        lifecycle.stop_event.set()
        self._fail_pending(
            lifecycle,
            failure or CodexProcessExitedError("Codex app-server is closing"),
        )
        process = lifecycle.process
        if process is not None:
            try:
                with self._write_lock:
                    if process.stdin is not None:
                        process.stdin.close()
            except (OSError, ValueError) as exc:
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

        current = threading.current_thread()
        for thread in lifecycle.threads:
            if thread is not current:
                thread.join(timeout=self._config.shutdown_timeout_seconds)

        try:
            with self._state_lock:
                lifecycle.pid = None
                lifecycle.process = None
                if self._active_lifecycle is lifecycle:
                    if close_error is None:
                        self._state = final_state
                    else:
                        self._state = CodexAppServerState.FAILED
                        lifecycle.last_error = _sanitize_text(str(close_error))
        finally:
            lifecycle.completion_event.set()

    def _close_wait_timeout(self) -> float:
        return max(self._config.shutdown_timeout_seconds * 6, 0.5)


__all__ = [
    "CodexAppServerClient",
    "NotificationCallback",
    "ServerRequestHandler",
]
