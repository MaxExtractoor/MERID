# Position Reconciliation Audit

## Overview
Audit of Kalshi position reconciliation between local state (`KalshiPositionCache`) and Kalshi REST API (`client.get_positions()`).

---

## Components Audited

### 1. KalshiPositionCache (`merid/event_venues/kalshi/position_cache.py`)

#### sync_from_rest() Method (Lines 434-479)
**Purpose:** Sync cache with REST API positions as fallback/reconciliation

**Implementation:**
```python
async def sync_from_rest(self, positions: list) -> None:
    async with self._mutex:
        try:
            self._positions.clear()
            for pos in positions:
                market_id = pos.get("market_id") or pos.get("ticker")
                if not market_id:
                    continue
                
                # Filter out test positions
                if _is_test_ticker(market_id):
                    logger.debug(f"Skipping test ticker in position cache sync: {market_id}")
                    continue

                contracts = int(pos.get("contracts", 0))
                
                # Only cache open positions (contracts > 0)
                if contracts == 0:
                    logger.debug(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
                    continue

                self._positions[market_id] = CachedPosition(...)
            
            self._last_sync = datetime.now(timezone.utc)
            logger.info(f"Position cache synced from REST: {len(self._positions)} positions (test & closed filtered)")
        except Exception as e:
            logger.error(f"Position cache sync from REST failed: {e}")
```

**Strengths:**
- ✅ Async with mutex protection for thread safety
- ✅ Filters out test positions (prevents bleeding into production)
- ✅ Filters out closed positions (contracts=0) to prevent phantom positions
- ✅ Updates `_last_sync` timestamp for staleness detection
- ✅ Exception handling with logging

**Weaknesses:**
- ⚠️ **Clears entire cache before sync** - loses TP targets from existing positions
- ⚠️ No drift detection - doesn't compare old vs new positions before clearing
- ⚠️ No reconciliation of partial fills - assumes REST API is always correct

**Recommendations:**
1. Preserve TP targets from existing cache during sync (like `venue_adapter.py` does)
2. Add drift detection before clearing cache
3. Log positions being removed for audit trail

---

### 2. FillsPoller (`merid/event_venues/kalshi/fills_poller.py`)

#### Reconciliation Logic (Lines 360-409)
**Purpose:** Periodic reconciliation of positions with Kalshi REST API

**Implementation:**
```python
# Fetch positions from REST API
positions = []
for ticker, mp in self._market_positions.items():
    if ticker and contracts > 0:
        positions.append({
            "market_ticker": ticker,
            "contracts": contracts,
            "side": mp.get("side", "yes"),
            "avg_price_cents": int(mp.get("avg_price_cents", mp.get("avg_price", 0))),
        })

# Run reconciliation with fills_ledger
ledger = get_fills_ledger()
report = await ledger.reconcile_with_kalshi_positions(positions)
self._last_reconcile_report = report

# Sync position cache with ground truth from Kalshi REST API
if report.get("status") in ("ok", "degraded", "broken"):
    cache = get_position_cache()
    await cache.sync_from_rest(positions)
    logger.info(f"Position cache synced from REST API (single source of truth): {len(positions)} positions")
    
    # Resync category_contracts counter
    risk_mgr = get_kalshi_risk()
    risk_mgr.resync_category_contracts_from_positions()
    
    # Detect cache vs ledger divergence
    _CACHE_LEDGER_DIVERGENCE_THRESHOLD = 5
    _cache_positions = cache.get_all_positions()
    _ledger_positions = ledger.compute_net_positions()
    # ... divergence detection logic
```

**Strengths:**
- ✅ Uses REST API as "single source of truth"
- ✅ Reconciles with fills_ledger before syncing cache
- ✅ Resyncs category_contracts counter after position sync
- ✅ Detects cache vs ledger divergence with threshold
- ✅ Syncs even in "degraded" or "broken" status (fail-safe)

