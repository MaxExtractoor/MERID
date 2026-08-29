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
    [string]$Profile = "kalshi_crypto_15m_v2",
    [string]$EnvFile = ".\.env"
)

$ErrorActionPreference = "Stop"

# 0. Pre-flight helpers
function Require-ExactEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value) -or $value.Trim().ToLowerInvariant() -ne $Expected.ToLowerInvariant()) {
        throw "[start_15m] LIVE MODE REFUSED: $Name must be exactly '$Expected'; actual value is missing or invalid."
    }
}

function Write-StartupFingerprint {
    $legacy = @(
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_CLIENT_API_KEY", "COINBASE_CLIENT_API_SECRET",
        "MERID_COINBASE_API_KEY", "MERID_COINBASE_API_SECRET",
        "KRAKEN_API_KEY", "KRAKEN_PRIVATE_KEY",
        "ALPACA_API_KEY", "ALPACA_API_SECRET",
        "MERID_ALPACA_API_KEY", "MERID_ALPACA_API_SECRET",
        "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_WALLET_ADDRESS",
        "OKX_API_KEY", "OKX_API_SECRET",
        "BYBIT_API_KEY", "BYBIT_API_SECRET"
    )
    $legacyPresent = @()
    foreach ($var in $legacy) {
        if ([Environment]::GetEnvironmentVariable($var, "Process")) {
            $legacyPresent += $var
        }
    }

    $manualToken = if ([string]::IsNullOrWhiteSpace($env:MERID_MANUAL_EMERGENCY_TOKEN)) { "absent" } else { "present" }
    $breakerToken = if ([string]::IsNullOrWhiteSpace($env:MERID_BREAKER_RELEASE_TOKEN)) { "absent" } else { "present" }
    $circuitDisabled = if ([Environment]::GetEnvironmentVariable("MERID_CIRCUIT_BREAKER_DISABLED", "Process") -in ("1", "true")) { "disabled" } else { "enabled" }
    $circuitObserve = [Environment]::GetEnvironmentVariable("MERID_CIRCUIT_BREAKER_OBSERVE_ONLY", "Process")
    if ([string]::IsNullOrWhiteSpace($circuitObserve)) { $circuitObserve = "not_set" }

    Write-Host "[start_15m] === Production startup fingerprint ===" -ForegroundColor Green
    Write-Host "[start_15m] MERID_ENV=$($env:MERID_ENV)" -ForegroundColor Green
    Write-Host "[start_15m] MERID_KALSHI_ENV=$($env:MERID_KALSHI_ENV)" -ForegroundColor Green
    Write-Host "[start_15m] KALSHI_ENV=$($env:KALSHI_ENV)" -ForegroundColor Green
    Write-Host "[start_15m] MERID_REQUIRE_EXIT_PARENTAGE=$($env:MERID_REQUIRE_EXIT_PARENTAGE)" -ForegroundColor Green
    Write-Host "[start_15m] MERID_EXIT_FIREWALL_OBSERVE_ONLY=$($env:MERID_EXIT_FIREWALL_OBSERVE_ONLY)" -ForegroundColor Green
    Write-Host "[start_15m] MERID_CIRCUIT_BREAKER_OBSERVE_ONLY=$circuitObserve" -ForegroundColor Green
    Write-Host "[start_15m] MERID_CIRCUIT_BREAKER_DISABLED=$circuitDisabled" -ForegroundColor Green
    Write-Host "[start_15m] MERID_MANUAL_EMERGENCY_TOKEN=$manualToken" -ForegroundColor Green
    Write-Host "[start_15m] MERID_BREAKER_RELEASE_TOKEN=$breakerToken" -ForegroundColor Green
    Write-Host "[start_15m] legacy_exchange_credentials=$($legacyPresent -join ', ')" -ForegroundColor $(if ($legacyPresent.Count -gt 0) { "Red" } else { "Green" })
    Write-Host "[start_15m] =======================================" -ForegroundColor Green
}

