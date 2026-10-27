# Kalshi 15m Crypto Production Contract

**Profile:** `kalshi_crypto_15m_v2`
**Effective Date:** 2026-05-14
**Status:** ENFORCED

## Kalshi Expectations (Source of Truth)

Kalshi's 15-minute crypto product explicitly includes the following assets with continuously refreshed short-duration markets:

- **Assets:** BTC, ETH, SOL, XRP, DOGE
- **Timeframe:** 15-minute contracts
- **Series Tickers:** KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- **Market ID Pattern:** KX{ASSET}15M-{DATE}{TIME} (e.g., KXBTC15M-26MAY131530)
- **Category:** crypto
- **Frequency:** fifteen_min

**Reference:** https://kalshi.com/category/crypto/frequency/fifteen_min

## System Requirements

### 1. Asset Set Invariant

**Rule:** The ONLY valid asset set for 15m Kalshi crypto is `{BTC, ETH, SOL, XRP, DOGE}`.

**Implementation:**
- Canonical constant: `CRYPTO_15M_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")` in `merid/constants.py`
- All 15m crypto code MUST use this constant
- Any subset (e.g., "BTC/ETH/SOL only") is a bug
- Startup validation enforces this invariant via `validate_15m_crypto_5_asset_invariant()`

**Violations Detected As:**
- StartupValidationError if AgentGrid config is incomplete
- StartupValidationError if LaneRegistry is incomplete
- Audit flag if hard-coded asset subsets found

### 2. Series Ticker Wiring

**Rule:** All 15m crypto components MUST use 15M series tickers (KXBTC15M, etc.), not base tickers (KXBTC, etc.).

**Implementation:**
- AgentGrid agents: series_tickers must be ["KXBTC15M"], ["KXETH15M"], etc.
- Market catalog: _PRIORITY_SERIES must be ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
- Discovery: kalshi_agent_grid_catalog_series_tickers() returns 15M tickers only
- Dynamic sizing: asset_map must map 15M series tickers to agents

**Violations Detected As:**
- StartupValidationError if series ticker mismatch detected
- Audit flag if base tickers found in 15m code paths

### 3. Market Discovery

**Rule:** Market catalog MUST discover all 5 series with identical parameters.

**Implementation:**
- KalshiMarketCatalog.refresh() fetches all 5 priority series concurrently
- Each series fetched with: active_only=True, limit=200, search=<series_ticker>
- Series ticker extraction from market_id overrides API's series_ticker field
- Backfill disabled for production (uses priority series only)

**Expected Behavior:**
- All 5 series return >= 1 market (subject to Kalshi API availability)
- Markets enriched with correct asset (BTC/ETH/SOL/XRP/DOGE) and timeframe (15m)
- Discovery logs show series_counts for each asset

**Violations Detected As:**
- Warning if any series returns 0 markets (may be API-side issue)
- Audit flag if discovery parameters differ between assets

### 4. WebSocket Subscription

**Rule:** WebSocket bridge MUST subscribe to all 5 assets with correct tickers.

**Implementation:**
- CoinbasePriceFeed default product_ids: ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
- Kalshi WS subscription covers all 5 series tickers
- Startup assertion validates 5-asset subscription coverage
- Fails fast if any asset missing from subscription

**Expected Behavior:**
- WS bridge logs: "Kalshi WS crypto subscription coverage OK by asset BTC 1, ETH 1, SOL 1, XRP 1, DOGE 1 total tickers 5"
- All 5 assets receive live price updates
- No missing or partial subscriptions

**Violations Detected As:**
- StartupValidationError if subscription coverage incomplete
- Warning if fallback product_ids used

### 5. Execution Stack

**Rule:** AgentGrid MUST start cleanly and run 15m cycles for all 5 assets.

**Implementation:**
- AgentGrid.start() initializes start_lock before any early returns
- 5 agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- Each agent runs decision loop with 30-second entry window
- Risk enforcement via kalshi_crypto_15m_v2 profile
- Orders routed via KalshiVenueAdapter

**Expected Behavior:**
- AgentGrid logs clean start with 5 agents
- 15m cycles retrieve markets from MarketUniverse (5 assets)
- Spot feed (Kraken/CB + Coinbase WS) provides prices for all 5 assets
- Consensus/opinions generated for all 5 assets
- Orders emitted via KalshiVenueAdapter for all 5 assets

**Violations Detected As:**
- Startup error if AgentGrid fails to start
- Warning if any agent fails to run cycle
- Audit flag if execution path missing for any asset

### 6. Risk Configuration

**Rule:** All risk parameters MUST use CRYPTO_15M_ASSETS constant.

