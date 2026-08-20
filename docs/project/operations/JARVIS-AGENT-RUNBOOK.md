# Jarvis Agent runbook

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-20
Applies to code SHA: `846127cfa76680d11dd686ea052f5b7fdc7c4818`
Branch: `codex/edge-live-relay-release`

## 1. Scope and safety

This runbook operates the local Jarvis Agent Core for AceleraChat e-mail,
AceleraChat WhatsApp and Codex Desktop. It does not authorize deploy, VPS,
GitHub, tunnel changes, credential rotation, dependency installation or a real
external mutation.

This document assumes the stack is already installed. A new Windows machine
must first follow `operations/FRESH-WINDOWS-INSTALL.md`; do not infer setup
steps from old chronological reports or from the upstream Ollama installer.

Before any operation:

- verify the repository branch and status;
- preserve unknown files;
- never print `.private` content, bearer/HMAC values, cookies or provider
  credentials;
- use a read-only smoke unless Cesar separately names the external target and
  authorizes that mutation;
- do not retry an external action with unknown outcome.

## 2. Managed paths

| Purpose | Path |
|---|---|
| Repository | `D:\dev\workspaces\openjarvis` |
| Active framework state | `D:\dev\runtime\openjarvis\state` |
| Jarvis Agent database | under active state as `jarvis-agent.sqlite3` |
| Runtime logs and process files | `D:\dev\runtime\openjarvis` |
| AceleraChat private environment | `.private\env\acelerachat.env` (ignored; never print or commit) |
| Legacy direct-provider state | under `D:\dev\runtime\openjarvis`; preserved and inactive |
| Baseline backup | `D:\dev\runtime\openjarvis\backups\jarvis-agent-baseline-20260808-233113` |
| State migration evidence | `D:\dev\runtime\openjarvis\backups\state-migration-20260809-000321` |
| Visual smoke evidence | `D:\dev\runtime\openjarvis\visual-smoke\20260809-orchestrator` |
| Preserved rollback | `C:\Users\Cesar\.openjarvis` |

The C: rollback copy is inactive and must not be deleted. State movement is a
local filesystem migration, not an external data migration.

## 3. Runtime map

| Component | Address | Expected owner |
|---|---|---|
| frontend | `http://127.0.0.1:5173` | Vite/OpenJarvis launcher |
| backend | `http://127.0.0.1:8127` | OpenJarvis server |
| Codex app-server | `http://127.0.0.1:8131` | local Codex integration |
| authenticated gateway | `http://127.0.0.1:8140` | tracked remote-access proxy; one owner only |

The normal launcher is `scripts/workspace/start-codex-live.ps1`. It sets
`OPENJARVIS_HOME` and `OPENJARVIS_RUNTIME_ROOT` to D: and binds
`VITE_API_URL` to its selected backend port. Do not start a second backend,
frontend, app-server or bridge on the same ports.

The launcher imports only the six allowlisted `ACELERACHAT_*` names from the
ignored private file. The installer may copy the empty template from
`.workspace\templates\acelerachat.env.example`; it never supplies real values.

Remote test access has a separate lifecycle:

```powershell
scripts\workspace\start-remote-access.ps1 -ValidateOnly
scripts\workspace\start-remote-access.ps1
scripts\workspace\stop-remote-access.ps1
```

The start script requires a healthy backend and compiled frontend, validates
the private gateway file without printing it, starts the tracked gateway from
`src/openjarvis/server/remote_access`, then starts a Cloudflare Quick Tunnel.
It writes the public URL, QR Code and process ledger only under the D: runtime.
The stop script verifies both PID and command line and preserves logs. Never
use either script to replace or stop an unknown owner on port 8140.

## 4. Preflight

Run from the repository root:

```powershell
git status --short --branch
git rev-parse HEAD
git worktree list --porcelain
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -In 5173,8127,8131,8140 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Stop if a port is owned by an unknown process, the branch is unexpected, or
the worktree contains an unexplained overlapping edit.

Read-only health:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/jarvis
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/v1/info
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/v1/codex/catalog
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/v1/jarvis/agent/catalog
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/v1/jarvis/live/status
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/v1/jarvis/agent/catalog
```

