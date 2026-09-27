[CmdletBinding()]
param(
    [int]$Port = 18131,
    [string]$OpenJarvisRepository = 'F:\OpenJarvis',
    [switch]$KeepArtifacts,
    [switch]$CleanupArtifactsOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repository = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\..')
)
$validationRoot = 'F:\OpenJarvis\runtime\validation'
$validationPrefix = "$validationRoot\"


function Remove-ValidatedProtocolArtifact {
    param([Parameter(Mandatory)][string]$Path)

    $candidate = [System.IO.Path]::GetFullPath($Path)
    if (-not $candidate.StartsWith(
        $validationPrefix, [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to remove unsafe path: $candidate"
    }
    $cleanupError = $null
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            if ([System.IO.Directory]::Exists($candidate)) {
                $extendedPath = '\\?\' + $candidate
                foreach ($file in [System.IO.Directory]::EnumerateFiles(
                    $extendedPath,
                    '*',
                    [System.IO.SearchOption]::AllDirectories
                )) {
                    try {
                        [System.IO.File]::SetAttributes(
                            $file,
                            [System.IO.FileAttributes]::Normal
                        )
                    }
                    catch [System.IO.FileNotFoundException] {
                        # Cache files may disappear while enumeration is in progress.
                    }
                    catch [System.IO.DirectoryNotFoundException] {
                        # A concurrent cache cleanup can remove a parent directory.
                    }
                }
                [System.IO.Directory]::Delete($extendedPath, $true)
            }
            $cleanupError = $null
            break
        }
        catch [System.IO.DirectoryNotFoundException] {
            $cleanupError = $null
            break
        }
        catch {
            $cleanupError = $_
            Start-Sleep -Milliseconds (200 * $attempt)
        }
    }
    if ($null -ne $cleanupError -and [System.IO.Directory]::Exists($candidate)) {
        throw $cleanupError
    }
}


