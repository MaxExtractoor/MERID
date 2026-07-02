# Spot Service Contract Audit

## Executive Summary

This audit documents the intended vs actual spot contract for the unified spot service, identifying critical gaps between design and implementation.

---

## 1. Intended Spot Contract (Design Document)

### Canonical Function
```
get_unified_spot(A) -> SpotPrice(price, timestamp, source)
```

### Contract Requirements (from design doc)

For each asset A ∈ {BTC, ETH, SOL, XRP, DOGE}:

1. **Provider Composition**
   - Primary: Coinbase
   - Fallbacks: Kraken, BinanceUS
   - Failover: Immediate fallback on primary timeout

2. **Freshness**
   - Return fresh data (timestamp within X seconds of now, tuned per asset)
   - Handle transient provider failures without blocking main 15m loop

3. **Error Handling**
   - Clear reasons when cannot provide valid spot:
     - "no provider healthy"
     - "server rate limited"
     - "provider timeout"

---

## 2. Actual Implementation Audit

### 2.1 Provider Composition

**Documented in Code:**
```python
# Line 7-8 in unified_spot_service.py docstring:
# Streaming layer (primary): Coinbase public API, Kraken public API
```

**Actual Implementation:**
- **Only Coinbase is implemented**
- No Kraken fetch method exists
- No BinanceUS fetch method exists
- No fallback logic between providers

**Evidence:**
- Only `_fetch_coinbase_async()` method exists (line 619)
- No `_fetch_kraken_async()` or `_fetch_binanceus_async()` methods
- Provider list is hardcoded in `pair_map` (line 627-633) - only Coinbase pairs

**Gap:** ❌ **CRITICAL** - Fallback providers are documented but not implemented

---

### 2.2 Timeout Strategy

**Per-Asset Timeouts:**
```python
# Line 650 in _fetch_coinbase_async:
timeout = 2.0 if asset == 'SOL' else 0.5
```

- **SOL:** 2.0s timeout
- **BTC/ETH/XRP/DOGE:** 0.5s timeout

**Retry Logic:**
```python
# Lines 681-758:
max_retries = 2
base_timeout = 0.5 if asset != 'SOL' else 2.0
# Exponential backoff with jitter
```

**Issue:** SOL's 2s timeout is 4x longer than other assets, but no fallback to Kraken/BinanceUS on timeout.

**Gap:** ⚠️ **SOL-specific timeout without fallback** - If Coinbase SOL times out, no alternative provider is tried

---

### 2.3 Cache Policy

**Cache Structure:**
```python
# Line 113:
self._cache: Dict[str, Dict[str, Any]] = {}
self._cache_lock = threading.Lock()
```

**Update Cadence:**
- **Seed fetch:** Synchronous on startup (line 168-207)
- **Background refresh:** Every 2 seconds (line 537)
- **Watchdog check:** Every 2 seconds (line 272)

**Cache Fields:**
```python
{
    'price': float,
    'timestamp': int (ms),
    'source': 'coinbase_public',
    'recv_ts': float (seconds)
}
```

**Gap:** ✅ **Adequate** - Cache policy is reasonable for 15m trading

---

### 2.4 Staleness Rules

**Multiple Thresholds (INCONSISTENT):**

1. **Freshness threshold for degradation:** 5.0s (line 123)
   ```python
   self._freshness_threshold_s = 5.0
   ```

2. **Hard staleness check in get():** 600s (10 min) (line 776)
   ```python
   if age_ms > 600000:
       logger.warning(f"[UNIFIED-SPOT] Stale spot price for {asset} (age={age_ms}ms > 600000ms threshold)")
       return None
   ```

3. **Watchdog threshold:** 10.0s (line 125)
   ```python
   self._watchdog_threshold_s = 10.0
   ```

4. **Health check staleness:** 20s (line 870)
   ```python
   "stale": age_ms > 20000  # 20s threshold for 15m crypto strategy
   ```