The last three requests validate the Vite proxy itself. A healthy 8127 with a
500 from 5173 is a proxy-origin defect, not a Codex or Gemini failure.

Port 8131 is a local Codex transport boundary, not a generic OpenJarvis HTTP
health API. Verify that it is listening and validate Codex through the backend
catalog/info contract; a direct `GET /health` on 8131 currently returns 400.

Do not treat a generic process response as provider capability. The canonical
catalog is the Jarvis authority.

## 5. Catalog diagnosis

Expected current logical Sources:

- AceleraChat e-mail: one explicitly selected/uniquely discoverable e-mail
  inbox and only its declared capabilities.
- AceleraChat WhatsApp: one explicitly selected/uniquely discoverable WhatsApp
  inbox and only its declared capabilities.
- Codex Desktop: available when the app-server responds.
- Hacker News: preserved but `manifest_enabled=false`.

Direct Gmail/IMAP and Baileys connectors remain in source/state for rollback,
but they are not composed into the Jarvis orchestrator and are filtered from
the Data Sources connection UI. Do not re-enable them as a local fallback.

Inspect without dumping message content:

```powershell
$catalog = Invoke-RestMethod http://127.0.0.1:8127/v1/jarvis/agent/catalog
$catalog.sources | ConvertTo-Json -Depth 6
$catalog.tools |
  Select-Object id,effect,available,unavailable_reason
```

If provider state changes after session creation, the next proposal must fail
with `MANIFEST_STALE`, `SOURCE_DISCONNECTED` or
`CAPABILITY_NOT_AVAILABLE`. Never force the stale tool through.

## 6. Session and approval diagnosis

Canonical sequence:

1. `POST /sessions` creates a generation.
2. `POST /sessions/{id}/turns` commits final speech.
3. `POST /sessions/{id}/proposals` creates/executes the tool.
4. Mutation/delegation returns `AWAITING_APPROVAL`.
5. The UI sends `X-Jarvis-Decision-Channel: visual` with the displayed hash.
6. SSE or action/job GET returns the terminal state.

When an approval does not appear:

- inspect the committed turn and any `tool_call_rejected` event; an explicit
  Codex request paired with a status/history/provider proposal must fail as
  `TOOL_INTENT_MISMATCH` and create no action;
- confirm the tool is a `MUTATION` or `DELEGATION` in `/catalog`;
- confirm no other action is already pending in that session;
- inspect safe SSE event types and IDs, not payload contents;
- verify the session generation has not changed;
- do not ask Jarvis to accept a spoken confirmation.

When a spoken “confirmo” is observed:

- it may be committed as a normal turn;
- the pending action must remain `AWAITING_APPROVAL`;
- no adapter call may occur;
- the UI should remind the user to use the button, not ask for another spoken
  confirmation.

## 7. Codex diagnosis

Use status before history. Status is bounded and history-free.

| Symptom | Required interpretation |
|---|---|
| `CODEX_BUSY` | selected thread is active; fail fast and retry only manually later |
| `CODEX_THREAD_INVALID` | thread identity is invalid, not merely slow |
| `CODEX_THREAD_RESUME_TIMEOUT` | bounded resume/history read elapsed |
| `CODEX_DISPATCH_TIMEOUT` | dispatch deadline elapsed; do not retry automatically |
| job still `RUNNING` after voice closes | inspect job/action and recover in next session |
| placeholder instead of response | reconcile canonical job and public Codex history |

Never issue another delegation to diagnose whether the first delegation ran.
Inspect the original `request_id`, `action_id`, `job_id` and selected thread.

For durable command history, query the canonical Agent Core history route with
the same project and selected task used by the UI:

```text
GET /v1/jarvis/agent/events/history?project_key=<project>&codex_thread_id=<task>&limit=100
```

