[CmdletBinding()]
param(
    [string]$WorkspaceRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-PathValue {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [IO.Path]::GetFullPath($PathValue).TrimEnd('\')
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Run-Test {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    try {
        & $Action
        $script:Passed++
        Write-Output "PASS: $Name"
    } catch {
        $script:Failed++
        Write-Output "FAIL: $Name :: $($_.Exception.Message)"
    }
}

function Invoke-PowerShellScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Arguments = @()
    )
    $argumentList = @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $Path
    ) + $Arguments
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& powershell.exe @argumentList 2>&1 | ForEach-Object { [string]$_ })
        $exitCode = [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Invoke-PowerShellCommand {
    param([Parameter(Mandatory = $true)][string]$Command)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(
            & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $Command 2>&1 |
                ForEach-Object { [string]$_ }
        )
        $exitCode = [int]$LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    [pscustomobject]@{
        Output = $output
        ExitCode = $exitCode
    }
}

$script:Passed = 0
$script:Failed = 0
$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$derivedRoot = Normalize-PathValue (Join-Path $scriptDirectory '..\..\..')
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
    $WorkspaceRoot = $derivedRoot
}
$WorkspaceRoot = Normalize-PathValue $WorkspaceRoot
Assert-True ($WorkspaceRoot -eq $derivedRoot) 'Tests must run against the canonical D workspace.'

$scriptsRoot = Join-Path $WorkspaceRoot 'scripts\workspace'
$rehydrate = Join-Path $scriptsRoot 'rehydrate-project.ps1'
$diskGuard = Join-Path $scriptsRoot 'disk-guard.ps1'
$boundaryValidator = Join-Path $scriptsRoot 'validate-local-boundaries.ps1'
$newTask = Join-Path $scriptsRoot 'new-task.ps1'
$manifestPath = Join-Path $WorkspaceRoot '.workspace\local\bootstrap-manifest.json'