**Gap:** ❌ **CRITICAL** - **Four different staleness thresholds** exist:
- 5s for degradation
- 10s for watchdog
- 20s for health check
- 600s for hard rejection

This creates confusion about which threshold to use and can lead to inconsistent behavior across call sites.

---

### 2.5 Degradation Policy

**Implementation:**
```python
# Lines 786-797:
if freshness_s > self._freshness_threshold_s:
    if not degraded:
        self._asset_degraded[asset] = True
        logger.error(f"[SPOT-DEGRADED-ACTION] suppressing {asset} trading due to stale spot")
    return None
```

**Behavior:**
- Asset marked degraded if freshness > 5s
- Trading suppressed for degraded assets
- Asset recovered when freshness drops below 5s

**Gap:** ⚠️ **No per-asset tuning** - All assets use same 5s threshold, but SOL has slower API response times

---

## 3. Call-Site Audit

### 3.1 Candidate Optimizer (merid/prediction/candidate_optimizer.py)

**Spot Check:**
```python
# Lines 555-589:
async def _check_spot_data(self, spot_service: Any, asset: str) -> bool:
    spot_data = spot_service.get(asset)
    if spot_data is None:
        return False
    
    # Uses timing-aware SLA from sla_config.py
    max_age = get_spot_max_age_seconds(asset, None)
    return age < max_age
```

**Threshold:** Uses `sla_config.get_spot_max_age_seconds()` - **different from unified_spot_service thresholds**

**Gap:** ⚠️ **Inconsistent staleness check** - Uses SLA config instead of service's own thresholds

---

### 3.2 Health Snapshot (merid/event_venues/kalshi/health_snapshot.py)

**Spot Check:**
```python
# Lines 197-229:
spot_data = spot_service._cache.get(asset)  # Direct cache access
spot_ts = spot_data.get('timestamp', 0) / 1000.0
spot_age_ms = int((time.time() - spot_ts) * 1000)

spot_status_str = get_spot_status(asset, spot_age_ms)  # Uses sla_config
```

**Issues:**
- Bypasses `spot_service.get()` - accesses `_cache` directly
- Uses `sla_config.get_spot_status()` instead of service's degradation state
- Does not respect `_asset_degraded` flag

**Gap:** ❌ **CRITICAL** - Bypasses service API and degradation policy

---

### 3.3 Spot Provider (merid/prediction/spot_provider.py)

**Spot Check:**
```python
# Lines 132-157:
service = get_unified_spot_service()
spot = service.get(asset.upper())

if spot is None:
    return None

staleness_ms = now_ms - spot.timestamp
return SpotSnapshot(...)
```

**Behavior:** Uses `service.get()` correctly, respects staleness

**Gap:** ✅ **Correct** - Uses proper API

---

### 3.4 Loop 15m (merid/loop_15m.py)

**Spot Usage:** Not directly visible in first 747 lines - likely uses through agent_grid or candidate_optimizer

---

## 4. SOL-Specific Audit

### 4.1 Per-Asset Implementation

**Timeout Differences:**
```python
# Line 650:
timeout = 2.0 if asset == 'SOL' else 0.5
```

**Retry Logic:** Same as other assets (max 2 retries with backoff)

**Degradation:** Same 5s threshold as other assets

**Gap:** ⚠️ **SOL has longer timeout but same degradation threshold** - Inconsistent: SOL is given more time to fetch but is marked degraded at same freshness threshold

---

### 4.2 SOL Degradation Definition

**Current:** Same as other assets (freshness > 5s)

**Issue:** SOL API is slower (2s timeout vs 0.5s), so it's more likely to hit the 5s degradation threshold during network latency spikes.

**Gap:** ⚠️ **No SOL-specific degradation tuning** - Should have higher degradation threshold to match slower API

---

### 4.3 SOL Fallback Behavior

**Current:** No fallback - only Coinbase with retries

