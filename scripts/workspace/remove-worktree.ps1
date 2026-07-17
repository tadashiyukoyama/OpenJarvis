[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $scriptDirectory '..\..')).TrimEnd('\')
$worktreesRoot = 'D:\dev\worktrees\openjarvis'
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot '.git') -PathType Container)) {
    throw "Worktree removal refused: canonical Git root is not established."
}

$resolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
$prefix = ([IO.Path]::GetFullPath($worktreesRoot)).TrimEnd('\') + '\'
if (-not $resolvedPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Worktree removal refused: path must be under $worktreesRoot."
}

if ($PSCmdlet.ShouldProcess($resolvedPath, 'git worktree remove')) {
    & git -C $workspaceRoot worktree remove $resolvedPath
    if ($LASTEXITCODE -ne 0) {
        throw "git worktree remove failed with exit code $LASTEXITCODE."
    }
    & git -C $workspaceRoot worktree prune
}
