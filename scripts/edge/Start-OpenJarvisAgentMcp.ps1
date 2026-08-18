[CmdletBinding()]
param(
    [string]$Repository = 'D:\dev\workspaces\openjarvis',
    [string]$EnvironmentFile = 'D:\dev\runtime\openjarvis\private\agent-mcp.env'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'OpenJarvisEnvironment.psm1') -Force
Import-OpenJarvisEnvironment -LiteralPath $EnvironmentFile
$python = Join-Path $Repository '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenJarvis virtual environment is unavailable.'
}
Set-Location -LiteralPath $Repository
& $python -m openjarvis.mcp.agent_stdio
exit $LASTEXITCODE
