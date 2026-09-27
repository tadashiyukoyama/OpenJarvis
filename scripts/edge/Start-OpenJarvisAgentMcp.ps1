[CmdletBinding()]
param(
    [string]$Repository = 'F:\OpenJarvis',
    [string]$EnvironmentFile = 'F:\OpenJarvis\credenciais\runtime\agent-mcp.env'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'OpenJarvisEnvironment.psm1') -Force
Import-OpenJarvisEnvironment -LiteralPath $EnvironmentFile
[Environment]::SetEnvironmentVariable(
    'OPENJARVIS_WORKSPACE_ROOT', $Repository, 'Process'
)
[Environment]::SetEnvironmentVariable(
    'OPENJARVIS_RUNTIME_ROOT', (Join-Path $Repository 'runtime'), 'Process'
)
$python = Join-Path $Repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenJarvis virtual environment is unavailable.'
}
Set-Location -LiteralPath $Repository
& $python -m openjarvis.mcp.agent_stdio
exit $LASTEXITCODE
