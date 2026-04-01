# Tick Processing Optimization Plan

## Executive Summary

This document addresses tick-level processing lag in `merid/loop.py`. While event-loop scheduler lag has been resolved (P95 <1ms), individual tick steps still exceed their budgets, causing the overall tick duration to exceed the target.

**Current State**:
- Event loop lag: P95 <1ms ✅ (fixed in previous PR)
- Tick processing lag: P95 ~650-800ms ❌ (target <500ms)
- Target tick cadence: every ~5 seconds
- Issue: Multiple steps regularly exceed their budgets, risking tick overlap

---

## Step 1 — Quantitative Prioritization and Classification

### Per-Tick Step Analysis

Based on `merid/loop.py` and observed profiling data:

| Step | Line | Frequency | Budget (ms) | Observed (ms) | Load Type | Role | Tier |
|------|------|-----------|-------------|---------------|-----------|------|------|
| `_refresh_features` | 278 | Every 30s (6 ticks) | 250 | 1,370–4,700 | Mixed (SQLite + HTTP + CPU) | Critical for signals | **Tier 1** |
| `_run_agent_cycles` | 283 | Every 60s (12 ticks) | 30,000 timeout | <30,000 (varies) | CPU + I/O | Critical for trading | **Tier 1** |
| `_run_reflection_cycle` | 288 | Every 300s (60 ticks) | N/A | 7,000 startup, 100-500 steady | CPU | Secondary (learning) | **Tier 3** |
| `_run_consensus` | 293 | Every 15s (3 ticks) | N/A | 866–3,149 | CPU | Critical for decisions | **Tier 1** |
| `_run_arb_scan` | 298 | Every 10s (2 ticks) | N/A | 867–3,147 | CPU + I/O | Secondary (opportunities) | **Tier 2** |
| `_refresh_liquidity` | 303 | Every 30s (6 ticks) | N/A | 868–3,149 | I/O (HTTP) | Relaxable (risk mgmt) | **Tier 2** |
| `_execute_plans` | 308 | Every tick | N/A | <500 | I/O | Critical for execution | **Tier 1** |
| `_update_cqi` | 312 | Every 300s (60 ticks) | N/A | <500 | CPU | Secondary (metrics) | **Tier 2** |
| `_sync_promotion` | 317 | Every 300s (60 ticks) | N/A | <100 | CPU | Secondary (reporting) | **Tier 2** |
| `_refresh_betting_odds` | 322 | Every 120s (24 ticks) | N/A | <1000 | I/O | Non-critical | **Tier 3** |
| `_reconcile_positions` | 327 | Every 120s (24 ticks) | N/A | <2000 | I/O | Critical (safety) | **Tier 1** |
| `_sync_order_groups` | 332 | **Every tick** ⚠️ | N/A | 869–3,150 | I/O | Tier 2 (can throttle) | **Tier 2** |
| `_reload_config` | 336 | Every 300s (60 ticks) | N/A | <100 | CPU | Tier 2 | **Tier 2** |
| `_notify` | 341 | Every tick | N/A | 2,675 | CPU | Secondary (observability) | **Tier 3** |

### Priority Tiers

**Tier 1 (must fit within tick budget):**
- `_refresh_features` (minimal subset for live trading)
- `_run_agent_cycles` (Kalshi agents)
- `_run_consensus` (final decisions)
- `_execute_plans` (trade execution)
- `_reconcile_positions` (safe cadence)

**Tier 2 (can be relaxed, staggered, or offloaded):**
- `_run_arb_scan` (can run less frequently)
- `_refresh_liquidity` (can use cached data)
- `_update_cqi`, `_sync_promotion` (can buffer)
- `_sync_order_groups` (⚠️ runs every tick, should throttle)

**Tier 3 (purely informative / deferred):**
- `_run_reflection_cycle` (learning, not time-critical)
- `_notify` (observability fan-out)
- `_refresh_betting_odds` (non-essential)

---

## Step 2 — Root Cause Analysis per Heavy Step

### 2.1 `_refresh_features` (1,370–4,700 ms) ⚠️ CRITICAL