This is a read-only reconciliation path. It must not create an action, approval
or Edge job. The panel combines it with the durable operational event store and
live events by canonical identity.

### Selected-conversation synchronization

`GET /v1/codex/threads/{thread_id}/events` is a read-only channel and must not
load the task history before returning HTTP 200. It registers the event callback
first, then uses official `thread/resume` with `excludeTurns=true` only as a
lightweight rejoin. Its status events are:

| State | Meaning |
|---|---|
| `connecting` | SSE transport is open; lightweight rejoin is starting |
| `live` | Desktop public events are subscribed; history may still be loading |
| `synchronizing` | bounded older pages are being reconciled |
| `synchronized` | a canonical history snapshot was read successfully |
| `degraded` | live transport remains active while bounded history is retried |

`degraded` is non-terminal. Reads are coalesced and retried with exponential
backoff capped at ten seconds; browsers must not reconnect merely because
history is temporarily unavailable. Automatic synchronization must never call
`thread/read includeTurns=true`. It uses paginated summary pages and one
`itemsView=full` read limited to the newest turn so steering messages can be
recovered after a backend restart.

If the UI cycles between `connecting` and `retrying`:

1. verify the SSE request returns HTTP 200 and an immediate `status` event;
2. count `Failed to start Codex thread synchronization` in the current backend
   log; the expected count is zero;
3. verify `live` appears before any snapshot and remains active during a slow
   reconciliation;
4. investigate repeated `degraded` transitions, but do not increase the timeout
   or restore monolithic history reads.

For a `trycloudflare.com` Quick Tunnel, do not use SSE as the acceptance probe.
The frontend selects finite polling automatically. Verify instead:

- `/v1/jarvis/agent/events/poll?after=0&limit=10` returns JSON and a
  `next_after` cursor;
- `/v1/codex/threads/{id}/history` returns the newest bounded page;
- following `next_cursor` returns older pages without repeating the cursor;
- the browser bundle contains `/events/poll` and Quick Tunnel detection.

Named tunnels or other proxies may retain SSE only after an explicit streaming
probe proves that later snapshots and heartbeats are delivered.

When Jarvis reports `Invalid JSON` immediately after starting a voice session:

1. capture the Gemini WebSocket close code/reason without printing the token;
2. verify the canonical manifest contains strict backend schemas;
3. verify the Live setup projection removes unsupported JSON Schema fields;
4. run a real token + setup smoke and require `setupComplete`;
5. do not rotate credentials or alter microphone permissions for a schema
   rejection.

## 8. AceleraChat boundary diagnosis

The OpenJarvis side has one native adapter and two logical providers:

```text
acelerachat_email | acelerachat_whatsapp
```

Configuration is private and server-only:

```text
ACELERACHAT_BASE_URL
ACELERACHAT_BEARER_TOKEN
ACELERACHAT_WEBHOOK_SECRET_CURRENT
ACELERACHAT_WEBHOOK_SECRET_PREVIOUS (optional rotation overlap)
ACELERACHAT_EMAIL_INBOX_ID
ACELERACHAT_WHATSAPP_INBOX_ID
```

Never print these values. A missing token makes API capabilities unavailable.
An invalid/non-HTTPS base URL fails closed. If more than one inbox of a channel
is authorized, configure its ID; the adapter will return
`inbox_selection_required` instead of guessing.

The current production contract still selects one inbox per channel. Inbox 20
is the selected connected Evolution WhatsApp inbox and inbox 16 is the selected
e-mail inbox in the 2026-08-20 release. Do not describe this as automatic access
to every current or future inbox.

Read-only checks:

```powershell
$catalog = Invoke-RestMethod http://127.0.0.1:8127/v1/jarvis/agent/catalog
$catalog.providers |
  Where-Object id -Like 'acelerachat_*' |
  Select-Object id,status,connected,reason
```

Do not call AceleraChat endpoints with a token printed on the command line.
Provider `401`, `403`, `409`, `429`, invalid response and timeout map to stable
public errors. Reads may be repeated manually after diagnosis; mutations must
never be retried automatically when the outcome is unknown.

