[CmdletBinding()]
param(
    [int]$AppServerPort = 8131,
    [int]$BackendPort = 8127,
    [int]$FrontendPort = 5173,
    [ValidateSet('untrusted', 'on-request', 'never')]
    [string]$ApprovalPolicy = 'never',
    [ValidateSet('read-only', 'workspace-write', 'danger-full-access')]
    [string]$SandboxMode = 'danger-full-access',
    [switch]$SkipDesktop,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$LocalConfigPath = Join-Path $WorkspaceRoot '.workspace\local\project.local.json'
if (-not (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf)) {
    throw "Local workspace configuration not found: $LocalConfigPath"
}

$LocalConfig = Get-Content -LiteralPath $LocalConfigPath -Raw | ConvertFrom-Json
$RuntimeRoot = [System.IO.Path]::GetFullPath([string]$LocalConfig.runtimeRoot)
$StateRoot = [System.IO.Path]::GetFullPath((Join-Path $RuntimeRoot 'state'))
$CodexHome = [System.IO.Path]::GetFullPath([string]$LocalConfig.codexHome)
foreach ($ManagedPath in @($WorkspaceRoot, $RuntimeRoot, $StateRoot, $CodexHome)) {
    if (-not $ManagedPath.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Managed project path must remain on disk D: $ManagedPath"
    }
}

$SharedUrl = "ws://127.0.0.1:$AppServerPort"
$AppServerHealth = "http://127.0.0.1:$AppServerPort/healthz"
$BackendOrigin = "http://127.0.0.1:$BackendPort"
$BackendHealth = "$BackendOrigin/health"
$FrontendHealth = "http://127.0.0.1:$FrontendPort/"
$PythonExe = Join-Path $WorkspaceRoot '.venv\Scripts\python.exe'
$JarvisExe = Join-Path $WorkspaceRoot '.venv\Scripts\jarvis.exe'
$ViteScript = Join-Path $WorkspaceRoot 'frontend\node_modules\vite\bin\vite.js'
$GeminiEnvironmentPath = Join-Path $WorkspaceRoot '.private\env\gemini-live.env'
$AceleraChatEnvironmentPath = Join-Path $WorkspaceRoot '.private\env\acelerachat.env'

function Import-GeminiPrivateEnvironment {
    param([Parameter(Mandatory)][string]$Path)
    $AllowedNames = @(
        'GEMINI_LIVE_API_KEY_PRIMARY',
        'GEMINI_LIVE_API_KEY_FALLBACK',
        'GEMINI_LIVE_MODEL'
    )
    $Values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $Values }
    foreach ($RawLine in Get-Content -LiteralPath $Path) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith('#')) { continue }
        $Pair = $Line.Split('=', 2)
        if ($Pair.Count -ne 2) { throw "Invalid Gemini environment line in private file" }
        $Name = $Pair[0].Trim()
        if ($Name -notin $AllowedNames) {
            throw "Unknown variable in Gemini private environment: $Name"
        }
        $Value = $Pair[1].Trim()
        if ($Value.StartsWith('"') -and $Value.EndsWith('"')) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        if ($Value) { $Values[$Name] = $Value }
    }
    return $Values
}

function Import-AceleraChatPrivateEnvironment {
    param([Parameter(Mandatory)][string]$Path)
    $AllowedNames = @(
        'ACELERACHAT_BASE_URL',
        'ACELERACHAT_BEARER_TOKEN',
        'ACELERACHAT_WEBHOOK_SECRET_CURRENT',
        'ACELERACHAT_WEBHOOK_SECRET_PREVIOUS',
        'ACELERACHAT_EMAIL_INBOX_ID',
        'ACELERACHAT_WHATSAPP_INBOX_ID'
    )
    $Values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $Values }
    foreach ($RawLine in Get-Content -LiteralPath $Path) {
        $Line = $RawLine.Trim()
        if (-not $Line -or $Line.StartsWith('#')) { continue }
        $Pair = $Line.Split('=', 2)
        if ($Pair.Count -ne 2) { throw 'Invalid AceleraChat environment line in private file' }
        $Name = $Pair[0].Trim()
        if ($Name -notin $AllowedNames) {
            throw "Unknown variable in AceleraChat private environment: $Name"
        }
        $Value = $Pair[1].Trim()
        if ($Value.StartsWith('"') -and $Value.EndsWith('"')) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        if ($Value) { $Values[$Name] = $Value }
    }
    return $Values
}

function Test-HttpEndpoint {
    param([Parameter(Mandatory)][string]$Url)
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-HttpEndpoint {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 20
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Test-HttpEndpoint -Url $Url) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for local endpoint: $Url"
}

