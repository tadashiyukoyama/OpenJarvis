# Project document index

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

This is the only entry point for the canonical project memory.

Applicable SHA values identify the upstream code baseline used by each
document's factual claims; they do not identify the commit containing the
documentation.

| Document | Status | Responsibility | Last verified | Applicable SHA |
|---|---|---|---|---|
| CURRENT-PROJECT-STATE.md | CANONICAL | factual local state and blockers | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| ARCHITECTURE-MAP.md | CANONICAL | component and boundary map | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| REPOSITORY-MAP.md | CANONICAL | Git, remotes and synchronization | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| CODEX-AGENT-INTEGRATION.md | CANONICAL | Codex agent requirement and state | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| MOBILE-STRATEGY.md | CANONICAL | mobile evidence and decision gate | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| VPS-READINESS.md | CANONICAL | future VPS preparation | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| DECISIONS.md | CANONICAL | approved decisions only | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| KNOWN-ISSUES.md | CANONICAL | proven issues and risks | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| ROADMAP.md | CANONICAL | phases and dependencies | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| CHANGE-HISTORY.md | CANONICAL | product foundation changes | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| research/OJ2-CODEX-RUNTIME-AUDIT.md | DRAFT | OJ2/OJ2-V Codex runtime, installed app-server proof and no-Ollama audit | 2026-07-17 | 3000116d181eb69737241c09eaa70d4c65eb80a0 |

Upstream documentation is present in the checkout. OJ2 indexed the relevant
installation, runtime, frontend, desktop and Claude evidence; OJ2-V added the
local `codex-cli 0.144.3` schema and sanitized app-server probe evidence in
ignored `.workspace/local/audit/`. The canonical memory now freezes Codex as a
first-class agent (`agent=codex`), with PR A — External Agent Contract as the
only possible future implementation scope. The report remains DRAFT and does
not authorize functional Codex, UI, installation or default changes.