## 9. E-mail and WhatsApp diagnosis

E-mail is AceleraChat customer-service e-mail, not a generic Gmail mailbox.
Supported operations are search, unread listing, message/conversation read and
reply inside an existing conversation. Archive, trash, new composition and new
attachments are unsupported and must remain absent.

WhatsApp supports provider status, contact/chat search, bounded history,
summary context, text in an existing conversation and an AceleraChat-internal
read marker. A name collision must return choices. Native contextual reply,
reaction, provider read receipt, media upload and administrative operations are
unsupported in contract version `2026-08-18.2`.

For an accepted e-mail reply or WhatsApp text:

1. HTTP acceptance creates an `ACCEPTED` external operation.
2. `message.updated` confirms `delivered`/`read` or `failed`.
3. Missing/out-of-order events are reconciled by read-only `/backfill`.
4. Delivery/event IDs are deduplicated and resource sequence cannot roll a
   terminal action backwards.
5. An event arriving before local acceptance is retained and atomically linked
   when the operation is recorded.

Webhook endpoint:

```text
POST /v1/jarvis/agent/providers/acelerachat/webhooks
```

Configure its public HTTPS URL on the AceleraChat side. The exact POST path may
cross the remote gateway without browser Basic Auth, but the backend rejects it
unless the raw body passes HMAC-SHA256, timestamp tolerance, UUID delivery ID,
schema validation and the 1 MiB body limit. Wrong methods or neighboring paths
remain browser-authenticated.

At startup and after a sequence gap, a single-worker reconciler reads at most
ten pages of 100 snapshots for contacts, conversations and messages. It never
issues an external mutation and shuts down without scheduling new work.

Do not include full e-mail/chat bodies or credentials in operational logs.
Provider content is always untrusted input.

## 10. Context and event diagnosis

Context is optional. A slow Codex history or connector must not prevent Live
startup. The partition key is derived from normalized project and Codex thread.

Expected context sections:

```text
objective | decisions | pending | results | references
```

Full transcript and raw provider content must not appear. Context expires after
30 days from last write. `DELETE /v1/jarvis/agent/context` deletes only the
Jarvis summary for that partition.

SSE reconnects with `Last-Event-ID`. Replayed events update presentation but
must not dispatch an action again.

## 11. Controlled D: migration and rollback

The completed migration used stop, staging, SHA-256, SQLite integrity checks,
count comparison and launcher switch. The original C: tree remains intact.

Before a future migration:

- stop only known OpenJarvis processes;
- capture source/target absolute paths;
- copy to a new D: staging directory;
- never overwrite an existing `knowledge.db`;
- hash source and staging;
- run `PRAGMA integrity_check` on every SQLite database;
- compare Source/chunk counts;
- update launcher paths only after verification;
- keep both the manifest and source rollback.

Rollback procedure:

1. stop known OpenJarvis services;
2. record hashes and database counts of the failed D: generation;
3. restore launcher environment to the preserved C: source;
4. start one backend and verify health/catalog/read-only Sources;
5. do not delete the D: generation until a separate retention decision.

The rollback was documented and path-validated; destructive deletion was not
performed.

## 12. Test gates

### Directed Python gate

The current directed matrix covers AceleraChat capabilities/client/adapters,
opaque references, visual approval, no-retry mutation, provider ledger,
webhook/HMAC, backfill, event races, catalog, policy, persistence, Codex and the
remote gateway.

### Agent Core gate

```powershell
.venv\Scripts\python.exe -m pytest tests\server\jarvis_agent -q
```

Current result: 132 passed together with the remote-gateway suite. The 17-test
direct-provider compatibility suite also passes while those providers remain
preserved but inactive.

### Frontend gate

```powershell
Set-Location frontend
npm test -- --run
npx tsc --noEmit
npm run build
```

Result: 92 tests passed in 22 files, TypeScript passed and the production Vite/PWA build
passed. Existing bundle-size/dynamic-import warnings remain non-blocking.