**Gap:** ❌ **CRITICAL** - No Kraken/BinanceUS fallback for SOL despite documented design

---

## 5. Critical Issues Summary

### P0 - Critical Gaps

1. **No fallback providers implemented** - Docstring claims Kraken/BinanceUS, but only Coinbase exists
2. **Four different staleness thresholds** - 5s, 10s, 20s, 600s - creates confusion
3. **Health snapshot bypasses service API** - Direct cache access ignores degradation policy
4. **Inconsistent staleness checks across call sites** - Some use SLA config, some use service thresholds

### P1 - High-Priority Issues

5. **SOL has longer timeout but same degradation threshold** - Should be tuned together
6. **No per-asset degradation tuning** - All assets use same 5s despite different API characteristics
7. **No clear error reasons** - Returns None without distinguishing between "no provider healthy", "rate limited", "timeout"

### P2 - Medium-Priority Issues

8. **Cache accessed directly by health snapshot** - Should use service.get() API
9. **Staleness thresholds scattered across code** - Should be centralized in config

---

## 6. Recommendations

### Immediate Actions (P0)

1. **Implement fallback providers or remove from documentation**
   - Either add Kraken/BinanceUS fetch methods
   - Or update docstring to reflect Coinbase-only reality

2. **Consolidate staleness thresholds**
   - Define single source of truth in config
   - Use same threshold across all call sites
   - Recommended: 10s for 15m contracts (balances freshness vs reliability)

3. **Fix health snapshot to use service API**
   - Replace `spot_service._cache.get(asset)` with `spot_service.get(asset)`
   - Respect `_asset_degraded` flag
   - Use service's staleness calculation

### Short-Term Actions (P1)

4. **Add per-asset degradation tuning**
   - SOL: 10s threshold (matches 2s timeout)
   - BTC/ETH/XRP/DOGE: 5s threshold (matches 0.5s timeout)

5. **Add clear error reasons**
   - Return enum or structured error instead of None
   - Distinguish between timeout, rate limit, no provider

### Long-Term Actions (P2)

6. **Centralize spot SLA configuration**
   - Single config file for all thresholds
   - Per-asset tuning support
   - Clear documentation of each threshold's purpose

---

## 7. Test Coverage Gaps

### Missing Tests

1. **Fallback provider tests** - None exist because fallbacks don't exist
2. **Staleness threshold consistency tests** - No cross-component validation
3. **Degradation policy tests** - No tests for _asset_degraded flag behavior
4. **Health snapshot integration tests** - No tests for cache bypass issue

---

## 8. Scheduler Health Logic Audit

### 8.1 Series Health Computation

**Location:** `merid/event_venues/kalshi/market_catalog.py`

**Health States:**
```python
_series_health: Dict[str, str] = {}  # series_ticker -> "healthy", "stuck", "no_active_tickers", "unknown"
```

**Computation Logic** (lines 1169-1334 in `_log_catalog_snapshot`):

1. **"healthy"** - Set when:
   - Ticker advances to new window (line 1233)
   - Contract is still valid even if ticker unchanged (line 1316)
   - First time seeing series with active ticker (line 1327)

2. **"stuck"** - Set when:
   - Contract is expired (`not contract_valid`)
   - Time since last catalog change > 120s threshold (line 1302)
   - No new ticker appeared after contract expiry

3. **"no_active_tickers"** - Set when:
   - No active tickers found for series (line 1334)

4. **"unknown"** - Default when series not in health dict (line 2023)

**Threshold:**
```python
_catalog_stuck_threshold_sec: float = 120.0  # 2 windows = 30s * 4 = 120s
```

**Gap:** ⚠️ **Stuck definition is catalog-centric, not MD-centric** - "stuck" means catalog hasn't advanced, not that MD is stale

---

### 8.2 MD Freshness Comparison

**MD SLA Configuration** (`merid/event_venues/kalshi/sla_config.py`):

