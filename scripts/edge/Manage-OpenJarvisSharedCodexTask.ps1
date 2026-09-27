[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Status', 'Validate', 'RemoveLegacy')]
    [string]$Action = 'Status',
    [string]$TaskName = 'OpenJarvis Shared Codex',
    [string]$Repository = 'F:\OpenJarvis',
    [int]$Port = 8131
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
$environmentBackup = Join-Path `
    $config.StateDirectory 'shared-codex-user-environment.backup.json'


function Restore-OpenJarvisLegacyUserEnvironment {
    [CmdletBinding(SupportsShouldProcess)]
    param()

    if (Test-Path -LiteralPath $environmentBackup -PathType Leaf) {
        $backup = Get-Content -LiteralPath $environmentBackup -Raw |
            ConvertFrom-Json
        $variables = @(
            @('CODEX_APP_SERVER_WS_URL', $backup.codex_app_server_ws_url),
            @('CODEX_HOME', $backup.codex_home)
        )
        foreach ($entry in $variables) {
            $name = [string]$entry[0]
            $saved = $entry[1]
            $value = if ([bool]$saved.existed) {
                [string]$saved.value
            }
            else { $null }
            if ($PSCmdlet.ShouldProcess($name, 'Restore legacy user environment')) {
                [Environment]::SetEnvironmentVariable($name, $value, 'User')
            }
        }
        if ($PSCmdlet.ShouldProcess(
            $environmentBackup, 'Remove consumed legacy backup'
        )) {
            Remove-Item -LiteralPath $environmentBackup -Force
        }
        return
    }

    $legacyRedirect = [Environment]::GetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', 'User'
    )
    if ($legacyRedirect -eq $config.SharedUrl -and $PSCmdlet.ShouldProcess(
        'CODEX_APP_SERVER_WS_URL', 'Remove known legacy user redirect'
    )) {
        [Environment]::SetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', $null, 'User'
        )
    }
}


function Get-OpenJarvisSharedCodexStatus {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $owner = Get-OpenJarvisSharedCodexOwner -Config $config
    $readiness = Get-OpenJarvisSharedCodexReadiness -Config $config
    $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
    $redirect = Get-OpenJarvisPersistentCodexRedirect
    [pscustomobject]@{
        TaskName = $TaskName
        LegacyTaskState = if ($null -eq $task) {
            'NOT_INSTALLED'
        }
        else { [string]$task.State }
        RuntimeId = $config.RuntimeId
        PackageVersion = $config.PackageVersion
        SharedOwnerManaged = $null -ne $owner -and $owner.Managed
        SharedOwnerCurrent = $null -ne $owner -and $owner.CurrentRuntime
        SharedReady = $readiness.Ready
        SharedHealthy = $readiness.Healthy
        ProtocolInitialized = $readiness.ProtocolInitialized
        DesktopRunning = $topology.DesktopRunning
        DesktopShared = $topology.SharedConnected
        PrivateAppServerCount = $topology.PrivateAppServerCount
        UserRedirect = $redirect.User
        MachineRedirect = $redirect.Machine
    }
}


switch ($Action) {
    'Status' { Get-OpenJarvisSharedCodexStatus }
    'Validate' {
        $status = Get-OpenJarvisSharedCodexStatus
        [pscustomobject]@{
            RuntimeResolved = $true
            PersistentRedirectAbsent = (
                $null -eq $status.UserRedirect -and
                $null -eq $status.MachineRedirect
            )
            LegacyTaskAbsent = $status.LegacyTaskState -eq 'NOT_INSTALLED'
            Status = 'VALIDATED_WITHOUT_MUTATION'
        }
    }
    'RemoveLegacy' {
        $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
        if ($topology.DesktopRunning) {
            throw 'Close Codex Desktop normally before removing legacy authority.'
        }
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -ne $task) {
            if ($PSCmdlet.ShouldProcess($TaskName, 'Stop legacy scheduled task')) {
                Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            }
        }
        Stop-OpenJarvisSharedCodexOwner -Config $config `
            -AllowStaleManagedRuntime -Confirm:$false
        if ($null -ne $task -and $PSCmdlet.ShouldProcess(
            $TaskName, 'Unregister legacy scheduled task'
        )) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }
        Restore-OpenJarvisLegacyUserEnvironment -Confirm:$false
        [pscustomobject]@{
            TaskName = $TaskName
            Status = 'LEGACY_AUTHORITY_REMOVED'
        }
    }
}
