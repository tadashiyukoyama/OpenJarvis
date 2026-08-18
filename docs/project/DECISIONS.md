# Decisions

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-18 13:20:52 -03:00
Applies through local Edge/MCP implementation on `codex/vps-edge-mcp`, based on `4b2b16ab6ffce6f100180cfa40780f8296690515`
Supersedes: none
Superseded by: none

## OJ0-D01 - Local staging on D

- Decision: establish `OPENJARVIS_WORKSPACE_ROOT` as the permanent local
  workspace root.
- Reason: keep project-managed files on D and make rehydration predictable.
- Consequence: machine-specific paths stay in ignored local configuration.
- Evidence: OJ0 preflight and project portable identity.

## OJ0-D02 - No official download in OJ0

- Decision: defer clone, fork and code acquisition until OJ1 is separately
  authorized after this report is reviewed.
- Reason: OJ0 is foundation-only and must not make network changes.
- Consequence: Git root, remotes and source SHAs remain unknown.

## OJ1-D03 - Controlled fork promotion

- Decision: use tadashiyukoyama/OpenJarvis as origin, open-jarvis/OpenJarvis
  as upstream, and promote the verified partial clone to the canonical root.
- Reason: establish the product fork without overwriting upstream files.
- Consequence: the foundation is versioned on
  ops/openjarvis-workspace-foundation at the live SHA
  3000116d181eb69737241c09eaa70d4c65eb80a0.
- Evidence: clone state, collision scan, D: staging hash backup and Git root
  verification.

## OJ1-H-D04 - Lifecycle automation remains disabled

- Decision: keep `new-task.ps1`, `close-task.ps1`, `register-worktree.ps1` and
  `remove-worktree.ps1` as neutral safe stubs.
- Reason: worktree lifecycle mutation requires a verified ledger, status and
  untracked checks, commit and PR/task disposition, transactional ledger
  update and filesystem confirmation.
- Consequence: no task or worktree can be created, closed, registered or
  removed by automation in this phase.
- Evidence: OJ1-H script gate and workspace-foundation test coverage.

## OJ-JARVIS-D05 - Visual approval is the sole mutation authority

- Decision: every Codex delegation and every external Data Source mutation
  remains suspended in its original Gemini function call until Cesar selects
  `Autorizar e executar` or `Negar` in the Jarvis interface.
- Reason: a spoken `sim`, `confirmo` or model-generated function call is not a
  durable, unambiguous authorization boundary.
- Consequence: Jarvis must not ask for confirmation by voice, must not issue a
  second function call and must treat the button result (`complete`, `rejected`,
  `expired`, `session_closed` or `approval_busy`) as authoritative.
- Evidence: `JarvisApprovalCoordinator`, Gemini setup policy and approval tests.

## OJ-JARVIS-D06 - Only committed speech turns may create intent

- Decision: partial transcripts are accumulated and only one final committed
  turn may reach routing or tool authorization.
- Reason: Gemini Live can emit several fragments and late callbacks for one
  human utterance.
- Consequence: session generations invalidate old callbacks before shutdown;
  duplicate finals and callbacks from closed sessions are ignored and logged
  as metadata.
- Evidence: `TurnAssembler`, session-generation checks and lifecycle tests.

## OJ-JARVIS-D07 - Tool routing is deterministic and fail-closed

- Decision: Gmail and WhatsApp requests use their registered Data Source tools;
  Codex is eligible only when Cesar explicitly names Codex as the destination.
- Reason: prompt-only routing previously converted source requests into Codex
  commands.
- Consequence: ambiguity or unavailable tools produce a controlled explanation,
  never a silent fallback to Codex.
- Evidence: tool catalog, runtime route validation and routing tests.

## OJ-JARVIS-D08 - Codex concurrency fails fast without hidden retries

- Decision: a busy Codex conversation is rejected immediately; dispatch and
  resume have bounded, distinct timeouts and no retry that could create a
  duplicate turn.
- Reason: Desktop-owned turns were invisible to the local runtime and resume
  timeouts left Jarvis waiting or produced a second attempt.
