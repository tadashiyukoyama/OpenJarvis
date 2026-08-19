Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'SharedCodexProtocol.psm1') -Force


function Get-OpenJarvisFileSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $algorithm.ComputeHash($stream)
        return [System.BitConverter]::ToString($bytes).Replace('-', '')
    }
    finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}


function Resolve-OpenJarvisCodexRuntime {
    [CmdletBinding()]
    param()

    $package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop |
        Sort-Object Version -Descending |
        Select-Object -First 1
    if ($null -eq $package) { throw 'Codex Desktop is not installed.' }

    $packagedCodex = Join-Path $package.InstallLocation 'app\resources\codex.exe'
    $packagedHost = Join-Path `
        $package.InstallLocation 'app\resources\codex-code-mode-host.exe'
    $desktopExe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    foreach ($path in @($packagedCodex, $packagedHost, $desktopExe)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Installed Codex Desktop package is incomplete: $path"
        }
    }

    $codexHash = Get-OpenJarvisFileSha256 -Path $packagedCodex
    $hostHash = Get-OpenJarvisFileSha256 -Path $packagedHost
    $materializedRoot = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    $matches = @(
        Get-ChildItem -LiteralPath $materializedRoot -Directory `
            -ErrorAction SilentlyContinue |
            ForEach-Object {
                $candidateCodex = Join-Path $_.FullName 'codex.exe'
                $candidateHost = Join-Path $_.FullName 'codex-code-mode-host.exe'
                if ((Test-Path -LiteralPath $candidateCodex -PathType Leaf) -and
                    (Test-Path -LiteralPath $candidateHost -PathType Leaf) -and
                    (Get-OpenJarvisFileSha256 -Path $candidateCodex) -eq $codexHash -and
                    (Get-OpenJarvisFileSha256 -Path $candidateHost) -eq $hostHash) {
                    [pscustomobject]@{
                        RuntimeId = $_.Name
                        CodexExe = [System.IO.Path]::GetFullPath($candidateCodex)
                        CodeModeHostExe = [System.IO.Path]::GetFullPath($candidateHost)
                    }
                }
            }
    )
    if ($matches.Count -ne 1) {
        throw (
            'Could not resolve exactly one executable Codex runtime matching ' +
            "the installed Desktop package. Matches: $($matches.Count)."
        )
    }

    [pscustomobject]@{
        PackageVersion = [string]$package.Version
        PackageInstallLocation = [string]$package.InstallLocation
        RuntimeId = $matches[0].RuntimeId
        CodexExe = $matches[0].CodexExe
        CodeModeHostExe = $matches[0].CodeModeHostExe
        CodexSha256 = $codexHash
        CodeModeHostSha256 = $hostHash
        DesktopExe = [System.IO.Path]::GetFullPath($desktopExe)
    }
}


function Get-OpenJarvisSharedCodexConfig {
    [CmdletBinding()]
    param(
        [string]$Repository = 'D:\dev\workspaces\openjarvis',
        [int]$Port = 8131
    )

    $repositoryRoot = [System.IO.Path]::GetFullPath($Repository)
    $localConfigPath = Join-Path $repositoryRoot '.workspace\local\project.local.json'
    if (-not (Test-Path -LiteralPath $localConfigPath -PathType Leaf)) {
        throw "OpenJarvis local configuration was not found: $localConfigPath"
    }
    $localConfig = Get-Content -LiteralPath $localConfigPath -Raw |
        ConvertFrom-Json
    $runtimeRoot = [System.IO.Path]::GetFullPath([string]$localConfig.runtimeRoot)
    $codexHome = [System.IO.Path]::GetFullPath([string]$localConfig.codexHome)
    foreach ($managedPath in @($repositoryRoot, $runtimeRoot, $codexHome)) {
        if (-not $managedPath.StartsWith(
            'D:\', [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "OpenJarvis managed paths must remain on disk D: $managedPath"
        }
    }

    $runtime = Resolve-OpenJarvisCodexRuntime
    [pscustomobject]@{
        Repository = $repositoryRoot
        RuntimeRoot = $runtimeRoot
        CodexHome = $codexHome
        Port = $Port
        SharedUrl = "ws://127.0.0.1:$Port"
        ReadyUrl = "http://127.0.0.1:$Port/readyz"
        HealthUrl = "http://127.0.0.1:$Port/healthz"
        LogDirectory = Join-Path $runtimeRoot 'codex'
        StateDirectory = Join-Path $runtimeRoot 'state'
        StatePath = Join-Path $runtimeRoot 'state\shared-codex-runtime.json'
        RuntimeId = $runtime.RuntimeId
        PackageVersion = $runtime.PackageVersion
        CodexExe = $runtime.CodexExe
        CodeModeHostExe = $runtime.CodeModeHostExe
        CodexSha256 = $runtime.CodexSha256
        CodeModeHostSha256 = $runtime.CodeModeHostSha256
        DesktopExe = $runtime.DesktopExe
    }
}


function Get-OpenJarvisPersistentCodexRedirect {
    [CmdletBinding()]
    param()

    [pscustomobject]@{
        User = [Environment]::GetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', 'User'
        )
        Machine = [Environment]::GetEnvironmentVariable(
            'CODEX_APP_SERVER_WS_URL', 'Machine'
        )
    }
}