**Current Implementation** (lines 359-395):
```python
# Sequential per-symbol processing
for symbol in self.config.active_symbols:
    news = svc.get_news_features(symbol, now=now)
    social = svc.get_social_features(symbol, now=now)
    chain = "solana" if symbol in ("SOL", "BONK", "WIF") else "ethereum"
    onchain = svc.get_onchain_features(chain, symbol, now=now)
    for fs in [news, social, onchain]:
        store.store_feature_snapshot(fs.to_dict())
```

**Issues**:
1. Sequential iteration (no parallelization)
2. SQLite reads + live HTTP calls in each iteration
3. No caching of features that haven't changed
4. Runs for all symbols even if only a subset needs refresh

**Proposed Fixes**:
- ✅ Parallelize symbol processing with `asyncio.gather()`
- ✅ Add feature staleness check (skip if fresh)
- ✅ Batch symbol processing (max N per tick)
- ✅ Cache macro features (low change frequency)

### 2.2 `_run_consensus` (866–3,149 ms)

**Current Implementation** (lines 618-715):
```python
# Sequential opinion submission (lines 490-515 in _run_kalshi_agent_cycle)
for sig in recent_signals:
    # ... build opinion ...
    await coordinator.submit_opinion(opinion)
    opinions_submitted += 1

# Sequential consensus cycles (lines 650-656)
for sym in pending_symbols:
    plan = await coordinator._run_consensus_cycle(sym)
```

**Issues**:
1. Sequential opinion submission (no batching)
2. Sequential consensus cycles for multiple symbols
3. Debate store queries in tight loop (lines 684, 696)

**Proposed Fixes**:
- ✅ Batch opinion submissions
- ✅ Parallelize consensus cycles for independent symbols
- ✅ Pre-fetch debate data to avoid repeated queries
- ✅ Add timeout per consensus cycle

### 2.3 `_refresh_liquidity` (868–3,149 ms)

**Current Implementation** (lines 717-796):
```python
# Sequential orderbook polling (lines 756-790)
for ticker in tickers:
    ob = await client.get_orderbook(ticker)
    # process...
```

**Issues**:
1. Sequential HTTP calls for each market
2. No timeout per market
3. No concurrency limit
4. Runs every 30s regardless of tick load

**Proposed Fixes**:
- ✅ Parallelize orderbook fetches with `asyncio.gather()`
- ✅ Add per-market timeout (e.g., 500ms)
- ✅ Limit concurrent fetches (e.g., 10 at a time)
- ✅ Skip if previous tick still running (backpressure)

### 2.4 `_sync_order_groups` (869–3,150 ms) ⚠️ RUNS EVERY TICK

**Current Implementation** (lines 1125-1160):
```python
# Runs EVERY tick without throttling
if "prediction" in self.config.active_domains:
    await self._sync_order_groups(summary)
```

**Issues**:
1. No cadence control — runs every tick
2. Lifecycle validation can be expensive
3. No skip logic when no active orders

**Proposed Fixes**:
- ✅ Add configurable interval (e.g., every 30s like liquidity)
- ✅ Skip if no active order groups
- ✅ Add timeout

### 2.5 `_notify` (2,675 ms)

**Current Implementation** (lines 1170-1178):
```python
# Fan-out to all subscribers
for cb in self._subscribers:
    if asyncio.iscoroutinefunction(cb):
        await cb(event_type, data)
    else:
        cb(event_type, data)
```

**Issues**:
1. Sequential notification of all subscribers
2. No timeout per subscriber
3. Blocking subscribers can delay entire tick
4. No filtering (all subscribers get all events)

**Proposed Fixes**:
- ✅ Parallelize subscriber notifications
- ✅ Add timeout per subscriber (e.g., 100ms)
- ✅ Offload to background task queue
- ✅ Add subscriber filtering

---

## Step 3 — Design: Work Slicing and Batching

### 3.1 Symbol Batching for Features

**Current**: Process all symbols every 30s
**Proposed**: Process N symbols per tick, round-robin