function Remove-LegacyExchangeCredentials {
    $legacy = @(
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_CLIENT_API_KEY", "COINBASE_CLIENT_API_SECRET",
        "MERID_COINBASE_API_KEY", "MERID_COINBASE_API_SECRET",
        "KRAKEN_API_KEY", "KRAKEN_PRIVATE_KEY",
        "ALPACA_API_KEY", "ALPACA_API_SECRET",
        "MERID_ALPACA_API_KEY", "MERID_ALPACA_API_SECRET",
        "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_WALLET_ADDRESS",
        "OKX_API_KEY", "OKX_API_SECRET",
        "BYBIT_API_KEY", "BYBIT_API_SECRET"
    )
    foreach ($var in $legacy) {
        $val = [Environment]::GetEnvironmentVariable($var, "Process")
        if ($val) {
            Remove-Item -Path "env:$var" -ErrorAction SilentlyContinue
            Write-Host "[start_15m] Removed legacy $var from process environment" -ForegroundColor Yellow
        }
    }

    # Fail closed if any legacy credential is still present after removal.
    # This happens when the value is set at user/machine scope and re-inherited,
    # or when a .env file contains it. The persistent source must be cleaned.
    $stillPresent = @()
    foreach ($var in $legacy) {
        if ([Environment]::GetEnvironmentVariable($var, "Process")) {
            $stillPresent += $var
        }
    }
    if ($stillPresent.Count -gt 0) {
        throw "[start_15m] LIVE MODE REFUSED: legacy exchange credentials are still present: $($stillPresent -join ', '). Remove them from the .env file and persistent environment before live trading."
    }
}

# 0.1 Load .env file to get credentials
if (Test-Path $EnvFile) {
    Write-Host "[start_15m] Loading environment variables from $EnvFile" -ForegroundColor Cyan
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            # Skip empty values and comments
            if ($name -and $value -and !$name.StartsWith('#')) {
                Set-Item -Path "env:$name" -Value $value
            }
        }
    }
    Write-Host "[start_15m] $EnvFile loaded successfully" -ForegroundColor Green
} else {
    Write-Host "[start_15m] WARNING: env file not found at $EnvFile" -ForegroundColor Yellow
}

# 0.2 Strip legacy exchange credentials from the live 15m process environment.
Remove-LegacyExchangeCredentials

# 0.2a Never allow replay mode in a live trading process. An inherited or stale
# MERID_REPLAY_TAPE would silently switch ingress to a tape and corrupt time math.
@("MERID_REPLAY_TAPE", "MERID_REPLAY_SEED", "MERID_REPLAY_ACTIVE_SOURCES") | ForEach-Object {
    $val = [Environment]::GetEnvironmentVariable($_, "Process")
    if ($val) {
        Remove-Item -Path "env:$_" -ErrorAction SilentlyContinue
        Write-Host "[start_15m] Removed replay env $_ from live process" -ForegroundColor Yellow
    }
}

# 0.3 Canonical environment resolver.
# MERID_ENV=prod is the canonical application mode for this production startup script.
$existingMeridEnv = [Environment]::GetEnvironmentVariable("MERID_ENV", "Process")
if ([string]::IsNullOrWhiteSpace($existingMeridEnv)) {
    $env:MERID_ENV = "prod"
} elseif ($existingMeridEnv.Trim().ToLowerInvariant() -notin ("prod", "production")) {
    throw "[start_15m] LIVE MODE REFUSED: MERID_ENV is '$existingMeridEnv' but must be 'prod' or 'production' for this startup script."
}
Write-Host "[start_15m] MERID_ENV=$($env:MERID_ENV)" -ForegroundColor Cyan

# 1. Risk profile (loop expects kalshi_crypto_15m_v2)
$env:MERID_PROFILE = $Profile
Write-Host "[start_15m] MERID_PROFILE=$($env:MERID_PROFILE)" -ForegroundColor Cyan

# 1.1 Production runtime profile for live Kalshi 15m crypto.
# MERID_PM_PROFILE=production enables production wiring, data guards, and
# fail-closed auth.  It is required for any live 15m crypto run.
$env:MERID_PM_PROFILE = "production"
Write-Host "[start_15m] MERID_PM_PROFILE=$($env:MERID_PM_PROFILE)" -ForegroundColor Cyan

# 1.2 SECURITY: Single-user operator bypass is prohibited when live trading is
# enabled.  Force it off regardless of .env.
$env:MERID_SINGLE_USER_OPERATOR = "0"
Write-Host "[start_15m] MERID_SINGLE_USER_OPERATOR=$($env:MERID_SINGLE_USER_OPERATOR)" -ForegroundColor Cyan

# 1.3 Live trading requires the production WebSocket client (`ws`).
$env:MERID_KALSHI_WS_CLIENT = "ws"
Write-Host "[start_15m] MERID_KALSHI_WS_CLIENT=$($env:MERID_KALSHI_WS_CLIENT)" -ForegroundColor Cyan

