[CmdletBinding()]
param(
    [string]$Repository = 'F:\OpenJarvis',
    [string]$EnvironmentFile = 'F:\OpenJarvis\credenciais\runtime\edge-worker.env',
    [string]$LogFile = 'F:\OpenJarvis\runtime\logs\edge-worker.log'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'OpenJarvisEnvironment.psm1') -Force
Import-OpenJarvisEnvironment -LiteralPath $EnvironmentFile
$runtimeRoot = Join-Path $Repository 'runtime'
[Environment]::SetEnvironmentVariable(
    'OPENJARVIS_WORKSPACE_ROOT', $Repository, 'Process'
)
[Environment]::SetEnvironmentVariable(
    'OPENJARVIS_RUNTIME_ROOT', $runtimeRoot, 'Process'
)
[Environment]::SetEnvironmentVariable(
    'OPENJARVIS_EDGE_PROJECT_ROOTS', $Repository, 'Process'
)
$python = Join-Path $Repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenJarvis virtual environment is unavailable.'
}
$logDirectory = Split-Path -Parent $LogFile
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
[Environment]::SetEnvironmentVariable('OPENJARVIS_EDGE_LOG_FILE', $LogFile, 'Process')
Set-Location -LiteralPath $Repository
$process = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'openjarvis.edge_worker.main', '--log-level', 'INFO') `
    -WorkingDirectory $Repository -WindowStyle Hidden -Wait -PassThru
exit $process.ExitCode
