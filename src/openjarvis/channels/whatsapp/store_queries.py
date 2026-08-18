"""Read/query mixin for the WhatsApp SQLite store."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .identity import (
    WhatsAppJidKind,
    classify_jid,
    clean_text,
    fold_search,
    match_rank,
    normalize_phone,
    phone_from_jid,
)

_MAX_QUERY = 160
_PHONE_QUERY_RE = re.compile(r"^[+()0-9. -]+$")
_MESSAGE_REF_RE = re.compile(r"^wam_[A-Za-z0-9_-]{16,64}$")


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class WhatsAppStoreQueries:
    """Bounded reads shared by the concrete store implementation."""

    _connection: sqlite3.Connection
    _lock: Any

    def search_contacts(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Search the complete personal-contact index, then rank and limit."""

        raw_query = clean_text(query, _MAX_QUERY)
        normalized = fold_search(raw_query)
        bounded = min(100, max(1, int(limit)))
        numeric = bool(raw_query and _PHONE_QUERY_RE.fullmatch(raw_query))
        digits = normalize_phone(raw_query) if numeric else ""
        with self._lock:
            if not normalized:
                rows = self._connection.execute(
                    """
                    SELECT * FROM whatsapp_contacts
                    WHERE jid LIKE '%@s.whatsapp.net' OR jid LIKE '%@lid'
                    ORDER BY name = '', name COLLATE NOCASE,
                             notify_name COLLATE NOCASE, updated_at DESC
                    LIMIT ?
                    """,
                    (bounded,),
                ).fetchall()
            elif numeric:
                pattern = _like(digits)
                rows = self._connection.execute(
                    """
                    SELECT * FROM whatsapp_contacts
                    WHERE phone LIKE ? ESCAPE '\\'
                       OR phone_jid LIKE ? ESCAPE '\\'
                    """,
                    (pattern, pattern),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT * FROM whatsapp_contacts
                    WHERE search_text LIKE ? ESCAPE '\\'
                    """,
                    (_like(normalized),),
                ).fetchall()

        ranked: list[tuple[int, str, int, dict[str, Any]]] = []
        seen: set[str] = set()
        for row in rows:
            item = dict(row)
            kind = classify_jid(item["jid"])
            if kind not in {WhatsAppJidKind.PHONE, WhatsAppJidKind.LID}:
                continue
            candidates = (
                (item["phone"], item["phone_jid"])
                if numeric
                else (
                    item["name"],
                    item["notify_name"],
                    item["verified_name"],
                    item["phone"],
                    item["phone_jid"],
                    item["lid_jid"],
                    item["jid"],
                )
            )
            rank = match_rank(digits if numeric else normalized, candidates)
            if rank is None:
                continue
            identity_key = item["phone_jid"] or item["lid_jid"] or item["jid"]
            if identity_key in seen:
                continue
            seen.add(identity_key)
            item["display_name"] = (
                item["name"]
                or item["notify_name"]
                or item["verified_name"]
                or item["phone"]
                or item["jid"]
            )
            item["jid_kind"] = kind.value
            item.pop("search_text", None)
            ranked.append(
                (
                    rank,
                    fold_search(item["display_name"]),
                    -int(item["updated_at"]),
                    item,
                )
            )
        ranked.sort(key=lambda entry: entry[:3])
        return [entry[3] for entry in ranked[:bounded]]

    def search_chats(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Search all chats with contact aliases and collision-safe phone rules."""

        raw_query = clean_text(query, _MAX_QUERY)
        normalized = fold_search(raw_query)
        bounded = min(100, max(1, int(limit)))
        numeric = bool(raw_query and _PHONE_QUERY_RE.fullmatch(raw_query))
        digits = normalize_phone(raw_query) if numeric else ""
        with self._lock:
            chats = [
                dict(row)
                for row in self._connection.execute(
                    """
                    SELECT * FROM whatsapp_chats
                    ORDER BY last_message_at DESC, updated_at DESC
                    """
                ).fetchall()
            ]
            contacts = [
                dict(row)
                for row in self._connection.execute(
                    "SELECT * FROM whatsapp_contacts"
                ).fetchall()
            ]
        aliases: dict[str, list[dict[str, Any]]] = {}
        for contact in contacts:
            for alias in {contact["jid"], contact["phone_jid"], contact["lid_jid"]}:
                if alias:
                    aliases.setdefault(str(alias), []).append(contact)

        ranked: list[tuple[int, int, int, dict[str, Any]]] = []
        for chat in chats:
            kind = classify_jid(chat["jid"])
            if kind is WhatsAppJidKind.UNKNOWN:
                continue
            linked = aliases.get(str(chat["jid"]), [])
            if numeric:
                if kind is WhatsAppJidKind.GROUP:
                    continue
                candidates = [phone_from_jid(chat["jid"])]
                candidates.extend(str(contact["phone"]) for contact in linked)
                candidates.extend(str(contact["phone_jid"]) for contact in linked)
                rank = match_rank(digits, candidates)
            else:
                candidates: list[Any] = [chat["name"], chat["jid"]]
                for contact in linked:
                    candidates.extend(
                        (
                            contact["name"],
                            contact["notify_name"],
                            contact["verified_name"],
                            contact["phone"],
                        )
                    )
                rank = match_rank(normalized, candidates)
            if rank is None:
                continue
            display_name = str(chat["name"] or "")
            if not display_name:
                for contact in linked:
                    display_name = str(
                        contact["name"]
                        or contact["notify_name"]
                        or contact["verified_name"]
                        or contact["phone"]
                        or ""
                    )
                    if display_name:
                        break
            chat["display_name"] = display_name or str(chat["jid"])
            chat["jid_kind"] = kind.value
            chat["is_group"] = kind is WhatsAppJidKind.GROUP
            chat["archived"] = bool(chat["archived"])
            chat.pop("search_text", None)
            ranked.append(
                (rank, -int(chat["last_message_at"]), -int(chat["updated_at"]), chat)
            )
        ranked.sort(key=lambda entry: entry[:3])
        return [entry[3] for entry in ranked[:bounded]]

    def list_messages(
        self, jid: str, *, query: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        normalized_jid = clean_text(jid, 160)
        normalized_query = clean_text(query, _MAX_QUERY)
        bounded = min(200, max(1, int(limit)))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT message_ref, message_id, jid, sender, text, message_type,
                       from_me, message_at, quoted_message_id, updated_at
                FROM whatsapp_messages
                WHERE jid = ? AND (? = '' OR text LIKE ? ESCAPE '\\')
                ORDER BY message_at DESC, updated_at DESC
                LIMIT ?
                """,
                (normalized_jid, normalized_query, _like(normalized_query), bounded),
            ).fetchall()
        messages = []
        for row in reversed(rows):
            item = dict(row)
            item["from_me"] = bool(item["from_me"])
            messages.append(item)
        return messages

    def get_message_by_ref(self, message_ref: str) -> dict[str, Any] | None:
        """Resolve an opaque public reference to the full internal message key."""

        reference = clean_text(message_ref, 80)
        if not _MESSAGE_REF_RE.fullmatch(reference):
            return None
        with self._lock:
            row = self._connection.execute(
                """
                SELECT message_ref, message_id, jid, remote_jid_alt, sender,
                       participant, participant_alt, text, message_type, from_me,
                       message_at
                FROM whatsapp_messages WHERE message_ref = ?
                """,
                (reference,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["from_me"] = bool(item["from_me"])
        return item

    def list_message_keys(
        self,
        jid: str,
        message_ids: list[str] | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return bounded internal Baileys keys for read/reply operations."""

        normalized_jid = clean_text(jid, 160)
        requested = [clean_text(value, 256) for value in (message_ids or [])]
        requested = [value for value in requested if value][:50]
        bounded = min(50, max(1, int(limit)))
        params: list[Any] = [normalized_jid]
        predicate = ""
        if requested:
            placeholders = ",".join("?" for _ in requested)
            predicate = f" AND message_id IN ({placeholders})"
            params.extend(requested)
        params.append(bounded)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT message_id, jid, remote_jid_alt, participant,
                       participant_alt, sender, from_me, message_at
                FROM whatsapp_messages
                WHERE jid = ?{predicate}
                ORDER BY message_at DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [{**dict(row), "from_me": bool(row["from_me"])} for row in rows]

    def oldest_message(self, jid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT message_id, jid, sender, participant, participant_alt,
                       remote_jid_alt, message_at, from_me
                FROM whatsapp_messages WHERE jid = ?
                ORDER BY message_at ASC, updated_at ASC LIMIT 1
                """,
                (clean_text(jid, 160),),
            ).fetchone()
        return dict(row) if row else None

    def summary(self, jid: str, *, limit: int = 50) -> dict[str, Any]:
        messages = self.list_messages(jid, limit=limit)
        participants = sorted(
            {message["sender"] for message in messages if message["sender"]}
        )
        return {
            "jid": clean_text(jid, 160),
            "message_count": len(messages),
            "participants": participants[:50],
            "first_message_at": messages[0]["message_at"] if messages else 0,
            "last_message_at": messages[-1]["message_at"] if messages else 0,
            "messages": messages,
        }


__all__ = ["WhatsAppStoreQueries"]
