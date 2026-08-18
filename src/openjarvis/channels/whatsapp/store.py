"""Durable local WhatsApp index with PN/LID-aware identity resolution."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from openjarvis.core.paths import get_data_dir

from .identity import (
    WhatsAppJidKind,
    build_search_text,
    classify_jid,
    clean_text,
    is_supported_jid,
    normalize_phone,
    phone_from_jid,
)
from .store_queries import WhatsAppStoreQueries
from .store_schema import initialize_schema, new_message_ref

_MAX_TEXT = 16_000


def default_database_path() -> Path:
    """Resolve the persistent index under the configured runtime root."""

    explicit = os.environ.get("OPENJARVIS_WHATSAPP_DATABASE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    runtime_root = os.environ.get("OPENJARVIS_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return (
            Path(runtime_root).expanduser().resolve()
            / "whatsapp"
            / "whatsapp_baileys.db"
        )
    return get_data_dir() / "whatsapp_baileys.db"


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _alias_jid(value: Any, kind: WhatsAppJidKind) -> str:
    candidate = clean_text(value, 160)
    if not candidate:
        return ""
    if candidate.isdecimal():
        suffix = "@s.whatsapp.net" if kind is WhatsAppJidKind.PHONE else "@lid"
        candidate = f"{candidate}{suffix}"
    return candidate if classify_jid(candidate) is kind else ""


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class WhatsAppStore(WhatsAppStoreQueries):
    """SQLite index populated by bridge events and queried by Jarvis tools.

    The store persists normalized metadata and bounded message text only.
    Baileys credentials, raw protobufs and media bytes never enter this file.
    """

    def __init__(self, database_path: Path | None = None) -> None:
        target = (
            Path(database_path)
            if database_path is not None
            else default_database_path()
        )
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = target
        self._connection = sqlite3.connect(
            str(target), check_same_thread=False, timeout=10
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            initialize_schema(self._connection)

    def upsert_contact(self, contact: dict[str, Any]) -> None:
        """Store one personal contact and its PN/LID aliases."""

        jid = clean_text(contact.get("jid"), 160)
        jid_kind = classify_jid(jid)
        if jid_kind not in {WhatsAppJidKind.PHONE, WhatsAppJidKind.LID}:
            return

        with self._lock:
            existing = _row_dict(
                self._connection.execute(
                    "SELECT * FROM whatsapp_contacts WHERE jid = ?", (jid,)
                ).fetchone()
            )
            phone_jid = (
                _alias_jid(
                    contact.get("phone_jid") or contact.get("phone_number"),
                    WhatsAppJidKind.PHONE,
                )
                or (jid if jid_kind is WhatsAppJidKind.PHONE else "")
                or str(existing.get("phone_jid", ""))
            )
            lid_jid = (
                _alias_jid(
                    contact.get("lid_jid") or contact.get("lid"), WhatsAppJidKind.LID
                )
                or (jid if jid_kind is WhatsAppJidKind.LID else "")
                or str(existing.get("lid_jid", ""))
            )
            name = clean_text(contact.get("name"), 240) or str(existing.get("name", ""))
            notify_name = clean_text(contact.get("notify_name"), 240) or str(
                existing.get("notify_name", "")
            )
            verified_name = clean_text(contact.get("verified_name"), 240) or str(
                existing.get("verified_name", "")
            )
            phone = (
                normalize_phone(contact.get("phone"))
                or phone_from_jid(phone_jid)
                or str(existing.get("phone", ""))
            )
            search_text = build_search_text(
                (name, notify_name, verified_name, phone, phone_jid, lid_jid, jid)
            )
            self._connection.execute(
                """
                INSERT INTO whatsapp_contacts
                    (jid, name, notify_name, verified_name, phone, phone_jid,
                     lid_jid, search_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    name = excluded.name,
                    notify_name = excluded.notify_name,
                    verified_name = excluded.verified_name,
                    phone = excluded.phone,
                    phone_jid = excluded.phone_jid,
                    lid_jid = excluded.lid_jid,
                    search_text = excluded.search_text,
                    updated_at = excluded.updated_at
                """,
                (
                    jid,
                    name,
                    notify_name,
                    verified_name,
                    phone,
                    phone_jid,
                    lid_jid,
                    search_text,
                    max(
                        _number(contact.get("updated_at")),
                        _number(existing.get("updated_at")),
                    ),
                ),
            )
            self._connection.commit()

    def upsert_chat(self, chat: dict[str, Any]) -> None:
        """Store one chat without conflating LID, phone and group identities."""

        jid = clean_text(chat.get("jid"), 160)
        if not is_supported_jid(jid):
            return
        with self._lock:
            existing = _row_dict(
                self._connection.execute(
                    "SELECT * FROM whatsapp_chats WHERE jid = ?", (jid,)
                ).fetchone()
            )
            name = clean_text(chat.get("name"), 240) or str(existing.get("name", ""))
            message_id = clean_text(chat.get("last_message_id"), 256) or str(
                existing.get("last_message_id", "")
            )
            message_at = max(
                _number(chat.get("last_message_at")),
                _number(existing.get("last_message_at")),
            )
            updated_at = max(
                _number(chat.get("updated_at")), _number(existing.get("updated_at"))
            )
            self._connection.execute(
                """
                INSERT INTO whatsapp_chats
                    (jid, name, search_text, is_group, unread_count, archived,
                     pinned, muted_until, last_message_id, last_message_at,
                     updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    name = excluded.name,
                    search_text = excluded.search_text,
                    is_group = excluded.is_group,
                    unread_count = excluded.unread_count,
                    archived = excluded.archived,
                    pinned = excluded.pinned,
                    muted_until = excluded.muted_until,
                    last_message_id = excluded.last_message_id,
                    last_message_at = excluded.last_message_at,
                    updated_at = excluded.updated_at
                """,
                (
                    jid,
                    name,
                    build_search_text((name, jid)),
                    int(classify_jid(jid) is WhatsAppJidKind.GROUP),
                    max(
                        0,
                        _number(
                            chat.get("unread_count", existing.get("unread_count", 0))
                        ),
                    ),
                    int(bool(chat.get("archived", existing.get("archived", 0)))),
                    max(0, _number(chat.get("pinned", existing.get("pinned", 0)))),
                    max(
                        0,
                        _number(
                            chat.get("muted_until", existing.get("muted_until", 0))
                        ),
                    ),
                    message_id,
                    message_at,
                    updated_at,
                ),
            )
            self._connection.commit()

    def upsert_message(self, message: dict[str, Any]) -> None:
        """Store one message while preserving the complete Baileys message key."""

        jid = clean_text(message.get("jid"), 160)
        message_id = clean_text(message.get("message_id"), 256)
        if not is_supported_jid(jid, allow_status=True) or not message_id:
            return
        with self._lock:
            existing = _row_dict(
                self._connection.execute(
                    """
                    SELECT * FROM whatsapp_messages
                    WHERE jid = ? AND message_id = ?
                    """,
                    (jid, message_id),
                ).fetchone()
            )
            remote_jid_alt = clean_text(message.get("remote_jid_alt"), 160) or str(
                existing.get("remote_jid_alt", "")
            )
            participant = clean_text(message.get("participant"), 160) or str(
                existing.get("participant", "")
            )
            participant_alt = clean_text(message.get("participant_alt"), 160) or str(
                existing.get("participant_alt", "")
            )
            sender = (
                clean_text(message.get("sender"), 160)
                or participant
                or participant_alt
                or str(existing.get("sender", ""))
            )
            text = clean_text(message.get("text"), _MAX_TEXT) or str(
                existing.get("text", "")
            )
            message_type = clean_text(message.get("message_type"), 80)
            if not message_type or message_type == "unknown":
                message_type = str(existing.get("message_type", "unknown")) or "unknown"
            message_at = max(
                _number(message.get("message_at")), _number(existing.get("message_at"))
            )
            updated_at = max(
                _number(message.get("updated_at")), _number(existing.get("updated_at"))
            )
            message_ref = str(existing.get("message_ref", "")) or new_message_ref()
            self._connection.execute(
                """
                INSERT INTO whatsapp_messages
                    (message_id, jid, message_ref, remote_jid_alt, sender,
                     participant, participant_alt, text, message_type, from_me,
                     message_at, quoted_message_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(jid, message_id) DO UPDATE SET
                    message_ref = whatsapp_messages.message_ref,
                    remote_jid_alt = excluded.remote_jid_alt,
                    sender = excluded.sender,
                    participant = excluded.participant,
                    participant_alt = excluded.participant_alt,
                    text = excluded.text,
                    message_type = excluded.message_type,
                    from_me = excluded.from_me,
                    message_at = excluded.message_at,
                    quoted_message_id = excluded.quoted_message_id,
                    updated_at = excluded.updated_at
                """,
                (
                    message_id,
                    jid,
                    message_ref,
                    remote_jid_alt,
                    sender,
                    participant,
                    participant_alt,
                    text,
                    message_type,
                    int(bool(message.get("from_me", existing.get("from_me", 0)))),
                    message_at,
                    clean_text(message.get("quoted_message_id"), 256)
                    or str(existing.get("quoted_message_id", "")),
                    updated_at,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO whatsapp_chats
                    (jid, search_text, is_group, last_message_id,
                     last_message_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(jid) DO UPDATE SET
                    last_message_id = excluded.last_message_id,
                    last_message_at = MAX(
                        whatsapp_chats.last_message_at,
                        excluded.last_message_at
                    ),
                    updated_at = MAX(whatsapp_chats.updated_at, excluded.updated_at)
                """,
                (
                    jid,
                    build_search_text((jid,)),
                    int(classify_jid(jid) is WhatsAppJidKind.GROUP),
                    message_id,
                    message_at,
                    updated_at,
                ),
            )
            self._connection.commit()

    def delete_chat(self, jid: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM whatsapp_chats WHERE jid = ?", (clean_text(jid, 160),)
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["WhatsAppStore", "default_database_path"]
