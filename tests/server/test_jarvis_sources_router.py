from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.jarvis_sources_router import router


class _Gmail:
    def is_connected(self):
        return True

    def search_messages(self, query, max_results):
        return [{"id": "m1", "subject": query, "body": "bounded"}][:max_results]

    def read_message(self, message_id):
        return {"id": message_id, "body": "hello"}

    def send_message(self, **kwargs):
        return {"id": "sent-1"}

    def archive_message(self, message_id):
        self.archived = message_id

    def delete_message(self, message_id):
        self.trashed = message_id


class _DisconnectedGmail:
    connector_id = "gmail"

    def is_connected(self):
        return False


class _ImapGmail:
    connector_id = "gmail_imap"
    display_name = "Gmail (IMAP)"

    def is_connected(self):
        return True

    def search_messages(self, query, max_results):
        return [{"id": "7", "subject": query}][:max_results]

    def read_message(self, message_id):
        return {"id": message_id, "body": "from synchronized source"}


class _WhatsApp:
    def __init__(self):
        self.sent = None
        self.reset_calls = 0
        self._last_qr = "qr-challenge"
        self.contacts = [
            {
                "jid": "5511999999999@s.whatsapp.net",
                "name": "Marta",
                "display_name": "Marta",
            }
        ]
        self.chats = [{"jid": "5511999999999@s.whatsapp.net", "name": "Marta"}]
        self.messages = [
            {
                "message_id": "m1",
                "jid": "5511999999999@s.whatsapp.net",
                "sender": "5511999999999@s.whatsapp.net",
                "text": "Olá",
            }
        ]

    class _Status:
        value = "connected"

    def status(self):
        return self._Status()

    def connect(self):
        return None

    def reset_auth_state(self):
        self.reset_calls += 1

    def send(self, jid, text):
        self.sent = (jid, text)
        return True

    def search_contacts(self, query="", limit=20):
        return self.contacts[:limit]

    def search_chats(self, query="", limit=20):
        return self.chats[:limit]

    def list_messages(self, jid, *, query="", limit=50):
        return self.messages[:limit]

    def conversation_summary(self, jid, *, limit=50):
        return {"jid": jid, "message_count": 1, "messages": self.messages[:limit]}

    def request_history(self, jid, *, limit=50):
        return True

    def mark_read(self, jid, message_ids=None):
        self.read = (jid, message_ids or [])
        return True

    def execute_action(self, action):
        self.action = action
        return True

    def reaction_preview(self, message_ref, reaction):
        if message_ref != "wam_0123456789abcdefghijklmn":
            raise ValueError("Referencia de mensagem WhatsApp invalida ou expirada")
        return {
            "message_ref": message_ref,
            "jid": "12345-67890@g.us",
            "reaction": reaction,
            "message_preview": "Mensagem de teste",
            "message_at": 10,
        }

    def react_to_message(self, message_ref, reaction, *, timeout=15.0):
        self.reaction = (message_ref, reaction, timeout)
        return {"type": "command_ok", "message_id": "m1"}


def _client():
    app = FastAPI()
    app.include_router(router)
    app.state.jarvis_gmail_connector = _Gmail()
    app.state.jarvis_whatsapp_channel = _WhatsApp()
    return app, TestClient(app)


def test_whatsapp_reset_requires_confirmation_and_restarts_channel():
    app, client = _client()

    rejected = client.post(
        "/v1/jarvis/sources/whatsapp/reset",
        json={"confirm": False},
    )
    accepted = client.post(
        "/v1/jarvis/sources/whatsapp/reset",
        json={"confirm": True},
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert app.state.jarvis_whatsapp_channel.reset_calls == 1


def test_gmail_read_and_search_are_bounded_and_token_free():
    _, client = _client()

    response = client.post(
        "/v1/jarvis/sources/gmail/search",
        json={"query": "from:cesar", "max_results": 25},
    )
    assert response.status_code == 200
    assert response.json()["messages"][0]["subject"] == "from:cesar"
    assert "token" not in response.text.lower()

    response = client.post("/v1/jarvis/sources/gmail/read", json={"message_id": "m1"})
    assert response.status_code == 200
    assert response.json()["message"]["id"] == "m1"


def test_gmail_resolves_connected_imap_data_source_when_oauth_is_disconnected():
    app = FastAPI()
    app.include_router(router)
    with (
        patch(
            "openjarvis.connectors.gmail.GmailConnector",
            return_value=_DisconnectedGmail(),
        ),
        patch(
            "openjarvis.connectors.gmail_imap.GmailIMAPConnector",
            return_value=_ImapGmail(),
        ),
    ):
        client = TestClient(app)
        status = client.get("/v1/jarvis/sources/gmail/status")
        assert status.status_code == 200
        assert status.json()["connector_id"] == "gmail_imap"
        assert status.json()["capabilities"] == ["search", "read"]

        response = client.post(
            "/v1/jarvis/sources/gmail/search",
            json={"query": "from:Marta inova-ts.com.br", "max_results": 10},
        )
        assert response.status_code == 200
        assert response.json()["messages"][0]["id"] == "7"


def test_gmail_imap_source_refuses_oauth_mutations_explicitly():
    app = FastAPI()
    app.include_router(router)
    app.state.jarvis_gmail_connector = _ImapGmail()
    client = TestClient(app)
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "gmail_send_email"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/gmail/send",
        headers={"X-Jarvis-Approval": approval},
        json={"to": "person@example.com", "subject": "x", "body": "y"},
    )
    assert response.status_code == 501
    assert "OAuth" in response.json()["detail"]


