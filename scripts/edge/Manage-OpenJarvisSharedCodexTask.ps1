[CmdletBinding()]
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Uninstall')]
    [string]$Action = 'Status',
    [string]$TaskName = 'OpenJarvis Shared Codex',
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [int]$Port = 8131
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
$launcher = Join-Path $Repository 'scripts\edge\Start-OpenJarvisSharedCodex.ps1'
$windowsPowerShell = Join-Path $env:SystemRoot `
    'System32\WindowsPowerShell\v1.0\powershell.exe'
$environmentBackup = Join-Path `
    $config.StateDirectory 'shared-codex-user-environment.backup.json'


function Save-OpenJarvisUserEnvironmentBackup {
    if (Test-Path -LiteralPath $environmentBackup -PathType Leaf) { return }
    [System.IO.Directory]::CreateDirectory($config.StateDirectory) | Out-Null
    $appServer = [Environment]::GetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', 'User'
    )
    $codexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'User')
    $backup = [ordered]@{
        schema_version = 1
        codex_app_server_ws_url = [ordered]@{
            existed = $null -ne $appServer
            value = $appServer
        }
        codex_home = [ordered]@{
            existed = $null -ne $codexHome
            value = $codexHome
        }
    }
    $backup | ConvertTo-Json -Depth 4 | Set-Content `
        -LiteralPath $environmentBackup -Encoding UTF8
}


function Restore-OpenJarvisUserEnvironment {
    if (-not (Test-Path -LiteralPath $environmentBackup -PathType Leaf)) { return }
    $backup = Get-Content -LiteralPath $environmentBackup -Raw | ConvertFrom-Json
    $variables = @(
        @('CODEX_APP_SERVER_WS_URL', $backup.codex_app_server_ws_url),
        @('CODEX_HOME', $backup.codex_home)
    )
    foreach ($entry in $variables) {
        $name = [string]$entry[0]
        $saved = $entry[1]
        $value = if ([bool]$saved.existed) { [string]$saved.value } else { $null }
        [Environment]::SetEnvironmentVariable($name, $value, 'User')
    }
    Remove-Item -LiteralPath $environmentBackup -Force
}


function Stop-OpenJarvisSharedCodexProcess {
    $owner = Get-OpenJarvisSharedCodexOwner -Config $config
    if ($null -eq $owner) { return }
    if (-not $owner.Valid) {
        throw "Port $Port is owned by an unexpected process; nothing was stopped."
    }
    Stop-Process -Id $owner.ProcessId -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ((Get-OpenJarvisSharedCodexOwner -Config $config) -and `
        [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Get-OpenJarvisSharedCodexOwner -Config $config) {
        throw 'Shared Codex app-server did not stop.'
    }
}


switch ($Action) {
    'Install' {
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            throw 'Shared Codex launcher was not found.'
        }
        Save-OpenJarvisUserEnvironmentBackup
        [Environment]::SetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', $config.SharedUrl, 'User'
        )
        [Environment]::SetEnvironmentVariable(
            'CODEX_HOME', $config.CodexHome, 'User'
        )
        $taskAction = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument (
            '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden ' +
            '-ExecutionPolicy Bypass ' +
            "-File `"$launcher`" -Repository `"$Repository`" -Port $Port"
        )
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
            -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction `
            -Trigger $trigger -Principal $principal -Settings $settings -Force |
            Out-Null
        [pscustomobject]@{
            TaskName = $TaskName
            SharedUrl = $config.SharedUrl
            CodexHome = $config.CodexHome
            Status = 'INSTALLED'
        }
    }
    'Start' {
        $owner = Get-OpenJarvisSharedCodexOwner -Config $config
        if ($null -ne $owner) {
            if (-not $owner.Valid) {
                throw "Port $Port is owned by an unexpected process."
            }
        }
        else {
            Start-ScheduledTask -TaskName $TaskName
            Wait-OpenJarvisSharedCodexHealth -Config $config
        }
        [pscustomobject]@{
            TaskName = $TaskName
            SharedUrl = $config.SharedUrl
            Status = 'RUNNING'
        }
    }
    'Stop' {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Stop-OpenJarvisSharedCodexProcess
    }
    'Status' {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        $owner = Get-OpenJarvisSharedCodexOwner -Config $config
        $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
        [pscustomobject]@{
            TaskName = $TaskName
            TaskState = if ($null -eq $task) { 'NOT_INSTALLED' } else { $task.State }
            SharedHealthy = Test-OpenJarvisSharedCodexHealth -Config $config
            SharedOwnerValid = $null -ne $owner -and $owner.Valid
            DesktopRunning = $topology.DesktopRunning
            DesktopShared = $topology.SharedConnected
            PrivateAppServerCount = $topology.PrivateAppServerCount
            UserAppServerUrl = [Environment]::GetEnvironmentVariable(
                'CODEX_APP_SERVER_WS_URL', 'User'
            )
        }
    }
    'Uninstall' {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Stop-OpenJarvisSharedCodexProcess
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false `
            -ErrorAction SilentlyContinue
        Restore-OpenJarvisUserEnvironment
    }
}