function Assert-OpenJarvisNoPersistentCodexRedirect {
    [CmdletBinding()]
    param()

    $redirect = Get-OpenJarvisPersistentCodexRedirect
    if ($null -ne $redirect.User -or $null -ne $redirect.Machine) {
        throw (
            'Persistent CODEX_APP_SERVER_WS_URL is unsafe. Remove the legacy ' +
            'redirect before using opt-in shared mode.'
        )
    }
}


function Get-OpenJarvisDesktopCodexTopology {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Config)

    $desktopIds = @(
        Get-Process -Name ChatGPT -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Id
    )
    $connections = @(
        if ($desktopIds.Count -gt 0) {
            Get-NetTCPConnection -RemotePort $Config.Port -State Established `
                -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -in $desktopIds }
        }
    )
    $privateServers = @(
        if ($desktopIds.Count -gt 0) {
            Get-CimInstance Win32_Process | Where-Object {
                $_.ParentProcessId -in $desktopIds -and
                $_.Name -eq 'codex.exe' -and
                $_.CommandLine -like '*app-server*'
            }
        }
    )
    [pscustomobject]@{
        DesktopRunning = $desktopIds.Count -gt 0
        SharedConnected = $connections.Count -gt 0
        PrivateAppServerCount = $privateServers.Count
        DesktopProcessCount = $desktopIds.Count
    }
}


function Get-OpenJarvisSharedCodexOwner {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Config)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Config.Port `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) { return $null }

    $process = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $($listener.OwningProcess)"
    $commandLine = if ($null -eq $process) { '' } else {
        [string]$process.CommandLine
    }
    $executablePath = if ($null -eq $process) { '' } else {
        [string]$process.ExecutablePath
    }
    $managed = (
        $commandLine -like '*app-server*' -and
        $commandLine -like "*--listen $($Config.SharedUrl)*"
    )
    $runtimeRoot = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    $recognizedRuntime = (
        $executablePath.StartsWith(
            $runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        $executablePath -match (
            '(?i)\\WindowsApps\\OpenAI\.Codex_[^\\]+\\app\\resources\\codex\.exe$'
        )
    )
    $currentRuntime = $executablePath.Equals(
        $Config.CodexExe, [System.StringComparison]::OrdinalIgnoreCase
    )
    [pscustomobject]@{
        ProcessId = [int]$listener.OwningProcess
        ExecutablePath = $executablePath
        CommandLine = $commandLine
        Managed = $managed
        RecognizedRuntime = $recognizedRuntime
        CurrentRuntime = $currentRuntime
        Valid = $null -ne $process -and $managed -and $currentRuntime
    }
}


function Test-OpenJarvisHttpProbe {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Uri)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    }
    catch { return $false }
}


