#!/usr/bin/env python3
"""Classify a GitHub Actions change set and select the least costly safe lane.

The classifier deliberately operates on Git SHAs supplied through the process
environment by the workflow.  It never evaluates a commit message or embeds a
context value in shell source.  The same pure functions are used by the local
governance tests, so routing changes can be reviewed without GitHub access.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ZERO_SHA = "0" * 40


def _normalise(path: str) -> str:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def classify_paths(paths: Iterable[str]) -> dict[str, bool]:
    """Return deterministic change flags for repository-relative paths."""

    flags = {
        "docs_changed": False,
        "python_changed": False,
        "tests_changed": False,
        "integrations_changed": False,
        "rust_changed": False,
        "windows_sensitive_changed": False,
        "frontend_changed": False,
        "tauri_changed": False,
        "workflow_changed": False,
    }

    for raw_path in paths:
        path = _normalise(raw_path)
        lower = path.lower()
        name = Path(path).name.lower()

        flags["docs_changed"] |= (
            lower.startswith("docs/")
            or lower in {"mkdocs.yml", "readme.md", "readme.rst", "readme.txt"}
        )
        flags["python_changed"] |= (
            lower.endswith(".py")
            or name in {"pyproject.toml", "uv.lock", "setup.py", "setup.cfg"}
        )
        flags["tests_changed"] |= lower.startswith("tests/") or name.startswith("test_")
        flags["integrations_changed"] |= (
            lower.startswith("src/openjarvis/integrations/")
            or lower.startswith("tests/integrations/")
            or lower.startswith("src/openjarvis/channels/")
            or lower.startswith("tests/channels/")
            or lower.startswith("src/openjarvis/connectors/")
            or lower.startswith("tests/connectors/")
        )
        flags["rust_changed"] |= (
            lower.startswith("rust/")
            or lower.endswith(".rs")
            or name in {"cargo.toml", "cargo.lock"}
        )
        flags["windows_sensitive_changed"] |= (
            "windows" in lower
            or lower.startswith("deploy/windows/")
            or lower.startswith("tests/hardware/")
            or lower.endswith((".ps1", ".bat", ".cmd"))
        )
        flags["frontend_changed"] |= (
            lower.startswith("frontend/")
            or lower.startswith("web/")
            or (lower.endswith((".ts", ".tsx", ".js", ".jsx")) and not lower.startswith("scripts/"))
            or name in {"package.json", "pnpm-lock.yaml", "yarn.lock"}
        )
        flags["tauri_changed"] |= (
            "src-tauri/" in lower or lower.startswith("tauri/") or lower.startswith("desktop/")
        )
        flags["workflow_changed"] |= (
            lower.startswith(".github/workflows/")
            or lower in {
                "scripts/ci/classify_changes.py",
                "tests/ops/test_ci_cost_governance.py",
            }
        )

    return flags


def targeted_test_roots(paths: Iterable[str], repo_root: Path) -> list[str]:
    """Map changed Python domains to existing, bounded test roots.

    The returned paths are later passed as argv entries to pytest by the
    workflow.  Deleted paths and unmapped source domains intentionally produce
    no test argument instead of falling back to the full suite.
    """

    roots: set[str] = set()
    for raw_path in paths:
        path = _normalise(raw_path)
        lower = path.lower()

        if lower.startswith("tests/") and lower.endswith(".py"):
            candidate = repo_root / Path(path)
            if candidate.exists():
                roots.add(path)
            continue

        prefix = "src/openjarvis/"
        if lower.startswith(prefix) and lower.endswith(".py"):
            relative = Path(path[len(prefix) :])
            domain = relative.parts[0] if relative.parts else ""
            if domain:
                candidate = Path("tests") / domain
                if (repo_root / candidate).is_dir():
                    roots.add(candidate.as_posix())

    return sorted(roots)


def _valid_sha(value: str) -> bool:
    return bool(SHA_RE.fullmatch(value))


def changed_paths(base_sha: str, head_sha: str, repo_root: Path) -> list[str]:
    """Read a real Git diff using argv-safe subprocess calls."""

    if not _valid_sha(head_sha):
        raise ValueError("HEAD_SHA must be a 40-character hexadecimal Git SHA")
    if base_sha and base_sha != ZERO_SHA and not _valid_sha(base_sha):
        raise ValueError("BASE_SHA must be empty, all-zero, or a 40-character hexadecimal Git SHA")

    if not base_sha or base_sha == ZERO_SHA:
        command = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", head_sha]
    else:
        command = ["git", "diff", "--name-only", "--diff-filter=ACMR", base_sha, head_sha]

    result = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [_normalise(line) for line in result.stdout.splitlines() if line.strip()]


def route_for(event_name: str, draft: bool, flags: dict[str, bool]) -> dict[str, bool]:
    """Select jobs for CI without depending on commit text or PR metadata."""

    is_draft_pr = event_name == "pull_request" and draft
    full_ci = not is_draft_pr
    fast_lane = is_draft_pr

    return {
        "draft_fast_lane": fast_lane,
        "full_ci_required": full_ci,
        "run_lint": True,
        "run_python_full": full_ci,
        "run_python_targeted": fast_lane
        and (flags["python_changed"] or flags["tests_changed"])
        and not flags["integrations_changed"],
        "run_codex_targeted": fast_lane and flags["integrations_changed"],
        "run_rust": full_ci or flags["rust_changed"],
        "run_windows_312": full_ci or (fast_lane and flags["windows_sensitive_changed"]),
        "run_windows_313": full_ci,
        "run_governance": flags["workflow_changed"],
        "docs_build_required": (
            event_name != "pull_request"
            or (not draft and (flags["docs_changed"] or flags["python_changed"] or flags["workflow_changed"]))
        ),
    }


def _write_outputs(output_path: Path, values: dict[str, object]) -> None:
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, (dict, list)):
                rendered = json.dumps(value, separators=(",", ":"))
            else:
                rendered = str(value)
            output.write(f"{key}={rendered}\n")


def _write_summary(summary_path: Path, event_name: str, draft: bool, paths: list[str], route: dict[str, bool]) -> None:
    selected = [name for name, enabled in route.items() if name.startswith("run_") and enabled]
    avoided = [name for name, enabled in route.items() if name.startswith("run_") and not enabled]
    selected_text = ", ".join(selected) or "none"
    avoided_text = ", ".join(avoided) or "none"
    lines = [
        "## CI cost-aware classification",
        "",
        f"- Event: `{event_name}`; draft: `{str(draft).lower()}`",
        f"- Changed files classified: `{len(paths)}`",
        "- Lane: `{}`".format("full" if route["full_ci_required"] else "draft-fast"),
        f"- Jobs selected: `{selected_text}`",
        f"- Jobs avoided: `{avoided_text}`",
        "- Reason: routing is based on the real base/head diff; workflow/classifier changes activate governance.",
    ]
    with summary_path.open("a", encoding="utf-8", newline="\n") as summary:
        summary.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        paths = changed_paths(args.base_sha, args.head_sha, args.repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"classification failed: {exc}", file=sys.stderr)
        return 1

    flags = classify_paths(paths)
    route = route_for(args.event_name, args.draft, flags)
    values: dict[str, object] = {**flags, **route}
    values["targeted_test_roots"] = targeted_test_roots(paths, args.repo_root)
    _write_outputs(args.output, values)
    if args.summary:
        _write_summary(args.summary, args.event_name, args.draft, paths, route)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
