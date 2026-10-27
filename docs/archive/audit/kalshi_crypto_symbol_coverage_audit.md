# Kalshi Crypto Symbol & Timeframe Coverage Audit

**Date:** 2026-03-30  
**Scope:** All crypto-related Kalshi integration code in MERID  
**Canonical assets:** `BTC, ETH, SOL, XRP, DOGE`  
**Canonical timeframes (CT-active):** `15m, 1h, daily, weekly`  
**Extended timeframes (catalog-only):** `monthly, annual`

---

## 1. Canonical Source of Truth

Already existed before this audit — no changes needed:

| Module | Constant | Coverage |
|--------|----------|----------|
| `config/kalshi_crypto_config.py` | `ACTIVE_CRYPTO_ASSETS` | 5 assets ✅ |
| `config/kalshi_crypto_config.py` | `ACTIVE_CRYPTO_FREQS` | 4 freqs (15M, 1H, D1, W1) ✅ |
| `config/kalshi_crypto_config.py` | `ACTIVE_CRYPTO_WS_TIMEFRAMES` | 4 timeframes ✅ |
| `config/kalshi_universe.py` | `KALSHI_CRYPTO_PRODUCTS` | 5×6 (incl monthly/annual) ✅ |
| `config/kalshi_universe.py` | `KALSHI_CRYPTO_SERIES_TICKERS` | 30 tickers ✅ |
| `config/kalshi_universe.py` | `kalshi_ct_default_series_tickers()` | 20 tickers (excl monthly/annual) ✅ |
| `config/kalshi_crypto_series_meta.py` | `SERIES_META_LIST` | 5×6 = 30 entries ✅ |
| `merid/event_venues/kalshi/constants.py` | `ALL_CRYPTO_ASSETS` | frozenset from canonical ✅ |
| `merid/event_venues/kalshi/constants.py` | `assert_exact_assets()` | Enforces 5-asset match ✅ |

---

## 2. Files Updated (Before → After)

### 2.1 CRITICAL: `merid/event_venues/kalshi/market_mapping.py`
**Impact:** XRP and DOGE markets were **not auto-enabled** — they fell through to a generic "crypto" fallback rule that mapped them to BTC, losing asset-specific sentiment/debate context.

- **Before:** `major_crypto = ["BTC", "ETH", "SOL"]` — only 3 assets auto-enabled
- **After:** Uses `ACTIVE_CRYPTO_ASSETS` from canonical config (all 5)
- **Added:** Dedicated `MappingRule` entries for XRP (xrp/ripple patterns) and DOGE (doge/dogecoin patterns), on par with BTC/ETH/SOL rules

### 2.2 CRITICAL: `merid/event_venues/kalshi/market_wiring/mapping.py`
**Impact:** XRP and DOGE markets had **no explicit wiring rules** — sentiment symbols, debate symbols, and series patterns were missing.

- **Before:** Only BTC, ETH, SOL had dedicated `MappingRule` blocks
- **After:** Added XRP and DOGE mapping rules with correct sentiment symbols (`XRP-USD`, `DOGE-USD`) and debate symbols

### 2.3 CRITICAL: `merid/event_venues/kalshi/market_wiring/sync.py`
**Impact:** SOL/XRP/DOGE markets could be **misclassified** (not tagged as `CRYPTO_LINKED`) if their title/tags didn't include "crypto"/"bitcoin"/"ethereum".

- **Before:** Classification keywords: `["crypto", "bitcoin", "ethereum", "btc", "eth"]`
- **After:** Added: `"solana", "sol", "xrp", "ripple", "doge", "dogecoin"`

### 2.4 CRITICAL: `merid/event_venues/kalshi/market_classifier.py`
**Impact:** XRP/DOGE keywords missing from classification patterns; series_ticker direct-symbol check only had 3 crypto assets.

- **Before:** tags/title/series patterns only had `btc, eth, sol`; series_ticker check: `["BTC", "ETH", "SOL", "SPY", "QQQ", "NDX"]`
- **After:** All 5 crypto assets in tags/title/series; series_ticker uses `set(ACTIVE_CRYPTO_ASSETS) | {"SPY", "QQQ", "NDX"}`

