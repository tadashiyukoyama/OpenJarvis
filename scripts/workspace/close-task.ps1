[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$TaskName
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $scriptDirectory '..\..')).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot '.git') -PathType Container)) {
    throw "Task close refused: canonical Git root is not established at $workspaceRoot."
}

throw "OJ0 safety gate: task closing and cleanup are deferred until a later authorized phase."
