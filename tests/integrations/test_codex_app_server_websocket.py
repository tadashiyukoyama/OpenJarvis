"""Loopback WebSocket tests for the shared Codex app-server transport."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator

import pytest
from websockets.sync.server import Server, ServerConnection, serve

from openjarvis.integrations.codex_app_server import CodexAppServerClient
from openjarvis.integrations.codex_protocol import CodexAppServerConfig


class _FakeSharedAppServer:
    def __init__(self) -> None:
        self._connections: set[ServerConnection] = set()
        self._lock = threading.Lock()
        self._server: Server = serve(self._handle, "127.0.0.1", 0)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fake-shared-codex-app-server",
            daemon=True,
        )

    @property
    def url(self) -> str:
        port = self._server.socket.getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=2)

    def _handle(self, connection: ServerConnection) -> None:
        with self._lock:
            self._connections.add(connection)
        try:
            for raw_message in connection:
                assert isinstance(raw_message, str)
                message = json.loads(raw_message)
                method = message.get("method")
                request_id = message.get("id")
                if request_id is None:
                    continue
                if method == "initialize":
                    result: object = {"capabilities": {"shared": True}}
                elif method == "echo":
                    result = message.get("params")
                elif method == "large":
                    result = {"content": "x" * (2 * 1024 * 1024)}
                elif method == "broadcast":
                    result = {"accepted": True}
                    self._broadcast(
                        {
                            "jsonrpc": "2.0",
                            "method": "turn/started",
                            "params": {"threadId": "thread-shared"},
                        }
                    )
                else:
                    result = {}
                connection.send(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": request_id, "result": result},
                        separators=(",", ":"),
                    )
                )
        finally:
            with self._lock:
                self._connections.discard(connection)

    def _broadcast(self, message: dict[str, object]) -> None:
        encoded = json.dumps(message, separators=(",", ":"))
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            connection.send(encoded)


@pytest.fixture
def shared_app_server() -> Iterator[_FakeSharedAppServer]:
    server = _FakeSharedAppServer()
    server.start()
    try:
        yield server
    finally:
        server.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8128",
        "ws://0.0.0.0:8128",
        "ws://192.168.1.10:8128",
        "ws://user:secret@127.0.0.1:8128",
        "ws://127.0.0.1",
        "ws://127.0.0.1:8128/?token=secret",
    ],
)
def test_config_rejects_non_loopback_or_credential_bearing_url(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        CodexAppServerConfig(websocket_url=url)


@pytest.mark.parametrize("value", [0, -1, True])
def test_config_rejects_invalid_websocket_message_limit(value: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        CodexAppServerConfig(websocket_max_message_bytes=value)


def test_config_rejects_non_boolean_unhandled_request_policy() -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        CodexAppServerConfig(reject_unhandled_server_requests="no")  # type: ignore[arg-type]


def test_websocket_transport_connects_without_owning_server_process(
    shared_app_server: _FakeSharedAppServer,
) -> None:
    client = CodexAppServerClient(
        CodexAppServerConfig(websocket_url=shared_app_server.url)
    )
    client.start()
    try:
        assert client.transport_kind == "websocket"
        assert client.pid is None
        assert client.request("echo", {"shared": True}) == {"shared": True}
    finally:
        client.close()

    assert client.state.value == "CLOSED"


def test_websocket_transport_accepts_large_thread_history_frames(
    shared_app_server: _FakeSharedAppServer,
) -> None:
    client = CodexAppServerClient(
        CodexAppServerConfig(websocket_url=shared_app_server.url)
    )
    client.start()
    try:
        result = client.request("large", {})
        assert isinstance(result, dict)
        assert len(result["content"]) == 2 * 1024 * 1024
    finally:
        client.close()


def test_two_websocket_clients_receive_the_same_live_notification(
    shared_app_server: _FakeSharedAppServer,
) -> None:
    clients = [
        CodexAppServerClient(
            CodexAppServerConfig(
                websocket_url=shared_app_server.url,
                client_name=f"openjarvis-test-{index}",
            )
        )
        for index in range(2)
    ]
    for client in clients:
        client.start()
    try:
        assert clients[0].request("broadcast", {}) == {"accepted": True}
        notifications = [
            client.get_notification(timeout_seconds=2) for client in clients
        ]
        assert [item.method if item else None for item in notifications] == [
            "turn/started",
            "turn/started",
        ]

        clients[0].close()
        assert clients[1].request("echo", {"server": "alive"}) == {"server": "alive"}
    finally:
        for client in clients:
            client.close()