def test_gmail_mutations_are_separate_endpoints():
    app, client = _client()
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "gmail_archive_email"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/gmail/archive",
        headers={"X-Jarvis-Approval": approval},
        json={"message_id": "m1"},
    )
    assert response.status_code == 200
    assert app.state.jarvis_gmail_connector.archived == "m1"

    missing = client.post("/v1/jarvis/sources/gmail/trash", json={"message_id": "m1"})
    assert missing.status_code == 403
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "gmail_trash_email"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/gmail/trash",
        headers={"X-Jarvis-Approval": approval},
        json={"message_id": "m1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "trashed"

    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "gmail_trash_email"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/gmail/trash",
        headers={"X-Jarvis-Approval": approval},
        json={"message_id": "../secret"},
    )
    assert response.status_code == 400


def test_whatsapp_status_qr_and_send_do_not_expose_auth_state():
    app, client = _client()
    response = client.get("/v1/jarvis/sources/whatsapp/status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "source": "whatsapp_baileys",
        "status": "connected",
        "qr_available": True,
    }

    response = client.get("/v1/jarvis/sources/whatsapp/qr")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private, max-age=0"
    assert response.json()["qr"] == "qr-challenge"
    assert response.json()["qr_generation"] == 0
    assert response.json()["qr_issued_at"] is None

    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "whatsapp_send_message"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/whatsapp/send",
        headers={"X-Jarvis-Approval": approval},
        json={"jid": "5511999999999@s.whatsapp.net", "text": "teste"},
    )
    assert response.status_code == 200
    assert app.state.jarvis_whatsapp_channel.sent == (
        "5511999999999@s.whatsapp.net",
        "teste",
    )


def test_whatsapp_contacts_chats_history_and_summary_are_read_only():
    _, client = _client()
    contacts = client.get("/v1/jarvis/sources/whatsapp/contacts?query=Marta")
    assert contacts.status_code == 200
    assert contacts.json()["contacts"][0]["name"] == "Marta"

    chats = client.get("/v1/jarvis/sources/whatsapp/chats")
    assert chats.status_code == 200
    assert chats.json()["chats"][0]["jid"] == "5511999999999@s.whatsapp.net"

    messages = client.get(
        "/v1/jarvis/sources/whatsapp/messages",
        params={"jid": "5511999999999@s.whatsapp.net"},
    )
    assert messages.status_code == 200
    assert messages.json()["messages"][0]["text"] == "Olá"

    summary = client.get(
        "/v1/jarvis/sources/whatsapp/summary",
        params={"jid": "5511999999999@s.whatsapp.net"},
    )
    assert summary.status_code == 200
    assert summary.json()["summary"]["message_count"] == 1

    history = client.post(
        "/v1/jarvis/sources/whatsapp/history",
        json={"jid": "5511999999999@s.whatsapp.net", "limit": 10},
    )
    assert history.status_code == 200


def test_whatsapp_read_endpoints_accept_baileys_lid_jids():
    _, client = _client()
    lid = "123456789012345@lid"

    messages = client.get(
        "/v1/jarvis/sources/whatsapp/messages",
        params={"jid": lid},
    )
    summary = client.get(
        "/v1/jarvis/sources/whatsapp/summary",
        params={"jid": lid},
    )

    assert messages.status_code == 200
    assert summary.status_code == 200


def test_whatsapp_send_resolves_a_unique_contact_name():
    app, client = _client()
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "whatsapp_send_message"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/whatsapp/send",
        headers={"X-Jarvis-Approval": approval},
        json={"contact_name": "Marta", "text": "Olá Marta"},
    )
    assert response.status_code == 200
    assert response.json()["jid"] == "5511999999999@s.whatsapp.net"
    assert app.state.jarvis_whatsapp_channel.sent == (
        "5511999999999@s.whatsapp.net",
        "Olá Marta",
    )


