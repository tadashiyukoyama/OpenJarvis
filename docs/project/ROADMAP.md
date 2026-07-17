# Roadmap

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 5c719de2da9c2f43a46bdf598a3f6d982cd28807
Supersedes: none
Superseded by: none

| Phase | Dependency | State |
|---|---|---|
| OJ0 - local foundation | none | completed |
| OJ1 - controlled clone and promotion | OJ0 review and new authorization | completed in this task |
| OJ2 - upstream audit | OJ1 completed | completed; canonical approved |
| OJ2-V - installed Codex contract validation | OJ2 | completed; canonical approved; GO only for PR A contract scope |
| PR A - External Agent Contract | OJ2-V validation and explicit authorization | OJ3-A implemented on draft PR; CI/review pending |
| OJ3 - controlled D installation | PR A and separate installation authorization | not authorized |
| OJ4 - CodexAgent | PR A, end-to-end tests and explicit authorization | not authorized |
| OJ5 - mobile | verified source and technology decision | not authorized |
| OJ6 - VPS | contracted VPS and approved plan | not authorized |

OJ2-M approved the OJ2/OJ2-V audit after human architectural review on
2026-07-17. The installed `codex-cli 0.144.3` schema and basic app-server
handshake are proven without functional changes. The public architecture is
agent selection (`agent=codex`); GO is limited to PR A — External Agent
Contract. OJ2 did not implement PR A; OJ3-A implements only its contract.
Thread
durability, reconnection, concurrency, final sandbox, telemetry and
end-to-end integration remain unproven. OJ3-A is limited to the external-agent
contract and stops after its draft PR CI; no OJ3 installation, OJ4, UI or
default change is authorized by this documentation.
