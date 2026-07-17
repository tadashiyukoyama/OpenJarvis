# Project document index

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Functional implementation commit: `523ebb18a805c2dad1cf03fb7649ae27ebbd02f1`
Current live PR head/checks: confirm on GitHub after push; not asserted here.
Supersedes: none
Superseded by: none

This is the only entry point for the canonical project memory.

The functional implementation SHA identifies the code commit used by the
OJ3-B-H claims; the documentation commit is intentionally not described as
the current PR head. The live PR head and checks must be confirmed on GitHub.

| Document | Status | Responsibility | Last verified | Applicable SHA |
|---|---|---|---|---|
| CURRENT-PROJECT-STATE.md | CANONICAL | factual local state and blockers | 2026-07-17 | 523ebb18a805c2dad1cf03fb7649ae27ebbd02f1 |
| ARCHITECTURE-MAP.md | CANONICAL | component and boundary map | 2026-07-17 | 523ebb18a805c2dad1cf03fb7649ae27ebbd02f1 |
| REPOSITORY-MAP.md | CANONICAL | Git, remotes and synchronization | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| CODEX-AGENT-INTEGRATION.md | CANONICAL | Codex agent requirement and state | 2026-07-17 | 523ebb18a805c2dad1cf03fb7649ae27ebbd02f1 |
| MOBILE-STRATEGY.md | CANONICAL | mobile evidence and decision gate | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| VPS-READINESS.md | CANONICAL | future VPS preparation | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| DECISIONS.md | CANONICAL | approved decisions only | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| KNOWN-ISSUES.md | CANONICAL | proven issues and risks | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| ROADMAP.md | CANONICAL | phases and dependencies | 2026-07-17 | 523ebb18a805c2dad1cf03fb7649ae27ebbd02f1 |
| CHANGE-HISTORY.md | CANONICAL | product foundation changes | 2026-07-17 | 523ebb18a805c2dad1cf03fb7649ae27ebbd02f1 |
| research/OJ2-CODEX-RUNTIME-AUDIT.md | CANONICAL | OJ2/OJ2-V Codex runtime, installed app-server proof and no-Ollama audit | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |

Upstream documentation is present in the checkout. OJ2 indexed the relevant
installation, runtime, frontend, desktop and Claude evidence; OJ2-V added the
local `codex-cli 0.144.3` schema and sanitized app-server probe evidence in
ignored `.workspace/local/audit/`. Human architectural review approved the
report on 2026-07-17; OJ2 is now canonical and freezes Codex as a first-class
agent (`agent=codex`), with PR A — External Agent Contract implemented only
as the OJ3-A merged scope. OJ3-B is limited to an isolated client core.
Thread durability, reconnection, concurrency, final sandbox, production
telemetry and end-to-end integration remain unproven. No functional CodexAgent,
UI, installation or default change is authorized.

OJ3-A is now merged; OJ3-B-H adds only the isolated client-core hardening in
functional commit `523ebb18a805c2dad1cf03fb7649ae27ebbd02f1` and remains
disconnected from the runtime. PR #4 remains draft; live head/checks must be
confirmed on GitHub.
