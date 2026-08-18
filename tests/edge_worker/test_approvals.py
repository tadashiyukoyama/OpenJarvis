from __future__ import annotations

import threading
import time
from typing import Any

from openjarvis.edge_worker.approvals import CodexApprovalBridge
from openjarvis.integrations.codex_protocol import JsonRpcServerRequest


def test_approval_without_active_job_is_denied() -> None:
    bridge = CodexApprovalBridge(lambda *_: None, timeout_seconds=0.1)

    result = bridge.handle(
        JsonRpcServerRequest(1, "item/commandExecution/requestApproval", {})
    )

    assert result == {"decision": "decline"}


def test_active_approval_waits_for_visual_resolution() -> None:
    sent: list[tuple[str, str, dict[str, Any]]] = []
    bridge = CodexApprovalBridge(
        lambda job_id, kind, payload: sent.append((job_id, kind, dict(payload))),
        timeout_seconds=2.0,
    )
    result: list[object] = []

    def request() -> None:
        with bridge.activate("job-1", "attempt-1"):
            result.append(
                bridge.handle(
                    JsonRpcServerRequest(
                        1,
                        "item/commandExecution/requestApproval",
                        {"command": "git status", "cwd": r"D:\dev\workspaces\x"},
                    )
                )
            )

    thread = threading.Thread(target=request)
    thread.start()
    deadline = time.monotonic() + 1.0
    while not sent and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sent and sent[0][0:2] == ("job-1", "approval.required")
    payload = sent[0][2]
    assert payload["attempt_id"] == "attempt-1"
    assert payload["preview"]["command"] == "git status"
    assert bridge.resolve(payload["approval_id"], "approve")
    thread.join(timeout=1.0)

    assert result == [{"decision": "accept"}]
    assert not bridge.resolve(payload["approval_id"], "approve")
