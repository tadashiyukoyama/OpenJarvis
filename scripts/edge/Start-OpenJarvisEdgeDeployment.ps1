[CmdletBinding()]
param(
    [string]$CanonicalRepository = 'F:\OpenJarvis',
    [string]$EnvironmentFile = 'F:\OpenJarvis\credenciais\runtime\edge-worker.env',
    [string]$LogFile = 'F:\OpenJarvis\runtime\logs\edge-worker.log'
)

$ErrorActionPreference = 'Stop'

# The desktop Codex, credentials and runtime state remain in the canonical
# local installation.  Only the worker Python modules come from this checked
# out deployment revision, so a restart cannot silently fall back to an older
# catalog implementation.
$canonicalModule = Join-Path $CanonicalRepository 'scripts\edge\OpenJarvisEnvironment.psm1'
Import-Module $canonicalModule -Force
Import-OpenJarvisEnvironment -LiteralPath $EnvironmentFile

$branchRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $CanonicalRepository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenJarvis virtual environment is unavailable.'
}

$env:OPENJARVIS_WORKSPACE_ROOT = $CanonicalRepository
$env:OPENJARVIS_RUNTIME_ROOT = Join-Path $CanonicalRepository 'runtime'
$env:OPENJARVIS_EDGE_PROJECT_ROOTS = $CanonicalRepository
$env:OPENJARVIS_EDGE_LOG_FILE = $LogFile
$env:PYTHONPATH = Join-Path $branchRoot 'src'

$logDirectory = Split-Path -Parent $LogFile
[System.IO.Directory]::CreateDirectory($logDirectory) | Out-Null
Set-Location -LiteralPath $CanonicalRepository

# Keep the worker in the scheduled-task process.  This lets Task Scheduler's
# restart policy supervise the real process instead of an intermediate child.
& $python -m openjarvis.edge_worker.main --log-level INFO
exit $LASTEXITCODE
