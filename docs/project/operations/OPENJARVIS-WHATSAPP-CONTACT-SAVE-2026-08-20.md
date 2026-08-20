# OpenJarvis WhatsApp contact-save production release — 2026-08-20

Status: CANONICAL EVIDENCE
Owner: Cesar Yukoyama / Codex
Applicable functional SHA: `33a12d4020ac2b0325359ac5c1c3bd667a8db622`
Functional tree: `76546bab3bde0e97ed1760be08d055112fbaec8c`
Branch: `codex/edge-live-relay-release`
Documentation HEAD: the commit containing this report; the exact published SHA
is recorded in the completion output to avoid a circular self-reference.

## Outcome and boundaries

OpenJarvis can now propose saving a WhatsApp contact from an exact E.164 number
and optional name through the native AceleraChat boundary. The server resolves
the contact-to-inbox association; OpenJarvis does not invent a `source_id`, does
not receive Evolution credentials and does not call a message endpoint while
saving.

The executable contract is:

- internal ID: `whatsapp.save_contact`;
- Gemini alias: `whatsapp_save_contact`;
- effect: `MUTATION`;
- approval: exact visual approval is mandatory;
- provider capability: `conversations.create` on an operational WhatsApp inbox;
- existing exact phone: reused without overwriting its stored name;
- multiple operational inboxes: exact inbox ID or name is mandatory;
- send side effect: forbidden; successful execution reports
  `message_sent=false`.

AceleraChat already exposed the required idempotent `contacts.create` and
server-owned `conversations.create` contract. No AceleraChat source change or
database migration was necessary.

## Implementation identity

Functional commit:

- SHA: `33a12d4020ac2b0325359ac5c1c3bd667a8db622`;
- tree: `76546bab3bde0e97ed1760be08d055112fbaec8c`;
- parent/deployment base: `03bda72d95117e35fd6dd9c38cf494b05dfecf7c`;
- delta: 16 files, 561 insertions and 22 deletions.

The implementation remains modular:

- `adapters/acelerachat/whatsapp_contacts.py`: 122 lines;
- `adapters/acelerachat/whatsapp_values.py`: 23 lines;
- `registry/acelerachat_contacts.py`: 31 lines;
- `registry/acelerachat.py`: 398 lines;
- focused regression suite `test_acelerachat_contact_save.py`: 202 lines.

No new production module exceeds 400 physical lines. Private untracked
`.manus-audit/`, root `node_modules/` and `frontend/pnpm-lock.yaml` were not
modified or committed.

## Local validation

The final functional tree passed:

- focused contact/catalog/intent suite: 127 tests;
- canonical Agent Core, Edge, MCP and Codex matrix: 615 tests plus 4 subtests;
- frontend Vitest: 112 tests in 29 files;
- TypeScript validation and Vite/PWA production build;
- Ruff check and format for 260 Python files;
- generated-contract parity check;
- Python `compileall`;
- PowerShell AST parsing for 10 Edge scripts;
- Compose YAML and MCP TOML parsing;
- `git diff --check`;
- publication scanner over 2,453 tracked files: pass, with no forbidden path,
  oversized file or newly detected secret.

No real contact, conversation, WhatsApp message, e-mail or Codex turn was
created by local validation.

## Source archive and image

The exact source archive copied to the VPS is:

- path:
  `/opt/openjarvis/backups/source-33a12d4020ac2b0325359ac5c1c3bd667a8db622.tar.gz`;
- bytes: 43,201,032;
- entries: 2,764;
- forbidden/private entries: 0;
- SHA-256:
  `23c2ea90a1b3702ae6aace1d9c7a8b74607c1d86536890029471678b77194cdc`.

The image was built directly from that verified archive without GitHub
Actions:

- tag: `openjarvis-core:33a12d4020ac2b0325359ac5c1c3bd667a8db622`;
- image ID:
  `sha256:f9fb105dfe40932849b2eff9a56775cad43b7ae6eef0bfac43db2a74b98995d2`;
- size: 177,983,007 bytes;
- OCI revision label: the full functional SHA.

Before deployment the image loaded the new adapter and catalog in a no-network,
read-only container. The temporary VPS build directory was removed only after
post-deploy validation; the verified source archive and both images remain.

## Pre-deploy backup

Backup timestamp: `20260820T233225Z`. The prior active image was
`openjarvis-core:339f8d57d309ab0967ce4d5df36c94759905300e`, image ID
`sha256:e624b25e7015f2c903279328b96868a0900ecb338625c3e8c626f8d1af73ee76`.