```python
MD_SLA = MDSLA(
    ok_threshold_ms=2000,   # 2 seconds for OK
    warn_threshold_ms=10000,  # 10 seconds for stale
    block_threshold_ms=120000,  # 120 seconds for block
)
```

**Timing-Aware MD SLA** (`sla_config.py` lines 149-179):
- <2 min to expiry: ≤1s required
- 2-5 min to expiry: ≤2s required
- 5-10 min to expiry: ≤5s required
- >10 min to expiry: 120s base threshold

**Health Snapshot MD Check** (`health_snapshot.py` lines 231-287):
- Uses `build_md_health_record(ticker, md_age_ms, seconds_to_expiry)`
- Compares MD age against timing-aware thresholds
- Returns MDState: FRESH, STALE, UNINITIALIZED

**Gap:** ✅ **MD freshness is well-defined with timing-aware thresholds**

---

### 8.3 Health Definition Alignment

**Two Separate Health Dimensions:**

1. **Catalog Health** (`_series_health`):
   - Concern: Market discovery and ticker advancement
   - Metric: Time since catalog ticker changed
   - Threshold: 120s (2 windows)
   - Purpose: Detect if Kalshi is publishing new contracts

2. **MD Health** (`build_md_health_record`):
   - Concern: Market data freshness
   - Metric: Time since last book update
   - Threshold: 2s-120s (timing-aware)
   - Purpose: Detect if orderbook data is stale

**Scheduler Usage** (`crypto_15m_scheduler.py`):
- Does NOT use `get_series_health()`
- Computes windows based on deterministic UTC boundaries
- Returns `should_trade` based on time-to-expiry window (1-14 min)

**Agent Grid Usage** (`agent_grid_15m.py` line 4810):
```python
series_health = self.catalog.get_series_health(series_ticker)
# HF-RELAX: Only block if health is critically bad (no_active_tickers)
# Allow "stuck" or "unknown" if MD is fresh and liquid
if series_health == "no_active_tickers":
    should_trade = False
```

**Gap:** ⚠️ **"stuck" health is non-blocking** - Agent grid allows trading if MD is fresh even if catalog is "stuck"

---

### 8.4 WS vs REST Data Plane Interaction

**WS Bridge Health Tracking** (`ws_bridge.py` lines 68-73):
```python
_ws_forward_first_event_ts: float = 0.0
_ws_forward_last_event_ts: float = 0.0
_ws_forward_events_per_sec: float = 0.0
_ws_forward_queue_size: int = 0
_ws_forward_stalled: bool = False
```

**Prometheus Metrics** (lines 92-111):
```python
kalshi_ws_mode = Gauge('kalshi_ws_mode', 'Kalshi WebSocket connection mode (1=WS, 0=REST fallback)', ['venue'])
kalshi_rest_orderbook_errors_total = Counter('kalshi_rest_orderbook_errors_total', 'Total REST orderbook fetch errors', ['endpoint', 'symbol'])
kalshi_orderbook_completeness = Gauge('kalshi_orderbook_completeness', 'Orderbook completeness (1=OK, 0=MISSING/UNAVAILABLE)', ['symbol'])
```

**REST Fallback Status:**
- Line 52: `rest_fallback_removed=True` - REST fallback was removed
- No `ws_forwarder_healthy` flag found in current code
- WS mode is tracked via Prometheus gauge only

**Health Snapshot WS Check** (`health_snapshot.py` lines 143-167):
```python
ws_bridge = getattr(app.state, "ws_bridge", None)
if ws_bridge:
    stats = ws_bridge.stats()
    snapshot.ws_connected = stats.get("connected", False)
    last_msg_time = stats.get("last_message_time", 0)
    if last_msg_time > 0:
        snapshot.ws_md_age_ms = (time.time() * 1000) - last_msg_time
```

**Gap:** ⚠️ **No explicit REST fallback mode** - System relies on WS only; if WS fails, no graceful degradation to REST

