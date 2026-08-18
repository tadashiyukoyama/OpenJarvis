"""Correlate Python bridge commands with Baileys completion events."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


class BridgeCommandError(RuntimeError):
    """Raised when Baileys explicitly rejects a correlated command."""


class BridgeCommandTimeout(TimeoutError):
    """Raised when a correlated command receives no terminal bridge event."""


@dataclass
class _PendingCommand:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: str = ""


class BridgeCommandTracker:
    """Small thread-safe registry for one-shot bridge acknowledgements."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingCommand] = {}

    def register(self) -> str:
        command_id = f"wac_{uuid.uuid4().hex}"
        with self._lock:
            self._pending[command_id] = _PendingCommand()
        return command_id

    def resolve(self, command_id: str, result: dict[str, Any]) -> bool:
        with self._lock:
            pending = self._pending.get(command_id)
            if pending is None:
                return False
            pending.result = dict(result)
            pending.event.set()
            return True

    def reject(self, command_id: str, message: str) -> bool:
        with self._lock:
            pending = self._pending.get(command_id)
            if pending is None:
                return False
            pending.error = str(message or "Falha no bridge WhatsApp")[:512]
            pending.event.set()
            return True

    def wait(self, command_id: str, timeout: float) -> dict[str, Any]:
        with self._lock:
            pending = self._pending.get(command_id)
        if pending is None:
            raise BridgeCommandError("Comando WhatsApp nao registrado")
        if not pending.event.wait(max(0.01, float(timeout))):
            with self._lock:
                self._pending.pop(command_id, None)
            raise BridgeCommandTimeout("O bridge WhatsApp nao confirmou a operacao")
        with self._lock:
            completed = self._pending.pop(command_id, pending)
        if completed.error:
            raise BridgeCommandError(completed.error)
        if completed.result is None:
            raise BridgeCommandError("Resposta vazia do bridge WhatsApp")
        return completed.result

    def cancel(self, command_id: str, message: str) -> None:
        self.reject(command_id, message)

    def cancel_all(self, message: str) -> None:
        with self._lock:
            pending = list(self._pending.values())
        for item in pending:
            item.error = str(message or "Bridge WhatsApp encerrado")[:512]
            item.event.set()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


__all__ = [
    "BridgeCommandError",
    "BridgeCommandTimeout",
    "BridgeCommandTracker",
]
