[CmdletBinding()]
param(
    [int64]$MaximumTrackedFileBytes = 25MB
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $Output = & $script:GitExe -C $script:WorkspaceRoot @Arguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "git $($Arguments -join ' ') exited with code $ExitCode"
    }
    return @($Output)
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if (-not $WorkspaceRoot.StartsWith('F:\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Publication audit must run from the managed F: workspace: $WorkspaceRoot"
}
$GitExe = (Get-Command git.exe -ErrorAction Stop).Source
$GitOutput = & $GitExe -C $WorkspaceRoot rev-parse --show-toplevel
$GitExitCode = $LASTEXITCODE
if ($GitExitCode -ne 0 -or -not $GitOutput) {
    throw 'An audited existing Git repository is required.'
}
$GitRoot = [System.IO.Path]::GetFullPath([string]($GitOutput | Select-Object -First 1)).TrimEnd('\')
if ($GitRoot -ne $WorkspaceRoot) {
    throw "Unexpected Git root: $GitRoot"
}

$TrackedFiles = @(Invoke-Git -Arguments @('ls-files'))
$ReviewedFixtureHashes = @{
    'desktop/src-tauri/binaries/ollama-aarch64-apple-darwin' = '6f632c7a6e46cab5cb22a271bc451cc0baaf68fc3647fa58134dd463fc260b3a'
    'docs/user-guide/security.md' = 'ddfb8b2b4ca769542230142d612ff55140f5442b5079ada9497b68c84a8b2961'
    'rust/crates/openjarvis-security/src/guardrails.rs' = 'c53b479fc74b2cdfa07aaa6b17f196fdae4d5002ade30dde25874786a7bc480a'
    'rust/crates/openjarvis-security/src/scanner.rs' = 'e71c785ede779f54c489349a3d2d46c7a276f62f349eb13251462708032aaf02'
    'rust/crates/openjarvis-security/src/taint.rs' = '973b6a45c35894a73d1b9e71609c291d611b2b21833aa559ef1e3af246ecbc31'
    'src/openjarvis/evals/datasets/security_scanner.py' = 'f2ff9a4d9aaa0b2e74951592437955730aa2804cdd213fc8dc0bcca9524430ef'
    'tests/analytics/test_redaction.py' = '6dccb80180cd01aa677579c8b5202b5735619ae67ca0718aab0fc138c9f7559f'
    'tests/core/test_rust_bridge.py' = '8c8f10f76fae9f97cfc97b097f80b3ac3e358322342c9060c25551594b455104'
    'tests/install/test_bootstrap_keys.py' = '72259cd7d62ccf0429530067977d00ef6cce83acaf7dfdbeb252737fe66ac6cf'
    'tests/security/test_boundary_guard.py' = '6ea31b28dbc231e741714451661d8ccd85936bfef57028b4f0efa14455cd539d'
    'tests/security/test_credential_stripper.py' = '88db1114601dd42eab011aa10bc5f9a20da1efa01992c77441ac2608751cfc33'
    'tests/security/test_guardrails.py' = 'f116443afe60c3ed04b0753d7fc770f96d2c849d1a0e6fcd94906910dea4a0db'
    'tests/security/test_log_sanitization.py' = '794d703aa0110f9bbff751e809132ebb89d0f9eaf3a9fb4abc96448cda9faa9f'
    'tests/security/test_scanner.py' = '037ff583b3d27675b4de9f29e66273ad8287b2dfcc4744c43efde91890610bc5'
    'tests/security/test_taint.py' = '9a019b5007ffab304b7e0d58779925429e47b6e700c3baf544957585e25683c5'
}
$ForbiddenPathPatterns = @(
    '(^|/)credenciais(/|$)',
    '(^|/)\.workspace/local(/|$)',
    '(^|/)\.runtime(/|$)',
    '(^|/)\.artifacts(/|$)',
    '(^|/)\.venv(/|$)',
    '(^|/)node_modules(/|$)',
    '\.(sqlite3?|db|log|pem|key|pfx|p12)$',
    '(^|/)(public-url\.txt|.*-qr\.png)$'
)
$ForbiddenTrackedFiles = @(@(
    foreach ($File in $TrackedFiles) {
        $Normalized = $File.Replace('\', '/')
        if ($ForbiddenPathPatterns | Where-Object { $Normalized -match $_ }) {
            $Normalized
        }
    }
) | Sort-Object -Unique)

$OversizedTrackedFiles = @(
    foreach ($File in $TrackedFiles) {
        $Path = Join-Path $WorkspaceRoot $File
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { continue }
        $Item = Get-Item -LiteralPath $Path
        if ($Item.Length -gt $MaximumTrackedFileBytes) {
            $ReviewedHash = $ReviewedFixtureHashes[$File.Replace('\', '/')]
            $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($ReviewedHash -and $ActualHash -eq $ReviewedHash) { continue }
            [pscustomobject]@{ path = $File; bytes = $Item.Length }
        }
    }
)

$SensitivePatterns = @(
    ('AI' + 'za[0-9A-Za-z_-]{24,}'),
    ('AQ' + '\.[0-9A-Za-z_-]{20,}'),
    ('gh' + '[pousr]_[0-9A-Za-z]{20,}'),
    ('sk' + '-[0-9A-Za-z_-]{20,}'),
    ('GEMINI_LIVE_API_KEY_' + '(PRIMARY|FALLBACK)=[0-9A-Za-z_-]{20,}'),
    ('OJ_GATEWAY_PASSWORD=' + '[0-9A-Za-z!@#$%^&*._-]{20,}'),
    ('-----BEGIN ' + '[A-Z0-9 ]*PRIVATE KEY-----')
)
$SensitiveFiles = @()
foreach ($Pattern in $SensitivePatterns) {
    $Matches = & $GitExe -C $WorkspaceRoot grep -I -l -E -- $Pattern
    $GrepExitCode = $LASTEXITCODE
    if ($GrepExitCode -eq 0) {
        foreach ($Match in @($Matches)) {
            $Normalized = $Match.Replace('\', '/')
            $ReviewedHash = $ReviewedFixtureHashes[$Normalized]
            if ($ReviewedHash) {
                $Path = Join-Path $WorkspaceRoot $Match
                $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($ActualHash -eq $ReviewedHash) { continue }
            }
            $SensitiveFiles += $Normalized
        }
    }
    elseif ($GrepExitCode -ne 1) {
        throw "git grep failed with code $GrepExitCode"
    }
}
$SensitiveFiles = @($SensitiveFiles | Sort-Object -Unique)

$TrackedChanges = @(Invoke-Git -Arguments @('status', '--porcelain', '--untracked-files=no'))
$UntrackedFiles = @(Invoke-Git -Arguments @('ls-files', '--others', '--exclude-standard'))
& $GitExe -C $WorkspaceRoot diff --check
if ($LASTEXITCODE -ne 0) {
    throw 'git diff --check failed.'
}

$Failures = @()
if ($ForbiddenTrackedFiles.Count -gt 0) { $Failures += 'forbidden tracked paths' }
if ($OversizedTrackedFiles.Count -gt 0) { $Failures += 'oversized tracked files' }
if ($SensitiveFiles.Count -gt 0) { $Failures += 'possible sensitive tracked content' }
if ($TrackedChanges.Count -gt 0) { $Failures += 'uncommitted tracked changes' }

[pscustomobject]@{
    status = if ($Failures.Count -eq 0) { 'PASS' } else { 'BLOCKED' }
    branch = (Invoke-Git -Arguments @('branch', '--show-current') | Select-Object -First 1)
    sha = (Invoke-Git -Arguments @('rev-parse', 'HEAD') | Select-Object -First 1)
    trackedFiles = $TrackedFiles.Count
    forbiddenTrackedFiles = $ForbiddenTrackedFiles
    oversizedTrackedFiles = $OversizedTrackedFiles
    possibleSensitiveFiles = $SensitiveFiles
    uncommittedTrackedChanges = $TrackedChanges.Count
    preservedUntrackedFiles = $UntrackedFiles
    failures = $Failures
    githubChanged = $false
} | ConvertTo-Json -Depth 5

if ($Failures.Count -gt 0) { exit 1 }