- Consequence: public stable error codes distinguish busy, missing thread,
  invalid project, closed session, resume timeout, dispatch timeout and
  duplicate request. A timed-out turn is interrupted only by its exact ID.
- Evidence: Codex agent/conversation runtime tests.

## OJ-JARVIS-D09 - Canonical responses and privacy-safe telemetry

- Decision: the selected Codex thread history is the canonical source for the
  final assistant response; operational telemetry stores correlation IDs,
  hashes and lengths instead of private message or command bodies.
- Reason: transport acknowledgements are not assistant responses, while full
  payloads in operational logs create unnecessary privacy exposure.
- Consequence: Jarvis and Chat receive the complete canonical response under
  one request ID; the operational log remains safe for diagnostics.
- Evidence: shared dispatcher, history recovery, observability and SSE tests.

## OJ-JARVIS-D10 - Baileys state must be process-backed

- Decision: WhatsApp Baileys reports connected and send-capable only while the
  bridge process is alive and has emitted a real connected transition.
- Reason: a stale generic status concealed 401, conflict and logged-out states.
- Consequence: QR required, conflict, logged out and failed remain distinct,
  timestamped states and never alter Codex availability.
- Evidence: channel status snapshots and Baileys lifecycle tests.

## OJ-JARVIS-D11 - Baileys auth is managed on D: and reset is explicit

- Decision: the launcher-managed Baileys runtime and authentication state live
  under `OPENJARVIS_RUNTIME_ROOT` on D:. Authentication outside that runtime is
  never deleted automatically.
- Reason: a legacy logged-out session under the Windows user profile both
  violated the project storage rule and made QR recovery ambiguous.
- Consequence: a logged-out state exposes one explicit reset action; the reset
  requires confirmation, affects only the managed D: directory, moves the old
  generation atomically to `auth-quarantine` and starts a fresh QR session.
  The UI displays QR readiness separately from bridge startup and terminal
  failures.
- Evidence: managed-path reset tests, external-path refusal test, status
  presentation tests and controlled Chromium QR smoke on 2026-08-08.

## OJ-JARVIS-D12 - Baileys reconnects transiently without stale failure state

- Decision: disconnect reasons classified as transient create a new socket
  generation and clear the expired QR/error; terminal authentication or
  session failures stop the bridge and require explicit user action.
- Reason: an expired QR returned status 408, reconnected successfully and then
  exposed a new QR together with the previous error, producing a contradictory
  public state.
- Consequence: callbacks from superseded sockets are ignored; a new QR is
  always published without stale error, and a terminal failure always removes
  stale QR data before becoming public.
- Evidence: bridge TypeScript build, three lifecycle regression tests, 47
  directed Python tests and repeated real API snapshots on 2026-08-08.

## OJ-JARVIS-D13 - WhatsApp authentication QR never enters operational logs

- Decision: the Baileys QR is emitted only through the structured stdout event
  consumed by the protected local API; it is never rendered on stderr.
- Reason: a terminal-rendered QR is still an authentication credential and can
  be reconstructed from an otherwise ordinary diagnostic log.
- Consequence: the Sources interface keeps receiving the QR, while backend and
  bridge logs retain only safe lifecycle metadata.
- Evidence: bridge TypeScript build and a real QR generation where the newly
  appended backend log segment contained no QR block glyphs.

## OJ-JARVIS-D14 - Codex status preflight is bounded and history-free

- Decision: the busy preflight reads only the canonical thread status with
  `includeTurns=false`; full history is read only when a completed response
  must be recovered.
- Reason: a 177-turn conversation made `thread/read` with full history exceed
  the two-second status timeout before any Codex turn was started.
- Consequence: active or system-error states fail closed, status timeout and
  dispatch timeout have distinct public codes, and an SSE error can never be
  recorded as a successful assistant response.
- Evidence: live protocol timing, Codex runtime/agent tests and frontend SSE
  regression tests on 2026-08-08.