**Implementation:**
- ASSET_VOL_SCALE_15M: Dict[str, float] built from CRYPTO_15M_ASSETS
- MAX_DELTA_PCT: Dict[str, float] built from CRYPTO_15M_ASSETS
- asset_max_exposure_pct: Dict[str, float] built from CRYPTO_15M_ASSETS
- _get_max_strike_distance_pct() fallback built from CRYPTO_15M_ASSETS
- Profile config (kalshi_crypto_15m.yaml) defines per-asset caps for all 5 assets

**Expected Behavior:**
- All risk dictionaries have exactly 5 keys (BTC, ETH, SOL, XRP, DOGE)
- No hard-coded subsets in risk code
- Profile config is single source of truth for risk limits

**Violations Detected As:**
- StartupValidationError if risk config incomplete
- Audit flag if hard-coded risk subsets found

### 7. Profile-Specific Guards

**Rule:** kalshi_crypto_15m_v2 profile MUST skip non-15m code paths.

**Implementation:**
- PROFILE-GUARD: Skip AutoPromoter for kalshi_crypto_15m_v2
- PROFILE-GUARD: Skip regime agents for kalshi_crypto_15m_v2
- PROFILE-GUARD: Skip lane registry validation for kalshi_crypto_15m_v2
- PROFILE-GUARD: Skip sentiment execution for kalshi_crypto_15m_v2
- PROFILE-GUARD: Skip reflection layer for kalshi_crypto_15m_v2
- PROFILE-GUARD: Skip AgentMesh for kalshi_crypto_15m_v2

**Expected Behavior:**
- Startup logs show PROFILE-GUARD skips for all non-15m paths
- No lane-related warnings (uses AgentGrid, not lanes)
- No sentiment/research/LLM influence on 15m execution
- Clean startup with only 15m-specific components

**Violations Detected As:**
- Warning if non-15m code runs for this profile
- Audit flag if PROFILE-GUARD missing for non-15m path

## Startup Validation Sequence

1. **Profile Check:** MERID_PROFILE=kalshi_crypto_15m_v2
2. **5-Asset Invariant:** validate_15m_crypto_5_asset_invariant()
3. **Catalog Discovery:** KalshiMarketCatalog.refresh() - all 5 series
4. **WS Subscription:** Kalshi WS bridge - all 5 assets
5. **AgentGrid Start:** AgentGrid.start() - all 5 agents
6. **Risk Config:** kalshi_crypto_15m_v2 profile - all 5 assets
7. **Profile Guards:** Skip non-15m paths (AutoPromoter, regime agents, lanes, sentiment, etc.)

## Audit Checklist

For any code change affecting 15m crypto:

- [ ] Uses CRYPTO_15M_ASSETS constant (not hard-coded lists)
- [ ] Includes all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- [ ] Uses 15M series tickers (KXBTC15M, etc.)
- [ ] Has PROFILE-GUARD for kalshi_crypto_15m_v2 if applicable
- [ ] Does not add new execution paths without profile guard
- [ ] Does not re-enable sentiment/research/LLM for this profile
- [ ] Updates this doc if adding new requirements

## Failure Modes

### Critical (Blocks 15m Trading)
- AgentGrid fails to start (e.g., start_lock missing)
- Series ticker mismatch (agents use KXBTC, catalog uses KXBTC15M)
- WS subscription missing for any asset
- Risk config missing for any asset

### High (Confusion, Over-Engineering)
- Lane validation warnings for kalshi_crypto_15m_v2 (legacy noise)
- Duplicate risk config sources
- Non-15m code running for this profile
- Sentiment/research/LLM influence on 15m execution

### Medium (Cleanup, Maintenance)
- Archived agent comments in YAML
- Hard-coded asset subsets in non-critical paths
- Missing PROFILE-GUARD for non-15m paths

## Verification Commands

```bash
# Check constant usage
grep -r "CRYPTO_15M_ASSETS" merid/ --include="*.py"

# Check for hard-coded subsets (should return minimal results)
grep -r "\[\"BTC\".*\"ETH\".*\"SOL\"\]" merid/ --include="*.py"

# Verify startup validation
python -c "from merid.startup_validations import validate_15m_crypto_5_asset_invariant; validate_15m_crypto_5_asset_invariant()"

# Check series tickers in agent grid
grep -A 5 "BTC_15M:" config/kalshi_agent_grid.yaml | grep series_tickers
```

## References

- Canonical constant: `merid/constants.py` - CRYPTO_15M_ASSETS
- Startup validation: `merid/startup_validations.py` - validate_15m_crypto_5_asset_invariant()
- Agent grid config: `config/kalshi_agent_grid.yaml`
- Universe config: `config/kalshi_universe.py` - kalshi_agent_grid_catalog_series_tickers()
- Market catalog: `merid/event_venues/kalshi/market_catalog.py`
- Profile config: `config/profiles/kalshi_crypto_15m.yaml`
- Invariant documentation: `docs/CRYPTO_15M_5_ASSET_INVARIANT_ENFORCEMENT.md`
