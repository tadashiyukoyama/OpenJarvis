from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import httpx
import pytest

from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import AceleraChatConfig
from openjarvis.server.jarvis_agent.adapters.acelerachat.webhooks import (
    AceleraChatWebhookService,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService

_SECRET = "webhook-test-secret"


def _service(
    tmp_path: Path,
    handler=None,
    *,
    current_secret: str = _SECRET,
    previous_secret: str = "",
) -> tuple[AceleraChatWebhookService, JarvisAgentStore]:
    store = JarvisAgentStore(tmp_path / "webhook.sqlite3")
    config = AceleraChatConfig(
        base_url="https://acelerachat.test/api/v1/openjarvis",
        bearer_token="token",
        webhook_secret_current=current_secret,
        webhook_secret_previous=previous_secret,
    )
    client = AceleraChatClient(
        config,
        transport=httpx.MockTransport(handler or (lambda _: None)),
    )
    service = AceleraChatWebhookService(
        config=config,
        client=client,
        store=store,
        events=EventService(store),
        context=ContextService(store),
    )
    return service, store


def _dispatching_action(store: JarvisAgentStore) -> None:
    store.create_session(
        {
            "session_id": "session-1",
            "generation": 1,
            "project_key": "D:/project",
            "codex_thread_id": "thread-1",
            "manifest_version": "v1",
            "state": "CLOSED",
            "created_at": 1.0,
        }
    )
    store.create_action(
        {
            "action_id": "action-1",
            "session_id": "session-1",
            "generation": 1,
            "function_call_id": "function-1",
            "tool_id": "whatsapp.send_text",
            "payload_hash": "c" * 64,
            "payload": {"text": "private"},
            "preview": {"message": "private"},
            "state": "DISPATCHING",
            "created_at": 1.0,
        }
    )


def _accepted_action(store: JarvisAgentStore) -> None:
    _dispatching_action(store)
    store.accept_external_operation(
        action_id="action-1",
        provider="acelerachat",
        resource_type="Message",
        resource_id="901",
        result={"status": "accepted", "references": {"message": "war_test"}},
        summary="accepted",
        now=2.0,
    )


def _body(*, sequence: int, status: str, result_state: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "event": "message.updated",
            "occurred_at": "2026-08-18T12:01:00Z",
            "resource": {
                "type": "Message",
                "id": 901,
                "internal_id": 901,
                "version": f"v{sequence}",
                "sequence": sequence,
            },
            "data": {
                "id": 901,
                "status": status,
                "delivery": {"status": status, "result_state": result_state},
            },
        },
        separators=(",", ":"),
    ).encode()


def _headers(body: bytes, *, secret: str = _SECRET) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return {
        "delivery_id": str(uuid.uuid4()),
        "timestamp": timestamp,
        "signature": f"sha256={digest}",
    }


