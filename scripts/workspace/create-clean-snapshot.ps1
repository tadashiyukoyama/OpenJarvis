[CmdletBinding()]
param(
    [string]$SnapshotBranch = 'codex/distribution-snapshot',
    [switch]$Create,
    [switch]$ReplaceExistingSnapshot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $Output = & $script:GitExe -C $script:WorkspaceRoot @Arguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "git $($Arguments -join ' ') exited with code $ExitCode"
    }
    return @($Output)
}

if ($SnapshotBranch -notmatch '^codex/[A-Za-z0-9._/-]+$') {
    throw 'Snapshot branch must use the codex/ prefix and safe Git characters.'
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if (-not $WorkspaceRoot.StartsWith('F:\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Snapshot creation must run from the managed F: workspace: $WorkspaceRoot"
}
$GitExe = (Get-Command git.exe -ErrorAction Stop).Source
$GitOutput = & $GitExe -C $WorkspaceRoot rev-parse --show-toplevel
$GitExitCode = $LASTEXITCODE
if ($GitExitCode -ne 0 -or -not $GitOutput) {
    throw 'An audited existing Git repository is required.'
}
$GitRoot = [System.IO.Path]::GetFullPath([string]($GitOutput | Select-Object -First 1)).TrimEnd('\')
if ($GitRoot -ne $WorkspaceRoot) {
    throw "Unexpected Git root: $GitRoot"
}

$TrackedChanges = @(Invoke-Git -Arguments @(
    'status', '--porcelain', '--untracked-files=no'
))
if ($TrackedChanges.Count -gt 0) {
    throw 'Tracked changes must be committed before creating a distribution snapshot.'
}

$Verifier = Join-Path $WorkspaceRoot 'scripts\workspace\verify-clean-publication.ps1'
$VerifierOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Verifier
if ($LASTEXITCODE -ne 0) {
    throw 'The clean-publication verifier blocked snapshot creation.'
}
$VerifierResult = ($VerifierOutput -join "`n") | ConvertFrom-Json
if ($VerifierResult.status -ne 'PASS') {
    throw 'The clean-publication verifier did not return PASS.'
}

$ExistingRef = & $GitExe -C $WorkspaceRoot show-ref --hash --verify "refs/heads/$SnapshotBranch"
if ($LASTEXITCODE -eq 0) {
    $ExistingRef = [string]($ExistingRef | Select-Object -First 1)
    if (-not $ReplaceExistingSnapshot) {
        throw "Snapshot branch already exists and was not modified: $SnapshotBranch"
    }
    $ExistingParentRecord = Invoke-Git -Arguments @(
        'rev-list', '--parents', '-n', '1', $ExistingRef
    ) | Select-Object -First 1
    if (@($ExistingParentRecord -split ' ').Count -ne 1) {
        throw 'Existing snapshot branch is not parentless and was not modified.'
    }
}
if ($LASTEXITCODE -ne 1) {
    if (-not $ExistingRef) {
        throw 'Could not audit the requested snapshot ref.'
    }
}

$SourceBranch = Invoke-Git -Arguments @('branch', '--show-current') |
    Select-Object -First 1
$SourceSha = Invoke-Git -Arguments @('rev-parse', 'HEAD') |
    Select-Object -First 1
$SourceTree = Invoke-Git -Arguments @('rev-parse', 'HEAD^{tree}') |
    Select-Object -First 1

if (-not $Create) {
    [pscustomobject]@{
        status = 'READY'
        sourceBranch = $SourceBranch
        sourceSha = $SourceSha
        sourceTree = $SourceTree
        snapshotBranch = $SnapshotBranch
        existingSnapshotSha = $ExistingRef
        actionTaken = 'NONE'
        githubChanged = $false
    } | ConvertTo-Json -Depth 4
    return
}

$SnapshotSha = & $GitExe -C $WorkspaceRoot commit-tree $SourceTree `
    -m 'OpenJarvis Codex + Gemini clean distribution snapshot' `
    -m "Source-Commit: $SourceSha" `
    -m 'Upstream: https://github.com/open-jarvis/OpenJarvis'
$SnapshotExitCode = $LASTEXITCODE
if ($SnapshotExitCode -ne 0 -or -not $SnapshotSha) {
    throw 'Could not create the root snapshot commit.'
}
if ($ExistingRef) {
    & $GitExe -C $WorkspaceRoot update-ref `
        "refs/heads/$SnapshotBranch" $SnapshotSha $ExistingRef
}
else {
    & $GitExe -C $WorkspaceRoot update-ref "refs/heads/$SnapshotBranch" $SnapshotSha
}
if ($LASTEXITCODE -ne 0) {
    throw 'Could not create the local snapshot branch.'
}

$SnapshotTree = Invoke-Git -Arguments @('rev-parse', "$SnapshotSha^{tree}") |
    Select-Object -First 1
$ParentRecord = Invoke-Git -Arguments @('rev-list', '--parents', '-n', '1', $SnapshotSha) |
    Select-Object -First 1
if ($SnapshotTree -ne $SourceTree -or @($ParentRecord -split ' ').Count -ne 1) {
    throw 'Snapshot verification failed; the local ref was preserved for audit.'
}

[pscustomobject]@{
    status = 'CREATED'
    sourceBranch = $SourceBranch
    sourceSha = $SourceSha
    sourceTree = $SourceTree
    snapshotBranch = $SnapshotBranch
    snapshotSha = $SnapshotSha
    snapshotTree = $SnapshotTree
    parentCount = 0
    githubChanged = $false
} | ConvertTo-Json -Depth 4
