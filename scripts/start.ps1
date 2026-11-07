param([switch]$NoBrowser, [switch]$SkipAdmin)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) {
        $failure = $LASTEXITCODE
        Write-Host 'Startup diagnostics (database and migration logs):'
        & docker compose logs --no-color --tail 60 db migrate
        throw "Docker command failed (exit $failure). See container logs above."
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Install Docker Desktop, select Linux containers, then run this file again.'
}
Invoke-Docker info --format '{{.OSType}}'
Invoke-Docker compose version
& (Join-Path $PSScriptRoot 'create_env.ps1')
Invoke-Docker compose config --quiet
Invoke-Docker compose up -d --wait db
Write-Host 'Synchronizing the application database role with .env (existing data is preserved).'
Invoke-Docker compose exec -T db sh /docker-entrypoint-initdb.d/10-app.sh
Invoke-Docker compose up --build -d --wait app
if ($SkipAdmin) {
    Invoke-Docker compose exec -T app python manage.py bootstrap_postgres --load-if-empty
} else {
    Invoke-Docker compose exec app python manage.py bootstrap_postgres --load-if-empty --create-admin
}
$port = '8000'
foreach ($line in [IO.File]::ReadAllLines((Join-Path (Get-Location) '.env'))) {
    if ($line -match '^APP_PORT=(\d+)\s*$') { $port = $Matches[1] }
}
$url = "http://127.0.0.1:$port/"
Write-Host "Ready: $url"
if (-not $NoBrowser) { Start-Process $url }