# 2. ENABLE live trading.  ALL FOUR latches are required for live; any missing
#    latch demotes to PAPER (orders simulated, not sent).
$env:TRADING_ENABLED = "true"
$env:MERID_PM_TRADING_MODE = "live"
$env:MERID_PM_LIVE_ENABLED = "true"
$env:MERID_ALLOW_LIVE_TRADES = "true"
# CRITICAL 2026-08-14: Re-enable net edge filter.  The previous "disable" allowed
# low/negative edge momentum_fvg signals to execute and lose money.  The filter now
# uses the signal's ev_net_cents or computes canonical edge_cents = (P_true - P_market)*100.
$env:MERID_KALSHI_NET_EDGE_FILTER_ENABLED = "true"
Write-Host "[start_15m] *** LIVE MODE - REAL ORDERS WILL BE SENT ***" -ForegroundColor Red
Write-Host "[start_15m] TRADING_ENABLED=$($env:TRADING_ENABLED)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_PM_TRADING_MODE=$($env:MERID_PM_TRADING_MODE)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_PM_LIVE_ENABLED=$($env:MERID_PM_LIVE_ENABLED)" -ForegroundColor Cyan
Write-Host "[start_15m] MERID_ALLOW_LIVE_TRADES=$($env:MERID_ALLOW_LIVE_TRADES)" -ForegroundColor Cyan

# 2.1 PREFLIGHT: live mode requires explicit safety controls.  These must come
#    from the production config source (.env / .env.production / env) and are
#    intentionally fail-closed.  Do not provide silent defaults.
if ($env:MERID_PM_TRADING_MODE -eq "live") {
    Require-ExactEnvValue -Name "MERID_REQUIRE_EXIT_PARENTAGE" -Expected "1"
    Require-ExactEnvValue -Name "MERID_EXIT_FIREWALL_OBSERVE_ONLY" -Expected "false"

    # Production emergency and breaker release tokens must be set and must not be
    # the placeholder values from the template.
    if ([string]::IsNullOrWhiteSpace($env:MERID_MANUAL_EMERGENCY_TOKEN) -or $env:MERID_MANUAL_EMERGENCY_TOKEN -eq "SET_FROM_SECRET_STORE") {
        throw "[start_15m] LIVE MODE REFUSED: MERID_MANUAL_EMERGENCY_TOKEN must be set to a real secret from the secret store."
    }
    if ([string]::IsNullOrWhiteSpace($env:MERID_BREAKER_RELEASE_TOKEN) -or $env:MERID_BREAKER_RELEASE_TOKEN -eq "SET_FROM_SECRET_STORE") {
        throw "[start_15m] LIVE MODE REFUSED: MERID_BREAKER_RELEASE_TOKEN must be set to a real secret from the secret store."
    }

    # Circuit breaker must not be disabled.  Observe-only is the canary default
    # and must be explicitly configured.
    if ([Environment]::GetEnvironmentVariable("MERID_CIRCUIT_BREAKER_DISABLED", "Process") -in ("1", "true")) {
        throw "[start_15m] LIVE MODE REFUSED: MERID_CIRCUIT_BREAKER_DISABLED must not be '1' in production."
    }
}

# 3. Kalshi environment and endpoints (use api.elections.kalshi.com per .env configuration)
# Consolidated to single environment variable: MERID_KALSHI_ENV
$env:MERID_KALSHI_ENV = "prod"  # Unified environment variable (prod=demo, prod=live)
$env:KALSHI_USE_DEMO = "false"  # Explicitly disable demo mode for production safety
# CRITICAL FIX: Use api.elections.kalshi.com endpoints (elections API, not external-api)
# The external-api endpoints do not support elections markets
$env:MERID_KALSHI_HTTP_BASE = "https://api.elections.kalshi.com/trade-api/v2"
$env:MERID_KALSHI_WS_BASE = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# 3.0a Derive the legacy KALSHI_ENV from the canonical MERID_KALSHI_ENV.
# KALSHI_ENV=live is the operational form that the Kalshi client uses to pick
# production endpoints.  MERID_KALSHI_ENV=prod is the canonical setting.
$canonicalKalshi = $env:MERID_KALSHI_ENV.Trim().ToLowerInvariant()
$derivedKalshi = if ($canonicalKalshi -in ("prod", "live")) { "live" } elseif ($canonicalKalshi -eq "demo") { "demo" } else { $canonicalKalshi }
$existingKalshi = [Environment]::GetEnvironmentVariable("KALSHI_ENV", "Process")
if ([string]::IsNullOrWhiteSpace($existingKalshi)) {
    $env:KALSHI_ENV = $derivedKalshi
    Write-Host "[start_15m] KALSHI_ENV=derived-from-MERID_KALSHI_ENV -> $($env:KALSHI_ENV)" -ForegroundColor Cyan
} elseif ($existingKalshi.Trim().ToLowerInvariant() -ne $derivedKalshi) {
    throw "[start_15m] LIVE MODE REFUSED: KALSHI_ENV='$existingKalshi' conflicts with MERID_KALSHI_ENV='$($env:MERID_KALSHI_ENV)' (expected KALSHI_ENV='$derivedKalshi'). Do not set KALSHI_ENV independently; use MERID_KALSHI_ENV."
} else {
    $env:KALSHI_ENV = $existingKalshi
    Write-Host "[start_15m] KALSHI_ENV=$($env:KALSHI_ENV) (consistent with MERID_KALSHI_ENV)" -ForegroundColor Cyan
}

