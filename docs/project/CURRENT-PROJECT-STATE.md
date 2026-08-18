# Current project state

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-18 13:20:52 -03:00
Working tree base: `4b2b16ab6ffce6f100180cfa40780f8296690515`
Branch: `codex/vps-edge-mcp`
Remote publication: private `https://github.com/tadashiyukoyama/openjarvis-codex`

## Executive status

The server-side Jarvis Agent Orchestrator now composes AceleraChat as the sole
active e-mail and WhatsApp execution boundary, plus Codex Desktop. Gemini Live
proposes functions; the backend owns capability, policy, approval, idempotency,
dispatch, provider-event reconciliation, jobs, context and canonical results.

Direct Gmail/IMAP and Baileys code/state remain preserved but dormant. They are
not in the active Jarvis catalog and no longer appear as connection controls in
Data Sources. The earlier direct-provider acceptance below remains historical
evidence; it is not evidence of a live AceleraChat deployment.

The hybrid VPS/Windows boundary is now implemented locally: a VPS-mode Core,
outbound authenticated Edge WSS, durable Edge jobs/leases, a persistent Windows
worker using the loopback Codex app-server, nested visual approvals and a
filtered Codex MCP STDIO facade. Release artifacts and runbooks exist, but no
VPS, DNS, TLS, OpenResty, task, credential or runtime was changed in this gate.

## Edge Worker and MCP preparation — 2026-08-18 13:09 -03:00

Implemented on `codex/vps-edge-mcp`, based on the local AceleraChat checkpoint
`4b2b16ab6ffce6f100180cfa40780f8296690515`:

- Edge protocol `1.0` with closed generated schemas and sanitized fixtures;
- device authentication with current/previous overlap, fingerprinting and
  revocation that cannot be cleared by reconnecting;
- heartbeat, offline truth, reconnect jitter, resume and durable frame spool;
- Core-owned jobs, attempts, leases, deduplication and restart reconciliation;
- immediate offline failure instead of an invisible Codex queue;
- Windows Edge Worker that keeps 8131 loopback-only and reuses the installed
  Codex app-server protocol;
- nested native Codex approval rendered through the existing exact visual gate;
- VPS Codex catalog/history proxy using bounded Edge read jobs;
- MCP STDIO derived from the canonical catalog, capped at 13 and excluding all
  Codex tools and the legacy executor;
- authenticated Windows named pipe between MCP and the persistent worker;
- path-allowlisted worker relay to the Core, so Codex receives no VPS Bearer;
- non-root, read-only, resource-limited VPS container/Compose artifacts;
- isolated OpenResty sample for PWA, Agent API, Gemini, Edge and webhook;
- external mutations disabled by default for the first release;
- Windows task scripts and bounded rotating Edge logs.

No Edge worker service was registered or started, no container was built and no
remote endpoint was contacted. Docker/OpenResty binaries are unavailable in the
current Windows session, so image reproducibility and `openresty -t` remain
release gates rather than claimed results.

## AceleraChat native integration - 2026-08-18 07:04 -03:00

Implemented in the current working tree:

- private, no-retry AceleraChat HTTP client with streaming-bounded responses
  and stable errors;
- live inbox/capability discovery with explicit selection when ambiguous;
- five e-mail tools and seven WhatsApp tools matching contract version
  `2026-08-18.2`;
- opaque references, bounded presentation and untrusted-data marking;
- visual approval and one-attempt idempotent mutation dispatch;
- durable `ACCEPTED` external operations;
- signed, timestamped, idempotent webhook ingestion;
- per-resource sequence protection, gap detection and read-only backfill;
- atomic reconciliation when a webhook arrives before local operation
  acceptance;
- terminal provider transitions emitted once even when delivery is duplicated;
- 1 MiB webhook limit enforced while reading at both gateway and backend;
- exact webhook gateway exception protected by backend HMAC;
- server-only launcher configuration from an ignored allowlisted private file;
- Data Sources presentation owned by AceleraChat, without local Gmail/Baileys
  setup panels.

No AceleraChat secret was opened, copied or changed. No live AceleraChat API or
external mutation was exercised. Live acceptance remains blocked until the
AceleraChat implementation is deployed and its token, webhook secret, inbox IDs
and callback URL are configured through the private boundary.

## Clean repository distribution - 2026-08-09 15:53 -03:00

Preparation is active on `codex/clean-repository-distribution`, based on
`0709013acb7e7015f7a45f2b41ed6462978ee0b5`. The goal is one clean GitHub
source repository that can reproduce the accepted Windows stack without
publishing personal runtime state.

