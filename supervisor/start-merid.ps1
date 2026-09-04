# MERID Trading Server Startup Script (PowerShell)
# Usage: .\supervisor\start-merid.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MERID Trading Server - SRE Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Safety-first: Force paper mode
# REMOVED: MERID_VALIDATION_MODE=1 to enable WebSocket bridge for live orderbook data
$env:MERID_TRADING_MODE = "paper"
$env:MERID_PM_TRADING_MODE = "paper"
$env:MERID_LIVE_TRADING_UNLOCKED = "false"
$env:MERID_ALLOW_LIVE_TRADES = "false"
# CANARY: this is a debug/paper restart of a working tree with uncommitted
# live-money-path changes.  Remove this line before promoting to live.
$env:MERID_ALLOW_DIRTY_TREE = "1"
# Do not override KALSHI_ENV here; the canonical source is .env (MERID_KALSHI_ENV).
$env:MERID_HTTP_PORT = "8011"
$env:MERID_API_BASE_URL = "http://127.0.0.1:8011"
$env:MERID_LOG_LEVEL = "INFO"

# Risk Management Configuration (Optimized Regime 2026-05-07)
$env:MAX_CYCLE_RISK_PCT = "0.06"  # 6% per cycle (increased to allow multi-asset trading)
$env:MAX_TOTAL_RISK_PCT = "0.08"  # 8% total max (was 5%)
$env:SCALPER_SINGLE_BATCH_MODE = "false"  # Allow multi-batch (was true)
$env:SCALPER_MAX_TRADES_PER_BATCH = "5"  # Increased from 3

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Mode: PAPER (WS ENABLED)"
Write-Host "  Port: 8011"
Write-Host "  Kalshi: demo"
Write-Host "  Logs: logs/merid-server.log"
Write-Host ""

# Check for port conflicts
$portInUse = Get-NetTCPConnection -LocalPort 8011 -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Warning "Port 8011 is already in use! Killing existing process..."
    Get-NetTCPConnection -LocalPort 8011 | ForEach-Object { 
        try { Stop-Process -Id $_.OwningProcess -Force } catch {} 
    }
    Start-Sleep 2
}

# Ensure log directory exists
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

Write-Host "Starting MERID server..." -ForegroundColor Green

# Prefer the project virtualenv uvicorn and do not terminate on stderr chatter.
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "py" }
$ErrorActionPreference = "Continue"

& $python -m uvicorn web.main_15m_lean:app `
    --host 0.0.0.0 `
    --port 8011 `
    --log-level info `
    *> logs/merid-server.log

Write-Host "Server exited" -ForegroundColor Red
