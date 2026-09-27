[CmdletBinding()]
param(
    [string]$Repository = 'F:\OpenJarvis',
    [int]$Port = 8131,
    [switch]$ValidateOnly,
    [switch]$NoNormalFallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force


function Start-CodexDesktopNormally {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$WorkingDirectory)

    $package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop |
        Sort-Object Version -Descending | Select-Object -First 1
    $desktopExe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    if (-not (Test-Path -LiteralPath $desktopExe -PathType Leaf)) {
        throw 'The normal Codex Desktop executable was not found.'
    }
    $previousRedirect = [Environment]::GetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', 'Process'
    )
    try {
        [Environment]::SetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', $null, 'Process'
        )
        Start-Process -FilePath $desktopExe `
            -WorkingDirectory $WorkingDirectory | Out-Null
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', $previousRedirect, 'Process'
        )
    }
}


function Complete-NormalFallback {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        $Config
    )

    if ($NoNormalFallback) { throw $Reason }
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $listener) {
        $ownerDescription = "PID $($listener.OwningProcess)"
        if ($null -ne $Config) {
            $owner = Get-OpenJarvisSharedCodexOwner -Config $Config
            if ($null -ne $owner) {
                $ownerDescription = if ($owner.Managed) {
                    'a managed shared Codex runtime'
                }
                else { "unrelated $ownerDescription" }
            }
        }
        throw (
            "$Reason Normal fallback was withheld because $ownerDescription " +
            "still owns port $Port."
        )
    }
    Start-CodexDesktopNormally -WorkingDirectory $WorkingDirectory
    [pscustomobject]@{
        SharedUrl = $null
        Reason = $Reason
        Status = 'NORMAL_CODEX_STARTED_WITHOUT_REDIRECT'
    }
}


try {
    $config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
}
catch {
    if ($ValidateOnly) { throw }
    Complete-NormalFallback -Reason $_.Exception.Message `
        -WorkingDirectory ([System.IO.Path]::GetFullPath($Repository))
    return
}
if ($ValidateOnly) {
    $redirect = Get-OpenJarvisPersistentCodexRedirect
    $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
    [pscustomobject]@{
        SharedUrl = $config.SharedUrl
        PackageVersion = $config.PackageVersion
        RuntimeId = $config.RuntimeId
        UserRedirect = $redirect.User
        MachineRedirect = $redirect.Machine
        DesktopRunning = $topology.DesktopRunning
        SharedConnected = $topology.SharedConnected
        PrivateAppServerCount = $topology.PrivateAppServerCount
        Status = 'VALIDATED_WITHOUT_START'
    }
    return
}

$topology = Get-OpenJarvisDesktopCodexTopology -Config $config
if ($topology.DesktopRunning) {
    if ($topology.SharedConnected -and $topology.PrivateAppServerCount -eq 0) {
        Write-Output 'codex_desktop=already_shared'
        return
    }
    throw (
        'Codex Desktop is already open in normal/private mode. Nothing was ' +
        'closed, redirected or restarted.'
    )
}

try {
    Assert-OpenJarvisNoPersistentCodexRedirect
}
catch {
    Complete-NormalFallback -Reason $_.Exception.Message `
        -WorkingDirectory $config.Repository
    return
}

$serverLauncher = Join-Path $PSScriptRoot 'Start-OpenJarvisSharedCodex.ps1'
$server = $null
try {
    $server = & $serverLauncher -Repository $config.Repository -Port $Port
    $readiness = Get-OpenJarvisSharedCodexReadiness -Config $config
    if (-not $readiness.Valid) {
        throw 'Shared Codex preflight did not remain valid before Desktop launch.'
    }
}
catch {
    if ($null -ne $server -and [bool]$server.Started) {
        Stop-OpenJarvisSharedCodexOwner -Config $config -Confirm:$false
    }
    Complete-NormalFallback -Reason $_.Exception.Message `
        -WorkingDirectory $config.Repository -Config $config
    return
}

$previous = [ordered]@{
    CODEX_HOME = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
    CODEX_APP_SERVER_WS_URL = [Environment]::GetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', 'Process'
    )
}
$desktopLaunch = $null
try {
    [Environment]::SetEnvironmentVariable(
        'CODEX_HOME', $config.CodexHome, 'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'CODEX_APP_SERVER_WS_URL', $config.SharedUrl, 'Process'
    )
    try {
        $desktopLaunch = Start-Process -FilePath $config.DesktopExe `
            -WorkingDirectory $config.Repository -PassThru
    }
    catch {
        if ([bool]$server.Started) {
            Stop-OpenJarvisSharedCodexOwner -Config $config -Confirm:$false
        }
        Complete-NormalFallback -Reason $_.Exception.Message `
            -WorkingDirectory $config.Repository -Config $config
        return
    }
}
finally {
    foreach ($entry in $previous.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable(
            $entry.Key, $entry.Value, 'Process'
        )
    }
}

