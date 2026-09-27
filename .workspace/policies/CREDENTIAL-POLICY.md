# Credential policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-09-13
Applies to SHA: codex/local-f-relocation
Supersedes: none
Superseded by: none

`credenciais`, `.private`, `.runtime`, `.artifacts` and `.workspace/local` are
never versioned. The workstation uses the plain local directory
`F:\OpenJarvis\credenciais` by operator choice; no additional ACL hardening is
claimed by this policy. Locating a credential does not authorize reading or
using it. Never print, upload or include secret values in documentation or
logs. Deployment, when separately authorized, uses platform-managed secrets;
this policy does not authorize opening or importing credentials.
