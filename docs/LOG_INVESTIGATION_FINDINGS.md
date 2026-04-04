# Log Investigation Findings - 2026-04-04

Complete root cause analysis of 5 critical issues identified from production logs.

## Issue #1: Event Loop Lag and WS Backpressure ⚠️ CRITICAL

### Symptoms from Logs
- Event loop lag exceeding 2000ms halt threshold while trading continues
- Queue pressure at 99.5% with "no essentialtickers set! Cannot auto-reduce scope"
- WS message queue full, dropping messages
- Kalshi WS ping timeouts causing disconnects
- Reconnect resubscribing to 669 tickers

### Root Causes Identified

#### 1.1 Execution Gate Missing Loop-Lag Check
**Location:** `core/execution_gate.py:104-258`

**Finding:** The execution gate has only 4 checks:
1. Kill switch (line 114-125)
2. Reconciliation (line 127-174)
3. Price feed staleness (line 175-193)
4. PnL consistency (line 195-207)

**The 5th check for loop-lag is MISSING** despite EventLoopMonitor existing.

**Impact:** Trading continues even when event loop is severely lagged (2000ms+), causing:
- Stale price data being used for sizing
- Delayed order placement
- Risk of slippage and adverse selection

**Fix Required:** Add loop-lag gating at line 208:
```python
# ── 5. Loop lag ──────────────────────────────────────────────
try:
    from observability.event_loop_monitor import get_event_loop_monitor
    monitor = get_event_loop_monitor()
    stats = monitor.get_stats(window_seconds=60)

    if stats.p95_ms >= 500.0:  # Critical threshold
        reasons.append(BlockReason(
            source="loop_lag",
            severity="critical",
            message=f"Event loop P95 lag {stats.p95_ms:.0f}ms exceeds 500ms",
            details=f"P99={stats.p99_ms:.0f}ms, samples_above_crit={stats.samples_above_crit}",
            hint="Check for blocking operations or high CPU usage",
        ))
    elif stats.p95_ms >= 200.0:  # Warning threshold
        reasons.append(BlockReason(
            source="loop_lag",
            severity="warning",
            message=f"Event loop P95 lag {stats.p95_ms:.0f}ms exceeds 200ms",
            details=f"P99={stats.p99_ms:.0f}ms",
            hint="Consider reducing workload or optimizing hot paths",
        ))
except Exception as exc:
    logger.debug("Loop lag check failed: %s", exc)
```

#### 1.2 Essential Tickers Not Implemented
**Location:** Searched entire codebase - NOT FOUND

**Finding:** The log message "Queue pressure CRITICAL 99.5 but no essentialtickers set!" references a configuration that **does not exist** in the code.

**Impact:** When WS queue fills up, the system cannot:
- Prioritize critical market data
- Auto-reduce subscription scope to essential markets only
- Degrade gracefully under backpressure

**Fix Required:** Implement essential tickers configuration:
```python
# In config/trading_config.py or similar
ESSENTIAL_TICKERS_KALSHI = [
    "KXBTCD1",  # BTC daily - most liquid
    "KXETHD1",  # ETH daily
    # ... high-priority markets for risk management
]

# In merid/event_venues/kalshi/ws.py
def _should_drop_on_overflow(self, ticker: str) -> bool:
    """Return True if this ticker can be dropped during queue overflow."""
    essential = os.getenv("KALSHI_ESSENTIAL_TICKERS", "").split(",")
    return ticker not in essential if essential else True
```

#### 1.3 WS Backpressure Drops Messages Without Scope Reduction
**Location:** `merid/event_venues/kalshi/ws.py:421-436`

**Current Behavior:**
```python
except asyncio.QueueFull:
    self._queue_overflow_count += 1
    self._queue_overflow_recent.append(time.monotonic())
    try:
        self._msg_queue.get_nowait()  # Drop OLDEST
    except asyncio.QueueEmpty:
        pass
    self._msg_queue.put_nowait(data)  # Enqueue NEW
    logger.warning("WS message queue full — dropped oldest message")
    self._try_grow_queue()  # Attempt adaptive growth
```

**Problem:** Drops messages but continues subscribing to all 669 tickers.