Executable distribution tooling is committed locally as
`ff5df65b7766960b034a699c65c430d86c4c00de`; atomic snapshot refresh is
`3363076dff8950ab966146136da0cd3942cf2980`.

Implemented locally:

- canonical fresh-Windows installation and acceptance runbook;
- D:-only bootstrap for locked Python/frontend/Baileys dependencies;
- private Gemini and gateway templates with empty values;
- source-tracked authenticated gateway and guarded Quick Tunnel lifecycle;
- credential-free tunnel URL QR generation;
- publication verifier for private paths, secrets, unexpected large files and
  uncommitted tracked changes;
- parentless Git snapshot builder so the future clean repository receives only
  the approved tree, license and provenance, not development history.

Current validation:

- 14 authenticated-gateway tests passed;
- 112 Jarvis Agent Core tests passed;
- Ruff check/format passed for the new Python package and tests;
- all six PowerShell files parsed successfully;
- remote-access `-ValidateOnly` passed against the live backend without changing
  the current gateway/tunnel;
- a credential-free HTTPS QR was generated and inspected;
- the publication scan found no forbidden tracked path, unexpected large file or
  possible sensitive value;
- bootstrap preflight found the current installed runtime artifacts but reported
  `uv` missing from this machine's `PATH`; no dependency was installed to hide
  that prerequisite.

Local code/documentation commits, the clean-publication scan and a parentless
snapshot/tree-identity validation are complete. César selected the private
repository `tadashiyukoyama/openjarvis-codex` and authorized publication of only
the verified snapshot as `main`. No development-history branch, tag, runtime
state or credential is part of that distribution. The currently running app and
temporary tunnel were not restarted.

## Connectivity recovery - 2026-08-09 13:27 -03:00

The Chat `connecting` state and Jarvis `Invalid JSON` failure had independent,
reproducible causes. The correction is functional commit
`c7687ddb5efe4ede9caa063cb1144574f951947d`.

- Vite proxied local `/v1`, `/api` and `/health` requests to port 8000 while
  the audited backend runs on 8127. The launcher now sets `VITE_API_URL`
  explicitly and the development fallback matches port 8127.
- Gemini Live rejected canonical JSON Schema fields such as
  `additionalProperties` and closed the socket with code 1007. The Live
  boundary now projects the backend schema onto the supported Gemini Schema
  subset while backend validation remains authoritative.
- Cloudflare Quick Tunnels buffer SSE and are unsuitable as the only event
  transport. Local/named transports keep SSE; `trycloudflare.com` uses bounded,
  cursor-based finite polling for Jarvis events and Codex history.
- Nanosecond session generations exceeded JavaScript's exact integer range,
  causing valid close callbacks to be rejected. New generations use exact
  epoch microseconds; `session_id` remains the primary identity.

Runtime proof after restart:

- all backend routes through `http://127.0.0.1:5173` returned HTTP 200;
- local Codex SSE reached `live` in 0.49 seconds and `synchronized` with 376
  public messages in 13.19 seconds;
- the real Gemini Live service returned `setupComplete` for all 12 manifest
  tools;
- a real Agent session was created and closed as `CLOSED` using its
  JavaScript-exact generation;
- the preserved Quick Tunnel returned 376 unique messages across two finite
  pages in 14.5 seconds and served the bundle containing the polling path.

Final directed gates: 131 Python tests and 92 frontend tests passed; generated
contracts, TypeScript, production Vite/PWA build, Ruff check/format, Python
compilation and `git diff --check` passed. No external mutation, deploy,
migration, credential, tunnel or GitHub change occurred during these protocol
smokes. This evidence did not itself claim visual acceptance; the later
user-operated acceptance is recorded below.

## Git and workspace

| Field | Current value |
|---|---|
| Canonical repository | `D:\dev\workspaces\openjarvis` |
| Branch | `codex/vps-edge-mcp` |
| Current HEAD/base | `4b2b16ab6ffce6f100180cfa40780f8296690515` |
| AceleraChat integration | local checkpoint `4b2b16ab`; no push from this branch |
| Distribution preparation base | `0709013acb7e7015f7a45f2b41ed6462978ee0b5` |
| Distribution tooling commit | `ff5df65b7766960b034a699c65c430d86c4c00de` |
| Snapshot refresh commit | `3363076dff8950ab966146136da0cd3942cf2980` |
| Distribution remote | `https://github.com/tadashiyukoyama/openjarvis-codex.git` (private) |
| Push/PR | clean snapshot on `main`; no PR |
| Additional worktree | none created for this implementation |
| Preserved untracked items | `.manus-audit/`, root `node_modules/`, `frontend/pnpm-lock.yaml` |
| Baseline backup | `D:\dev\runtime\openjarvis\backups\jarvis-agent-baseline-20260808-233113` |