**Weaknesses:**
- ⚠️ No automatic trigger on WS sequence gaps
- ⚠️ No staleness-based trigger (only periodic)
- ⚠️ Divergence detection logic not shown in snippet (may be incomplete)

**Recommendations:**
1. Add reconciliation trigger on WS sequence gaps
2. Add staleness-based trigger (e.g., if cache > 5 min old)
3. Complete divergence detection logic

---

### 3. FillsLedger (`merid/event_venues/kalshi/fills_ledger.py`)

#### reconcile_with_kalshi_positions() Method (Lines 1632-1729)
**Purpose:** Compare computed positions from fills vs Kalshi-reported positions

**Implementation:**
```python
async def reconcile_with_kalshi_positions(self, kalshi_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    divergences = []
    matched = 0
    ghost_trade_candidates = 0
    checked_markets: Set[str] = set()
    
    for kalshi_pos in kalshi_positions:
        ticker = kalshi_pos.get("market_ticker") or kalshi_pos.get("ticker")
        if not ticker:
            continue
        
        checked_markets.add(ticker)
        computed = await self.compute_position_from_fills_async(ticker)
        
        kalshi_contracts = int(kalshi_pos.get("contracts", 0) or kalshi_pos.get("count", 0))
        kalshi_side = kalshi_pos.get("side", "yes")
        kalshi_avg_price_cents = int(kalshi_pos.get("avg_price_cents", 0) or kalshi_pos.get("avg_price", 0))
        
        if computed is None:
            # Kalshi has position but we have no fills — ghost trade candidate
            if kalshi_contracts > 0:
                ghost_trade_candidates += 1
                divergences.append({
                    "type": "position_without_fills",
                    "market": ticker,
                    "kalshi_contracts": kalshi_contracts,
                    "kalshi_side": kalshi_side,
                    "ledger_contracts": 0,
                    "contract_diff": kalshi_contracts,
                    "pct_diff": 100.0,
                })
            continue
        
        our_contracts = computed["contracts"]
        our_side = computed["side"]
        our_avg_price_cents = computed["avg_price_cents"]
        
        contract_diff = abs(kalshi_contracts - our_contracts)
        price_diff_cents = abs(kalshi_avg_price_cents - our_avg_price_cents)
        
        if kalshi_contracts > 0:
            pct_diff = (contract_diff / kalshi_contracts) * 100.0
        else:
            pct_diff = 100.0 if our_contracts > 0 else 0.0
        
        side_mismatch = kalshi_side != our_side
        
        if contract_diff > 0 or side_mismatch or price_diff_cents > 1:
            divergences.append({
                "type": "side_mismatch" if side_mismatch else "contract_divergence",
                "market": ticker,
                "kalshi_contracts": kalshi_contracts,
                "kalshi_side": kalshi_side,
                "kalshi_avg_price_cents": kalshi_avg_price_cents,
                "ledger_contracts": our_contracts,
                "ledger_side": our_side,
                "ledger_avg_price_cents": our_avg_price_cents,
                "contract_diff": contract_diff,
                "price_diff_cents": price_diff_cents,
                "pct_diff": round(pct_diff, 2),
            })
        else:
            matched += 1
            # Mark fills as reconciled
            for fill_id in self._fills_by_market.get(ticker, []):
                fill = self._fills[fill_id]
                fill.reconciled = True
                fill.reconciliation_ts = datetime.now(timezone.utc)
    
    # Check for fills without positions
    fills_without_positions = 0
    # ... logic for settled/closed markets
    
    return {
        "status": "ok" if len(divergences) == 0 else "degraded" if len(divergences) < 5 else "broken",
        "divergences": divergences,
        "matched": matched,
        "ghost_trade_candidates": ghost_trade_candidates,
        "fills_without_positions": fills_without_positions,
        "checked_markets": len(checked_markets),
    }
```

