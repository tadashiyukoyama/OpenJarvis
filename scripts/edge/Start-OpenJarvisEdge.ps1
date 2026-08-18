[CmdletBinding()]
param(
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [string]$EnvironmentFile = 'D:\dev\runtime\openjarvis\private\edge-worker.env',
    [string]$LogFile = 'D:\dev\runtime\openjarvis\logs\edge-worker.log'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'OpenJarvisEnvironment.psm1') -Force
Import-OpenJarvisEnvironment -LiteralPath $EnvironmentFile
$python = Join-Path $Repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenJarvis virtual environment is unavailable.'
}
$logDirectory = Split-Path -Parent $LogFile
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
[Environment]::SetEnvironmentVariable('OPENJARVIS_EDGE_LOG_FILE', $LogFile, 'Process')
Set-Location -LiteralPath $Repository
& $python -m openjarvis.edge_worker.main --log-level INFO
exit $LASTEXITCODE
