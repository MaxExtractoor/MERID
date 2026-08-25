# High-Leverage Bugs Identified - Comprehensive Analysis

## Executive Summary

This document identifies **8 critical high-leverage bugs** across the MERID trading stack, focusing on Category 1 (State Synchronization) and Category 2 (Enforcement Gaps) which have the highest system-wide impact.

---

## CATEGORY 1: STATE SYNCHRONIZATION BUGS

### Bug 1: Position Cache - Race Condition Between WebSocket and REST Sync
**Component**: `merid/event_venues/kalshi/position_cache.py` (lines 2016-2215)

**Bug Description**: The position cache has a race condition where WebSocket fill events and REST API sync can update the same position concurrently. While `sync_from_rest` uses a mutex and `on_fill` uses a mutex, there's no coordination between them. REST sync can overwrite fresh WebSocket data with stale REST data.

**Impact**: System-wide - position state can become inconsistent, leading to incorrect exposure calculations and failed exit orders.

**Root Cause**: Separate mutexes for WebSocket (`_mutex`) and REST sync (`_ensure_mutex`), no cross-source validation or conflict resolution.

**Evidence**:
```python
# Line 676 - WebSocket fill uses its own mutex
async with self._ensure_mutex():
    # ... fill processing

# Line 2060 - REST sync uses separate mutex
async with self._ensure_mutex():
    # ... REST sync processing
```

**Fix Strategy**: Implement a single unified mutex for all position state updates, or implement a last-write-wins timestamp-based conflict resolution with validation.

**Priority**: Critical

---

### Bug 2: Position Cache - No Validation When Sync Sources Disagree
**Component**: `merid/event_venues/kalshi/position_cache.py` (lines 2095-2170)

**Bug Description**: When REST sync overwrites positions from WebSocket fills, there's no validation that the REST data is consistent with the fill ledger. The code preserves `thesis_side` from fills but doesn't validate other fields like `contracts`, `avg_price_cents`, etc.

**Impact**: Position cache can diverge from canonical fills ledger, causing incorrect PnL calculations and exposure tracking.

**Root Cause**: Missing cross-validation between REST sync data and fills ledger state.

**Evidence**:
```python
# Line 2095-2098 - Preserves thesis_side but no other validation
# CRITICAL FIX: Preserve existing positions to avoid overwriting correct side from fills
# Kalshi REST API always reports side="yes" (YES-side perspective), which would
# invert the side for NO positions. We preserve the fill-based side and only update
# size/price from REST.
existing_positions = dict(self._positions)
```

**Fix Strategy**: Add validation that REST sync data is consistent with fills ledger. If discrepancy detected, flag position as unhealthy and trigger reconciliation.

**Priority**: Critical

---

### Bug 3: Slot Allocator - Dead Code After Exception (Unreachable Code)
**Component**: `merid/risk/global_slot_allocator.py` (lines 593-603)

**Bug Description**: The `sync_with_position_cache` method has unreachable code after an exception handler. Lines 596-603 are dead code that will never execute because the function returns at line 595.

**Impact**: Slot cleanup logic is never executed, potentially leaving orphaned slots.

**Root Cause**: Early return in exception handler makes subsequent code unreachable.

**Evidence**:
```python
# Line 593-595
except Exception as e:
    logger.error("[SLOT-ALLOCATOR] Failed to sync with position cache: %s", e)
    return 0  # <-- Function returns here
    
# Lines 596-603 - DEAD CODE, never executes
total_exposure = self.get_total_exposure()
available = self.get_available_exposure()
logger.info(
    "[SLOT-ALLOCATOR] Cleared %d stale slots, total_exposure=$%.2f available=$%.2f",
    len(stale_slots), total_exposure, available
)
return len(stale_slots)
```

**Fix Strategy**: Remove dead code or move the cleanup logic before the exception handler.

**Priority**: Medium

---

### Bug 4: Slot Allocator - No Slot Release on All Error Paths
**Component**: `merid/risk/global_slot_allocator.py` (lines 228-365)