**Strengths:**
- ✅ Comprehensive comparison (contracts, side, avg_price)
- ✅ Detects ghost trades (Kalshi has position, no fills)
- ✅ Detects side mismatches
- ✅ Detects contract divergences with percentage calculation
- ✅ Detects price divergences
- ✅ Marks fills as reconciled for bookkeeping
- ✅ Returns status (ok/degraded/broken) based on divergence count
- ✅ Purely diagnostic - doesn't make risk decisions

**Weaknesses:**
- ⚠️ No automatic corrective action - only reports
- ⚠️ No integration with position cache sync (caller must do it)
- ⚠️ No threshold-based alerting (status is hardcoded: <5 = degraded, >=5 = broken)

**Recommendations:**
1. Add configurable thresholds for ok/degraded/broken status
2. Add automatic corrective action for known divergence types
3. Add integration with position cache sync for auto-correction

---

### 4. WebSocket Sequence Tracking (`merid/event_venues/kalshi/ws.py`)

#### _check_sequence() Method (Lines 931-959)
**Purpose:** Validate message sequence; detect gaps

**Implementation:**
```python
def _check_sequence(self, data: Dict[str, Any]) -> bool:
    seq = data.get("seq")
    if seq is None:
        return True  # not all channels have seq
    
    market_id = data.get("ticker") or data.get("market_ticker") or "global"
    last = self._last_seq.get(market_id)
    
    if last is not None and seq <= last:
        # Out-of-order / duplicate — drop
        logger.debug(f"WS seq duplicate/OOO: market={market_id} got={seq} last={last}")
        return False
    
    if last is not None and seq > last + 1:
        gap = seq - last - 1
        self._seq_gaps += gap
        logger.warning(
            f"WS seq gap: market={market_id} expected={last+1} got={seq} "
            f"gap={gap} total_gaps={self._seq_gaps}"
        )
        # Invalidate cached orderbook — need a fresh snapshot
        self._ob_initialised.discard(market_id)
        self._ob_snapshots.pop(market_id, None)
    
    self._last_seq[market_id] = seq
    return True
```

**Strengths:**
- ✅ Per-market sequence tracking
- ✅ Detects out-of-order/duplicate messages
- ✅ Detects sequence gaps
- ✅ Invalidates orderbook on sequence gaps (forces fresh snapshot)
- ✅ Logs sequence gaps with details (market, expected, got, gap, total)

**Weaknesses:**
- ⚠️ **No reconciliation trigger on sequence gaps** - only invalidates orderbook
- ⚠️ No integration with position cache sync
- ⚠️ No alerting on high sequence gap counts

**Recommendations:**
1. Add reconciliation trigger on sequence gaps (e.g., if gap > 10)
2. Add integration with position cache sync on sequence gaps
3. Add alerting on high sequence gap counts

---

### 5. WS Bridge Sequence Tracking (`merid/event_venues/kalshi/ws_bridge.py`)

#### Fill Sequence Tracking (Lines 1256-1268)
**Purpose:** Track sequence numbers for gap detection in fill events

**Implementation:**
```python
# Check for sequence gaps in fill events
seq = event.get("sequence") or event.get("seq") or event.get("msg_id")
if seq is not None and isinstance(seq, numbers.Integral) and not isinstance(seq, bool):
    if self._last_sequence is not None:
        expected = self._last_sequence + 1
        if seq > expected:
            gap = seq - expected
            self._sequence_gaps += gap
            logger.warning(
                f"WS fill sequence gap detected: expected {expected}, got {seq}, "
                f"gap={gap}, total_gaps={self._sequence_gaps}"
            )
    self._last_sequence = seq
```

**Strengths:**
- ✅ Tracks sequence numbers in fill events
- ✅ Detects sequence gaps
- ✅ Logs sequence gaps with details
- ✅ Exposes sequence_gaps in health metrics

**Weaknesses:**
- ⚠️ **No reconciliation trigger on sequence gaps** - only logs
- ⚠️ No integration with position cache sync
- ⚠️ No threshold-based alerting