Unknown/unrelated items were not deleted or committed.

## Runtime

| Component | Address | Final gate |
|---|---|---|
| Frontend | `127.0.0.1:5173` | HTTP 200 |
| Backend | `127.0.0.1:8127` | HTTP 200 |
| Codex app-server | `127.0.0.1:8131` | listening; backend catalog/info HTTP 200 |
| Remote gateway | `127.0.0.1:8140` | offline; not started or modified in this task |
| VPS Core/Edge Worker | not installed | source and release artifacts only |

The frontend, backend and a shared Codex app-server were started by the tracked
launcher with `-SkipDesktop` for the final local smoke. The already open Codex
Desktop was not restarted. The frontend and backend health routes, the Vite
proxy and the 16-tool Agent catalog returned HTTP 200. A real Agent session
completed `ACTIVE -> CLOSED`, and the WhatsApp status read completed without an
external mutation. Port 8140 and the tunnel remained offline and unchanged.

## Jarvis Agent Core

| Capability | State |
|---|---|
| Canonical catalog | 16 registered typed tools |
| Current Live manifest | dynamically filtered by AceleraChat inboxes and Codex state |
| Session lifecycle | generation-bound, close invalidates late callbacks |
| Approval | visual-only, one pending action, five-minute expiry, exact hash |
| Idempotency | session + function call + payload hash |
| Long Codex operations | asynchronous job plus canonical SSE result |
| Context | structured, project/thread partitioned, 30-day retention |
| Persistent transcript | disabled; only transient final text before redaction |
| Operational events | server-assigned and privacy-safe |
| External retries | disabled for mutations/delegations |

The public API is mounted at `/v1/jarvis/agent`. Its generated contracts are in
`contracts/jarvis-agent.openapi.json` and
`frontend/src/features/jarvis/api/generated-contracts.ts`.

## Source state

Current architectural source state at 2026-08-18 07:04 -03:00:

| Source/provider | State | Jarvis capability |
|---|---|---|
| Jarvis local | code available | operational audit read |
| AceleraChat e-mail | live state not configured/verified in this task | search, unread, message/conversation read and approved reply when the selected inbox declares them |
| AceleraChat WhatsApp | live state not configured/verified in this task | status, contacts, chats, history, summary, approved text and internal read marker when declared |
| Direct Gmail/IMAP | preserved, inactive | absent from active manifest and Data Sources controls |
| Direct WhatsApp Baileys | preserved, inactive | absent from active manifest and Data Sources controls |
| Codex Desktop | preserved existing integration | status, recent history and visually approved delegation when available |
| Hacker News | preserved | excluded from the Jarvis manifest |

Previously recorded Gmail and Hacker News data remains preserved. This change
does not delete or migrate direct-provider data; it only removes those providers
from active Jarvis composition.

## State placement

| State | Path and result |
|---|---|
| Active OpenJarvis state | `D:\dev\runtime\openjarvis\state` |
| Runtime root | `D:\dev\runtime\openjarvis` |
| Jarvis Agent SQLite | active on D: with WAL, foreign keys and busy timeout |
| Migration evidence | `D:\dev\runtime\openjarvis\backups\state-migration-20260809-000321` |
| C: rollback | `C:\Users\Cesar\.openjarvis`, preserved and inactive |

The controlled migration copied to staging, verified SHA-256, ran SQLite
integrity checks and compared Source counts. Existing D: databases were not
overwritten. The C: rollback was not deleted.

## Frontend state

- `JarvisPage.tsx` and `DataSourcesPage.tsx` are composition pages.
- Jarvis concerns are split into API, session, approvals and timeline modules.
- Data Sources concerns are split into controller hooks, cards, provider
  overview, messaging and memory modules.
- Data Sources hides direct Gmail/Baileys connectors and renders canonical
  AceleraChat e-mail/WhatsApp provider state from the Agent catalog.
- Gemini Live transport is split into setup, audio and transcript helpers.
- The legacy frontend delegation/router/catalog authority was removed.
- A session uses either the server orchestrator path or no orchestration; two
  orchestrators do not run together.