**Bug Description**: The `request_allocation` method validates the request before the atomic lock section (lines 256-275). If validation fails, it returns early without releasing any previously allocated slots. While this is correct for the validation phase, there's no `finally` block to ensure cleanup if an exception occurs during allocation.

**Impact**: Slot leaks can occur if exceptions happen during allocation, permanently reducing available exposure.

**Root Cause**: Missing `finally` block in allocation logic to handle unexpected exceptions.

**Evidence**:
```python
# Lines 256-275 - Validation outside lock, early returns
try:
    if request.entry_price_cents < self.MIN_ENTRY_CENTS:
        self._total_rejections += 1
        return False, f"Entry price {request.entry_price_cents}c below minimum", None
    # ... more validation
except ValueError as e:
    self._total_rejections += 1
    return False, str(e), None

# Lines 280-365 - Allocation inside lock, no finally block
with self._lock:
    # ... allocation logic
    # If exception occurs here, no cleanup
```

**Fix Strategy**: Add `finally` block to handle unexpected exceptions and ensure consistent state.

**Priority**: High

---

### Bug 5: Window Tracking - No Persistence, State Lost on Restart
**Component**: `merid/event_venues/kalshi/order_router.py` (lines 185-189)

**Bug Description**: Entry window tracking (`_asset_entry_windows`) is stored in-memory with no persistence. On restart, all window state is lost, potentially allowing duplicate entries in the same 15-minute window.

**Impact**: Per-asset entry limit enforcement can be bypassed after restart, leading to over-trading.

**Root Cause**: In-memory state without persistence mechanism.

**Evidence**:
```python
# Line 185-189 - In-memory state, no persistence
# CRITICAL FIX (2026-07-18): Per-asset entry window tracking (in-memory, resets on restart)
# Key: asset (BTC, ETH, SOL, XRP, DOGE) -> window_start timestamp (15-minute boundary)
# This enforces 1 entry per asset per 15-minute window across all order paths
_asset_entry_windows: Dict[str, int] = {}
_asset_entry_windows_lock = threading.Lock()
```

**Fix Strategy**: Implement window state persistence similar to slot allocator, or rebuild window state from position cache on startup.

**Priority**: High

---

### Bug 6: Window Tracking - Not Cleared on All Error Paths
**Component**: `merid/event_venues/kalshi/order_router.py` (lines 7928-7942)

**Bug Description**: Entry windows are cleared on exchange rejection (lines 7932-7942), but this is inside a try-except block. If the exception handler fails, the window may not be cleared. Additionally, windows are not cleared on other rejection paths (e.g., validation failures before submission).

**Impact**: Stale windows can permanently block trading for an asset.

**Root Cause**: Window clearing logic not in all rejection paths, exception handling can fail.

**Evidence**:
```python
# Lines 7932-7942 - Window clearing only on exchange rejection
if asset and intent.action.lower() == "buy":
    try:
        with _asset_entry_windows_lock:
            current_window = int(_time.time() // 900) * 900
            if _asset_entry_windows.get(asset) == current_window:
                del _asset_entry_windows[asset]
    except Exception as window_clear_err:
        logger.warning("[ORDER-ROUTER] Failed to clear entry window on rejection: %s", window_clear_err)
```

**Fix Strategy**: Add window clearing to all rejection paths with a `finally` block to ensure cleanup.

**Priority**: High

---

### Bug 7: Pending Orders - Timeout-Based Cleanup May Miss Edge Cases
**Component**: `merid/risk/profiles/global_allocator.py` (lines 118-123, 274-289)

**Bug Description**: Pending orders are cleared based on a 30-second timeout. However, if the system clock changes or there are timing issues, pending orders may persist indefinitely or be cleared prematurely. There's no validation that the pending order actually exists in the order gate.

**Impact**: Pending order tracking can desync from actual order state, allowing duplicate submissions or blocking legitimate orders.

**Root Cause**: Time-based cleanup without cross-validation with order gate state.

