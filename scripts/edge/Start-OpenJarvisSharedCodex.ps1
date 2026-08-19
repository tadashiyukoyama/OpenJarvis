[CmdletBinding()]
param(
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [int]$Port = 8131,
    [ValidateSet('untrusted', 'on-request', 'never')]
    [string]$ApprovalPolicy = 'never',
    [ValidateSet('read-only', 'workspace-write', 'danger-full-access')]
    [string]$SandboxMode = 'danger-full-access',
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
if ($ValidateOnly) {
    [pscustomobject]@{
        Repository = $config.Repository
        CodexHome = $config.CodexHome
        SharedUrl = $config.SharedUrl
        CodexExe = $config.CodexExe
        Status = 'VALIDATED'
    }
    return
}

[System.IO.Directory]::CreateDirectory($config.LogDirectory) | Out-Null
[System.IO.Directory]::CreateDirectory($config.StateDirectory) | Out-Null
$owner = Get-OpenJarvisSharedCodexOwner -Config $config
if ($null -ne $owner) {
    if (-not $owner.Valid) {
        throw "Port $Port is owned by an unexpected process; nothing was stopped."
    }
    Write-Output "shared_codex=already_running pid=$($owner.ProcessId)"
    return
}

$previousCodexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
[Environment]::SetEnvironmentVariable('CODEX_HOME', $config.CodexHome, 'Process')
Set-Location -LiteralPath $config.Repository
$stdoutLog = Join-Path $config.LogDirectory 'shared-app-server.stdout.log'
$stderrLog = Join-Path $config.LogDirectory 'shared-app-server.stderr.log'
$arguments = @(
    '-a', $ApprovalPolicy,
    '-s', $SandboxMode,
    'app-server', '--listen', $config.SharedUrl
)
try {
    & $config.CodexExe @arguments 1>> $stdoutLog 2>> $stderrLog
    exit $LASTEXITCODE
}
finally {
    [Environment]::SetEnvironmentVariable(
        'CODEX_HOME', $previousCodexHome, 'Process'
    )
}