- Codex conversation SSE subscribes through the official lightweight
  `thread/resume` contract with `excludeTurns=true`; live public events are the
  primary data path.
- History reconciliation uses bounded `thread/turns/list` pages. The newest
  turn alone is also read with `itemsView=full` so steering messages survive a
  backend restart; reasoning, commands and commentary remain excluded.
- New AceleraChat production modules are at most 292 lines; transport,
  capabilities, e-mail, WhatsApp directory, webhooks, reconciliation and
  persistence outcomes are separate responsibilities.

## Validation

| Gate | Result |
|---|---|
| Jarvis Agent Core + remote gateway | 132 passed; one upstream TestClient deprecation warning |
| AceleraChat adapter/webhook focused matrix | 17 passed |
| Preserved direct-provider compatibility suite | 17 passed; one upstream TestClient deprecation warning |
| Frontend Vitest | 92 passed in 22 files |
| Frontend TypeScript | passed through production build |
| Vite/PWA production build | passed |
| Ruff check | passed for Jarvis Agent Core and tests |
| Ruff format | passed for 85 Python files |
| Generated OpenAPI/TypeScript contracts | regenerated and parity check passed |
| Python compileall, PowerShell parser and `git diff --check` | passed |

Edge/MCP directed validation in the current branch:

- 310 directed Python tests passed for Agent Core, Edge Worker and MCP;
- 94 frontend tests passed in 23 files;
- TypeScript no-emit check passed;
- 14 Edge named-pipe tests passed, including an actual authenticated Windows
  pipe round trip;
- generated Agent and Edge contracts match runtime schemas;
- four new Edge PowerShell files parse successfully;
- static release-artifact policy tests pass;
- Docker image build, Compose rendering, OpenResty syntax and remote visual
  smokes remain pending because their runtimes/deployment were not authorized
  or available.

The final live backend rejected a 1 MiB-plus webhook with HTTP 413 and
`WEBHOOK_INVALID_PAYLOAD`. Backend and frontend contained no error-level,
traceback or critical entry. The app-server recorded one expected WARN socket
10054 when the launcher restarted the local backend connection. Browser-control
tooling was not exposed to this Codex session, so this task does not claim a
visual click-path gate. Live AceleraChat and tablet/tunnel acceptance remain
pending the external deployment and private configuration described below.

The full upstream suite was also attempted. It is not all-green in this local
environment for unrelated, pre-existing reasons: optional native Rust extension
absent, Gemma/Ollama model absent, user skills absent, optional `polars` absent,
Windows path/permission behavior and SQLite teardown locks. No dependency or
model was installed to alter that evidence. A split learning group produced
1,363 passes, 10 skips, 6 unrelated failures and 4 Windows teardown errors.

## Runtime smoke

Read-only real smokes completed:

- operational audit: `COMPLETED`;
- Gmail search: `COMPLETED`;
- WhatsApp status: `COMPLETED`;
- Codex status: `COMPLETED`;
- Codex recent history on an idle task: `COMPLETED`;
- selected-conversation SSE on the current 190-message task: HTTP 200,
  `connecting` at 520 ms and `live` at 558 ms;
- reconciled snapshot: 192 public messages at 8.96 seconds, including both
  steering messages sent during the active turn;
- post-restart backend log: zero history timeout/reconnect loops and no
  monolithic `thread/read includeTurns=true` request.

### Chat history follow-up — 2026-08-09 03:42 -03:00

The remaining `History unavailable` symptom was a separate frontend race: chat
selection started a one-shot `/history` request while the canonical SSE was
already connected. The active Codex task can legitimately exceed that one-shot
request's five-second deadline, so its error overwrote the healthy stream state.

Functional commit: `3ad49898ced5b962c45fac9a66e0ab705cab3bed` on
`codex/jarvis-agent-orchestrator`.

- selected conversations now recover history only through the coalesced SSE;
- a connected or degraded SSE clears stale one-shot loading/error state;
- the sidebar reports connection/catch-up state instead of the false terminal
  `History unavailable` warning;
- abandoned shared history reads retrieve late exceptions and no longer emit
  `Task exception was never retrieved`;
- local services were restarted without changing the tunnel;
- ports 5173, 8127 and 8131 returned HTTP 200; gateway 8140 remained protected;
- a real SSE probe on the active task again returned `connected` followed by
  non-terminal `degraded`;
- the served frontend module contained the new catch-up state and no old warning.