```python
# Add to __init__
self._feature_batch_size = 2  # symbols per tick
self._feature_symbol_idx = 0  # round-robin cursor

# In _refresh_features
symbols_to_process = []
for i in range(self._feature_batch_size):
    idx = (self._feature_symbol_idx + i) % len(self.config.active_symbols)
    symbols_to_process.append(self.config.active_symbols[idx])
self._feature_symbol_idx = (self._feature_symbol_idx + self._feature_batch_size) % len(self.config.active_symbols)

# Process batch in parallel
tasks = [self._fetch_symbol_features(sym, now, svc, store) for sym in symbols_to_process]
await asyncio.gather(*tasks, return_exceptions=True)
```

**Expected Impact**:
- Cost per tick: 4,700ms / 3 symbols * 2 symbols ≈ 3,133ms → **<1,567ms** (50% reduction)
- Full coverage: Every 3 ticks (15s vs 30s)

### 3.2 Parallel Liquidity Refresh

**Current**: Sequential HTTP calls
**Proposed**: Concurrent with semaphore

```python
semaphore = asyncio.Semaphore(10)  # max 10 concurrent

async def fetch_with_timeout(ticker):
    async with semaphore:
        try:
            return await asyncio.wait_for(
                client.get_orderbook(ticker),
                timeout=0.5  # 500ms per market
            )
        except asyncio.TimeoutError:
            logger.warning(f"Orderbook timeout for {ticker}")
            return None

tasks = [fetch_with_timeout(t) for t in tickers]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Expected Impact**:
- Cost per tick: 3,149ms / 20 markets → **~315ms** (10x speedup with 10 concurrent)

### 3.3 Throttle Order Group Sync

**Current**: Runs every tick
**Proposed**: Run every 30s like liquidity

```python
# Add to __init__
self._last_order_group_sync = 0.0
self._order_group_sync_interval = 30.0

# In tick()
if "prediction" in self.config.active_domains:
    if now - self._last_order_group_sync >= self._order_group_sync_interval:
        await self._sync_order_groups(summary)
        self._last_order_group_sync = now
```

**Expected Impact**:
- Eliminate 3,150ms cost from ~50% of ticks

---

## Step 4 — Backpressure and Tick Scheduler

### 4.1 Add Tick Overlap Detection

```python
# Add to __init__
self._tick_in_progress = False
self._last_tick_duration_ms = 0.0

# In tick()
if self._tick_in_progress:
    logger.warning("Tick overlap detected - previous tick still running")
    summary["tick_overlap"] = True
    # Skip non-critical steps
    return summary

self._tick_in_progress = True
try:
    # ... existing tick logic ...
finally:
    self._tick_in_progress = False
```

### 4.2 Skip Non-Critical Steps Under Pressure

```python
# After computing elapsed time
if self._last_tick_duration_ms > 4000:  # >4s = pressure
    logger.warning(f"Tick pressure detected ({self._last_tick_duration_ms}ms) - skipping Tier 3 steps")
    skip_tier3 = True
```

### 4.3 Add Per-Step Timeouts

```python
async def _run_with_timeout(self, coro, timeout_ms, step_name):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_ms / 1000.0)
    except asyncio.TimeoutError:
        logger.error(f"Step {step_name} exceeded timeout of {timeout_ms}ms")
        return None

# Usage
await self._run_with_timeout(
    self._refresh_features(now, summary),
    timeout_ms=2000,
    step_name="_refresh_features"
)
```

---

## Step 5 — Thread Pool Quotas

### Current State
From problem statement: "Thread pool (32 workers) shared across reflection, features, arb_scan, CQI, notify"

### Proposed Fix
Create dedicated executors for different workload types:

```python
# In __init__
import concurrent.futures
self._io_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="merid-io"
)
self._cpu_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="merid-cpu"
)