## OJ-JARVIS-D15 - Baileys transport and authentication are restart-safe

- Decision: the Python bridge boundary is UTF-8 strict, individual data events
  are isolated, operation/protocol errors do not mutate connection state, and
  the primary authentication credential is written atomically with one valid
  local backup.
- Reason: Windows `cp1252` decoding stopped the reader after synchronized data,
  while a non-atomic `creds.json` had become zero bytes and left a connection
  that survived only in the old Node process memory.
- Consequence: connection failures remain distinct from command failures; a
  corrupt primary credential is restored from its last valid backup. An empty
  directory may start a first pairing, while invalid credentials or residual
  session artifacts without a valid snapshot return `AUTH_INCONSISTENT` and
  require explicit preservation before a new QR is generated.
- Evidence: UTF-8/process lifecycle tests, scoped-error tests, four atomic
  credential tests and the controlled local restart on 2026-08-08.

## OJ-JARVIS-D16 - Baileys QR is versioned, atomic and non-cacheable

- Decision: every QR event increments a process-local generation and records
  its own issuance time; the protected API returns QR, generation and channel
  state from one atomic snapshot with browser and gateway caching disabled.
- Reason: Baileys can supersede a QR while the Sources page remains open. A
  one-time fetch left the previous credential visible and the phone rejected
  it immediately.
- Consequence: the Sources page monitors `CONNECTING` and `QR_REQUIRED` even
  when mounted after the bridge starts, clears the previous image before
  rendering a new generation, aborts callbacks on unmount and stops on
  connected or terminal states. A monitoring failure removes the visible QR
  instead of leaving a potentially stale credential scannable.
- Evidence: monitor/cache regression tests, atomic channel/router tests and a
  live generation change from 2 to 3 with `Cache-Control: no-store` on
  2026-08-08.

## OJ-JARVIS-D17 - Executor and subject are independent routing dimensions

- Decision: the explicitly requested executor has precedence over subjects
  mentioned in a request. A request to report a WhatsApp or Gmail failure to
  Codex is a Codex delegation; a request to mutate WhatsApp or Gmail uses the
  corresponding Data Source tool.
- Reason: classifying only by source keywords blocked explicit diagnostic
  delegations such as "relate ao Codex que o WhatsApp falhou".
- Consequence: the runtime applies one deterministic route guard after Gemini
  proposes a tool. Explicit Codex delegation still requires visual approval;
  direct source mutations cannot silently fall back to Codex, and ambiguous
  mutations fail closed.
- Evidence: the canonical intent classifier, runtime route guard and regression
  tests for Codex-as-executor with WhatsApp-as-subject on 2026-08-08.

## OJ-JARVIS-D18 - WhatsApp identity and message keys are server-resolved

- Decision: contacts and chats are resolved with explicit PN, LID and group
  identities. A model may select only an opaque `message_ref`; the backend
  resolves the complete Baileys key and waits for a correlated bridge result.
- Reason: treating every JID as a phone JID and accepting a raw message/JID pair
  lost LID and group participant metadata, causing contact misses and invalid
  reaction keys.
- Consequence: name lookup covers the complete local index, phone searches do
  not collide with group JIDs, group operations fail closed when participant
  data is incomplete, and generic raw-key reactions are rejected. External
  mutation occurs only after visual approval and a real bridge acknowledgement.
- Evidence: PN/LID store regressions, reaction-key tests, router contract tests
  and a read-only live preview against the connected bridge on 2026-08-08.

## OJ-JARVIS-D19 - Optional context never gates a Live voice session

- Decision: a Gemini Live session requires only its ephemeral token. Codex
  history and operational events are bounded, cancellable enrichment and fall
  back to local memory when unavailable.
- Reason: coupling token creation to a full 316 KB conversation read and log
  query made optional context capable of exhausting the entire 30-second
  startup deadline.
- Consequence: the voice channel can start while context is degraded; full
  reads for the same Codex thread are coalesced behind one shielded request and
  a short cache. Blocking connector, source and log I/O executes outside the
  asynchronous server loop, and browser polling cannot overlap indefinitely.
