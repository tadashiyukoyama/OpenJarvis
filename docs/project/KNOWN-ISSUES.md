# Known issues

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-18 13:20:52 -03:00
Working tree base: `4b2b16ab6ffce6f100180cfa40780f8296690515`
Branch: `codex/vps-edge-mcp`

## Acceptance status

The AceleraChat adapter implementation and automated gates are local. Live
acceptance is still open because the AceleraChat side was reported as not yet
deployed/configured for this OpenJarvis instance, and no private token, webhook
secret, inbox IDs or public callback were changed in this task.

The earlier Gmail IMAP/Baileys visual acceptance is historical evidence for the
preserved direct providers. Those providers are now intentionally inactive in
Jarvis and do not prove the AceleraChat boundary.

Current external prerequisites for live acceptance:

1. deploy/enable contract version `2026-08-19.2` on AceleraChat;
2. configure the ignored local private environment without exposing values;
3. configure the HTTPS callback ending in
   `/v1/jarvis/agent/providers/acelerachat/webhooks`;
4. verify the authorized e-mail and WhatsApp inbox IDs;
5. run read-only smokes, then obtain separate target-specific authorization for
   any real message/e-mail mutation.

The Edge/MCP implementation is also local-only. Before it can be called
installable or production-ready, the release still needs:

1. a clean final commit/SHA and publication authorization;
2. a real Docker build from that SHA and immutable image digest;
3. Compose rendering and container non-root/health proof;
4. authorized DNS, TLS and isolated OpenResty configuration with syntax check;
5. independent private Edge, relay, webhook, browser and provider credentials;
6. authorized Windows Scheduled Task installation and real outbound WSS smoke;
7. PWA desktop/tablet, SSE/poll, Gemini token and nested approval visual proof;
8. read-only AceleraChat/Codex integration smokes with mutations disabled.

## Proven platform/environment limitations

1. Codex Desktop and OpenJarvis are separate app-server clients. Canonical final
   messages synchronize, but token-by-token cross-process Desktop mirroring is
   not guaranteed. While a long Desktop task is active, full history may be
   temporarily `degraded`; the SSE stays connected and catches up after the
   canonical read becomes available.
2. The complete upstream test suite is not all-green in this Windows environment
   because optional native Rust, Gemma/Ollama, user skills and `polars` are
   absent, and some upstream tests exhibit Windows path/permission and SQLite
   teardown-lock behavior. Directed product gates are green; no dependency or
   model was installed to mask the upstream evidence.
3. The Vite production build reports existing bundle-size/dynamic-import
   warnings. The build passes; this is a future performance optimization.
4. The general connector registry remains broader than the Jarvis catalog.
   Connectors outside e-mail, WhatsApp and Codex are not executable Jarvis tools
   merely because `/v1/tools` or `mcp_tools()` lists metadata.
5. AceleraChat contract `2026-08-19.2` supports Evolution WhatsApp text,
   provider-native contextual reply, reaction, provider read receipt and media
   fetched from a public HTTPS URL. It does not expose group/profile/status,
   broadcast, calls, privacy administration or direct local-file transfer; nor
   e-mail archive, trash, new composition or attachment upload. Unsupported
   capabilities must not be advertised.
6. Vite still contains dormant direct-provider components and libraries for
   preservation/rollback. They are not imported by the active Data Sources page;
   removal requires a separate provenance and compatibility decision.
7. Docker and OpenResty executables are not available in the current Windows
   session. Their artifacts have policy tests, but no container build,
   `docker compose config` or `openresty -t` result is claimed.
8. The remote release allowlist supports `/jarvis` and Codex catalog/history.
   Generic OpenJarvis Chat submission through `/v1/chat/completions` remains
   intentionally unexposed; adding it requires a separate authenticated policy
   contract rather than widening the gateway casually.
9. The MCP Core relay currently uses a second outbound HTTPS request path from
   the persistent worker in addition to its Edge WSS connection. Local Codex
   still talks only through the authenticated named pipe. Consolidating relay
   RPC onto WSS is optional future optimization, not a correctness requirement.

## Preserved local items

The untracked `.manus-audit/`, root `node_modules/` and
`frontend/pnpm-lock.yaml` remain outside the implementation commits pending
separate provenance/cleanup authorization. They were not deleted or overwritten.

## External infrastructure

The gateway/tunnel was not started, stopped or replaced in this task. The tracked
gateway now permits only the exact signed AceleraChat webhook POST without
browser authentication; backend HMAC remains mandatory.

Cloudflare Quick Tunnels remain a test facility: the URL is random, there is no
SLA, and SSE is unsupported. The remote UI relies on bounded reconciliation;
stable production access requires a separately designed named tunnel and access
policy. VPS and production deployment remain outside the current scope.

A clean source installation reproduces capabilities, not personal state.
AceleraChat, Gemini and Codex must be configured/authenticated on each machine.
Private state transfer, if ever authorized, requires an encrypted non-Git
procedure.
