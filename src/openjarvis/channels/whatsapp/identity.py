"""Canonical WhatsApp identity parsing and search helpers.

Baileys 7 may expose the same person through a phone-number JID (PN) and a
local-identifier JID (LID).  This module is the single authority for identity
classification so the store, API validation and bridge commands cannot drift.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Iterable


class WhatsAppJidKind(str, Enum):
    """Supported WhatsApp address classes."""

    PHONE = "phone"
    LID = "lid"
    GROUP = "group"
    STATUS = "status"
    UNKNOWN = "unknown"


_PHONE_JID_RE = re.compile(r"^(?P<user>[0-9]+)@s\.whatsapp\.net$")
_LID_JID_RE = re.compile(r"^(?P<user>[0-9]+)@lid$")
_GROUP_JID_RE = re.compile(r"^(?P<user>[0-9]+(?:-[0-9]+)?)@g\.us$")
_STATUS_JID = "status@broadcast"


def clean_text(value: object, limit: int) -> str:
    """Return bounded, stripped text for data crossing the bridge boundary."""

    return str(value or "").strip()[:limit]


def fold_search(value: object) -> str:
    """Normalize accents, case and whitespace for deterministic local search."""

    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return " ".join(without_marks.split())


def classify_jid(value: object) -> WhatsAppJidKind:
    """Classify one exact WhatsApp JID without accepting fuzzy variants."""

    jid = clean_text(value, 160)
    if _PHONE_JID_RE.fullmatch(jid):
        return WhatsAppJidKind.PHONE
    if _LID_JID_RE.fullmatch(jid):
        return WhatsAppJidKind.LID
    if _GROUP_JID_RE.fullmatch(jid):
        return WhatsAppJidKind.GROUP
    if jid == _STATUS_JID:
        return WhatsAppJidKind.STATUS
    return WhatsAppJidKind.UNKNOWN


def is_supported_jid(value: object, *, allow_status: bool = False) -> bool:
    """Return whether ``value`` is safe for an OpenJarvis WhatsApp operation."""

    kind = classify_jid(value)
    return kind in {
        WhatsAppJidKind.PHONE,
        WhatsAppJidKind.LID,
        WhatsAppJidKind.GROUP,
    } or (allow_status and kind is WhatsAppJidKind.STATUS)


def phone_from_jid(value: object) -> str:
    """Extract a phone number only from a PN JID, never from a group or LID."""

    match = _PHONE_JID_RE.fullmatch(clean_text(value, 160))
    return match.group("user") if match else ""


def normalize_phone(value: object) -> str:
    """Keep only decimal digits from a user-entered phone query."""

    return "".join(char for char in str(value or "") if char.isdecimal())


def build_search_text(values: Iterable[object]) -> str:
    """Build one folded search document from bounded identity fields."""

    return fold_search(" ".join(str(value or "") for value in values))


def match_rank(query: str, candidates: Iterable[object]) -> int | None:
    """Rank exact, prefix, token-prefix and substring matches.

    Lower values are better. ``None`` means no match.  Ranking is performed
    after SQL has filtered the complete dataset, so the result is independent
    from insertion order or the number of synchronized contacts.
    """

    needle = fold_search(query)
    folded = [fold_search(value) for value in candidates if str(value or "").strip()]
    if not needle:
        return 50
    if any(value == needle for value in folded):
        return 0
    if any(value.startswith(needle) for value in folded):
        return 10
    if any(
        any(token.startswith(needle) for token in value.split()) for value in folded
    ):
        return 20
    if any(needle in value for value in folded):
        return 30
    return None


__all__ = [
    "WhatsAppJidKind",
    "build_search_text",
    "classify_jid",
    "clean_text",
    "fold_search",
    "is_supported_jid",
    "match_rank",
    "normalize_phone",
    "phone_from_jid",
]
