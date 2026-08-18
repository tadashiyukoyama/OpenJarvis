# Roadmap

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-18
Functional implementation commit: OJ5-A draft branch; SHA recorded in the task report
Current main base: `d487c428a48f50163ba4fb08387e3545ee6607a3`
Current draft PR head/checks: confirm on GitHub after push; not asserted here.
Supersedes: none
Superseded by: none

| Phase | Dependency | State |
|---|---|---|
| OJ0 - local foundation | none | completed |
| OJ1 - controlled clone and promotion | OJ0 review and new authorization | completed in this task |
| OJ2 - upstream audit | OJ1 completed | completed; canonical approved |
| OJ2-V - installed Codex contract validation | OJ2 | completed; canonical approved; GO only for PR A contract scope |
| PR A - External Agent Contract | OJ2-V validation and explicit authorization | merged by squash as `7ff9dbebfb36c74073795ba96b83aa84db7a741e` |
| PR B - Codex App Server Client Core | PR A merge and explicit sequential authorization | merged by squash as `f37bb5bad35a6ee21ac9920b462f09f24cae5476`; transport remains disconnected from runtime |
| PR C - Codex Conversation Runtime Core | PR B merge, stable schema confirmation and explicit sequential authorization | merged by squash in PR #5; no CodexAgent or persistent identity |
| OJ4-A - Actions cost governance | OJ3-C merge and explicit sequential authorization | merged by squash in PR #6 as `d487c428a48f50163ba4fb08387e3545ee6607a3` |
| OJ5-A - Persistent conversation identity contract | OJ4-A merge and explicit sequential authorization | current draft branch/PR; no CodexAgent or provider propagation |
| OJ3 - controlled D installation | PR A and separate installation authorization | not authorized |
| OJ4 - CodexAgent | PR A, end-to-end tests and explicit authorization | not authorized |
| OJ5 - mobile | verified source and technology decision | not authorized |
| OJ6 - VPS | contracted VPS and approved plan | not authorized |

OJ2-M approved the OJ2/OJ2-V audit after human architectural review on
2026-07-17. The installed `codex-cli 0.144.3` schema and basic app-server
handshake are proven. The public architecture is
agent selection (`agent=codex`); GO is limited to PR A — External Agent
Contract, which is now merged. OJ3-C implements only stable conversation
contracts, routing and sanitized public aggregation over the client. OJ3-C-H
additionally hardens bounded waiting, close/failure release, multi-waiter
notification, final-text reconciliation and completed-turn retention with
deterministic tests. OJ3-C was integrated before OJ4-A; OJ5-A is the current
draft for the identity contract.
Persistent provider propagation, reconnection, concurrency, approvals UX,
telemetry and end-to-end integration remain unproven. OJ5-A is draft and must
remain unmerged pending architectural review. No installation, CodexAgent,
UI, default change, ready transition or later phase is authorized by this
documentation.
