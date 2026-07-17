# Storage policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: unknown
Supersedes: none
Superseded by: none

Project workspace: D:\dev\workspaces\openjarvis
External worktrees: D:\dev\worktrees\openjarvis
Runtime: D:\dev\runtime\openjarvis
Caches: D:\dev\caches\openjarvis
Models: D:\dev\models\openjarvis
Large artifacts: D:\dev\artifacts\openjarvis
Shared toolchains: D:\dev\toolchains
CODEX_HOME: D:\dev\codex-home\.codex

Only project-managed files are required to remain on D. Windows and
third-party tools may create small unrelated files elsewhere; this must be
detected and documented rather than promised away. Do not change global TEMP
or TMP in OJ0.

In OJ0 the only project environment variable is
OPENJARVIS_WORKSPACE_ROOT.
