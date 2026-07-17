# Roadmap

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Functional implementation commit: `91e4330` (OJ3-C primary commit)
Current live PR head/checks: confirm on GitHub after push; not asserted here.
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
| PR C - Codex Conversation Runtime Core | PR B merge, stable schema confirmation and explicit sequential authorization | primary commit `91e4330`; draft PR; live head/checks must be confirmed; no CodexAgent or persistent identity |
| OJ3 - controlled D installation | PR A and separate installation authorization | not authorized |
| OJ4 - CodexAgent | PR A, end-to-end tests and explicit authorization | not authorized |
| OJ5 - mobile | verified source and technology decision | not authorized |
| OJ6 - VPS | contracted VPS and approved plan | not authorized |

OJ2-M approved the OJ2/OJ2-V audit after human architectural review on
2026-07-17. The installed `codex-cli 0.144.3` schema and basic app-server
handshake are proven. The public architecture is
agent selection (`agent=codex`); GO is limited to PR A — External Agent
Contract, which is now merged. OJ3-C implements only stable conversation
contracts, routing and sanitized public aggregation over the client.
Persistent identity, reconnection, concurrency, approvals UX, telemetry and
end-to-end integration remain unproven. The C PR is draft and its current CI
gate must complete before any later action. No OJ3 installation, OJ4, UI,
default change, ready transition or merge is authorized by this documentation.
