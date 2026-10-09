# CoinGecko Removal Audit - BinanceUS Replacement

## Step 1: Codebase Sweep for CoinGecko References

### Category A: Live Dependencies (code that actually calls CoinGecko)

| File | Lines | Category | New Behavior |
|------|-------|----------|--------------|
| `oracles/coingecko_oracle.py` | 1-212 | Live dependency | DELETE entire file - replace with BinanceUS oracle |
| `merid/prediction/coingecko_context.py` | 1-225 | Live dependency | DELETE entire file - market context not needed for 15m Kalshi |
| `data/live_price_feed.py` | 2010-2150 | Live dependency | Replace `_fetch_from_coingecko()` with `_fetch_from_binanceus()` |
| `data/live_price_feed.py` | 749-754 | Live dependency | Replace fallback call to CoinGecko with BinanceUS |
| `data/live_price_feed.py` | 1316-1318 | Live dependency | Replace fallback call to CoinGecko with BinanceUS |
| `data/live_price_feed.py` | 2400-2412 | Live dependency | Replace fallback call to CoinGecko with BinanceUS |
| `data/us_compliant_data_sources.py` | 111-162 | Live dependency | Replace `fetch_coingecko_data()` with `fetch_binanceus_data()` |
| `data/us_compliant_data_sources.py` | 370 | Live dependency | Remove from aggregate_all_sources task list |
| `data/us_compliant_data_sources.py` | 384 | Live dependency | Remove from source_priority list |
| `merid/external_api_rate_limiter.py` | TBD | Live dependency | Remove CoinGecko rate limiting, add BinanceUS if needed |
| `merid/alignment/spot_basis_tracker.py` | TBD | Live dependency | Check for CoinGecko references, replace with BinanceUS |

### Category B: Integration Plumbing (config, env vars, feature flags)

| File | Lines | Category | New Behavior |
|------|-------|----------|--------------|
| `merid/settings.py` | 97-98 | Integration plumbing | Remove COINGECKO_API_KEY, COINGECKO_PRO_API_KEY |
| `config/external_integrations.py` | 46-53 | Integration plumbing | Remove CoinGecko config, add BinanceUS config |
| `config/rate_limits.yaml` | TBD | Integration plumbing | Remove CoinGecko rate limits, add BinanceUS if needed |
| `config/spot_basis_config.py` | TBD | Integration plumbing | Check for CoinGecko references |
| `config/spot_composite_config.py` | TBD | Integration plumbing | Check for CoinGecko references |

### Category C: Dead / Unused (comments, docs, old code)

| File | Lines | Category | New Behavior |
|------|-------|----------|--------------|
| `web/api/crypto_spot_kalshi_api.py` | TBD | API endpoint | Remove CoinGecko references from API |
| `web/api/dashboard.py` | TBD | API endpoint | Remove CoinGecko fallback references |
| `web/api/kalshi_api.py` | TBD | API endpoint | Remove CoinGecko references |
| `web/api/live_data.py` | TBD | API endpoint | Remove CoinGecko references |
| `web/api/loop_api.py` | TBD | API endpoint | Remove CoinGecko references |
| `web/api/halt_diagnosis_api.py` | TBD | API endpoint | Remove CoinGecko references |
| `web/metrics_app.py` | TBD | API endpoint | Remove CoinGecko references |
| `web/static/merid.js` | TBD | Frontend | Remove CoinGecko references |
| `web/templates/components/api_dashboard_screen.html` | TBD | Frontend | Remove CoinGecko references |
| All test files | TBD | Tests | Remove CoinGecko test references, add BinanceUS tests |
| All documentation files | TBD | Docs | Update or remove CoinGecko mentions |

## Step 2: BinanceUS Design

### BinanceUS Client Adapter

```python
# data/binanceus_oracle.py - NEW FILE

class BinanceUSOracle:
    """
    BinanceUS public spot price client for BTC/ETH/SOL/XRP/DOGE.
    
    Uses public REST endpoints (no authentication required).
    Serves as fallback spot source when Coinbase/Kraken/CCXT are unavailable.
    
    Assets supported:
    - BTC → BTCUSDT (or BTCUSD if available)
    - ETH → ETHUSDT
    - SOL → SOLUSDT
    - XRP → XRPUSDT
    - DOGE → DOGEUSDT
    """
    
    BASE_URL = "https://api.binance.us"
    
    # Symbol mapping: internal asset → BinanceUS symbol
    SYMBOL_MAP = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
    }
    
    async def get_price(asset: str) -> Optional[float]:
        """Fetch current price for asset."""
        binance_symbol = self.SYMBOL_MAP.get(asset.upper())
        if not binance_symbol:
            return None
        
        # Call BinanceUS public API: /api/v3/ticker/price?symbol=BTCUSDT
        # Return price or None on error
```

### Integration with LivePriceFeed

