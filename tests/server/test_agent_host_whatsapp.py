from __future__ import annotations

import hashlib
import hmac
import json

from openjarvis.channels._stubs import ChannelMessage
from openjarvis.channels.whatsapp.store import WhatsAppStore
from openjarvis.server.whatsapp_agent_host import (
    AgentHostChannelClient,
    WhatsAppAgentHostGateway,
    WhatsAppAgentHostIngress,
    conversation_id_for_jid,
    principal_id_for_jid,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return b'{"status":"accepted"}'


def test_channel_callback_uses_canonical_agent_host_secret(monkeypatch):
    """The callback signs with the Host secret, never the opaque-ID secret."""

    shared = "s" * 48
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", shared)
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_ID_SECRET", "i" * 48)
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("openjarvis.server.whatsapp_agent_host.urlopen", fake_urlopen)
    client = AgentHostChannelClient()
    payload = {
        "channel": "whatsapp_baileys",
        "principal_id": "owner",
        "conversation_id": "wa:" + "a" * 32,
        "message": "synthetic callback",
        "idempotency_key": "callback-test-1",
        "attachments": [],
    }
    result = client.submit(payload)

    assert result == {"status": "accepted"}
    request = captured["request"]
    body = request.data
    timestamp = request.headers["X-agent-timestamp"]
    canonical = "\n".join(
        (
            timestamp,
            "POST",
            "/v1/agent-host/channel-events",
            hashlib.sha256(body).hexdigest(),
        )
    ).encode()
    expected = hmac.new(shared.encode(), canonical, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(request.headers["X-agent-signature"], expected)
    assert json.loads(body)["idempotency_key"] == "callback-test-1"


class _Channel:
    def __init__(self, store: WhatsAppStore) -> None:
        self._store = store
        self.handlers = []
        self.sent = []
        self.sent_media = []

    def on_message(self, handler):
        self.handlers.append(handler)

    def status_snapshot(self):
        return {"status": "connected"}

    def send_and_wait(self, jid, text, *, conversation_id, timeout):
        self.sent.append((jid, text, conversation_id))
        return {"message_id": "provider-message"}

    def send_media_and_wait(
        self,
        jid,
        file_path,
        *,
        mime_type,
        filename,
        caption,
        voice_note,
        conversation_id,
        timeout,
    ):
        self.sent_media.append(
            (jid, file_path, mime_type, filename, caption, voice_note, conversation_id)
        )
        return {"message_id": "provider-media-message"}


def test_opaque_refs_and_owner_mapping(monkeypatch):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_OWNER_JID", "5511999999999@s.whatsapp.net")
    ref = conversation_id_for_jid("5511999999999@s.whatsapp.net")
    assert ref.startswith("wa:") and len(ref) == 35
    assert "5511999999999" not in ref
    assert principal_id_for_jid("5511999999999@s.whatsapp.net") == "owner"
    assert principal_id_for_jid("5511888888888@s.whatsapp.net").startswith("whatsapp:")


def test_gateway_idempotency_and_external_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_OWNER_JID", "5511999999999@s.whatsapp.net")
    monkeypatch.setenv(
        "OPENJARVIS_WHATSAPP_ALLOWED_JIDS", "5511999999999@s.whatsapp.net"
    )
    monkeypatch.setenv("AGENT_HOST_WHATSAPP_EXTERNAL", "1")
    store = WhatsAppStore(tmp_path / "wa.db")
    channel = _Channel(store)
    ref = conversation_id_for_jid("5511999999999@s.whatsapp.net")
    store.bind_agent_host_conversation(ref, "5511999999999@s.whatsapp.net", "owner")
    gateway = WhatsAppAgentHostGateway(channel)
    first = gateway.send_message(
        {"conversation_id": ref, "text": "oi", "idempotency_key": "k1"}, {}
    )
    second = gateway.send_message(
        {"conversation_id": ref, "text": "oi", "idempotency_key": "k1"}, {}
    )
    assert first["status"] == "completed"
    assert second["data"]["idempotent_replay"] is True
    assert len(channel.sent) == 1
    monkeypatch.setenv("AGENT_HOST_WHATSAPP_EXTERNAL", "0")
    blocked = gateway.send_message(
        {"conversation_id": ref, "text": "novo", "idempotency_key": "k2"}, {}
    )
    assert blocked["status"] == "blocked"
    store.close()


def test_group_ingress_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    store = WhatsAppStore(tmp_path / "wa.db")
    channel = _Channel(store)
    ingress = WhatsAppAgentHostIngress(channel)
    submitted = []
    ingress.client.submit = lambda payload: (
        submitted.append(payload) or {"status": "accepted"}
    )
    ingress(ChannelMessage("whatsapp_baileys", "x@g.us", "group", "m1", "123@g.us"))
    assert submitted == []
    store.close()


def test_media_gateway_validates_artifact_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_OWNER_JID", "5511999999999@s.whatsapp.net")
    monkeypatch.setenv(
        "OPENJARVIS_WHATSAPP_ALLOWED_JIDS", "5511999999999@s.whatsapp.net"
    )
    monkeypatch.setenv("AGENT_HOST_WHATSAPP_EXTERNAL", "1")
    artifact_root = tmp_path / "registry"
    artifact_root.mkdir()
    artifact = artifact_root / "art-12345678-1234-1234-1234-123456789abc-report.pdf"
    artifact.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setenv("OPENJARVIS_ARTIFACT_ROOT", str(artifact_root))
    store = WhatsAppStore(tmp_path / "wa.db")
    channel = _Channel(store)
    ref = conversation_id_for_jid("5511999999999@s.whatsapp.net")
    store.bind_agent_host_conversation(ref, "5511999999999@s.whatsapp.net", "owner")
    gateway = WhatsAppAgentHostGateway(channel)
    arguments = {
        "conversation_id": ref,
        "artifact_id": "art-12345678-1234-1234-1234-123456789abc",
        "artifact_path": str(artifact),
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "idempotency_key": "media-k1",
    }
    first = gateway.send_media(arguments, {})
    second = gateway.send_media(arguments, {})
    assert first["status"] == "completed"
    assert first["data"]["artifact_id"] == arguments["artifact_id"]
    assert second["data"]["idempotent_replay"] is True
    assert len(channel.sent_media) == 1
    store.close()


def test_audio_media_gateway_marks_voice_note_and_replays_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    monkeypatch.setenv("OPENJARVIS_WHATSAPP_OWNER_JID", "5511999999999@s.whatsapp.net")
    monkeypatch.setenv(
        "OPENJARVIS_WHATSAPP_ALLOWED_JIDS", "5511999999999@s.whatsapp.net"
    )
    monkeypatch.setenv("AGENT_HOST_WHATSAPP_EXTERNAL", "1")
    artifact_root = tmp_path / "registry"
    artifact_root.mkdir()
    artifact = artifact_root / "art-12345678-1234-1234-1234-123456789abc-note.ogg"
    artifact.write_bytes(b"OggS" + b"\x00" * 16)
    monkeypatch.setenv("OPENJARVIS_ARTIFACT_ROOT", str(artifact_root))
    store = WhatsAppStore(tmp_path / "wa.db")
    channel = _Channel(store)
    ref = conversation_id_for_jid("5511999999999@s.whatsapp.net")
    store.bind_agent_host_conversation(ref, "5511999999999@s.whatsapp.net", "owner")
    gateway = WhatsAppAgentHostGateway(channel)
    arguments = {
        "conversation_id": ref,
        "artifact_id": "art-12345678-1234-1234-1234-123456789abc",
        "artifact_path": str(artifact),
        "filename": "note.ogg",
        "mime_type": "audio/ogg",
        "size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "idempotency_key": "audio-k1",
        "voice_note": True,
    }
    first = gateway.send_media(arguments, {})
    second = gateway.send_media(arguments, {})
    assert first["status"] == "completed"
    assert first["data"]["voice_note"] is True
    assert second["data"]["idempotent_replay"] is True
    assert len(channel.sent_media) == 1
    assert channel.sent_media[0][5] is True
    store.close()


def test_outbound_operation_lookup_is_read_only_and_supports_both_selectors(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AGENT_HOST_SHARED_SECRET", "s" * 48)
    store = WhatsAppStore(tmp_path / "wa.db")
    channel = _Channel(store)
    gateway = WhatsAppAgentHostGateway(channel)
    stored = {
        "status": "completed",
        "operation_id": "wa-op-reconcile",
        "data": {"remote_message_id": "remote-1"},
    }
    store.save_agent_host_outbound("reconcile-key", "wa-op-reconcile", stored)

    by_key = gateway.get_outbound_operation(idempotency_key="reconcile-key")
    by_operation = gateway.get_outbound_operation(operation_id="wa-op-reconcile")
    missing = gateway.get_outbound_operation(operation_id="missing")

    assert by_key["status"] == "completed"
    assert by_key["data"]["remote_message_id"] == "remote-1"
    assert by_operation == by_key
    assert missing["status"] == "not_found"
    assert channel.sent_media == []
    assert channel.sent == []
    store.close()
