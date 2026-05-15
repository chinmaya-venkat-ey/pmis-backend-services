# PMIS local-dev bootstrap (Windows PowerShell).
#
# Prereqs:
#   - Postgres running on localhost:5432 with a DB named `pmis`.
#   - Two roles: `pmis_app` (RW on schemas) and `pmis_ddl` (DDL on schemas),
#     both with the password configured in each service's .env.
#   - Python venv per service is set up, with `pip install -r requirements.txt`.
#   - Each service's .env exists (copy from .env.example and edit).
#
# This script:
#   1. Runs migrations/00_create_schemas.sql against the DB (one-shot).
#   2. Runs alembic for masters, users, project in order. notification has
#      no owned tables so its alembic is skipped.
#   3. Tells you the URLs to hit (per-service ports — direct, no nginx).
#
# To start each service interactively after this script runs, open four
# terminals and `uvicorn app.main:app --reload --port <port>` in each.
#
# Usage:
#   cd C:\Programming\PMIS-refactor
#   .\tools\init_local.ps1

param(
    [string]$DbHost = "localhost",
    [string]$DbPort = "5432",
    [string]$DbName = "pmis",
    [string]$DdlUser = "pmis_ddl",
    [string]$DdlPassword = "changeme",
    [switch]$SkipSchemaCreate
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host ""
Write-Host "=== PMIS local bootstrap ===" -ForegroundColor Cyan
Write-Host "Repo root: $repoRoot"
Write-Host "Postgres : $DdlUser@${DbHost}:${DbPort}/$DbName"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1 — schemas
# ---------------------------------------------------------------------------
if (-not $SkipSchemaCreate) {
    Write-Host "[1/3] Creating schemas via migrations/00_create_schemas.sql..." -ForegroundColor Yellow
    $env:PGPASSWORD = $DdlPassword
    & psql -h $DbHost -p $DbPort -U $DdlUser -d $DbName -f (Join-Path $repoRoot "migrations/00_create_schemas.sql")
    if (-not $?) { throw "Schema creation failed" }
    Write-Host "  OK" -ForegroundColor Green
} else {
    Write-Host "[1/3] Skipped (-SkipSchemaCreate)" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# Step 2 — alembic per service (order matters)
# ---------------------------------------------------------------------------
$services = @(
    "pmis-masters-management",
    "pmis-user-management",
    "pmis-project-management"
)

foreach ($svc in $services) {
    Write-Host ""
    Write-Host "[2/3] alembic upgrade head for $svc" -ForegroundColor Yellow
    $svcDir = Join-Path $repoRoot "services\$svc"
    if (-not (Test-Path (Join-Path $svcDir "alembic.ini"))) {
        Write-Host "  No alembic.ini in $svcDir — skipping." -ForegroundColor DarkYellow
        continue
    }
    Push-Location $svcDir
    try {
        & alembic upgrade head
        if (-not $?) { throw "alembic upgrade failed for $svc" }
        Write-Host "  OK" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "[3/3] All migrations applied." -ForegroundColor Green
Write-Host ""
Write-Host "=== Next steps ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Open four terminals and start each service (use --reload during dev):" -ForegroundColor White
Write-Host ""
Write-Host "  Terminal 1:  cd services\pmis-user-management        ; uvicorn app.main:app --reload --port 8000"
Write-Host "  Terminal 2:  cd services\pmis-masters-management     ; uvicorn app.main:app --reload --port 8001"
Write-Host "  Terminal 3:  cd services\pmis-notification-management; uvicorn app.main:app --reload --port 8002"
Write-Host "  Terminal 4:  cd services\pmis-project-management     ; uvicorn app.main:app --reload --port 8003"
Write-Host ""
Write-Host "Then in a browser:" -ForegroundColor White
Write-Host "  http://localhost:8000/docs   — user-svc (auth + RBAC + role-assignments)"
Write-Host "  http://localhost:8001/docs   — masters-svc (catalogs)"
Write-Host "  http://localhost:8002/docs   — notification-svc (dispatch + cron)"
Write-Host "  http://localhost:8003/docs   — project-svc (projects + M/A/T/S + comments + dashboard + tree)"
Write-Host ""
Write-Host "To log in as the bootstrap super_admin:" -ForegroundColor White
Write-Host "  POST http://localhost:8000/user/users/login"
Write-Host "  body: { ""login"": ""superadmin"", ""password"": ""<SUPERADMIN_BOOTSTRAP_PASSWORD from .env>"" }"
Write-Host ""
Write-Host "OTP dev backdoor is on (UNIVERSAL_OTP_ENABLED=true): use 000000 when prompted." -ForegroundColor White
Write-Host ""
