from __future__ import annotations

from openjarvis.edge_worker.worker import _safe_connection_failure


def test_safe_connection_failure_reports_known_protocol_state() -> None:
    assert (
        _safe_connection_failure(ValueError("Core frame sequence moved backwards"))
        == "ValueError:core_sequence_moved_backwards"
    )


def test_safe_connection_failure_does_not_echo_unknown_values() -> None:
    secret = "wss://example.invalid/edge?token=private"
    result = _safe_connection_failure(ValueError(secret))

    assert result == "ValueError:protocol_value_error"
    assert secret not in result
