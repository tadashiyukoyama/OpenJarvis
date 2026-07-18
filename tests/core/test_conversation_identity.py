"""Offline tests for the provider-neutral conversation identity contract."""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest import TestCase

from openjarvis.core.conversation_identity import (
    ConversationBindingAlreadyBoundError,
    ConversationBindingKey,
    ConversationBindingOwnerError,
    ConversationBindingState,
    ConversationIdentity,
    SQLiteConversationBindingStore,
)


def _identity(
    conversation_id: str = "conversation-a",
    scope_id: str = "scope-a",
) -> ConversationIdentity:
    return ConversationIdentity(conversation_id, scope_id)


def _key(
    conversation_id: str = "conversation-a",
    scope_id: str = "scope-a",
    agent_name: str = "example-agent",
    external_runtime: str = "example-runtime",
) -> ConversationBindingKey:
    return ConversationBindingKey(
        _identity(conversation_id, scope_id),
        agent_name,
        external_runtime,
    )


class ConversationIdentityTests(TestCase):
    def test_conversation_id_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            ConversationIdentity("", "scope")
        with self.assertRaises(ValueError):
            ConversationIdentity("   ", "scope")

    def test_scope_id_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            ConversationIdentity("conversation", "")
        with self.assertRaises(ValueError):
            ConversationIdentity("conversation", "   ")

    def test_agent_name_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            ConversationBindingKey(_identity(), "", "runtime")

    def test_digest_is_deterministic(self) -> None:
        self.assertEqual(_key().digest, _key().digest)
        self.assertEqual(_key().digest, _key().key_digest)

    def test_digest_changes_for_different_conversations(self) -> None:
        self.assertNotEqual(
            _key("conversation-a").digest,
            _key("conversation-b").digest,
        )

    def test_digest_changes_for_different_scopes(self) -> None:
        self.assertNotEqual(
            _key(scope_id="scope-a").digest,
            _key(scope_id="scope-b").digest,
        )

    def test_digest_changes_for_different_agents(self) -> None:
        self.assertNotEqual(
            _key(agent_name="agent-a").digest,
            _key(agent_name="agent-b").digest,
        )

    def test_digest_changes_for_different_runtimes(self) -> None:
        self.assertNotEqual(
            _key(external_runtime="runtime-a").digest,
            _key(external_runtime="runtime-b").digest,
        )

    def test_identity_repr_does_not_expose_conversation_id(self) -> None:
        value = repr(_identity("private-conversation-id"))
        self.assertNotIn("private-conversation-id", value)

    def test_identity_repr_does_not_expose_scope_id(self) -> None:
        value = repr(_identity(scope_id="private-scope-id"))
        self.assertNotIn("private-scope-id", value)

    def test_binding_repr_does_not_expose_external_id(self) -> None:
        binding = _bound_binding("external-thread-id-that-must-stay-private")
        self.assertNotIn("external-thread-id-that-must-stay-private", repr(binding))


