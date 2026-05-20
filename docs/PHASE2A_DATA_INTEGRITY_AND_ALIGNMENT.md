# Phase 2A: Data Integrity and Alignment

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate candle/orderbook data, check for drift between backtest and live, verify Kalshi metadata

---

## Executive Summary

This document defines validation checks for market data integrity, timezone/resampling alignment, and drift detection between backtest and live environments. All data sources must be validated against official Kalshi API responses with version tracking.

---

## Data Pipeline Architecture

### Current Data Flow

```
Kalshi REST API
    ↓
KalshiMarketCatalog (metadata refresh every 60s)
    ↓
KalshiMarketStateStore (real-time state from WS + REST)
    ↓
CandlePoller (candlesticks every 60s, period=1m)
    ↓
Trading Agents (read from MarketStateStore)
```

### Historical Data Flow

```
Historical Snapshots (WS logs or cached data)
    ↓
Backtest Engine (MarketSnapshot objects)
    ↓
Strategy Simulation
    ↓
PnL Attribution
```

---

## Candle/Orderbook Validation

### Validation 1: Candlestick Data Completeness

**Source:** `merid/event_venues/kalshi/candle_poller.py`  
**Endpoint:** `GET /markets/{ticker}/candlesticks`

**Required Fields per Candle:**
```python
{
    "t": int,           # Open time (Unix epoch seconds, UTC)
    "o": float,         # Open price in cents
    "h": float,         # High price in cents
    "l": float,         # Low price in cents
    "c": float,         # Close price in cents
    "v": int,           # Volume
}
```

**Validation Checks:**
1. `t` must be Unix epoch seconds (UTC)
2. `o`, `h`, `l`, `c` must be in range [0, 100] (cents)
3. `h >= l` (high >= low)
4. `h >= o` and `h >= c` (high is maximum)
5. `l <= o` and `l <= c` (low is minimum)
6. `v >= 0` (non-negative volume)
7. Bar alignment: `t % period_interval == 0` (bars aligned to period boundaries)

**Enforcement Point:** `CandlePoller._poll_one()` before `apply_candle_dict()`

**Violation Action:** Log warning, skip bar, increment error counter, alert if >5% of bars fail

---

### Validation 2: Orderbook Data Integrity

**Source:** `merid/event_venues/kalshi/ws_bridge.py` (WebSocket)  
**Message Type:** `orderbook_msg`

**Required Fields per Orderbook Level:**
```python
{
    "yes_price": int,      # YES bid/ask in cents [0, 100]
    "yes_size": int,       # YES quantity >= 0
    "no_price": int,       # NO bid/ask in cents [0, 100]
    "no_size": int,        # NO quantity >= 0
}
```

**Validation Checks:**
1. `yes_price` in range [0, 100]
2. `no_price` in range [0, 100]
3. `yes_price + no_price ≈ 100` (within 1 cent tolerance)
4. `yes_size >= 0` and `no_size >= 0`
5. Bid prices <= Ask prices (if both sides present)
6. Price levels strictly increasing/decreasing (no duplicate prices)

**Enforcement Point:** `WSBridge._handle_orderbook_msg()` before `store.apply_orderbook()`

**Violation Action:** Log warning, skip message, increment error counter, alert if >10% of messages fail

---

### Validation 3: Timestamp Consistency

**Requirement:** All timestamps must be UTC Unix epoch seconds.

**Validation Checks:**
1. Candle timestamps: `t % 60 == 0` for 1-minute bars
2. 15-minute bars: `t % 900 == 0` (aligned to :00, :15, :30, :45)
3. Orderbook timestamps: within 5 seconds of current time (freshness)
4. Expiry timestamps: `expires_at >= now` for active markets
5. No timezone offset indicators in timestamps

**Enforcement Point:** Multiple (candle poller, WS bridge, market catalog)

**Violation Action:** Log error, reject data, alert operator

---

## Timezone and Resampling Logic

### Requirement: UTC-Only, 15-Minute Alignment

**Current Implementation:**
- Candle poller uses Unix epoch seconds (UTC)
- 15-minute bars aligned at :00, :15, :30, :45 UTC
- No timezone conversion performed

**Validation Checks:**

### Check 1: 15-Minute Bar Alignment

**Test:** For each 15-minute candle, verify `timestamp % 900 == 0`

**Expected Behavior:**
```
2026-05-12 00:00:00 UTC  →  timestamp % 900 == 0 ✓
2026-05-12 00:15:00 UTC  →  timestamp % 900 == 0 ✓
2026-05-12 00:30:00 UTC  →  timestamp % 900 == 0 ✓
2026-05-12 00:45:00 UTC  →  timestamp % 900 == 0 ✓
2026-05-12 00:13:00 UTC  →  timestamp % 900 == 0 ✗ (misaligned)
```

