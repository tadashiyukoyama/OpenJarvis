function Import-OpenJarvisEnvironment {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$LiteralPath)

    $resolved = (Resolve-Path -LiteralPath $LiteralPath -ErrorAction Stop).Path
    foreach ($line in Get-Content -LiteralPath $resolved -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -le 0) { throw "Invalid environment entry in private file." }
        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1)
        if ($name -notmatch '^[A-Z][A-Z0-9_]+$') {
            throw "Invalid environment variable name in private file."
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

Export-ModuleMember -Function Import-OpenJarvisEnvironment
