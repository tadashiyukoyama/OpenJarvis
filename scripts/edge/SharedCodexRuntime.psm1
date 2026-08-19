Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'


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
    $localConfig = Get-Content -LiteralPath $localConfigPath -Raw | ConvertFrom-Json
    $runtimeRoot = [System.IO.Path]::GetFullPath([string]$localConfig.runtimeRoot)
    $codexHome = [System.IO.Path]::GetFullPath([string]$localConfig.codexHome)
    foreach ($managedPath in @($repositoryRoot, $runtimeRoot, $codexHome)) {
        if (-not $managedPath.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "OpenJarvis managed paths must remain on disk D: $managedPath"
        }
    }

    $package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop |
        Sort-Object Version -Descending |
        Select-Object -First 1
    $codexExe = Join-Path $package.InstallLocation 'app\resources\codex.exe'
    $desktopExe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    foreach ($executable in @($codexExe, $desktopExe)) {
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            throw 'The installed Codex Desktop package is incomplete.'
        }
    }

    [pscustomobject]@{
        Repository = $repositoryRoot
        RuntimeRoot = $runtimeRoot
        CodexHome = $codexHome
        CodexExe = $codexExe
        DesktopExe = $desktopExe
        Port = $Port
        SharedUrl = "ws://127.0.0.1:$Port"
        HealthUrl = "http://127.0.0.1:$Port/healthz"
        LogDirectory = Join-Path $runtimeRoot 'codex'
        StateDirectory = Join-Path $runtimeRoot 'state'
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
    $commandLine = if ($null -eq $process) { '' } else { [string]$process.CommandLine }
    $executablePath = if ($null -eq $process) { '' } else { [string]$process.ExecutablePath }
    $packagedCodex = $executablePath -match (
        '(?i)\\WindowsApps\\OpenAI\.Codex_[^\\]+\\app\\resources\\codex\.exe$'
    )
    $valid = (
        $null -ne $process -and
        $packagedCodex -and
        $commandLine -like "*$executablePath*" -and
        $commandLine -like "*app-server --listen $($Config.SharedUrl)*"
    )
    [pscustomobject]@{
        ProcessId = [int]$listener.OwningProcess
        CommandLine = $commandLine
        Valid = $valid
    }
}


function Test-OpenJarvisSharedCodexHealth {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Config)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Config.HealthUrl -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    }
    catch {
        return $false
    }
}


function Wait-OpenJarvisSharedCodexHealth {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Config,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-OpenJarvisSharedCodexHealth -Config $Config) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Shared Codex app-server did not become healthy on $($Config.SharedUrl)."
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
        else {
            $stableSince = $null
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'Codex Desktop did not join the shared OpenJarvis app-server.'
}


Export-ModuleMember -Function @(
    'Get-OpenJarvisSharedCodexConfig',
    'Get-OpenJarvisSharedCodexOwner',
    'Test-OpenJarvisSharedCodexHealth',
    'Wait-OpenJarvisSharedCodexHealth',
    'Get-OpenJarvisDesktopCodexTopology',
    'Wait-OpenJarvisDesktopSharedConnection'
)
