# Shared Codex runtime for OpenJarvis

## Required outcome

OpenJarvis and Codex Desktop must append to and observe the same persisted Codex
thread. The Windows computer therefore runs one shared Codex app-server and two
clients:

```text
Codex Desktop ──┐
                ├── ws://127.0.0.1:8131 ── one Codex app-server
Edge Worker ────┘
```

A private app-server child under Codex Desktop while the Edge Worker uses port
8131 is a split-brain topology. It causes `thread/resume` to fail with an active
writer conflict and must not be treated as normal thread activity.

The official app-server contract describes the server as the interface for rich
clients, including conversation history, approvals and streamed events. It also
defines `thread/resume` as the operation that reopens a stored thread so later
`turn/start` calls append to it. See:

<https://developers.openai.com/codex/app-server>

## Tracked components

- `SharedCodexRuntime.psm1`: strict topology and health inspection.
- `Start-OpenJarvisSharedCodex.ps1`: foreground app-server process used by Task
  Scheduler; hidden by the task action.
- `Manage-OpenJarvisSharedCodexTask.ps1`: reversible task and user-environment
  installation.
- `Start-OpenJarvisCodexDesktop.ps1`: starts Desktop only after the shared server
  is healthy and refuses to replace an already-running private topology.
- `start-openjarvis-codex.cmd`: shortcut entrypoint.

No script kills Codex Desktop. The operator closes it normally before changing
topology so the current rollout is persisted.

## Install

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action Install
```

Installation:

1. saves the previous user values of `CODEX_HOME` and
   `CODEX_APP_SERVER_WS_URL` under the managed D: runtime;
2. points future Desktop processes to `ws://127.0.0.1:8131`;
3. registers `OpenJarvis Shared Codex` at user logon with hidden execution,
   restart-on-failure and no time limit;
4. does not close or restart the currently running Desktop.

The existing `OpenJarvis Edge Worker` task remains independent. It reconnects
to the shared server if the server starts after the worker.

## Controlled cutover

1. Finish the current Codex response.
2. Close Codex Desktop normally.
3. Stop any old shared app-server only through the manager after verifying its
   exact packaged executable and listen URL.
4. Start `OpenJarvis Shared Codex`.
5. Open Codex through the tracked OpenJarvis shortcut.
6. Verify the same thread is visible in Desktop and OpenJarvis before allowing
   a delegation.

Do not start a second app-server to work around a busy result.

## Verification

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action Status
```

Required state:

- `SharedHealthy = true`;
- `SharedOwnerValid = true`;
- `DesktopShared = true`;
- `PrivateAppServerCount = 0`;
- exactly one packaged `codex.exe ... app-server` process;
- Edge advertises `codex.status`, `codex.history`, `codex.catalog` and
  `codex.delegate`;
- selecting a thread loads public history in both clients;
- one separately authorized harmless turn appears in both clients with the same
  thread and turn IDs.

The final turn is not part of installation and requires explicit operator
authorization. Voice confirmation alone is not authority.

## Failure behavior

| Condition | Result |
|---|---|
| Desktop uses a private app-server | refuse launch/cutover and report topology |
| port 8131 has an unrelated owner | fail closed; do not stop the process |
| selected thread has a real active turn | `CODEX_BUSY`, without queue or retry |
| Edge starts before shared server | reconnect after the server becomes healthy |
| shared server is offline | no Codex delegation is accepted |

## Rollback

Close Codex Desktop normally, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\edge\Manage-OpenJarvisSharedCodexTask.ps1 -Action Uninstall
```

Uninstall stops only the verified shared process, removes the task and restores
the exact prior user environment from the D: backup. It does not delete Codex
threads, OpenJarvis state, credentials or logs.
