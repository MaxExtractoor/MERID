# CRITICAL RISK BYPASS AUDIT - 2026-07-08

## EXECUTIVE SUMMARY
**SEVERITY: CRITICAL - IMMEDIATE ACTION REQUIRED**

The 15M Kalshi crypto trading system has a **critical bypass** that allows agents to trade beyond their allocated risk limits. The window-based risk tracking (3% per agent / 5% total per 15m window) is **NEVER ENFORCED** because exposure recording is missing from the order execution flow.

---

## CRITICAL FINDING #1: Window Exposure Recording Missing

### Location: `merid/event_venues/kalshi/order_router.py`

### Problem:
- Window limit checks exist at line 5923 (`envelope.check_window_limit()`)
- Orders that pass window checks proceed to venue submission
- **BUT `envelope.record_order_execution()` is NEVER called after submission**
- This means window exposure is never tracked
- The 3% per agent / 5% total per 15m window limits are **COMPLETELY BYPASSED**

### Evidence:
```python
# Line 5923: Window check exists
window_allowed, window_reason = envelope.check_window_limit(
    agent_id=_agent,
    order_notional_usd=order_notional_usd,
    current_ts=time.time()
)

# Line 5942: Order rejected if window limit exceeded
if not window_allowed:
    return OrderResult(status="rejected", reason=f"window_limit:{window_reason}")

# CRITICAL: After this point, if window_allowed=True, order proceeds to venue
# BUT record_order_execution() is NEVER called
# This means exposure is never tracked, so subsequent orders never see cumulative exposure
```

### Impact:
- Agents can execute unlimited orders within a 15m window
- The 3% per agent limit is not enforced
- The 5% total venue limit is not enforced
- Risk limits are **completely ineffective**

---

## CRITICAL FINDING #2: Position Closure Recording Exists But May Be Ineffective

### Location: `merid/event_venues/kalshi/position_cache.py` (lines 493, 848)

### Problem:
- `record_position_closure()` is called when positions close
- This should release window capacity
- **BUT if `record_order_execution()` is never called, there's no exposure to release**
- The closure recording is ineffective because exposure was never recorded

### Evidence:
```python
# Line 493: Closure recording exists
envelope.record_position_closure(
    agent_id=agent_id,
    position_notional_usd=position_notional_usd
)
```

### Impact:
- Window capacity release mechanism exists but is ineffective
- Even if exposure was recorded, the release path needs verification

---

## CRITICAL FINDING #3: Order Gate Check Exists But Not Integrated

### Location: `merid/event_venues/kalshi/order_gate.py` (line 928)

### Problem:
- `PreTradeGate.check()` calls `envelope.check_window_limit()`
- This is the correct enforcement point
- **BUT the order router path may bypass this gate in some cases**
- Need to verify all order paths go through `PreTradeGate.check()`

### Evidence:
```python
# Line 928: Window check in order gate
window_allowed, window_reason = envelope.check_window_limit(
    agent_id=agent_id,
    order_notional_usd=order_notional_usd,
    current_ts=time.time()
)
```

### Impact:
- If orders bypass `PreTradeGate.check()`, they bypass window limits entirely
- Need to audit all order entry points

---

## CRITICAL FINDING #4: Take Profit/Trailing Stop System Exists

### Location: `merid/position_management/position_monitor.py`

### Status:
- Ratchet profit floor logic exists (lines 351-487)
- Trailing stop logic exists (lines 542+)
- Extreme profit (99c) exit exists (lines 217+)
- These emit exit intents which route through `route_order_async`

### Problem:
- Exit orders may bypass window limit checks
- Exit orders should use custom limits to allow position closure
- Need to verify exit orders don't consume window capacity meant for entries

---

## CRITICAL FINDING #5: Refund Mechanism Exists for Business Rejects

### Location: `merid/event_venues/kalshi/venue_adapter.py` (line 564)

### Status:
- `refund_order_execution()` is called for Kalshi business rejects
- This correctly releases exposure for rejected orders

### Problem:
- This is good, but only covers business rejects
- Need to verify all rejection paths refund exposure

---

## REQUIRED FIXES

### Fix #1: Add `record_order_execution()` Call in Order Router
**File:** `merid/event_venues/kalshi/order_router.py`
**Location:** After successful venue submission (around line 5342)
**Action:** Call `envelope.record_order_execution()` after `mark_submitted()`

### Fix #2: Verify All Order Paths Go Through PreTradeGate
**Action:** Audit all order entry points to ensure they call `PreTradeGate.check()`

### Fix #3: Add Window Exposure Recording in Order Gate
**File:** `merid/event_venues/kalshi/order_gate.py`
**Location:** In `mark_submitted()` method
**Action:** Call `envelope.record_order_execution()` when order transitions to SUBMITTED

### Fix #4: Verify Exit Orders Use Custom Window Limits
**File:** `merid/event_venues/kalshi/order_gate.py`
**Location:** In `check_window_limit()` call for exit orders
**Action:** Pass `custom_per_agent_limit_pct=1.0` (100%) for exit orders to allow closure

### Fix #5: Add Refund for All Rejection Paths
**Action:** Ensure all rejection paths (gate rejection, venue rejection, timeout) call `refund_order_execution()`

---

## AUDIT CHECKLIST

- [ ] Add `record_order_execution()` in order_router.py after venue submission
- [ ] Add `record_order_execution()` in order_gate.py mark_submitted()
- [ ] Verify all order entry points use PreTradeGate.check()
- [ ] Verify exit orders use custom window limits (100% allowance)
- [ ] Verify all rejection paths call refund_order_execution()
- [ ] Test window limit enforcement with multiple orders
- [ ] Test window capacity release on position closure
- [ ] Test exit orders don't consume entry capacity
- [ ] Verify take profit/trailing stop orders work correctly
- [ ] End-to-end test of full trading cycle with window limits

---

## SEVERITY ASSESSMENT

**CRITICAL** - This bypass allows agents to trade beyond their allocated risk limits, potentially leading to:
- Unlimited exposure within 15m windows
- Violation of 3% per agent limit
- Violation of 5% total venue limit
- Uncontrolled risk accumulation
- Potential for significant losses beyond risk parameters

**IMMEDIATE ACTION REQUIRED** - Do not restart server until fixes are applied and verified.
