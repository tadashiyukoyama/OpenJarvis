[CmdletBinding()]
param(
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [string]$TaskName = 'OpenJarvis Shared Codex',
    [int]$Port = 8131,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
if ($ValidateOnly) {
    $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
    [pscustomobject]@{
        SharedUrl = $config.SharedUrl
        DesktopRunning = $topology.DesktopRunning
        SharedConnected = $topology.SharedConnected
        PrivateAppServerCount = $topology.PrivateAppServerCount
        Status = 'VALIDATED'
    }
    return
}

if (-not (Test-OpenJarvisSharedCodexHealth -Config $config)) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($task.State -ne 'Running') {
        Start-ScheduledTask -TaskName $TaskName
    }
    Wait-OpenJarvisSharedCodexHealth -Config $config
}

$topology = Get-OpenJarvisDesktopCodexTopology -Config $config
if ($topology.DesktopRunning) {
    if ($topology.SharedConnected -and $topology.PrivateAppServerCount -eq 0) {
        Write-Output 'codex_desktop=already_shared'
        return
    }
    throw (
        'Codex Desktop is already open with a private app-server. Close it ' +
        'normally and use the OpenJarvis Codex shortcut again.'
    )
}

$previousCodexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
$previousAppServer = [Environment]::GetEnvironmentVariable(
    'CODEX_APP_SERVER_WS_URL', 'Process'
)
try {
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $config.CodexHome, 'Process')
    [Environment]::SetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', $config.SharedUrl, 'Process'
    )
    Start-Process -FilePath $config.DesktopExe `
        -WorkingDirectory $config.Repository | Out-Null
}
finally {
    [Environment]::SetEnvironmentVariable(
        'CODEX_HOME', $previousCodexHome, 'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', $previousAppServer, 'Process'
    )
}

$joined = Wait-OpenJarvisDesktopSharedConnection -Config $config
[pscustomobject]@{
    SharedUrl = $config.SharedUrl
    DesktopProcessCount = $joined.DesktopProcessCount
    SharedConnected = $joined.SharedConnected
    PrivateAppServerCount = $joined.PrivateAppServerCount
    Status = 'RUNNING_SHARED'
}
