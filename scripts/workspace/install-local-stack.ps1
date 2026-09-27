[CmdletBinding()]
param(
    [string]$DevelopmentRoot = 'F:\OpenJarvis',
    [switch]$InstallDependencies,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ManagedPath {
    param([Parameter(Mandatory)][string]$PathValue)
    $Resolved = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
    if (-not $Resolved.StartsWith('F:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Every managed OpenJarvis path must remain on disk F: $Resolved"
    }
    return $Resolved
}

function Resolve-RequiredCommand {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string[]]$Fallback = @()
    )
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $Command) { return $Command.Source }
    foreach ($Candidate in $Fallback) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($Candidate)
        }
    }
    throw "Required command not found: $Name"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Test-Artifact {
    param([Parameter(Mandatory)][string]$Path)
    if (Test-Path -LiteralPath $Path) { return 'PRESENT' }
    return 'MISSING'
}

$WorkspaceRoot = Resolve-ManagedPath (Join-Path $PSScriptRoot '..\..')
$DevelopmentRoot = Resolve-ManagedPath $DevelopmentRoot
$GitExe = Resolve-RequiredCommand -Name 'git.exe'
$GitOutput = & $GitExe -C $WorkspaceRoot rev-parse --show-toplevel 2>$null
$GitExitCode = $LASTEXITCODE
$GitRoot = $GitOutput | Select-Object -First 1
if ($GitExitCode -ne 0 -or -not $GitRoot) {
    throw 'The installer requires an already-cloned and audited Git repository.'
}
$GitRoot = [System.IO.Path]::GetFullPath([string]$GitRoot).TrimEnd('\')
if ($GitRoot -ne $WorkspaceRoot) {
    throw "Unexpected Git root: $GitRoot"
}

$Drive = Get-PSDrive -Name F -ErrorAction Stop
$MinimumFreeBytes = 5GB
if ([UInt64]$Drive.Free -lt [UInt64]$MinimumFreeBytes) {
    throw 'Disk F: must have at least 5 GiB free for the source-only stack.'
}

$NodeExe = Resolve-RequiredCommand -Name 'node.exe'
$NpmExe = Resolve-RequiredCommand -Name 'npm.cmd' -Fallback @(
    (Join-Path (Split-Path -Parent $NodeExe) 'npm.cmd')
)
$UvCommand = Get-Command 'uv.exe' -ErrorAction SilentlyContinue
$UvExe = if ($null -ne $UvCommand) {
    $UvCommand.Source
}
elseif (Test-Path -LiteralPath (Join-Path $HOME '.local\bin\uv.exe') -PathType Leaf) {
    [System.IO.Path]::GetFullPath((Join-Path $HOME '.local\bin\uv.exe'))
}
elseif ($ValidateOnly) {
    $null
}
else {
    throw 'Required command not found: uv.exe'
}
$CloudflaredExe = Resolve-RequiredCommand -Name 'cloudflared.exe'

$NodeVersion = (& $NodeExe --version).Trim().TrimStart('v')
$NodeMajor = [int]($NodeVersion.Split('.')[0])
if ($NodeMajor -lt 20) {
    throw "Node.js 20 or newer is required; found $NodeVersion"
}

$CodexPackage = Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue
if ($null -eq $CodexPackage) {
    throw 'The official ChatGPT/Codex Windows app is required. Install Microsoft Store package 9PLM9XGG6VKS.'
}

$WorkspaceName = Split-Path -Leaf $WorkspaceRoot
$Paths = [ordered]@{
    schemaVersion = 2
    workspaceRoot = $WorkspaceRoot
    worktreesRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'worktrees')
    runtimeRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'runtime')
    cacheRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'cache')
    modelsRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'models')
    artifactsRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'artifacts')
    toolchainsRoot = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'toolchains')
    codexHome = Resolve-ManagedPath (Join-Path $DevelopmentRoot 'codex-home\.codex')
}
$ManagedToolState = [ordered]@{
    uvCache = Resolve-ManagedPath (Join-Path $Paths.cacheRoot 'uv')
    uvPython = Resolve-ManagedPath (Join-Path $Paths.toolchainsRoot 'python')
    uvTools = Resolve-ManagedPath (Join-Path $Paths.toolchainsRoot 'uv-tools')
    npmCache = Resolve-ManagedPath (Join-Path $Paths.cacheRoot 'npm')
}

$LocalConfigPath = Join-Path $WorkspaceRoot '.workspace\local\project.local.json'
$LocalConfigState = 'PRESENT'
if (Test-Path -LiteralPath $LocalConfigPath -PathType Leaf) {
    $ExistingConfig = Get-Content -LiteralPath $LocalConfigPath -Raw | ConvertFrom-Json
    foreach ($Name in $Paths.Keys) {
        if ($Name -eq 'schemaVersion') { continue }
        $Property = $ExistingConfig.PSObject.Properties[$Name]
        if ($null -eq $Property -or -not $Property.Value) {
            throw "Existing local configuration is missing $Name; it was not overwritten."
        }
        $ExistingValue = $Property.Value
        $ResolvedExisting = Resolve-ManagedPath ([string]$ExistingValue)
        if ($ResolvedExisting -ne [string]$Paths[$Name]) {
            throw "Existing local configuration differs at $Name; it was not overwritten."
        }
    }
    $LocalConfigState = 'PRESENT_VALIDATED'
}
else {
    $LocalConfigState = 'MISSING'
}

