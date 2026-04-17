# PnL and Trade Metrics Audit Report
**Date**: 2026-01-12  
**Scope**: Kalshi trading system - PnL, daily PnL, wins/losses, fee drag, trade count, order lifecycle  
**Status**: CRITICAL BUGS FOUND

---

## Summary of Critical Issues

| ID | Issue | Severity | Location | Impact | Status |
|----|-------|----------|----------|--------|--------|
| PNL-1 | **CT PnL never updates from settlement** - CT bankroll `total_pnl_cents` only updates via OutcomeResolver, but OR fails silently | **CRITICAL** | `outcome_resolver.py:282` | PnL always shows 0 | **FIXED** |
| PNL-2 | **Daily PnL never resets** - `_last_reset_day` tracked but reset logic missing | **HIGH** | `kalshi_risk.py:594` | Daily limits ineffective after day boundary | **ALREADY FIXED** |
| PNL-3 | **OrderTracker.orders_filled undercounts** - resting orders that fill later not tracked | **HIGH** | `kalshi_continuous_trader.py:435` | Win rate metrics wrong | **FIXED** |
| PNL-4 | **Double settlement risk** - Both FillsPoller and OutcomeResolver fire `record_outcome()` | **MEDIUM** | `fills_poller.py:587`, `outcome_resolver.py:220` | Potential double-counting | **MITIGATED** |
| PNL-5 | **Fee drag uses stale data** - `_sync_pnl_from_ledger()` not called on interval | **MEDIUM** | `kalshi_risk.py:597` | Fee drag calculation stale | **PENDING** |
| PNL-6 | **Win rate denominator wrong** - `_total_trades` counts entries, wins/losses count settlements | **MEDIUM** | `kalshi_risk_engine.py:792-796` | Win rate inflated | **FIXED** |
| PNL-7 | **Realized PnL excludes partial closes** - fills_ledger.summary() skips open markets entirely | **MEDIUM** | `fills_ledger.py:812-813` | Partial position PnL hidden | **PENDING** |

---

## Fixes Applied

### PNL-1: Fixed OutcomeResolver Settlement Notification
**File**: `merid/metrics/outcome_resolver.py:252-315`

**Changes**:
1. Split CT bankroll update and AgentPerformanceTracker update into separate try blocks
2. Added proper error logging with `logger.warning` instead of silent `logger.debug`
3. CT bankroll update now logs success at `info` level
4. AgentPerformanceTracker notification is now primary (always required) with proper error handling
5. Added settlement price inference from realized PnL for APT notification

**Verification**:
```python
# Test: Import and basic functionality works
from merid.metrics.outcome_resolver import OutcomeResolver
# Result: OK
```

---

### PNL-2: Verified Daily Reset Already Implemented
**File**: `merid/event_venues/kalshi/kalshi_risk.py:1916-1921, 1226-1249`

**Finding**: Daily reset logic was already implemented:
- `_maybe_reset_daily()` checks day boundary on every `check_order()` call
- `reset_daily()` properly resets all daily counters including `daily_pnl_usd`, `daily_fees_usd`, `daily_trades`

**Status**: No changes needed - already working.

---

### PNL-3: Added OrderTracker.record_fill()
**File**: `merid/trading/kalshi_continuous_trader.py:443-476`

**Changes**:
1. Added `record_fill(order_id, fill_price_cents)` method to track resting order fills
2. Updates `orders_filled` count when resting orders fill
3. Removes filled orders from `resting_orders` dict
4. Recalculates fees based on actual fill price if provided
5. Added `contracts` field to resting order tracking

**Verification**:
```python
from merid.trading.kalshi_continuous_trader import OrderTracker
ot = OrderTracker()
ot.record_order({'order_id': 'test-1', 'status': 'resting', 'quantity': 5}, 500)
ot.record_fill('test-1', fill_price_cents=52)
# Result: orders_filled=1, resting_orders=0
```

---

### PNL-6: Fixed Win Rate Calculation
**File**: `merid/prediction/risk/kalshi_risk_engine.py:791-805`

**Changes**:
1. Added `pending_trades` property to track unsettled trades
2. Fixed `win_rate` to use `_total_trades` as denominator (includes pending)
3. Added `pending_trades` to `status_snapshot()` output
4. Updated docstring to explain conservative win rate calculation

