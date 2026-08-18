[CmdletBinding()]
param(
    [int]$GatewayPort = 8140,
    [int]$BackendPort = 8127,
    [int]$StartupTimeoutSeconds = 30,
    [switch]$ValidateOnly
)

. (Join-Path $PSScriptRoot 'remote-access-common.ps1')

$Context = Get-OpenJarvisRemoteContext -ScriptRoot $PSScriptRoot
Assert-GatewayCredentialFile -Path $Context.CredentialFile
foreach ($RequiredFile in @(
    $Context.PythonExe,
    (Join-Path $Context.WorkspaceRoot 'frontend\scripts\generate-url-qr.mjs'),
    (Join-Path $Context.WorkspaceRoot 'src\openjarvis\server\static\index.html')
)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required remote-access artifact not found: $RequiredFile"
    }
}
$NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$CloudflaredExe = (Get-Command cloudflared.exe -ErrorAction Stop).Source
$GatewayHealth = "http://127.0.0.1:$GatewayPort/__openjarvis/health"
$BackendHealth = "http://127.0.0.1:$BackendPort/health"

$CloudflaredConfig = @(@(
    (Join-Path $HOME '.cloudflared\config.yml'),
    (Join-Path $HOME '.cloudflared\config.yaml')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
if ($CloudflaredConfig.Count -gt 0) {
    throw 'Quick Tunnel startup refused because a .cloudflared config file exists. Preserve it and use the named-tunnel procedure.'
}

$PortOwner = Get-NetTCPConnection -State Listen -LocalPort $GatewayPort -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($ValidateOnly) {
    [pscustomobject]@{
        status = 'VALIDATED'
        workspaceRoot = $Context.WorkspaceRoot
        backend = if (Test-OpenJarvisHttpEndpoint -Url $BackendHealth) { 'READY' } else { 'OFFLINE' }
        gatewayPort = $GatewayPort
        gatewayPortOwner = if ($null -eq $PortOwner) { 'FREE' } else { [string]$PortOwner.OwningProcess }
        credentials = 'CONFIGURED'
        staticFrontend = 'PRESENT'
        cloudflared = $CloudflaredExe
        actionTaken = 'NONE'
    } | ConvertTo-Json -Depth 4
    return
}

if (-not (Test-OpenJarvisHttpEndpoint -Url $BackendHealth)) {
    throw "OpenJarvis backend is not ready at $BackendHealth"
}
[System.IO.Directory]::CreateDirectory($Context.CloudflareRoot) | Out-Null

if (Test-Path -LiteralPath $Context.StateFile -PathType Leaf) {
    $ExistingState = Get-Content -LiteralPath $Context.StateFile -Raw | ConvertFrom-Json
    $GatewayAlive = Test-OpenJarvisExpectedProcess `
        -ProcessId ([int]$ExistingState.gatewayPid) `
        -ExpectedPatterns @('openjarvis.server.remote_access', "--port $GatewayPort")
    $TunnelAlive = Test-OpenJarvisExpectedProcess `
        -ProcessId ([int]$ExistingState.tunnelPid) `
        -ExpectedPatterns @('cloudflared', "127.0.0.1:$GatewayPort")
    if ($GatewayAlive -and $TunnelAlive -and (Test-Path -LiteralPath $Context.PublicUrlFile)) {
        [pscustomobject]@{
            status = 'ALREADY_RUNNING'
            url = (Get-Content -LiteralPath $Context.PublicUrlFile -Raw).Trim()
            qrCode = $Context.QrCodeFile
            gatewayPid = [int]$ExistingState.gatewayPid
            tunnelPid = [int]$ExistingState.tunnelPid
        } | ConvertTo-Json -Depth 4
        return
    }
    if ($GatewayAlive -or $TunnelAlive) {
        throw 'Partial remote-access state detected. Run stop-remote-access.ps1 before retrying.'
    }
    Remove-Item -LiteralPath $Context.StateFile
}

if ($null -ne $PortOwner) {
    throw "Gateway port collision on 127.0.0.1:$GatewayPort; owner was not modified"
}

$Timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$GatewayStdout = Join-Path $Context.CloudflareRoot "gateway-$Timestamp.stdout.log"
$GatewayStderr = Join-Path $Context.CloudflareRoot "gateway-$Timestamp.stderr.log"
$TunnelStdout = Join-Path $Context.CloudflareRoot "cloudflared-$Timestamp.stdout.log"
$TunnelStderr = Join-Path $Context.CloudflareRoot "cloudflared-$Timestamp.stderr.log"
$GatewayProcess = $null
$TunnelProcess = $null
try {
    $GatewayProcess = Start-OpenJarvisProcessWithEnvironment `
        -FilePath $Context.PythonExe `
        -ArgumentList @('-m', 'openjarvis.server.remote_access', '--host', '127.0.0.1', '--port', [string]$GatewayPort) `
        -Environment @{
            OPENJARVIS_WORKSPACE_ROOT = $Context.WorkspaceRoot
            OPENJARVIS_RUNTIME_ROOT = $Context.RuntimeRoot
            OJ_GATEWAY_ORIGIN = "http://127.0.0.1:$BackendPort"
            OJ_GATEWAY_SECRET_FILE = $Context.CredentialFile
            OJ_GATEWAY_ACCESS_LOG = (Join-Path $Context.CloudflareRoot 'gateway-access.log')
        } `
        -WorkingDirectory $Context.WorkspaceRoot `
        -StandardOutput $GatewayStdout `
        -StandardError $GatewayStderr
    Wait-OpenJarvisHttpEndpoint -Url $GatewayHealth -TimeoutSeconds $StartupTimeoutSeconds

    $TunnelProcess = Start-Process `
        -FilePath $CloudflaredExe `
        -ArgumentList @('tunnel', '--url', "http://127.0.0.1:$GatewayPort", '--no-autoupdate') `
        -WorkingDirectory $Context.WorkspaceRoot `
        -RedirectStandardOutput $TunnelStdout `
        -RedirectStandardError $TunnelStderr `
        -WindowStyle Hidden `
        -PassThru

    $Deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    $PublicUrl = ''
    while ([DateTime]::UtcNow -lt $Deadline -and -not $PublicUrl) {
        Start-Sleep -Milliseconds 300
        foreach ($LogPath in @($TunnelStdout, $TunnelStderr)) {
            if (-not (Test-Path -LiteralPath $LogPath)) { continue }
            $Match = Select-String -Path $LogPath -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
                Select-Object -Last 1
            if ($null -ne $Match) {
                $PublicUrl = $Match.Matches[-1].Value
                break
            }
        }
    }
    if (-not $PublicUrl) {
        throw 'Cloudflare Quick Tunnel did not publish a URL before the timeout.'
    }
    if ($TunnelProcess.HasExited) {
        throw "Cloudflare Quick Tunnel exited with code $($TunnelProcess.ExitCode)."
    }
    $JarvisUrl = "$PublicUrl/jarvis"
    Set-Content -LiteralPath $Context.PublicUrlFile -Value $JarvisUrl -Encoding ASCII
    & $NodeExe `
        (Join-Path $Context.WorkspaceRoot 'frontend\scripts\generate-url-qr.mjs') `
        $JarvisUrl `
        $Context.QrCodeFile | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Context.QrCodeFile)) {
        throw 'Failed to generate the local QR code for the tunnel URL.'
    }
    if ($GatewayProcess.HasExited -or $TunnelProcess.HasExited) {
        throw 'Remote-access process exited before the runtime state was committed.'
    }

    [ordered]@{
        schemaVersion = 1
        workspaceRoot = $Context.WorkspaceRoot
        gatewayPort = $GatewayPort
        backendPort = $BackendPort
        gatewayPid = $GatewayProcess.Id
        tunnelPid = $TunnelProcess.Id
        url = $JarvisUrl
        startedAt = [DateTimeOffset]::Now.ToString('o')
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Context.StateFile -Encoding UTF8

    [pscustomobject]@{
        status = 'RUNNING'
        url = $JarvisUrl
        qrCode = $Context.QrCodeFile
        gatewayPid = $GatewayProcess.Id
        tunnelPid = $TunnelProcess.Id
    } | ConvertTo-Json -Depth 4
}
catch {
    if ($null -ne $TunnelProcess -and -not $TunnelProcess.HasExited) {
        Stop-Process -Id $TunnelProcess.Id -ErrorAction SilentlyContinue
    }
    if ($null -ne $GatewayProcess -and -not $GatewayProcess.HasExited) {
        Stop-Process -Id $GatewayProcess.Id -ErrorAction SilentlyContinue
    }
    throw
}
