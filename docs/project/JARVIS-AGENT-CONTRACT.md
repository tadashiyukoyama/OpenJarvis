# Jarvis Agent contract

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-20
Applies to integrated code SHA: `6d5b964178f28319081b5ff057616a4979a5efba`
Branch: `codex/edge-live-relay-release`

## 1. Purpose

This document is the public contract for the server-side Jarvis Agent Core. It
defines how Gemini Live proposes typed work, how the backend validates and
authorizes that work, and how AceleraChat e-mail, AceleraChat WhatsApp and Codex
return canonical
results. Code and generated schemas remain the executable source of truth.

The contract has four non-negotiable boundaries:

1. Gemini understands and proposes; it does not authorize or execute.
2. The backend catalog and policy are authoritative.
3. Reads may run automatically; mutations and Codex delegations require one
   visual approval for the exact payload.
4. Provider content is untrusted data and cannot create another tool call by
   itself.

## 2. Canonical entities

| Entity | Identity and responsibility |
|---|---|
| `Session` | `session_id`, monotonically checked `generation`, project, Codex thread, manifest version and lifecycle |
| `Turn` | one committed final transcript; partials are transport-only |
| `ToolDefinition` | internal ID, Gemini alias, schema, Source, provider, capability, effect, timeout and policy |
| `ToolProposal` | immutable action, validated arguments, safe preview and SHA-256 payload hash |
| `Approval` | one visual decision bound to action, session, function call and payload hash |
| `Execution` | idempotent dispatch state and canonical result |
| `ExternalOperation` | accepted AceleraChat resource awaiting terminal webhook/backfill reconciliation |
| `Job` | asynchronous Codex work and terminal state |
| `ToolResult` | public status, safe summary, bounded data, opaque references and stable error |
| `ContextMemory` | bounded objective, decisions, pending actions, results and opaque references by project/thread |

Provider-native identifiers are never accepted from the model when an opaque
reference can be used. The backend resolves AceleraChat inbox, conversation,
contact and message IDs at dispatch time and never asks Gemini to invent them.

## 3. State machines

### Session

```text
OPENING -> ACTIVE -> CLOSING -> CLOSED
               \-> FAILED
```

- Closing invalidates the current generation before transport callbacks are
  drained.
- A callback with an old generation returns `LATE_CALLBACK` and cannot mutate
  state.
- A generation is an exact JSON/JavaScript integer no greater than
  `Number.MAX_SAFE_INTEGER`; `session_id` remains the primary identity.
- Closing cancels only proposals that have not started execution.

### Action

```text
PROPOSED
|- READ --------------------> DISPATCHING -> COMPLETED
`- MUTATION/DELEGATION ----> AWAITING_APPROVAL -> APPROVED
                                  |                 `-> DISPATCHING
                                  |                       |-> ACCEPTED -> COMPLETED
                                  |                       |             `-> FAILED
                                  |                       |-> COMPLETED
                                  |-> DENIED              |-> BUSY
                                  |-> EXPIRED             `-> UNKNOWN
                                  `-> CANCELLED

DISPATCHING -> FAILED | BUSY | UNKNOWN
```

Only one action may wait for approval in a session. Approval expires after five
minutes. `ACCEPTED` means the external provider accepted a mutation but has not
confirmed its terminal outcome. `UNKNOWN` is terminal and never retried
automatically.

### Job

```text
ACCEPTED -> RUNNING -> COMPLETED
                    |-> FAILED
                    |-> BUSY
                    `-> UNKNOWN
```

Gemini Live function calling receives a synchronous response. Long Codex work
therefore returns `accepted` and `job_id`; completion arrives through the event
stream and context memory.

## 4. HTTP API

Prefix: `/v1/jarvis/agent`

