# Kalshi Configuration Audit — 15-Minute Crypto Markets

**Date**: 2026-05-17
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute contracts (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)
**Objective**: Deep-audit and fix configuration and wiring end-to-end for live Kalshi API

---

## 1. Configuration Table

| Config key | Source (.env/settings/YAML) | First read site | Live meaning | Default | Notes |
|------------|---------------------------|-----------------|--------------|---------|-------|
| `KALSHI_MIN_CLOSE_SECONDS_AGO` | settings.py + env override | client.py:list_markets | Freshness cutoff; empty string/None = disabled | None (disabled) | NEW - replaces hard-coded 3-day cutoff |
| `KALSHI_ENV` | .env | mode_resolver.py:get_kalshi_environment | Chooses demo vs prod host/keys | demo | Values: demo, live, elections |
| `KALSHI_USE_DEMO` | .env | KalshiConfig.__post_init__ | Demo vs prod API toggle | true (safe default) | Legacy; superseded by KALSHI_ENV but still used as fallback |
| `KALSHI_CONFIRM_LIVE` | .env | invariants.py:require_live_confirmation | Safety gate for live trading | 0 (not confirmed) | Must be "1" for live production |
| `KALSHI_API_KEY_ID` | .env | KalshiConfig.__post_init__ | Live API key ID | None | Used when KALSHI_ENV=live |
| `KALSHI_PRIVATE_KEY_PATH` | .env | KalshiConfig.__post_init__ | Path to RSA private key PEM file | kalshi_private_key.pem | Used when KALSHI_ENV=live |
| `KALSHI_PRIVATE_KEY_PEM` | .env | KalshiConfig.__post_init__ | Inline PEM string (alternative to file) | None | Used when KALSHI_ENV=live |
| `KALSHI_LIVE_API_KEY_ID` | .env | KalshiConfig.__post_init__ (KALSHI_ENV=live path) | Explicit live API key | None | Takes precedence over KALSHI_API_KEY_ID when set |
| `KALSHI_LIVE_PRIVATE_KEY_PATH` | .env | KalshiConfig.__post_init__ (KALSHI_ENV=live path) | Explicit live key path | None | Takes precedence over KALSHI_PRIVATE_KEY_PATH when set |
| `KALSHI_DEMO_API_KEY_ID` | .env | KalshiConfig.__post_init__ (KALSHI_ENV=demo path) | Demo API key | None | Used when KALSHI_ENV=demo |
| `KALSHI_DEMO_PRIVATE_KEY_PATH` | .env | KalshiConfig.__post_init__ (KALSHI_ENV=demo path) | Demo key path | None | Used when KALSHI_ENV=demo |
| `KALSHI_API_BASE_URL` | .env (optional) | invariants.py:get_kalshi_base_url | Override REST API base URL | https://api.elections.kalshi.com/trade-api/v2 | Optional; if set, must end with /trade-api/v2 |
| `KALSHI_API_HOST` | settings.py | KalshiConfig.__post_init__ | Override API host | None | Optional; overrides KALSHI_API_BASE_URL if set |
| `KALSHI_MAX_ORDERS_PER_MINUTE` | .env | kalshi_api.py:place_order | Rate limit per minute | 60 | Kalshi tier limit |
| `KALSHI_MAX_ORDERS_PER_HOUR` | .env | kalshi_api.py:place_order | Rate limit per hour | 1000 | Kalshi tier limit |
| `KALSHI_TRADER_MAX_PRICE` | .env | kalshi_continuous_trader.py | Max price for CT orders | 65 | Safety limit for CT |
| `KALSHI_EMAIL` | .env | KalshiConfig.__post_init__ | Email for password auth (legacy) | None | Legacy; RSA auth preferred |
| `KALSHI_PASSWORD` | .env | KalshiConfig.__post_init__ | Password for password auth (legacy) | None | Legacy; RSA auth preferred |

---

## 2. Current .env Configuration (Sanitized)

```bash
# Environment
KALSHI_ENV=live
KALSHI_USE_DEMO=false
KALSHI_CONFIRM_LIVE=1

# Live credentials
KALSHI_API_KEY_ID=18e1cc92-101c-4118-8135-4c3fc27b9fd8
KALSHI_PRIVATE_KEY_PATH=kalshi_private_key.pem

# Rate limits
KALSHI_MAX_ORDERS_PER_MINUTE=60
KALSHI_MAX_ORDERS_PER_HOUR=1000
KALSHI_TRADER_MAX_PRICE=65

# Demo credentials (fallback)
KALSHI_DEMO_EMAIL=demo@kalshi.com
KALSHI_DEMO_PASSWORD=demo123
KALSHI_DEMO_API_KEY_ID=32822964-15ac-4d44-bf99-dfa1c75d5af6
KALSHI_DEMO_PRIVATE_KEY=kalshi_private_key.pem

# Freshness cutoff (NEW - disabled by default)
# KALSHI_MIN_CLOSE_SECONDS_AGO=  # Leave unset to disable
```

