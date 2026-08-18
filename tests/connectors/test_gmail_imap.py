"""Tests for live read/search operations on the synchronized Gmail IMAP source."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.connectors.gmail_imap import GmailIMAPConnector


def _connector(tmp_path: Path) -> GmailIMAPConnector:
    connector = GmailIMAPConnector(credentials_path=str(tmp_path / "gmail.json"))
    connector.handle_callback("user@gmail.com:app-password")
    return connector


def _raw_email() -> bytes:
    return (
        b"From: Marta <marta@inova-ts.com.br>\r\n"
        b"To: user@gmail.com\r\n"
        b"Subject: Projeto OpenJarvis\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <marta-1@inova-ts.com.br>\r\n"
        b"\r\n"
        b"Mensagem sincronizada pelo Data Source."
    )


def _mock_imap() -> MagicMock:
    imap = MagicMock()
    imap.login.return_value = ("OK", [])
    imap.select.return_value = ("OK", [])
    imap.uid.return_value = ("OK", [(b"RFC822", _raw_email())])
    imap.logout.return_value = ("OK", [])
    return imap


def test_search_messages_uses_imap_query_and_returns_bounded_message(tmp_path: Path):
    connector = _connector(tmp_path)
    imap = _mock_imap()
    imap.uid.side_effect = [
        ("OK", [b"1 2"]),
        ("OK", [(b"RFC822", _raw_email())]),
    ]
    with patch("openjarvis.connectors.gmail_imap.imaplib.IMAP4_SSL", return_value=imap):
        results = connector.search_messages("from:Marta inova-ts.com.br", 1)

    assert len(results) == 1
    assert results[0]["id"] == "2"
    assert results[0]["message_id"] == "<marta-1@inova-ts.com.br>"
    assert imap.uid.call_args_list[0].args == ("search", None, "FROM", "Marta")
    imap.logout.assert_called_once()


def test_read_message_accepts_imap_uid(tmp_path: Path):
    connector = _connector(tmp_path)
    imap = _mock_imap()
    with patch("openjarvis.connectors.gmail_imap.imaplib.IMAP4_SSL", return_value=imap):
        message = connector.read_message("1")

    assert message["id"] == "1"
    assert "sincronizada" in message["body"]
    imap.uid.assert_called_once_with("fetch", b"1", "(RFC822)")
