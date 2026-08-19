# Shared Codex runtime for OpenJarvis

## Status and safety boundary

Shared mode is an explicit, opt-in Windows operating mode. It is not installed
at logon and it does not replace normal Codex Desktop startup. The tracked code
never writes `CODEX_APP_SERVER_WS_URL` at User or Machine scope. The variable is
set only in the launcher process long enough for the specifically launched
Desktop child to inherit it.

Normal Codex remains the recovery path. A failed shared-server preflight opens
Codex normally without the redirect unless the operator passed
`-NoNormalFallback`. The launcher never closes an existing Desktop process.

The Codex app-server documentation defines the server used by rich clients,
conversation history and `thread/resume`. It also marks WebSocket transport as
experimental and not supported for production deployments:

<https://developers.openai.com/codex/app-server>

This integration is therefore a controlled local compatibility mode, not a
production-supported OpenAI transport guarantee.

## Required topology

```text
Codex Desktop ──┐
                ├── ws://127.0.0.1:8131 ── one validated Codex app-server
Edge Worker ────┘
```

A private Desktop app-server plus a second listener for Edge is split brain.
Both processes can read the same files, but `thread/resume` may reject the
second writer. Never create another thread or retry a mutation to hide that
condition.

## Root cause of the retired launcher

The first launcher created three coupled failure modes:

1. it persisted `CODEX_APP_SERVER_WS_URL=ws://127.0.0.1:8131` for the Windows
   user, making normal Desktop startup depend on that listener;
2. its scheduled task attempted to execute `codex.exe` directly from the MSIX
   `WindowsApps` resources directory, which can return access denied outside
   the packaged process boundary;
3. owner validation accepted any installed `OpenAI.Codex` package path, so a
   stale runtime from an older Desktop version could be treated as current.

If the task then exited, Desktop inherited the global redirect and failed with
`ECONNREFUSED 127.0.0.1:8131`. Reinstalling Desktop could also invalidate the
old runtime path and authentication session.

## Version-pinned runtime resolution

`Resolve-OpenJarvisCodexRuntime` reads the current MSIX package and hashes both
packaged resources:

- `codex.exe`;
- `codex-code-mode-host.exe`.

It then resolves exactly one executable pair under
`%LOCALAPPDATA%\OpenAI\Codex\bin\<runtime-id>` whose two SHA-256 values match the
current package. Zero or multiple matches fail closed. The npm Codex CLI and an
older materialized runtime are never accepted as substitutes.

After a Desktop update, validate again. A changed package hash intentionally
invalidates the old listener. Stale cleanup is allowed only for a recognized
Codex runtime, the exact managed listen command and a closed Desktop.

## Preflight gates

Before Desktop receives a process-scoped redirect, all gates must pass:

1. no User/Machine `CODEX_APP_SERVER_WS_URL` exists;
2. Desktop is closed, or is already connected to the exact shared topology;
3. port 8131 is free or owned by the exact current materialized runtime;
4. `/readyz` returns success;
5. `/healthz` returns success;
6. a bounded WebSocket client completes JSON-RPC `initialize` and sends
   `initialized`;
7. after launch, Desktop has a connection to 8131 and no private app-server
   child.

An HTTP response alone cannot prove protocol compatibility. The initialize
probe is limited to one MiB and five seconds.

## Tracked components

- `SharedCodexProtocol.psm1`: bounded WebSocket initialize probe.
- `SharedCodexRuntime.psm1`: package/hash resolution, ownership, health and
  topology inspection.
- `Start-OpenJarvisSharedCodex.ps1`: starts only the validated materialized
  executable with `on-request` and `workspace-write` defaults.
- `Start-OpenJarvisCodexDesktop.ps1`: opt-in preflight, process-scoped redirect
  and normal-Codex fallback.
- `Manage-OpenJarvisSharedCodexTask.ps1`: read-only status/validation and
  explicit removal of the retired scheduled-task authority.
- `start-openjarvis-codex.cmd`: visible opt-in shortcut entrypoint.

There is no automatic shared-runtime task. The independent `OpenJarvis Edge
Worker` task may remain active and reconnect when a validated listener exists.

## Validation without activation

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Start-OpenJarvisSharedCodex.ps1 -ValidateOnly

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Start-OpenJarvisCodexDesktop.ps1 -ValidateOnly

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action Status
```

`-ValidateOnly` resolves and hashes the current runtime but does not open,
close, redirect or stop anything.

## Controlled opt-in cutover

1. Finish the current Codex response and confirm the task is persisted.
2. Close Codex Desktop normally.
3. Confirm port 8131 is free and legacy User/Machine redirects are absent.
4. Run the tracked `start-openjarvis-codex.cmd` explicitly.
5. Confirm `RUNNING_SHARED_OPT_IN` and the required topology below.
6. Verify history is visible from Desktop and OpenJarvis using read-only calls.
7. Perform one harmless same-task turn only under separate authorization.

Required state:

- `SharedOwnerManaged = true`;
- `SharedOwnerCurrent = true`;
- `SharedReady = true`;
- `SharedHealthy = true`;
- `ProtocolInitialized = true`;
- `DesktopShared = true`;
- `PrivateAppServerCount = 0`;
- User and Machine redirects are empty.

No message, e-mail, reaction, campaign or provider mutation belongs to this
cutover. Voice confirmation alone is not authority.

## Failure behavior

| Condition | Fail-safe result |
|---|---|
| current normal/private Desktop is open | report topology; close or restart nothing |
| materialized hashes do not match current package | refuse shared mode |
| port has an unrelated owner | refuse shared mode; stop nothing |
| stale recognized Codex owns the port | require explicit legacy cleanup |
| ready, health or initialize probe fails | remove only a newly started verified listener, then start normal Codex; withhold fallback if any listener remains |
| Desktop opens a private server instead of joining | stop only the newly started verified shared listener and preserve normal Desktop |
| Edge starts before shared server | remain offline/reconnecting without hidden job execution |

## One-time retirement of the old authority

Only after Codex Desktop is closed, inspect first:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action Status
```

Then remove only the known legacy task, verified managed listener and backed-up
user redirect:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action RemoveLegacy
```

`RemoveLegacy` refuses to run while Desktop is open and refuses unrelated port
owners. It never deletes threads, credentials, project state or Codex logs.

## Rollback

Close a shared Desktop normally. With Desktop closed, stop only the exact
current managed runtime through `Stop-OpenJarvisSharedCodexOwner`, then launch
Codex from its normal installed shortcut. Because there is no persistent
redirect, normal startup does not depend on port 8131.

Rolling source back restores code only. It does not require a database
migration and does not modify Codex task history.
