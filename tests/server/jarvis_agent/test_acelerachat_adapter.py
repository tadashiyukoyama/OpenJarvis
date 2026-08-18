from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from openjarvis.server.jarvis_agent.adapters.acelerachat import AceleraChatAdapter
from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import AceleraChatConfig
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.services.orchestrator import JarvisAgentOrchestrator
from openjarvis.server.jarvis_agent.services.references import ReferenceService


def _capability(supported: bool = True) -> dict[str, Any]:
    return {"supported": supported, "mode": "acelerachat"}


def _inbox(inbox_id: int, channel_type: str, *, connected: bool) -> dict[str, Any]:
    capabilities = {
        "connection.inspect": _capability(),
        "conversations.search": _capability(),
        "messages.search": _capability(),
        "messages.read": _capability(),
        "messages.send": _capability(),
        "messages.mark_read_internal": _capability(),
    }
    if channel_type == "Channel::Email":
        capabilities.update(
            {
                "email.search": _capability(),
                "email.unread": _capability(),
                "email.threads": _capability(),
                "email.reply": _capability(),
            }
        )
    return {
        "id": inbox_id,
        "name": f"Inbox {inbox_id}",
        "channel_type": channel_type,
        "inbox_type": "Email" if channel_type == "Channel::Email" else "Whatsapp",
        "connection": {
            "state": "connected" if connected else "configured_not_probed",
            "connected": connected,
            "operational": True,
            "provider": "evolution" if connected else "imap_smtp",
        },
        "capabilities": capabilities,
    }


def _contact(contact_id: int = 41, name: str = "Klaus Consultor") -> dict[str, Any]:
    return {"id": contact_id, "name": name, "blocked": False}


def _conversation(
    contact: Mapping[str, Any],
    inbox: Mapping[str, Any],
    *,
    conversation_id: int = 104,
) -> dict[str, Any]:
    return {
        "id": conversation_id,
        "status": "open",
        "inbox": inbox,
        "contact": dict(contact),
        "labels": [],
        "created_at": "2026-08-18T10:00:00Z",
        "updated_at": "2026-08-18T12:00:00Z",
    }


def _message(*, status: str = "sent", result_state: str = "unknown") -> dict[str, Any]:
    return {
        "id": 901,
        "conversation_id": 104,
        "message_type": "outgoing",
        "content_type": "text",
        "content": "Olá",
        "private": False,
        "status": status,
        "delivery": {"status": status, "result_state": result_state},
        "attachments": [],
        "unread": False,
        "created_at": "2026-08-18T12:00:00Z",
        "updated_at": "2026-08-18T12:00:00Z",
    }


def _email_message() -> dict[str, Any]:
    message = _message(status="sent", result_state="submitted")
    message.update(
        id=902,
        conversation_id=204,
        message_type="incoming",
        content="Assunto de atendimento",
        unread=True,
        sender={"name": "Marta", "email": "marta@example.test", "type": "contact"},
        email={
            "thread_id": "bf4fd8d4-b655-4e3f-a7c0-9beec9bb4598",
            "subject": "Atendimento",
            "to": ["suporte@example.test"],
            "cc": [],
            "bcc": [],
        },
    )
    return message