The selected-conversation synchronization regression passed 140 directed Python
tests plus 4 subtests and 88 frontend tests. A real active-task probe returned
HTTP 200, `connecting` in 704 ms, `live` in 745 ms and 192 public messages in
8.96 seconds, including two steering messages omitted by summary history.

### Chat history race diagnostic

If Jarvis shows `live` but Chat remains stale, do not hide the warning or
restart the Codex app-server first. Confirm these invariants:

1. conversation selection must not call `/v1/codex/threads/{id}/history`;
2. exactly one `/v1/codex/threads/{id}/events` stream owns automatic recovery;
3. the synchronizer uses `thread/resume` only with `excludeTurns=true`;
4. automatic history uses `thread/turns/list`, never monolithic `thread/read`;
5. the newest turn is reconciled with `itemsView=full`, limit 1;
6. a late snapshot merges live canonical item IDs and cannot roll back the UI;
7. local OpenJarvis streaming does not abort the shared Desktop SSE;
8. a disconnected browser must not leave an unobserved shared-read exception.

The complete 2026-08-09 correction is functional commit
`d720d5fc096970d9b1a25556656d8c091f0b5824`. Direct protocol evidence showed
lightweight rejoin in 31-41 ms, while both a 100-turn summary page and one full
active turn took about 7.3-7.5 seconds. Summary exposed 2 active-turn items;
full exposed 301 raw items and the two missing steering messages. Public
filtering retained those user messages and excluded reasoning, commands and
commentary. Backend, frontend, app-server and gateway remained healthy; tunnel
and credentials were preserved.

### Bridge and quality gates

- WhatsApp bridge: 9 tests and TypeScript build passed.
- Ruff check and format check passed for 69 Python files.
- Python `compileall` passed.
- generated contract check passed.
- `git diff --check` passed before the functional commit.

### Connectivity regression - 2026-08-09

- 131 directed Python tests passed.
- 92 frontend tests, TypeScript and production Vite/PWA build passed.
- Ruff check/format, Python compilation, generated contracts and
  `git diff --check` passed.
- Real Gemini Live returned `setupComplete` for 12 canonical tools.
- Local Vite-proxied Codex SSE reached `live` in 0.49 seconds and
  `synchronized` with 376 messages in 13.19 seconds.
- The preserved Quick Tunnel reconciled 376 unique messages over two finite
  pages in 14.5 seconds.
- A browser-exact Agent generation completed a real create/close lifecycle.

### Full upstream suite qualification

The complete upstream suite is not a valid all-green gate in this machine
without changing the authorized environment. Split execution identified
unrelated failures from the missing optional native Rust extension, absent
Gemma/Ollama model, absent user skills, optional `polars`, Windows path/permission
behavior and SQLite teardown locks. One learning group produced 1,363 passes,
10 skips, 6 unrelated failures and 4 Windows teardown errors. No dependency or
model was installed to conceal these conditions.

## 13. Safe smoke

Allowed without a separate mutation authorization:

1. health and catalog;
2. create/close a Jarvis session;
3. operational audit read;
4. AceleraChat e-mail search/read;
5. AceleraChat WhatsApp status/contact/chat/history reads;
6. Codex status/history on an idle task;
7. create a Codex proposal and deny it visually;
8. duplicate/expired/wrong-hash/session-close simulations;
9. verify context does not contain the full transcript.

Not allowed in the normal gate:

- sending e-mail or WhatsApp messages;
- the AceleraChat-internal read marker;
- approving a real Codex delegation;
- changing AceleraChat provider authentication;
- changing OAuth, Gemini or gateway credentials.

## 14. Prior direct-provider gate evidence (historical)

The following evidence predates the AceleraChat adapter and is retained only to
document the prior direct Gmail/Baileys generation. It must not be used as live
AceleraChat acceptance.

Read-only runtime smokes completed in that prior generation:

- backend/frontend health and backend Codex catalog/info returned HTTP 200;
- the Codex process was listening on 8131; its unsupported direct `/health`
  path returned HTTP 400 as expected for that boundary;