---

## 3. Configuration Conflicts and Issues

### Issue 1: KALSHI_API_BASE_URL Not Set in .env
- **Problem**: `KALSHI_API_BASE_URL` is not set in .env, so code defaults to `https://api.elections.kalshi.com/trade-api/v2` (kalshi_api.py line 501)
- **Impact**: For live trading, should use `https://trading-api.kalshi.com/trade-api/v2` (per Kalshi docs)
- **Fix**: Add `KALSHI_API_BASE_URL=https://trading-api.kalshi.com/trade-api/v2` to .env for live trading

### Issue 2: KALSHI_ENV vs KALSHI_USE_DEMO Dual System
- **Problem**: Two environment variables control demo vs live (KALSHI_ENV and KALSHI_USE_DEMO)
- **Current behavior**: KALSHI_ENV takes precedence in KalshiConfig.__post_init__, but KALSHI_USE_DEMO is still read as fallback
- **Impact**: Confusing which variable actually controls the environment
- **Fix**: Standardize on KALSHI_ENV as primary; deprecate KALSHI_USE_DEMO usage

### Issue 3: Hard-coded URLs in KalshiConfig
- **Problem**: KalshiConfig has hard-coded default URLs:
  - `rest_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"`
  - `public_rest_api_url: str = "https://external-api.kalshi.com/trade-api/v2"`
- **Impact**: May not respect KALSHI_API_BASE_URL override
- **Fix**: Ensure KalshiConfig respects KALSHI_API_BASE_URL via get_kalshi_base_url()

---

## 4. Series Ticker Configuration (15m Crypto)

### Canonical Series Tickers (Single Source of Truth)
| Asset | 15m Series Ticker | Source |
|-------|------------------|--------|
| BTC | KXBTC15M | config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS |
| ETH | KXETH15M | config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS |
| SOL | KXSOL15M | config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS |
| XRP | KXXRP15M | config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS |
| DOGE | KXDOGE15M | config/kalshi_15m_crypto_config.py:KALSHI_15M_SERIES_TICKERS |

### Agent Grid Series Tickers
- **File**: config/kalshi_agent_grid.yaml
- **Status**: ✅ CORRECT - All 5 agents use 15M series tickers
  - BTC_15M: series_tickers: [KXBTC15M]
  - ETH_15M: series_tickers: [KXETH15M]
  - SOL_15M: series_tickers: [KXSOL15M]
  - XRP_15M: series_tickers: [KXXRP15M]
  - DOGE_15M: series_tickers: [KXDOGE15M]

### Catalog Priority Series
- **File**: config/kalshi_universe.py:kalshi_agent_grid_catalog_series_tickers()
- **Status**: ✅ CORRECT - Returns 15M series tickers
  - Returns: [KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M]

### Continuous Trader Default Series
- **File**: config/kalshi_universe.py:kalshi_ct_default_series_tickers()
- **Status**: ✅ CORRECT - Returns 15M series tickers
  - Returns: [KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M]

---

## 5. Required Fixes (COMPLETED)

### Fix 1: Update get_kalshi_base_url() to Use Kalshi's Recommended URLs (✅ COMPLETED)
**File**: merid/event_venues/kalshi/invariants.py
**Change**: Updated get_kalshi_base_url() to use Kalshi's documented URLs:
  - live: https://external-api.kalshi.com/trade-api/v2 (recommended)
  - demo: https://external-api.demo.kalshi.co/trade-api/v2 (recommended)
  - elections: https://api.elections.kalshi.com/trade-api/v2 (alias for live)
**Priority**: KALSHI_ENV → KALSHI_API_BASE_URL (escape valve) → KALSHI_USE_DEMO (compat shim with deprecation warning)

### Fix 2: Deprecate KALSHI_USE_DEMO (✅ COMPLETED)
**File**: merid/event_venues/kalshi/models.py
**Change**: Added deprecation warning in KalshiConfig.__post_init__ when KALSHI_ENV is unset but KALSHI_USE_DEMO is set
**Log**: `KALSHI_ENV_DEPRECATED_BOOL_USED` with instructions to set KALSHI_ENV explicitly