class ApiDouble:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.email = _inbox(15, "Channel::Email", connected=False)
        self.whatsapp = _inbox(19, "Channel::Whatsapp", connected=True)
        self.ambiguous = ambiguous
        self.posts: list[httpx.Request] = []
        self.before_message_response = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/inboxes"):
            return httpx.Response(200, json={"data": [self.email, self.whatsapp]})
        if request.method == "GET" and path.endswith("/contacts"):
            contacts = [_contact()]
            if self.ambiguous:
                contacts.append(_contact(42, "Klaus Consultor"))
            return httpx.Response(200, json={"data": contacts, "meta": {}})
        if (
            request.method == "GET"
            and path.endswith("/messages")
            and not path.endswith("/conversations/104/messages")
            and not path.endswith("/conversations/204/messages")
        ):
            return httpx.Response(200, json={"data": [_email_message()], "meta": {}})
        if request.method == "GET" and path.endswith("/conversations"):
            contact_id = int(request.url.params.get("contact_id", "41"))
            contact = _contact(contact_id)
            conversation = _conversation(contact, self.whatsapp)
            if contact_id == 42:
                conversation["id"] = 105
            return httpx.Response(200, json={"data": [conversation], "meta": {}})
        if request.method == "GET" and path.endswith("/conversations/204"):
            contact = {
                "id": 51,
                "name": "Marta",
                "email": "marta@example.test",
                "blocked": False,
            }
            return httpx.Response(
                200,
                json={"data": _conversation(contact, self.email, conversation_id=204)},
            )
        if request.method == "GET" and path.endswith("/conversations/204/messages"):
            return httpx.Response(200, json={"data": [_email_message()], "meta": {}})
        if request.method == "POST" and path.endswith("/conversations/104/messages"):
            self.posts.append(request)
            if self.before_message_response is not None:
                self.before_message_response()
            return httpx.Response(
                201,
                json={
                    "data": _message(),
                    "result": {
                        "state": "accepted",
                        "delivery_confirmation": "asynchronous",
                        "result_state": "unknown_until_message_updated",
                    },
                },
            )
        if request.method == "POST" and path.endswith("/conversations/204/messages"):
            self.posts.append(request)
            message = _email_message()
            message.update(message_type="outgoing", unread=False)
            return httpx.Response(
                201,
                json={
                    "data": message,
                    "result": {
                        "state": "accepted",
                        "delivery_confirmation": "asynchronous",
                        "result_state": "unknown_until_message_updated",
                    },
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")


def _orchestrator(tmp_path: Path, api: ApiDouble) -> JarvisAgentOrchestrator:
    store = JarvisAgentStore(tmp_path / "acelerachat.sqlite3")
    adapter = AceleraChatAdapter(
        ReferenceService(store),
        config=AceleraChatConfig(
            base_url="https://acelerachat.test/api/v1/openjarvis",
            bearer_token="test-token",
            email_inbox_id=15,
            whatsapp_inbox_id=19,
        ),
        transport=httpx.MockTransport(api),
        capability_ttl_seconds=60,
    )
    return JarvisAgentOrchestrator(
        store=store,
        catalog=JarvisToolCatalog(),
        adapters={"acelerachat": adapter},
    )


def test_send_by_unique_contact_is_approved_once_and_remains_accepted(
    tmp_path: Path,
) -> None:
    api = ApiDouble()
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-send",
            tool_name="whatsapp_send_text",
            arguments={"contact_name": "Klaus Consultor", "text": "Olá"},
        )

        assert pending["state"] == "AWAITING_APPROVAL"
        assert pending["preview"]["target"] == "Klaus Consultor"
        assert api.posts == []

        accepted = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )
        repeated = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert accepted["status"] == "accepted"
        assert repeated["status"] == "accepted"
        assert len(api.posts) == 1
        assert (
            api.posts[0].headers["Idempotency-Key"] == f"jarvis:{pending['action_id']}"
        )
        assert orchestrator.store.get_action(pending["action_id"])["payload"] is None
    finally:
        orchestrator.close()


def test_ambiguous_contact_never_creates_a_proposal_or_send(tmp_path: Path) -> None:
    api = ApiDouble(ambiguous=True)
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        with pytest.raises(JarvisAgentError) as raised:
            orchestrator.propose(
                session_id=session["session_id"],
                generation=session["generation"],
                function_call_id="fc-ambiguous",
                tool_name="whatsapp_send_text",
                arguments={"contact_name": "Klaus Consultor", "text": "Olá"},
            )
        assert raised.value.code == "INVALID_REQUEST"
        assert api.posts == []
    finally:
        orchestrator.close()


