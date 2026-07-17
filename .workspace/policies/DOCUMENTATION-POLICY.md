# Documentation policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

The canonical project memory is only `docs/project`; its entry point is
`DOCUMENT-INDEX.md`. A canonical document must carry Status, Owner,
Last verified, Applies to SHA, Supersedes and Superseded by metadata.
Only CANONICAL documents are current decisions.

`Applies to SHA` means the upstream code baseline used for factual claims; it
is not the commit containing the document. The foundation baseline is
`3000116d181eb69737241c09eaa70d4c65eb80a0`. Do not replace it with the branch
HEAD merely because documentation changed.

Temporary audit and test reports belong under `.workspace/local/audit` or
`.artifacts/reports`. Do not duplicate upstream changelogs or create
parallel memories for the same subject.
