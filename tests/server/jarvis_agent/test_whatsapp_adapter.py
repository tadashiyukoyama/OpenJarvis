from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.whatsapp import WhatsAppAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class _Channel:
    def __init__(self, status="connected"):
        self.public_status = status
        self.commands = []

    def status_snapshot(self):
        return {
            "status": self.public_status,
            "send_available": self.public_status == "connected",
        }

    def search_contacts(self, query="", limit=20):
        return [
            {
                "jid": "5511999999999@s.whatsapp.net",
                "display_name": "Klaus Consultor",
                "verified_name": "Klaus",
            }
        ][:limit]

    def search_chats(self, query="", limit=20):
        return [
            {
                "jid": "5511999999999@s.whatsapp.net",
                "display_name": "Klaus Consultor",
                "is_group": False,
                "unread_count": 1,
                "last_message_at": 10,
            }
        ][:limit]

    def list_messages(self, jid, *, query="", limit=50):
        return [
            {
                "message_ref": "wam_0123456789abcdefghijklmn",
                "message_id": "provider-message-id",
                "jid": jid,
                "sender": "provider-sender-jid",
                "text": "Olá",
                "from_me": False,
                "message_at": 10,
            }
        ]

    def conversation_summary(self, jid, *, limit=50):
        return {"message_count": 1, "messages": self.list_messages(jid)}

    def resolve_message_reference(self, reference):
        return {
            "message_ref": reference,
            "message_id": "provider-message-id",
            "jid": "5511999999999@s.whatsapp.net",
            "text": "Olá",
            "from_me": False,
            "participant": "",
        }

    def execute_action_and_wait(self, command, timeout=20.0):
        self.commands.append(command)
        return {"id": "internal", "remoteJid": command.get("jid", "")}

    def react_to_message(self, message_ref, reaction, timeout=20.0):
        self.commands.append({"message_ref": message_ref, "reaction": reaction})
        return {"message_id": "internal"}

    def mark_read(self, jid, message_ids):
        self.commands.append({"jid": jid, "message_ids": message_ids})
        return True


@pytest.fixture
def context():
    return AdapterContext("s1", "D:/project", "t1", "partition", "request")


def _adapter(tmp_path: Path, channel: _Channel) -> WhatsAppAdapter:
    store = JarvisAgentStore(tmp_path / "agent.sqlite3")
    return WhatsAppAdapter(ReferenceService(store), lambda: channel)


def test_contact_and_chat_reads_never_expose_jids(
    tmp_path: Path, context: AdapterContext
) -> None:
    adapter = _adapter(tmp_path, _Channel())
    contacts = adapter.execute(
        "whatsapp.search_contacts", {"query": "Klaus", "limit": 10}, context
    )
    chats = adapter.execute(
        "whatsapp.search_chats", {"query": "Klaus", "limit": 10}, context
    )

    assert contacts.data["contacts"][0]["contact_ref"].startswith("war_")
    assert chats.data["chats"][0]["chat_ref"].startswith("war_")
    assert "@s.whatsapp.net" not in str(contacts.as_dict())
    assert "@s.whatsapp.net" not in str(chats.as_dict())


def test_send_by_name_resolves_server_side_and_preserves_preview(
    tmp_path: Path, context: AdapterContext
) -> None:
    channel = _Channel()
    adapter = _adapter(tmp_path, channel)
    prepared = adapter.prepare(
        "whatsapp.send_text",
        {"contact_name": "Klaus Consultor", "text": "Olá, tudo bem?"},
        context,
    )

    assert prepared.preview["destination"] == "Klaus Consultor"
    assert "jid" not in prepared.preview
    assert prepared.arguments["jid"].endswith("@s.whatsapp.net")

    result = adapter.execute("whatsapp.send_text", prepared.arguments, context)
    assert result.status == "completed"
    assert len(channel.commands) == 1


def test_disconnected_provider_has_reads_but_no_mutations(
    tmp_path: Path, context: AdapterContext
) -> None:
    adapter = _adapter(tmp_path, _Channel("logged_out"))
    provider = adapter.provider_capabilities()["whatsapp_baileys"]

    assert "whatsapp.contacts" in provider.capabilities
    assert "whatsapp.send" not in provider.capabilities
    with pytest.raises(JarvisAgentError) as error:
        adapter.prepare(
            "whatsapp.send_text",
            {"contact_name": "Klaus", "text": "hello"},
            context,
        )
    assert error.value.code == "PROVIDER_LOGGED_OUT"


def test_reaction_uses_only_opaque_message_reference(
    tmp_path: Path, context: AdapterContext
) -> None:
    channel = _Channel()
    adapter = _adapter(tmp_path, channel)
    prepared = adapter.prepare(
        "whatsapp.react",
        {
            "message_ref": "wam_0123456789abcdefghijklmn",
            "reaction": "👍",
        },
        context,
    )

    assert prepared.arguments == {
        "message_ref": "wam_0123456789abcdefghijklmn",
        "reaction": "👍",
    }
    assert "@s.whatsapp.net" not in str(prepared.preview)