def test_client_does_not_retry_unknown_mutation(tmp_path: Path) -> None:
    attempts = 0

    def timeout(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timeout")

    store = JarvisAgentStore(tmp_path / "timeout.sqlite3")
    adapter = AceleraChatAdapter(
        ReferenceService(store),
        config=AceleraChatConfig(
            base_url="https://acelerachat.test/api/v1/openjarvis",
            bearer_token="token",
        ),
        transport=httpx.MockTransport(timeout),
    )
    try:
        with pytest.raises(JarvisAgentError) as raised:
            adapter.client.create_message(
                104, {"content": "once"}, idempotency_key="jarvis:once"
            )
        assert raised.value.code == "EXTERNAL_RESULT_UNKNOWN"
        assert attempts == 1
    finally:
        adapter.close()


def test_provider_delivery_race_returns_the_reconciled_terminal_state(
    tmp_path: Path,
) -> None:
    api = ApiDouble()
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-race",
            tool_name="whatsapp_send_text",
            arguments={"contact_name": "Klaus Consultor", "text": "Olá"},
        )

        api.before_message_response = lambda: orchestrator.store.record_provider_event(
            delivery_id="delivery-before-accept",
            event_id="event-before-accept",
            provider="acelerachat",
            event_name="message.updated",
            resource_type="Message",
            resource_id="901",
            resource_sequence=2,
            resource_version="v2",
            occurred_at="2026-08-18T12:01:00Z",
            received_at=time.time(),
            next_state="COMPLETED",
            result={"status": "delivered", "provider": "acelerachat"},
            summary="Entrega confirmada.",
            error_code=None,
        )
        completed = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert completed["state"] == "COMPLETED"
        assert completed["status"] == "completed"
        assert completed["result"]["status"] == "delivered"
        assert completed["result"]["references"]["message"].startswith("war_")
        events = orchestrator.events.after(0, 100)
        assert events[-1]["event_type"] == "dispatch_completed"
    finally:
        orchestrator.close()


def test_email_search_returns_opaque_references_and_reply_requires_approval(
    tmp_path: Path,
) -> None:
    api = ApiDouble()
    orchestrator = _orchestrator(tmp_path, api)
    try:
        session = orchestrator.create_session(project_key="D:/project")
        search = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-email-search",
            tool_name="email_search_messages",
            arguments={"query": "Marta", "limit": 5},
        )

        assert search["state"] == "COMPLETED"
        item = search["result"]["data"]["messages"][0]
        assert item["message_ref"].startswith("emr_")
        assert item["conversation_ref"].startswith("emr_")
        assert "id" not in item

        pending = orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="fc-email-reply",
            tool_name="email_reply_conversation",
            arguments={
                "conversation_ref": item["conversation_ref"],
                "body": "Resposta aprovada",
                "to": ["marta@example.test"],
            },
        )

        assert pending["state"] == "AWAITING_APPROVAL"
        assert pending["preview"]["target"] == "Marta"
        assert api.posts == []

        accepted = orchestrator.decide(
            action_id=pending["action_id"],
            session_id=session["session_id"],
            payload_hash=pending["payload_hash"],
            decision="approve",
        )

        assert accepted["status"] == "accepted"
        assert len(api.posts) == 1
        payload = api.posts[0].read().decode("utf-8")
        assert '"content":"Resposta aprovada"' in payload
        assert '"to_emails":"marta@example.test"' in payload
        assert api.posts[0].headers["Idempotency-Key"] == (
            f"jarvis:{pending['action_id']}"
        )
    finally:
        orchestrator.close()


@pytest.mark.parametrize(
    "base_url",
    (
        "http://acelerachat.test/api/v1/openjarvis",
        "https://user:secret@acelerachat.test/api/v1/openjarvis",
        "https://acelerachat.test/api/v1/openjarvis?token=secret",
    ),
)
def test_private_config_rejects_unsafe_base_urls(base_url: str) -> None:
    config = AceleraChatConfig.from_env(
        {
            "ACELERACHAT_BASE_URL": base_url,
            "ACELERACHAT_BEARER_TOKEN": "configured",
        }
    )

    assert config.api_enabled is False
    assert config.error == "invalid_private_configuration"


def test_client_stops_streaming_responses_above_the_safe_limit() -> None:
    config = AceleraChatConfig(
        base_url="https://acelerachat.test/api/v1/openjarvis",
        bearer_token="configured",
        max_response_bytes=32,
    )
    client = AceleraChatClient(
        config,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(b"x" * 64))
        ),
    )
    try:
        with pytest.raises(JarvisAgentError) as captured:
            client.list_inboxes()
    finally:
        client.close()

    assert captured.value.code == "PROVIDER_RESPONSE_INVALID"
