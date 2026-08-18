[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'remote-access-common.ps1')

$Context = Get-OpenJarvisRemoteContext -ScriptRoot $PSScriptRoot
if (-not (Test-Path -LiteralPath $Context.StateFile -PathType Leaf)) {
    [pscustomobject]@{ status = 'NOT_RUNNING'; actionTaken = 'NONE' } |
        ConvertTo-Json
    return
}
$State = Get-Content -LiteralPath $Context.StateFile -Raw | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath([string]$State.workspaceRoot).TrimEnd('\') -ne $Context.WorkspaceRoot) {
    throw 'Remote-access state belongs to another workspace; no process was modified.'
}

$Expected = @(
    [pscustomobject]@{
        Name = 'Cloudflare tunnel'
        ProcessId = [int]$State.tunnelPid
        Patterns = @('cloudflared', "127.0.0.1:$([int]$State.gatewayPort)")
    },
    [pscustomobject]@{
        Name = 'OpenJarvis gateway'
        ProcessId = [int]$State.gatewayPid
        Patterns = @('openjarvis.server.remote_access', "--port $([int]$State.gatewayPort)")
    }
)

foreach ($Entry in $Expected) {
    $Process = Get-Process -Id $Entry.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $Process) { continue }
    if (-not (Test-OpenJarvisExpectedProcess -ProcessId $Entry.ProcessId -ExpectedPatterns $Entry.Patterns)) {
        throw "$($Entry.Name) PID no longer matches the recorded command; no process was modified."
    }
}
foreach ($Entry in $Expected) {
    $Process = Get-Process -Id $Entry.ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $Process) { continue }
    Stop-Process -Id $Entry.ProcessId
    Wait-Process -Id $Entry.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    if (Get-Process -Id $Entry.ProcessId -ErrorAction SilentlyContinue) {
        throw "$($Entry.Name) did not stop cleanly; forced termination was not attempted."
    }
}

foreach ($ManagedOutput in @($Context.StateFile, $Context.PublicUrlFile, $Context.QrCodeFile)) {
    $Resolved = [System.IO.Path]::GetFullPath($ManagedOutput)
    if (-not $Resolved.StartsWith($Context.CloudflareRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refused to remove output outside the managed Cloudflare runtime: $Resolved"
    }
    if (Test-Path -LiteralPath $Resolved) { Remove-Item -LiteralPath $Resolved }
}

[pscustomobject]@{
    status = 'STOPPED'
    gatewayPid = [int]$State.gatewayPid
    tunnelPid = [int]$State.tunnelPid
    logsPreserved = $true
} | ConvertTo-Json -Depth 3