**Enforcement Point:** Candle storage layer

**Remediation:** Reject misaligned bars, log warning

---

### Check 2: No Timezone Offsets in Data

**Test:** Scan all timestamp fields for timezone indicators (e.g., `+00:00`, `Z`, timezone names)

**Expected Behavior:** All timestamps are pure Unix epoch seconds (integers)

**Enforcement Point:** Data ingestion layer (candle poller, WS bridge)

**Remediation:** Strip timezone info if present, convert to UTC epoch seconds

---

### Check 3: Resampling from 1-Minute to 15-Minute

**Current Approach:** Candle poller fetches 1-minute bars, stores last closed bar

**Validation:** If resampling from 1m to 15m is implemented, verify:
1. 15-minute OHLC derived from 15 consecutive 1-minute bars
2. `high_15m = max(high_1m)` across the 15 bars
3. `low_15m = min(low_1m)` across the 15 bars
4. `open_15m = open_1m[0]` (first bar's open)
5. `close_15m = close_1m[-1]` (last bar's close)
6. `volume_15m = sum(volume_1m)` across the 15 bars

**Enforcement Point:** Resampling logic (if implemented)

**Remediation:** Fix resampling algorithm, add unit tests

---

## Kalshi Metadata Verification

### Metadata Source: Kalshi REST API

**Primary Endpoint:** `GET /markets`  
**Secondary Endpoint:** `GET /markets/{market_id}`

**Required Metadata Fields:**

### Field 1: Market Ticker

**Format:** `KX{ASSET}{SUFFIX}`  
**Examples:** `KXBTC-15M`, `KXETH-15M`, `KXSOL-15M`, `KXXRP-15M`, `KXDOGE-15M`

**Validation:**
1. Ticker starts with `KX` prefix
2. Asset is one of: `BTC`, `ETH`, `SOL`, `XRP`, `DOGE`
3. Suffix is one of: `-15M`, `` (hourly), `-D`, `-W`
4. Production scope: Only `-15M` suffix allowed for trading

**Enforcement Point:** `KalshiMarketCatalog._enrich()`

**Violation Action:** Log warning, exclude from trading catalog

---

### Field 2: Series Ticker

**Format:** `KX{ASSET}{SUFFIX}` (same as market ticker, but for series)

**Validation:**
1. Series ticker matches market ticker pattern
2. Series ticker is consistent across all markets in the series
3. Production scope: Only `KXBTC-15M`, `KXETH-15M`, `KXSOL-15M`, `KXXRP-15M`, `KXDOGE-15M`

**Enforcement Point:** `KalshiMarketCatalog._enrich()`

**Violation Action:** Log warning, exclude from trading catalog

---

### Field 3: Expiration Time

**Format:** ISO 8601 UTC datetime (e.g., `2026-05-12T00:15:00Z`)

**Validation:**
1. Expiration time is in UTC (ends with `Z` or `+00:00`)
2. Expiration time >= current time for active markets
3. Expiration time is aligned to 15-minute boundaries for 15m series
4. No timezone offset other than UTC

**Enforcement Point:** `KalshiMarketCatalog._enrich()`

**Violation Action:** Log warning, exclude from trading catalog

---

### Field 4: Strike Prices

**Format:** Float in USD (e.g., `50000.0`, `3000.0`, `150.0`)

**Validation:**
1. `floor_strike >= 0`
2. `cap_strike >= 0`
3. `cap_strike >= floor_strike`
4. Strike prices are reasonable for the asset (BTC ~50k, ETH ~3k, SOL ~150, XRP ~0.5, DOGE ~0.1)
5. Strike prices are in USD (not cents)

**Enforcement Point:** `KalshiMarketCatalog._enrich()`

**Violation Action:** Log warning, flag for manual review

---

### Field 5: Volume and Open Interest

**Format:** Integer (number of contracts)

**Validation:**
1. `volume_24h >= 0`
2. `open_interest >= 0`
3. Volume and OI are integers (not floats)
4. Volume and OI are not negative

**Enforcement Point:** `KalshiMarketCatalog._enrich()`

**Violation Action:** Log warning, clamp to 0 if negative

---

## Drift Detection: Backtest vs Live

### Drift Check 1: Candle Data Consistency

**Test:** Compare historical candle data (from backtest) with live candle data (from Kalshi API)

**Method:**
1. For a given ticker and timeframe, fetch historical candles from backtest data
2. Fetch live candles from Kalshi API for the same time period
3. Compare OHLC values for each timestamp
4. Calculate drift metrics:
   - Absolute drift: `|live_price - backtest_price|`
   - Relative drift: `|live_price - backtest_price| / backtest_price`
   - Max drift across all bars
   - Mean drift across all bars

**Thresholds:**
- Absolute drift: < 1 cent (0.01 USD)
- Relative drift: < 0.1% (0.001)
- Max drift: < 5 cents (0.05 USD)
- Mean drift: < 1 cent (0.01 USD)

**Enforcement Point:** Drift detection job (cron or scheduled task)

**Violation Action:** Log error, alert operator, pause backtest if drift > threshold

---

### Drift Check 2: Orderbook Depth Consistency

**Test:** Compare historical orderbook snapshots with live orderbook state

**Method:**
1. For a given ticker, fetch historical orderbook snapshots from backtest data
2. Fetch live orderbook from Kalshi API
3. Compare top 5 levels on both sides
4. Calculate drift metrics for price and size

**Thresholds:**
- Price drift: < 1 cent (0.01 USD)
- Size drift: < 10 contracts
- Spread drift: < 2 cents (0.02 USD)

**Enforcement Point:** Drift detection job

**Violation Action:** Log warning, alert operator

---

### Drift Check 3: Fee Schedule Alignment

**Test:** Verify fee calculation in backtest matches Kalshi's actual fee schedule

**Kalshi Fee Schedule (from docs):**
- Contracts < 100: 7% of payout
- Contracts 100-999: 5% of payout
- Contracts >= 1000: 3% of payout
- Minimum fee: 2 cents per contract
- Payout = `100 - price_cents`

**Backtest Fee Calculation:**
```python
# From backtest.py line 110-122
def _kalshi_fee_for_backtest(price_cents: int, contracts: int) -> int:
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    payout = 100 - price_cents
    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03
    per_contract = max(2, math.ceil(payout * rate))
    return per_contract * contracts
```

**Validation:**
1. Compare backtest fee calculation with Kalshi API fee for sample trades
2. Verify rate tiers match (7%, 5%, 3%)
3. Verify minimum fee (2 cents)
4. Verify payout calculation (100 - price_cents)

**Thresholds:** Exact match (0 cents difference)

**Enforcement Point:** Unit tests for fee calculation

**Violation Action:** Fix fee calculation, update backtest code

---

## Metadata Versioning

### Requirement: Track Kalshi API Version

**Implementation:**
1. Store Kalshi API version in environment variable: `KALSHI_API_VERSION`
2. Include API version in all API requests (via header or query param)
3. Log API version on startup and on every API call
4. Store API version in cached metadata
5. Alert if API version changes unexpectedly

**Enforcement Point:** Kalshi client wrapper

**Violation Action:** Log warning, alert operator, review API changelog

---

## Data Freshness Checks

### Check 1: Candle Freshness

**Requirement:** Last closed candle must be within 2 × period_interval

**Validation:**
- For 1-minute candles: last closed candle within 120 seconds
- For 15-minute candles: last closed candle within 1800 seconds (30 minutes)

**Enforcement Point:** Candle poller status check

**Violation Action:** Log warning, mark candle data as STALE, alert if >5 minutes stale

---

### Check 2: Orderbook Freshness

**Requirement:** Orderbook must be within 30 seconds of current time

**Validation:**
- `last_update` in KalshiMarketStateStore must be within 30 seconds
- If stale, disable trading for that market

**Enforcement Point:** Market state store freshness check

**Violation Action:** Disable trading for stale market, log warning

---

### Check 3: Market Catalog Freshness

**Requirement:** Market catalog must refresh every 60 seconds

**Validation:**
- `_last_refresh` in KalshiMarketCatalog must be within 120 seconds
- If stale, trigger manual refresh

**Enforcement Point:** Market catalog health check

**Violation Action:** Trigger manual refresh, log warning

---

## Automated Test Plan

### Test Suite: `tests/data/test_kalshi_data_integrity.py`

**Test Classes:**

1. `TestCandlestickValidation`
   - Test: candle OHLC in valid range [0, 100]
   - Test: high >= low invariant
   - Test: high >= open and high >= close
   - Test: low <= open and low <= close
   - Test: volume non-negative
   - Test: timestamp alignment (1m: %60 == 0, 15m: %900 == 0)
   - Test: timestamp is UTC epoch seconds

2. `TestOrderbookValidation`
   - Test: yes_price in range [0, 100]
   - Test: no_price in range [0, 100]
   - Test: yes_price + no_price ≈ 100 (within 1 cent)
   - Test: size non-negative
   - Test: bid <= ask invariant
   - Test: price levels strictly increasing/decreasing

3. `TestMetadataValidation`
   - Test: ticker format KX{ASSET}{SUFFIX}
   - Test: asset is one of BTC/ETH/SOL/XRP/DOGE
   - Test: suffix is one of 15M/""/D/W
   - Test: production scope only allows 15M
   - Test: expiration time is UTC
   - Test: expiration time >= current time
   - Test: expiration aligned to 15m boundaries
   - Test: strike prices non-negative
   - Test: cap_strike >= floor_strike
   - Test: volume and OI non-negative

4. `TestTimezoneAlignment`
   - Test: all timestamps are UTC epoch seconds
   - Test: no timezone offsets in data
   - Test: 15m bars aligned to :00, :15, :30, :45

5. `TestResamplingLogic`
   - Test: 15m high = max of 1m highs
   - Test: 15m low = min of 1m lows
   - Test: 15m open = first 1m open
   - Test: 15m close = last 1m close
   - Test: 15m volume = sum of 1m volumes

6. `TestDriftDetection`
   - Test: candle drift < 1 cent
   - Test: relative drift < 0.1%
   - Test: orderbook price drift < 1 cent
   - Test: orderbook size drift < 10 contracts
   - Test: spread drift < 2 cents
   - Test: fee calculation matches Kalshi schedule

7. `TestDataFreshness`
   - Test: candle freshness within 2 × period_interval
   - Test: orderbook freshness within 30 seconds
   - Test: catalog freshness within 120 seconds

8. `TestAPIVersionTracking`
   - Test: API version header included in requests
   - Test: API version logged on startup
   - Test: API version stored in metadata
   - Test: alert on unexpected API version change

**Total Target:** 60+ data integrity tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify candle poller implementation
- ✅ Identify market catalog implementation
- ✅ Identify crypto series implementation
- ✅ Identify backtest implementation
- ✅ Document data flow

### Step 2: Define Validation Checks (DONE)
- ✅ Define candlestick validation
- ✅ Define orderbook validation
- ✅ Define timestamp consistency
- ✅ Define timezone alignment
- ✅ Define resampling logic
- ✅ Define metadata verification
- ✅ Define drift detection
- ✅ Define freshness checks

### Step 3: Implement Validation Scripts (NEXT)
- [ ] Create `scripts/audit/validate_candlestick_data.py`
- [ ] Create `scripts/audit/validate_orderbook_data.py`
- [ ] Create `scripts/audit/validate_metadata.py`
- [ ] Create `scripts/audit/detect_drift.py`
- [ ] Create `scripts/audit/check_timezone_alignment.py`

### Step 4: Add Runtime Validation
- [ ] Add validation to `CandlePoller._poll_one()`
- [ ] Add validation to `WSBridge._handle_orderbook_msg()`
- [ ] Add validation to `KalshiMarketCatalog._enrich()`
- [ ] Add freshness checks to `KalshiMarketStateStore`

### Step 5: Implement Drift Detection Job
- [ ] Create scheduled job for drift detection
- [ ] Add drift metrics to Prometheus
- [ ] Add alerting for drift violations

### Step 6: Implement Test Suite
- [ ] Create `tests/data/test_kalshi_data_integrity.py`
- [ ] Implement all 8 test classes
- [ ] Target: 60+ tests passing
- [ ] Wire into CI pipeline

### Step 7: Add Monitoring and Alerting
- [ ] Add Prometheus metrics for data quality
- [ ] Add alerting for validation failures
- [ ] Add dashboard for data health

---

## Success Criteria

Phase 2A is complete when:

1. ✅ This design document is approved
2. [ ] All validation scripts are implemented and passing
3. [ ] Runtime validation is added to all data ingestion points
4. [ ] Drift detection job is running and alerting
5. [ ] All 60+ data integrity tests are implemented and passing
6. [ ] Monitoring and alerting are wired
7. [ ] CI pipeline includes data integrity test suite
8. [ ] No data drift > thresholds detected in production

---

## References

- `merid/event_venues/kalshi/candle_poller.py` - Candle polling
- `merid/event_venues/kalshi/market_catalog.py` - Market metadata
- `merid/event_venues/kalshi/crypto_series.py` - Crypto series discovery
- `merid/event_venues/kalshi/backtest.py` - Backtesting framework
- `merid/event_venues/kalshi/market_state.py` - Market state store
- `merid/event_venues/kalshi/ws_bridge.py` - WebSocket bridge
- Kalshi API Documentation (v2)

---

**Next Phase:** Phase 2B - Signal correctness and determinism (offline recompute, cross-asset/timeframe sync, signal diff job)
