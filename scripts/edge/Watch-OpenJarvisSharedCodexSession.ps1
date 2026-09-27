[CmdletBinding()]
param(
    [string]$Repository = 'F:\OpenJarvis',
    [int]$Port = 8131,
    [Parameter(Mandatory)][int]$ExpectedOwnerProcessId,
    [Parameter(Mandatory)][string]$ExpectedDesktopProcessIds,
    [string]$ExpectedDesktopExecutablePath,
    [int]$PollMilliseconds = 500,
    [int]$DesktopExitStableSeconds = 3,
    [string]$StatePathOverride,
    [string]$LogPathOverride
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
$statePath = if ($StatePathOverride) {
    [System.IO.Path]::GetFullPath($StatePathOverride)
}
else { $config.StatePath }
$logPath = if ($LogPathOverride) {
    [System.IO.Path]::GetFullPath($LogPathOverride)
}
else { Join-Path $config.LogDirectory 'shared-session-guardian.log' }
foreach ($artifactPath in @($statePath, $logPath)) {
    if (-not $artifactPath.StartsWith(
        'F:\', [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Guardian artifacts must remain on disk F: $artifactPath"
    }
}
$desktopProcessIds = @(
    $ExpectedDesktopProcessIds.Split(',') |
        ForEach-Object {
            $parsed = 0
            if (-not [int]::TryParse($_, [ref]$parsed) -or $parsed -lt 1) {
                throw 'Expected Desktop process IDs are invalid.'
            }
            $parsed
        } |
        Select-Object -Unique
)
if ($desktopProcessIds.Count -lt 1) {
    throw 'At least one expected Desktop process ID is required.'
}
$expectedDesktopPath = if ($ExpectedDesktopExecutablePath) {
    [System.IO.Path]::GetFullPath($ExpectedDesktopExecutablePath)
}
else { $config.DesktopExe }


function Get-TrackedDesktopProcesses {
    @(
        Get-Process -Id $desktopProcessIds -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Path -and $_.Path.Equals(
                    $expectedDesktopPath,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
    )
}


function Get-ReplacementDesktopProcesses {
    @(
        Get-Process -Name ChatGPT -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Path -and $_.Path.Equals(
                    $expectedDesktopPath,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -and $_.MainWindowHandle -ne 0
            }
    )
}


function Write-GuardianEvent {
    param([Parameter(Mandatory)][string]$Event)

    $line = '{0} event={1} owner_pid={2}' -f `
        [DateTime]::UtcNow.ToString('o'), $Event, $ExpectedOwnerProcessId
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}


function Remove-MatchingState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ([int]$state.process_id -eq $ExpectedOwnerProcessId) {
            Remove-Item -LiteralPath $statePath -Force
        }
    }
    catch {
        Write-GuardianEvent -Event 'state_cleanup_failed'
    }
}


[System.IO.Directory]::CreateDirectory(
    [System.IO.Path]::GetDirectoryName($logPath)
) | Out-Null
$owner = Get-OpenJarvisSharedCodexOwner -Config $config
if ($null -eq $owner -or -not $owner.Valid -or
    $owner.ProcessId -ne $ExpectedOwnerProcessId) {
    Write-GuardianEvent -Event 'owner_preflight_rejected'
    exit 2
}
$expectedDesktopProcesses = @(
    Get-Process -Id $desktopProcessIds -ErrorAction SilentlyContinue
)
$trackedDesktop = @(Get-TrackedDesktopProcesses)
if ($trackedDesktop.Count -lt 1) {
    $rejectionEvent = if ($expectedDesktopProcesses.Count -lt 1) {
        'desktop_preflight_pid_rejected'
    }
    else { 'desktop_preflight_path_rejected' }
    Write-GuardianEvent -Event $rejectionEvent
    exit 2
}

Write-GuardianEvent -Event 'guardian_started'
$desktopGoneSince = $null
while ($true) {
    $owner = Get-OpenJarvisSharedCodexOwner -Config $config
    if ($null -eq $owner) {
        Remove-MatchingState
        Write-GuardianEvent -Event 'owner_already_stopped'
        exit 0
    }
    if (-not $owner.Valid -or $owner.ProcessId -ne $ExpectedOwnerProcessId) {
        Write-GuardianEvent -Event 'owner_identity_changed'
        exit 3
    }

    $trackedDesktop = @(Get-TrackedDesktopProcesses)
    if ($trackedDesktop.Count -gt 0) {
        $desktopGoneSince = $null
    }
    else {
        $topology = Get-OpenJarvisDesktopCodexTopology -Config $config
        if ($topology.SharedConnected -and $topology.PrivateAppServerCount -eq 0) {
            $replacementDesktop = @(Get-ReplacementDesktopProcesses)
            if ($replacementDesktop.Count -gt 0) {
                $desktopProcessIds = @(
                    $replacementDesktop | Select-Object -ExpandProperty Id
                )
                Write-GuardianEvent -Event 'desktop_processes_reacquired'
                $desktopGoneSince = $null
                continue
            }
        }
        if ($null -eq $desktopGoneSince) {
            $desktopGoneSince = [DateTime]::UtcNow
        }
        elseif (([DateTime]::UtcNow - $desktopGoneSince).TotalSeconds -ge `
            $DesktopExitStableSeconds) {
            if ($topology.DesktopRunning -and
                $topology.PrivateAppServerCount -gt 0 -and
                -not $topology.SharedConnected) {
                Stop-OpenJarvisSharedCodexOwner -Config $config `
                    -AllowUnsharedDesktopRecovery `
                    -ExpectedProcessId $ExpectedOwnerProcessId -Confirm:$false
            }
            elseif (-not $topology.DesktopRunning) {
                Stop-OpenJarvisSharedCodexOwner -Config $config `
                    -ExpectedProcessId $ExpectedOwnerProcessId -Confirm:$false
            }
            else {
                Stop-OpenJarvisSharedCodexOwner -Config $config `
                    -AllowDetachedDesktopRecovery `
                    -ExpectedProcessId $ExpectedOwnerProcessId -Confirm:$false
            }
            Remove-MatchingState
            Write-GuardianEvent -Event 'desktop_exit_released_owner'
            exit 0
        }
    }
    Start-Sleep -Milliseconds $PollMilliseconds
}