def test_signed_delivery_event_completes_action_once(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    _accepted_action(store)
    body = _body(sequence=2, status="delivered", result_state="confirmed")
    headers = _headers(body)

    first = service.receive(body, **headers)
    duplicate = service.receive(body, **headers)

    assert first["disposition"] == "accepted"
    assert duplicate["disposition"] == "duplicate"
    action = store.get_action("action-1")
    assert action["state"] == "COMPLETED"
    assert action["payload"] is None
    assert action["result"]["references"] == {"message": "war_test"}
    assert action["result"]["status"] == "delivered"
    completed = [
        event
        for event in store.list_events(0, 100)
        if event["event_type"] == "dispatch_completed"
    ]
    assert len(completed) == 1


def test_out_of_order_event_cannot_roll_completed_action_back(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    _accepted_action(store)
    delivered = _body(sequence=2, status="delivered", result_state="confirmed")
    service.receive(delivered, **_headers(delivered))
    stale = _body(sequence=1, status="sent", result_state="unknown")

    result = service.receive(stale, **_headers(stale))

    assert result["disposition"] == "out_of_order"
    assert store.get_action("action-1")["state"] == "COMPLETED"


def test_later_contradictory_event_cannot_reverse_terminal_delivery(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    _accepted_action(store)
    delivered = _body(sequence=2, status="delivered", result_state="confirmed")
    failed = _body(sequence=3, status="failed", result_state="failed")
    try:
        service.receive(delivered, **_headers(delivered))
        result = service.receive(failed, **_headers(failed))
    finally:
        service.close()

    assert result["disposition"] == "accepted"
    assert store.get_action("action-1")["state"] == "COMPLETED"
    connection = store._connect()
    try:
        external_state = connection.execute(
            "SELECT state FROM jarvis_external_operations WHERE action_id = ?",
            ("action-1",),
        ).fetchone()["state"]
    finally:
        connection.close()
    assert external_state == "COMPLETED"
    terminal_events = [
        event
        for event in store.list_events(0, 100)
        if event["event_type"] in {"dispatch_completed", "dispatch_failed"}
    ]
    assert [event["event_type"] for event in terminal_events] == ["dispatch_completed"]


def test_event_arriving_before_local_acceptance_is_reconciled_atomically(
    tmp_path: Path,
) -> None:
    service, store = _service(tmp_path)
    _dispatching_action(store)
    delivered = _body(sequence=2, status="delivered", result_state="confirmed")

    received = service.receive(delivered, **_headers(delivered))
    assert received["disposition"] == "accepted"
    assert store.get_action("action-1")["state"] == "DISPATCHING"

    reconciled = store.accept_external_operation(
        action_id="action-1",
        provider="acelerachat",
        resource_type="Message",
        resource_id="901",
        result={"status": "accepted", "references": {"message": "war_test"}},
        summary="accepted",
        now=time.time(),
    )

    assert reconciled["state"] == "COMPLETED"
    assert reconciled["result"]["status"] == "delivered"
    assert reconciled["result"]["references"] == {"message": "war_test"}


def test_invalid_signature_is_rejected_before_persistence(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    body = _body(sequence=1, status="sent", result_state="unknown")

    try:
        with pytest.raises(JarvisAgentError) as raised:
            service.receive(
                body,
                delivery_id=str(uuid.uuid4()),
                timestamp=str(int(time.time())),
                signature="sha256=" + "0" * 64,
            )
    finally:
        service.close()

    assert raised.value.code == "WEBHOOK_INVALID_SIGNATURE"
    connection = store._connect()
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM jarvis_provider_events"
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 0


def test_oversized_webhook_is_rejected_before_signature_work(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    try:
        with pytest.raises(JarvisAgentError) as captured:
            service.receive(
                b"x" * (1024 * 1024 + 1),
                delivery_id=str(uuid.uuid4()),
                timestamp=str(int(time.time())),
                signature="",
            )
    finally:
        service.close()

    assert captured.value.code == "WEBHOOK_INVALID_PAYLOAD"


def test_previous_rotation_signature_is_accepted_during_overlap(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        current_secret="new-secret",
        previous_secret=_SECRET,
    )
    body = _body(sequence=1, status="sent", result_state="unknown")
    headers = _headers(body)

    result = service.receive(
        body,
        delivery_id=headers["delivery_id"],
        timestamp=headers["timestamp"],
        signature="",
        previous_signature=headers["signature"],
    )

    assert result["disposition"] == "accepted"


def test_backfill_is_read_only_bounded_and_idempotent(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    event_id = "backfill:Contact:41:7b0f0e4aa11f0ab2"

    def backfill(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path.endswith("/backfill")
        assert request.url.params["resource"] == "contacts"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "schema_version": "1.0",
                        "event_id": event_id,
                        "event": "resource.snapshot",
                        "occurred_at": "2026-08-18T12:00:00Z",
                        "resource": {
                            "type": "Contact",
                            "id": 41,
                            "internal_id": 41,
                            "version": "v1",
                            "sequence": 1,
                        },
                        "data": {"id": 41, "name": "Example"},
                    }
                ],
                "meta": {
                    "resource": "contacts",
                    "limit": 100,
                    "returned": 1,
                    "has_more": False,
                    "next_cursor": None,
                },
            },
        )

    service, store = _service(tmp_path, backfill)
    try:
        first = service.reconcile("contacts")
        repeated = service.reconcile("contacts")
    finally:
        service.close()

    assert first == {"accepted": 1, "duplicate": 0, "out_of_order": 0}
    assert repeated == {"accepted": 0, "duplicate": 1, "out_of_order": 0}
    assert len(requests) == 2
    connection = store._connect()
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM jarvis_provider_events"
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1
