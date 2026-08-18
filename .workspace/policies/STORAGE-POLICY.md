# Storage policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

All project-managed paths for this workstation must remain on disk D. The
concrete values are local configuration, not portable policy. Read them from
`.workspace/local/project.local.json` using these keys:

- `workspaceRoot`
- `worktreesRoot`
- `runtimeRoot`
- `cacheRoot`
- `modelsRoot`
- `artifactsRoot`
- `toolchainsRoot`
- `codexHome`

The project root environment variable is `OPENJARVIS_WORKSPACE_ROOT`.
Windows and third-party tools may create small unrelated files elsewhere;
detect and document those files rather than promising that they cannot exist.
Do not alter global `TEMP` or `TMP` without explicit authorization.
