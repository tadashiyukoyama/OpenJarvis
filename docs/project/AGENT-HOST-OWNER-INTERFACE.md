# OpenJarvis ↔ Agent Host owner interface

Status: CANONICAL FOR THIS INTEGRATION SLICE
Owner: Cesar Yukoyama / Codex

## Boundary

The Agent Host in `F:\agente` owns the Codex `native_agent` session, queue,
state, policy, budgets, recovery and operational approval. OpenJarvis owns the
owner-facing UI and voice/text transport. OpenJarvis never interprets a
message as an operational approval and never selects a tool on this path.

The local bridge is loopback-only by default:

```text
owner UI -> OpenJarvis /v1/agent-host -> HMAC envelope -> Agent Host :8765
         <- status/history/events/approval ---------------------------
```

Every request carries `X-Agent-Principal: owner`, a timestamp and an HMAC made
from method, path and body hash. The shared secret is supplied through
`AGENT_HOST_SHARED_SECRET` in both processes and is never committed, logged or
placed in UI state. Message/control/approval commands also carry an
`idempotency_key`; the Host deduplicates retries before queueing a second
command. A keyless OpenJarvis process is accepted only on loopback;
remote binding still requires the existing API-key middleware.

## Host lifecycle

`apps/agent_hub/service.py` serializes HostStore/AgentHost access on its worker
thread. `POST /v1/agent-host/messages` persists the owner message, wakes the
existing run and returns an idempotent acceptance. The Host writes the Codex
response to `conversation_events` with the same run and conversation IDs.
`GET /status`, `/history` and `/events` are read-only projections; the UI polls
them at one-second intervals so a restart can reload durable history.

`pause`, `continue` and `stop` are mechanical budget/lifecycle controls. They
do not ask the Codex to make a decision and they do not create a second run.
`POST /approvals/test` creates a safe visual approval request; the decision is
forwarded to the Host and has no external effect. Every owner message carries
an opaque `correlation_id`, `event_id`, `dedupe_key`, `conversation_id` and
`run_id` in the Host history; the Codex response reuses the correlation.

The Host currently constructs Platform V1.1 with `allowed_effects=("read",)`
and `execution_mode="read_only"`. Physical phone, WhatsApp, SMS, payment and
deploy effects therefore remain blocked. The existing `/jarvis-legacy` route
is retained as fallback, while `/jarvis` is the owner interface for this
boundary.

## Voice

The application opens on the owner-facing Gemini Live voice page (`/jarvis`); the
Codex project/chat workspace remains available at `/chat`. Gemini
handles audio/VAD/transcription and may propose a typed request, but it never
authorizes or executes an external action. The resulting request goes to the
same Host conversation, where Codex remains the cognitive authority and Policy
controls every tool/effect. The legacy voice route remains available only as a
compatibility fallback.

## Startup

Set a random shared secret of at least 32 characters in the environment of
both processes, then start the Host and OpenJarvis server separately. Do not
put the value in Git, command history or a report. The Host command is:

```powershell
$env:PYTHONPATH = 'F:\agente'
& 'F:\OpenJarvis\.venv\Scripts\python.exe' -m apps.agent_hub serve --root F:\agente --port 8765
```

OpenJarvis uses `OPENJARVIS_AGENT_HOST_URL` (default
`http://127.0.0.1:8765`) and the same `AGENT_HOST_SHARED_SECRET`. Open the
existing `/jarvis` route after the server is running. Start its transport-only
server with the explicit `agent-host` mode; this mode does not create a second
inference agent:

```powershell
$env:OPENJARVIS_AGENT_HOST_URL = 'http://127.0.0.1:8765'
$env:AGENT_HOST_SHARED_SECRET = '<same local secret>'
& 'F:\OpenJarvis\.venv\Scripts\python.exe' -m openjarvis.cli serve --agent agent-host --host 127.0.0.1 --port 8127
```

`AGENT_HOST_SHARED_SECRET` is the single canonical source for both the
outbound gateway signature and the OpenJarvis channel callback signature. It
must be provisioned by the common service launcher and inherited unchanged by
both processes. A restart must reuse that provisioned value; OpenJarvis does
not generate a replacement, fall back to the WhatsApp identity secret, or
persist the value in the repository. If the variable is absent, the callback
fails closed as `AGENT_HOST_AUTH_UNCONFIGURED` rather than sending an
unauthenticated request.

For an interactive operator run under an account that cannot write the
commissioned `F:\agente\data` directory, set `AGENT_HOST_DATABASE` to a
temporary database under `F:\agente\runtime` for that run. The commissioned
service should use the canonical data path and does not need this override.

This document does not authorize WhatsApp, physical phone calls, SMS,
deployment or any other external effect.

## Gemini Live and Evolution API transport

The owner-facing home page uses the existing Gemini Live transport for voice.
The two backend credentials remain `GEMINI_LIVE_API_KEY_PRIMARY` and
`GEMINI_LIVE_API_KEY_FALLBACK`; they are provisioned outside the repository and
the browser receives only a short-lived token. Gemini understands the request,
but the Agent Host remains the only cognitive and policy authority.

WhatsApp transport is an explicit provider choice. The optional Evolution API
integration uses the loopback-only `OPENJARVIS_EVOLUTION_API_URL`, a server-side
`OPENJARVIS_EVOLUTION_API_KEY`, and `OPENJARVIS_EVOLUTION_INSTANCE_NAME`.
The Integrations page exposes status and QR for the configured instance. It only
offers explicit instance creation when `OPENJARVIS_EVOLUTION_PROVISIONING_ENABLED=1`;
it never creates an instance merely by loading the page. Inbound Evolution webhooks must carry the
separate `OPENJARVIS_EVOLUTION_WEBHOOK_SECRET`; OpenJarvis forwards only opaque
conversation/principal references to the Agent Host. Outbound text/media still
requires the Agent Host WhatsApp policy, idempotency and external-effect gate.
Baileys remains source-compatible legacy code and is not selected by this
provider path.

## WhatsApp Inbox and human intervention

The owner UI exposes `/whatsapp` as a WhatsApp-like inbox. It reads summaries
and message history from the authenticated Agent Host bridge; the browser
receives only opaque `wa:<sha256-reference>` conversation IDs and never sees a
provider JID, phone number or API credential. A conversation is created by an
authenticated Evolution webhook (or the compatible legacy channel ingress) and
is persisted in the Host `conversation_events` store.

The composer has two explicit modes:

- **Orientar agente** sends an owner message to that conversation. Codex remains
  responsible for deciding whether any tool or reply is appropriate.
- **Responder como você** requires a visible confirmation and calls the same
  configured WhatsApp gateway used by the Agent tools. The Host reserves a
  durable `whatsapp.operator.reply` idempotency key before the provider call,
  records the operator event and never retries an unknown result automatically.

The manual mode is therefore an intervention surface, not a second provider or
an authorization bypass. The gateway, destination policy and external-effect
flag still decide whether a physical send is permitted.
