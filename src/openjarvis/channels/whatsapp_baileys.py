"""WhatsAppBaileysChannel -- bidirectional WhatsApp messaging via Baileys protocol.

Spawns a Node.js subprocess that runs the Baileys bridge (JSON-line protocol
on stdio).  The bridge handles QR-code authentication, message sending, and
incoming-message forwarding.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)
from openjarvis.channels.whatsapp.bridge_commands import (
    BridgeCommandError,
    BridgeCommandTimeout,
    BridgeCommandTracker,
)
from openjarvis.channels.whatsapp.identity import (
    WhatsAppJidKind,
    classify_jid,
    is_supported_jid,
)
from openjarvis.channels.whatsapp.store import WhatsAppStore
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)

# Path to the bundled bridge shipped inside the package.
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_BRIDGE_SRC = Path(__file__).resolve().parent / "whatsapp_baileys_bridge"
if not _BRIDGE_SRC.exists():
    _BRIDGE_SRC = (
        Path(__file__).resolve().parents[2]
        / "_node_modules"
        / "whatsapp_baileys_bridge"
    )


def _default_runtime_dir() -> Path:
    """Resolve bridge artifacts under the project runtime when configured."""

    runtime_root = os.environ.get("OPENJARVIS_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve() / "whatsapp_baileys_bridge"
    return get_config_dir() / "whatsapp_baileys_bridge"


_BAILEYS_STATUS_QR_REQUIRED = "qr_required"
_BAILEYS_STATUS_CONFLICT = "conflict"
_BAILEYS_STATUS_LOGGED_OUT = "logged_out"
_BAILEYS_STATUS_AUTH_INCONSISTENT = "auth_inconsistent"
_BAILEYS_STATUS_FAILED = "failed"

# Keep the provider payload kind separate from the artifact MIME.  In
# particular, ``application/pdf`` is a Baileys ``document`` (not the string
# before the slash, ``application``).  The explicit table is deliberately
# closed so an unknown artifact cannot silently become a different payload.
_WHATSAPP_MEDIA_KIND_BY_MIME = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.ms-word.document.macroenabled.12": "document",
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ): "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.ms-excel.sheet.macroenabled.12": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12": "document",
    (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ): "document",
    "application/rtf": "document",
    "text/rtf": "document",
    "text/csv": "document",
    "text/plain": "document",
    "application/zip": "document",
    "audio/ogg": "audio",
    "audio/mpeg": "audio",
    "audio/mp4": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/webm": "audio",
}


def _whatsapp_media_kind(mime_type: str) -> tuple[str, str]:
    """Return the closed Baileys payload kind and canonical MIME.

    The provider needs a semantic payload key (``document``, ``image`` or
    ``audio``), while the original MIME remains metadata on the document.
    Never derive the payload key by splitting at ``/``: that maps PDF to the
    invalid Baileys kind ``application``.
    """

    canonical = str(mime_type or "").split(";", 1)[0].strip().lower()
    kind = _WHATSAPP_MEDIA_KIND_BY_MIME.get(canonical)
    if kind is None:
        raise ValueError(
            f"Tipo de mídia WhatsApp não suportado: {canonical or '<vazio>'}"
        )
    return kind, canonical


def _path_has_symlink(path: Path) -> bool:
    """Check every path component before resolving a provider path."""

    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _find_node_tool(name: str) -> Optional[str]:
    """Resolve Node.js tools even when the service inherited a reduced PATH."""
    candidates = [name]
    if os.name == "nt":
        candidates.append(f"{name}.cmd")
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    node_path = shutil.which("node")
    if node_path:
        node_dir = Path(node_path).parent
        for suffix in ("", ".cmd", ".exe"):
            candidate = node_dir / f"{name}{suffix}"
            if candidate.exists():
                return str(candidate)
    return None


@ChannelRegistry.register("whatsapp_baileys")
class WhatsAppBaileysChannel(BaseChannel):
    """Bidirectional WhatsApp channel using the Baileys protocol.

    Communicates with a Node.js bridge subprocess over JSON-line stdio.

    Parameters
    ----------
    auth_dir:
        Directory for Baileys auth state persistence.  Defaults to
        ``OPENJARVIS_RUNTIME_ROOT/whatsapp_baileys_bridge/auth`` when the
        project runtime is configured, otherwise the OpenJarvis config root.
    assistant_name:
        Display name used by the assistant in conversations.
    assistant_has_own_number:
        If ``True`` the assistant has a dedicated WhatsApp number and will
        not filter out its own messages.
    bus:
        Optional event bus for publishing channel events.
    """

    channel_id = "whatsapp_baileys"

    def __init__(
        self,
        *,
        auth_dir: str = "",
        assistant_name: str = "Jarvis",
        assistant_has_own_number: bool = False,
        bus: Optional[EventBus] = None,
        store: Optional[WhatsAppStore] = None,
    ) -> None:
        self._auth_dir = auth_dir
        self._assistant_name = assistant_name
        self._assistant_has_own_number = assistant_has_own_number
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._runtime_dir = _default_runtime_dir()
        self._last_qr: str = ""
        self._qr_generation = 0
        self._qr_issued_at: Optional[str] = None
        self._last_error: str = ""
        self._last_operation_error: str = ""
        self._status_reason: str = ""
        self._last_transition_at = datetime.now(timezone.utc).isoformat()
        self._node_executable = "node"
        self._store = store or WhatsAppStore()
        self._commands = BridgeCommandTracker()
        logger.info("WhatsApp local index ready database=%s", self._store.database_path)

    def _transition_status(
        self,
        status: ChannelStatus,
        *,
        reason: str = "",
        preserve_reason: bool = False,
    ) -> None:
        """Update the public state and timestamp one actual transition."""

        with self._state_lock:
            next_reason = self._status_reason if preserve_reason else reason
            if status != self._status or next_reason != self._status_reason:
                self._last_transition_at = datetime.now(timezone.utc).isoformat()
            self._status = status
            self._status_reason = next_reason

    def _clear_qr(self) -> None:
        """Remove an obsolete QR without reusing its issuance timestamp."""

        with self._state_lock:
            self._last_qr = ""
            self._qr_issued_at = None

    def _record_qr(self, qr: str) -> None:
        """Publish one new QR generation as a single atomic state change."""

        qr = qr.strip()
        if not qr:
            raise ValueError("bridge emitted an empty QR challenge")
        with self._state_lock:
            self._last_qr = qr
            self._qr_generation += 1
            self._qr_issued_at = datetime.now(timezone.utc).isoformat()
            self._last_error = ""
            self._last_operation_error = ""
            self._transition_status(
                ChannelStatus.CONNECTING,
                reason=_BAILEYS_STATUS_QR_REQUIRED,
            )

    # -- bridge lifecycle -------------------------------------------------------

    def _ensure_bridge(self) -> Path:
        """Resolve a prebuilt bridge or prepare an isolated runtime copy.

        Returns the path to ``dist/bridge.js``.

        Raises
        ------
        RuntimeError
            If ``node`` is not found on ``PATH``.
        """
        node_executable = _find_node_tool("node")
        if node_executable is None:
            raise RuntimeError(
                "Node.js is required for WhatsAppBaileysChannel but 'node' "
                "was not found on PATH.  Install Node.js 22+ and try again."
            )
        self._node_executable = node_executable

        source_bridge = _BRIDGE_SRC / "dist" / "bridge.js"
        source_node_modules = _BRIDGE_SRC / "node_modules"
        if source_bridge.exists() and source_node_modules.is_dir():
            logger.info("Using the prebuilt Baileys bridge from the workspace")
            return source_bridge

        runtime = self._runtime_dir
        runtime.mkdir(parents=True, exist_ok=True)

        # Copy the small bridge package into its isolated runtime directory.
        # A source-only checkout is supported: the TypeScript bridge is built
        # on first use instead of failing with a missing dist/bridge.js.
        pkg_dst = runtime / "package.json"
        pkg_src = _BRIDGE_SRC / "package.json"
        if pkg_src.exists() and (
            not pkg_dst.exists() or pkg_src.stat().st_mtime > pkg_dst.stat().st_mtime
        ):
            shutil.copy2(pkg_src, pkg_dst)

        lock_src = _BRIDGE_SRC / "package-lock.json"
        lock_dst = runtime / "package-lock.json"
        if lock_src.exists() and (
            not lock_dst.exists() or lock_src.stat().st_mtime > lock_dst.stat().st_mtime
        ):
            shutil.copy2(lock_src, lock_dst)

        dist_dst = runtime / "dist"
        dist_src = _BRIDGE_SRC / "dist"
        if dist_src.exists():
            if dist_dst.exists():
                shutil.rmtree(dist_dst)
            shutil.copytree(dist_src, dist_dst)

        bridge_js = runtime / "dist" / "bridge.js"
        if not bridge_js.exists():
            for relative in ("src", "tsconfig.json"):
                source = _BRIDGE_SRC / relative
                target = runtime / relative
                if source.is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(source, target)
                elif source.exists():
                    shutil.copy2(source, target)

        # A full install is needed for the TypeScript compiler when a bundled
        # dist artifact is not present. It remains isolated from the Python
        # environment and only runs when the QR connection is explicitly
        # started by the user.
        node_modules = runtime / "node_modules"
        if not node_modules.exists() or not bridge_js.exists():
            npm_executable = _find_node_tool("npm")
            if npm_executable is None:
                raise RuntimeError(
                    "npm was not found beside Node.js. Add the Node.js directory "
                    "to the OpenJarvis service PATH and try again."
                )
            logger.info("Installing the Baileys bridge runtime in %s", runtime)
            subprocess.run(
                [npm_executable, "install", "--ignore-scripts"],
                cwd=str(runtime),
                check=True,
                capture_output=True,
            )

        if not bridge_js.exists():
            npm_executable = _find_node_tool("npm")
            if npm_executable is None:
                raise RuntimeError(
                    "npm was not found beside Node.js. Add the Node.js directory "
                    "to the OpenJarvis service PATH and try again."
                )
            logger.info("Building the Baileys TypeScript bridge in %s", runtime)
            subprocess.run(
                [npm_executable, "run", "build"],
                cwd=str(runtime),
                check=True,
                capture_output=True,
            )

        if not bridge_js.exists():
            raise RuntimeError(
                f"Bridge entry point not found at {bridge_js}.  "
                "Ensure the bridge TypeScript has been compiled."
            )
        return bridge_js

    # -- BaseChannel interface ---------------------------------------------------

    def connect(self) -> None:
        """Spawn the Node.js bridge subprocess and start the reader thread."""
        if self._status == ChannelStatus.CONNECTED and self._process_is_alive():
            return
        if self._process is not None:
            logger.info("Stopping stale Baileys bridge before a new connection")
            self.disconnect()

        with self._state_lock:
            self._transition_status(ChannelStatus.CONNECTING)
            self._last_error = ""
            self._last_operation_error = ""
            self._clear_qr()

        try:
            bridge_js = self._ensure_bridge()
        except Exception as exc:
            logger.error("Bridge setup failed: %s", exc)
            self._last_error = "Falha ao preparar o bridge local."
            self._transition_status(
                ChannelStatus.ERROR,
                reason=_BAILEYS_STATUS_FAILED,
            )
            return

        auth = str(self._auth_state_path())

        try:
            self._stop_event.clear()
            self._process = subprocess.Popen(
                [self._node_executable, str(bridge_js), "--auth-dir", auth],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
            )
            self._reader_thread.start()
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                daemon=True,
            )
            self._stderr_thread.start()
            logger.info(
                "WhatsApp Baileys bridge started (pid=%s)",
                self._process.pid,
            )
        except Exception:
            logger.exception("Failed to start bridge subprocess")
            self._last_error = "Falha ao iniciar o bridge local."
            self._transition_status(
                ChannelStatus.ERROR,
                reason=_BAILEYS_STATUS_FAILED,
            )

    def _auth_state_path(self) -> Path:
        if self._auth_dir:
            return Path(self._auth_dir).expanduser().resolve()
        return (self._runtime_dir / "auth").resolve()

    def reset_auth_state(self) -> None:
        """Quarantine only the explicitly managed Baileys auth state.

        The public reset endpoint calls this method only after a deliberate UI
        confirmation. Custom auth directories outside the channel runtime are
        never moved automatically. The previous generation is preserved under
        ``auth-quarantine`` instead of being deleted.
        """

        self.disconnect()
        runtime = self._runtime_dir.resolve()
        auth = self._auth_state_path()
        if auth == runtime:
            raise RuntimeError(
                "O diretório raiz do runtime não pode ser usado como autenticação."
            )
        managed_auth = (runtime / "auth").resolve()
        if auth != managed_auth:
            raise RuntimeError(
                "A sessão não usa o diretório de autenticação gerenciado; "
                "a preservação automática foi recusada."
            )
        if auth.exists():
            if not auth.is_dir():
                raise RuntimeError(
                    "O caminho de autenticação gerenciado não é uma pasta."
                )
            quarantine_root = runtime / "auth-quarantine"
            quarantine_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            quarantine = quarantine_root / f"{auth.name}-{timestamp}"
            auth.rename(quarantine)
        with self._state_lock:
            self._last_error = ""
            self._last_operation_error = ""
            self._clear_qr()
            self._transition_status(ChannelStatus.DISCONNECTED)

    def disconnect(self) -> None:
        """Send disconnect command to the bridge and terminate the subprocess."""
        self._stop_event.set()
        self._commands.cancel_all("O bridge WhatsApp foi encerrado")

        if self._process is not None and self._process.stdin is not None:
            try:
                self._write_command({"type": "disconnect"})
            except Exception:
                logger.debug("Could not send disconnect command", exc_info=True)

        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5.0)
            except Exception:
                logger.debug("Bridge process termination error", exc_info=True)
            self._process = None

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5.0)
            self._reader_thread = None

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=5.0)
            self._stderr_thread = None

        with self._state_lock:
            self._transition_status(ChannelStatus.DISCONNECTED)
            self._clear_qr()

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a message to a WhatsApp JID via the bridge subprocess."""
        if self._process is None or self._status != ChannelStatus.CONNECTED:
            logger.warning("Cannot send: bridge not connected")
            return False

        try:
            self._write_command(
                {
                    "type": "send",
                    "jid": channel,
                    "text": content,
                }
            )
            self._publish_sent(channel, content, conversation_id)
            return True
        except Exception:
            logger.debug("WhatsApp Baileys send failed", exc_info=True)
            return False

    def send_and_wait(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Send text and publish success only after Baileys acknowledges it."""

        if not is_supported_jid(channel):
            raise ValueError("JID WhatsApp invalido")
        if not str(content or "").strip():
            raise ValueError("Mensagem WhatsApp vazia")
        result = self.execute_action_and_wait(
            {"type": "send", "kind": "text", "jid": channel, "text": content},
            timeout=timeout,
        )
        self._publish_sent(channel, content, conversation_id)
        return result

    def send_media_and_wait(
        self,
        channel: str,
        file_path: str,
        *,
        mime_type: str,
        filename: str,
        caption: str = "",
        voice_note: bool = False,
        conversation_id: str = "",
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Send one already-validated local artifact through Baileys."""

        if not is_supported_jid(channel):
            raise ValueError("JID WhatsApp invalido")
        raw_path = Path(file_path).expanduser()
        if _path_has_symlink(raw_path):
            raise ValueError("Artefato contem symlink")
        path = raw_path.resolve()
        root = (
            Path(
                os.environ.get(
                    "OPENJARVIS_ARTIFACT_ROOT", r"F:\agente\artifacts\registry"
                )
            )
            .expanduser()
            .resolve()
        )
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Artefato fora da raiz controlada") from exc
        if path.is_symlink() or not path.is_file():
            raise ValueError("Artefato indisponivel")
        media_kind, canonical_mime = _whatsapp_media_kind(mime_type)
        result = self.execute_action_and_wait(
            {
                "type": "send",
                "kind": "media",
                "jid": channel,
                "filePath": str(path),
                "mediaType": media_kind,
                "mimetype": canonical_mime,
                "fileName": filename,
                "caption": str(caption or "")[:4000],
                "voiceNote": bool(voice_note),
            },
            timeout=timeout,
        )
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "conversation_id": conversation_id,
                    "message_type": "media",
                    "mime_type": mime_type,
                    "filename": filename,
                    "voice_note": bool(voice_note),
                },
            )
        return result

    def status(self) -> ChannelStatus:
        """Return the current connection status."""
        return self._status

    def status_snapshot(self) -> Dict[str, Any]:
        """Return a truthful public Baileys state for the Sources UI.

        ``ChannelStatus`` is intentionally kept compatible with the core
        channel contract.  This richer snapshot prevents a bridge conflict or
        logout from being rendered as a generic connected/disconnected state.
        """

        with self._state_lock:
            if self._status == ChannelStatus.CONNECTED and not self._process_is_alive():
                self._last_error = "O processo do bridge não está ativo."
                self._transition_status(
                    ChannelStatus.ERROR,
                    reason=_BAILEYS_STATUS_FAILED,
                )

            process_alive = self._process_is_alive()
            if self._status == ChannelStatus.CONNECTED and process_alive:
                public_status = "connected"
            elif self._status_reason in {
                _BAILEYS_STATUS_CONFLICT,
                _BAILEYS_STATUS_LOGGED_OUT,
                _BAILEYS_STATUS_AUTH_INCONSISTENT,
                _BAILEYS_STATUS_FAILED,
            }:
                public_status = self._status_reason
            elif self._status_reason == _BAILEYS_STATUS_QR_REQUIRED or self._last_qr:
                public_status = _BAILEYS_STATUS_QR_REQUIRED
            elif self._status == ChannelStatus.CONNECTING:
                public_status = "connecting"
            elif self._status == ChannelStatus.ERROR:
                public_status = _BAILEYS_STATUS_FAILED
            else:
                public_status = "disconnected"
            return {
                "status": public_status,
                "base_status": self._status.value,
                "reason": self._status_reason or None,
                "last_error": self._last_error[:512] or None,
                "last_operation_error": self._last_operation_error[:512] or None,
                "qr_available": bool(self._last_qr),
                "qr_generation": self._qr_generation,
                "qr_issued_at": self._qr_issued_at,
                "send_available": bool(
                    self._status == ChannelStatus.CONNECTED and process_alive
                ),
                "last_transition_at": self._last_transition_at,
            }

    def qr_snapshot(self) -> Dict[str, Any]:
        """Return QR payload and metadata from one consistent state snapshot."""

        with self._state_lock:
            return {
                **self.status_snapshot(),
                "qr": self._last_qr,
                "available": bool(self._last_qr),
            }

    def list_channels(self) -> List[str]:
        """Return available channel identifiers."""
        return ["whatsapp_baileys"]

    def search_contacts(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Search the local contact index by name, notify name or JID."""
        return self._store.search_contacts(query, limit)

    def search_chats(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """List or search chats ordered by most recent known activity."""
        return self._store.search_chats(query, limit)

    def list_messages(
        self, jid: str, *, query: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Read bounded local history for one conversation."""
        return self._store.list_messages(jid, query=query, limit=limit)

    def conversation_summary(self, jid: str, *, limit: int = 50) -> Dict[str, Any]:
        """Return a bounded context pack for Jarvis to summarize read-only."""
        return self._store.summary(jid, limit=limit)

    def request_history(self, jid: str, *, limit: int = 50) -> bool:
        """Ask Baileys for older history using the oldest indexed message."""
        oldest = self._store.oldest_message(jid)
        if (
            oldest is None
            or self._process is None
            or self._status != ChannelStatus.CONNECTED
        ):
            return False
        try:
            self._write_command(
                {
                    "type": "history",
                    "jid": jid,
                    "limit": min(50, max(1, int(limit))),
                    "oldest": oldest,
                }
            )
            return True
        except Exception:
            logger.debug("WhatsApp history request failed", exc_info=True)
            return False

    def mark_read(self, jid: str, message_ids: list[str] | None = None) -> bool:
        """Mark selected indexed messages as read in WhatsApp.

        The local index supplies the sender/participant key required for group
        messages. No more than 50 keys are sent to the bridge per request.
        """
        if self._process is None or self._status != ChannelStatus.CONNECTED:
            return False
        indexed = self._store.list_message_keys(jid, message_ids, limit=50)
        allowed = {str(message.get("message_id", "")) for message in indexed}
        requested = [str(message_id).strip() for message_id in (message_ids or [])]
        if requested and any(message_id not in allowed for message_id in requested):
            return False
        selected = [
            message
            for message in indexed
            if (not requested and not message.get("from_me"))
            or (requested and message.get("message_id") in requested)
        ]
        keys = []
        for message in selected[:50]:
            key: dict[str, Any] = {
                "remoteJid": jid,
                "id": message["message_id"],
                "fromMe": bool(message.get("from_me")),
            }
            if message.get("remote_jid_alt"):
                key["remoteJidAlt"] = message["remote_jid_alt"]
            if jid.endswith("@g.us"):
                participant = str(
                    message.get("participant") or message.get("sender") or ""
                )
                participant_alt = str(message.get("participant_alt") or "")
                if (
                    not message.get("from_me")
                    and classify_jid(participant)
                    not in {WhatsAppJidKind.PHONE, WhatsAppJidKind.LID}
                    and classify_jid(participant_alt)
                    not in {WhatsAppJidKind.PHONE, WhatsAppJidKind.LID}
                ):
                    return False
                if participant:
                    key["participant"] = participant
                if participant_alt:
                    key["participantAlt"] = participant_alt
            keys.append(key)
        if not keys:
            return False
        try:
            self._write_command({"type": "read", "keys": keys})
            return True
        except Exception:
            logger.debug("WhatsApp mark-read request failed", exc_info=True)
            return False

    def execute_action(self, action: dict[str, Any]) -> bool:
        """Submit one validated namespace action to the connected bridge."""
        if self._process is None or self._status != ChannelStatus.CONNECTED:
            return False
        try:
            self._write_command(action)
            return True
        except Exception:
            logger.debug("WhatsApp action request failed", exc_info=True)
            return False

    def execute_action_and_wait(
        self, action: dict[str, Any], *, timeout: float = 15.0
    ) -> Dict[str, Any]:
        """Execute an action and return only after Baileys confirms completion.

        This method is intentionally separate from the legacy boolean method:
        API mutations must not report success merely because JSON reached the
        subprocess stdin.
        """

        if self._process is None or self._status != ChannelStatus.CONNECTED:
            raise BridgeCommandError("O bridge WhatsApp nao esta conectado")
        command_id = self._commands.register()
        command = dict(action)
        command["commandId"] = command_id
        try:
            self._write_command(command)
        except Exception as exc:
            self._commands.cancel(command_id, "Falha ao escrever no bridge WhatsApp")
            try:
                self._commands.wait(command_id, 0.01)
            except (BridgeCommandError, BridgeCommandTimeout):
                pass
            raise BridgeCommandError("Falha ao escrever no bridge WhatsApp") from exc
        try:
            result = self._commands.wait(command_id, timeout)
            self._last_operation_error = ""
            return result
        except (BridgeCommandError, BridgeCommandTimeout) as exc:
            self._last_operation_error = str(exc)[:512]
            raise

    def react_to_message(
        self, message_ref: str, reaction: str, *, timeout: float = 15.0
    ) -> Dict[str, Any]:
        """React using an opaque reference resolved to the exact stored key."""

        _, command = self._resolve_reaction(message_ref, reaction)
        return self.execute_action_and_wait(command, timeout=timeout)

    def reaction_preview(self, message_ref: str, reaction: str) -> Dict[str, Any]:
        """Validate a reaction and expose only safe confirmation metadata."""

        target, _ = self._resolve_reaction(message_ref, reaction)
        return {
            "message_ref": str(target["message_ref"]),
            "jid": str(target["jid"]),
            "reaction": str(reaction).strip(),
            "message_preview": str(target.get("text") or "")[:160],
            "message_at": int(target.get("message_at") or 0),
        }

    def resolve_message_reference(self, message_ref: str) -> Dict[str, Any]:
        """Resolve one opaque message reference inside the trusted adapter boundary.

        Provider identifiers returned here must never be sent to Gemini or the
        browser.  They are used only to build an exact, visually approved bridge
        command on the server.
        """

        target = self._store.get_message_by_ref(message_ref)
        if target is None:
            raise ValueError("Referencia de mensagem WhatsApp invalida ou expirada")
        return dict(target)

    def _resolve_reaction(
        self, message_ref: str, reaction: str
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        target = self._store.get_message_by_ref(message_ref)
        if target is None:
            raise ValueError("Referencia de mensagem WhatsApp invalida ou expirada")
        emoji = str(reaction or "").strip()
        if not emoji or len(emoji) > 16:
            raise ValueError("Reacao WhatsApp invalida")
        jid = str(target["jid"])
        if not is_supported_jid(jid):
            raise ValueError("JID da mensagem WhatsApp invalido")
        remote_jid_alt = str(target.get("remote_jid_alt") or "")
        participant = str(target.get("participant") or "")
        participant_alt = str(target.get("participant_alt") or "")
        if remote_jid_alt and not is_supported_jid(remote_jid_alt):
            raise ValueError("JID alternativo da mensagem WhatsApp invalido")
        if participant and not is_supported_jid(participant):
            raise ValueError("Participante da mensagem WhatsApp invalido")
        if participant_alt and not is_supported_jid(participant_alt):
            raise ValueError("Participante alternativo da mensagem WhatsApp invalido")
        if (
            classify_jid(jid) is WhatsAppJidKind.GROUP
            and not bool(target.get("from_me"))
            and not (participant or participant_alt)
        ):
            raise ValueError(
                "A chave desta mensagem de grupo e incompleta; "
                "sincronize o historico novamente"
            )
        command: Dict[str, Any] = {
            "type": "send",
            "kind": "reaction",
            "jid": jid,
            "remoteJidAlt": remote_jid_alt,
            "messageId": str(target["message_id"]),
            "participant": participant,
            "participantAlt": participant_alt,
            "fromMe": bool(target.get("from_me")),
            "reaction": emoji,
        }
        return target, command

    def on_message(self, handler: ChannelHandler) -> None:
        """Register a callback for incoming messages."""
        self._handlers.append(handler)

    # -- internal helpers -------------------------------------------------------

    def _process_is_alive(self) -> bool:
        process = self._process
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            return False

    def _write_command(self, cmd: Dict[str, Any]) -> None:
        """Write a JSON-line command to the bridge's stdin."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Bridge process not running")
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _reader_loop(self) -> None:
        """Background thread: read JSON lines from bridge stdout."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        try:
            for raw_line in proc.stdout:
                if self._stop_event.is_set():
                    break

                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON line from bridge: %s", line)
                    continue

                self._handle_bridge_event_safely(event)
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("WhatsApp bridge reader stopped unexpectedly")
                self._last_error = "Falha no leitor do bridge local."
                self._transition_status(
                    ChannelStatus.ERROR,
                    reason=_BAILEYS_STATUS_FAILED,
                )
        finally:
            if (
                not self._stop_event.is_set()
                and self._process is proc
                and self._status in {ChannelStatus.CONNECTED, ChannelStatus.CONNECTING}
            ):
                self._last_error = "O processo do bridge encerrou inesperadamente."
                self._transition_status(
                    ChannelStatus.ERROR,
                    reason=self._status_reason or _BAILEYS_STATUS_FAILED,
                )

    def _stderr_loop(self) -> None:
        """Capture bridge diagnostics without allowing stderr to fill up."""
        proc = self._process
        if proc is None or proc.stderr is None:
            return

        try:
            for raw_line in proc.stderr:
                line = raw_line.strip()
                if line:
                    logger.info("WhatsApp Baileys bridge: %s", line)
        except Exception:
            if not self._stop_event.is_set():
                logger.debug("Bridge stderr reader error", exc_info=True)

    def _handle_bridge_event_safely(self, event: object) -> None:
        """Isolate one malformed data event from the connection lifecycle."""

        event_type = (
            str(event.get("type", "unknown"))[:64]
            if isinstance(event, dict)
            else "invalid"
        )
        try:
            if not isinstance(event, dict):
                raise TypeError("bridge event must be an object")
            self._handle_bridge_event(event)
        except Exception as exc:
            self._last_operation_error = (
                f"Falha ao processar evento do bridge ({event_type})."
            )
            logger.warning(
                "WhatsApp bridge event rejected type=%s error_type=%s",
                event_type,
                type(exc).__name__,
                exc_info=True,
            )

    def _handle_bridge_event(self, event: Dict[str, Any]) -> None:
        """Dispatch a single JSON event from the bridge."""
        event_type = event.get("type", "")

        if event_type == "status":
            new_status = event.get("status", "")
            if new_status == "connected":
                with self._state_lock:
                    self._transition_status(ChannelStatus.CONNECTED)
                    self._last_error = ""
                    self._last_operation_error = ""
                    self._clear_qr()
                logger.info("WhatsApp Baileys bridge connected")
            elif new_status == "connecting":
                with self._state_lock:
                    self._clear_qr()
                    self._last_error = ""
                    self._last_operation_error = ""
                    self._transition_status(ChannelStatus.CONNECTING)
            elif new_status == "disconnected":
                self._commands.cancel_all("O bridge WhatsApp foi desconectado")
                self._transition_status(
                    ChannelStatus.DISCONNECTED,
                    preserve_reason=True,
                )

        elif event_type == "qr":
            self._record_qr(str(event.get("data", "")))
            logger.info("WhatsApp QR code received -- scan to authenticate")

        elif event_type == "contact":
            self._store.upsert_contact(event)

        elif event_type == "chat":
            self._store.upsert_chat(event)

        elif event_type == "chat_deleted":
            self._store.delete_chat(str(event.get("jid", "")))

        elif event_type == "message":
            self._store.upsert_message(event)
            if event.get("from_me"):
                return
            cm = ChannelMessage(
                channel="whatsapp_baileys",
                sender=event.get("sender", ""),
                content=event.get("text", ""),
                message_id=event.get("message_id", ""),
                conversation_id=event.get("jid", ""),
                metadata={
                    key: event.get(key)
                    for key in (
                        "message_type",
                        "media_type",
                        "media_mime_type",
                        "media_filename",
                        "media_path",
                        "media_size",
                        "media_sha256",
                        "media_error",
                    )
                    if event.get(key) not in {None, ""}
                },
            )
            for handler in self._handlers:
                try:
                    handler(cm)
                except Exception:
                    logger.exception("WhatsApp Baileys handler error")
            if self._bus is not None:
                self._bus.publish(
                    EventType.CHANNEL_MESSAGE_RECEIVED,
                    {
                        "channel": cm.channel,
                        "sender": cm.sender,
                        "content": cm.content,
                        "message_id": cm.message_id,
                    },
                )

        elif event_type == "command_ok":
            command_id = str(event.get("command_id", ""))
            if command_id:
                self._commands.resolve(command_id, event)

        elif event_type == "error":
            code = str(event.get("code", ""))
            message = str(event.get("message", "unknown"))[:512]
            scope = str(event.get("scope", "connection")).strip().lower()
            if scope in {"operation", "protocol"}:
                self._last_operation_error = message
                command_id = str(event.get("command_id", ""))
                if command_id:
                    self._commands.reject(command_id, message)
                logger.warning(
                    "WhatsApp bridge non-terminal error scope=%s code=%s",
                    scope,
                    code[:32],
                )
                return
            self._clear_qr()
            self._last_error = message
            error_text = f"{code} {self._last_error}".lower()
            structured_reason = str(event.get("reason", "")).strip().lower()
            if structured_reason in {
                _BAILEYS_STATUS_CONFLICT,
                _BAILEYS_STATUS_LOGGED_OUT,
                _BAILEYS_STATUS_AUTH_INCONSISTENT,
                _BAILEYS_STATUS_FAILED,
            }:
                reason = structured_reason
            elif "conflict" in error_text or "stream errored" in error_text:
                reason = _BAILEYS_STATUS_CONFLICT
            elif (
                "logged out" in error_text
                or "401" in error_text
                or "unauthorized" in error_text
            ):
                reason = _BAILEYS_STATUS_LOGGED_OUT
            else:
                reason = _BAILEYS_STATUS_FAILED
            logger.error("Bridge error: %s", self._last_error)
            self._transition_status(ChannelStatus.ERROR, reason=reason)

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        """Publish a CHANNEL_MESSAGE_SENT event on the bus."""
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = ["WhatsAppBaileysChannel"]