if (-not $ValidateOnly) {
    foreach ($Path in @($Paths.Values; $ManagedToolState.Values) | Where-Object { $_ -is [string] }) {
        [System.IO.Directory]::CreateDirectory([string]$Path) | Out-Null
    }
    [System.IO.Directory]::CreateDirectory((Split-Path -Parent $LocalConfigPath)) | Out-Null
    if ($LocalConfigState -eq 'MISSING') {
        $Paths | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $LocalConfigPath -Encoding UTF8
        $LocalConfigState = 'CREATED'
    }
    [Environment]::SetEnvironmentVariable(
        'OPENJARVIS_WORKSPACE_ROOT',
        $WorkspaceRoot,
        [EnvironmentVariableTarget]::User
    )
    $env:OPENJARVIS_WORKSPACE_ROOT = $WorkspaceRoot

    $PrivateEnvRoot = Join-Path $WorkspaceRoot 'credenciais\workspace\env'
    [System.IO.Directory]::CreateDirectory($PrivateEnvRoot) | Out-Null
    $PrivateTemplates = @{
        (Join-Path $WorkspaceRoot '.workspace\templates\gemini-live.env.example') =
            (Join-Path $PrivateEnvRoot 'gemini-live.env')
        (Join-Path $WorkspaceRoot '.workspace\templates\cloudflare-quick-tunnel.env.example') =
            (Join-Path $PrivateEnvRoot 'cloudflare-quick-tunnel.env')
        (Join-Path $WorkspaceRoot '.workspace\templates\acelerachat.env.example') =
            (Join-Path $PrivateEnvRoot 'acelerachat.env')
    }
    foreach ($Template in $PrivateTemplates.Keys) {
        $Destination = $PrivateTemplates[$Template]
        if (-not (Test-Path -LiteralPath $Destination)) {
            Copy-Item -LiteralPath $Template -Destination $Destination
        }
    }
}

if ($InstallDependencies -and -not $ValidateOnly) {
    $env:UV_CACHE_DIR = $ManagedToolState.uvCache
    $env:UV_PYTHON_INSTALL_DIR = $ManagedToolState.uvPython
    $env:UV_TOOL_DIR = $ManagedToolState.uvTools
    $env:npm_config_cache = $ManagedToolState.npmCache
    Invoke-Checked -FilePath $UvExe -WorkingDirectory $WorkspaceRoot -ArgumentList @(
        'sync', '--frozen', '--python', '3.13',
        '--extra', 'desktop', '--extra', 'dev'
    )
    Invoke-Checked -FilePath $NpmExe -WorkingDirectory (Join-Path $WorkspaceRoot 'frontend') -ArgumentList @('ci')
    Invoke-Checked -FilePath $NpmExe -WorkingDirectory (Join-Path $WorkspaceRoot 'frontend') -ArgumentList @('run', 'build')
}

$BridgeRoot = Join-Path $WorkspaceRoot 'src\openjarvis\channels\whatsapp_baileys_bridge'
$PythonEnvironment = Test-Artifact (Join-Path $WorkspaceRoot '.venv\Scripts\python.exe')
$FrontendDependencies = Test-Artifact (Join-Path $WorkspaceRoot 'frontend\node_modules')
$FrontendStaticBuild = Test-Artifact (Join-Path $WorkspaceRoot 'src\openjarvis\server\static\index.html')
$LegacyBaileysSource = Test-Artifact $BridgeRoot
$AllArtifactsReady = @(
    $PythonEnvironment,
    $FrontendDependencies,
    $FrontendStaticBuild
) -notcontains 'MISSING'
$Status = if ($ValidateOnly -and -not $UvExe) {
    'BLOCKED'
}
elseif ($ValidateOnly -and $AllArtifactsReady) {
    'VALIDATED'
}
elseif ($ValidateOnly) {
    'READY_FOR_INSTALL'
}
else {
    'PREPARED'
}
[pscustomobject]@{
    status = $Status
    workspaceRoot = $WorkspaceRoot
    localConfig = $LocalConfigState
    gitChangesRequiringAudit = @(& $GitExe -C $WorkspaceRoot status --porcelain).Count
    pythonEnvironment = $PythonEnvironment
    frontendDependencies = $FrontendDependencies
    frontendStaticBuild = $FrontendStaticBuild
    legacyBaileysSource = $LegacyBaileysSource
    legacyBaileysActive = $false
    nodeVersion = $NodeVersion
    uv = if ($UvExe) { $UvExe } else { 'MISSING' }
    managedToolState = $ManagedToolState
    cloudflared = $CloudflaredExe
    codexPackage = $CodexPackage.Version.ToString()
    ollamaInstalledOrModified = $false
    modelsDownloaded = $false
} | ConvertTo-Json -Depth 4
