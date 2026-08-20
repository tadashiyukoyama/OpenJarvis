# OpenJarvis WhatsApp voice routing hotfix — 2026-08-20

Status: LOCAL RELEASE CANDIDATE; PRODUCTION DEPLOY PENDING
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

## Deployment and rollback gate

This functional commit has no migration and changes no credentials. Before
activation:

1. confirm the current production image, container health and Edge status;
2. back up the two OpenJarvis SQLite databases and verify `quick_check=ok`;
3. build an image named with the full functional SHA and record its digest;
4. render Compose and validate the reverse-proxy configuration;
5. recreate only the OpenJarvis Core service;
6. require container health, public HTTPS health, catalog availability and Edge
   `ONLINE` before closing the rollback window;
7. perform a no-send visual smoke by proposing a WhatsApp send and clicking
   **Negar**; verify zero provider POSTs;
8. execute one real message only under a new, explicit operator authorization.

The rollback target must be the exact healthy image active immediately before
deployment. Current expected source identity is
`b129eaf591675fa411e2ae164211952ac96c67d7`; it must be verified live rather
than assumed. The additive runtime databases should remain in place unless an
independent database fault is proven.

No push, GitHub Action, deploy, migration, credential change or provider send
is part of the local functional commit.
