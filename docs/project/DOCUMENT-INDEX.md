# Project document index

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-20
Applies to integrated code SHA: `33a12d4020ac2b0325359ac5c1c3bd667a8db622`
Production-source baseline: `9874381c9df924e9d439ecb958761a6df27586b1`
Branch: `codex/edge-live-relay-release`
Remote publication: private `https://github.com/cesaryukoyama28-eng/openjarvis-codex`
Supersedes: none
Superseded by: none

This is the canonical entry point for project memory. Code and generated
contracts remain the executable source of truth; dated operational reports are
evidence, not current architecture.

`Applies to SHA` names the latest production-code tree covered by a document.
A later repository HEAD is valid only when every intervening path is canonical
documentation; the completion report must record both SHAs and prove that diff.

| Document | Status | Responsibility | Last verified | Applicable implementation |
|---|---|---|---|---|
| `CURRENT-PROJECT-STATE.md` | CANONICAL | concise factual local state and acceptance evidence | 2026-08-20 | `33a12d4` |
| `ARCHITECTURE-MAP.md` | CANONICAL | current AceleraChat/Codex boundaries and state placement | 2026-08-19 | `28744c7` |
| `JARVIS-AGENT-CONTRACT.md` | CANONICAL | entities, states, APIs, AceleraChat tools, policy, errors and context | 2026-08-20 | `33a12d4` |
| `JARVIS-EDGE-MCP-CONTRACT.md` | CANONICAL | VPS Core, outbound Edge WSS, local Codex and filtered MCP boundaries | 2026-08-19 | `1ecb90a` |
| `operations/JARVIS-AGENT-RUNBOOK.md` | CANONICAL | operation, AceleraChat diagnosis, webhook/backfill, rollback, tests and smoke | 2026-08-20 | `6d5b964` |
| `operations/JARVIS-EDGE-MCP-RUNBOOK.md` | CANONICAL | hybrid installation, dedicated image runner, rotation, revocation, VPS/Windows gates and rollback | 2026-08-20 | `14d026f` |
| `operations/OPENJARVIS-CONTROLLED-RELEASE-2026-08-19.md` | CANONICAL EVIDENCE | exact Core/local SHAs, backups, digest, read-only smokes and rollback | 2026-08-19 | `1ecb90a` |
| `operations/OPENJARVIS-DELEGATION-HISTORY-RELEASE-2026-08-20.md` | CANONICAL EVIDENCE | deterministic delegation, durable history, production image, backups, smoke and rollback | 2026-08-20 | `846127c` |
| `operations/OPENJARVIS-WHATSAPP-CONTACT-SAVE-2026-08-20.md` | CANONICAL EVIDENCE | approved contact persistence, production image, backups, denied smoke and rollback | 2026-08-20 | `33a12d4` |
| `operations/FRESH-WINDOWS-INSTALL.md` | CANONICAL | clean Windows installation, private reconnection, remote tunnel and publication gate | 2026-08-10 | distribution snapshot |
| `CODEX-AGENT-INTEGRATION.md` | CANONICAL | Codex external-agent job, busy, thread and response contract | 2026-08-19 | `1ecb90a` |
| `DECISIONS.md` | CANONICAL | approved architectural decisions | 2026-08-20 | `6d5b964` |
| `KNOWN-ISSUES.md` | CANONICAL | proven current risks and scoped acceptance status | 2026-08-18 | AceleraChat working tree |
| `REPOSITORY-MAP.md` | CANONICAL | Git roots, remotes and synchronization history | 2026-07-17 | historical foundation |
| `MOBILE-STRATEGY.md` | CANONICAL | mobile evidence and future decision gate | 2026-07-17 | historical foundation |
| `VPS-READINESS.md` | CANONICAL | future VPS preparation | 2026-07-17 | historical foundation |
| `ROADMAP.md` | CANONICAL | prior phase map and dependencies | 2026-07-17 | historical foundation |
| `CHANGE-HISTORY.md` | CANONICAL | product and operational release history | 2026-08-20 | `33a12d4` |
| `research/OJ2-CODEX-RUNTIME-AUDIT.md` | CANONICAL EVIDENCE | original installed Codex app-server and no-Ollama audit | 2026-07-17 | OJ2/OJ2-V |
| `operations/OJ-CODEX-LOCAL-RUNTIME-2026-08-05.md` | HISTORICAL EVIDENCE | chronological local runtime/Jarvis debugging evidence; frozen | 2026-08-09 | superseded operationally by the new runbook |

## Reading order for Jarvis work

1. `CURRENT-PROJECT-STATE.md`
2. `ARCHITECTURE-MAP.md`
3. `JARVIS-AGENT-CONTRACT.md`
4. `CODEX-AGENT-INTEGRATION.md`
5. `JARVIS-EDGE-MCP-CONTRACT.md`
6. `DECISIONS.md`
7. `KNOWN-ISSUES.md`
8. `operations/JARVIS-AGENT-RUNBOOK.md`
9. `operations/JARVIS-EDGE-MCP-RUNBOOK.md`
10. `operations/OPENJARVIS-WHATSAPP-CONTACT-SAVE-2026-08-20.md`
11. `operations/OPENJARVIS-DELEGATION-HISTORY-RELEASE-2026-08-20.md`
12. `operations/OPENJARVIS-CONTROLLED-RELEASE-2026-08-19.md`
13. generated OpenAPI/TypeScript/Edge contracts and code

For a new computer, read `operations/FRESH-WINDOWS-INSTALL.md` immediately
after `AGENTS.md` and `.workspace/project.portable.json`, then resume the order
above. It is the only canonical end-to-end installation procedure for the
Codex + Gemini edition.

The dated 2026-08-05 operational report is intentionally retained because it
contains the chronology of earlier local runtime, voice, gateway, Gmail and
Baileys investigations. Those direct-provider records are historical after the
AceleraChat boundary. New operational instructions must be added to the
canonical runbook, not appended to that historical report.

No document may contain API keys, bearer/HMAC values, OAuth tokens, passwords,
WhatsApp QR values, provider auth material or full private message/e-mail
content.
