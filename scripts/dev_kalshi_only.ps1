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

# ═══════════════════════════════════════════════════════════════════════════
# RISK MANAGEMENT — TOP-N ALLOCATOR (CRITICAL: prevents oversizing bugs)
# ═══════════════════════════════════════════════════════════════════════════
# When TRUE: Uses TopNEdgeAllocator with 1-2% cycle-wide risk cap + GlobalRiskGuard
# When FALSE: Uses legacy Kelly per-trade sizing (DANGEROUS — can cause oversizing)
# 
# This flag is the primary defense against the 7-BTC-orders-with-28-equity bug.
# Regresssion test: tests/trading/test_risk_oversizing_regression.py
# ═══════════════════════════════════════════════════════════════════════════
$env:USE_TOPN_ALLOCATOR = "true"
$env:MAX_CYCLE_RISK_PCT = "0.03"  # 3% per cycle (was 2%)
$env:MAX_TOTAL_RISK_PCT = "0.08"  # 8% total max (was 5%)
$env:SCALPER_SINGLE_BATCH_MODE = "false"  # Allow multi-batch (was true)
$env:SCALPER_MAX_TRADES_PER_BATCH = "5"  # Increased from 3

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
Write-Host "  RISK CONFIG:"                          -ForegroundColor Green
Write-Host "    USE_TOPN_ALLOCATOR: $env:USE_TOPN_ALLOCATOR"  -ForegroundColor Green
Write-Host "    MAX_CYCLE_RISK_PCT: $env:MAX_CYCLE_RISK_PCT"  -ForegroundColor Green
Write-Host "    MAX_TOTAL_RISK_PCT: $env:MAX_TOTAL_RISK_PCT"  -ForegroundColor Green
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