### 2.5 MODERATE: `merid/signals/agents.py`
**Impact:** XRP/DOGE sentiment spikes and news events were **misclassified as "equity" domain** instead of "crypto".

- **Before:** Domain check: `{"BTC", "ETH", "SOL"}` (2 locations)
- **After:** `set(ACTIVE_CRYPTO_ASSETS)` (all 5 assets)

### 2.6 MODERATE: `merid/signals/arbitrage.py`
**Impact:** Synthetic scan (dev/testing) only generated dislocation signals for BTC/ETH/SOL — no XRP/DOGE test coverage.

- **Before:** `symbols = ["BTC", "ETH", "SOL"]` with 3-venue maps
- **After:** Added XRP and DOGE with realistic venue prices

### 2.7 MODERATE: `merid/lanes/crypto15m_lane.py`
**Impact:** DOGE was excluded from the `CryptoSymbol` type literal.

- **Before:** `CryptoSymbol = Literal["BTC", "ETH", "SOL", "XRP"]`
- **After:** `CryptoSymbol = Literal["BTC", "ETH", "SOL", "XRP", "DOGE"]`

### 2.8 CENTRALIZATION: `merid/event_venues/kalshi/invariants.py`
**Impact:** Drift risk — duplicated asset/timeframe lists instead of importing from canonical source.

- **Before:** `KALSHI_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]` (hard-coded)
- **After:** `KALSHI_CRYPTO_ASSETS = list(ACTIVE_CRYPTO_ASSETS)` (imported from `config.kalshi_crypto_config`)
- **Before:** `KALSHI_CRYPTOTIMEFRAMES = ["15m", "1h", "daily", "weekly"]` (hard-coded)
- **After:** `KALSHI_CRYPTOTIMEFRAMES = list(ACTIVE_CRYPTO_WS_TIMEFRAMES)` (imported)

### 2.9 CENTRALIZATION: `merid/event_venues/kalshi/settlement_poller.py`
**Impact:** Drift risk — duplicated VALID_ASSETS and VALID_TIMEFRAMES in 2 locations.

- **Before:** `VALID_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}` (local), `_VALID_ASSETS = frozenset({...})` (class attr)
- **After:** Both derived from `ACTIVE_CRYPTO_ASSETS` and `ACTIVE_CRYPTO_FREQS`

### 2.10 CENTRALIZATION: `merid/event_venues/kalshi/market_filter.py`
**Impact:** Drift risk — 2 hard-coded asset lists in utility functions.

- **Before:** `assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]` (2 locations)
- **After:** `assets = list(ACTIVE_CRYPTO_ASSETS)` (imported)

### 2.11 CENTRALIZATION: `merid/event_venues/kalshi/tools/snapshot_dump.py`
**Impact:** Drift risk — duplicated EXPECTED_ASSETS and per-asset timeframe dict.

- **Before:** Hard-coded `EXPECTED_ASSETS` set and `EXPECTED_TIMEFRAMES` dict
- **After:** Derived from `ACTIVE_CRYPTO_ASSETS` and `ACTIVE_CRYPTO_WS_TIMEFRAMES`

### 2.12 CENTRALIZATION: `merid/guards/__init__.py`
**Impact:** Drift risk — 5 hard-coded `["BTC", "ETH", "SOL", "XRP", "DOGE"]` lists across guard checks.

- **Before:** 5 hard-coded lists in various guard methods
- **After:** All use `list(ACTIVE_CRYPTO_ASSETS)` from canonical import

### 2.13 CLEANUP: `merid/trading/kalshi_continuous_trader.py`
**Impact:** Minor — removed redundant `enum_assets` hard-coded set in `_validate_asset_wiring`.

- **Before:** `enum_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}` (unused shadow of EXPECTED_CRYPTO_UNIVERSE)
- **After:** Removed

---

## 3. Already Correct (No Changes Needed)

