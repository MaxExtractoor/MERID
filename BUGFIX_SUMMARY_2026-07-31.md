# Bugfix Summary - 2026-07-31

## Issues Identified and Fixed

### 1. **Resting Order Monitor Bug** (CRITICAL - FIXED)
**File**: `merid/event_venues/kalshi/resting_order_monitor.py`

**Problem**: 
```
[RESTING_ORDER_MONITOR] Failed to sync order status for d282cd43-c4f3-4369-ab76-6186b37bc769: 'PlacedOrder' object has no attribute 'get'
```

**Root Cause**: The code was treating `result.data` as a dictionary and calling `.get()` on it, but `get_order_result()` returns a `PlacedOrder` object (dataclass), not a dict.

**Fix**: Changed from dictionary-style access to attribute access:
```python
# Before (WRONG):
order_data = result.data
raw_status = order_data.get("status", "")
remaining_size = order_data.get("remaining_size", order_data.get("remaining_quantity", 0))

# After (CORRECT):
order_data = result.data
raw_status = order_data.status if order_data else ""
remaining_size = int(order_data.remaining_size) if order_data and order_data.remaining_size else 0
```

**Impact**: This bug prevented proper order status synchronization from Kalshi's portfolio endpoint, which could lead to stale order tracking and incorrect risk management decisions.

---

### 2. **Counter Sanity Mismatch** (FIXED)
**File**: `merid/loop_15m.py`

**Problem**:
```
WARNING | merid.loop_15m | [COUNTER-SANITY-WARNING] tick=100 candidate count mismatch: 2 candidates != 0 executed + 4 rejections (per-tick counters)
```

**Root Cause**: When an order was not submitted (`order_submitted=False`), the code was incrementing the `"other"` rejection counter in addition to the specific rejection category (e.g., `router_rejected`) that was already incremented in `_execute_candidate()`. This caused double-counting of rejections.

**Fix**: Removed the redundant `"other"` counter increment:
```python
# Before (WRONG):
else:
    self._rejection_counters["other"] += 1
    logger.warning(
        "[15m-LOOP] Order not submitted for ticker=%s (order_submitted=False) - counting as rejection",
        ticker
    )

# After (CORRECT):
else:
    # CRITICAL FIX (2026-07-31): Do NOT increment "other" counter here
    # The rejection is already counted in the specific category (router_rejected, etc.)
    # in _execute_candidate. Counting it again causes counter sanity mismatch.
    logger.warning(
        "[15m-LOOP] Order not submitted for ticker=%s (order_submitted=False) - rejection already counted in specific category",
        ticker
    )
```

**Impact**: This caused false warnings about counter mismatches, making it harder to detect real issues with order flow tracking.

---

## Issues Identified (Not Bugs - Working as Designed)

### 3. **Fills Ledger Identity Collisions**
**Log Pattern**:
```
WARNING | merid.event_venues.kalshi.fills_ledger | [FILLS-LEDGER] fill_id=2c2aa1d9-40cf-7b49-6012-316e32982bbb already seen in another source - potential identity collision
```

**Analysis**: This is the invariant checker working as designed. It detects when the same fill_id appears from multiple sources (WebSocket, REST API, backfill, replay). This is expected behavior for cross-source deduplication and prevents double-counting fills.

**Status**: No fix needed - this is a feature, not a bug.

---

### 4. **Incomplete Fills**
**Log Pattern**:
```
WARNING | merid.event_venues.kalshi.fills_ledger | Fill b9088706-791e-54f7-e088-651239360b34 still incomplete after HTTP upsert: count_fp=0 price_cents=46 yes_price=0.46 no_price=0.54
```

**Analysis**: The Kalshi API sometimes returns incomplete fill data (count_fp=0). The code already handles this by:
1. Warning about incomplete fills
2. Deriving count from proceeds when count is missing
3. Providing a `clear_incomplete_fills()` method to remove phantom fills
4. Using `is_incomplete()` to flag fills that should not be counted as positions

**Status**: No fix needed - this is a data quality issue from the Kalshi API that the code already handles correctly.

---

## Testing Recommendations

1. **Resting Order Monitor**: Verify that order status synchronization works correctly after the fix by:
   - Placing a test order
   - Checking that the resting order monitor can successfully sync its status
   - Verifying no more `'PlacedOrder' object has no attribute 'get'` errors

2. **Counter Sanity**: Verify that counter sanity checks no longer show false mismatches by:
   - Running the system for several ticks
   - Checking that `total_candidates == total_executed + total_rejections` holds true
   - Verifying that rejection breakdown is accurate

3. **Fills Ledger**: Monitor the fills ledger warnings to ensure they remain at expected levels and don't indicate actual data corruption.

---

## Files Modified

1. `merid/event_venues/kalshi/resting_order_monitor.py` - Fixed PlacedOrder object access
2. `merid/loop_15m.py` - Fixed double-counting of rejections

---

## Verification

Run the following to verify the fixes:
```bash
# Run tests for modified modules
pytest tests/test_global_slot_allocator.py tests/test_unified_sizing.py tests/test_continuous_reconciliation.py tests/test_exit_policy_backtester.py -v

# Monitor logs for the specific error patterns
# Should no longer see:
# - 'PlacedOrder' object has no attribute 'get'
# - COUNTER-SANITY-WARNING with mismatched counts
```
