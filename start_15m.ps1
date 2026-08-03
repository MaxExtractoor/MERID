# start_15m.ps1
# PRODUCTION startup script for the MERID 15m lean trading server.
#
# This is the ONLY startup script for the production 15m Kalshi crypto trading system.
# It sets environment variables and starts the FastAPI server.
# Startup is handled exclusively by FastAPI lifespan events in main_15m_lean.py.
#
# Usage (from repo root):
#   .\start_15m.ps1
#
# Optional overrides:
#   .\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2

param(
    [int]$Port = 8011,
    [string]$ServerHost = "127.0.0.1",
    [string]$Profile = "kalshi_crypto_15m_v2"
)

$ErrorActionPreference = "Stop"

# 0. Load .env file to get credentials
$envFile = ".\.env"
if (Test-Path $envFile) {
    Write-Host "[start_15m] Loading environment variables from .env file" -ForegroundColor Cyan
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            # Skip empty values and comments
            if ($name -and $value -and !$name.StartsWith('#')) {
                Set-Item -Path "env:$name" -Value $value
            }
        }
    }
    Write-Host "[start_15m] .env file loaded successfully" -ForegroundColor Green
} else {
    Write-Host "[start_15m] WARNING: .env file not found at $envFile" -ForegroundColor Yellow
}

# 1. Risk profile (loop expects kalshi_crypto_15m_v2)
$env:MERID_PROFILE = $Profile
Write-Host "[start_15m] MERID_PROFILE=$($env:MERID_PROFILE)" -ForegroundColor Cyan

# 2. Enable live trading -- ALL FOUR latches are required:
#    TRADING_ENABLED=true (15m loop startup) AND
#    MERID_PM_TRADING_MODE=live AND MERID_PM_LIVE_ENABLED=true AND MERID_ALLOW_LIVE_TRADES=true
#    Missing any one force-demotes to PAPER (orders simulated, not sent).
#    To run PAPER again, set MERID_PM_TRADING_MODE=paper (or unset live_enabled).
$env:TRADING_ENABLED = "true"
$env:MERID_PM_TRADING_MODE = "live"
$env:MERID_PM_LIVE_ENABLED = "true"
$env:MERID_ALLOW_LIVE_TRADES = "true"
# CRITICAL FIX: Disable net edge filter to allow velocity-based small-edge trades
# The filter was rejecting orders with edge < (fee + buffer), blocking valid signals
$env:MERID_KALSHI_NET_EDGE_FILTER_ENABLED = "false"
Write-Host "[start_15m] *** LIVE TRADING ENABLED - REAL ORDERS WILL BE SENT ***" -ForegroundColor Red
Write-Host "[start_15m] TRADING_ENABLED=$($env:TRADING_ENABLED)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_PM_TRADING_MODE=$($env:MERID_PM_TRADING_MODE)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_PM_LIVE_ENABLED=$($env:MERID_PM_LIVE_ENABLED)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_ALLOW_LIVE_TRADES=$($env:MERID_ALLOW_LIVE_TRADES)" -ForegroundColor Cyan

# 3. Kalshi environment and endpoints (use api.elections.kalshi.com per .env configuration)
# Consolidated to single environment variable: MERID_KALSHI_ENV
$env:MERID_KALSHI_ENV = "prod"  # Unified environment variable (prod=demo, prod=live)
$env:KALSHI_USE_DEMO = "false"  # Explicitly disable demo mode for production safety
# CRITICAL FIX: Use api.elections.kalshi.com endpoints (elections API, not external-api)
# The external-api endpoints do not support elections markets
$env:MERID_KALSHI_HTTP_BASE = "https://api.elections.kalshi.com/trade-api/v2"
$env:MERID_KALSHI_WS_BASE = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# 3.1 Kalshi API credentials (required for live trading)
# These should be set in your .env file or environment
# Credentials are expected to be already set in environment variables
if (-not $env:KALSHI_LIVE_API_KEY_ID) {
    $env:KALSHI_LIVE_API_KEY_ID = $env:KALSHI_API_KEY_ID
}
if (-not $env:KALSHI_LIVE_PRIVATE_KEY_PATH) {
    $env:KALSHI_LIVE_PRIVATE_KEY_PATH = $env:KALSHI_PRIVATE_KEY_PATH
}

