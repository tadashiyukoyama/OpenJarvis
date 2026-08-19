[CmdletBinding()]
param(
    [int]$Port = 18131,
    [string]$OpenJarvisRepository = 'D:\dev\workspaces\openjarvis',
    [switch]$KeepArtifacts,
    [switch]$CleanupArtifactsOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repository = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\..')
)
$validationRoot = 'D:\dev\runtime\openjarvis\validation'
$validationPrefix = "$validationRoot\"
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
            if (-not $candidate.StartsWith(
                $validationPrefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Refusing to remove unsafe path: $candidate"
            }
            Remove-Item -LiteralPath $candidate -Recurse -Force
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
$result = $null
$managedStopValidated = $false
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
        ThreadOrTurnSent = $false
        Status = 'ISOLATED_PROTOCOL_SMOKE_PASSED'
    }
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
        Remove-Item -LiteralPath $probeRoot -Recurse -Force
    }
}

$result.ManagedStopValidated = $managedStopValidated
$result.ClosedPortRejected = -not (
    Test-OpenJarvisSharedCodexProtocol `
        -SharedUrl "ws://127.0.0.1:$Port" -TimeoutSeconds 2
)
if (-not $result.ClosedPortRejected) {
    throw 'Protocol preflight accepted a closed temporary port.'
}
$result
