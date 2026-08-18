"""Gmail IMAP connector — reads email via IMAP with app password.

Simpler alternative to the OAuth-based Gmail connector.
Uses Python's built-in imaplib + email modules (no dependencies).

Setup: generate an app password at https://myaccount.google.com/apppasswords
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import re
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gmail_imap.json")


def _decode_subject(raw: str) -> str:
    """Decode a possibly-encoded email subject header."""
    if not raw:
        return ""
    decoded_parts = decode_header(raw)
    return "".join(
        part.decode(enc or "utf-8", errors="replace")
        if isinstance(part, bytes)
        else part
        for part, enc in decoded_parts
    )


def _extract_text_body(msg: email_lib.message.Message) -> str:
    """Extract plain-text body from an email Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        # Fallback: try text/html
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace")
    return ""


def _parse_date(msg: email_lib.message.Message) -> datetime:
    """Parse the Date header, falling back to now."""
    date_str = msg.get("Date", "")
    if not date_str:
        return datetime.now()
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now()


def _message_field(msg: email_lib.message.Message, name: str) -> str:
    """Return a decoded, single-line header value."""
    value = _decode_subject(msg.get(name, ""))
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


@ConnectorRegistry.register("gmail_imap")
class GmailIMAPConnector(BaseConnector):
    """Gmail connector using IMAP + app password.

    No OAuth needed — just an email address and app password.
    """

    connector_id = "gmail_imap"
    display_name = "Gmail (IMAP)"
    auth_type = "oauth"  # Reuses credential storage pattern
    _default_imap_host = "imap.gmail.com"

    def __init__(
        self,
        email_address: str = "",
        app_password: str = "",
        credentials_path: str = "",
        *,
        imap_host: str = "",
        max_messages: Optional[int] = None,
    ) -> None:
        self._email = email_address
        self._password = app_password
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._imap_host = imap_host or self._default_imap_host
        # ``None`` means "no cap" — the full inbox is indexed. A positive
        # value is still honored for tests that want a bounded scan.
        self._max_messages = max_messages
        self._items_synced = 0
        self._items_total = 0

    def _resolve_credentials(self) -> tuple[str, str]:
        """Return (email, password) — direct args take priority."""
        if self._email and self._password:
            return self._email, self._password
        tokens = load_tokens(self._credentials_path)
        if tokens:
            return tokens.get("email", ""), tokens.get("password", "")
        return "", ""

    def is_connected(self) -> bool:
        em, pw = self._resolve_credentials()
        return bool(em and pw)

    def _open_mailbox(self) -> Any:
        """Open the configured mailbox without exposing credentials."""
        em, pw = self._resolve_credentials()
        if not em or not pw:
            raise RuntimeError("Gmail IMAP Data Source não está conectado")
        imap = imaplib.IMAP4_SSL(self._imap_host)
        try:
            imap.login(em, pw)
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError("Não foi possível selecionar a caixa de entrada")
        except Exception:
            try:
                imap.logout()
            except Exception:
                pass
            raise
        return imap

    @staticmethod
    def _raw_message(data: Any) -> bytes:
        """Extract RFC822 bytes from the different IMAP fetch shapes."""
        for item in data or []:
            if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
                return item[1]
        raise ValueError("Mensagem IMAP não encontrada")

    @staticmethod
    def _tool_message(
        msg: email_lib.message.Message, sequence_id: str
    ) -> Dict[str, Any]:
        body = _extract_text_body(msg)
        return {
            "id": sequence_id,
            "message_id": _message_field(msg, "Message-ID") or sequence_id,
            "thread_id": _message_field(msg, "In-Reply-To"),
            "from": _message_field(msg, "From"),
            "to": _message_field(msg, "To"),
            "subject": _message_field(msg, "Subject"),
            "date": _parse_date(msg).isoformat(),
            "snippet": " ".join(body.split())[:300],
            "body": body[:20_000],
        }

    @staticmethod
    def _query_criteria(query: str) -> tuple[list[str], list[str]]:
        """Translate the safe subset of Gmail search syntax to IMAP criteria."""
        tokens = re.findall(r"(?:[^\s\"]|\"[^\"]*\")+", query.strip())
        criteria = ["ALL"]
        free_text: list[str] = []
        for token in tokens:
            value = token.strip('"')
            if value.lower().startswith("from:") and len(value) > 5:
                criteria = ["FROM", value[5:]]
            elif value.lower().startswith("subject:") and len(value) > 8:
                criteria = ["SUBJECT", value[8:]]
            elif value.lower() == "is:unread":
                criteria = ["UNSEEN"]
            elif value:
                free_text.append(value.lower())
        return criteria, free_text

    def _fetch_tool_message(self, imap: Any, message_uid: str) -> Dict[str, Any]:
        status, data = imap.uid("fetch", message_uid.encode(), "(RFC822)")
        if status != "OK":
            raise ValueError("Mensagem IMAP não encontrada")
        msg = email_lib.message_from_bytes(self._raw_message(data))
        return self._tool_message(msg, message_uid)

    def search_messages(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search the synchronized IMAP Data Source and return bounded results."""
        bounded = min(25, max(1, int(max_results)))
        criteria, free_text = self._query_criteria(query)
        imap = self._open_mailbox()
        try:
            status, data = imap.uid("search", None, *criteria)
            if status != "OK" or not data:
                return []
            sequence_ids = list(reversed(data[0].split()))
            results: List[Dict[str, Any]] = []
            for raw_id in sequence_ids:
                sequence_id = raw_id.decode("ascii", errors="ignore")
                if not sequence_id:
                    continue
                try:
                    message = self._fetch_tool_message(imap, sequence_id)
                except (OSError, ValueError, IndexError, TypeError):
                    continue
                haystack = " ".join(
                    str(message.get(field, ""))
                    for field in ("from", "to", "subject", "body")
                ).lower()
                if free_text and not all(term in haystack for term in free_text):
                    continue
                results.append(message)
                if len(results) >= bounded:
                    break
            return results
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def read_message(self, message_id: str) -> Dict[str, Any]:
        """Read one message by its stable IMAP sequence ID or Message-ID header."""
        requested = message_id.strip()
        if not requested:
            raise ValueError("message_id inválido")
        imap = self._open_mailbox()
        try:
            if requested.isdigit():
                return self._fetch_tool_message(imap, requested)
            header_id = requested if requested.startswith("<") else f"<{requested}>"
            status, data = imap.uid("search", None, "HEADER", "Message-ID", header_id)
            if status != "OK" or not data or not data[0]:
                raise ValueError("Mensagem IMAP não encontrada")
            sequence_id = data[0].split()[-1].decode("ascii", errors="ignore")
            return self._fetch_tool_message(imap, sequence_id)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def disconnect(self) -> None:
        self._email = ""
        self._password = ""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return "https://myaccount.google.com/apppasswords"

    def handle_callback(self, code: str) -> None:
        # code format: "email:password"
        if ":" in code:
            em, pw = code.split(":", 1)
            save_tokens(
                self._credentials_path,
                {"email": em.strip(), "password": pw.strip()},
            )
        else:
            save_tokens(
                self._credentials_path,
                {"email": "", "password": code.strip()},
            )

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        em, pw = self._resolve_credentials()
        if not em or not pw:
            return

        imap = imaplib.IMAP4_SSL(self._imap_host)
        try:
            imap.login(em, pw)
        except imaplib.IMAP4.error as exc:
            logger.error("IMAP login failed: %s", exc)
            return

        imap.select("INBOX", readonly=True)

        # Always SEARCH ALL. IMAP has no native cursor that survives a
        # server restart, so applying the SyncEngine's ``since`` filter
        # during a partial backfill would silently skip the older
        # unprocessed messages. The pipeline-level dedup (_seen_doc_ids
        # set + INSERT OR IGNORE in KnowledgeStore) makes re-scanning
        # already-indexed messages cheap, so resume is correct as long
        # as we keep enumerating the full inbox.
        _, data = imap.search(None, "ALL")
        msg_ids = data[0].split()
        self._items_total = len(msg_ids)

        # Newest-first iteration so Deep Research becomes useful while
        # the long tail of older mail finishes indexing in the
        # background. IMAP returns sequence numbers in arrival order
        # (oldest -> newest), so reversing puts the most recent first.
        ordered = list(reversed(msg_ids))
        if self._max_messages is not None and self._max_messages > 0:
            ordered = ordered[: self._max_messages]
        synced = 0

        for mid in ordered:
            try:
                _, msg_data = imap.fetch(mid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
            except Exception:
                continue

            subject = _decode_subject(msg.get("Subject", ""))
            sender = msg.get("From", "")
            to = msg.get("To", "")
            body = _extract_text_body(msg)
            timestamp = _parse_date(msg)
            message_id = msg.get("Message-ID", mid.decode())

            synced += 1
            yield Document(
                doc_id=f"gmail:{message_id}",
                source="gmail",
                doc_type="email",
                content=body,
                title=subject,
                author=sender,
                participants=[a.strip() for a in (to or "").split(",") if a.strip()],
                timestamp=timestamp,
                thread_id=msg.get("In-Reply-To", ""),
                url="https://mail.google.com/mail/u/0/#inbox",
                metadata={
                    "message_id": message_id,
                },
            )

        imap.logout()
        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
        )

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="gmail_search_emails",
                description="Search Gmail messages by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_list_unread",
                description="List recent unread emails.",
                parameters={
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Max results",
                            "default": 10,
                        },
                    },
                },
                category="communication",
            ),
        ]