Write-Host "[start_15m] MERID_KALSHI_ENV=$($env:MERID_KALSHI_ENV)" -ForegroundColor Cyan
Write-Host "[start_15m] KALSHI_USE_DEMO=$($env:KALSHI_USE_DEMO)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_KALSHI_HTTP_BASE=$($env:MERID_KALSHI_HTTP_BASE)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_KALSHI_WS_BASE=$($env:MERID_KALSHI_WS_BASE)" -ForegroundColor Cyan
if ($env:KALSHI_LIVE_API_KEY_ID) {
    Write-Host "[start_15m] KALSHI_LIVE_API_KEY_ID=$($env:KALSHI_LIVE_API_KEY_ID.Substring(0, [Math]::Min(8, $env:KALSHI_LIVE_API_KEY_ID.Length)))****" -ForegroundColor Cyan
} else {
    Write-Host "[start_15m] KALSHI_LIVE_API_KEY_ID=NOT_SET" -ForegroundColor Yellow
}
Write-Host "[start_15m] KALSHI_LIVE_PRIVATE_KEY_PATH=$($env:KALSHI_LIVE_PRIVATE_KEY_PATH)" -ForegroundColor Cyan

# 4. Enable 15M loop diagnostic logging for debugging
$env:MERID_LOOP_DIAG_FILE = "1"
Write-Host "[start_15m] MERID_LOOP_DIAG_FILE=$($env:MERID_LOOP_DIAG_FILE) - loop diagnostics enabled" -ForegroundColor Cyan

# 5. Enable Phase 1 Profitability Enhancements
$env:MERID_YES_NO_ARBITRAGE_ENABLED = "true"
Write-Host "[start_15m] MERID_YES_NO_ARBITRAGE_ENABLED=$($env:MERID_YES_NO_ARBITRAGE_ENABLED) - YES/NO arbitrage enabled" -ForegroundColor Green

# 6. Risk Management Configuration
# DEPRECATED: Environment variable overrides removed in favor of unified risk management
# All risk limits are now configured in config/risk_limits.yaml (single source of truth)
# UnifiedRiskManager reads from this file and enforces all risk checks
Write-Host "[start_15m] Risk limits configured in config/risk_limits.yaml (UnifiedRiskManager)" -ForegroundColor Cyan

# CRITICAL FIX: Disable deprecated GlobalRiskGuard for kalshi_crypto_15m_v2
# The legacy GlobalRiskGuard uses 0.5% cycle cap which is too restrictive for micro accounts
# The risk envelope provides proper risk management with per-asset caps and drawdown tracking
$env:MERID_DISABLE_SHARED_RISK_GUARD = "true"
Write-Host "[start_15m] MERID_DISABLE_SHARED_RISK_GUARD=$($env:MERID_DISABLE_SHARED_RISK_GUARD) - using risk envelope only" -ForegroundColor Cyan

# 2026-07-16: MAX_CYCLE_RISK_PCT REMOVED (percentage-based allocation PRUNED)
# The $1 global slot allocator (MERID_FIXED_EXPOSURE_CAP_USD, default 1.00) is the
# single source of truth for exposure. GlobalExecutionGuard is deprecated (import-blocked).
Write-Host "[start_15m] Exposure model: fixed `$1 global slot allocator (percentage caps disabled)" -ForegroundColor Cyan

# Market making and correlation tracking are controlled by profile config (kalshi_crypto_15m_v2.yaml)
# These are already enabled in the profile config

# CRITICAL FIX: Event loop policy is now set inside main_15m_lean.py
# This ensures it's set in the same process that runs uvicorn
$env:PYTHONUNBUFFERED = "1"
Write-Host "[start_15m] Event loop policy will be set inside main_15m_lean.py" -ForegroundColor Cyan

Write-Host "[start_15m] Launching server on http://${ServerHost}:${Port}" -ForegroundColor Cyan
Write-Host "[start_15m] Startup is handled by FastAPI lifespan events - no health watcher needed" -ForegroundColor Green
Write-Host "[start_15m] ---- server logs below ----" -ForegroundColor Yellow

# CRITICAL FIX (2026-08-02): Re-enable catalog feed skip - apply_rest_market is blocking
# The catalog feed is hanging during apply_rest_market calls
# This allows the server to start and trade without getting stuck in catalog initialization
$env:MERID_SKIP_CATALOG_FEED = "true"
Write-Host "[start_15m] Skipping catalog feed to prevent startup hang" -ForegroundColor Yellow

# Start the server - FastAPI lifespan will handle startup automatically
# Use --log-level info (less verbose than debug)
# CRITICAL FIX: Remove --log-config to prevent interference with lifespan event
# CRITICAL FIX: Remove --reload after clearing __pycache__ to force fresh import
# CRITICAL FIX: Remove --lifespan on (redundant - app already has lifespan defined)
$env:PYTHONUNBUFFERED = "1"
$ErrorActionPreference = "Continue"
& py -m uvicorn web.main_15m_lean:app --host $ServerHost --port $Port --log-level info
