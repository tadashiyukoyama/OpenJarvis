from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.adapters.gmail import GmailAdapter
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class _DisconnectedOAuth:
    connector_id = "gmail"

    def is_connected(self):
        return False


class _Imap:
    connector_id = "gmail_imap"

    def is_connected(self):
        return True

    def search_messages(self, query, max_results):
        return [
            {
                "id": "provider-message-7",
                "thread_id": "provider-thread-8",
                "from": "Marta <marta@example.com>",
                "subject": query,
                "body": "bounded body",
            }
        ][:max_results]

    def read_message(self, message_id):
        return {
            "id": message_id,
            "from": "Marta",
            "subject": "Read",
            "body": "message",
        }

    def read_thread(self, thread_id):
        return [
            {
                "id": "provider-message-thread",
                "thread_id": thread_id,
                "from": "Marta",
                "subject": "Thread",
                "body": "thread body",
            }
        ]


class _OAuth(_Imap):
    connector_id = "gmail"

    def __init__(self):
        self.sent = None

    def send_message(self, **kwargs):
        self.sent = kwargs
        return {"id": "provider-sent-id"}

    def archive_message(self, message_id):
        self.archived = message_id

    def delete_message(self, message_id):
        self.trashed = message_id


@pytest.fixture
def adapter_context():
    return AdapterContext("s1", "D:/project", "t1", "partition", "request")


def _adapter(tmp_path: Path, oauth, imap) -> GmailAdapter:
    store = JarvisAgentStore(tmp_path / "agent.sqlite3")
    return GmailAdapter(
        ReferenceService(store),
        oauth_factory=lambda: oauth,
        imap_factory=lambda: imap,
    )


def test_imap_exposes_reads_but_not_oauth_mutations(
    tmp_path: Path, adapter_context: AdapterContext
) -> None:
    adapter = _adapter(tmp_path, _DisconnectedOAuth(), _Imap())
    providers = adapter.provider_capabilities()

    assert providers["gmail"].capabilities == frozenset(
        {"gmail.search", "gmail.read", "gmail.thread"}
    )
    assert not providers["gmail_oauth"].connected

    result = adapter.execute(
        "gmail.search", {"query": "from:Marta", "max_results": 10}, adapter_context
    )
    message = result.data["messages"][0]
    assert message["message_ref"].startswith("gmr_")
    assert "provider-message-7" not in str(result.as_dict())
    assert "provider-thread-8" not in str(result.as_dict())

    with pytest.raises(JarvisAgentError) as error:
        adapter.prepare(
            "gmail.send",
            {"to": "x@example.com", "body": "hello"},
            adapter_context,
        )
    assert error.value.code == "CAPABILITY_NOT_AVAILABLE"


def test_oauth_mutation_uses_resolved_exact_payload(
    tmp_path: Path, adapter_context: AdapterContext
) -> None:
    oauth = _OAuth()
    adapter = _adapter(tmp_path, oauth, _Imap())
    prepared = adapter.prepare(
        "gmail.send",
        {
            "to": "person@example.com",
            "subject": "Subject",
            "body": "Exact body",
        },
        adapter_context,
    )

    result = adapter.execute("gmail.send", prepared.arguments, adapter_context)

    assert result.status == "completed"
    assert oauth.sent == {
        "to": "person@example.com",
        "subject": "Subject",
        "body": "Exact body",
        "cc": "",
    }


def test_all_gmail_reads_use_opaque_references(
    tmp_path: Path, adapter_context: AdapterContext
) -> None:
    adapter = _adapter(tmp_path, _DisconnectedOAuth(), _Imap())
    search = adapter.execute(
        "gmail.search", {"query": "from:Marta", "max_results": 10}, adapter_context
    )
    message = search.data["messages"][0]

    unread = adapter.execute("gmail.list_unread", {"max_results": 5}, adapter_context)
    read = adapter.execute(
        "gmail.read_message", {"message_ref": message["message_ref"]}, adapter_context
    )
    thread = adapter.execute(
        "gmail.read_thread", {"thread_ref": message["thread_ref"]}, adapter_context
    )

    for result in (search, unread, read, thread):
        serialized = str(result.as_dict())
        assert result.status == "completed"
        assert "provider-message-7" not in serialized
        assert "provider-thread-8" not in serialized


def test_oauth_archive_and_trash_resolve_the_approved_reference(
    tmp_path: Path, adapter_context: AdapterContext
) -> None:
    oauth = _OAuth()
    adapter = _adapter(tmp_path, oauth, _Imap())
    search = adapter.execute(
        "gmail.search", {"query": "archive", "max_results": 1}, adapter_context
    )
    message_ref = search.data["messages"][0]["message_ref"]

    archive = adapter.prepare(
        "gmail.archive", {"message_ref": message_ref}, adapter_context
    )
    trash = adapter.prepare(
        "gmail.trash", {"message_ref": message_ref}, adapter_context
    )
    adapter.execute("gmail.archive", archive.arguments, adapter_context)
    adapter.execute("gmail.trash", trash.arguments, adapter_context)

    assert oauth.archived == "provider-message-7"
    assert oauth.trashed == "provider-message-7"
    assert "provider-message-7" not in str(archive.preview)
    assert "provider-message-7" not in str(trash.preview)
