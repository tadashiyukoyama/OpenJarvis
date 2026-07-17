# Roadmap

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

| Phase | Dependency | State |
|---|---|---|
| OJ0 - local foundation | none | completed |
| OJ1 - controlled clone and promotion | OJ0 review and new authorization | completed in this task |
| OJ2 - upstream audit | OJ1 completed | completed as DRAFT |
| OJ2-V - installed Codex contract validation | OJ2 DRAFT | validated; GO only for PR A contract scope |
| PR A - External Agent Contract | OJ2-V validation and explicit authorization | possible next scope; not executed |
| OJ3 - controlled D installation | PR A and separate installation authorization | not authorized |
| OJ4 - CodexAgent | PR A, end-to-end tests and explicit authorization | not authorized |
| OJ5 - mobile | verified source and technology decision | not authorized |
| OJ6 - VPS | contracted VPS and approved plan | not authorized |

OJ2-V proved the installed `codex-cli 0.144.3` schema and basic app-server
handshake without changing functional code. It freezes the public architecture
as agent selection (`agent=codex`) and permits only preparation of PR A —
External Agent Contract. PR A itself was not executed or authorized by this
run. No OJ3, OJ4, installation, UI or default change is authorized.