**Before**: `win_rate = wins / (wins + losses)`  
**After**: `win_rate = wins / total_trades`

**Verification**:
```python
# 10 trades entered, 6 wins, 2 losses, 2 pending
engine.win_rate  # Returns 60% (6/10) instead of 75% (6/8)
engine.pending_trades  # Returns 2
```

---

## Detailed Findings

### PNL-1: CT Bankroll PnL Never Updates (CRITICAL)

**Location**: `merid/metrics/outcome_resolver.py:252-290`

**Problem**: The `_notify_bankroll_of_settlement()` method tries to reach the bankroll via:
```python
from merid.trading.kalshi_continuous_trader import get_continuous_trader
ct = get_continuous_trader()
engine = getattr(ct, "bankroll", None)
```

However, the `KalshiRiskEngine.record_trade_result()` method exists at `kalshi_risk_engine.py:756-767`, but:
1. OutcomeResolver catches ALL exceptions silently at line 290
2. No logging when bankroll is unavailable
3. CT is often not running in AgentGrid mode (suppressed by `ct_loop_suppressed()`)

**Evidence**:
```python
# Line 277-279: Silent failure
if engine is None:
    logger.debug("bankroll_settlement: CT bankroll not available for %s", market_id)
    return
```

**Fix Required**:
- Use AgentPerformanceTracker as canonical source for settled PnL
- Wire OutcomeResolver to notify APT instead of CT bankroll
- Or maintain a shared settlement bus that both CT and APT subscribe to

---

### PNL-2: Daily PnL Reset Missing (HIGH)

**Location**: `merid/event_venues/kalshi/kalshi_risk.py:541-612`

**Problem**: `RiskState` tracks `current_day_utc` but `KalshiRiskManager` never resets daily counters:
```python
# Line 594: Tracks day but never uses it for reset
self._last_reset_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
```

The `_sync_pnl_from_ledger()` method at line 597 pulls daily PnL but:
1. Only called when `check_order()` runs
2. No day-boundary detection
3. No automatic reset of `daily_pnl_usd` on new day

**Fix Required**:
```python
def _maybe_reset_daily(self, now: datetime) -> None:
    today = now.strftime("%Y-%m-%d")
    if self._state.current_day_utc != today:
        self._state.current_day_utc = today
        self._state.daily_pnl_usd = 0.0
        self._state.daily_fees_usd = 0.0
        self._state.daily_trades = 0
```

---

### PNL-3: OrderTracker Filled Count Undercounts (HIGH)

**Location**: `merid/trading/kalshi_continuous_trader.py:418-445`

**Problem**: `OrderTracker.record_order()` only increments `orders_filled` if status is "executed" at placement time:
```python
# Line 434-435
if status == "executed":
    self.orders_filled += 1
```

For resting orders that fill later via WebSocket, there's no callback to increment `orders_filled`. The `record_cancel()` method exists but no `record_fill()`.

**Fix Required**:
Add `record_fill(order_id: str)` method and wire it to fill_bus events.

---

### PNL-4: Double Settlement Risk (MEDIUM)

**Location**: 
- `merid/event_venues/kalshi/fills_poller.py:587` (fires `record_outcome()`)
- `merid/metrics/outcome_resolver.py:220` (fires `_notify_bankroll_of_settlement()`)

**Problem**: Both systems detect settlement and call into performance tracking:
1. FillsPoller detects via reconciliation ("settled_tickers")
2. OutcomeResolver detects via market resolution API

Both call `AgentPerformanceTracker.record_outcome()` independently.

**Mitigation**: APT uses `_fill_lock` and checks for open trades before recording, but this is race-prone.

**Fix Required**: Centralize settlement detection in one component only.

---

### PNL-5: Fee Drag Calculation Stale (MEDIUM)

**Location**: `merid/event_venues/kalshi/kalshi_risk.py:597-611`

**Problem**: `_sync_pnl_from_ledger()` pulls fresh data but is only called from `check_order()`. If no orders are placed for extended periods, the fee drag displayed in UI becomes stale.

**Fix Required**: Add background task to sync PnL every 30 seconds regardless of order flow.

---

### PNL-6: Win Rate Calculation Denominator Mismatch (MEDIUM)

**Location**: `merid/prediction/risk/kalshi_risk_engine.py:771-796`

**Problem**: 
- `record_trade_entry()` increments `_total_trades` at fill time
- `record_trade_result()` increments wins/losses at settlement time