**Evidence**:
```python
# Lines 118-123 - Timeout-based tracking
self._pending_orders: Dict[str, str] = {}  # asset -> order_id (pending submission)
self._pending_order_timestamps: Dict[str, float] = {}  # asset -> submission timestamp
self._pending_order_timeout = 30.0  # 30 seconds timeout for pending orders

# Lines 274-289 - Timeout-based cleanup
if c.asset in self._pending_orders:
    time_since_submit = time.time() - self._pending_order_timestamps.get(c.asset, 0)
    if time_since_submit < self._pending_order_timeout:
        # Skip
    else:
        # Clear based on timeout only, no validation
        del self._pending_orders[c.asset]
```

**Fix Strategy**: Cross-validate pending order state with order gate before clearing. Add order status checks.

**Priority**: Medium

---

### Bug 8: Fills Ledger - No Validation of Fill Data Before Recording
**Component**: `merid/event_venues/kalshi/fills_ledger.py` (lines 3150-3160)

**Bug Description**: The `on_fill` method deduplicates fills by `fill_id` but doesn't validate the fill data itself (e.g., contracts > 0, price_cents in valid range, etc.). Invalid fills from Kalshi API could corrupt the ledger.

**Impact**: Corrupted fill data can lead to incorrect position calculations and PnL reporting.

**Root Cause**: Missing data validation before fill recording.

**Evidence**:
```python
# Lines 3150-3160 - Only deduplication, no data validation
def on_fill(self, fill: KalshiFill) -> None:
    """Handle fill event with position state machine."""
    # Deduplicate fills
    if fill.fill_id in self._processed_fill_ids:
        return
    self._processed_fill_ids.add(fill.fill_id)
    # No validation of fill data here
```

**Fix Strategy**: Add fill data validation (contracts > 0, price_cents in valid range, etc.) before recording.

**Priority**: High

---

## CATEGORY 2: ENFORCEMENT GAPS

### Bug 9: Multiple Enforcement Layers Without Coordination
**Component**: Multiple files (global_allocator.py, global_slot_allocator.py, order_router.py)

**Bug Description**: The system has 3 different enforcement layers (Slot Allocator, Global Allocator, Order Router) that make independent decisions without coordination. State can change between checks, causing race conditions.

**Impact**: Inconsistent enforcement, race conditions, potential bypass of limits.

**Root Cause**: No single enforcement gate, multiple independent checks.

**Evidence**: See architecture audit for enforcement point inventory.

**Fix Strategy**: Implement single pre-trade enforcement gate as outlined in Unified Position Manager design.

**Priority**: Critical

---

### Bug 10: No Atomic Transactions Across Enforcement Layers
**Component**: Multiple files (global_allocator.py, global_slot_allocator.py, order_router.py)

**Bug Description**: When an order is submitted, enforcement checks happen sequentially. If the order fails after slot allocation, the slot may not be released properly, creating a "phantom slot."

**Impact**: Phantom slots can block future orders permanently.

**Root Cause**: No atomic transaction with rollback across enforcement layers.

**Evidence**: See architecture audit for data flow diagram.

**Fix Strategy**: Implement atomic operations with rollback as outlined in Unified Position Manager design.

**Priority**: Critical

---

## Summary

### Critical Priority (4 bugs)
1. Bug 1: Position Cache - Race Condition Between WebSocket and REST Sync
2. Bug 2: Position Cache - No Validation When Sync Sources Disagree
3. Bug 9: Multiple Enforcement Layers Without Coordination
4. Bug 10: No Atomic Transactions Across Enforcement Layers

### High Priority (4 bugs)
4. Bug 4: Slot Allocator - No Slot Release on All Error Paths
5. Bug 5: Window Tracking - No Persistence, State Lost on Restart
6. Bug 6: Window Tracking - Not Cleared on All Error Paths
8. Bug 8: Fills Ledger - No Validation of Fill Data Before Recording

### Medium Priority (2 bugs)
3. Bug 3: Slot Allocator - Dead Code After Exception
7. Bug 7: Pending Orders - Timeout-Based Cleanup May Miss Edge Cases

## Next Steps

1. Research best practices for each identified bug
2. Implement fixes starting with Critical priority
3. Add comprehensive tests for all changes
4. Ensure all tests pass before deployment