| Method and path | Purpose | Important rule |
|---|---|---|
| `GET /catalog` | current Sources, providers, tools and Live manifest | only available tools enter the manifest |
| `POST /sessions` | create one generation-bound session | returns manifest and bounded context |
| `POST /sessions/{id}/turns` | commit one final user turn | duplicate `turn_id` is idempotent; partial text is invalid |
| `POST /sessions/{id}/proposals` | validate one Gemini function call | read executes; write/delegation becomes pending |
| `POST /actions/{id}/decision` | approve or deny exact action | requires visual header and matching payload hash |
| `GET /actions/{id}` | read canonical action state | may expire stale approval before returning |
| `GET /jobs/{id}` | read asynchronous job state | never creates or retries work |
| `GET /events` | authenticated SSE of state changes | resumable by `Last-Event-ID` or `after` |
| `GET /events/poll` | finite page of state changes | same `after` cursor contract for transports without SSE |
| `GET /events/history` | durable operational history by project and Codex task | deterministic order; never dispatches or retries work |
| `POST /providers/acelerachat/webhooks` | receive signed provider events | HMAC, timestamp, UUID delivery, body limit, durable deduplication and sequence checks precede HTTP 202 |
| `POST /sessions/{id}/close` | close and invalidate generation | no late callback may reopen it |
| `GET /context` | read bounded project/thread memory | optional and non-blocking for Live startup |
| `DELETE /context` | explicit user deletion | does not delete external e-mail, WhatsApp or Codex history |

The generated OpenAPI contract is
`contracts/jarvis-agent.openapi.json`. Frontend contract types are generated in
`frontend/src/features/jarvis/api/generated-contracts.ts`. The exporter must
pass in check mode before commit.

### Function response envelope

Every Gemini function response uses the controlled envelope:

```json
{
  "result": {
    "status": "completed",
    "action_id": "opaque-action-id",
    "job_id": null
  }
}
```

The result also identifies `requested_tool_id`, whether an operation or
delegation was actually confirmed, and a `claim_boundary`. Gemini must not
describe a read-only status/history result as a delegation.

Canonical tool inputs are strict JSON Schema. Before a declaration enters the
Gemini Live setup, the client projects it onto the supported Gemini `Schema`
subset. Unsupported JSON Schema keywords are never sent to Live; this does not
relax backend validation.

The response is a tool result, never a new user utterance.

## 5. Catalog and capability rules

The implementation registers 24 typed tools. The Live manifest is a filtered
view generated for current provider state; it is not a fixed frontend list.

### Jarvis

| Internal ID | Gemini alias | Effect |
|---|---|---|
| `jarvis.operational_audit` | `jarvis_read_operational_audit` | read |

### All authorized AceleraChat inboxes

| Internal ID | Alias | Effect |
|---|---|---|
| `acelerachat.list_inboxes` | `acelerachat_list_inboxes` | read |
| `acelerachat.list_conversations` | `acelerachat_list_conversations` | read |
| `acelerachat.read_conversation` | `acelerachat_read_conversation` | read |
| `acelerachat.send_message` | `acelerachat_send_message` | mutation |

The inbox list is discovered dynamically from the account-scoped Bearer, so
future inboxes require no OpenJarvis redeploy. Disconnected inboxes are visible
for diagnosis but cannot execute. If multiple inboxes could perform an action,
the caller must select an exact ID or name; the adapter never guesses.

### AceleraChat e-mail

This Source represents customer-service e-mail conversations managed by
AceleraChat. It is not a generic Gmail/IMAP mailbox.

| Internal ID | Alias | Effect |
|---|---|---|
| `email.search` | `email_search_messages` | read |
| `email.list_unread` | `email_list_unread` | read |
| `email.read_message` | `email_read_message` | read |
| `email.read_conversation` | `email_read_conversation` | read |
| `email.reply` | `email_reply_conversation` | mutation |

Reply is available only for an existing AceleraChat conversation and requires
visual approval. Provider archive, trash, new-message composition and binary
attachment upload are not in contract and are never announced.

### AceleraChat WhatsApp

| Internal ID | Alias | Effect |
|---|---|---|
| `whatsapp.status` | `whatsapp_get_status` | read |
| `whatsapp.search_contacts` | `whatsapp_search_contacts` | read |
| `whatsapp.search_chats` | `whatsapp_search_chats` | read |
| `whatsapp.read_conversation` | `whatsapp_read_conversation` | read |
| `whatsapp.summarize_conversation` | `whatsapp_summarize_conversation` | read |
| `whatsapp.send_text` | `whatsapp_send_text` | mutation |
| `whatsapp.reply` | `whatsapp_reply_message` | mutation |
| `whatsapp.react` | `whatsapp_react_message` | mutation |
| `whatsapp.mark_read_provider` | `whatsapp_mark_provider_read` | mutation |
| `whatsapp.send_media` | `whatsapp_send_media` | mutation |
| `whatsapp.mark_read_internal` | `whatsapp_mark_acelerachat_read` | mutation |

