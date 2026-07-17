[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathValue {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$expectedRoot = Normalize-PathValue (Join-Path $scriptDirectory '..\..')
$environmentRoot = $env:OPENJARVIS_WORKSPACE_ROOT
$workspaceRoot = if ([string]::IsNullOrWhiteSpace($environmentRoot)) {
    $expectedRoot
} else {
    Normalize-PathValue $environmentRoot
}
if ($workspaceRoot -ne $expectedRoot) {
    throw "Wrong workspace: expected $expectedRoot but resolved $workspaceRoot."
}

$gitRoot = 'NOT_ESTABLISHED'
$branch = 'unknown'
$gitStatus = 'NOT_PRESENT'
$gitDirectory = Join-Path $workspaceRoot '.git'
if (Test-Path -LiteralPath $gitDirectory) {
    $gitStatus = 'PRESENT'
    try {
        $gitTop = (& git -C $workspaceRoot rev-parse --show-toplevel 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $gitTop) {
            $gitRoot = Normalize-PathValue ([string]$gitTop)
        }
        $branchOutput = (& git -C $workspaceRoot branch --show-current 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $branchOutput) {
            $branch = ([string]$branchOutput).Trim()
        }
    } catch {
        $gitStatus = 'PRESENT_BUT_UNREADABLE'
    }
}

[pscustomobject]@{
    workspaceRoot = $workspaceRoot
    gitRoot = $gitRoot
    gitStatus = $gitStatus
    activeBranch = $branch
    officialCodeDownloaded = (Test-Path -LiteralPath $gitDirectory)
    additionalWorktrees = 0
} | ConvertTo-Json -Depth 4