Files changed: `CodexTargetSelector.tsx`, `store.ts`, its synchronization test,
`codex_history_reader.py`, its server test and generated TypeScript build info.
No deploy, external migration, credential, tunnel or GitHub change occurred.

### Canonical Codex synchronization follow-up - 2026-08-09 04:53 -03:00

The stale Chat state was not a presentation-only defect. The SSE transport was
connected while its data plane repeatedly requested the entire long task with
`thread/read includeTurns=true`. Those requests timed out, leaving the last
successful snapshot in the UI. The official app-server protocol was audited
against the installed schema and measured on the real task.

Functional commit: `d720d5fc096970d9b1a25556656d8c091f0b5824` on
`codex/jarvis-agent-orchestrator`.

- event subscription now uses `thread/resume` with `excludeTurns=true` and
  completed in 31-41 ms in direct protocol probes;
- live message/delta notifications are delivered before history is available;
- summary history is bounded and paginated instead of loading the whole task;
- one bounded full read of only the newest turn recovers user steering messages
  omitted by `itemsView=summary` after a backend restart;
- a snapshot that finishes after a live event is merged by canonical item ID
  and cannot roll the Chat back;
- local streaming no longer disables the shared Desktop synchronization;
- repeated public text such as `Sim` is aligned to the most recent sequence,
  never to the first equal message in the task;
- Codex status, recent-history tools and selected-thread validation use the
  same lightweight/paginated contracts.

Real smoke after restart: `live` in 745 ms; 192 public messages reconciled in
8.96 seconds; the two current steering messages were present; reasoning,
commands and commentary were absent. Backend `8127`, frontend `5173`, app-server
`8131` and gateway `8140` remained active. The existing tunnel was preserved.

At this earlier sub-gate the browser-control runtime was unavailable, so no
rendered UI acceptance was claimed by Codex. Cesar subsequently performed and
approved the visual gate recorded below. No deploy, external migration,
credential, tunnel or GitHub change occurred.

Approval/security smoke for a Codex proposal:

- initial state `AWAITING_APPROVAL`;
- exact command preview and payload hash returned;
- duplicate function call returned the same action;
- spoken `Confirmo` did not authorize it;
- missing visual header returned HTTP 403;
- wrong hash returned HTTP 409;
- visual denial returned `DENIED`;
- no Codex turn was executed.

Context inspection confirmed that the full transcript was not retained.

## Prior direct-provider visual acceptance - 2026-08-09 14:08 -03:00

The refactored local Jarvis page was rendered and visually inspected from:

`D:\dev\runtime\openjarvis\visual-smoke\20260809-orchestrator\jarvis-local-clean.png`

A delayed browser DOM smoke also verified the rendered provider panel and its
truthful states for Gmail OAuth/IMAP, WhatsApp Baileys/Meta/Export and Codex.

Cesar supplied the final operator report and confirmed all five scenarios:

1. WhatsApp state query returned `connected`.
2. Gmail unread-message listing completed successfully.
3. WhatsApp conversation history was read successfully.
4. A text message was sent to `Klaus Consultor`, and its read receipt was
   confirmed. This was the separately authorized real mutation for acceptance;
   it was not repeated by Codex while documenting the result.
5. Visual approval and denial through the suspended-proposal buttons both
   behaved as expected.

A read-only catalog check at documentation time independently confirmed Gmail
IMAP connected, WhatsApp Baileys connected with live capabilities, and Codex
Desktop available. The final operator report is the authority for the rendered
button behavior and the real message/read-receipt result.

All acceptance tests listed above passed for the prior direct-provider
generation. AceleraChat live acceptance remains open as stated in the current
executive section. The historical gate does not add unsupported capabilities.

## Change declaration

- Deploy: no.
- VPS: no.
- External migration: no.
- GitHub, PR, merge or push: no.
- Credentials: no.
- Tunnel: no.
- Local runtime: backend, frontend and shared app-server started with the tracked
  launcher using `-SkipDesktop`; left running for local inspection.
- Dependency/model installation: no.
- Local managed-state migration in this task: no; the prior D: migration remains
  preserved and rollback-capable.
- External mutation in this task: no. The user-authorized text to
  `Klaus Consultor` is historical direct-provider evidence only.
- External e-mail or Codex mutation during current gates: no.
- AceleraChat deployment or configuration: no.
- Edge Worker task/service installation: no.
- Container build or VPS Core installation: no.
- DNS, TLS or OpenResty reload: no.
