[CmdletBinding()]
param(
    [UInt64]$MinimumFreeBytes = 5368709120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathValue {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$expectedRoot = Normalize-PathValue (Join-Path $scriptDirectory '..\..')
$environmentRoot = $env:OPENJARVIS_WORKSPACE_ROOT
$workspaceRoot = if ([string]::IsNullOrWhiteSpace($environmentRoot)) {
    $expectedRoot
} else {
    Normalize-PathValue $environmentRoot
}
if ($workspaceRoot -ne $expectedRoot) {
    throw "Wrong workspace: expected $expectedRoot but resolved $workspaceRoot."
}

$driveLetter = $workspaceRoot.Substring(0, 1)
$drive = Get-PSDrive -Name $driveLetter -ErrorAction Stop
$freeBytes = [UInt64]$drive.Free
$usedBytes = [UInt64]$drive.Used
$totalBytes = $freeBytes + $usedBytes
if ($freeBytes -lt $MinimumFreeBytes) {
    throw "Disk guard failed: $($drive.Name): has $freeBytes free bytes; minimum is $MinimumFreeBytes."
}

[pscustomobject]@{
    readOnly = $true
    workspaceRoot = $workspaceRoot
    drive = "$($drive.Name):"
    totalBytes = $totalBytes
    freeBytes = $freeBytes
    minimumFreeBytes = $MinimumFreeBytes
    actionTaken = 'NONE'
} | ConvertTo-Json -Depth 4
