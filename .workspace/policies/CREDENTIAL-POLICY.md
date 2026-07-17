# Credential policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

`.private`, `.runtime`, `.artifacts` and `.workspace/local` are never
versioned. Locating a credential does not authorize reading or using it.
Never print, copy, upload or document secrets. Deployment, when separately
authorized, uses platform-managed secrets; this policy does not authorize
opening or importing credentials.