| Backup | Bytes | SHA-256 |
|---|---:|---|
| `compose-20260820T233225Z-339f8d57d309ab0967ce4d5df36c94759905300e.yaml` | 1,072 | `1c91bbbc492c3a99d3374a76ca757231143a6683c62d07a669bdaea0a2575b51` |
| `core.env-20260820T233225Z-339f8d57d309ab0967ce4d5df36c94759905300e` | 1,145 | `e0d9bc52e1f395291648fc47e4ae6bea135745d1235a0f505a397de774cc6838` |
| `active-image-20260820T233225Z-339f8d57d309ab0967ce4d5df36c94759905300e` | 57 | `d62fc0d5f7e1c53389acd174ac784ca78eaafd2dd524969f9f562c6c294bf700` |
| `jarvis-agent-20260820T233225Z-339f8d57d309ab0967ce4d5df36c94759905300e.sqlite3` | 123,973,632 | `754a7a47a99445d6d83976a45ead10b71df206d2a4a537ca450a196792a49878` |
| `operational-events-20260820T233225Z-339f8d57d309ab0967ce4d5df36c94759905300e.sqlite3` | 40,960 | `28ab76ab83c99e549229797d2686e668387e8753b3cb6e34d5e22520e6ac2a9a` |

Both frozen SQLite backups passed `PRAGMA quick_check` using read-only immutable
access. No credential value was printed or copied into this report.

## Controlled production deployment and smoke

Only Compose service `core` was recreated. An automatic rollback branch in the
deployment command restored the previous `active-image` and prior container if
the new service failed to become healthy. Rollback was not triggered.

Post-deploy evidence:

- container image and image ID exactly matched the values above;
- container health: `healthy`; restart count: 0;
- internal `/healthz`: `ok`;
- live `jarvis-agent.sqlite3`: `quick_check=ok`;
- live `operational-events.sqlite3`: `quick_check=ok`;
- catalog: 25 of 25 tools available;
- `whatsapp.save_contact`: available, mutation, approval required, capability
  `conversations.create`;
- AceleraChat inbox 20 `AiFoodmanager`: connected and operational;
- Edge device `cesar-codex-desktop-01`: online with Codex capabilities;
- Core error signatures since deployment: 0.

The no-mutation production smoke used synthetic phone `+5511999990000`:

1. verified zero exact contacts before the smoke;
2. opened session `jas_3fbcb9dd7aae4c178bff0eb844903ae6`;
3. committed the intent and contact details in two final turns;
4. proposed action `act_dd3e09c008bb44698d0c54f2a8552051`;
5. verified state `AWAITING_APPROVAL`, inbox `AiFoodmanager` and preview
   `salva o contato e o associa à caixa; não envia mensagem`;
6. denied through `X-Jarvis-Decision-Channel: visual`;
7. closed the session;
8. verified zero exact contacts after the smoke.

Result: no provider mutation, no contact, no conversation and no message. No
e-mail or Codex delegation was executed.

The VPS release manifest is
`/opt/openjarvis/backups/release-33a12d4020ac2b0325359ac5c1c3bd667a8db622.json`,
SHA-256
`cecf924e65d728df24983425ec2afff1a94ebec8bf67689982bdb06b089cd811`.

## Rollback

Rollback target:
`openjarvis-core:339f8d57d309ab0967ce4d5df36c94759905300e`.

Controlled rollback procedure on the VPS:

1. atomically restore the backed-up `active-image` value;
2. set `OPENJARVIS_IMAGE_TAG=339f8d57d309ab0967ce4d5df36c94759905300e`;
3. run `docker compose -f /opt/openjarvis/compose.yaml up -d --no-deps --force-recreate core`;
4. wait for `openjarvis-core-1` to report `healthy` and zero unexpected
   restarts;
5. verify `/healthz`, both SQLite databases, catalog, Edge and inbox health.

This release has no database migration. Ordinary code rollback does not require
restoring a database. The validated SQLite snapshots exist for disaster
recovery and must be restored only during an explicit data-recovery operation.

## Publication and mutation statement

The functional commit was created before deployment. Canonical documentation is
committed separately with `[skip ci]`, then both commits are published in one
fast-forward push to private `main`; no intermediate push or PR is used.

Credentials, AceleraChat source/database, SSH keys, DNS, TLS and GitHub Actions
configuration were not changed. No real contact, conversation, WhatsApp
message, e-mail or Codex turn was created during this release.
