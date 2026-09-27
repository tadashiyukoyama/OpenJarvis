[CmdletBinding()]
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Uninstall')]
    [string]$Action = 'Status',
    [string]$TaskName = 'OpenJarvis Edge Worker',
    [string]$Repository = 'F:\OpenJarvis'
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $PSScriptRoot 'Start-OpenJarvisEdge.ps1'

switch ($Action) {
    'Install' {
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            throw 'Edge Worker launcher was not found.'
        }
        $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
            throw 'Windows PowerShell executable was not found.'
        }
        $taskAction = New-ScheduledTaskAction -Execute $powerShell -Argument (
            "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass " +
            "-File `"$launcher`" -Repository `"$Repository`""
        )
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
            -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction `
            -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    }
    'Start' { Start-ScheduledTask -TaskName $TaskName }
    'Stop' { Stop-ScheduledTask -TaskName $TaskName }
    'Status' { Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo }
    'Uninstall' {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}