function Wait-DesktopSharedConnection {
    param(
        [Parameter(Mandatory)][int]$Port,
        [int]$TimeoutSeconds = 30
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $ConnectedSince = $null
    while ([DateTime]::UtcNow -lt $Deadline) {
        $DesktopProcessIds = @(
            Get-Process -Name ChatGPT -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty Id
        )
        if ($DesktopProcessIds.Count -gt 0) {
            $Connections = @(
                Get-NetTCPConnection -RemotePort $Port -State Established -ErrorAction SilentlyContinue
            )
            $PrivateAppServers = @(
                Get-CimInstance Win32_Process |
                    Where-Object {
                        $_.ParentProcessId -in $DesktopProcessIds -and
                        $_.Name -eq 'codex.exe' -and
                        $_.CommandLine -like '*app-server*'
                    }
            )
            $HasSharedConnection = @(
                $Connections | Where-Object { $_.OwningProcess -in $DesktopProcessIds }
            ).Count -gt 0
            if ($HasSharedConnection -and $PrivateAppServers.Count -eq 0) {
                if ($null -eq $ConnectedSince) { $ConnectedSince = [DateTime]::UtcNow }
                if (([DateTime]::UtcNow - $ConnectedSince).TotalSeconds -ge 2) { return }
            }
            else {
                $ConnectedSince = $null
            }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Codex Desktop did not connect to the shared app-server on 127.0.0.1:$Port"
}

function Get-PortOwner {
    param([Parameter(Mandatory)][int]$Port)
    return Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ProcessCommandLine {
    param([Parameter(Mandatory)][int]$ProcessId)
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $ProcessInfo) { return $null }
    return [string]$ProcessInfo.CommandLine
}

function Start-WithEnvironment {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [string]$StandardOutput,
        [string]$StandardError,
        [switch]$Visible
    )
    $Previous = @{}
    foreach ($Name in $Environment.Keys) {
        $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        [Environment]::SetEnvironmentVariable($Name, [string]$Environment[$Name], 'Process')
    }
    try {
        $Parameters = @{
            FilePath = $FilePath
            WorkingDirectory = $WorkingDirectory
            PassThru = $true
        }
        if ($ArgumentList.Count -gt 0) { $Parameters.ArgumentList = $ArgumentList }
        if ($StandardOutput) { $Parameters.RedirectStandardOutput = $StandardOutput }
        if ($StandardError) { $Parameters.RedirectStandardError = $StandardError }
        if (-not $Visible) { $Parameters.WindowStyle = 'Hidden' }
        return Start-Process @Parameters
    }
    finally {
        foreach ($Name in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process')
        }
    }
}

function Assert-ExpectedPortOwner {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string[]]$ExpectedPattern,
        [Parameter(Mandatory)][string]$ServiceName
    )
    $Owner = Get-PortOwner -Port $Port
    if ($null -eq $Owner) { return $null }
    $CommandLine = Get-ProcessCommandLine -ProcessId $Owner.OwningProcess
    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        Start-Sleep -Milliseconds 250
        if ($null -eq (Get-PortOwner -Port $Port)) { return $null }
        throw "$ServiceName port owner could not be audited; owner was not modified"
    }
    $MatchesExpectedOwner = @(
        $ExpectedPattern | Where-Object { $CommandLine -like "*$_*" }
    ).Count -gt 0
    if (-not $MatchesExpectedOwner) {
        throw "$ServiceName port collision on 127.0.0.1:$Port; owner was not modified"
    }
    return $Owner
}

foreach ($RequiredFile in @($PythonExe, $JarvisExe, $ViteScript)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required local runtime file not found: $RequiredFile"
    }
}

$CodexPackage = Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop
$CodexExe = Join-Path $CodexPackage.InstallLocation 'app\resources\codex.exe'
$DesktopExe = Join-Path $CodexPackage.InstallLocation 'app\ChatGPT.exe'
$NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$GeminiEnvironment = Import-GeminiPrivateEnvironment -Path $GeminiEnvironmentPath
$AceleraChatEnvironment = Import-AceleraChatPrivateEnvironment -Path $AceleraChatEnvironmentPath
foreach ($PackagedExecutable in @($CodexExe, $DesktopExe)) {
    if (-not (Test-Path -LiteralPath $PackagedExecutable -PathType Leaf)) {
        throw "Required Codex executable not found in the installed package"
    }
}

if ($ValidateOnly) {
    [pscustomobject]@{
        WorkspaceRoot = $WorkspaceRoot
        RuntimeRoot = $RuntimeRoot
        StateRoot = $StateRoot
        CodexHome = $CodexHome
        SharedUrl = $SharedUrl
        CodexExe = $CodexExe
        DesktopExe = $DesktopExe
        Status = 'VALIDATED'
    }
    return
}

if (-not $SkipDesktop) {
    $DesktopProcesses = @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue)
    if ($DesktopProcesses.Count -gt 0) {
        throw 'Codex Desktop is open. Close it normally, then run this launcher again.'
    }
}

