# OpenJarvis WhatsApp voice routing hotfix — 2026-08-20

Status: PRODUCTION DEPLOYED AND AUDITED
Owner: Cesar Yukoyama / Codex
Branch: `codex/edge-live-relay-release`
Base SHA: `aab11ae5c231d67354a1e5114ead8222d77aaf77`
Functional SHA: `339f8d57d309ab0967ce4d5df36c94759905300e`
Functional tree: `c05330b3c6e92b2d7e80628262ac43da69d0de47`

## Incident evidence

The Codex relay itself worked: the voice request containing "testando 03" reached
the selected Codex task and received `OK`. The WhatsApp path was a separate
failure and never reached provider dispatch.

For production session `jas_63b34ec22a2a4764819e8085a05d71c3`, action
`act_c682017a8e55416ca241df1f7b339449` executed only
`whatsapp.search_chats` with query `Klaus consultor` and completed with zero
conversations. At the same timestamp AceleraChat recorded only read requests to
the inbox and contact endpoints. There was no message POST, no visual approval,
no OpenJarvis dispatch job and no Evolution send request.

The connected AceleraChat WhatsApp inbox is operational, but it has no contact
or conversation named Klaus. A similarly named contact exists only in closed,
older Evolution instances belonging to another connected number. Reusing that
stale identity would risk sending from or to the wrong WhatsApp account and is
therefore explicitly prohibited.

## Root cause

Two facts combined:

1. the explicit instruction to send through WhatsApp and the target/message
   details were committed in separate human voice turns;
2. the backend validated a tool proposal against only its final turn, so Gemini
   downgraded the operation to a contact search instead of proposing the send.

After the empty search, no exact phone was available in the currently connected
inbox. The system correctly had no safe target to dispatch, but its result did
not tell Gemini which field had to be requested next.

## Correction

- A mutation may use one bounded voice-evidence window from the same active
  session and generation: at most four unredacted human turns and 120 seconds.
- The current explicit intent always wins. Otherwise the most recent explicit
  executor is the only eligible anchor; the system never searches backwards for
  a more convenient executor.
- Every contributing turn is consumed together after the immutable proposal is
  created. An exact retry returns the same action and cannot duplicate work.
- Read intents now have an explicit read-tool allowlist, so a request to read
  WhatsApp or e-mail cannot authorize a mutation.
- Gemini is instructed to call `whatsapp_send_text` directly when name and
  message are known, instead of searching first.
- Empty contact/conversation results expose `resolution=not_found` and
  `next_required_field=phone_number_e164`.
- A missing name produces an actionable error: ask for the complete E.164 phone
  number and state that no message was sent.
- Direct phone dispatch continues to use the existing AceleraChat server-owned
  contact/inbox association and remains suspended behind visual approval.

No direct Baileys connector was restored. AceleraChat remains the exclusive
WhatsApp authority.

## Validation

| Gate | Result |
|---|---|
| Focused intent + AceleraChat adapter | `42 passed` |
| Canonical Agent Core + Edge + MCP + Codex matrix | `605 passed + 4 subtests`; 45 upstream deprecation warnings |
| Frontend Vitest | `112 passed` in 29 files |
| Frontend TypeScript | passed |
| Vite/PWA production build | passed |
| Ruff check and format | passed |
| Generated Agent contracts | check passed |
| Python compileall | passed |
| PowerShell AST | 10 Edge scripts, zero parse errors |
| Compose YAML and MCP TOML | parsed successfully |
| Patch whitespace | `git diff --check` passed |
| Staged publication scanner | 9 functional files; zero forbidden paths or detected secrets |

The repository-wide upstream suite was also started as a diagnostic and stopped
at 41%. As documented in `JARVIS-EDGE-MCP-RUNBOOK.md`, that suite includes
unrelated optional providers and external integrations and is not the release
gate. No production code was changed in response to those diagnostic failures.

All provider calls in the new tests use in-memory HTTP doubles. No real
WhatsApp message, e-mail, Codex delegation or external mutation was executed.

## Production deployment evidence

The controlled deployment ran from `2026-08-20T22:57:44Z` to
`2026-08-20T22:58:07Z` and recreated only the OpenJarvis Core service.

| Artifact | Identity |
|---|---|
| Source archive | `source-339f8d57d309ab0967ce4d5df36c94759905300e.tar.gz` |
| Source bytes | `43195575` |
| Source SHA-256 | `d4148212923989a35ed59886c11033029b003b0149c5a0035f64dd42cdda2b50` |
| Production image | `openjarvis-core:339f8d57d309ab0967ce4d5df36c94759905300e` |
| Image ID | `sha256:e624b25e7015f2c903279328b96868a0900ecb338625c3e8c626f8d1af73ee76` |
| Image size | `177981643` bytes |
| Rollback image | `openjarvis-core:b129eaf591675fa411e2ae164211952ac96c67d7` |
| Final manifest | `release-manifest-final-20260820T230000Z-339f8d57d309ab0967ce4d5df36c94759905300e.json` |
| Manifest SHA-256 | `6351b5f780f99add7a1f9ececb56b4cf131538a312e7b39299d5392a92e08b9c` |

Validated backups created before replacement:

- `jarvis-agent-20260820T225640Z-b129eaf591675fa411e2ae164211952ac96c67d7.sqlite3`
  — SHA-256 `10bc5ff523feb027c6fb8a5473269c98762c72e685d5269c88713b1ec3c1a3a4`;
- `operational-events-20260820T225640Z-b129eaf591675fa411e2ae164211952ac96c67d7.sqlite3`
  — SHA-256 `dafc232f619ce15f51bd2bfb00a514bde6ccd8ce033d4180e26f54129a865e1d`;
- Compose SHA-256
  `1c91bbbc492c3a99d3374a76ca757231143a6683c62d07a669bdaea0a2575b51`;
- private configuration backup SHA-256
  `e0d9bc52e1f395291648fc47e4ae6bea135745d1235a0f505a397de774cc6838`.

Both live databases and both SQLite backups returned `quick_check=ok`.
OpenResty and Compose validation passed. The new container is healthy with zero
restarts; Edge is `ONLINE` with no last error; the catalog exposes 24 of 24
tools, including the WhatsApp mutations behind visual approval.

The production no-send smoke reached `AWAITING_APPROVAL`, was denied through the
visual decision channel and persisted as `DENIED`. The missing `Klaus Consultor`
smoke returned `409 INVALID_REQUEST`, required E.164 and created no action.
Across both checks there were zero AceleraChat provider POSTs, zero Evolution
sends, zero jobs and zero external operations since deployment. One expected
denied smoke action remains in the audit trail.

The temporary build directory was removed only after all gates passed. The
validated source archive and both image tags remain available for recovery.
Rollback consists of setting `OPENJARVIS_IMAGE_TAG` to
`b129eaf591675fa411e2ae164211952ac96c67d7`, recreating only `core`, and
requiring container health plus Edge `ONLINE`. Runtime databases remain in
place unless an independently proven database fault requires restoration.

No migration, credential change, GitHub Action, real Codex delegation, real
WhatsApp message or e-mail was executed by this release. A real WhatsApp send
requires a new explicit operator request and visual approval.