Run-Test 'all JSON files parse' {
    $foundationManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $jsonFiles = @(
        $foundationManifest.files |
            Where-Object { [string]$_.path -match '\.json$' } |
            ForEach-Object { Get-Item -LiteralPath (Join-Path $WorkspaceRoot ([string]$_.path).Replace('/','\')) }
    )
    $jsonFiles += Get-Item -LiteralPath $manifestPath
    Assert-True ($jsonFiles.Count -gt 0) 'No JSON files found.'
    foreach ($jsonFile in $jsonFiles) {
        $null = Get-Content -LiteralPath $jsonFile.FullName -Raw | ConvertFrom-Json
    }
}

Run-Test 'schemas and local instances satisfy required shape' {
    $schemaFiles = @(Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot '.workspace\schemas') -File -Filter '*.json')
    Assert-True ($schemaFiles.Count -eq 4) 'Expected four schema files.'
    foreach ($schemaFile in $schemaFiles) {
        $schema = Get-Content -LiteralPath $schemaFile.FullName -Raw | ConvertFrom-Json
        Assert-True ($schema.type -eq 'object') "Schema type is not object: $($schemaFile.Name)"
        Assert-True ($schema.required.Count -gt 0) "Schema has no required fields: $($schemaFile.Name)"
    }
    $localSchema = Get-Content -LiteralPath (Join-Path $WorkspaceRoot '.workspace\schemas\project-local.schema.json') -Raw | ConvertFrom-Json
    $local = Get-Content -LiteralPath (Join-Path $WorkspaceRoot '.workspace\local\project.local.json') -Raw | ConvertFrom-Json
    foreach ($field in @($localSchema.required)) {
        Assert-True ($null -ne $local.PSObject.Properties[$field]) "Local field missing: $field"
    }
    Assert-True ([string]$local.workspaceRoot -match '^D:\\') 'Local workspace root is not on D.'
    $ledger = Get-Content -LiteralPath (Join-Path $WorkspaceRoot '.workspace\local\worktrees.local.json') -Raw | ConvertFrom-Json
    Assert-True ($ledger.worktrees.Count -eq 0) 'Initial worktree ledger is not empty.'
    Assert-True ($ledger.worktrees.Count -le 2) 'Worktree ledger exceeds the allowed maximum.'
}

Run-Test 'all PowerShell files have valid syntax' {
    $psFiles = @(Get-ChildItem -LiteralPath $scriptsRoot -Force -Recurse -File -Filter '*.ps1')
    Assert-True ($psFiles.Count -ge 10) 'Expected workspace scripts were not found.'
    foreach ($psFile in $psFiles) {
        $tokens = $null
        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $psFile.FullName,
            [ref]$tokens,
            [ref]$errors
        )
        Assert-True ($errors.Count -eq 0) "PowerShell parse errors in $($psFile.FullName)"
    }
}

Run-Test 'user environment variable is present in a new PowerShell' {
    $newProcess = Invoke-PowerShellCommand "[Environment]::GetEnvironmentVariable('OPENJARVIS_WORKSPACE_ROOT','User')"
    Assert-True ($newProcess.ExitCode -eq 0) 'New PowerShell did not exit successfully.'
    Assert-True (($newProcess.Output -join '').Trim() -eq $WorkspaceRoot) 'User variable has the wrong value.'
}

Run-Test 'rehydration succeeds with environment variable' {
    $result = Invoke-PowerShellScript -Path $rehydrate
    Assert-True ($result.ExitCode -eq 0) ($result.Output -join [Environment]::NewLine)
    Assert-True (($result.Output -join [Environment]::NewLine) -match 'VALID') 'Rehydration did not report a valid portable identity.'
}

Run-Test 'rehydration succeeds without process environment variable' {
    $quotedScript = $rehydrate.Replace([string][char]39, ([string][char]39) + [string][char]39)
    $command = '$env:OPENJARVIS_WORKSPACE_ROOT = $null; & ' + [char]39 + $quotedScript + [char]39 + '; exit $LASTEXITCODE'
    $result = Invoke-PowerShellCommand $command
    Assert-True ($result.ExitCode -eq 0) ($result.Output -join [Environment]::NewLine)
}

Run-Test 'rehydration fails safely with incorrect projectId' {
    $invalidPortable = Join-Path $WorkspaceRoot '.workspace\local\audit\OJ0-invalid-project-portable.json'
    $result = Invoke-PowerShellScript -Path $rehydrate -Arguments @('-PortablePath', $invalidPortable)
    Assert-True ($result.ExitCode -ne 0) 'Invalid projectId was accepted.'
}

Run-Test 'disk guard is read-only' {
    $before = @(Get-ChildItem -LiteralPath $WorkspaceRoot -Force -Recurse | ForEach-Object { $_.FullName })
    $result = Invoke-PowerShellScript -Path $diskGuard
    $after = @(Get-ChildItem -LiteralPath $WorkspaceRoot -Force -Recurse | ForEach-Object { $_.FullName })
    Assert-True ($result.ExitCode -eq 0) ($result.Output -join [Environment]::NewLine)
    $difference = Compare-Object -ReferenceObject $before -DifferenceObject $after
    Assert-True ($null -eq $difference) 'Disk guard changed workspace entries.'
}

Run-Test 'local boundary validator passes' {
    $result = Invoke-PowerShellScript -Path $boundaryValidator
    Assert-True ($result.ExitCode -eq 0) ($result.Output -join [Environment]::NewLine)
    Assert-True (($result.Output -join [Environment]::NewLine) -match '"valid"\s*:\s*true') 'Boundary validator did not report valid.'
}

Run-Test 'new-task remains gated during OJ1' {
    $result = Invoke-PowerShellScript -Path $newTask -Arguments @('-TaskName', 'oj0-test')
    Assert-True ($result.ExitCode -ne 0) 'new-task did not refuse without canonical Git.'
    Assert-True (($result.Output -join [Environment]::NewLine) -match '(?i)refused|deferred') 'new-task safety refusal was not explicit.'
}

Run-Test 'bootstrap manifest hashes are valid' {
    Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) 'Bootstrap manifest is missing.'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    Assert-True ($manifest.schemaVersion -eq 1) 'Unexpected bootstrap manifest version.'
    Assert-True ([string]$manifest.workspaceRoot -eq $WorkspaceRoot) 'Manifest workspace root is wrong.'
    Assert-True ($manifest.files.Count -gt 0) 'Bootstrap manifest has no files.'
    foreach ($entry in @($manifest.files)) {
        Assert-True ($entry.path -notmatch '^[A-Za-z]:') "Manifest path is not relative: $($entry.path)"
        Assert-True ($entry.sha256 -match '^[A-Fa-f0-9]{64}$') "Invalid hash: $($entry.path)"
        Assert-True ($entry.classification -in @('portable', 'local')) "Invalid classification: $($entry.path)"
        $filePath = Join-Path $WorkspaceRoot $entry.path
        Assert-True (Test-Path -LiteralPath $filePath -PathType Leaf) "Manifest file missing: $($entry.path)"
        $file = Get-Item -LiteralPath $filePath
        $hash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash
        Assert-True ([int64]$file.Length -eq [int64]$entry.sizeBytes) "Size mismatch: $($entry.path)"
        Assert-True ($hash -eq $entry.sha256) "Hash mismatch: $($entry.path)"
    }
}

