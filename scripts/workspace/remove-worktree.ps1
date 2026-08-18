[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $scriptDirectory '..\..')).TrimEnd('\')
$disabledMessage = 'WORKTREE_LIFECYCLE_NOT_ENABLED:' + [Environment]::NewLine + 'o lifecycle de tarefas e worktrees será implementado em uma fase posterior explicitamente autorizada.'
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot '.git') -PathType Container)) {
    throw $disabledMessage
}

throw $disabledMessage