def test_whatsapp_send_rejects_conflicting_or_missing_destination_before_approval():
    app, client = _client()
    conflicting = client.post(
        "/v1/jarvis/sources/whatsapp/send",
        json={
            "jid": "5511999999999@s.whatsapp.net",
            "contact_name": "Marta",
            "text": "nao enviar",
        },
    )
    assert conflicting.status_code == 400
    assert "nunca os dois" in conflicting.json()["detail"]

    missing = client.post(
        "/v1/jarvis/sources/whatsapp/send",
        json={"text": "sem destinatario"},
    )
    assert missing.status_code == 400
    assert app.state.jarvis_whatsapp_channel.sent is None


def test_whatsapp_mark_read_requires_one_use_approval():
    app, client = _client()
    denied = client.post(
        "/v1/jarvis/sources/whatsapp/read",
        json={"jid": "5511999999999@s.whatsapp.net"},
    )
    assert denied.status_code == 403
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "whatsapp_mark_read"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/whatsapp/read",
        headers={"X-Jarvis-Approval": approval},
        json={"jid": "5511999999999@s.whatsapp.net", "message_ids": ["m1"]},
    )
    assert response.status_code == 200
    assert app.state.jarvis_whatsapp_channel.read == (
        "5511999999999@s.whatsapp.net",
        ["m1"],
    )


def test_whatsapp_reply_is_namespaced_and_requires_approval():
    app, client = _client()
    approval = client.post(
        "/v1/jarvis/sources/approval", json={"action": "whatsapp_reply"}
    ).json()["approval_token"]
    response = client.post(
        "/v1/jarvis/sources/whatsapp/action",
        headers={"X-Jarvis-Approval": approval},
        json={
            "operation": "reply",
            "jid": "5511999999999@s.whatsapp.net",
            "message_id": "m1",
            "text": "Resposta",
        },
    )
    assert response.status_code == 200
    assert app.state.jarvis_whatsapp_channel.action["kind"] == "reply"


def test_whatsapp_reaction_uses_opaque_reference_and_real_completion():
    app, client = _client()
    reference = "wam_0123456789abcdefghijklmn"
    approval = client.post(
        "/v1/jarvis/sources/approval",
        json={"action": "whatsapp_react_message"},
    ).json()["approval_token"]

    response = client.post(
        "/v1/jarvis/sources/whatsapp/reaction",
        headers={"X-Jarvis-Approval": approval},
        json={"message_ref": reference, "reaction": "👍"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["target"]["message_ref"] == reference
    assert app.state.jarvis_whatsapp_channel.reaction == (reference, "👍", 15.0)


def test_whatsapp_reaction_preview_is_read_only_and_bounded():
    app, client = _client()
    reference = "wam_0123456789abcdefghijklmn"

    response = client.post(
        "/v1/jarvis/sources/whatsapp/reaction/preview",
        json={"message_ref": reference, "reaction": "👍"},
    )

    assert response.status_code == 200
    assert response.json()["target"] == {
        "message_ref": reference,
        "jid": "12345-67890@g.us",
        "reaction": "👍",
        "message_preview": "Mensagem de teste",
        "message_at": 10,
    }
    assert not hasattr(app.state.jarvis_whatsapp_channel, "reaction")


def test_whatsapp_reaction_validates_reference_before_consuming_approval():
    _, client = _client()
    approval = client.post(
        "/v1/jarvis/sources/approval",
        json={"action": "whatsapp_react_message"},
    ).json()["approval_token"]

    invalid = client.post(
        "/v1/jarvis/sources/whatsapp/reaction",
        headers={"X-Jarvis-Approval": approval},
        json={"message_ref": "wam_0000000000000000", "reaction": "👍"},
    )
    valid = client.post(
        "/v1/jarvis/sources/whatsapp/reaction",
        headers={"X-Jarvis-Approval": approval},
        json={
            "message_ref": "wam_0123456789abcdefghijklmn",
            "reaction": "👍",
        },
    )

    assert invalid.status_code == 409
    assert valid.status_code == 200


def test_generic_whatsapp_action_refuses_unsafe_reaction_contract():
    _, client = _client()
    response = client.post(
        "/v1/jarvis/sources/whatsapp/action",
        json={
            "operation": "reaction",
            "jid": "12345-67890@g.us",
            "message_id": "m1",
            "reaction": "👍",
        },
    )

    assert response.status_code == 400
    assert "whatsapp_react_message" in response.json()["detail"]


def test_whatsapp_voice_call_is_explicitly_not_implemented():
    _, client = _client()
    response = client.post("/v1/jarvis/sources/whatsapp/call")
    assert response.status_code == 501
    assert "WebRTC" in response.json()["detail"]
