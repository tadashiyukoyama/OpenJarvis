"""Contract tests for the owner-facing Agent Host transport boundary."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.channels.whatsapp.store import WhatsAppStore  # noqa: E402
from openjarvis.server.agent_host_bridge import AgentHostClient  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402


def _engine() -> MagicMock:
    value = MagicMock()
    value.engine_id = "bridge-test"
    value.health.return_value = True
    value.list_models.return_value = ["bridge-test"]
    return value


@pytest.fixture()
def bridge_client(monkeypatch):
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    async def fake_request(self, method, path, payload=None, query=None):
        calls.append((method, path, payload, query))
        if path.endswith("/status"):
            return {"status": "waiting", "principal_id": "owner"}
        if path.endswith("/history"):
            return {"events": [], "next_after": 0, "principal_id": "owner"}
        return {"status": "accepted", "principal_id": "owner"}

    monkeypatch.setattr(AgentHostClient, "request", fake_request)
    app = create_app(_engine(), "bridge-test", api_key="")
    return TestClient(app), calls


def test_owner_identity_and_host_routes_are_thin(bridge_client) -> None:
    client, calls = bridge_client

    status = client.get("/v1/agent-host/status", params={"conversation_id": "c-1"})
    assert status.status_code == 200
    assert status.json()["principal_id"] == "owner"

    message = client.post(
        "/v1/agent-host/messages",
        json={
            "conversation_id": "c-1",
            "message": "olá",
            "idempotency_key": "m-1",
            "correlation_id": "corr-1",
        },
    )
    assert message.status_code == 202
    assert calls[-1][2]["principal_id"] == "owner"
    assert calls[-1][2]["correlation_id"] == "corr-1"

    approval = client.post(
        "/v1/agent-host/approvals/test",
        json={"preview": {"kind": "safe_test"}},
    )
    assert approval.status_code == 202
    assert calls[-1][1].endswith("/approvals/test")


def test_whatsapp_inbox_lists_opaque_threads_and_requires_operator_confirmation(
    bridge_client,
) -> None:
    client, calls = bridge_client
    conversation_id = "wa:" + "a" * 32

    listing = client.get("/v1/agent-host/whatsapp/conversations")
    assert listing.status_code == 200
    assert calls[-1][1].endswith("/conversations")

    missing_confirmation = client.post(
        "/v1/agent-host/whatsapp/reply",
        json={
            "conversation_id": conversation_id,
            "message": "resposta",
            "idempotency_key": "operator-1",
        },
    )
    assert missing_confirmation.status_code == 409

    reply = client.post(
        "/v1/agent-host/whatsapp/reply",
        json={
            "conversation_id": conversation_id,
            "message": "resposta",
            "idempotency_key": "operator-1",
            "confirm_send": True,
        },
    )
    assert reply.status_code == 200
    assert calls[-1][1].endswith("/whatsapp/reply")
    assert calls[-1][2]["confirm_send"] is True


def test_owner_message_rejects_unknown_fields(bridge_client) -> None:
    client, _ = bridge_client
    response = client.post(
        "/v1/agent-host/messages",
        json={"conversation_id": "c-1", "message": "x", "tool": "crm"},
    )
    assert response.status_code == 422


def test_authenticated_operation_reconciliation_is_read_only(
    tmp_path, monkeypatch
) -> None:
    secret = "s" * 48
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", secret)
    store = WhatsAppStore(tmp_path / "wa.db")
    store.save_agent_host_outbound(
        "key-read-only",
        "wa-op-read-only",
        {"status": "completed", "data": {"remote_message_id": "remote-1"}},
    )

    class Channel:
        _store = store

    class Gateway:
        channel = Channel()

        @staticmethod
        def get_outbound_operation(*, operation_id=None, idempotency_key=None):
            if operation_id:
                return store.get_agent_host_outbound_by_operation(operation_id) or {
                    "status": "not_found"
                }
            return store.get_agent_host_outbound(idempotency_key) or {
                "status": "not_found"
            }

    monkeypatch.setattr(
        "openjarvis.server.whatsapp_agent_host.get_whatsapp_agent_host_gateway",
        lambda app: Gateway(),
    )
    app = create_app(_engine(), "bridge-test", api_key="")
    client = TestClient(app)
    path = "/v1/agent-host/gateway/whatsapp/operation"
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(),
        "\n".join((timestamp, "GET", path, hashlib.sha256(b"").hexdigest())).encode(),
        hashlib.sha256,
    ).hexdigest()
    response = client.get(
        path,
        params={"operation_id": "wa-op-read-only"},
        headers={
            "X-Agent-Principal": "agent-host-gateway",
            "X-Agent-Timestamp": timestamp,
            "X-Agent-Signature": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["remote_message_id"] == "remote-1"
    store.close()
