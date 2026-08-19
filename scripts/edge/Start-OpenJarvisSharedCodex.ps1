[CmdletBinding()]
param(
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [int]$Port = 8131,
    [ValidateSet('untrusted', 'on-request', 'never')]
    [string]$ApprovalPolicy = 'on-request',
    [ValidateSet('read-only', 'workspace-write', 'danger-full-access')]
    [string]$SandboxMode = 'workspace-write',
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexRuntime.psm1') -Force

$config = Get-OpenJarvisSharedCodexConfig -Repository $Repository -Port $Port
$redirect = Get-OpenJarvisPersistentCodexRedirect
if ($ValidateOnly) {
    [pscustomobject]@{
        Repository = $config.Repository
        CodexHome = $config.CodexHome
        SharedUrl = $config.SharedUrl
        PackageVersion = $config.PackageVersion
        RuntimeId = $config.RuntimeId
        CodexExe = $config.CodexExe
        CodexSha256 = $config.CodexSha256
        UserRedirect = $redirect.User
        MachineRedirect = $redirect.Machine
        Status = 'VALIDATED_WITHOUT_START'
    }
    return
}

Assert-OpenJarvisNoPersistentCodexRedirect
$topology = Get-OpenJarvisDesktopCodexTopology -Config $config
if ($topology.DesktopRunning) {
    throw (
        'Codex Desktop is already running. It was not closed or redirected; ' +
        'close it normally before explicitly entering shared mode.'
    )
}

$owner = Get-OpenJarvisSharedCodexOwner -Config $config
if ($null -ne $owner) {
    $readiness = Get-OpenJarvisSharedCodexReadiness -Config $config
    if ($readiness.Valid) {
        [pscustomobject]@{
            ProcessId = $owner.ProcessId
            SharedUrl = $config.SharedUrl
            RuntimeId = $config.RuntimeId
            Started = $false
            Status = 'ALREADY_RUNNING_VALIDATED'
        }
        return
    }
    if ($owner.Managed -and $owner.RecognizedRuntime) {
        throw (
            'Port is owned by a stale or unhealthy managed Codex runtime. ' +
            'Use the explicit legacy cleanup only while Desktop is closed.'
        )
    }
    throw "Port $Port is owned by an unrelated process; nothing was stopped."
}

[System.IO.Directory]::CreateDirectory($config.LogDirectory) | Out-Null
[System.IO.Directory]::CreateDirectory($config.StateDirectory) | Out-Null
$stdoutLog = Join-Path $config.LogDirectory 'shared-app-server.stdout.log'
$stderrLog = Join-Path $config.LogDirectory 'shared-app-server.stderr.log'
$arguments = @(
    '-a', $ApprovalPolicy,
    '-s', $SandboxMode,
    'app-server', '--listen', $config.SharedUrl
)
$previous = [ordered]@{
    CODEX_HOME = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
    OPENJARVIS_SHARED_CODEX_RUNTIME = [Environment]::GetEnvironmentVariable(
        'OPENJARVIS_SHARED_CODEX_RUNTIME', 'Process'
    )
}
$process = $null
try {
    [Environment]::SetEnvironmentVariable(
        'CODEX_HOME', $config.CodexHome, 'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'OPENJARVIS_SHARED_CODEX_RUNTIME', $config.RuntimeId, 'Process'
    )
    $process = Start-Process -FilePath $config.CodexExe `
        -ArgumentList $arguments -WorkingDirectory $config.Repository `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog `
        -WindowStyle Hidden -PassThru
}
finally {
    foreach ($entry in $previous.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable(
            $entry.Key, $entry.Value, 'Process'
        )
    }
}

try {
    $readiness = Wait-OpenJarvisSharedCodexReadiness -Config $config
}
catch {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    $stopDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $stopDeadline -and `
        (Get-OpenJarvisSharedCodexOwner -Config $config)) {
        Start-Sleep -Milliseconds 100
    }
    $remainingOwner = Get-OpenJarvisSharedCodexOwner -Config $config
    if ($null -ne $remainingOwner) {
        if ($remainingOwner.Valid) {
            Stop-OpenJarvisSharedCodexOwner -Config $config -Confirm:$false
        }
        else {
            throw (
                'Preflight failed and the port changed to an unverified owner; ' +
                'nothing else was stopped.'
            )
        }
    }
    throw
}

$state = [ordered]@{
    schema_version = 2
    process_id = $process.Id
    shared_url = $config.SharedUrl
    runtime_id = $config.RuntimeId
    package_version = $config.PackageVersion
    codex_exe = $config.CodexExe
    codex_sha256 = $config.CodexSha256
    started_at = [DateTime]::UtcNow.ToString('o')
}
$state | ConvertTo-Json -Depth 4 | Set-Content `
    -LiteralPath $config.StatePath -Encoding UTF8
[pscustomobject]@{
    ProcessId = $process.Id
    SharedUrl = $config.SharedUrl
    RuntimeId = $config.RuntimeId
    Ready = $readiness.Ready
    Healthy = $readiness.Healthy
    ProtocolInitialized = $readiness.ProtocolInitialized
    Started = $true
    Status = 'STARTED_AND_VALIDATED'
}