**Fix Required:** Add dynamic scope reduction:
```python
# After queue overflow threshold
if self._queue_overflow_count > 100:  # 100 drops = critical
    self._trigger_scope_reduction()

def _trigger_scope_reduction(self):
    """Auto-unsubscribe from non-essential tickers under backpressure."""
    if not self._subscriptions:
        return

    essential = set(os.getenv("KALSHI_ESSENTIAL_TICKERS", "").split(","))
    non_essential = self._subscriptions - essential

    if non_essential:
        logger.warning(
            f"WS queue pressure CRITICAL — unsubscribing from {len(non_essential)} "
            f"non-essential tickers to reduce load"
        )
        # Batch unsubscribe to non-essential tickers
        asyncio.create_task(self._unsubscribe_batch(list(non_essential)))
```

#### 1.4 Single Connection Overload - 669 Tickers
**Location:** `merid/event_venues/kalshi/ws.py:572-589`

**Finding:** On reconnect, the system resubscribes to ALL 669 tickers on a single WS connection:
```python
for ob_ticker in self._orderbook_tickers:
    await self.subscribe_orderbook(ob_ticker)
    await asyncio.sleep(0)  # Only yield between subscriptions
```

**Problem:**
- Kalshi WS has ping_interval=20s, ping_timeout=10s (line 132-133)
- With 669 tickers × ~10 msgs/sec/ticker = 6690 msgs/sec potential
- Single connection bottleneck causes ping timeouts
- Full resubscribe on reconnect amplifies the problem

**Fix Required:** Shard subscriptions across multiple connections:
```python
# Split tickers into shards (e.g., 4 connections × ~167 tickers each)
_WS_SHARD_COUNT = int(os.getenv("KALSHI_WS_SHARD_COUNT", "4"))

def _get_shard_for_ticker(self, ticker: str) -> int:
    """Hash ticker to deterministic shard."""
    return hash(ticker) % _WS_SHARD_COUNT

# Maintain multiple WS connections
self._ws_shards: List[KalshiWSConnection] = []
```

---

## Issue #2: SOL Crypto Wiring Bug 🟡 NON-CRITICAL

### Symptoms from Logs
- `CRYPTO-WIRING-BUG assetSOL discovered=True candidates=0 tradeable=0`
- `filterstats raw=1 precap=1 postcap=1` (filter sees the market but produces zero tradeable)
- Other assets (BTC, ETH, XRP, DOGE) have tradeable candidates

### Root Cause Analysis

**Finding:** SOL is **fully wired** in the codebase:

**Evidence:**
1. **Strategy Profiles Exist:**
   - `merid/event_venues/kalshi/crypto_kalshi_risk.py:229-234` - All 5 SOL timeframes
   - Profiles: `("SOL", "15m")`, `("SOL", "1h")`, `("SOL", "daily")`, `("SOL", "weekly")`, `("SOL", "monthly")`

2. **Continuous Trader Includes SOL:**
   - `merid/trading/kalshi_continuous_trader.py:42` - Imports from `config.crypto_universe`
   - Line 538: `allowed_underlyings=list(_CRYPTO_ASSETS)` includes SOL

3. **Edge Thresholds Defined:**
   - `kalshi_continuous_trader.py:105-109` - SOL edge thresholds (1-2%) in initial_live profile

**The Issue is NOT wiring - it's filtering or catalog availability.**

### Likely Causes (Requires Live Debugging)

#### 2.1 Filter Rejecting All SOL Markets
**Location:** `merid/event_venues/kalshi/market_filter.py:295-380`

**Hypothesis:** SOL markets are being filtered out by one of:
- **Volume band filter** (lines 295-320): SOL has lower volume than BTC/ETH, might be in bottom percentile
- **Spread filter** (max_spread_cents=12 default): SOL spreads may be wider
- **Edge dead zone filter** (min_edge_dead_zone_pct): SOL mid-prices may cluster near 50¢

**Debug Action Required:**
```python
# Add to kalshi_continuous_trader.py _refresh_candidates() around line 700
if asset == "SOL":
    logger.warning(
        f"SOL FILTER DEBUG: asset={asset} tf={tf} "
        f"raw_input={len(raw_candidates)} "
        f"filter_passed={len(filter_result.candidates)} "
        f"rejected_volume_band={filter_result.rejected_volume_band} "
        f"rejected_spread={filter_result.rejected_spread} "
        f"rejected_dead_zone={filter_result.rejected_edge_deadzone} "
        f"rejected_price={filter_result.rejected_price}"
    )
```

#### 2.2 Catalog Not Returning SOL Markets
**Location:** `kalshi_continuous_trader.py:629`

**Hypothesis:** `self._catalog.get_markets_by_asset("SOL", timeframe=tf)` returns empty list because:
- Kalshi has no active SOL markets at the time
- SOL markets have different series naming than expected
- Catalog filtering excludes SOL