[System.IO.Directory]::CreateDirectory((Join-Path $RuntimeRoot 'codex')) | Out-Null
[System.IO.Directory]::CreateDirectory($StateRoot) | Out-Null
$SharedOwner = Assert-ExpectedPortOwner -Port $AppServerPort -ExpectedPattern "app-server --listen $SharedUrl" -ServiceName 'Codex app-server'
if ($null -ne $SharedOwner) {
    $SharedCommandLine = Get-ProcessCommandLine -ProcessId $SharedOwner.OwningProcess
    $ExpectedPolicyArguments = "-a $ApprovalPolicy -s $SandboxMode app-server --listen $SharedUrl"
    if ($SharedCommandLine -notlike "*$ExpectedPolicyArguments*") {
        Stop-Process -Id $SharedOwner.OwningProcess
        Wait-Process -Id $SharedOwner.OwningProcess -Timeout 10 -ErrorAction SilentlyContinue
        $SharedOwner = $null
    }
}
if ($null -eq $SharedOwner) {
    Start-WithEnvironment `
        -FilePath $CodexExe `
        -ArgumentList @('-a', $ApprovalPolicy, '-s', $SandboxMode, 'app-server', '--listen', $SharedUrl) `
        -Environment @{ CODEX_HOME = $CodexHome } `
        -WorkingDirectory $WorkspaceRoot `
        -StandardOutput (Join-Path $RuntimeRoot 'codex\shared-app-server.stdout.log') `
        -StandardError (Join-Path $RuntimeRoot 'codex\shared-app-server.stderr.log') | Out-Null
}
Wait-HttpEndpoint -Url $AppServerHealth

$BackendOwner = Assert-ExpectedPortOwner `
    -Port $BackendPort `
    -ExpectedPattern @(
        "$WorkspaceRoot\.venv\Scripts\jarvis.exe",
        '-m openjarvis.cli serve'
    ) `
    -ServiceName 'OpenJarvis backend'
if ($null -ne $BackendOwner) {
    Stop-Process -Id $BackendOwner.OwningProcess
    Wait-Process -Id $BackendOwner.OwningProcess -Timeout 10 -ErrorAction SilentlyContinue
}
Start-WithEnvironment `
    -FilePath $PythonExe `
    -ArgumentList @('-m', 'openjarvis.cli', 'serve', '--host', '127.0.0.1', '--port', [string]$BackendPort, '--agent', 'codex') `
    -Environment (@{
        CODEX_HOME = $CodexHome
        CODEX_APP_SERVER_WS_URL = $SharedUrl
        OPENJARVIS_CODEX_APP_SERVER_URL = $SharedUrl
        OPENJARVIS_CODEX_APPROVAL_POLICY = $ApprovalPolicy
        OPENJARVIS_WORKSPACE_ROOT = $WorkspaceRoot
        OPENJARVIS_RUNTIME_ROOT = $RuntimeRoot
        OPENJARVIS_HOME = $StateRoot
    } + $GeminiEnvironment + $AceleraChatEnvironment) `
    -WorkingDirectory $WorkspaceRoot `
    -StandardOutput (Join-Path $RuntimeRoot 'backend.stdout.log') `
    -StandardError (Join-Path $RuntimeRoot 'backend.stderr.log') | Out-Null
Wait-HttpEndpoint -Url $BackendHealth

$FrontendOwner = Assert-ExpectedPortOwner -Port $FrontendPort -ExpectedPattern "$WorkspaceRoot\frontend\node_modules\vite" -ServiceName 'OpenJarvis frontend'
if ($null -eq $FrontendOwner) {
    Start-WithEnvironment `
        -FilePath $NodeExe `
        -ArgumentList @($ViteScript, '--host', '127.0.0.1', '--port', [string]$FrontendPort) `
        -Environment @{ VITE_API_URL = $BackendOrigin } `
        -WorkingDirectory (Join-Path $WorkspaceRoot 'frontend') `
        -StandardOutput (Join-Path $RuntimeRoot 'frontend.stdout.log') `
        -StandardError (Join-Path $RuntimeRoot 'frontend.stderr.log') | Out-Null
}
Wait-HttpEndpoint -Url $FrontendHealth

if (-not $SkipDesktop) {
    Start-WithEnvironment `
        -FilePath $DesktopExe `
        -ArgumentList @() `
        -Environment @{
            CODEX_HOME = $CodexHome
            CODEX_APP_SERVER_WS_URL = $SharedUrl
            OPENJARVIS_WORKSPACE_ROOT = $WorkspaceRoot
        } `
        -WorkingDirectory $WorkspaceRoot `
        -Visible `
        | Out-Null
    Wait-DesktopSharedConnection -Port $AppServerPort
}

[pscustomobject]@{
    SharedAppServer = $SharedUrl
    ApprovalPolicy = $ApprovalPolicy
    SandboxMode = $SandboxMode
    Backend = "http://127.0.0.1:$BackendPort"
    Frontend = "http://127.0.0.1:$FrontendPort"
    DesktopStarted = -not $SkipDesktop
    Status = 'RUNNING'
}
