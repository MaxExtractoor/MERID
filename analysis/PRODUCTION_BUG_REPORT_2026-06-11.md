# Production Stack Bug Report
**Date**: 2026-06-11  
**Profile**: kalshi_crypto_15m_v2  
**Scope**: End-to-end data ingestion, trading, execution, and reconciliation

## Executive Summary

Conducted comprehensive multipass bug analysis across:
- **Pass 1**: Upstream (data ingestion, price feeds, market data APIs)
- **Pass 2**: Midstream (agent grid, signal generation)
- **Pass 3**: Downstream (trading, execution pipeline)
- **Pass 4**: End-to-end (reconciliation, order lifecycle)

**Critical Bugs Found**: 3  
**High Priority Bugs**: 2  
**Medium Priority Bugs**: 3  
**Low Priority Issues**: 2

---

## CRITICAL BUGS

### BUG #1: WebSocket Forwarder Impossible-OK Violation
**Severity**: CRITICAL  
**Location**: `merid/event_venues/kalshi/health_snapshot.py:117-200`  
**Component**: Health Snapshot / WebSocket Bridge

**Description**:
The WS_FORWARDER_IMPOSSIBLE_OK invariant is being violated consistently. The system claims WebSocket is healthy when:
- `ws_raw_messages_seen` = 0 (no raw messages received)
- `ws_events_enqueued` = 0 (no events queued)
- `ws_forwarder_events_processed` = 0 (no events processed)
- But `ws_connected=True` and `ws_healthy=True`

**Evidence**:
```
KALSHI-READINESS tick=4 status=unhealthy ws_connected=True ws_raw=0 ws_enq=0 ws_proc=0 catalog_state=ok spot_fresh=5/5 md_fresh=5/5 reasons=ws_forwarder_impossible_ok_violation
```

**Impact**:
- System marked as unhealthy despite having fresh spot/MD data
- May block trading even when REST fallback is working
- Causes false positive health failures

**Root Cause**:
The invariant check in `check_ws_forwarder_impossible_ok()` has a time-based violation check (30s threshold), but the WS bridge may be connected but not actually forwarding events due to subscription issues or WS message processing failures.

**Fix Required**:
1. Add WS subscription validation - verify actual tickers are subscribed
2. Add WS message processing heartbeat - verify forward loop is actually running
3. Improve fallback logic - if REST is healthy but WS is stalled, continue trading with degraded mode

---

### BUG #2: Spot Data Staleness Triggering False Unhealthy States
**Severity**: CRITICAL  
**Location**: `merid/loop_15m.py:638-639`  
**Component**: Unified Spot Service / Health Snapshot

**Description**:
Spot data for DOGE (and occasionally other assets) goes stale frequently, triggering degraded/unhealthy states even when other assets are healthy and trading should continue.

**Evidence**:
```
KALSHI-READINESS tick=19 status=unhealthy ws_connected=True ws_raw=17 ws_enq=14 ws_proc=14 catalog_state=ok spot_fresh=0/5 md_fresh=0/5 reasons=spot_error: DOGE reason=stale message=Spot data age 10.6s exceeds degrade threshold 10.0s
```

**Impact**:
- System enters unhealthy mode when single asset spot is stale
- Blocks trading for all assets, not just the stale one
- Violates degraded mode semantics (should trade healthy assets)

**Root Cause**:
The health snapshot aggregates spot freshness across all assets and flips to unhealthy if ANY asset is stale, rather than using per-asset readiness.

**Fix Required**:
1. Implement per-asset spot freshness tracking
2. Allow trading on assets with fresh spot data even if others are stale
3. Add spot service fallback for individual assets

---

### BUG #3: Depth Check Thresholds Too Permissive
**Severity**: CRITICAL  
**Location**: Depth check logic in agent grid  
**Component**: Agent Grid / Market State

**Description**:
Depth check thresholds are too low, allowing trading in illiquid markets:
- BTC: yes>=1, no>=10 (should be yes>=25, no>=25 per documentation)
- ETH: yes>=1, no>=10 (should be yes>=25, no>=25)
- SOL: yes>=1, no>=5 (should be yes>=25, no>=25)
- XRP: yes>=1, no>=5 (should be yes>=25, no>=25)
- DOGE: yes>=1, no>=3 (should be yes>=25, no>=25)

**Evidence**:
```
DEPTH-CHECK asset=ETH ticker=KXETH15M-26JUN102130-30 min_depth_yes=1 min_depth_no=4000 thresholds=(yes>=1, no>=10) sufficient=True
DEPTH-CHECK asset=SOL ticker=KXSOL15M-26JUN102130-30 min_depth_yes=1 min_depth_no=664 thresholds=(yes>=1, no>=5) sufficient=True
```

**Impact**:
- Trading in illiquid markets with insufficient depth
- Higher slippage risk
- Potential for failed fills or partial fills

**Root Cause**:
Depth thresholds are asset-specific but too low. Documentation states minimum should be 25 contracts on both sides.

**Fix Required**:
1. Raise all depth thresholds to yes>=25, no>=25
2. Add regime-aware depth thresholds (stricter in high volatility)
3. Add depth-based position sizing limits

---

## HIGH PRIORITY BUGS

### BUG #4: Time-to-Expiry Configuration Mismatch
**Severity**: HIGH  
**Location**: Config vs Code Invariant  
**Component**: Agent Grid / Config

