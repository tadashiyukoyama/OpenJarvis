[CmdletBinding()]
param(
    [ValidateSet('Install', 'Start', 'Stop', 'Status', 'Uninstall')]
    [string]$Action = 'Status',
    [string]$TaskName = 'OpenJarvis Edge Worker',
    [string]$Repository = 'D:\dev\workspaces\openjarvis'
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Repository 'scripts\edge\Start-OpenJarvisEdge.ps1'

switch ($Action) {
    'Install' {
        if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
            throw 'Edge Worker launcher was not found.'
        }
        $taskAction = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument (
            "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$launcher`""
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
