# Compatible with Windows PowerShell 5.1 and PowerShell 7. No Python required.
param([string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
$target = Join-Path $ProjectRoot '.env'
$required = @('DJANGO_SECRET_KEY', 'POSTGRES_ADMIN_PASSWORD', 'POSTGRES_APP_PASSWORD')
if (Test-Path -LiteralPath $target) {
    # Never replace a configured password: a PostgreSQL volume may already use it.
    $text = [IO.File]::ReadAllText($target)
    $existing = $true
} else {
    $text = [IO.File]::ReadAllText((Join-Path $ProjectRoot '.env.example'))
    $existing = $false
}
$text = $text.Replace("`r`n", "`n")
$changed = $false
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    foreach ($key in $required) {
        $pattern = '(?m)^' + $key + '=([^\n]*)$'
        $match = [regex]::Match($text, $pattern)
        if ($match.Success -and $match.Groups[1].Value.Trim() -notin @('', '""', "''")) { continue }
        $bytes = New-Object byte[] 48
        $rng.GetBytes($bytes)
        $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        if ($match.Success) { $text = [regex]::Replace($text, $pattern, "$key=$token") }
        else { $text = $text.TrimEnd("`n") + "`n$key=$token`n" }
        $changed = $true
    }
} finally { $rng.Dispose() }
if (-not $changed) {
    Write-Host '.env already configured; existing secrets preserved.'
    return
}
# CreateNew also protects against concurrent launches overwriting credentials.
$mode = [IO.FileMode]::CreateNew
if ($existing) { $mode = [IO.FileMode]::Truncate }
$stream = [IO.File]::Open($target, $mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($text)
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
Write-Host 'Configured .env; existing secrets preserved. Keep this file for future starts.'
