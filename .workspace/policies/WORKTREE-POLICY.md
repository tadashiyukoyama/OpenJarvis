# Worktree policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: unknown
Supersedes: none
Superseded by: none

There is one canonical clone and at most two additional simultaneous
worktrees for the whole project. Worktrees must be under
D:\dev\worktrees\openjarvis and never inside the Git root.

Use a worktree only for genuine parallel work, keeping main clean for an
audit, an urgent isolated fix, or a separate review. OJ0 creates none.
Every worktree must have a local ledger entry. Removal requires a clean
status, no untracked work to preserve, disposition of exclusive commits,
closed/merged/cancelled task, ledger update, git worktree remove, prune,
and filesystem confirmation.