Text and HTTPS media are sent only to one existing uniquely resolved conversation
or an exact E.164 number. Name ambiguity never dispatches. Contextual reply,
reaction and provider read receipt use Evolution through AceleraChat; the internal
read marker remains separate. Every mutation requires visual approval. Polls,
groups, profile/privacy administration, broadcast, calls and direct local-file
transfer are absent from this contract and must not be announced.

Direct Gmail/IMAP and Baileys implementations remain preserved but dormant.
They are not active providers, do not enter the Live manifest and are not shown
as connection controls in Data Sources. Account/provider administration belongs
to AceleraChat.

### Codex

| Internal ID | Alias | Effect |
|---|---|---|
| `codex.status` | `codex_get_status` | read |
| `codex.history` | `codex_read_recent_history` | read |
| `codex.delegate` | `codex_delegate_task` | delegation |

Codex is selected only when it is the explicit executor. A request to report a
WhatsApp failure to Codex uses Codex; a request to send a WhatsApp message uses
WhatsApp. There is no silent cross-executor fallback.

The committed final turn is authoritative for explicit executor intent. Natural
requests such as “entre em contato com o Codex”, “acione o Codex” or “quero que
o Codex faça” require `codex.delegate`. If Gemini proposes status, history or a
provider tool for that turn, the server returns `TOOL_INTENT_MISMATCH` before
creating an action or job.

## 6. Proposal, approval and idempotency

1. The client commits one final turn.
2. Gemini proposes one registered function call.
3. The server compares the proposed tool with deterministic intent derived from
   that committed turn.
4. The server resolves the tool, current capability and route; an executor
   mismatch is rejected without creating an action.
5. Arguments are validated and provider identifiers are resolved.
6. The server builds a safe preview and deterministic SHA-256 payload hash.
7. A read dispatches immediately.
8. A mutation/delegation enters `AWAITING_APPROVAL`.
9. The UI displays destination, project/thread, exact bounded payload and risk.
10. The visual decision sends the displayed hash.
11. The backend compares every binding before dispatch.

Idempotency key:

```text
session_id + function_call_id + payload_hash
```

A repeated call returns the original action/result, including after the
transcript body has been redacted: the server resolves the exact action by
session, function call and payload hash. A repeated button decision
cannot execute again. A spoken `sim` or `confirmo` is committed only as speech
and never changes approval state.

AceleraChat mutations use `Idempotency-Key: jarvis:{action_id}` and exactly one
HTTP attempt. A successful create response transitions the action to `ACCEPTED`,
not `COMPLETED`. Terminal message delivery comes from `message.updated` or a
read-only `/backfill` snapshot. Events are deduplicated by both delivery ID and
event ID, ordered by monotonic sequence per provider resource and durably linked
to the accepted action. If an event wins the race and arrives before local
acceptance, its outcome is retained and applied atomically when the operation is
registered. A timeout or ambiguous provider failure becomes `UNKNOWN`; there is
no silent retry.

## 7. Context and privacy

Context is partitioned by normalized project plus Codex thread and expires 30
days after last write. Each bounded list keeps at most 20 items; summaries are
limited to 2,000 characters.

Persisted:

- safe objective label;
- approval decisions;
- pending action metadata;
- bounded result summaries;
- opaque references;
- job/action lifecycle.

Not persisted as long-lived context:

- audio;
- complete transcript;
- API keys, cookies, passwords or tokens;
- WhatsApp QR;
- raw full email or chat bodies;
- provider-native IDs exposed to Gemini.

The final transcript may exist transiently while its proposal is formed. After
terminal handling it is redacted to hash/summary according to the store
lifecycle. Operational events carry safe IDs and metadata, not private payloads.
They are also retained in the separate durable operational event store and can
be reconciled by project and Codex task after a voice or browser reconnect.

AceleraChat e-mail and WhatsApp content is tagged untrusted. It may be
summarized or shown as data but cannot issue instructions, create approval or
invoke another tool.

## 8. Stable errors

