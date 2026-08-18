"""Safe helpers for opening a persisted thread in Codex Desktop on Windows."""

from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable

_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CodexDesktopUnavailable(RuntimeError):
    """Raised when the host cannot dispatch documented Codex Desktop links."""


def codex_thread_uri(thread_id: str) -> str:
    """Return the documented Codex deep link for one syntactically safe thread."""

    if not _THREAD_ID_PATTERN.fullmatch(thread_id):
        raise ValueError("Invalid Codex thread identifier")
    return f"codex://threads/{thread_id}"


def open_codex_thread_in_desktop(
    thread_id: str,
    *,
    remount_delay_seconds: float = 0.75,
    opener: Callable[[str], object] | None = None,
    sleeper: Callable[[float], object] = time.sleep,
) -> str:
    """Remount a thread using only routes registered by Codex Desktop.

    Navigating directly to a thread that is already selected is a renderer
    no-op.  Visiting the documented settings route first and then returning to
    the thread forces the existing task to read its newly persisted history.
    """

    thread_uri = codex_thread_uri(thread_id)
    if opener is None:
        if sys.platform != "win32":
            raise CodexDesktopUnavailable(
                "Codex Desktop refresh is available only on Windows"
            )
        startfile = getattr(os, "startfile", None)
        if not callable(startfile):
            raise CodexDesktopUnavailable(
                "Windows URI protocol dispatch is unavailable"
            )
        opener = startfile

    opener("codex://settings")
    sleeper(remount_delay_seconds)
    opener(thread_uri)
    return thread_uri
