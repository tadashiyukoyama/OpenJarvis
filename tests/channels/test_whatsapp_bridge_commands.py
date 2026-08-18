from __future__ import annotations

import threading

import pytest

from openjarvis.channels.whatsapp.bridge_commands import (
    BridgeCommandError,
    BridgeCommandTimeout,
    BridgeCommandTracker,
)


def test_tracker_correlates_one_completion_without_cross_talk():
    tracker = BridgeCommandTracker()
    first = tracker.register()
    second = tracker.register()
    tracker.resolve(second, {"type": "command_ok", "command_id": second})

    result = tracker.wait(second, 0.1)

    assert result["command_id"] == second
    assert tracker.pending_count() == 1
    tracker.reject(first, "falha controlada")
    with pytest.raises(BridgeCommandError, match="falha controlada"):
        tracker.wait(first, 0.1)
    assert tracker.pending_count() == 0


def test_tracker_timeout_removes_the_pending_command():
    tracker = BridgeCommandTracker()
    command_id = tracker.register()

    with pytest.raises(BridgeCommandTimeout):
        tracker.wait(command_id, 0.01)

    assert tracker.pending_count() == 0


def test_tracker_cancel_all_wakes_waiters():
    tracker = BridgeCommandTracker()
    command_id = tracker.register()
    observed: list[str] = []

    def wait() -> None:
        try:
            tracker.wait(command_id, 1.0)
        except BridgeCommandError as exc:
            observed.append(str(exc))

    waiter = threading.Thread(target=wait)
    waiter.start()
    tracker.cancel_all("bridge encerrado")
    waiter.join(timeout=1.0)

    assert observed == ["bridge encerrado"]
    assert tracker.pending_count() == 0