try {
    $joined = Wait-OpenJarvisDesktopSharedConnection -Config $config
}
catch {
    $failedTopology = Get-OpenJarvisDesktopCodexTopology -Config $config
    if ([bool]$server.Started -and
        $failedTopology.DesktopRunning -and
        -not $failedTopology.SharedConnected -and
        $failedTopology.PrivateAppServerCount -gt 0) {
        Stop-OpenJarvisSharedCodexOwner -Config $config `
            -AllowUnsharedDesktopRecovery -Confirm:$false
        [pscustomobject]@{
            SharedUrl = $null
            Reason = $_.Exception.Message
            PrivateAppServerCount = $failedTopology.PrivateAppServerCount
            Status = 'NORMAL_CODEX_RECOVERED_AFTER_SHARED_JOIN_FAILURE'
        }
        return
    }
    if ([bool]$server.Started -and -not $failedTopology.DesktopRunning) {
        Stop-OpenJarvisSharedCodexOwner -Config $config -Confirm:$false
        Complete-NormalFallback -Reason $_.Exception.Message `
            -WorkingDirectory $config.Repository -Config $config
        return
    }
    throw
}
$owner = Get-OpenJarvisSharedCodexOwner -Config $config
if ($null -eq $owner -or -not $owner.Valid) {
    throw 'Shared Codex owner changed before lifecycle guardian startup.'
}
$guardianScript = Join-Path $PSScriptRoot 'Watch-OpenJarvisSharedCodexSession.ps1'
$guardianHost = (Get-Process -Id $PID).Path
$guardian = $null
$guardianLogPath = Join-Path $config.LogDirectory (
    'shared-session-guardian-{0}-{1}.log' -f `
        $owner.ProcessId, [guid]::NewGuid().ToString('N')
)
try {
    $desktopSessionProcesses = @(
        Get-Process -Name ChatGPT -ErrorAction Stop |
            Where-Object {
                $_.Path -and $_.Path.Equals(
                    $config.DesktopExe,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -and $_.MainWindowHandle -ne 0
            }
    )
    if ($desktopSessionProcesses.Count -lt 1 -and $null -ne $desktopLaunch -and
        -not $desktopLaunch.HasExited -and $desktopLaunch.Path.Equals(
            $config.DesktopExe, [System.StringComparison]::OrdinalIgnoreCase
        )) {
        $desktopSessionProcesses = @($desktopLaunch)
    }
    if ($desktopSessionProcesses.Count -lt 1) {
        throw 'Shared Desktop main process disappeared before guardian startup.'
    }
    $desktopProcessIds = @(
        $desktopSessionProcesses | Select-Object -ExpandProperty Id
    )
    $guardian = Start-Process -FilePath $guardianHost -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $guardianScript,
        '-Repository', $config.Repository,
        '-Port', [string]$Port,
        '-ExpectedOwnerProcessId', [string]$owner.ProcessId,
        '-ExpectedDesktopProcessIds', ($desktopProcessIds -join ','),
        '-LogPathOverride', $guardianLogPath
    ) -WindowStyle Hidden -PassThru

    $guardianReady = $false
    $guardianDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $guardianDeadline -and
        -not $guardian.HasExited) {
        if ((Test-Path -LiteralPath $guardianLogPath -PathType Leaf) -and
            (Select-String -LiteralPath $guardianLogPath `
                -SimpleMatch 'event=guardian_started' -Quiet)) {
            $guardianReady = $true
            break
        }
        Start-Sleep -Milliseconds 100
        $guardian.Refresh()
    }
    if (-not $guardianReady -or $guardian.HasExited) {
        throw 'Shared Codex lifecycle guardian did not become ready.'
    }

    if (Test-Path -LiteralPath $config.StatePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $config.StatePath -Raw |
            ConvertFrom-Json
        $state | Add-Member -NotePropertyName guardian_process_id `
            -NotePropertyValue $guardian.Id -Force
        $state | Add-Member -NotePropertyName guardian_log_path `
            -NotePropertyValue $guardianLogPath -Force
        $state | Add-Member -NotePropertyName desktop_process_count `
            -NotePropertyValue $joined.DesktopProcessCount -Force
        $state | ConvertTo-Json -Depth 4 | Set-Content `
            -LiteralPath $config.StatePath -Encoding UTF8
    }
    [pscustomobject]@{
        SharedUrl = $config.SharedUrl
        RuntimeId = $config.RuntimeId
        AppServerStarted = [bool]$server.Started
        DesktopProcessCount = $joined.DesktopProcessCount
        SharedConnected = $joined.SharedConnected
        PrivateAppServerCount = $joined.PrivateAppServerCount
        GuardianProcessId = $guardian.Id
        Status = 'RUNNING_SHARED_OPT_IN'
    }
}
catch {
    $startupError = $_
    if ($null -ne $guardian -and -not $guardian.HasExited) {
        Stop-Process -Id $guardian.Id -Force -ErrorAction SilentlyContinue
        $guardian.WaitForExit(5000) | Out-Null
    }
    $failedOwner = Get-OpenJarvisSharedCodexOwner -Config $config
    if ($null -ne $failedOwner -and $failedOwner.Valid -and
        $failedOwner.ProcessId -eq $owner.ProcessId) {
        Stop-OpenJarvisSharedCodexOwner -Config $config `
            -AllowDetachedDesktopRecovery `
            -ExpectedProcessId $owner.ProcessId -Confirm:$false
    }
    if (Test-Path -LiteralPath $config.StatePath -PathType Leaf) {
        try {
            $failedState = Get-Content -LiteralPath $config.StatePath -Raw |
                ConvertFrom-Json
            if ([int]$failedState.process_id -eq $owner.ProcessId) {
                Remove-Item -LiteralPath $config.StatePath -Force
            }
        }
        catch {
            # Preserve an unrecognized state file for operator inspection.
        }
    }
    throw $startupError
}