**Recommendations:**
1. Add reconciliation trigger on sequence gaps
2. Add integration with position cache sync
3. Add threshold-based alerting

---

## Reconciliation Triggers

### Current Triggers
1. **Periodic polling** - FillsPoller runs reconciliation on schedule
2. **Manual trigger** - Can be called via API or script

### Missing Triggers
1. **WS sequence gaps** - Not triggering reconciliation
2. **Cache staleness** - Not triggering reconciliation
3. **WS reconnection** - Not triggering reconciliation
4. **Manual order placement** - Not triggering reconciliation

---

## Drift Detection

### Current Drift Detection
1. **FillsLedger vs Kalshi REST** - Compares computed positions vs API
2. **Cache vs Ledger** - Detects divergence with threshold (5 contracts)

### Missing Drift Detection
1. **Cache vs REST** - No direct comparison before sync
2. **Price drift** - Detected but no threshold-based alerting
3. **Side drift** - Detected but no automatic correction

---

## Recommendations

### High Priority
1. **Add reconciliation trigger on WS sequence gaps**
   - In `ws.py` `_check_sequence()`, trigger reconciliation if gap > threshold
   - In `ws_bridge.py`, trigger reconciliation on fill sequence gaps

2. **Preserve TP targets during cache sync**
   - Modify `position_cache.py` `sync_from_rest()` to preserve TP targets
   - Follow pattern from `venue_adapter.py` (lines 268-310)

3. **Add staleness-based reconciliation trigger**
   - In `FillsPoller`, check cache staleness before sync
   - Trigger reconciliation if cache > 5 min old

4. **Add drift detection before cache clear**
   - In `position_cache.py` `sync_from_rest()`, compare old vs new positions
   - Log positions being removed for audit trail

### Medium Priority
5. **Add configurable thresholds for reconciliation status**
   - Make ok/degraded/broken thresholds configurable via profile
   - Current hardcoded: <5 = degraded, >=5 = broken

6. **Add automatic corrective action for known divergences**
   - For ghost trades: log and alert
   - For side mismatches: log and alert
   - For contract divergences: log and sync

7. **Add reconciliation trigger on WS reconnection**
   - In `ws.py` `_reconnect()`, trigger reconciliation after successful reconnect
   - Ensures cache is in sync after connection loss

### Low Priority
8. **Add alerting on high sequence gap counts**
   - In `ws_bridge.py`, alert if `sequence_gaps` > threshold
   - In `ws.py`, alert if `seq_gaps` > threshold

9. **Add integration with position cache sync on sequence gaps**
   - In `ws.py` `_check_sequence()`, call `cache.sync_from_rest()` on gap
   - In `ws_bridge.py`, call `cache.sync_from_rest()` on fill sequence gap

---

## Test Scenarios Reference

See `docs/POSITION_RECONCILIATION_TEST_SCENARIOS.md` for detailed test scenarios covering:
- Normal fill reconciliation
- WebSocket disconnection mid-fill
- Partial fill handling
- Network timeout during position sync
- Sequence number gap detection
- Concurrent order + reconciliation
- Stale position cache detection
- Market expiry position cleanup
- Multi-market position drift
- Reconciliation loop stress test

---

## Conclusion

**Overall Assessment:** The reconciliation system is **partially implemented** with good diagnostic capabilities but **missing critical triggers** for automatic reconciliation.

**Strengths:**
- Comprehensive position comparison (contracts, side, avg_price)
- Good logging and diagnostics
- Thread-safe async operations
- Test position filtering
- Closed position filtering

**Weaknesses:**
- No automatic reconciliation on WS sequence gaps
- No staleness-based reconciliation trigger
- TP targets lost during cache sync
- No drift detection before cache clear
- No automatic corrective action

**Critical Fixes Needed:**
1. Add reconciliation trigger on WS sequence gaps
2. Preserve TP targets during cache sync
3. Add staleness-based reconciliation trigger
4. Add drift detection before cache clear
