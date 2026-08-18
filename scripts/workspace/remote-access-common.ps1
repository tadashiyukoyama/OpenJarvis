Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-OpenJarvisManagedPath {
    param([Parameter(Mandatory)][string]$PathValue)
    $Resolved = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
    if (-not $Resolved.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Managed remote-access path must remain on disk D: $Resolved"
    }
    return $Resolved
}

function Get-OpenJarvisRemoteContext {
    param([Parameter(Mandatory)][string]$ScriptRoot)
    $WorkspaceRoot = Resolve-OpenJarvisManagedPath (Join-Path $ScriptRoot '..\..')
    $LocalConfigPath = Join-Path $WorkspaceRoot '.workspace\local\project.local.json'
    if (-not (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf)) {
        throw "Local workspace configuration not found: $LocalConfigPath"
    }
    $Config = Get-Content -LiteralPath $LocalConfigPath -Raw | ConvertFrom-Json
    $ConfiguredWorkspace = Resolve-OpenJarvisManagedPath ([string]$Config.workspaceRoot)
    if ($ConfiguredWorkspace -ne $WorkspaceRoot) {
        throw "Local configuration targets another workspace: $ConfiguredWorkspace"
    }
    $RuntimeRoot = Resolve-OpenJarvisManagedPath ([string]$Config.runtimeRoot)
    [pscustomobject]@{
        WorkspaceRoot = $WorkspaceRoot
        RuntimeRoot = $RuntimeRoot
        PythonExe = Join-Path $WorkspaceRoot '.venv\Scripts\python.exe'
        CredentialFile = Join-Path $WorkspaceRoot '.private\env\cloudflare-quick-tunnel.env'
        CloudflareRoot = Join-Path $RuntimeRoot 'cloudflare'
        StateFile = Join-Path $RuntimeRoot 'cloudflare\remote-access.processes.json'
        PublicUrlFile = Join-Path $RuntimeRoot 'cloudflare\public-url.txt'
        QrCodeFile = Join-Path $RuntimeRoot 'cloudflare\openjarvis-url-qr.png'
    }
}

function Assert-GatewayCredentialFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Gateway credential file not found: $Path"
    }
    $Names = @{}
    foreach ($RawLine in Get-Content -LiteralPath $Path) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith('#')) { continue }
        $Pair = $Line.Split('=', 2)
        if ($Pair.Count -ne 2) { throw 'Invalid gateway credential file' }
        $Name = $Pair[0].Trim()
        if ($Name -notin @('OJ_GATEWAY_USER', 'OJ_GATEWAY_PASSWORD') -or $Names.ContainsKey($Name)) {
            throw 'Invalid gateway credential file'
        }
        if (-not $Pair[1].Trim()) { throw "Gateway credential is empty: $Name" }
        $Names[$Name] = $true
    }
    if ($Names.Count -ne 2) { throw 'Gateway username and password must be configured' }
}

function Test-OpenJarvisHttpEndpoint {
    param([Parameter(Mandatory)][string]$Url)
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-OpenJarvisHttpEndpoint {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 20
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Test-OpenJarvisHttpEndpoint -Url $Url) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for local endpoint: $Url"
}

function Get-OpenJarvisProcessCommandLine {
    param([Parameter(Mandatory)][int]$ProcessId)
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $ProcessInfo) { return $null }
    return [string]$ProcessInfo.CommandLine
}

function Test-OpenJarvisExpectedProcess {
    param(
        [Parameter(Mandatory)][int]$ProcessId,
        [Parameter(Mandatory)][string[]]$ExpectedPatterns
    )
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $Process) { return $false }
    $CommandLine = Get-OpenJarvisProcessCommandLine -ProcessId $ProcessId
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    return @(
        $ExpectedPatterns | Where-Object { $CommandLine -like "*$_*" }
    ).Count -eq $ExpectedPatterns.Count
}

function Start-OpenJarvisProcessWithEnvironment {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$StandardOutput,
        [Parameter(Mandatory)][string]$StandardError
    )
    $Previous = @{}
    foreach ($Name in $Environment.Keys) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        [Environment]::SetEnvironmentVariable($Name, [string]$Environment[$Name], 'Process')
    }
    try {
        return Start-Process `
            -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StandardOutput `
            -RedirectStandardError $StandardError `
            -WindowStyle Hidden `
            -PassThru
    }
    finally {
        foreach ($Name in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process')
        }
    }
}