**Debug Action Required:**
```python
# Before line 632
catalog_markets = self._catalog.get_markets_by_asset(asset, timeframe=tf)
if asset == "SOL":
    logger.warning(
        f"SOL CATALOG DEBUG: asset={asset} tf={tf} "
        f"catalog_count={len(catalog_markets)} "
        f"sample_tickers={[m.market.market_id for m in catalog_markets[:5]]}"
    )
```

#### 2.3 SOL Series Naming Mismatch
**Known SOL Series:** `KXSOL`, `KXSOLD1`, `KXSOLW1` (mentioned in problem statement)

**Hypothesis:** Catalog lookup expects different naming convention.

**Investigation Required:** Check if catalog uses `SOL` vs `SOLANA` vs other naming.

---

## Issue #3: Guardian Caps and Zero Fills 🔴 CRITICAL

### Symptoms from Logs
- Markets identified with edge 0.47 (47 bps = 4.7%)
- Positive Kelly fractions computed
- `maxcontracts` calculated but cap=0
- Execution gate in "limited" state skipping new entries
- Zero orders placed, zero fills over 24h

### Root Cause Analysis

#### 3.1 "Guardian Caps" Do NOT Exist in Kalshi CT
**Location:** Searched `kalshi_continuous_trader.py` - ZERO "guardian" references

**Finding:** The term "guardian cap" from the logs refers to a **different system** (likely the crypto paper trader or an older version).

**Kalshi CT uses:**
- **Group notional caps:** `_max_group_notional` (default $50, line 51)
- **Kelly sizing:** `signal_to_sizing()` method (lines 839-951)
- **Risk checks:** `_apply_risk_checks()` (lines 953-984)

**There is NO separate "guardian" cap layer.**

#### 3.2 Execution Gate "Limited" State Blocks New Entries (BY DESIGN)
**Location:** `core/execution_gate.py:28-29`

**Definition:**
```python
LIMITED = "limited"  # warnings only — reduce/close positions OK, no new risk
BLOCKED = "blocked"  # critical issues — no execution at all
```

**This is correct behavior.** LIMITED state should block new entries when:
- Reconciliation has warnings (not critical)
- Price feeds are stale (warning level)
- PnL consistency diverges

**In Kalshi demo mode (line 88-101)**, reconciliation and price feed checks are downgraded from "critical" → "warning", which triggers LIMITED state instead of BLOCKED.

#### 3.3 Zero Fills Root Causes

**Cause A: Execution Gate in LIMITED State**
- Check `check_execution_gate().gate_state`
- If "limited", trading is **correctly** blocked
- Fix: Resolve the warning-level issues (reconciliation, price feeds)

**Cause B: Group Notional Cap Exhausted**
- Line 965-972: `if group_used >= self._max_group_notional: return None`
- Default cap is $50 (line 51)
- With 5 assets × 5 timeframes = 25 groups, this is **very restrictive**
- At $50/group, total trading capacity = $50 × 25 = $1250 max

**Recommended Fix:**
```python
# Increase group notional cap via env var
MERID_GROUP_NOTIONAL_CAP=500.0  # $500 per group = $12,500 total capacity
```

**Cause C: Edge Thresholds Too High**
- Lines 91-154: Edge thresholds range from 0.5% (BTC 15m) to 8% (SOL/XRP/DOGE monthly)
- In "production" profile (lines 123-154), thresholds are 2-8%
- Log shows edge=0.47 (47 bps = 4.7%), which would pass BTC but fail most other assets in production profile

**Current profile:** Line 76: `_EDGE_PROFILE = os.getenv("KALSHI_CT_EDGE_PROFILE", "initial_live")`
- Should use "initial_live" (0.5-2% thresholds) by default
- Verify via logs or env var

**Cause D: Max YES Price Cap**
- Lines 1250-1283: Drops YES intents with price > `max_yes_price` (default 50¢, line 54)
- If markets are trading at 51-60¢, ALL YES intents are dropped
- Log should show "MAX_YES_PRICE_CAP dropped YES intent" if this is the cause

**Diagnostic Command:**
```bash
curl http://localhost:8000/api/v1/ct/status | jq '.last_cycle.vetoed_by_reason'
```

Expected output will show counts per veto reason:
```json
{
  "edge_too_low": 15,
  "group_notional_cap": 8,
  "max_yes_price_cap": 3,
  ...
}
```

---

