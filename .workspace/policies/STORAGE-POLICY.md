# Storage policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-09-13
Applies to SHA: codex/local-f-relocation
Supersedes: none
Superseded by: none

All project-managed paths for this workstation must remain below `F:\OpenJarvis`.
The
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