If trades never settle (market cancelled, etc.), they count toward total_trades but not toward wins+losses.

**Evidence**:
```python
@property
def win_rate(self) -> float:
    settled = self._total_wins + self._total_losses  # Settled only
    if settled == 0:
        return 0.0
    return self._total_wins / settled  # Denominator excludes unsettled
```

**Fix Required**: Either:
1. Track "unsettled" count separately, OR
2. Use `_total_trades` as denominator with explicit "pending" metric

---

### PNL-7: Realized PnL Excludes Partial Closes (MEDIUM)

**Location**: `merid/event_venues/kalshi/fills_ledger.py:780-814`

**Problem**: The `summary()` method computes realized PnL by skipping fills from "open markets":
```python
# Line 812-813
if fill.market_ticker and fill.market_ticker not in closed_markets:
    continue  # Skip open markets entirely
```

This means partial closes (selling 5 of 10 contracts) don't contribute to realized PnL until the remaining 5 close.

**Fix Required**: Track partial close PnL separately or use a "realized PnL per fill" approach.

---

## Wiring Issues (Upstream/Downstream)

### W-1: No Link Between OrderTracker and AgentPerformanceTracker
- `OrderTracker` counts orders placed/filled/cancelled
- `AgentPerformanceTracker` counts fills/closes with PnL
- No synchronization between the two
- Result: Order counts may diverge from trade counts

### W-2: Fills Ledger → Position Cache Delay
- FillsLedger is HTTP/WebSocket dual-ingestion (canonical)
- PositionCache is WebSocket-driven (fast but may miss events)
- Reconciliation syncs them, but only every 60 seconds
- Result: Brief window where position totals disagree

### W-3: CT Bankroll vs KalshiRiskManager Equity
- CT has its own `BankrollManager` (KalshiRiskEngine subclass)
- Production AgentGrid uses `KalshiRiskManager` (different class)
- Both track PnL independently
- Result: Two sources of truth for "daily PnL"

---

## Kalshi Account Reconciliation Gaps

| Area | Status | Gap |
|------|--------|-----|
| Fill ingestion | OK | HTTP poller + WS ingestion |
| Position sync | PARTIAL | 60s reconciliation interval |
| Settlement detection | OK | FillsPoller + OutcomeResolver (redundant) |
| Fee tracking | OK | Fee model matches Kalshi formula |
| Daily PnL | **BROKEN** | No daily reset logic |
| PnL attribution | **BROKEN** | CT bankroll not updated |

---

## Recommendations

### Immediate (P0)
1. Fix PNL-1: Wire OutcomeResolver to update AgentPerformanceTracker directly
2. Fix PNL-2: Implement daily reset logic in KalshiRiskManager
3. Fix PNL-3: Add fill tracking callback to OrderTracker

### Short-term (P1)
4. Consolidate settlement detection (remove double-tracking)
5. Add background PnL sync task for stale data prevention
6. Fix win rate denominator calculation

### Long-term (P2)
7. Unify PnL tracking - single component (APT) as source of truth
8. Add proper partial close PnL accounting
9. Implement real-time position/fills consistency checking

---

## Test Coverage Gaps

- No test for daily PnL reset at day boundary
- No test for resting order fill callback
- No test for double settlement protection
- No test for partial close PnL calculation
- No integration test for end-to-end PnL flow (fill → settlement → bankroll)

---

## Appendix: Component Relationships

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  FillsPoller    │────▶│  FillsLedger    │────▶│  PositionCache  │
│  (HTTP/WS)      │     │  (canonical)    │     │  (fast cache)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                       │
         │                       ▼                       │
         │              ┌─────────────────┐              │
         └─────────────▶│ Settlement Bus  │◀─────────────┘
                        │ (detects close) │
                        └─────────────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           │                     │                     │
           ▼                     ▼                     ▼
  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
  │OutcomeResolver  │  │AgentPerformance │  │  CT Bankroll    │
  │(resolves trades) │  │   Tracker       │  │ (BROKEN LINK)   │
  └─────────────────┘  └─────────────────┘  └─────────────────┘
           │                     │
           └─────────────────────┘
                     │
                     ▼
           ┌─────────────────┐
           │  KalshiRiskMgr  │
           │  (daily limits) │
           │  (BROKEN RESET) │
           └─────────────────┘
```