- Evidence: startup fallback tests, concurrent history-reader tests, runtime
  load probe with responsive health checks, and César's visual confirmation on
  2026-08-08.

## OJ-JARVIS-D20 - A connected WhatsApp session does not expose a QR

- Decision: the Sources interface displays a QR only in `QR_REQUIRED`. In
  `CONNECTED`, it explicitly reports that the existing session is authenticated
  and no QR is necessary.
- Reason: generating a fresh QR for an already connected account would require
  logout/reset, disrupt a valid session and create misleading authentication
  state.
- Consequence: QR absence while `send_available=true` is healthy behavior. A
  new pairing remains an explicit recovery/account-change operation and cannot
  happen as a side effect of opening Sources.
- Evidence: connected-state presentation regression, live status with
  `send_available=true`, no bridge error and no active QR on 2026-08-08.

## OJ-JARVIS-D21 - The server catalog is the only executable Jarvis authority

- Decision: tool identity, schema, effect, provider, capability, timeout and
  availability are defined once in the server-side Jarvis Agent registry. The
  Gemini manifest and frontend presentation are derived from that registry.
- Reason: fixed Gemini functions, frontend regex routing and connector metadata
  had diverged and could route a request to the wrong executor.
- Consequence: a tool cannot exist only in the frontend; `mcp_tools()` and the
  general `/v1/tools` inventory remain metadata, not Jarvis execution authority.
  Source changes invalidate stale capabilities explicitly.
- Evidence: 32-tool catalog, generated OpenAPI/TypeScript contracts, catalog
  parity tests and removal of the legacy frontend catalog/router.

## OJ-JARVIS-D22 - Source, provider and executor are separate identities

- Decision: Gmail and WhatsApp are logical Sources; IMAP/OAuth and
  Baileys/Meta/Export are providers; Codex is an external executor. Capability
  checks occur at proposal and dispatch time.
- Reason: treating connector names as interchangeable caused IMAP/ OAuth and
  Meta/Export divergence and made a source keyword override an explicit Codex
  destination.
- Consequence: OAuth writes are hidden when disconnected, IMAP remains bounded
  read-only, Meta is unavailable, Export is historical ingestion only, and no
  Source silently falls back to Codex.
- Evidence: canonical provider snapshot, adapter matrix and policy tests.

## OJ-JARVIS-D23 - Approval is immutable, visual and single use

- Decision: every external mutation and Codex delegation is represented by an
  immutable proposal with a deterministic payload hash. Only one matching
  visual decision may authorize it within five minutes.
- Reason: spoken confirmations and repeated Gemini function calls previously
  replaced or duplicated the original requested command.
- Consequence: approval binds session, action, function call and hash; changing
  any field creates a new proposal. A second click or duplicate function call
  returns existing state and cannot dispatch twice.
- Evidence: live denial smoke, missing-header/wrong-hash rejection and
  idempotency/approval tests.

## OJ-JARVIS-D24 - Durable context is structured, bounded and stored on D:

- Decision: Jarvis persists only bounded objectives, decisions, pending action
  metadata, result summaries and opaque references for 30 days, partitioned by
  project and Codex thread. Audio, credentials, QR, full provider bodies and
  long-lived complete transcripts are excluded.
- Reason: continuity between sessions is required, but replaying private raw
  conversation creates privacy, prompt-injection and context-budget risk.
- Consequence: optional context never blocks Live startup; provider content is
  untrusted data; explicit context deletion does not delete external history.
  Active managed state lives under `D:\dev\runtime\openjarvis\state`; the C:
  source remains a preserved rollback.
- Evidence: context security/TTL tests, migration hashes and SQLite integrity
  checks.

## OJ-JARVIS-D25 - Long Codex work completes as a canonical asynchronous job

- Decision: a visually approved Codex delegation returns an accepted `job_id`
  synchronously and completes later through canonical job/action events and
  bounded context.
- Reason: Gemini Live function responses are synchronous while Codex tasks can
  exceed a Live callback deadline or finish after the voice session closes.
