# MERID Trading Server Startup Script (PowerShell)
# Usage: .\supervisor\start-merid.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MERID Trading Server - SRE Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Safety-first: Force paper mode
$env:MERID_VALIDATION_MODE = "1"
$env:MERID_TRADING_MODE = "paper"
$env:MERID_PM_TRADING_MODE = "paper"
$env:MERID_LIVE_TRADING_UNLOCKED = "false"
$env:MERID_ALLOW_LIVE_TRADES = "false"
$env:KALSHI_ENV = "demo"
$env:MERID_HTTP_PORT = "8012"
$env:MERID_API_BASE_URL = "http://127.0.0.1:8012"
$env:MERID_LOG_LEVEL = "INFO"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Mode: VALIDATION + PAPER (SAFE)"
Write-Host "  Port: 8012"
Write-Host "  Kalshi: demo"
Write-Host "  Logs: logs/merid-server.log"
Write-Host ""

# Check for port conflicts
$portInUse = Get-NetTCPConnection -LocalPort 8012 -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Warning "Port 8012 is already in use! Killing existing process..."
    Get-NetTCPConnection -LocalPort 8012 | ForEach-Object { 
        try { Stop-Process -Id $_.OwningProcess -Force } catch {} 
    }
    Start-Sleep 2
}

# Ensure log directory exists
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

Write-Host "Starting MERID server..." -ForegroundColor Green

# Start uvicorn with logging
uvicorn web.main:create_app `
    --factory `
    --host 0.0.0.0 `
    --port 8012 `
    --log-level info `
    2>&1 | Tee-Object logs/merid-server.log

Write-Host "Server exited" -ForegroundColor Red