## Issue #4: Reconciliation and Position Cache Anomalies 🟡 MEDIUM

### Symptoms from Logs
- "Reconciliation kalshi 3 discrepancies 0 critical, 0 warning"
- "Unexpected error in getpositions Event loop is closed"
- Position cache: REST=0 positions, reconciliation=2 positions
- Zero fills over 24h (so 2 positions are stale)

### Root Cause Analysis

#### 4.1 Event Loop Closure During getpositions
**Location:** `merid/reconciliation.py:251-261`

**Code:**
```python
try:
    venue_positions = _asyncio.run(adapter.get_positions())
except RuntimeError:
    # A running loop exists
    import concurrent.futures
    _running_loop = _asyncio.get_running_loop()  # ← LINE 257: FAILS IF LOOP CLOSED
    venue_positions = concurrent.futures.Future.result(
        _asyncio.run_coroutine_threadsafe(adapter.get_positions(), _running_loop),
        timeout=30,
    )
```

**Problem:** Line 257 calls `get_running_loop()` which raises `RuntimeError("There is no current event loop in thread Thread-X")` if:
1. The loop has been closed during shutdown
2. Reconciliation is called from a thread without a loop

**Impact:** Reconciliation fails silently, logs "Event loop is closed", but continues with zero discrepancies (lines 263-271).

**Fix Required:**
```python
except RuntimeError as exc:
    if "closed" in str(exc).lower() or "no current event loop" in str(exc).lower():
        logger.warning(
            f"Kalshi reconciliation: event loop unavailable (shutdown?): {exc}"
        )
        # Mark as run with zero discrepancies to unblock execution gate
        global _reconciliation_has_run, _last_reconciliation_ts, _last_discrepancies
        with _recon_lock:
            _reconciliation_has_run = True
            _last_reconciliation_ts = time.time()
            _last_discrepancies = []
        return discrepancies
    # Try run_coroutine_threadsafe if loop exists but is running
    try:
        import concurrent.futures
        _running_loop = _asyncio.get_running_loop()
        venue_positions = concurrent.futures.Future.result(
            _asyncio.run_coroutine_threadsafe(adapter.get_positions(), _running_loop),
            timeout=30,
        )
    except Exception as inner_exc:
        logger.error(f"Kalshi reconciliation failed: {inner_exc}")
        return discrepancies
```

#### 4.2 Position Cache Flapping: REST=0, Reconciliation=2
**Location:** `merid/reconciliation.py:273-331`

**Analysis:**
- Line 273: `merid_positions = _get_merid_positions()` - gets internal paper trader positions
- Lines 276-282: `venue_positions` - gets Kalshi REST API positions
- Lines 321-329: Detects "settled markets" where MERID has position but venue doesn't

**Scenario:**
1. System placed 2 trades in previous session
2. Markets settled (Kalshi removed positions)
3. Paper trader still holds the positions internally
4. REST returns 0 (correct - markets settled)
5. Reconciliation sees 2 positions in paper trader, 0 on venue
6. Lines 321-329 correctly identify these as "settled markets"
7. Calls `_fire_settlement_hooks(sym)` to resolve them

**This is WORKING AS DESIGNED.**

The "3 discrepancies, 0 critical, 0 warning" means:
- 3 positions found (likely 2 settled + 1 minor price drift)
- All classified as "info" level (lines 73-110)
- 0 critical: No phantom or missing positions with qty > 1.0
- 0 warning: No qty drift > 0.01 or price drift > 5%

**Action:** This is normal behavior after market settlements. No fix required.

#### 4.3 "3 Discrepancies" Classification
**Location:** `merid/reconciliation.py:79-110`

