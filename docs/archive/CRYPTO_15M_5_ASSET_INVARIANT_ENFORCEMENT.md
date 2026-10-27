# Crypto 15m 5-Asset Invariant Enforcement

**Date:** 2026-05-14
**Profile:** kalshi_crypto_15m_v2
**Status:** ENFORCED

## Overview

This document describes the enforcement of the hard invariant that the only valid asset set for the 15m Kalshi profile is `{BTC, ETH, SOL, XRP, DOGE}` on 15-minute contracts.

## Canonical Constant

**Location:** `merid/constants.py`

```python
CRYPTO_15M_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
```

This constant is the single source of truth for the 5-asset invariant. All code paths related to the 15m Kalshi profile must use this constant to ensure consistency.

## Startup Validation

**Location:** `merid/startup_validations.py`

**Function:** `validate_15m_crypto_5_asset_invariant()`

This validation runs at startup for the `kalshi_crypto_15m_v2` profile and checks:

1. **AgentGrid Config:** Ensures exactly 5 agents exist with the canonical assets
2. **Lane Registry:** Ensures exactly 5 lanes exist (one per asset)
3. **No Hard-coded Subsets:** Validates no hard-coded asset subsets exist in 15m-profile code paths

If any check fails, the system raises `StartupValidationError` and does not start.

## Code Changes

### Files Updated to Use CRYPTO_15M_ASSETS

1. **merid/prediction/trading_agent.py**
   - `ASSET_VOL_SCALE_15M`: Now built from CRYPTO_15M_ASSETS
   - `MAX_DELTA_PCT`: Now built from CRYPTO_15M_ASSETS

2. **merid/trading/kalshi_continuous_trader.py**
   - `asset_max_exposure_pct` (TraderConfig): Now built from CRYPTO_15M_ASSETS
   - `asset_max_exposure_pct` (from_env): Now built from CRYPTO_15M_ASSETS
   - `_get_max_strike_distance_pct()` fallback: Now built from CRYPTO_15M_ASSETS

3. **web/api/real_data_endpoints.py**
   - Consensus status fallback symbols: Now uses CRYPTO_15M_ASSETS

4. **merid/signals/ws_price_feed.py**
   - CoinbasePriceFeed default product_ids: Now built from CRYPTO_15M_ASSETS

5. **merid/sentiment/cfgi_client.py**
   - `get_market_summary()`: Now uses CRYPTO_15M_ASSETS for major assets

6. **data/ingestion/data_ingestion.py**
   - `MockSentimentSource` symbols: Now uses CRYPTO_15M_ASSETS

7. **core/market_heatmap.py**
   - `_build_sector_map()` fallback: Now built from CRYPTO_15M_ASSETS
   - `_build_category_symbols()` fallback: Now built from CRYPTO_15M_ASSETS

## Hard-coded Subset Fixes

### Prior State (Bugs)

Before this enforcement, the following hard-coded subsets existed:

- `["BTC", "ETH", "SOL"]` in web/api/real_data_endpoints.py (fallback)
- `["BTC-USD", "ETH-USD", "SOL-USD"]` in merid/signals/ws_price_feed.py (default)
- `["BTC", "ETH", "SOL"]` in merid/sentiment/cfgi_client.py (market summary)
- `["BTC", "ETH", "SOL"]` in data/ingestion/data_ingestion.py (mock)
- `{"BTC": "Crypto Major", "ETH": "Crypto Major", "SOL": "Crypto L1"}` in core/market_heatmap.py (fallback)
- `{"core": ["BTC", "ETH", "SOL"]}` in core/market_heatmap.py (fallback)

All of these have been updated to use the canonical CRYPTO_15M_ASSETS constant.

## Catalog Discovery

### Investigation

The catalog discovery issue where BTC/ETH/SOL were finding 0 markets while XRP/DOGE were finding 1 was investigated.

**Finding:** This is not a code bug. The discovery code correctly requests all 5 series with identical parameters:

```python
async def _fetch_series(series: str, limit: int = 200):
    return series, await self._client.list_markets_result(
        MarketFilter(active_only=True, limit=limit, search=series)
    )
```

The discrepancy in market counts is due to different numbers of active markets for each series on Kalshi at query time. This is an API-side data availability issue, not a code issue.

### Series Tickers

The 15m series tickers are:
- KXBTC15M
- KXETH15M
- KXSOL15M
- KXXRP15M
- KXDOGE15M

These are returned by `kalshi_agent_grid_catalog_series_tickers()` in `config/kalshi_universe.py`.

## Invariant Rules

1. **No Subsets:** Any reference to a subset of the 5 assets as the live 15m asset set is a bug
2. **Canonical Constant:** All code must use `CRYPTO_15M_ASSETS` from `merid/constants.py`
3. **Startup Validation:** The invariant is validated at startup for the `kalshi_crypto_15m_v2` profile
4. **AI Enforcement:** AI assistants should flag any deviations from this invariant as bugs

## Verification

To verify the invariant is enforced:

1. Check that `CRYPTO_15M_ASSETS` is imported and used in the files listed above
2. Run the system with `MERID_PROFILE=kalshi_crypto_15m_v2` and verify startup validation passes
3. Search the codebase for hard-coded asset lists and verify they use CRYPTO_15M_ASSETS

```bash
# Search for hard-coded asset lists (should return minimal results)
grep -r "\[\"BTC\".*\"ETH\".*\"SOL\"\]" --include="*.py" merid/
```

## Related Documentation

- `merid/constants.py` - Canonical constant definition
- `merid/startup_validations.py` - Startup validation logic
- `config/kalshi_universe.py` - Series ticker definitions
- `config/kalshi_15m_crypto_config.py` - 15m crypto configuration

## Future Maintenance

When adding new code related to the 15m Kalshi profile:

1. Always use `CRYPTO_15M_ASSETS` from `merid.constants.py`
2. Do not hard-code asset lists
3. Run startup validation to ensure the invariant is not violated
4. If a new asset needs to be added, update the canonical constant and all references
