# dev_kalshi_only.ps1 — Launch a minimal local dev instance in kalshi-only profile.
#
# Usage:
#   .\scripts\dev_kalshi_only.ps1              # paper mode (default)
#   .\scripts\dev_kalshi_only.ps1 -Live        # live mode (requires credentials)
#   .\scripts\dev_kalshi_only.ps1 -FreshStart  # reset all state
#
# This mirrors prod as closely as possible:
#   - Only Kalshi routers are registered (no mining, institutional, DeFi, etc.)
#   - Stub/missing_endpoints routers are suppressed
#   - Minimal dependency surface — no Neo4j, Redis, or external feeds required

param(
    [switch]$Live,
    [switch]$FreshStart,
    [int]$Port = 8011
)

$env:MERID_PROFILE = "kalshi-only"
$env:MERID_ENV = "development"

if ($FreshStart) {
    $env:MERID_FRESH_START = "1"
    Write-Host "[dev] Fresh start enabled — paper state will be cleared" -ForegroundColor Yellow
} else {
    Remove-Item Env:\MERID_FRESH_START -ErrorAction SilentlyContinue
}

if ($Live) {
    $env:MERID_PM_TRADING_MODE = "live"
    Write-Host "[dev] LIVE mode — real orders will be placed" -ForegroundColor Red
} else {
    $env:MERID_PM_TRADING_MODE = "paper"
    Write-Host "[dev] Paper mode — no real orders" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MERID kalshi-only dev instance"        -ForegroundColor Cyan
Write-Host "  Profile:  $env:MERID_PROFILE"          -ForegroundColor Cyan
Write-Host "  Mode:     $env:MERID_PM_TRADING_MODE"  -ForegroundColor Cyan
Write-Host "  Port:     $Port"                       -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Run structural tests first as a pre-flight
Write-Host "[pre-flight] Running structural tests..." -ForegroundColor DarkGray
py -m pytest tests/test_kalshi_only_profile.py tests/test_openapi_schema_sanity.py -q --timeout=30 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[pre-flight] FAILED — structural tests did not pass" -ForegroundColor Red
    Write-Host "Fix the failures before starting the dev server." -ForegroundColor Red
    exit 1
}
Write-Host "[pre-flight] OK" -ForegroundColor Green
Write-Host ""

# Start the server
py -m uvicorn web.main:app --host 0.0.0.0 --port $Port --reload