| Code | Meaning |
|---|---|
| `MANIFEST_STALE` | provider/capability changed after session manifest |
| `TOOL_UNAVAILABLE` | registered tool cannot currently execute |
| `TOOL_INTENT_MISMATCH` | proposed executor conflicts with the committed user intent |
| `SOURCE_DISCONNECTED` | required live provider is disconnected |
| `INBOX_SELECTION_REQUIRED` | multiple operational inboxes require an exact selection |
| `CAPABILITY_NOT_AVAILABLE` | provider lacks the requested capability |
| `ACTION_PENDING` | session already has one visual decision pending |
| `APPROVAL_REQUIRED` | missing/nonvisual approval |
| `APPROVAL_EXPIRED` | five-minute approval window ended |
| `APPROVAL_PAYLOAD_MISMATCH` | displayed and submitted payload hashes differ |
| `DUPLICATE_ACTION` | duplicate that cannot be returned safely |
| `SESSION_CLOSED` | operation targets a closed session |
| `LATE_CALLBACK` | callback belongs to an invalidated generation |
| `CODEX_BUSY` | selected Codex thread is already active |
| `CODEX_THREAD_INVALID` | selected thread is missing or invalid |
| `CODEX_THREAD_RESUME_TIMEOUT` | bounded resume/read exceeded its deadline |
| `CODEX_DISPATCH_TIMEOUT` | dispatch deadline elapsed |
| `PROVIDER_CONFLICT` | provider reports a conflicting active session |
| `PROVIDER_LOGGED_OUT` | provider authentication was invalidated |
| `PROVIDER_AUTH_FAILED` | private AceleraChat bearer authentication failed |
| `PROVIDER_RATE_LIMITED` | provider rate limit was reached |
| `PROVIDER_RESPONSE_INVALID` | provider response violated its bounded contract |
| `PROVIDER_TIMEOUT` | a read-only provider request timed out |
| `PROVIDER_UNAVAILABLE` | provider cannot currently serve the request |
| `PROVIDER_DELIVERY_FAILED` | asynchronous provider delivery failed |
| `WEBHOOK_INVALID_SIGNATURE` | webhook HMAC or timestamp is invalid |
| `WEBHOOK_INVALID_PAYLOAD` | webhook headers/body/schema are invalid |
| `EXTERNAL_RESULT_UNKNOWN` | external outcome cannot be proved; no retry |

The API also uses stable not-found, invalid-request and internal-error codes.
Messages are sanitized and must not contain credentials or provider payloads.

## 9. Event contract

SSE events use a server-assigned monotonically increasing sequence. Relevant
event families include session changes, committed turns, proposals, approval
decisions, dispatch acceptance/completion/failure, provider reconciliation,
busy rejection, jobs, context and late callbacks. Reconnection resumes after
the last sequence and must not replay an execution.

AceleraChat webhooks accept the current signature or a separately configured
previous signature during rotation overlap. The signature input is exactly
`timestamp + "." + raw_body`, HMAC-SHA256. The exact webhook `POST` may bypass
browser Basic Auth at the remote gateway because the backend HMAC is its
authentication boundary; every other method/path still requires browser auth.
Gateway and backend both stop reading the request at 1 MiB. Provider HTTP
responses are also bounded during streaming rather than after full buffering.
Only the first valid transition from `ACCEPTED` to a terminal state emits the
canonical completion/failure event; duplicate or later terminal callbacks are
retained as audit evidence without replaying the transition.

The finite event endpoint returns `events` plus `next_after` and is semantically
equivalent to one bounded SSE replay page. A client may change transport, but
it must keep the same cursor and may not replay dispatch.

The durable history endpoint is read-only and scoped by normalized project plus
Codex task. Stable ordering and canonical IDs let the UI merge historical and
live events without duplicating commands or treating presentation replay as an
execution request.

Client telemetry is advisory and separate from canonical server events.

## 10. Acceptance invariants

- One fragmented utterance produces at most one committed turn.
- Explicit Codex delegation intent cannot execute a status/provider tool.
- No mutation or Codex delegation occurs without a matching visual click.
- A duplicate function call or button click executes at most once.
- Direct Gmail/IMAP and Baileys providers never enter the active manifest.
- AceleraChat advertises the union of live capabilities, then validates the
  exact selected inbox again before every execution.
- HTTP acceptance of an external message is never reported as delivery.
- Duplicate or out-of-order provider events cannot repeat or roll back an action.
- Codex busy fails immediately without queue or retry.
- Closing a session prevents late callbacks from changing state.
- Canonical results appear by action/job event and survive a voice-session end.
- No provider content can create a new action.
- Hacker News remains preserved but absent from the Jarvis manifest.