# 3.1 Kalshi API credentials (required for live trading)
# These should be set in your .env file or environment
# Credentials are expected to be already set in environment variables
if (-not $env:KALSHI_LIVE_API_KEY_ID) {
    $env:KALSHI_LIVE_API_KEY_ID = $env:KALSHI_API_KEY_ID
}
if (-not $env:KALSHI_LIVE_PRIVATE_KEY_PATH) {
    $env:KALSHI_LIVE_PRIVATE_KEY_PATH = $env:KALSHI_PRIVATE_KEY_PATH
}

# 3.1a Mirror the live credentials to the canonical Kalshi credential names used by
# merid.settings and the settlement poller.  This ensures the settlement poller and
# balance fetcher can find credentials when only the KALSHI_LIVE_* variants are set.
if (-not $env:KALSHI_API_KEY_ID) {
    $env:KALSHI_API_KEY_ID = $env:KALSHI_LIVE_API_KEY_ID
}
if (-not $env:KALSHI_PRIVATE_KEY_PATH) {
    $env:KALSHI_PRIVATE_KEY_PATH = $env:KALSHI_LIVE_PRIVATE_KEY_PATH
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

# 5. CF Benchmarks RTI adapter is the canonical live settlement source.
$env:MERID_CFB_RTI_ADAPTER = "true"
Write-Host "[start_15m] MERID_CFB_RTI_ADAPTER=$($env:MERID_CFB_RTI_ADAPTER) - CF Benchmarks RTI enabled" -ForegroundColor Cyan

# 6. Arbitrage and market making are controlled by the profile
# (kalshi_crypto_15m_v2.yaml).  No hard override here.

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
# The $2 global slot allocator (MERID_FIXED_EXPOSURE_CAP_USD, default 2.00) is the
# single source of truth for exposure. GlobalExecutionGuard is deprecated (import-blocked).
Write-Host "[start_15m] Exposure model: fixed `$2 global slot allocator (percentage caps disabled)" -ForegroundColor Cyan

# Market making and correlation tracking are controlled by profile config (kalshi_crypto_15m_v2.yaml)
# These are already enabled in the profile config

# CRITICAL FIX: Event loop policy is now set inside main_15m_lean.py
# This ensures it's set in the same process that runs uvicorn
$env:PYTHONUNBUFFERED = "1"
Write-Host "[start_15m] Event loop policy will be set inside main_15m_lean.py" -ForegroundColor Cyan

Write-StartupFingerprint

Write-Host "[start_15m] Launching server on http://${ServerHost}:${Port}" -ForegroundColor Cyan
Write-Host "[start_15m] Startup is handled by FastAPI lifespan events - no health watcher needed" -ForegroundColor Green
Write-Host "[start_15m] ---- server logs below ----" -ForegroundColor Yellow



# Start the server - FastAPI lifespan will handle startup automatically
# Use --log-level info (less verbose than debug)
# CRITICAL FIX: Remove --log-config to prevent interference with lifespan event
# CRITICAL FIX: Remove --reload after clearing __pycache__ to force fresh import
# CRITICAL FIX: Remove --lifespan on (redundant - app already has lifespan defined)
$env:PYTHONUNBUFFERED = "1"
$ErrorActionPreference = "Continue"
# Prefer the project virtualenv so the exact package set is used.
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "py" }
& $python -m uvicorn web.main_15m_lean:app --host $ServerHost --port $Port --log-level info