# Usage in I/O-bound steps
await loop.run_in_executor(
    self._io_executor,  # dedicated pool
    blocking_io_call
)
```

---

## Step 6 — Upstream/Downstream Audit

### 6.1 Features (_refresh_features)

**Upstream**:
- Live feed manager (`merid/signals/live_feeds.py`)
- Feature service (`merid/signals/features.py`)
- Signal store (SQLite)

**Check for**:
- ✅ Redundant live feed subscriptions
- ✅ Duplicate feature queries
- ✅ Unbounded SQLite query scans

**Downstream**:
- Signal store consumers (agents, consensus)

**Check for**:
- ✅ Multiple consumers re-fetching same features
- ✅ Feature cache invalidation bugs

### 6.2 Consensus (_run_consensus)

**Upstream**:
- Agent opinion submissions (line 514 in loop.py)
- Debate store queries (lines 684, 696)

**Check for**:
- ✅ Redundant opinion submissions
- ✅ Debate store query N+1 problem

**Downstream**:
- Approved plans → execution

**Check for**:
- ✅ Plan expiry causing re-work
- ✅ Duplicate plan validation

### 6.3 Liquidity (_refresh_liquidity)

**Upstream**:
- Agent grid ticker collection (lines 732-739)

**Check for**:
- ✅ Duplicate tickers in collection
- ✅ Stale ticker references

**Downstream**:
- Liquidity monitor alerts
- Agent stop-loss price updates (lines 780-787)

**Check for**:
- ✅ Redundant price updates
- ✅ Alert fan-out overhead

---

## Step 7 — Implementation Phases

### Phase 1: Quick Wins (Target: P95 <500ms)
1. ✅ Throttle `_sync_order_groups` (every 30s instead of every tick)
2. ✅ Parallelize liquidity refresh with semaphore + timeout
3. ✅ Add tick overlap detection
4. ✅ Add per-step timeouts (Tier 1 steps only)

**Expected Impact**: Remove 3,150ms from 50% of ticks → **P95 ~400ms**

### Phase 2: Feature Optimization
1. ✅ Implement symbol batching (2 symbols per tick)
2. ✅ Parallelize symbol processing
3. ✅ Add feature staleness check
4. ✅ Cache macro features

**Expected Impact**: 4,700ms → <1,500ms → **P95 ~300ms**

### Phase 3: Consensus Optimization
1. ✅ Batch opinion submissions
2. ✅ Parallelize consensus cycles
3. ✅ Pre-fetch debate data
4. ✅ Add consensus cycle timeout

**Expected Impact**: 3,149ms → <800ms → **P95 ~250ms**

### Phase 4: Advanced (If needed)
1. ⬜ Dedicated thread pool quotas
2. ⬜ Offload notify to background queue
3. ⬜ Implement tick scheduler with backpressure
4. ⬜ Add per-step cost budget tracking

---

## Step 8 — Validation Plan

### Pre-Implementation Baseline
Run 30-minute paper gate and collect:
- Per-step duration (add logging)
- P50/P95/P99 tick duration
- Number of tick overlaps
- Number of timeouts per step

### Post-Implementation Validation
After each phase:
1. Run 5-minute smoke gate
2. Check P95 tick duration
3. Verify no dropped trades
4. Confirm all computations aligned
5. Update fix_history.md

### Success Criteria
- ✅ P95 tick duration <500ms sustained
- ✅ No tick overlaps under normal load
- ✅ No available trades dropped (execution ratio unchanged)
- ✅ All features/signals/consensus aligned
- ✅ No new errors or exceptions

---

## Step 9 — Safety Guardrails

### No Functional Changes
- All optimizations are performance-only
- No changes to trading logic
- No changes to risk management
- No changes to execution gates

### Preserve Correctness
- Work slicing must maintain full coverage
- Batching must not drop any symbols/markets
- Timeouts must not silently fail critical operations
- Backpressure must not create deadlocks

### Monitoring
- Add per-step duration metrics
- Log timeout events at WARNING level
- Track tick overlap frequency
- Monitor execution ratio (proposals → fills)

---

## Next Steps

1. Create baseline profiling data (see Step 8)
2. Implement Phase 1 (quick wins)
3. Validate with 5-minute smoke gate
4. Iterate through Phases 2-4 as needed
5. Final validation with 30-minute paper gate
6. Update fix_history.md with results

---

## References

- `merid/loop.py` — Main event loop implementation
- `fix_history.md` — Event loop lag fixes (already completed)
- `VALIDATION_GUIDE.md` — Validation procedures
- `PRE_LIVE_CHECKLIST.md` — Pre-live requirements
- Problem statement — Tick processing requirements
