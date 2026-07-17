# Credential policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: unknown
Supersedes: none
Superseded by: none

.private, .runtime, .artifacts and .workspace/local are never versioned.
Locating a credential does not authorize reading or using it. Never print,
copy, upload or document secrets. OJ0 imports no credentials. Future
deployment uses platform-managed secrets.
