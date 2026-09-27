"""Tests for the WhatsAppBaileysChannel adapter."""

from __future__ import annotations

import json
import threading
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelMessage, ChannelStatus
from openjarvis.channels.whatsapp_baileys import WhatsAppBaileysChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_whatsapp_baileys(tmp_path, monkeypatch):
    """Re-register after any registry clear."""
    monkeypatch.setenv("OPENJARVIS_RUNTIME_ROOT", str(tmp_path / "runtime"))
    if not ChannelRegistry.contains("whatsapp_baileys"):
        ChannelRegistry.register_value("whatsapp_baileys", WhatsAppBaileysChannel)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registry_key(self):
        assert ChannelRegistry.contains("whatsapp_baileys")

    def test_channel_id(self):
        ch = WhatsAppBaileysChannel()
        assert ch.channel_id == "whatsapp_baileys"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self):
        ch = WhatsAppBaileysChannel()
        assert ch._auth_dir == ""
        assert ch._assistant_name == "Jarvis"
        assert ch._assistant_has_own_number is False
        assert ch._status == ChannelStatus.DISCONNECTED
        assert ch._process is None
        assert ch._handlers == []

    def test_custom_params(self):
        ch = WhatsAppBaileysChannel(
            auth_dir="/tmp/auth",
            assistant_name="Bot",
            assistant_has_own_number=True,
        )
        assert ch._auth_dir == "/tmp/auth"
        assert ch._assistant_name == "Bot"
        assert ch._assistant_has_own_number is True

    def test_project_runtime_root_keeps_bridge_state_on_managed_disk(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("OPENJARVIS_RUNTIME_ROOT", str(tmp_path))

        ch = WhatsAppBaileysChannel()

        assert ch._runtime_dir == tmp_path.resolve() / "whatsapp_baileys_bridge"


# ---------------------------------------------------------------------------
# _ensure_bridge
# ---------------------------------------------------------------------------


class TestEnsureBridge:
    def test_raises_when_node_not_found(self):
        ch = WhatsAppBaileysChannel()
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Node.js is required"):
                ch._ensure_bridge()


# ---------------------------------------------------------------------------
# Connect / Disconnect lifecycle
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    def test_connect_spawns_subprocess(self, tmp_path):
        ch = WhatsAppBaileysChannel()
        ch._runtime_dir = tmp_path

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = StringIO("")
        mock_proc.stderr = MagicMock()
        mock_proc.pid = 12345

        bridge_js = tmp_path / "dist" / "bridge.js"
        bridge_js.parent.mkdir(parents=True, exist_ok=True)
        bridge_js.write_text("// bridge")

        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch("subprocess.run"),  # npm install
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch(
                "openjarvis.channels.whatsapp_baileys._BRIDGE_SRC",
                tmp_path / "source-without-prebuilt-dependencies",
            ),
        ):
            # Pretend node_modules already exists to skip npm install.
            (tmp_path / "node_modules").mkdir()
            ch.connect()

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            assert "node" in call_args[0][0][0]
            assert str(bridge_js) in call_args[0][0][1]
            assert call_args.kwargs["encoding"] == "utf-8"
            assert call_args.kwargs["errors"] == "strict"

        # Cleanup.
        ch._stop_event.set()
        ch._process = None

    def test_connect_reuses_prebuilt_workspace_bridge_without_install(self, tmp_path):
        source = tmp_path / "source"
        bridge_js = source / "dist" / "bridge.js"
        bridge_js.parent.mkdir(parents=True)
        bridge_js.write_text("// prebuilt")
        (source / "node_modules").mkdir()
        ch = WhatsAppBaileysChannel()
        ch._runtime_dir = tmp_path / "runtime"

        with (
            patch("shutil.which", return_value="/usr/bin/node"),
            patch("subprocess.run") as install,
            patch(
                "openjarvis.channels.whatsapp_baileys._BRIDGE_SRC",
                source,
            ),
        ):
            resolved = ch._ensure_bridge()

        assert resolved == bridge_js
        install.assert_not_called()

    def test_connect_sets_error_when_node_missing(self):
        ch = WhatsAppBaileysChannel()
        with patch("shutil.which", return_value=None):
            ch.connect()
            assert ch.status() == ChannelStatus.ERROR

    def test_disconnect_terminates_process(self):
        ch = WhatsAppBaileysChannel()
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        ch._process = mock_proc
        ch._status = ChannelStatus.CONNECTED

        ch.disconnect()

        mock_proc.terminate.assert_called_once()
        assert ch.status() == ChannelStatus.DISCONNECTED
        assert ch._process is None

    def test_disconnect_when_not_connected(self):
        ch = WhatsAppBaileysChannel()
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_reset_auth_state_quarantines_only_managed_runtime_auth(self, tmp_path):
        ch = WhatsAppBaileysChannel()
        ch._runtime_dir = tmp_path / "runtime"
        auth = ch._runtime_dir / "auth"
        auth.mkdir(parents=True)
        marker = auth / "managed-test-state.json"
        marker.write_text("{}")

        ch.reset_auth_state()

        assert not auth.exists()
        quarantines = list((ch._runtime_dir / "auth-quarantine").glob("auth-*"))
        assert len(quarantines) == 1
        assert (quarantines[0] / marker.name).read_text() == "{}"
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_reset_auth_state_refuses_runtime_root(self, tmp_path):
        ch = WhatsAppBaileysChannel(auth_dir=str(tmp_path / "runtime"))
        ch._runtime_dir = tmp_path / "runtime"
        ch._runtime_dir.mkdir(exist_ok=True)

        with pytest.raises(RuntimeError, match="raiz do runtime"):
            ch.reset_auth_state()

        assert ch._runtime_dir.exists()

    def test_reset_auth_state_refuses_external_custom_directory(self, tmp_path):
        external_auth = tmp_path / "external-auth"
        external_auth.mkdir()
        marker = external_auth / "preserve.json"
        marker.write_text("{}")
        ch = WhatsAppBaileysChannel(auth_dir=str(external_auth))
        ch._runtime_dir = tmp_path / "runtime"

        with pytest.raises(RuntimeError, match="preservação automática"):
            ch.reset_auth_state()

        assert marker.exists()


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