function Get-OpenJarvisSharedCodexReadiness {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Config)

    $owner = Get-OpenJarvisSharedCodexOwner -Config $Config
    $ready = Test-OpenJarvisHttpProbe -Uri $Config.ReadyUrl
    $healthy = Test-OpenJarvisHttpProbe -Uri $Config.HealthUrl
    $protocol = $false
    if ($null -ne $owner -and $owner.Valid -and $ready -and $healthy) {
        $protocol = Test-OpenJarvisSharedCodexProtocol `
            -SharedUrl $Config.SharedUrl
    }
    [pscustomobject]@{
        Owner = $owner
        Ready = $ready
        Healthy = $healthy
        ProtocolInitialized = $protocol
        Valid = (
            $null -ne $owner -and $owner.Valid -and
            $ready -and $healthy -and $protocol
        )
    }
}


function Wait-OpenJarvisSharedCodexReadiness {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Config,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $readiness = Get-OpenJarvisSharedCodexReadiness -Config $Config
        if ($readiness.Valid) { return $readiness }
        Start-Sleep -Milliseconds 250
    }
    throw (
        'Shared Codex app-server failed executable, readyz, healthz or ' +
        "initialize validation on $($Config.SharedUrl)."
    )
}


function Wait-OpenJarvisDesktopSharedConnection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Config,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $stableSince = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $topology = Get-OpenJarvisDesktopCodexTopology -Config $Config
        if ($topology.SharedConnected -and $topology.PrivateAppServerCount -eq 0) {
            if ($null -eq $stableSince) { $stableSince = [DateTime]::UtcNow }
            if (([DateTime]::UtcNow - $stableSince).TotalSeconds -ge 2) {
                return $topology
            }
        }
        else { $stableSince = $null }
        Start-Sleep -Milliseconds 250
    }
    throw 'Codex Desktop did not join the validated shared app-server.'
}


function Stop-OpenJarvisSharedCodexOwner {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)]$Config,
        [switch]$AllowStaleManagedRuntime,
        [switch]$AllowUnsharedDesktopRecovery,
        [switch]$AllowDetachedDesktopRecovery,
        [int]$ExpectedProcessId = 0
    )

    if ($AllowDetachedDesktopRecovery -and $ExpectedProcessId -lt 1) {
        throw 'Detached Desktop recovery requires the expected listener PID.'
    }
    $topology = Get-OpenJarvisDesktopCodexTopology -Config $Config
    if ($topology.DesktopRunning) {
        $unsharedRecovery = (
            $AllowUnsharedDesktopRecovery -and
            -not $topology.SharedConnected -and
            $topology.PrivateAppServerCount -gt 0
        )
        if (-not $unsharedRecovery -and -not $AllowDetachedDesktopRecovery) {
            throw 'Close Codex Desktop normally before stopping a shared runtime.'
        }
    }
    $owner = Get-OpenJarvisSharedCodexOwner -Config $Config
    if ($null -eq $owner) { return }
    if ($ExpectedProcessId -gt 0 -and $owner.ProcessId -ne $ExpectedProcessId) {
        throw 'Shared Codex listener identity changed; nothing was stopped.'
    }
    if (-not $owner.Managed -or -not $owner.RecognizedRuntime) {
        throw "Port $($Config.Port) has an unrelated owner; nothing was stopped."
    }
    if (-not $owner.CurrentRuntime -and -not $AllowStaleManagedRuntime) {
        throw 'A stale managed Codex runtime requires explicit stale cleanup.'
    }
    if ($PSCmdlet.ShouldProcess(
        "PID $($owner.ProcessId)", 'Stop verified shared Codex runtime'
    )) {
        Stop-Process -Id $owner.ProcessId -Force
        $deadline = [DateTime]::UtcNow.AddSeconds(5)
        while ([DateTime]::UtcNow -lt $deadline -and
            (Get-OpenJarvisSharedCodexOwner -Config $Config)) {
            Start-Sleep -Milliseconds 100
        }
        if (Get-OpenJarvisSharedCodexOwner -Config $Config) {
            throw 'Verified shared Codex runtime did not release its port.'
        }
    }
}


Export-ModuleMember -Function @(
    'Resolve-OpenJarvisCodexRuntime',
    'Get-OpenJarvisSharedCodexConfig',
    'Get-OpenJarvisPersistentCodexRedirect',
    'Assert-OpenJarvisNoPersistentCodexRedirect',
    'Get-OpenJarvisDesktopCodexTopology',
    'Get-OpenJarvisSharedCodexOwner',
    'Get-OpenJarvisSharedCodexReadiness',
    'Wait-OpenJarvisSharedCodexReadiness',
    'Wait-OpenJarvisDesktopSharedConnection',
    'Stop-OpenJarvisSharedCodexOwner'
)
