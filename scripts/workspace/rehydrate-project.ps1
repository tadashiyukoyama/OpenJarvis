[CmdletBinding()]
param(
    [string]$PortablePath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathValue {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$expectedRoot = Normalize-PathValue (Join-Path $scriptDirectory '..\..')
$environmentRoot = $env:OPENJARVIS_WORKSPACE_ROOT
if ([string]::IsNullOrWhiteSpace($environmentRoot)) {
    $workspaceRoot = $expectedRoot
} else {
    $workspaceRoot = Normalize-PathValue $environmentRoot
}
if ($workspaceRoot -ne $expectedRoot) {
    throw "Wrong workspace: expected $expectedRoot but resolved $workspaceRoot."
}
if (-not (Test-Path -LiteralPath $workspaceRoot -PathType Container)) {
    throw "Workspace does not exist: $workspaceRoot"
}

if ([string]::IsNullOrWhiteSpace($PortablePath)) {
    $portablePath = Join-Path $workspaceRoot '.workspace\project.portable.json'
} else {
    $portablePath = Normalize-PathValue $PortablePath
    $rootPrefix = $workspaceRoot + '\'
    if (-not $portablePath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Portable identity override must remain inside the workspace."
    }
}
if (-not (Test-Path -LiteralPath $portablePath -PathType Leaf)) {
    throw "Portable identity is missing: $portablePath"
}

$portable = Get-Content -LiteralPath $portablePath -Raw | ConvertFrom-Json
if ($portable.projectId -ne 'OPENJARVIS_CESAR') {
    throw "Safe failure: unexpected projectId in portable identity."
}
if ($portable.workspaceEnvironmentVariable -ne 'OPENJARVIS_WORKSPACE_ROOT') {
    throw "Portable identity has an unexpected environment variable."
}

$requiredFiles = @(
    'AGENTS.md',
    '.workspace\README.md',
    'docs\project\DOCUMENT-INDEX.md',
    'docs\project\CURRENT-PROJECT-STATE.md',
    'scripts\workspace\project-status.ps1',
    'scripts\workspace\disk-guard.ps1'
)
$missing = @(
    $requiredFiles | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $workspaceRoot $_) -PathType Leaf)
    }
)
if ($missing.Count -gt 0) {
    throw "Foundation is incomplete. Missing: $($missing -join ', ')"
}

$localPath = Join-Path $workspaceRoot '.workspace\local\project.local.json'
$localState = 'NOT_PRESENT'
if (Test-Path -LiteralPath $localPath -PathType Leaf) {
    $null = Get-Content -LiteralPath $localPath -Raw | ConvertFrom-Json
    $localState = 'PRESENT'
}

[pscustomobject]@{
    workspaceRoot = $workspaceRoot
    portableIdentity = 'VALID'
    localConfiguration = $localState
    gitRootCanonical = if (Test-Path -LiteralPath (Join-Path $workspaceRoot '.git')) { 'PRESENT' } else { 'NOT_ESTABLISHED' }
    cloneOrDownloadPerformed = $false
    installationPerformed = $false
    worktreesCreated = 0
} | ConvertTo-Json -Depth 4