### Fix 3: Add KALSHI_AUTH_CONFIG_SUMMARY Startup Validator (✅ COMPLETED)
**File**: merid/startup_validations.py
**Function**: `validate_kalshi_auth_config()`
**Behavior**: Validates env-scoped auth config (KALSHI_LIVE_API_KEY_ID for live, KALSHI_DEMO_API_KEY_ID for demo), warns on legacy generic keys, logs auth method
**Call site**: validate_live_mode_safety()
**Log**: `KALSHI_AUTH_CONFIG_SUMMARY env=<env> method=<api_key_rsa|password|password_legacy|none>`

### Fix 4: Add KALSHI_CONFIG_SUMMARY Logging at Startup (✅ COMPLETED)
**File**: merid/startup_validations.py
**Function**: `log_kalshi_config_summary()`
**Call site**: validate_live_mode_safety()
**Logs**: env, min_close_seconds_ago, trade_base_url, public_base_url

### Fix 5: Add KALSHI_RUNTIME_CONTRACT Logging per Agent (✅ COMPLETED)
**File**: merid/prediction/agent_grid.py
**Location**: Kalshi series subscription loop in start()
**Logs**: asset, series, env, status_filter=open, min_close, trading_mode

### Fix 6: Verify KalshiConfig Respects KALSHI_API_BASE_URL (✅ COMPLETED)
**File**: merid/event_venues/kalshi/models.py
**Change**: Updated __post_init__ to use get_kalshi_base_url() and get_kalshi_ws_url() from invariants.py
**Impact**: KalshiConfig now respects KALSHI_API_BASE_URL env var via invariants module

### Fix 7: Update KALSHI_MIN_CLOSE_SECONDS_AGO Config Self-Test (✅ COMPLETED)
**File**: merid/startup_validations.py
**Function**: `validate_kalshi_min_close_seconds_ago()`
**Behavior**: Validates config value, logs enabled/disabled status, raises error on invalid integer
**Call site**: validate_live_mode_safety()

### Fix 8: Update KALSHI_API_RESPONSE Logs to Include Resolved Base URL (✅ COMPLETED)
**File**: merid/event_venues/kalshi/client_public.py
**Change**: Added base_url parameter to KALSHI_API_RESPONSE log
**Impact**: Logs now show which host was actually hit for market discovery

### Fix 9: Add KALSHI_SERIES_CONSISTENCY_OK Startup Invariants Check (✅ COMPLETED)
**File**: merid/startup_validations.py
**Function**: `validate_kalshi_series_consistency()`
**Behavior**: Verifies all series references (catalog, CT, agent grid) match canonical KALSHI_15M_SERIES_TICKERS
**Call site**: validate_live_mode_safety()
**Log**: `KALSHI_SERIES_CONSISTENCY_OK canonical=[KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M]`

### Fix 10: Update Hardcoded URL Defaults in KalshiConfig (✅ COMPLETED)
**File**: merid/event_venues/kalshi/models.py
**Change**: Updated dataclass defaults to use Kalshi's recommended URLs (external-api.kalshi.com instead of api.elections.kalshi.com)
**Note**: These are fallbacks only; invariants.get_kalshi_base_url() overrides them at runtime

---

## 6. Verification Steps After Restart

### Step 1: Check Startup Logs
Look for:
- `KALSHI_SERIES_CANONICAL` - should show canonical series tickers
- `KALSHI_SERIES_CONSISTENCY_OK` - should confirm all series references match canonical
- `KALSHI_AUTH_CONFIG_SUMMARY` - should show env=live method=api_key_rsa
- `KALSHI_MIN_CLOSE_SECONDS_AGO` - should show "disabled" (or enabled if set)
- `KALSHI_CONFIG_SUMMARY` - should show env=live, min_close_seconds_ago=disabled, trade_base_url=https://external-api.kalshi.com/trade-api/v2
- `KALSHI_RUNTIME_CONTRACT` - should show all 5 assets with correct series tickers

### Step 2: Check Market Discovery Logs
For each series (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M), look for:
- `KALSHI_API_RESPONSE series=KXBTC15M base_url=https://external-api.kalshi.com/trade-api/v2 status=200 markets_count=X`
- `KALSHI_FRESHNESS_FILTER_DISABLED series=KXBTC15M` (since disabled)
- `KALSHI_PUBLIC_MARKETS_SUCCESS series=KXBTC15M total_raw=X total_after_freshness=X returned=X status_filter=open`