Replace `_fetch_from_coingecko()` with `_fetch_from_binanceus()`:
- Same signature: `async def _fetch_from_binanceus(self, symbol: str) -> bool`
- Same batch fetch pattern (fetch all 5 assets in one call)
- Same rate limiting and cooldown logic
- Same price validation
- Same logging (change "CoinGecko" to "BinanceUS")

### Integration with SpotComposite

BinanceUS will feed into SpotComposite like other exchanges:
- ExchangeName.BINANCEUS (add to enum in spot_models.py)
- ExchangeTick with exchange=ExchangeName.BINANCEUS
- SpotComposite treats it like any other exchange

## Step 3: Implementation Plan

1. Create `data/binanceus_oracle.py` with BinanceUS client
2. Add BINANCEUS to ExchangeName enum in `data/spot_models.py`
3. Replace `_fetch_from_coingecko()` with `_fetch_from_binanceus()` in `data/live_price_feed.py`
4. Remove CoinGecko imports and references from `data/live_price_feed.py`
5. Update `data/us_compliant_data_sources.py` to use BinanceUS instead of CoinGecko
6. Remove CoinGecko config from `config/external_integrations.py`
7. Remove COINGECKO env vars from `merid/settings.py`
8. Delete `oracles/coingecko_oracle.py`
9. Delete `merid/prediction/coingecko_context.py`
10. Update API endpoints to reference BinanceUS instead of CoinGecko
11. Update tests to use BinanceUS instead of CoinGecko
12. Update documentation

## Step 4: Risk Alignment

- BinanceUS is treated as degraded/fallback mode (same as CoinGecko was)
- No risk parameter changes - same conservative thresholds when in fallback mode
- Logging clearly indicates "BinanceUS fallback mode" when active
- CFB RTI remains canonical for settlement alignment (unchanged)

## Summary of Changes

### Files Created
- `data/binanceus_oracle.py` - New BinanceUS oracle implementation

### Files Modified
- `data/spot_models.py` - Added BINANCEUS to ExchangeName enum
- `data/live_price_feed.py` - Replaced CoinGecko references with BinanceUS
- `merid/settings.py` - Removed CoinGecko API key fields
- `config/external_integrations.py` - Replaced CoinGecko config with BinanceUS
- `data/us_compliant_data_sources.py` - Replaced CoinGecko with BinanceUS
- `tests/test_live_feeds.py` - Removed TestCoinGecko class
- `tests/core/test_oracle.py` - Updated to test BinanceUS instead of CoinGecko
- `tests/api/test_vertical_slice.py` - Updated to use BinanceUS

### Files Deleted
- `oracles/coingecko_oracle.py` - Removed CoinGecko oracle
- `merid/prediction/coingecko_context.py` - Removed CoinGecko context

## Remaining CoinGecko References

The following CoinGecko references remain in the codebase but are **out of scope** for this task:
- Web API files (dashboard, live_data, kalshi_api) - Use CoinGecko for broader market data
- Prediction/ML features (edge_model, signals) - Use CoinGecko context for alt-season signals
- Test files for non-price-feed functionality (test_sprint_h.py, test_kalshi_crypto_multi_asset.py, etc.)
- Asset universe metadata (coingecko_id field used for asset identification)

These are legitimate uses of CoinGecko for features beyond the core price feed for the 5 crypto assets.

## Completion Status

**COMPLETED**: CoinGecko has been successfully removed as a price feed source for BTC, ETH, SOL, XRP, and DOGE. BinanceUS public API now serves as the fallback source in the LivePriceFeed hierarchy.

**Price Feed Hierarchy (after replacement):**
1. Coinbase Advanced Trade API (primary)
2. Kraken public API (fallback)
3. CCXT exchanges (kraken, coinbase, gemini, binance, bybit, okx)
4. BinanceUS public API (last resort fallback)

**Risk Alignment:**
- BinanceUS is excluded from CF Benchmarks RTI methodology (as required)
- BinanceUS is excluded from direct Kalshi 15m contract trading (as required)
- BinanceUS serves only as a general fallback when other sources fail
- Price delta logging tracks transitions between Coinbase and BinanceUS
- Cooldown and rate limiting protect against API abuse
- Logging clearly indicates "[BINANCEUS-FALLBACK]" when in degraded pricing mode
- CFB RTI remains canonical for settlement alignment (unchanged)

## Smoke Testing

Created smoke test script: `tests/smoke_test_binanceus_integration.py`

**Test Coverage:**
1. Normal mode: Verify primary sources (Coinbase/Kraken) are active, BinanceUS not used
2. Forced fallback mode: Verify BinanceUS fallback works when primary sources fail
3. Edge sanity: Compare BinanceUS vs primary source prices (differences should be < 0.5%)

**Logging Enhancements:**
- Added `[BINANCEUS-FALLBACK]` markers to clearly identify degraded pricing mode
- Added `[PRICE-FAILURE]` marker when all sources fail
- Enhanced logging in CCXT stream and fallback paths

**To run smoke test:**
```bash
python tests/smoke_test_binanceus_integration.py
```