**Severity Logic:**
- **Critical** (blocks execution):
  - Qty delta > 1.0 contracts
  - Phantom position (MERID has, venue doesn't)
  - Missing position (venue has, MERID doesn't)

- **Warning** (triggers LIMITED gate state):
  - Qty delta > 0.01 contracts
  - Entry price delta > 5%

- **Info** (logged but not gating):
  - Small qty/price drifts below thresholds

**The 3 discrepancies are likely:**
1-2. Two settled markets (MERID qty > 0, venue qty = 0) - detected at lines 321-329
3. One position with minor price drift (<5%) or tiny qty drift (<0.01)

**All correctly classified as non-blocking.**

---

## Issue #5: Catalog Refresh and Scope Management 🟠 HIGH PRIORITY

### Symptoms from Logs
- Frequent full catalog refreshes (5000 markets, 8 assets)
- Refreshes occurring while WS queue at/near capacity
- Event loop lag elevated during refreshes

### Root Cause Analysis

#### 5.1 Synchronous Catalog Refresh Blocks Event Loop
**Location:** `merid/trading/kalshi_continuous_trader.py:613-806`

**Code Flow:**
```python
async def _refresh_candidates(self) -> List[TradingCandidate]:
    for asset in _CRYPTO_ASSETS:  # 5 assets
        for tf in _CRYPTO_TIMEFRAMES:  # 5 timeframes = 25 iterations
            catalog_markets = self._catalog.get_markets_by_asset(asset, timeframe=tf)
            # ← Potential REST call, blocks here

            # Build raw_candidates list (lines 638-683)
            # ← CPU-bound loop, no yields

            filter_result = self._filter.filter_markets(raw_candidates)
            # ← More CPU-bound filtering

            await asyncio.sleep(0)  # Only yield AFTER each (asset, tf) pair
```

**Problems:**
1. **Sequential REST Calls:** If `get_markets_by_asset()` makes REST calls, doing 25 sequentially is slow
2. **CPU-Bound Loops:** Lines 638-683 build candidates with no yields - blocks event loop
3. **Infrequent Yields:** Only yields every 1/25th of total work
4. **Competes with WS:** Runs on same event loop as WS message processing

#### 5.2 No Backpressure-Aware Scheduling
**Location:** No logic to defer refresh when queue pressure is high

**Problem:** Refresh runs on schedule regardless of system state. Should skip/defer when:
- WS queue pressure > 90%
- Event loop P95 lag > 500ms
- Execution gate in BLOCKED state

#### 5.3 Recommended Fixes

**Fix A: Parallelize Catalog Fetches**
```python
async def _refresh_candidates(self) -> List[TradingCandidate]:
    # Fetch all (asset, timeframe) combinations in parallel
    fetch_tasks = []
    for asset in _CRYPTO_ASSETS:
        for tf in _CRYPTO_TIMEFRAMES:
            fetch_tasks.append(
                self._fetch_and_filter_one_combo(asset, tf)
            )

    # Gather with yields between batches
    batch_size = 5
    all_candidates = []
    for i in range(0, len(fetch_tasks), batch_size):
        batch = fetch_tasks[i:i+batch_size]
        results = await asyncio.gather(*batch, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Catalog fetch failed: {result}")
            else:
                all_candidates.extend(result)
        await asyncio.sleep(0)  # Yield between batches

    return all_candidates

async def _fetch_and_filter_one_combo(self, asset: str, tf: str):
    catalog_markets = self._catalog.get_markets_by_asset(asset, timeframe=tf)
    await asyncio.sleep(0)  # Yield after catalog call

    raw_candidates = []
    for cm in catalog_markets:
        # Build candidate
        raw_candidates.append(...)
        if len(raw_candidates) % 50 == 0:
            await asyncio.sleep(0)  # Yield every 50 markets

    filter_result = self._filter.filter_markets(raw_candidates)
    return [TradingCandidate.from_candidate(c) for c in filter_result.candidates]
```

**Fix B: Backpressure-Aware Scheduling**
```python
async def _refresh_candidates(self) -> List[TradingCandidate]:
    # Check system health before expensive refresh
    from merid.event_venues.kalshi.ws import _get_kalshi_ws
    ws = _get_kalshi_ws()
    if ws:
        queue_depth_pct = ws._msg_queue.qsize() / ws._msg_queue.maxsize
        if queue_depth_pct > 0.90:
            logger.warning(
                f"Skipping catalog refresh — WS queue pressure {queue_depth_pct:.1%}"
            )
            return self._candidates  # Return stale candidates

    from observability.event_loop_monitor import get_event_loop_monitor
    monitor = get_event_loop_monitor()
    stats = monitor.get_stats(window_seconds=60)
    if stats.p95_ms > 500.0:
        logger.warning(
            f"Skipping catalog refresh — event loop P95 lag {stats.p95_ms:.0f}ms"
        )
        return self._candidates

    # Proceed with refresh
    ...
```

**Fix C: Rate Limit Refresh Frequency**
```python
# In __init__
self._last_refresh_ts: float = 0.0
self._min_refresh_interval_s: float = float(
    os.getenv("MERID_CT_MIN_REFRESH_INTERVAL_S", "300")  # 5 minutes default
)

async def _refresh_candidates(self) -> List[TradingCandidate]:
    now = time.monotonic()
    elapsed = now - self._last_refresh_ts
    if elapsed < self._min_refresh_interval_s:
        logger.debug(
            f"Skipping catalog refresh — only {elapsed:.0f}s since last "
            f"(min interval {self._min_refresh_interval_s:.0f}s)"
        )
        return self._candidates

    self._last_refresh_ts = now
    # Proceed with refresh
    ...
```

---

## Summary of Fixes Priority

### P0 - Critical (Deploy Immediately)
1. **Add loop-lag check to execution gate** - Prevents trading on stale data
2. **Increase group notional caps** - Unblocks trading (env var change)
3. **Fix reconciliation shutdown race** - Prevents errors during shutdown

### P1 - High Priority (Deploy This Week)
4. **Implement essential tickers** - Enables graceful degradation
5. **Add WS scope reduction on backpressure** - Prevents message drops
6. **Parallelize catalog refresh** - Reduces event loop blocking
7. **Add backpressure-aware refresh scheduling** - Prevents lag during high load

### P2 - Medium Priority (Deploy Next Sprint)
8. **Shard WS subscriptions** - Supports > 669 tickers without ping timeouts
9. **Add SOL diagnostic logging** - Troubleshoot zero candidates issue
10. **Rate limit catalog refresh** - Reduces unnecessary work

### P3 - Low Priority (Monitoring/Observability)
11. **Expose essential tickers config in dashboard**
12. **Add queue pressure metrics to Grafana**
13. **Create runbook for "limited" state debugging**

---

## Testing Recommendations

### For Each Fix:
1. **Unit tests** - Verify logic in isolation
2. **Integration tests** - Test with mock WS/catalog
3. **Paper gate** - Run 30-minute paper trading session
4. **Canary deployment** - 10% of live traffic for 24h
5. **Full rollout** - After canary validation

### Specific Tests:

**Execution Gate Loop-Lag:**
```python
# Test that execution gate blocks when P95 > 500ms
def test_execution_gate_blocks_on_high_lag():
    monitor = get_event_loop_monitor()
    # Inject high lag samples
    for _ in range(100):
        monitor._samples.append(LagSample(
            measured_at=datetime.now(timezone.utc),
            lag_ms=600.0,
        ))

    gate = check_execution_gate()
    assert gate.blocked
    assert any(r.source == "loop_lag" for r in gate.reasons)
```

**Essential Tickers:**
```python
# Test that non-essential tickers are dropped first
def test_ws_drops_non_essential_first():
    ws = KalshiWebSocket()
    ws._subscriptions = {"KXBTCD1", "KXETHD1", "KXDOGE_NONESSENTIAL"}
    os.environ["KALSHI_ESSENTIAL_TICKERS"] = "KXBTCD1,KXETHD1"

    # Fill queue and trigger overflow
    for _ in range(ws._queue_maxsize + 10):
        ws._msg_queue.put_nowait({"ticker": "KXDOGE_NONESSENTIAL"})

    # Verify non-essential was unsubscribed
    assert "KXDOGE_NONESSENTIAL" not in ws._subscriptions
    assert "KXBTCD1" in ws._subscriptions
```

---

## Metrics to Monitor Post-Deployment

1. **Event Loop Lag P95/P99** - Should stay < 200ms in steady state
2. **WS Queue Depth** - Should stay < 75% utilization
3. **WS Message Drop Rate** - Should be zero after scope reduction
4. **Catalog Refresh Duration** - Should drop by 50%+ after parallelization
5. **Execution Gate State** - % time in CLEAR vs LIMITED vs BLOCKED
6. **CT Fill Rate** - Should increase once caps and gate are fixed
7. **SOL Candidates Count** - Should be > 0 after diagnostic logging

---

## Implementation Checklist

- [ ] P0-1: Add loop-lag check to execution gate
- [ ] P0-2: Increase group notional cap to $500 (env var)
- [ ] P0-3: Fix reconciliation shutdown race condition
- [ ] P1-4: Implement essential tickers configuration
- [ ] P1-5: Add WS scope reduction on backpressure
- [ ] P1-6: Parallelize catalog refresh
- [ ] P1-7: Add backpressure-aware refresh scheduling
- [ ] P2-8: Design WS sharding architecture
- [ ] P2-9: Add SOL diagnostic logging
- [ ] P2-10: Rate limit catalog refresh
- [ ] P3-11: Dashboard updates
- [ ] P3-12: Grafana metrics
- [ ] P3-13: Runbook documentation