### Step 3: Verify No Zero Markets
If markets_count=0 for any series:
1. Check Kalshi website directly (https://kalshi.com/category/crypto/frequency/fifteen_min)
2. Compare with API response logged
3. Determine if issue is upstream (Kalshi API) or downstream (our filters)

### Step 4: Cross-Check Configuration
Ensure:
- KALSHI_CONFIG_SUMMARY matches .env values (env=live, base_url=https://external-api.kalshi.com/trade-api/v2)
- All agents bind to correct series tickers (KXBTC15M, etc.)
- No hard-coded 3-day freshness cutoff remains
- Live mode uses live env, demo mode uses demo env
- No KALSHI_ENV_DEPRECATED_BOOL_USED warning (or warning if KALSHI_USE_DEMO is set)

---

## 7. Open Questions (ANSWERED)

### Q1: Which base URL for live?
**Answer**: Use the **recommended external API host**: `https://external-api.kalshi.com/trade-api/v2`
- This is Kalshi's documented recommended URL for production public data and trade API
- Treat `https://api.elections.kalshi.com/trade-api/v2` as supported but not preferred (alias for elections-specific use)
- For public data and market discovery, docs explicitly use `external-api.kalshi.com`

**Source**: [Kalshi API Environments](https://docs.kalshi.com/getting_started/api_environments), [Kalshi Quick Start](https://docs.kalshi.com/getting_started/quick_start_market_data)

### Q2: Deprecate KALSHI_USE_DEMO?
**Answer**: Yes.
- Kalshi's docs separate by base URL, not booleans
- Keep `KALSHI_ENV` as the only real selector
- Use `KALSHI_USE_DEMO` purely as a compatibility shim when `KALSHI_ENV` is unset
- Add deprecation warning log: `KALSHI_ENV_DEPRECATED_BOOL_USED` with instructions to set `KALSHI_ENV` explicitly

**Source**: [Kalshi API Environments](https://docs.kalshi.com/getting_started/api_environments)

### Q3: Is external-api.kalshi.com correct for public discovery?
**Answer**: Yes.
- The Quick Start "Market Data" guide explicitly says unauthenticated public endpoints are at `https://external-api.kalshi.com/trade-api/v2`
- Shows `markets?series_ticker=...&status=open` examples
- Live-data endpoints also use `external-api.kalshi.com/trade-api/v2`

**Source**: [Kalshi Quick Start](https://docs.kalshi.com/getting_started/quick_start_market_data), [Kalshi Markets API](https://docs.kalshi.com/python-sdk/api/MarketsApi), [Kalshi Live Data](https://docs.kalshi.com/api-reference/live-data/get-live-data)

---

## 8. Summary of Changes

### Files Modified
1. **docs/KALSHI_CONFIG_AUDIT.md** - Created comprehensive configuration audit document
2. **merid/startup_validations.py** - Added four functions:
   - `log_kalshi_config_summary()` - Logs Kalshi configuration at startup
   - `validate_kalshi_min_close_seconds_ago()` - Validates freshness cutoff config
   - `validate_kalshi_auth_config()` - Validates env-scoped auth config
   - `validate_kalshi_series_consistency()` - Validates series ticker consistency
3. **merid/prediction/agent_grid.py** - Added KALSHI_RUNTIME_CONTRACT logging per agent during series subscription
4. **merid/event_venues/kalshi/models.py** - 
   - Updated KalshiConfig.__post_init__ to use get_kalshi_base_url() from invariants.py
   - Added KALSHI_USE_DEMO deprecation warning
   - Updated dataclass defaults to use Kalshi's recommended URLs
5. **merid/event_venues/kalshi/invariants.py** - Updated get_kalshi_base_url() to use Kalshi's recommended URLs:
   - live: https://external-api.kalshi.com/trade-api/v2
   - demo: https://external-api.demo.kalshi.co/trade-api/v2
   - elections: https://api.elections.kalshi.com/trade-api/v2
6. **merid/event_venues/kalshi/client_public.py** - Updated KALSHI_API_RESPONSE log to include resolved base URL

### Key Improvements
- Single source of truth for base URL (invariants.py) now respects Kalshi's documented recommendations
- Startup logs now clearly show Kalshi configuration state (env, auth method, series consistency)
- Per-agent runtime contract logging provides visibility into agent-series binding
- Freshness cutoff config validated at startup with clear error messages
- Auth config validated at startup with env-scoped checks and legacy warnings
- Series consistency validated at startup to prevent drift

### Configuration Flow
1. **.env** → Environment variables (KALSHI_ENV, KALSHI_LIVE_API_KEY_ID, KALSHI_MIN_CLOSE_SECONDS_AGO, etc.)
2. **settings.py** → Reads env vars, provides KALSHI_MIN_CLOSE_SECONDS_AGO (disabled by default)
3. **invariants.py** → get_kalshi_base_url() derives URL from KALSHI_ENV (Kalshi's recommended URLs)
4. **KalshiConfig** → Uses invariants for URLs, reads keys from env based on KALSHI_ENV (env-scoped)
5. **client.py** → Reads KALSHI_MIN_CLOSE_SECONDS_AGO from settings, passes to client_public.py
6. **client_public.py** → Applies freshness filter if min_close_ts provided, logs diagnostics with base URL

---

## 9. Concrete "Done" Criteria for Production-Ready Config

### Criterion 1: No Legacy Env Split
- **Check**: `KALSHI_ENV=live` is set in `.env`
- **Check**: `KALSHI_USE_DEMO` is ignored except for a single deprecation warning if present
- **Log**: `KALSHI_CONFIG_SUMMARY env=live base_url=https://external-api.kalshi.com/trade-api/v2 public_base_url=https://external-api.kalshi.com/trade-api/v2`

### Criterion 2: No Legacy URLs in Live Path
- **Check**: Grep shows no remaining hardcoded `api.elections.kalshi.com` or `demo-api.kalshi.co` in live path (except as documented fallback/alias)
- **Check**: Only `get_kalshi_base_url()` and its demo/live variants are used for URL resolution
- **Check**: KalshiConfig dataclass defaults use Kalshi's recommended URLs (external-api.kalshi.com)

### Criterion 3: Auth is Env-Scoped and Consistent
- **Log**: `KALSHI_AUTH_CONFIG_SUMMARY env=live method=api_key_rsa`
- **Check**: Password auth code paths are either unused or log as legacy when invoked
- **Check**: For live, KALSHI_LIVE_API_KEY_ID + KALSHI_LIVE_PRIVATE_KEY_PATH are used (or generic keys with warning)

### Criterion 4: Freshness is Config-Only
- **Log**: `KALSHI_MIN_CLOSE_SECONDS_AGO: disabled` (or `enabled (seconds=N)` if set)
- **Check**: Startup validation passes for this config
- **Check**: There are no other time-based filters on markets except `min_close_ts` coming from this one config

### Criterion 5: Series Mapping is Unified
- **Log**: `KALSHI_SERIES_CONSISTENCY_OK canonical=[KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M]`
- **Check**: All series references in catalog, grid, and CT resolve from `KALSHI_15M_SERIES_TICKERS`
- **Check**: Zero mismatches in series consistency check

### Criterion 6: Logs Prove Host + Filters are Correct
- **For each series**, logs show:
  - `KALSHI_API_RESPONSE series=KXBTC15M base_url=https://external-api.kalshi.com/trade-api/v2 status=200 markets_count=X`
  - `KALSHI_FRESHNESS_FILTER_DISABLED series=KXBTC15M` (or enabled with cutoff value)
  - `KALSHI_PUBLIC_MARKETS_SUCCESS series=KXBTC15M total_raw=X total_after_freshness=X returned=X status_filter=open`

### Criterion 7: No Zero Markets Degeneracy
- **Check**: All 5 series return non-zero markets_count in KALSHI_API_RESPONSE logs
- **Check**: If zero markets, logs clearly show whether Kalshi API returns 0 or our filters remove them
- **Check**: KALSHI_FRESHNESS_FILTER_DISABLED or KALSHI_FRESHNESS_FILTER logs show filtering behavior

---

## 10. Next Steps for User

1. **Restart the server** to see new logs at startup
2. **Verify KALSHI_CONFIG_SUMMARY** shows env=live, correct base URLs (external-api.kalshi.com)
3. **Verify KALSHI_AUTH_CONFIG_SUMMARY** shows env=live method=api_key_rsa
4. **Verify KALSHI_SERIES_CONSISTENCY_OK** shows canonical series tickers
5. **Verify KALSHI_RUNTIME_CONTRACT** logs show all 5 assets with correct series tickers
6. **Check market discovery logs** for KALSHI_API_RESPONSE with base_url, KALSHI_FRESHNESS_FILTER_DISABLED, KALSHI_PUBLIC_MARKETS_SUCCESS
7. **If zero markets issue persists**, logs will now clearly show whether Kalshi API returns 0 or our filters remove them
8. **Set KALSHI_ENV=live** in .env if not already set (currently KALSHI_ENV=live is set)
9. **Remove KALSHI_USE_DEMO** from .env after confirming KALSHI_ENV works (optional, deprecation warning will guide you)