class SQLiteConversationBindingStoreTests(TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self._temporary_directory.name) / "bindings.db"
        self.store = SQLiteConversationBindingStore(self.database_path)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_schema_creation_is_idempotent(self) -> None:
        SQLiteConversationBindingStore(self.database_path)
        SQLiteConversationBindingStore(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'conversation_bindings'"
                ).fetchone()
            )
        finally:
            connection.close()

    def test_lookup_of_missing_key(self) -> None:
        self.assertIsNone(self.store.lookup(_key()))

    def test_first_reservation_is_acquired(self) -> None:
        result = self.store.reserve(_key(), "owner-a", 30, now=100)
        self.assertTrue(result.acquired)
        self.assertFalse(result.busy)
        self.assertEqual(result.state, ConversationBindingState.RESERVED)
        self.assertEqual(result.binding.state, ConversationBindingState.RESERVED)

    def test_second_reservation_returns_busy(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        result = self.store.reserve(key, "owner-b", 30, now=101)
        self.assertTrue(result.busy)
        self.assertFalse(result.acquired)
        self.assertEqual(result.state, ConversationBindingState.BUSY)

    def test_wrong_owner_cannot_complete(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        with self.assertRaises(ConversationBindingOwnerError):
            self.store.complete_reservation(key, "owner-b", "external-a", now=101)

    def test_correct_owner_completes_reservation(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        binding = self.store.complete_reservation(key, "owner-a", "external-a", now=101)
        self.assertEqual(binding.state, ConversationBindingState.BOUND)
        self.assertEqual(binding.external_conversation_id, "external-a")

    def test_lookup_returns_bound_binding(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        self.store.complete_reservation(key, "owner-a", "external-a", now=101)
        binding = self.store.lookup(key)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.state, ConversationBindingState.BOUND)
        self.assertEqual(binding.external_conversation_id, "external-a")

    def test_bound_binding_cannot_be_overwritten(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        self.store.complete_reservation(key, "owner-a", "external-a", now=101)
        with self.assertRaises(ConversationBindingAlreadyBoundError):
            self.store.complete_reservation(key, "owner-b", "external-b", now=102)
        self.assertEqual(self.store.lookup(key).external_conversation_id, "external-a")

    def test_owner_can_release_reserved_binding(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        self.assertTrue(self.store.release_reservation(key, "owner-a", now=101))
        self.assertIsNone(self.store.lookup(key))

    def test_wrong_owner_cannot_release_reserved_binding(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        with self.assertRaises(ConversationBindingOwnerError):
            self.store.release_reservation(key, "owner-b", now=101)

    def test_release_does_not_delete_bound_binding(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        self.store.complete_reservation(key, "owner-a", "external-a", now=101)
        self.assertFalse(self.store.release_reservation(key, "owner-a", now=102))
        self.assertIsNotNone(self.store.lookup(key))

    def test_expired_lease_can_be_recovered_atomically(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 10, now=100)
        result = self.store.reserve(key, "owner-b", 10, now=111)
        self.assertTrue(result.acquired)
        self.assertEqual(result.owner_token, "owner-b")

    def test_valid_lease_cannot_be_stolen(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 10, now=100)
        result = self.store.reserve(key, "owner-b", 10, now=109)
        self.assertTrue(result.busy)

    def test_restart_of_store_preserves_bound_binding(self) -> None:
        key = _key()
        self.store.reserve(key, "owner-a", 30, now=100)
        self.store.complete_reservation(key, "owner-a", "external-a", now=101)
        restarted = SQLiteConversationBindingStore(self.database_path)
        binding = restarted.lookup(key)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.external_conversation_id, "external-a")
        self.assertEqual(binding.state, ConversationBindingState.BOUND)

    def test_raw_identity_values_are_not_persisted(self) -> None:
        key = _key("raw-conversation-value", "raw-scope-value")
        self.store.reserve(key, "owner-a", 30, now=100)
        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute("SELECT * FROM conversation_bindings").fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertNotIn("raw-conversation-value", repr(row))
        self.assertNotIn("raw-scope-value", repr(row))

    def test_concurrent_reservation_has_one_winner_and_integrity(self) -> None:
        """Repeat the critical race 20 times with real SQLite connections."""

        for iteration in range(20):
            database_path = (
                Path(self._temporary_directory.name) / f"race-{iteration}.db"
            )
            stores = [SQLiteConversationBindingStore(database_path) for _ in range(8)]
            barrier = threading.Barrier(len(stores))
            results: list[object] = []
            errors: list[BaseException] = []
            results_lock = threading.Lock()
            key = _key(conversation_id=f"race-{iteration}")

            def reserve(store: SQLiteConversationBindingStore, index: int) -> None:
                try:
                    barrier.wait(timeout=10)
                    result = store.reserve(key, f"owner-{index}", 30)
                    with results_lock:
                        results.append(result)
                except BaseException as exc:  # pragma: no cover - assertion below
                    with results_lock:
                        errors.append(exc)

            threads = [
                threading.Thread(target=reserve, args=(store, index))
                for index, store in enumerate(stores)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(sum(result.acquired for result in results), 1)
            self.assertEqual(len(results), len(stores))

            connection = sqlite3.connect(database_path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                connection.close()

    def test_contract_has_no_provider_specific_codex_type(self) -> None:
        from openjarvis.core import conversation_identity

        self.assertNotIn("Codex", inspect.getsource(conversation_identity))
        self.assertNotIn("Codex", conversation_identity.__all__)


def _bound_binding(external_id: str):
    with tempfile.TemporaryDirectory() as directory:
        store = SQLiteConversationBindingStore(Path(directory) / "bindings.db")
        key = _key()
        store.reserve(key, "owner-a", 30, now=100)
        return store.complete_reservation(key, "owner-a", external_id, now=101)


if __name__ == "__main__":
    import unittest

    unittest.main()