- Consequence: closing voice does not lose an already-started job; the next
  session can recover its result. Busy fails immediately, timeouts are distinct,
  and uncertain outcomes are never retried automatically.
- Evidence: job lifecycle, close/recovery, busy and timeout tests plus real
  read-only Codex smokes.

## OJ-JARVIS-D26 - Codex live events are primary; history is bounded reconciliation

- Decision: selected-conversation SSE registers its event listener first and
  rejoins the Desktop task with official `thread/resume` plus
  `excludeTurns=true`. Public live events are the primary path. History uses
  paginated `thread/turns/list` summary pages plus one `full` read restricted to
  the newest turn; `thread/read includeTurns=true` is prohibited for sync.
- Reason: the transport could remain connected while monolithic reads of a long
  active task timed out. Summary pages alone also omit steering messages inside
  an in-progress turn, so a restarted backend could not reconstruct current
  Chat state.
- Consequence: live messages arrive before reconciliation; concurrent consumers
  share bounded reads; the newest full turn restores missed steering input; and
  a late snapshot is overlaid with canonical live item IDs before emission.
  Reasoning, command execution and commentary never enter public Chat history.
- Evidence: installed app-server schema audit, direct 31-41 ms lightweight
  rejoin, real SSE `live` in 745 ms, 192-message snapshot in 8.96 seconds with
  both active-turn steering messages, 140 Python tests + 4 subtests and 88
  frontend tests on 2026-08-09. Functional commit:
  `d720d5fc096970d9b1a25556656d8c091f0b5824`.

## OJ-JARVIS-D27 - Gemini receives a protocol-specific Schema projection

- Decision: canonical input schemas remain strict JSON Schema in the backend;
  the Gemini Live boundary emits only fields supported by its protobuf
  `Schema` contract and converts primitive type names to protocol enums.
- Reason: forwarding `additionalProperties` caused the real Live socket to
  close with code 1007 and `Invalid JSON` before a voice session could start.
- Consequence: Gemini proposes against a compatible manifest while the backend
  still rejects unknown or invalid payload fields. The projection is covered
  by a manifest regression and a real `setupComplete` smoke.
- Evidence: 12-tool real Gemini Live setup on 2026-08-09.

## OJ-JARVIS-D28 - Transport selection follows tunnel capability

- Decision: loopback and transports known to carry streaming retain canonical
  SSE. Cloudflare Quick Tunnel hosts use finite cursor-based polling for Jarvis
  events and Codex history, with at most five bounded initial history pages.
- Reason: `trycloudflare.com` buffered the first SSE snapshot and never
  delivered later snapshots or heartbeats, although backend and gateway SSE
  were healthy.
- Consequence: Quick Tunnel is no longer an implicit streaming dependency.
  Polling preserves event cursors, idempotency and recent-to-older pagination;
  it does not create a second orchestrator.
- Evidence: external two-page reconciliation returned 376 unique messages.

## OJ-JARVIS-D29 - The launcher owns the local proxy contract

- Decision: the audited launcher explicitly sets the Vite API origin to the
  selected OpenJarvis backend port; direct `npm run dev` falls back to 8127.
- Reason: Vite silently used port 8000 while the local architecture assigned
  8127, producing HTTP 500 for every proxied Chat/Jarvis API request.
- Consequence: changing `BackendPort` in the launcher also changes the frontend
  proxy. Health verification must test APIs through port 5173, not only 8127.
- Evidence: proxied health, Live status and Agent catalog all returned HTTP 200.

## OJ-JARVIS-D30 - Session generations must be exact browser integers

- Decision: new Agent session generations use epoch microseconds and must remain
  within `Number.MAX_SAFE_INTEGER`; the opaque `session_id` is primary identity.
- Reason: epoch nanoseconds were rounded by browser JSON parsing and valid close
  callbacks failed generation validation.
- Consequence: stale callbacks remain rejectable without making valid browser
  callbacks nondeterministic.
- Evidence: exact-in-JavaScript regression and real create/close smoke.

