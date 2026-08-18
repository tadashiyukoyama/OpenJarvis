from __future__ import annotations

from openjarvis.channels.whatsapp_store import WhatsAppStore


def test_store_resolves_contacts_and_preserves_chat_history(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    store.upsert_contact(
        {
            "jid": "5511999999999@s.whatsapp.net",
            "name": "Márcia Silva",
            "notify_name": "Marcia",
            "updated_at": 10,
        }
    )
    store.upsert_chat(
        {
            "jid": "5511999999999@s.whatsapp.net",
            "name": "Márcia Silva",
            "updated_at": 10,
        }
    )
    store.upsert_message(
        {
            "jid": "5511999999999@s.whatsapp.net",
            "sender": "5511999999999@s.whatsapp.net",
            "message_id": "m1",
            "text": "A reunião ficou para amanhã",
            "message_type": "text",
            "message_at": 20,
            "updated_at": 20,
        }
    )

    contacts = store.search_contacts("marcia")
    assert contacts[0]["jid"] == "5511999999999@s.whatsapp.net"
    assert contacts[0]["display_name"] == "Márcia Silva"

    chats = store.search_chats("silva")
    assert chats[0]["last_message_id"] == "m1"

    messages = store.list_messages("5511999999999@s.whatsapp.net", query="reunião")
    assert messages[0]["text"] == "A reunião ficou para amanhã"
    summary = store.summary("5511999999999@s.whatsapp.net")
    assert summary["message_count"] == 1
    assert summary["participants"] == ["5511999999999@s.whatsapp.net"]
    store.close()


def test_store_upsert_is_idempotent_and_deletes_chat(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    payload = {
        "jid": "12345@g.us",
        "name": "Projeto",
        "is_group": True,
        "updated_at": 1,
    }
    store.upsert_chat(payload)
    store.upsert_chat(payload)
    assert len(store.search_chats()) == 1
    store.delete_chat("12345@g.us")
    assert store.search_chats() == []
    store.close()


def test_contact_search_filters_the_complete_index_before_limiting(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    for index in range(650):
        store.upsert_contact(
            {
                "jid": f"55{index:011d}@s.whatsapp.net",
                "name": f"Contato {index:04d}",
                "updated_at": index,
            }
        )
    store.upsert_contact(
        {
            "jid": "5511990000000@s.whatsapp.net",
            "name": "Klaus Consultor",
            "updated_at": 700,
        }
    )

    matches = store.search_contacts("klaus", limit=5)

    assert [item["display_name"] for item in matches] == ["Klaus Consultor"]
    store.close()


def test_phone_search_never_matches_a_group_prefix(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    phone_jid = "5511987654321@s.whatsapp.net"
    store.upsert_contact({"jid": phone_jid, "name": "Pessoa"})
    store.upsert_chat({"jid": phone_jid, "name": "Pessoa"})
    store.upsert_chat(
        {
            "jid": "5511987654321-1234567890@g.us",
            "name": "Grupo com prefixo numerico",
            "is_group": True,
        }
    )

    matches = store.search_chats("+55 (11) 98765-4321")

    assert [item["jid"] for item in matches] == [phone_jid]
    assert matches[0]["jid_kind"] == "phone"
    store.close()


def test_lid_contact_maps_name_and_phone_to_the_same_chat(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    lid_jid = "123456789012345@lid"
    phone_jid = "5511912345678@s.whatsapp.net"
    store.upsert_contact(
        {
            "jid": lid_jid,
            "lid_jid": lid_jid,
            "phone_jid": phone_jid,
            "name": "Vo Selma",
        }
    )
    store.upsert_chat({"jid": lid_jid})

    by_name = store.search_chats("vó selma")
    by_phone = store.search_chats("5511912345678")

    assert by_name[0]["jid"] == lid_jid
    assert by_phone[0]["jid"] == lid_jid
    assert by_name[0]["display_name"] == "Vo Selma"
    assert by_name[0]["jid_kind"] == "lid"
    store.close()


def test_message_reference_is_opaque_stable_and_resolves_full_key(tmp_path):
    store = WhatsAppStore(tmp_path / "whatsapp.db")
    payload = {
        "jid": "12345-67890@g.us",
        "remote_jid_alt": "987654321012345@lid",
        "participant": "5511999999999@s.whatsapp.net",
        "participant_alt": "112233445566778@lid",
        "message_id": "MSG-1",
        "text": "Mensagem do grupo",
        "from_me": False,
        "message_at": 10,
        "updated_at": 10,
    }
    store.upsert_message(payload)
    first = store.list_messages(payload["jid"])[0]
    store.upsert_message({**payload, "updated_at": 20})
    second = store.list_messages(payload["jid"])[0]

    assert first["message_ref"].startswith("wam_")
    assert first["message_ref"] == second["message_ref"]
    assert payload["message_id"] not in first["message_ref"]
    resolved = store.get_message_by_ref(first["message_ref"])
    assert resolved is not None
    assert resolved["participant"] == payload["participant"]
    assert resolved["participant_alt"] == payload["participant_alt"]
    assert resolved["remote_jid_alt"] == payload["remote_jid_alt"]
    store.close()
