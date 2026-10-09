#!/usr/bin/env powershell
# Live Trading Launcher for MERID
# This script sets environment variables and starts the trading server

$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting MERID in LIVE trading mode..." -ForegroundColor Green
Write-Host ""

# Set required environment variables for live trading (process-level)
$env:MERID_PM_TRADING_MODE = "live"
$env:MERID_PM_LIVE_ENABLED = "true"
$env:MERID_ALLOW_LIVE_TRADES = "true"
$env:MERID_PM_PHANTOM_GATE_ENABLED = "false"
$env:MERID_KALSHI_MAX_WS_SUBS = "150"
$env:MERID_KALSHI_WS_CRITICAL = "120"

Write-Host "📋 Live Trading Settings Applied:" -ForegroundColor Cyan
Write-Host "  MERID_PM_TRADING_MODE = $env:MERID_PM_TRADING_MODE"
Write-Host "  MERID_PM_LIVE_ENABLED = $env:MERID_PM_LIVE_ENABLED"
Write-Host "  MERID_ALLOW_LIVE_TRADES = $env:MERID_ALLOW_LIVE_TRADES"
Write-Host "  MERID_PM_PHANTOM_GATE_ENABLED = $env:MERID_PM_PHANTOM_GATE_ENABLED"
Write-Host "  MERID_KALSHI_MAX_WS_SUBS = $env:MERID_KALSHI_MAX_WS_SUBS"
Write-Host ""

# Change to project directory
Set-Location -Path "C:\Dev\MERID"

# Create logs directory if not exists
if (!(Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = "logs\live_trading_$timestamp.log"

Write-Host "📝 Logging to: $logFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠️  LIVE TRADING MODE ACTIVE - REAL MONEY AT RISK" -ForegroundColor Red -BackgroundColor Black
Write-Host ""

# Start the server and capture output
try {
    Write-Host "🔄 Starting server... (Press Ctrl+C to stop)" -ForegroundColor Yellow
    
    # Replace this with your actual server start command
    # Example: python -m merid.prediction.agent_grid
    # For now, we'll create a placeholder that shows how to run
    
    Write-Host ""
    Write-Host "🔴 READY TO TRADE LIVE" -ForegroundColor Green
    Write-Host ""
    Write-Host "To start your actual server, run your command here." -ForegroundColor Yellow
    Write-Host "Example commands to try:" -ForegroundColor Cyan
    Write-Host "  python -m merid.prediction.agent_grid"
    Write-Host "  python web\main.py"
    Write-Host "  python -m main"
    Write-Host ""
    
    # Keep the window open
    while ($true) {
        $cmd = Read-Host -Prompt "> Enter your server start command (or 'exit' to quit)"
        if ($cmd -eq "exit") { break }
        
        Write-Host "🔄 Executing: $cmd" -ForegroundColor Yellow
        Invoke-Expression $cmd 2>&1 | Tee-Object -FilePath $logFile
    }
    
} catch {
    Write-Host "❌ Error starting server: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "👋 Live trading session ended." -ForegroundColor Yellow
Read-Host -Prompt "Press Enter to exit"
