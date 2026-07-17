# Architecture map

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

OJ1 establishes the checkout boundary only. The official OpenJarvis
components are present at the captured SHA, but their full architecture
audit remains deferred to OJ2.

| Area | OJ0 state |
|---|---|
| Canonical Git root | OPENJARVIS_WORKSPACE_ROOT |
| Official OpenJarvis source | Checked out at captured SHA |
| Project memory | docs/project |
| Portable identity and policies | .workspace |
| Machine-local state | .workspace/local |
| Private material | .private |
| Runtime state | .runtime |
| Reproducible artifacts | .artifacts |
| Mobile reservation | apps/mobile |
| Shared contracts | contracts |
| Future infrastructure | infra |
| Workspace automation | scripts/workspace |

The actual engines, agents, Claude Code integration, frontend, desktop, API,
memory and security boundaries are deferred to OJ2.