def _chat_ref(adapter: WhatsAppAdapter, context: AdapterContext) -> str:
    result = adapter.execute(
        "whatsapp.search_chats", {"query": "Klaus", "limit": 10}, context
    )
    return result.data["chats"][0]["chat_ref"]


def test_all_whatsapp_reads_use_bounded_public_data(
    tmp_path: Path, context: AdapterContext
) -> None:
    adapter = _adapter(tmp_path, _Channel())
    chat_ref = _chat_ref(adapter, context)
    cases = (
        ("whatsapp.status", {}),
        ("whatsapp.search_contacts", {"query": "Klaus", "limit": 10}),
        ("whatsapp.search_chats", {"query": "Klaus", "limit": 10}),
        ("whatsapp.read_conversation", {"chat_ref": chat_ref, "limit": 10}),
        ("whatsapp.summarize_conversation", {"chat_ref": chat_ref, "limit": 10}),
        ("whatsapp.group_metadata", {"chat_ref": chat_ref}),
        ("whatsapp.privacy_read", {}),
    )

    for tool_id, arguments in cases:
        result = adapter.execute(tool_id, arguments, context)
        assert result.status == "completed", tool_id
        serialized = str(result.as_dict())
        assert "@s.whatsapp.net" not in serialized, tool_id
        assert "provider-message-id" not in serialized, tool_id


def test_all_whatsapp_mutations_prepare_exact_preview_and_execute_once(
    tmp_path: Path, context: AdapterContext
) -> None:
    channel = _Channel()
    adapter = _adapter(tmp_path, channel)
    chat_ref = _chat_ref(adapter, context)
    message_ref = "wam_0123456789abcdefghijklmn"
    cases = (
        ("whatsapp.send_text", {"contact_name": "Klaus Consultor", "text": "Olá"}),
        ("whatsapp.reply", {"message_ref": message_ref, "text": "Resposta"}),
        ("whatsapp.react", {"message_ref": message_ref, "reaction": "👍"}),
        (
            "whatsapp.mark_read",
            {"chat_ref": chat_ref, "message_refs": [message_ref]},
        ),
        (
            "whatsapp.send_media",
            {
                "contact_name": "Klaus Consultor",
                "media_type": "image",
                "url": "https://example.test/image.png",
                "caption": "Imagem",
            },
        ),
        (
            "whatsapp.poll",
            {
                "contact_name": "Klaus Consultor",
                "question": "Escolha",
                "options": ["A", "B"],
            },
        ),
        ("whatsapp.archive", {"chat_ref": chat_ref, "enabled": True}),
        ("whatsapp.pin", {"chat_ref": chat_ref, "enabled": True}),
        ("whatsapp.mute", {"chat_ref": chat_ref, "enabled": True}),
        (
            "whatsapp.group_create",
            {"subject": "Grupo", "contact_names": ["Klaus Consultor"]},
        ),
        ("whatsapp.group_subject", {"chat_ref": chat_ref, "subject": "Novo"}),
        (
            "whatsapp.privacy_update",
            {"setting": "last_seen", "value": "contacts"},
        ),
        ("whatsapp.profile_status", {"text": "Disponível"}),
        ("whatsapp.broadcast", {"text": "Atualização", "audience_refs": [chat_ref]}),
    )

    for tool_id, arguments in cases:
        before = len(channel.commands)
        prepared = adapter.prepare(tool_id, arguments, context)
        assert prepared.preview.get("risk"), tool_id
        assert "@s.whatsapp.net" not in str(prepared.preview), tool_id
        result = adapter.execute(tool_id, prepared.arguments, context)
        assert result.status == "completed", tool_id
        assert len(channel.commands) == before + 1, tool_id


class _AmbiguousChannel(_Channel):
    def search_contacts(self, query="", limit=20):
        return [
            {"jid": "5511000000001@s.whatsapp.net", "display_name": "Klaus"},
            {"jid": "5511000000002@s.whatsapp.net", "display_name": "Klaus"},
        ][:limit]


def test_ambiguous_contact_returns_opaque_choices_without_dispatch(
    tmp_path: Path, context: AdapterContext
) -> None:
    channel = _AmbiguousChannel()
    adapter = _adapter(tmp_path, channel)

    with pytest.raises(JarvisAgentError) as error:
        adapter.prepare(
            "whatsapp.send_text",
            {"contact_name": "Klaus", "text": "Não enviar"},
            context,
        )

    assert error.value.code == "INVALID_REQUEST"
    assert error.value.details["choices"]
    assert "@s.whatsapp.net" not in str(error.value.details)
    assert channel.commands == []