class TestSend:
    def test_send_writes_json_to_stdin(self):
        ch = WhatsAppBaileysChannel()
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        ch._process = mock_proc
        ch._status = ChannelStatus.CONNECTED

        result = ch.send("123456@s.whatsapp.net", "Hello!")
        assert result is True

        written = mock_proc.stdin.write.call_args[0][0]
        payload = json.loads(written.strip())
        assert payload["type"] == "send"
        assert payload["jid"] == "123456@s.whatsapp.net"
        assert payload["text"] == "Hello!"

    def test_send_fails_when_not_connected(self):
        ch = WhatsAppBaileysChannel()
        result = ch.send("123456@s.whatsapp.net", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = WhatsAppBaileysChannel(bus=bus)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        ch._process = mock_proc
        ch._status = ChannelStatus.CONNECTED

        ch.send("123@s.whatsapp.net", "Hi!")
        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestSendMedia:
    @pytest.mark.parametrize(
        ("mime_type", "expected_kind", "voice_note"),
        [
            ("application/pdf", "document", False),
            (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "document",
                False,
            ),
            ("image/png", "image", False),
            ("image/jpeg", "image", False),
            ("audio/ogg", "audio", True),
        ],
    )
    def test_media_maps_mime_to_baileys_kind_and_preserves_metadata(
        self, tmp_path, mime_type, expected_kind, voice_note, monkeypatch
    ):
        root = tmp_path / "registry"
        root.mkdir()
        artifact = root / "sample.bin"
        artifact.write_bytes(b"media fixture")
        monkeypatch.setenv("OPENJARVIS_ARTIFACT_ROOT", str(root))

        ch = WhatsAppBaileysChannel()
        ch._status = ChannelStatus.CONNECTED
        ch._process = MagicMock()
        captured = {}

        def _send(command, *, timeout):
            captured.update(command)
            return {"message_id": "provider-1"}

        ch.execute_action_and_wait = _send
        result = ch.send_media_and_wait(
            "5511999999999@s.whatsapp.net",
            str(artifact),
            mime_type=mime_type,
            filename="documento original.bin",
            voice_note=voice_note,
        )

        assert result["message_id"] == "provider-1"
        assert captured["mediaType"] == expected_kind
        assert captured["mimetype"] == mime_type
        assert captured["fileName"] == "documento original.bin"
        assert captured["filePath"] == str(artifact.resolve())
        assert captured["voiceNote"] is voice_note

    def test_media_rejects_unknown_mime_before_bridge_call(self, tmp_path, monkeypatch):
        root = tmp_path / "registry"
        root.mkdir()
        artifact = root / "sample.bin"
        artifact.write_bytes(b"media fixture")
        monkeypatch.setenv("OPENJARVIS_ARTIFACT_ROOT", str(root))

        ch = WhatsAppBaileysChannel()
        ch._status = ChannelStatus.CONNECTED
        ch._process = MagicMock()
        ch.execute_action_and_wait = MagicMock()

        with pytest.raises(ValueError, match="não suportado"):
            ch.send_media_and_wait(
                "5511999999999@s.whatsapp.net",
                str(artifact),
                mime_type="application/x-unknown",
                filename="sample.bin",
            )

        ch.execute_action_and_wait.assert_not_called()

    def test_reaction_resolves_the_complete_group_message_key(self):
        ch = WhatsAppBaileysChannel()
        ch._store.upsert_message(
            {
                "jid": "12345-67890@g.us",
                "remote_jid_alt": "123456789012345@lid",
                "participant": "5511999999999@s.whatsapp.net",
                "participant_alt": "998877665544332@lid",
                "message_id": "message-1",
                "text": "Mensagem",
                "from_me": False,
            }
        )
        message_ref = ch._store.list_messages("12345-67890@g.us")[0]["message_ref"]

        _, command = ch._resolve_reaction(message_ref, "👍")

        assert command == {
            "type": "send",
            "kind": "reaction",
            "jid": "12345-67890@g.us",
            "remoteJidAlt": "123456789012345@lid",
            "messageId": "message-1",
            "participant": "5511999999999@s.whatsapp.net",
            "participantAlt": "998877665544332@lid",
            "fromMe": False,
            "reaction": "👍",
        }

    def test_reaction_fails_closed_for_an_incomplete_group_key(self):
        ch = WhatsAppBaileysChannel()
        ch._store.upsert_message(
            {
                "jid": "12345-67890@g.us",
                "message_id": "legacy-message",
                "text": "Registro antigo sem participante",
                "from_me": False,
            }
        )
        message_ref = ch._store.list_messages("12345-67890@g.us")[0]["message_ref"]

        with pytest.raises(ValueError, match="chave.*incompleta"):
            ch._resolve_reaction(message_ref, "👍")


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------


class TestOnMessage:
    def test_handler_registration(self):
        ch = WhatsAppBaileysChannel()
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


# ---------------------------------------------------------------------------
# list_channels / status
# ---------------------------------------------------------------------------


class TestListChannelsAndStatus:
    def test_list_channels(self):
        ch = WhatsAppBaileysChannel()
        assert ch.list_channels() == ["whatsapp_baileys"]

    def test_initial_status(self):
        ch = WhatsAppBaileysChannel()
        assert ch.status() == ChannelStatus.DISCONNECTED


# ---------------------------------------------------------------------------
# _reader_loop + _handle_bridge_event
# ---------------------------------------------------------------------------


class TestReaderLoop:
    def test_parses_message_event(self):
        ch = WhatsAppBaileysChannel()
        handler = MagicMock()
        ch.on_message(handler)

        event = {
            "type": "message",
            "jid": "123@s.whatsapp.net",
            "sender": "456@s.whatsapp.net",
            "text": "Hello from WhatsApp",
            "message_id": "msg-001",
        }
        ch._handle_bridge_event(event)

        handler.assert_called_once()
        msg: ChannelMessage = handler.call_args[0][0]
        assert msg.channel == "whatsapp_baileys"
        assert msg.sender == "456@s.whatsapp.net"
        assert msg.content == "Hello from WhatsApp"
        assert msg.message_id == "msg-001"
        assert msg.conversation_id == "123@s.whatsapp.net"

    def test_parses_status_connected(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event({"type": "status", "status": "connected"})
        assert ch.status() == ChannelStatus.CONNECTED

    def test_parses_status_disconnected(self):
        ch = WhatsAppBaileysChannel()
        ch._status = ChannelStatus.CONNECTED
        ch._handle_bridge_event({"type": "status", "status": "disconnected"})
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_parses_qr_event(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event({"type": "qr", "data": "qr-code-string"})
        assert ch._last_qr == "qr-code-string"
        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "qr_required"
        assert snapshot["qr_available"] is True
        assert snapshot["qr_generation"] == 1
        assert snapshot["qr_issued_at"]
        assert ch.qr_snapshot()["qr"] == "qr-code-string"

    def test_each_qr_event_publishes_a_new_generation_in_the_same_status(self):
        ch = WhatsAppBaileysChannel()

        ch._handle_bridge_event({"type": "qr", "data": "first-qr"})
        first = ch.qr_snapshot()
        ch._handle_bridge_event({"type": "qr", "data": "second-qr"})
        second = ch.qr_snapshot()

        assert first["status"] == second["status"] == "qr_required"
        assert second["qr_generation"] == first["qr_generation"] + 1
        assert second["qr_issued_at"] >= first["qr_issued_at"]
        assert second["qr"] == "second-qr"

    def test_parses_error_event(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event({"type": "error", "message": "something broke"})
        assert ch.status() == ChannelStatus.ERROR
        assert ch.status_snapshot()["status"] == "failed"

    def test_operation_error_does_not_disconnect_a_healthy_bridge(self):
        ch = WhatsAppBaileysChannel()
        ch._process = MagicMock()
        ch._process.poll.return_value = None
        ch._handle_bridge_event({"type": "status", "status": "connected"})

        ch._handle_bridge_event(
            {
                "type": "error",
                "scope": "operation",
                "message": "History fetch failed",
            }
        )

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "connected"
        assert snapshot["send_available"] is True
        assert snapshot["last_error"] is None
        assert snapshot["last_operation_error"] == "History fetch failed"

    def test_bad_store_event_is_isolated_from_connection_state(self):
        ch = WhatsAppBaileysChannel()
        ch._process = MagicMock()
        ch._process.poll.return_value = None
        ch._handle_bridge_event({"type": "status", "status": "connected"})
        ch._store.upsert_contact = MagicMock(side_effect=RuntimeError("bad row"))

        ch._handle_bridge_event_safely({"type": "contact", "jid": "123@s.whatsapp.net"})

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "connected"
        assert snapshot["send_available"] is True
        assert snapshot["last_operation_error"] == (
            "Falha ao processar evento do bridge (contact)."
        )

    def test_conflict_remains_visible_after_bridge_disconnect(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event(
            {"type": "error", "code": 401, "message": "Stream Errored (conflict)"}
        )
        ch._handle_bridge_event({"type": "status", "status": "disconnected"})
        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "conflict"
        assert snapshot["reason"] == "conflict"

    def test_logged_out_is_not_reported_as_connected(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event(
            {"type": "error", "code": 401, "message": "Logged out from WhatsApp"}
        )
        assert ch.status_snapshot()["status"] == "logged_out"

    def test_connected_clears_stale_qr_and_error(self):
        ch = WhatsAppBaileysChannel()
        ch._process = MagicMock()
        ch._process.poll.return_value = None
        ch._handle_bridge_event({"type": "qr", "data": "qr-code-string"})
        ch._handle_bridge_event({"type": "error", "message": "conflict"})
        ch._handle_bridge_event({"type": "status", "status": "connected"})
        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "connected"
        assert snapshot["qr_available"] is False
        assert snapshot["qr_issued_at"] is None
        assert snapshot["last_error"] is None
        assert snapshot["send_available"] is True
        assert snapshot["last_transition_at"]

    def test_new_qr_clears_expired_qr_error(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event(
            {
                "type": "error",
                "code": "408",
                "reason": "failed",
                "message": "QR refs attempts ended",
            }
        )

        ch._handle_bridge_event({"type": "qr", "data": "renewed-qr"})

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "qr_required"
        assert snapshot["last_error"] is None
        assert snapshot["qr_available"] is True

    def test_reconnecting_status_clears_stale_qr_and_error(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event({"type": "qr", "data": "expired-qr"})
        ch._last_error = "QR refs attempts ended"

        ch._handle_bridge_event(
            {"type": "status", "status": "connecting", "reason": "reconnecting"}
        )

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "connecting"
        assert snapshot["reason"] is None
        assert snapshot["last_error"] is None
        assert snapshot["qr_available"] is False

    def test_structured_terminal_error_wins_over_stale_qr(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event({"type": "qr", "data": "stale-qr"})

        ch._handle_bridge_event(
            {
                "type": "error",
                "code": "440",
                "reason": "conflict",
                "message": "Connection replaced",
            }
        )

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "conflict"
        assert snapshot["reason"] == "conflict"
        assert snapshot["qr_available"] is False

    def test_inconsistent_auth_is_exposed_as_a_resettable_terminal_state(self):
        ch = WhatsAppBaileysChannel()
        ch._handle_bridge_event(
            {
                "type": "error",
                "reason": "auth_inconsistent",
                "message": "Authentication state requires quarantine",
            }
        )

        snapshot = ch.status_snapshot()
        assert snapshot["status"] == "auth_inconsistent"
        assert snapshot["qr_available"] is False

    def test_status_snapshot_reconciles_a_dead_connected_process(self):
        ch = WhatsAppBaileysChannel()
        ch._process = MagicMock()
        ch._process.poll.return_value = 1
        ch._status = ChannelStatus.CONNECTED

        snapshot = ch.status_snapshot()

        assert snapshot["status"] == "failed"
        assert snapshot["send_available"] is False
        assert snapshot["reason"] == "failed"

    def test_message_event_publishes_to_bus(self):
        bus = EventBus(record_history=True)
        ch = WhatsAppBaileysChannel(bus=bus)

        ch._handle_bridge_event(
            {
                "type": "message",
                "jid": "123@s.whatsapp.net",
                "sender": "456@s.whatsapp.net",
                "text": "Bus test",
                "message_id": "msg-002",
            }
        )

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_RECEIVED in event_types

    def test_reader_loop_marks_unexpected_eof_as_failed(self):
        ch = WhatsAppBaileysChannel()
        ch._stop_event = threading.Event()

        lines = [
            json.dumps({"type": "status", "status": "connected"}) + "\n",
            json.dumps(
                {
                    "type": "message",
                    "jid": "j",
                    "sender": "s",
                    "text": "t",
                    "message_id": "m",
                }
            )
            + "\n",
        ]

        mock_proc = MagicMock()
        mock_proc.stdout = lines
        ch._process = mock_proc

        ch._reader_loop()

        assert ch.status() == ChannelStatus.ERROR
        assert ch.status_snapshot()["status"] == "failed"

    def test_reader_loop_skips_non_json_then_marks_eof_as_failed(self):
        ch = WhatsAppBaileysChannel()
        ch._stop_event = threading.Event()

        lines = [
            "not json at all\n",
            json.dumps({"type": "status", "status": "connected"}) + "\n",
        ]

        mock_proc = MagicMock()
        mock_proc.stdout = lines
        ch._process = mock_proc

        ch._reader_loop()

        assert ch.status() == ChannelStatus.ERROR

    def test_handler_exception_does_not_crash(self):
        ch = WhatsAppBaileysChannel()
        bad_handler = MagicMock(side_effect=ValueError("boom"))
        ch.on_message(bad_handler)

        # Should not raise.
        ch._handle_bridge_event(
            {
                "type": "message",
                "jid": "j",
                "sender": "s",
                "text": "t",
                "message_id": "m",
            }
        )
        bad_handler.assert_called_once()
