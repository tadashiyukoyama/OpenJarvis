[CmdletBinding()]
param([int]$DelaySeconds = 3)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop
$ExpectedRoot = [System.IO.Path]::GetFullPath($Package.InstallLocation)
$Processes = @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue)
foreach ($Process in $Processes) {
    $Path = [System.IO.Path]::GetFullPath($Process.Path)
    if (-not $Path.StartsWith($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected ChatGPT process path; restart was cancelled"
    }
}

Start-Sleep -Seconds $DelaySeconds
foreach ($Process in $Processes | Where-Object MainWindowHandle -ne 0) {
    [void]$Process.CloseMainWindow()
}

$Deadline = [DateTime]::UtcNow.AddSeconds(15)
while ((Get-Process -Name ChatGPT -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $Deadline) {
    Start-Sleep -Milliseconds 250
}

$Remaining = @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue)
foreach ($Process in $Remaining) {
    $Path = [System.IO.Path]::GetFullPath($Process.Path)
    if (-not $Path.StartsWith($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected remaining ChatGPT process path; forced stop was cancelled"
    }
}
if ($Remaining.Count -gt 0) {
    $Remaining | Stop-Process -Force
    Wait-Process -Id $Remaining.Id -Timeout 10 -ErrorAction SilentlyContinue
}

& (Join-Path $PSScriptRoot 'start-codex-live.ps1')
