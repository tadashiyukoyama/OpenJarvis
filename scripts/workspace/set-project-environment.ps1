[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$WorkspaceRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathValue {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$expectedRoot = Normalize-PathValue (Join-Path $scriptDirectory '..\..')
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = $expectedRoot
}
$resolvedRoot = Normalize-PathValue $WorkspaceRoot
if ($resolvedRoot -ne $expectedRoot) {
    throw "Wrong workspace: expected $expectedRoot but received $resolvedRoot."
}
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    throw "Workspace does not exist: $resolvedRoot"
}

$portablePath = Join-Path $resolvedRoot '.workspace\project.portable.json'
if (-not (Test-Path -LiteralPath $portablePath -PathType Leaf)) {
    throw "Portable identity is missing: $portablePath"
}

if ($PSCmdlet.ShouldProcess('User environment', 'Set OPENJARVIS_WORKSPACE_ROOT only')) {
    [Environment]::SetEnvironmentVariable(
        'OPENJARVIS_WORKSPACE_ROOT',
        $resolvedRoot,
        [EnvironmentVariableTarget]::User
    )
    $env:OPENJARVIS_WORKSPACE_ROOT = $resolvedRoot
}

[pscustomobject]@{
    Variable = 'OPENJARVIS_WORKSPACE_ROOT'
    UserValue = [Environment]::GetEnvironmentVariable(
        'OPENJARVIS_WORKSPACE_ROOT',
        [EnvironmentVariableTarget]::User
    )
    WorkspaceRoot = $resolvedRoot
    OtherVariablesChanged = $false
} | ConvertTo-Json -Depth 3