if ($CleanupArtifactsOnly) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen `
        -ErrorAction SilentlyContinue) {
        throw "Port $Port has a listener; refusing artifact cleanup."
    }
    $removed = 0
    Get-ChildItem -LiteralPath $validationRoot -Directory `
        -Filter 'shared-codex-protocol-*' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $candidate = [System.IO.Path]::GetFullPath($_.FullName)
            Remove-ValidatedProtocolArtifact -Path $candidate
            $removed++
        }
    [pscustomobject]@{
        Removed = $removed
        Status = 'ISOLATED_PROTOCOL_ARTIFACTS_CLEANED'
    }
    return
}
$probeRoot = Join-Path $validationRoot (
    'shared-codex-protocol-' + [Guid]::NewGuid().ToString('N')
)
if (-not $probeRoot.StartsWith(
    $validationPrefix, [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Unsafe temporary validation path: $probeRoot"
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen `
    -ErrorAction SilentlyContinue) {
    throw "Port $Port already has a listener."
}

New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
$probeCodexHome = Join-Path $probeRoot 'codex-home'
New-Item -ItemType Directory -Path $probeCodexHome -Force | Out-Null
Import-Module (
    Join-Path $repository 'scripts\edge\SharedCodexRuntime.psm1'
) -Force
Import-Module (
    Join-Path $repository 'scripts\edge\SharedCodexProtocol.psm1'
) -Force

$runtime = Resolve-OpenJarvisCodexRuntime
$config = Get-OpenJarvisSharedCodexConfig `
    -Repository $OpenJarvisRepository -Port $Port
$oldHome = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
$process = $null
$guardianProcess = $null
$rejectedGuardianProcess = $null
$desktopSentinel = $null
$result = $null
$managedStopValidated = $false
$guardianStopValidated = $false
$guardianIdentityRejected = $false
try {
    [Environment]::SetEnvironmentVariable(
        'CODEX_HOME', $probeCodexHome, 'Process'
    )
    $process = Start-Process -FilePath $runtime.CodexExe -ArgumentList @(
        '-a', 'on-request',
        '-s', 'workspace-write',
        'app-server', '--listen', "ws://127.0.0.1:$Port"
    ) -WorkingDirectory $repository `
        -RedirectStandardOutput (Join-Path $probeRoot 'stdout.log') `
        -RedirectStandardError (Join-Path $probeRoot 'stderr.log') `
        -WindowStyle Hidden -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $ready = $false
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $ready = (Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$Port/readyz" `
                -TimeoutSec 1).StatusCode -eq 200
        }
        catch { $ready = $false }
        try {
            $healthy = (Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:$Port/healthz" `
                -TimeoutSec 1).StatusCode -eq 200
        }
        catch { $healthy = $false }
        if ($ready -and $healthy) { break }
        Start-Sleep -Milliseconds 250
    }
    $readiness = Get-OpenJarvisSharedCodexReadiness -Config $config
    $protocol = $readiness.ProtocolInitialized
    if ($protocol -isnot [bool]) {
        throw "Protocol preflight returned $($protocol.GetType().FullName), not Boolean."
    }
    $ownerValid = $null -ne $readiness.Owner -and $readiness.Owner.Valid
    $mismatchConfig = $config | Select-Object *
    $mismatchConfig.CodexExe = Join-Path $validationRoot 'stale\codex.exe'
    $mismatchOwner = Get-OpenJarvisSharedCodexOwner -Config $mismatchConfig
    $staleRuntimeRejected = (
        $null -ne $mismatchOwner -and $mismatchOwner.Managed -and
        -not $mismatchOwner.CurrentRuntime -and -not $mismatchOwner.Valid
    )
    if (-not (
        $ready -and $healthy -and $protocol -and
        $ownerValid -and $staleRuntimeRejected
    )) {
        throw (
            "Isolated app-server failed: ready=$ready healthy=$healthy " +
            "protocol=$protocol owner_valid=$ownerValid"
        )
    }
    $result = [pscustomobject]@{
        Port = $Port
        PackageVersion = $runtime.PackageVersion
        RuntimeId = $runtime.RuntimeId
        Ready = $ready
        Healthy = $healthy
        ProtocolInitialized = $protocol
        ProtocolResultType = $protocol.GetType().FullName
        OwnerManaged = $readiness.Owner.Managed
        OwnerCurrent = $readiness.Owner.CurrentRuntime
        OwnerValid = $readiness.Owner.Valid
        StaleRuntimeRejected = $staleRuntimeRejected
        ClosedPortRejected = $false
        ManagedStopValidated = $false
        GuardianStopValidated = $false
        GuardianIdentityRejected = $false
        ThreadOrTurnSent = $false
        Status = 'ISOLATED_PROTOCOL_SMOKE_PASSED'
    }

    $desktopSentinel = Start-Process -FilePath (Get-Process -Id $PID).Path `
        -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 120') `
        -WindowStyle Hidden -PassThru
    $guardianState = Join-Path $probeRoot 'guardian-state.json'
    $guardianLog = Join-Path $probeRoot 'guardian.log'
    @{ process_id = $process.Id } | ConvertTo-Json | Set-Content `
        -LiteralPath $guardianState -Encoding UTF8
    $guardianScript = Join-Path `
        $repository 'scripts\edge\Watch-OpenJarvisSharedCodexSession.ps1'
    $rejectedGuardianProcess = Start-Process `
        -FilePath (Get-Process -Id $PID).Path -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $guardianScript,
            '-Repository', $OpenJarvisRepository,
            '-Port', [string]$Port,
            '-ExpectedOwnerProcessId', [string]$process.Id,
            '-ExpectedDesktopProcessIds', [string]$desktopSentinel.Id,
            '-ExpectedDesktopExecutablePath', 'D:\invalid\not-powershell.exe',
            '-StatePathOverride', $guardianState,
            '-LogPathOverride', (Join-Path $probeRoot 'guardian-rejected.log')
        ) -WindowStyle Hidden -PassThru
    $rejectedDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $rejectedDeadline -and
        -not $rejectedGuardianProcess.HasExited) {
        Start-Sleep -Milliseconds 100
        $rejectedGuardianProcess.Refresh()
    }
    $ownerAfterRejectedGuardian = Get-OpenJarvisSharedCodexOwner -Config $config
    if (-not $rejectedGuardianProcess.HasExited -or
        $rejectedGuardianProcess.ExitCode -ne 2 -or
        $null -eq $ownerAfterRejectedGuardian -or
        $ownerAfterRejectedGuardian.ProcessId -ne $process.Id) {
        throw 'Guardian path mismatch did not fail closed.'
    }
    $guardianIdentityRejected = $true
    $result.GuardianIdentityRejected = $true
    $guardianProcess = Start-Process -FilePath (Get-Process -Id $PID).Path `
        -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-File', $guardianScript,
            '-Repository', $OpenJarvisRepository,
            '-Port', [string]$Port,
            '-ExpectedOwnerProcessId', [string]$process.Id,
            '-ExpectedDesktopProcessIds', [string]$desktopSentinel.Id,
            '-ExpectedDesktopExecutablePath', (Get-Process -Id $PID).Path,
            '-PollMilliseconds', '100',
            '-DesktopExitStableSeconds', '1',
            '-StatePathOverride', $guardianState,
            '-LogPathOverride', $guardianLog
        ) -WindowStyle Hidden -PassThru
    $guardianReadyDeadline = [DateTime]::UtcNow.AddSeconds(15)
    $guardianReady = $false
    while ([DateTime]::UtcNow -lt $guardianReadyDeadline -and
        -not $guardianProcess.HasExited) {
        if ((Test-Path -LiteralPath $guardianLog -PathType Leaf) -and
            (Select-String -LiteralPath $guardianLog `
                -SimpleMatch 'event=guardian_started' -Quiet)) {
            $guardianReady = $true
            break
        }
        Start-Sleep -Milliseconds 100
        $guardianProcess.Refresh()
    }
    if (-not $guardianReady -or $guardianProcess.HasExited) {
        throw 'Lifecycle guardian exited before the tracked Desktop sentinel.'
    }
    Stop-Process -Id $desktopSentinel.Id -Force
    $desktopSentinel.WaitForExit(5000) | Out-Null
    $guardianDeadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $guardianDeadline -and `
        -not $guardianProcess.HasExited) {
        Start-Sleep -Milliseconds 100
        $guardianProcess.Refresh()
    }
    if (-not $guardianProcess.HasExited -or $guardianProcess.ExitCode -ne 0 -or
        (Get-OpenJarvisSharedCodexOwner -Config $config)) {
        throw 'Lifecycle guardian did not release the isolated shared runtime.'
    }
    $guardianStopValidated = $true
    $result.GuardianStopValidated = $true
}
catch {
    $stderr = Join-Path $probeRoot 'stderr.log'
    if (Test-Path -LiteralPath $stderr -PathType Leaf) {
        Get-Content -LiteralPath $stderr -Tail 80 -ErrorAction SilentlyContinue |
            Write-Warning
    }
    throw
}
finally {
    [Environment]::SetEnvironmentVariable('CODEX_HOME', $oldHome, 'Process')
    if ($null -ne $desktopSentinel -and -not $desktopSentinel.HasExited) {
        Stop-Process -Id $desktopSentinel.Id -Force
        $desktopSentinel.WaitForExit(5000) | Out-Null
    }
    if ($null -ne $guardianProcess -and -not $guardianProcess.HasExited) {
        Stop-Process -Id $guardianProcess.Id -Force
        $guardianProcess.WaitForExit(5000) | Out-Null
    }
    if ($null -ne $rejectedGuardianProcess -and
        -not $rejectedGuardianProcess.HasExited) {
        Stop-Process -Id $rejectedGuardianProcess.Id -Force
        $rejectedGuardianProcess.WaitForExit(5000) | Out-Null
    }
    $ownerToStop = Get-OpenJarvisSharedCodexOwner -Config $config
    if ($null -ne $ownerToStop -and $ownerToStop.Valid) {
        Stop-OpenJarvisSharedCodexOwner -Config $config `
            -AllowUnsharedDesktopRecovery -Confirm:$false
        $managedStopValidated = $true
    }
    elseif ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(5000) | Out-Null
    }
    $stopDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $stopDeadline -and `
        (Get-NetTCPConnection -LocalPort $Port -State Listen `
            -ErrorAction SilentlyContinue)) {
        Start-Sleep -Milliseconds 100
    }
    if (Get-NetTCPConnection -LocalPort $Port -State Listen `
        -ErrorAction SilentlyContinue) {
        throw "Temporary listener on port $Port did not stop."
    }
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $probeRoot)) {
        if (-not $probeRoot.StartsWith(
            $validationPrefix, [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove unsafe path: $probeRoot"
        }
        Remove-ValidatedProtocolArtifact -Path $probeRoot
    }
}

$result.ManagedStopValidated = $managedStopValidated -or $guardianStopValidated
$result.GuardianIdentityRejected = $guardianIdentityRejected
$result.ClosedPortRejected = -not (
    Test-OpenJarvisSharedCodexProtocol `
        -SharedUrl "ws://127.0.0.1:$Port" -TimeoutSeconds 2
)
if (-not $result.ClosedPortRejected) {
    throw 'Protocol preflight accepted a closed temporary port.'
}
$result
