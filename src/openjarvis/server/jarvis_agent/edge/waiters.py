"""Process-local synchronization for an already offered Edge job."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class EdgeJobWaiter:
    accepted: threading.Event = field(default_factory=threading.Event)
    terminal: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _result: dict[str, Any] | None = field(default=None, repr=False)

    def mark_accepted(self) -> None:
        self.accepted.set()

    def finish(self, result: Mapping[str, Any]) -> None:
        with self._lock:
            if self._result is None:
                self._result = dict(result)
        self.accepted.set()
        self.terminal.set()

    def result(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._result) if self._result is not None else None


__all__ = ["EdgeJobWaiter"]