| Module | What | Status |
|--------|------|--------|
| `config/kalshi_crypto_config.py` | `ACTIVE_CRYPTO_ASSETS` | All 5 ✅ |
| `config/kalshi_universe.py` | `KALSHI_CRYPTO_PRODUCTS` | 5×6 ✅ |
| `merid/trading/crypto_spot_service.py` | `ASSET_TO_COINBASE_PRODUCT` | All 5 ✅ |
| `merid/trading/crypto_spot_service.py` | `ASSET_TO_BINANCEUS_SYMBOL` | All 5 ✅ |
| `merid/trading/crypto_spot_service.py` | `ASSET_TO_COINGECKO_ID` | All 5 ✅ |
| `merid/trading/kalshi_continuous_trader.py` | `TraderConfig.asset_max_exposure_pct` | All 5 ✅ |
| `merid/trading/kalshi_continuous_trader.py` | `_CG_IDS` | All 5 ✅ |
| `merid/trading/kalshi_continuous_trader.py` | `_STRIKE_BAND_PCT` | All 5 × 3 TFs ✅ |
| `merid/event_venues/kalshi/market_filter.py` | `MIN_EDGE_GRID` | All 5 (assert_exact_assets) ✅ |
| `merid/event_venues/kalshi/market_filter.py` | `MAX_PRICE_GRID` | All 5 (assert_exact_assets) ✅ |
| `merid/event_venues/kalshi/market_selector.py` | `CRYPTO_SERIES_BASE` | All 5 ✅ |
| `merid/event_venues/kalshi/market_catalog.py` | `_HOURLY_ROOTS` regex | All 5 ✅ |
| `merid/event_venues/kalshi/crypto_series.py` | `CRYPTO_SERIES_PREFIXES` | All 5 ✅ |
| `merid/event_venues/kalshi/order_router.py` | `_TICKER_UNDERLYING_MAP` | All 5 + extras ✅ |
| `merid/event_venues/kalshi/category_exposure.py` | `_UNDERLYING_CATEGORY_MAP` | All 5 ✅ |

---

## 4. Intentional Exceptions

| Item | Reason |
|------|--------|
| `merid/strategies/production_strategy_15m.py` — BTC/ETH only | Intentional: this is a BTC+ETH-specific 15m strategy, not the Kalshi crypto universe |
| `merid/strategies/risk_controls.py` — BTC/ETH only | Same: standalone strategy module scoped to BTC/ETH |
| `merid/strategies/engine_15m.py` — BTC/ETH only | Same |
| `merid/signals/sentiment_integration.py` — broader set | Intentional: general crypto sentiment, not Kalshi-specific |
| `merid/signals/live_feeds.py` — broader set | Intentional: general price feeds, includes non-Kalshi assets |
| `merid/signals/ingestion.py` — broader set | Intentional: general ticker universe for signal ingestion |
| `_STRIKE_BAND_PCT` missing `weekly` rows | Falls back to `config.max_strike_distance_pct` (12.5%) — acceptable |
| `CT monthly/annual` series excluded | By design: `kalshi_ct_default_series_tickers()` skips monthly/annual |

---

## 5. Verification Summary

### Strike / Bucket Coverage
- **Filter pipeline** iterates `raw_markets` keyed by asset from `_asset_series_map` — all 5 assets × 4 timeframes ✅
- **NearSpotSelector** in `market_filter.py` uses tiered grids (`MIN_EDGE_GRID`, `MAX_PRICE_GRID`) — validated by `assert_exact_assets` ✅
- **Strike distance** bands in CT cover all 5 assets for 15m/1h/daily; weekly falls back ✅

### Spot Feed Consistency
- `CryptoSpotService` symbol maps (Coinbase, BinanceUS, CoinGecko) all cover 5 assets ✅
- CT's `_get_all_spots(self._active_assets)` passes all 5 ✅
- `set_spot_prices()` in filter pipeline is asset-agnostic ✅

### Series / Ticker Resolution
- `kalshi_ct_default_series_tickers()` yields 20 tickers (5 assets × 4 TFs) ✅
- `_infer_asset_timeframe()` uses `config.kalshi_crypto_series_meta` for resolution ✅
- `_validate_asset_wiring()` checks against `EXPECTED_CRYPTO_UNIVERSE` ✅