---

## 9. Critical Issues Summary (Updated)

### P0 - Critical Gaps

1. **No fallback providers implemented** - Docstring claims Kraken/BinanceUS, but only Coinbase exists
2. **Four different staleness thresholds** - 5s, 10s, 20s, 600s - creates confusion
3. **Health snapshot bypasses service API** - Direct cache access ignores degradation policy
4. **Inconsistent staleness checks across call sites** - Some use SLA config, some use service thresholds

### P1 - High-Priority Issues

5. **SOL has longer timeout but same degradation threshold** - Should be tuned together
6. **No per-asset degradation tuning** - All assets use same 5s despite different API characteristics
7. **No clear error reasons** - Returns None without distinguishing between "no provider healthy", "rate limited", "timeout"
8. **No REST fallback mode** - WS-only with no graceful degradation

### P2 - Medium-Priority Issues

9. **Cache accessed directly by health snapshot** - Should use service.get() API
10. **Staleness thresholds scattered across code** - Should be centralized in config
11. **"stuck" health is non-blocking** - Confusing semantics; should be either blocking or renamed

---

## 10. Recommendations (Updated)

### Immediate Actions (P0)

1. **Implement fallback providers or remove from documentation**
   - Either add Kraken/BinanceUS fetch methods
   - Or update docstring to reflect Coinbase-only reality

2. **Consolidate staleness thresholds**
   - Define single source of truth in config
   - Use same threshold across all call sites
   - Recommended: 10s for 15m contracts (balances freshness vs reliability)

3. **Fix health snapshot to use service API**
   - Replace `spot_service._cache.get(asset)` with `spot_service.get(asset)`
   - Respect `_asset_degraded` flag
   - Use service's staleness calculation

### Short-Term Actions (P1)

4. **Add per-asset degradation tuning**
   - SOL: 10s threshold (matches 2s timeout)
   - BTC/ETH/XRP/DOGE: 5s threshold (matches 0.5s timeout)

5. **Add clear error reasons**
   - Return enum or structured error instead of None
   - Distinguish between timeout, rate limit, no provider

6. **Implement REST fallback mode**
   - Add REST orderbook polling when WS fails
   - Track `ws_forwarder_healthy` flag
   - Graceful degradation with metrics

### Long-Term Actions (P2)

7. **Centralize spot SLA configuration**
   - Single config file for all thresholds
   - Per-asset tuning support
   - Clear documentation of each threshold's purpose

8. **Clarify "stuck" health semantics**
   - Either make it blocking (halt trading)
   - Or rename to "catalog_lag" to reflect non-blocking nature
   - Document that MD freshness takes precedence

---

## 11. Test Coverage Gaps (Updated)

### Missing Tests

1. **Fallback provider tests** - None exist because fallbacks don't exist
2. **Staleness threshold consistency tests** - No cross-component validation
3. **Degradation policy tests** - No tests for _asset_degraded flag behavior
4. **Health snapshot integration tests** - No tests for cache bypass issue
5. **Series health computation tests** - No tests for stuck/healthy transition logic
6. **WS vs REST fallback tests** - No tests for fallback mode (doesn't exist)

---

## 12. Conclusion

The unified spot service has **significant gaps between documented design and actual implementation**:

- **Fallback providers are documented but not implemented**
- **Staleness thresholds are inconsistent across the codebase**
- **Health checks bypass the service API and degradation policy**
- **SOL has special timeout handling but no corresponding degradation tuning**
- **No REST fallback mode exists** - WS-only with no graceful degradation
- **"stuck" health is non-blocking** - Confusing semantics that don't match the name

These gaps explain the persistent "spot is broken" and "stuck" warnings - the system is not behaving as documented, and different components use different thresholds, leading to conflicting health assessments.

**Recommendation:** Prioritize P0 issues immediately, then address P1 issues to align implementation with documented contract.