- catalog returned 32 tools and 12 currently available manifest functions;
- operational audit, Gmail search, WhatsApp status and Codex status completed;
- Codex history completed on an idle task;
- the active task reached `live` before history and reconciled 192 public
  messages, including active-turn steering sent before the backend restart;
- a Codex proposal was created and denied, with duplicate, spoken confirmation,
  missing visual header and wrong hash all blocked as designed;
- no external mutation occurred.

Visual evidence:

- `jarvis-local-clean.png` proves the refactored Jarvis composition renders.
- the delayed DOM smoke proves Data Sources renders provider truth: Gmail OAuth
  disconnected, Gmail IMAP connected, Baileys disconnected, Meta unavailable,
  Export import-only and Codex connected.

At the automated sub-gate, the restarted Codex session did not expose the
installed Windows browser-control runtime, so Codex did not claim the rendered
click path. Cesar later executed and approved the visual gate.

Final operator acceptance at 2026-08-09 14:08 -03:00:

- WhatsApp status returned `connected`;
- Gmail unread listing completed;
- WhatsApp conversation history completed;
- one separately authorized text was sent to `Klaus Consultor`, with read
  receipt confirmed;
- both visual approval and visual denial worked on suspended proposals.

All five reported scenarios passed. A read-only catalog check made while
recording the report independently confirmed Gmail IMAP connected, WhatsApp
Baileys connected with live capabilities and Codex Desktop available. The
message send was not repeated. The tunnel was not changed.

## 15. AceleraChat implementation gate - 2026-08-18 07:04 -03:00

Current automated evidence:

- 132 Jarvis Agent Core/remote-gateway tests passed;
- 17 focused adapter/webhook tests passed;
- 17 preserved direct-provider compatibility tests passed;
- 92 frontend tests passed in 22 files;
- TypeScript and Vite/PWA production build passed;
- Ruff check/format, generated-contract parity, Python compilation, PowerShell
  parsing and `git diff --check` passed;
- local backend/frontend/Codex app-server started through the tracked launcher
  with `-SkipDesktop`;
- backend, frontend, Vite proxy and the 16-tool catalog returned HTTP 200;
- one real Agent session completed `ACTIVE -> CLOSED`, and the WhatsApp status
  read completed without external mutation;
- a 1 MiB-plus webhook returned HTTP 413 with `WEBHOOK_INVALID_PAYLOAD`;
- backend/frontend had no error-level entry; app-server recorded only the
  expected WARN socket 10054 caused by the controlled backend restart;
- the build retained pre-existing chunk-size/dynamic-import warnings;
- no external API mutation, provider credential, external provider service,
  gateway or tunnel was changed.

Live AceleraChat smoke is pending the external deployment and private
configuration. The current Codex session did not expose browser-control tooling,
so visual click-path and tablet/tunnel acceptance were not claimed. Required
sequence after that separate authorization:

1. verify catalog providers without printing secrets;
2. read e-mail unread/search and one conversation;
3. read WhatsApp status, contact search and one conversation;
4. create one mutation proposal and deny it visually;
5. only with a separately named target, approve one mutation and verify
   `ACCEPTED -> COMPLETED|FAILED` through webhook/backfill;
6. verify the action appears identically in Jarvis, Chat and context.

## 16. Change declaration

- Deploy: no.
- External migration: no.
- GitHub settings, PR or push: no.
- Credentials: no.
- Tunnel: no.
- Local runtime: backend, frontend and shared app-server started with the tracked
  launcher using `-SkipDesktop`; left running for local inspection.
- AceleraChat external deployment/configuration: no.
- External AceleraChat mutation: no.
- Local state migration in this task: no; the prior C: to D: migration remains
  preserved as historical state.
- External mutation in this task: no. The direct-provider text to
  `Klaus Consultor` belongs only to the historical 2026-08-09 acceptance.
- External e-mail or Codex mutation during current gates: no.