**Description**:
Documentation invariant states minimum time to expiry is 3 minutes (180 seconds), but config uses 2.5 minutes (150 seconds).

**Evidence**:
- Code invariant: `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN = 3` (line 100 of agent_grid_15m.py)
- Config: `min_time_to_expiry_min: 2.5` (kalshi_crypto_15m.yaml)

**Impact**:
- Inconsistent behavior between documented strategy and actual execution
- May enter trades closer to expiry than intended
- Higher risk of expiry-related losses

**Fix Required**:
1. Align config with code invariant (raise to 3.0 minutes)
2. Add validation to ensure config matches invariants at startup

---

### BUG #5: Health Snapshot Timeout Risk
**Severity**: HIGH  
**Location**: `merid/loop_15m.py:628-631`  
**Component**: Loop / Health Snapshot

**Description**:
Health snapshot call has 5-second timeout in a 5-second loop cadence, risking cascade delays.

**Evidence**:
```python
snapshot = await asyncio.wait_for(
    asyncio.to_thread(get_kalshi_health_snapshot, loop_tick=cycle_id),
    timeout=5.0  # 5 second timeout
)
```

**Impact**:
- If health snapshot is slow, entire loop cadence is disrupted
- May cause missed trading opportunities
- Could trigger watchdog timeouts

**Fix Required**:
1. Reduce timeout to 2 seconds
2. Make health snapshot call non-blocking with cached result
3. Add fallback to last known healthy state if timeout occurs

---

## MEDIUM PRIORITY BUGS

### BUG #6: MD Freshness Count Logging Error
**Severity**: MEDIUM  
**Location**: `merid/loop_15m.py:680`  
**Component**: Loop / Logging

**Description**:
MD freshness count uses `len(snapshot.md_status)` as denominator instead of fixed 5.

**Evidence**:
```python
f"md_fresh={md_fresh_count}/{len(snapshot.md_status)}"
```

**Impact**:
- Misleading logging when MD status dict is incomplete
- Makes debugging harder

**Fix Required**:
Change to `f"md_fresh={md_fresh_count}/5"`

---

### BUG #7: Resting Order Tracking Not Persistent
**Severity**: MEDIUM  
**Location**: `merid/event_venues/kalshi/order_router.py:98-117`  
**Component**: Order Router

**Description**:
Resting order tracking uses in-memory dict that resets on restart.

**Evidence**:
```python
_resting_orders: Dict[str, RestingOrder] = {}  # In-memory, resets on restart
```

**Impact**:
- Lost resting order state on restart
- Edge decay monitoring fails after restart
- May miss cancel opportunities

**Fix Required**:
1. Persist resting orders to database
2. Restore on startup
3. Add cleanup for stale orders

---

### BUG #8: Reconciliation System Not Integrated
**Severity**: MEDIUM  
**Location**: `deployment/reconciliation_system.py`  
**Component**: Reconciliation

**Description**:
Reconciliation system exists but is not called in the main trading loop.

**Evidence**:
- No calls to reconciliation functions in loop_15m.py
- No reconciliation triggers in agent grid
- System appears unused

**Impact**:
- No automated position/balance reconciliation
- Manual reconciliation required
- Risk of undetected position mismatches

**Fix Required**:
1. Integrate reconciliation into loop cycle
2. Add automated reconciliation triggers
3. Add alerts for reconciliation failures

---

## LOW PRIORITY ISSUES

### ISSUE #1: CryptoSurfaceLoader Disabled for 15m Profile
**Severity**: LOW  
**Location**: `services/crypto_surface_loader.py:25-30`  
**Component**: Data Ingestion

**Description**:
CryptoSurfaceLoader raises ImportError for kalshi_crypto_15m_v2 profile.

**Impact**:
- Surface loader not available for 15m profile
- May limit data aggregation capabilities

**Fix Required**:
Remove profile guard or implement 15m-specific surface loader logic.

---

### ISSUE #2: Silent Exception Pass Pattern
**Severity**: LOW  
**Location**: Multiple files  
**Component**: Error Handling

**Description**:
Several instances of `except Exception: pass` pattern found in codebase.

**Impact**:
- Silent error swallowing
- Makes debugging harder

**Fix Required**:
Add logging to all exception handlers.

---

## Recommended Fix Priority

1. **CRITICAL - Fix Immediately**:
   - BUG #1: WebSocket Forwarder Impossible-OK Violation
   - BUG #2: Spot Data Staleness False Unhealthy States
   - BUG #3: Depth Check Thresholds Too Permissive

2. **HIGH - Fix This Week**:
   - BUG #4: Time-to-Expiry Configuration Mismatch
   - BUG #5: Health Snapshot Timeout Risk

3. **MEDIUM - Fix This Sprint**:
   - BUG #6: MD Freshness Count Logging Error
   - BUG #7: Resting Order Tracking Not Persistent
   - BUG #8: Reconciliation System Not Integrated

4. **LOW - Technical Debt**:
   - ISSUE #1: CryptoSurfaceLoader Disabled
   - ISSUE #2: Silent Exception Pass Pattern

---

## Test Coverage Requirements

All fixes must include:
1. Unit tests for the specific bug scenario
2. Integration tests for the affected component
3. Regression tests to prevent recurrence
4. End-to-end tests for trading flow validation

---

## Next Steps

1. Fix CRITICAL bugs with test coverage
2. Restart server and monitor logs
3. Validate order creation and fill execution
4. Validate reconciliation system
5. Update documentation with fixes