## OJ-JARVIS-D31 - Distribution is source-only and private state is reconnected

- Decision: the clean GitHub repository contains the complete executable source,
  locks, contracts, installers and operational documentation, but excludes all
  runtime state and provider identity.
- Reason: Gmail credentials, Gemini keys, Codex state, Baileys authentication,
  databases, messages, logs and QR Codes are machine/user secrets, not portable
  source artifacts.
- Consequence: a clean Windows installation reproduces capabilities and then
  reconnects each account locally. Publication uses a verified source snapshot
  with a short new history, preserving license, attribution and the audited base
  SHA without copying the development `.git`. Moving personal state requires a
  separate, encrypted, hashed and non-Git procedure.
- Evidence: `operations/FRESH-WINDOWS-INSTALL.md`, ignored private boundaries,
  `scripts/workspace/verify-clean-publication.ps1` and the parentless snapshot
  builder `scripts/workspace/create-clean-snapshot.ps1`.

## OJ-JARVIS-D32 - Remote test access terminates at a tracked authenticated gateway

- Decision: Cloudflare Quick Tunnel may expose only the loopback authenticated
  gateway on port 8140; it must never point directly at backend 8127 or frontend
  5173. Credentials remain in an ignored private file and the public URL/QR stay
  under the D: runtime.
- Reason: a source repository must reproduce the working tablet flow without
  publishing account material or trusting a machine-specific untracked proxy.
- Consequence: start/stop scripts verify owners, reject collisions, preserve logs
  and use the tracked `openjarvis.server.remote_access` package. Quick Tunnel
  remains test-only and uses bounded polling because the provider does not carry
  SSE.
- Evidence: gateway contract tests, PowerShell parser checks, non-mutating live
  preflight and the canonical fresh-install runbook.

## OJ-JARVIS-D33 - AceleraChat owns active e-mail and WhatsApp execution

- Decision: the active Jarvis orchestrator exposes logical `email` and
  `whatsapp` Sources only through the private AceleraChat contract. Direct
  Gmail/IMAP and Baileys implementations and state remain preserved but are not
  composed, announced to Gemini or offered as connection controls in Data
  Sources.
- Reason: AceleraChat is the system of engagement selected by Cesar and already
  owns channel identity, contacts, conversations, provider state and delivery.
  Parallel local providers would create split truth, duplicate sends and
  conflicting authentication.
- Consequence: the backend discovers one authorized inbox per channel, exposes
  only capabilities declared by that inbox and fails closed when selection or
  credentials are missing. There is no silent fallback to a direct connector.
- Evidence: canonical 16-tool catalog, adapter/capability tests and Data Sources
  filtering tests on 2026-08-18.

## OJ-JARVIS-D34 - Provider acceptance is not delivery

- Decision: AceleraChat mutations execute once with an action-derived
  idempotency key and transition to `ACCEPTED`. Only a signed provider event or
  read-only backfill may establish terminal delivery. Ambiguous failures become
  `UNKNOWN` and are never retried automatically.
- Reason: the AceleraChat contract explicitly defines asynchronous delivery and
  at-least-once, non-globally-ordered webhooks. Treating HTTP 201 as delivery or
  retrying a timeout could produce false status or duplicate external messages.
- Consequence: delivery/event IDs are durably deduplicated, resource sequences
  prevent rollback, gaps schedule bounded read-only reconciliation, and an
  event arriving before local acceptance is applied atomically afterward.
- Evidence: persistence race, duplicate, out-of-order, HMAC rotation and
  no-retry tests on 2026-08-18.

## OJ-JARVIS-D35 - Provider webhook authentication is independent of browser login

- Decision: only the exact AceleraChat webhook `POST` path may cross the remote
  gateway without browser Basic Auth. The backend requires a fresh timestamp,
  UUID delivery ID, bounded body, valid schema and current/previous HMAC before
  durable persistence.
- Reason: a server-to-server provider cannot complete an interactive browser
  login, while exposing neighboring API routes would weaken the gateway.
