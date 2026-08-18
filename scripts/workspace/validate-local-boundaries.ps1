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

$localConfigPath = Join-Path $workspaceRoot '.workspace\local\project.local.json'
if (-not (Test-Path -LiteralPath $localConfigPath -PathType Leaf)) {
    throw "Local configuration is missing: $localConfigPath"
}
$config = Get-Content -LiteralPath $localConfigPath -Raw | ConvertFrom-Json
$configuredPaths = @(
    $config.workspaceRoot,
    $config.worktreesRoot,
    $config.runtimeRoot,
    $config.cacheRoot,
    $config.modelsRoot,
    $config.artifactsRoot,
    $config.toolchainsRoot,
    $config.codexHome
)
foreach ($configuredPath in $configuredPaths) {
    $normalized = Normalize-PathValue ([string]$configuredPath)
    if (-not $normalized.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Local boundary violation: $normalized is not on D:."
    }
}

$reparsePoints = @(
    Get-ChildItem -LiteralPath $workspaceRoot -Force -Recurse -ErrorAction Stop |
        Where-Object { [bool]($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }
)
if ($reparsePoints.Count -gt 0) {
    throw "Boundary validation refused reparse points under the workspace."
}

[pscustomobject]@{
    valid = $true
    workspaceRoot = $workspaceRoot
    configuredPathsOnD = $configuredPaths.Count
    reparsePoints = $reparsePoints.Count
    actionTaken = 'NONE'
} | ConvertTo-Json -Depth 4
