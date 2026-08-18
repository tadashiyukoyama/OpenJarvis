"""SQLite schema and in-place migrations for the WhatsApp local index."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterable

from .identity import build_search_text, classify_jid, phone_from_jid

_TABLES_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS whatsapp_contacts (
    jid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    notify_name TEXT NOT NULL DEFAULT '',
    verified_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_jid TEXT NOT NULL DEFAULT '',
    lid_jid TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS whatsapp_chats (
    jid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    is_group INTEGER NOT NULL DEFAULT 0,
    unread_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    muted_until INTEGER NOT NULL DEFAULT 0,
    last_message_id TEXT NOT NULL DEFAULT '',
    last_message_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    message_id TEXT NOT NULL,
    jid TEXT NOT NULL,
    message_ref TEXT NOT NULL DEFAULT '',
    remote_jid_alt TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL DEFAULT '',
    participant TEXT NOT NULL DEFAULT '',
    participant_alt TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    message_type TEXT NOT NULL DEFAULT 'unknown',
    from_me INTEGER NOT NULL DEFAULT 0,
    message_at INTEGER NOT NULL DEFAULT 0,
    quoted_message_id TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (jid, message_id)
);
"""


_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_whatsapp_contacts_name
    ON whatsapp_contacts(name, notify_name, verified_name);
CREATE INDEX IF NOT EXISTS idx_whatsapp_contacts_search
    ON whatsapp_contacts(search_text);
CREATE INDEX IF NOT EXISTS idx_whatsapp_contacts_aliases
    ON whatsapp_contacts(phone_jid, lid_jid);
CREATE INDEX IF NOT EXISTS idx_whatsapp_chats_updated
    ON whatsapp_chats(last_message_at DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_whatsapp_chats_search
    ON whatsapp_chats(search_text);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_chat_time
    ON whatsapp_messages(jid, message_at DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_text
    ON whatsapp_messages(text);
CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_messages_ref
    ON whatsapp_messages(message_ref) WHERE message_ref <> '';
"""


_MIGRATION_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "whatsapp_contacts": (
        ("phone_jid", "TEXT NOT NULL DEFAULT ''"),
        ("lid_jid", "TEXT NOT NULL DEFAULT ''"),
        ("search_text", "TEXT NOT NULL DEFAULT ''"),
    ),
    "whatsapp_chats": (("search_text", "TEXT NOT NULL DEFAULT ''"),),
    "whatsapp_messages": (
        ("message_ref", "TEXT NOT NULL DEFAULT ''"),
        ("remote_jid_alt", "TEXT NOT NULL DEFAULT ''"),
        ("participant", "TEXT NOT NULL DEFAULT ''"),
        ("participant_alt", "TEXT NOT NULL DEFAULT ''"),
    ),
}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _ensure_columns(connection: sqlite3.Connection) -> None:
    for table, definitions in _MIGRATION_COLUMNS.items():
        present = _columns(connection, table)
        for column, definition in definitions:
            if column not in present:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )


def _rows(connection: sqlite3.Connection, sql: str) -> Iterable[sqlite3.Row]:
    return connection.execute(sql).fetchall()


def _backfill_contacts(connection: sqlite3.Connection) -> None:
    rows = _rows(
        connection,
        """
        SELECT jid, name, notify_name, verified_name, phone, phone_jid,
               lid_jid, search_text
        FROM whatsapp_contacts
        WHERE search_text = ''
           OR (phone_jid = '' AND jid LIKE '%@s.whatsapp.net')
           OR (lid_jid = '' AND jid LIKE '%@lid')
        """,
    )
    for row in rows:
        jid = str(row["jid"])
        kind = classify_jid(jid).value
        phone_jid = str(row["phone_jid"] or "")
        lid_jid = str(row["lid_jid"] or "")
        if kind == "phone" and not phone_jid:
            phone_jid = jid
        if kind == "lid" and not lid_jid:
            lid_jid = jid
        phone = str(row["phone"] or "") or phone_from_jid(phone_jid)
        search_text = build_search_text(
            (
                row["name"],
                row["notify_name"],
                row["verified_name"],
                phone,
                phone_jid,
                lid_jid,
                jid,
            )
        )
        connection.execute(
            """
            UPDATE whatsapp_contacts
            SET phone = ?, phone_jid = ?, lid_jid = ?, search_text = ?
            WHERE jid = ?
            """,
            (phone, phone_jid, lid_jid, search_text, jid),
        )


def _backfill_chats(connection: sqlite3.Connection) -> None:
    rows = _rows(
        connection,
        "SELECT jid, name FROM whatsapp_chats WHERE search_text = ''",
    )
    for row in rows:
        connection.execute(
            "UPDATE whatsapp_chats SET search_text = ? WHERE jid = ?",
            (build_search_text((row["name"], row["jid"])), row["jid"]),
        )


def _new_message_ref() -> str:
    return f"wam_{secrets.token_urlsafe(18)}"


def _backfill_message_refs(connection: sqlite3.Connection) -> None:
    rows = _rows(
        connection,
        """
        SELECT jid, message_id FROM whatsapp_messages
        WHERE message_ref = '' OR message_ref IS NULL
        """,
    )
    for row in rows:
        connection.execute(
            """
            UPDATE whatsapp_messages SET message_ref = ?
            WHERE jid = ? AND message_id = ?
            """,
            (_new_message_ref(), row["jid"], row["message_id"]),
        )


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create or migrate the schema atomically and idempotently."""

    # Existing databases need columns before indexes that reference them.
    connection.executescript(_TABLES_SQL)
    _ensure_columns(connection)
    connection.executescript(_INDEXES_SQL)
    _backfill_contacts(connection)
    _backfill_chats(connection)
    _backfill_message_refs(connection)
    connection.commit()


def new_message_ref() -> str:
    """Return an opaque public reference that reveals no WhatsApp key data."""

    return _new_message_ref()


__all__ = ["initialize_schema", "new_message_ref"]