- Consequence: wrong methods and paths remain protected; rotating secrets can
  overlap without downtime; secrets never enter source, logs or browser state.
- Evidence: gateway exact-path tests and signed-webhook service tests on
  2026-08-18.

## OJ-JARVIS-D36 - The VPS Core is the sole authority and Edge is outbound-only

- Decision: the production Jarvis Agent Core owns every session, proposal,
  approval, action, job, catalog entry, context record and canonical event. A
  Windows Edge Worker initiates one authenticated WSS connection and only
  executes a job that the Core already approved and offered.
- Reason: publishing the local app-server or running a second local orchestrator
  would split authority, approval and idempotency. A persistent outbound worker
  reaches the computer without router changes or an inbound tunnel.
- Consequence: an offline worker causes immediate `DEVICE_OFFLINE`; the Core
  never stores an approved command for automatic execution after reconnection.
  Only an accepted attempt/result may be resumed and reconciled.
- Evidence: Edge protocol, registry, jobs, spool, offline/restart tests and
  generated schemas on 2026-08-18.

## OJ-JARVIS-D37 - Codex MCP uses filtered STDIO and authenticated local IPC

- Decision: Codex starts a thin MCP STDIO facade. The facade derives tools from
  the canonical catalog, removes every `codex.*` tool and communicates only
  with the persistent Edge Worker through an authenticated Windows named pipe.
  The worker owns a separate, allowlisted HTTPS credential for the Core.
- Reason: Codex must not delegate recursively, reach the legacy `ToolExecutor`,
  receive VPS credentials or control the lifecycle of the Edge Worker.
- Consequence: MCP exposes at most 13 eligible non-Codex tools; mutations still
  create an exact visual proposal in the Core. JSON-RPC tool notifications are
  not executed and stable request IDs produce stable function-call IDs.
- Evidence: MCP protocol/catalog tests and a real authenticated named-pipe round
  trip on Windows on 2026-08-18.

## OJ-JARVIS-D38 - Edge, MCP, provider, webhook and browser credentials are separate

- Decision: WSS device identity, Edge-to-Core relay Bearer, local named-pipe
  token, AceleraChat Bearer, webhook HMAC and browser authentication are
  independent secrets stored only in private runtime files.
- Reason: reusing credentials expands blast radius and makes revocation or
  rotation ambiguous.
- Consequence: Codex receives only the local pipe token; logs store at most
  short fingerprints. Device current/previous overlap has explicit expiry and
  revocation is not cleared by reconnecting.
- Evidence: fail-closed configuration, constant-time middleware authentication,
  rotation/revocation tests and source-only templates.

## OJ-JARVIS-D39 - The first VPS release starts mutation-disabled and single-process

- Decision: the Core container starts with external mutations disabled and one
  Uvicorn worker. It runs non-root, read-only, capability-free, resource-limited
  and bound to VPS loopback behind the existing OpenResty.
- Reason: read-only health, catalog, Edge, PWA, Gemini and webhook gates must be
  proven before enabling provider/Codex mutation. Live registries are
  process-local around durable SQLite, so horizontal replicas require a future
  shared coordination design.
- Consequence: a real image build/digest and OpenResty syntax/smoke remain
  mandatory release gates. `/mcp` is absent and unlisted routes return 404.
- Evidence: Docker/Compose/OpenResty artifacts and fail-closed artifact tests on
  2026-08-18; no deployment is claimed.

## OJ-JARVIS-D40 - Remote MCP remains a separate optional phase

- Decision: this release implements local MCP STDIO only. ChatGPT remote MCP
  over Streamable HTTP is not mounted or advertised.
- Reason: remote MCP needs its own identity, scopes, rate limiting, streaming
  lifecycle and workspace controls. Local Codex configuration cannot be reused
  by ChatGPT Web.
- Consequence: OpenResty denies `/mcp`; adding it requires a separate plan,
  threat model, authorization and acceptance gate.
- Evidence: release gateway allowlist, local MCP entry point and canonical Edge
  contract.
