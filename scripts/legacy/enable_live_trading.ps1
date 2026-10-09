#!/usr/bin/env powershell
# Live Trading Setup Script for MERID
# This script enables live trading mode for Kalshi PM

Write-Host "🔧 Setting environment variables for LIVE trading..." -ForegroundColor Green

# Set required environment variables for live trading
[Environment]::SetEnvironmentVariable("MERID_PM_TRADING_MODE", "live", "User")
[Environment]::SetEnvironmentVariable("MERID_PM_LIVE_ENABLED", "true", "User")
[Environment]::SetEnvironmentVariable("MERID_ALLOW_LIVE_TRADES", "true", "User")
[Environment]::SetEnvironmentVariable("MERID_PM_PHANTOM_GATE_ENABLED", "false", "User")
[Environment]::SetEnvironmentVariable("MERID_KALSHI_MAX_WS_SUBS", "150", "User")
[Environment]::SetEnvironmentVariable("MERID_KALSHI_WS_CRITICAL", "120", "User")

Write-Host "✅ Environment variables set successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Current Settings:" -ForegroundColor Cyan
Get-ChildItem Env: | Where-Object {$_.Name -like "MERID_*"} | Format-Table Name, Value

Write-Host ""
Write-Host "⚠️  IMPORTANT: Restart your trading application now to apply these settings." -ForegroundColor Yellow
Write-Host ""
Read-Host -Prompt "Press Enter to exit"