Run-Test 'official source state is coherent without execution' {
    Assert-True (Test-Path -LiteralPath (Join-Path $WorkspaceRoot '.git')) 'Canonical Git root is missing after promotion.'
    $state = Get-Content -LiteralPath (Join-Path $WorkspaceRoot 'docs\project\CURRENT-PROJECT-STATE.md') -Raw
    Assert-True ($state -match 'officialCodeDownloaded \| true') 'State does not prove official source is checked out.'
    Assert-True ($state -match 'originMainSha \| [0-9a-f]{40}') 'State lacks the live origin SHA.'
    Assert-True ($state -match 'upstreamMainSha \| [0-9a-f]{40}') 'State lacks the live upstream SHA.'
}

Run-Test 'credentials were not opened or copied into project' {
    $privateFiles = @(Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot '.private') -Force -Recurse -File)
    Assert-True ($privateFiles.Count -eq 0) 'Private project directories are not empty.'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $WorkspaceRoot '.codex'))) 'Project created a .codex directory.'
}

Run-Test 'no worktree was created' {
    Assert-True (Test-Path -LiteralPath (Join-Path $WorkspaceRoot '.git')) 'Canonical Git root is missing.'
    Assert-True (-not (Test-Path -LiteralPath 'D:\dev\worktrees\openjarvis')) 'External worktree root exists unexpectedly.'
    $ledger = Get-Content -LiteralPath (Join-Path $WorkspaceRoot '.workspace\local\worktrees.local.json') -Raw | ConvertFrom-Json
    Assert-True ($ledger.worktrees.Count -eq 0) 'Worktree ledger is not empty.'
    $worktreeLines = @(& git -C $WorkspaceRoot worktree list --porcelain 2>$null)
    $worktreeRoots = @($worktreeLines | Where-Object { [string]$_ -match '^worktree ' })
    Assert-True ($worktreeRoots.Count -eq 1) 'Expected exactly one canonical worktree.'
}

Run-Test 'project-managed files are on D and preexisting items remain' {
    $allItems = @(Get-ChildItem -LiteralPath $WorkspaceRoot -Force -Recurse)
    foreach ($item in $allItems) {
        Assert-True ($item.FullName -match '^[Dd]:\\') "Project item is outside D: $($item.FullName)"
    }
    $preflight = Get-Content -LiteralPath (Join-Path $WorkspaceRoot '.workspace\local\audit\OJ0-preflight-2026-07-17.md') -Raw
    Assert-True ($preflight -match 'Top-level items before OJ0: none') 'Preflight preservation evidence is missing.'
}

Write-Output "SUMMARY: Passed=$script:Passed Failed=$script:Failed"
if ($script:Failed -gt 0) {
    exit 1
}
exit 0
