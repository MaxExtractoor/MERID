# Live Path Fixes Summary - 2026-08-01

## Executive Summary

Fixed the **semantic leakage between entry and exit handling** that was causing the live execution path to fail. All 5 priority issues have been addressed with targeted fixes to the live execution code paths.

## Priority Fixes Applied

### 1. ✅ Verify Allocator Method Name and Runtime Deployment

**Issue:** `Failed to release entry slot for exit order ... no attribute 'release_slot_by_ticker'`

**Fix:** Added missing `release_slot_by_ticker` method to `GlobalSlotAllocator`

**File:** `merid/risk/global_slot_allocator.py`

**Changes:**
- Added `release_slot_by_ticker(ticker, exit_price_cents)` method
- Finds slots by ticker and releases them with PnL tracking
- Thread-safe with existing lock mechanism
- Comprehensive logging for debugging

**Impact:** Exit orders can now properly release entry slots, preventing slot leaks.

---

### 2. ✅ Fix Entry/Exit Intent Contract

**Issue:** `ENTRY-ORDER-INVARIANT-VIOLATION ... SELL actions are for exit trades only`

**Root Cause:** Bracket orders (TP/SL) were not properly marked as exit orders, causing them to pass through entry guards.

**Fix:** Updated bracket order creation and exit order detection

**Files:**
- `merid/event_venues/kalshi/position_cache.py`
- `merid/event_venues/kalshi/exit_order_utils.py`
- `merid/event_venues/kalshi/order_router.py`

**Changes:**
- Added `entry_or_exit="exit"` and `exit_reason` to bracket order intents
- Added `"resting_bracket"` to `EXIT_ORDER_MARKERS` in exit_order_utils.py
- Updated `is_exit_order_from_intent()` to check `entry_or_exit` field first
- Enhanced invariant violation logging with diagnostic context

**Impact:** Bracket orders now bypass entry guards correctly, preventing invariant violations.

---

### 3. ✅ Add Per-Filter Candidate Block Reason Counter

**Issue:** `NO-CANDIDATE` repeated across ticks with no visibility into which filter was blocking

**Fix:** Added diagnostic tracking for candidate generation blockers

**File:** `merid/prediction/agent_grid_15m.py`

**Changes:**
- Added `candidate_block_reasons` dict to track blocking reasons per asset
- Modified key return points to return `{"block_reason": "reason"}` instead of `None`
- Added logging for block reasons: `[CANDIDATE-BLOCK] asset=BTC reason=cooldown count=5`
- Updated cycle processing to detect and track block reasons

**Block Reasons Tracked:**
- `cooldown`
- `consecutive_loss_pause`
- `session_risk_cap`
- `no_spot_price`
- `no_contract_in_entry_window`

**Impact:** Full visibility into which filters are blocking candidate generation.

---

### 4. ✅ Search for Remaining 10c-75c Strings in Live Execution Paths

**Issue:** Old 10c-75c price range language still present in live code paths

**Fix:** Updated all references to canonical 5c-85c range

**Files Updated:**
- `merid/risk/profiles/crypto_15m_profile.py` - Updated profile price range to 5c-85c
- `merid/metrics/canonical_buckets.py` - Updated canonical range definition and function
- `merid/event_venues/kalshi/risk_parameters.py` - Updated rationale comment
- `merid/risk/profiles/test_global_allocator.py` - Updated test message
- `merid/prediction/test_regime_aware_price_filter.py` - Updated test docstring
- `merid/prediction/kalshi_15m_invariants.py` - Updated invariant documentation
- `merid/validation/parity_cycle_diagnostic.py` - Updated diagnostic documentation
- `merid/prediction/risk/_prediction_risk.py` - Updated spread comment
- `merid/event_venues/kalshi/invariants.py` - Updated spread comment

**Impact:** Consistent 5c-85c canonical range across all code paths.

---

### 5. ✅ Make Stale/Missing Market State Fail Closed

**Issue:** "Assuming fresh" graceful degradation allowing stale/missing market state to proceed

**Fix:** Implemented fail-closed policy with explicit exit order override

**File:** `merid/event_venues/kalshi/order_router.py`

**Changes:**
- **Missing market state:** Entry orders now rejected with `state_not_found:fail_closed_policy`
- **Missing timestamp:** Entry orders now rejected with `book_timestamp_missing:fail_closed_policy`
- **Exit orders:** Still allowed to proceed (must not be trapped)
- Added explicit `_is_exit_gate` checks for exit order override

**Impact:** Entry orders cannot proceed on stale/missing market data, preventing bad trades.

---

## Key Architectural Improvements

### Entry/Exit Separation
- Bracket orders now properly marked as exit orders with `entry_or_exit="exit"`
- Exit order detection uses `entry_or_exit` field first, then source markers
- Invariant checks include diagnostic context for debugging

### Fail-Closed Policy
- Entry orders require valid market state (no graceful degradation)
- Exit orders have explicit override to prevent being trapped
- Missing timestamps now cause rejection instead of "assuming fresh"

### Diagnostic Visibility
- Candidate block reasons tracked and logged per asset
- Invariant violations include full context (entry_or_exit, source, exit_policy_id)
- Slot release operations include PnL tracking

### Canonical Range Consistency
- All references updated to 5c-85c canonical range
- Profile configuration matches code implementation
- Test documentation aligned with current behavior

---

## Expected Log Changes

### Before Fixes
```
[ENTRY-ORDER-INVARIANT-VIOLATION] ticker=KXXRP15M-26AUG011315-15 side=yes action=sell kalshi_side=SELL_YES
Failed to release entry slot for exit order (non-critical): error='GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'
[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE] agent=BTC_15M
Book timestamp missing, assuming fresh (graceful degradation)
```

### After Fixes
```
[BRACKET-CREATION-DEBUG] TP intent created: side=yes action=sell price=80c count=1 entry_or_exit=exit
[order-router] EXIT ORDER FAST-PATH: KXXRP15M-26AUG011315-15 sell — bypassing execution gate
[SLOT-ALLOCATOR] Released slot by ticker: slot_id=xxx agent=BTC_15M ticker=KXXRP15M-26AUG011315-15
[CANDIDATE-BLOCK] asset=BTC reason=cooldown count=5
[order-router] Live order rejected — book timestamp missing (fail-closed): ticker=KXXRP15M-26AUG011315-15
```

---

## Verification Steps

1. **Test bracket order submission:**
   - Verify bracket orders set `entry_or_exit="exit"`
   - Confirm no `ENTRY-ORDER-INVARIANT-VIOLATION` messages
   - Check slot release succeeds without errors

2. **Test candidate generation diagnostics:**
   - Run live cycle and check for `[CANDIDATE-BLOCK]` logs
   - Verify block reasons are tracked per asset
   - Confirm block reason counts increment correctly

3. **Test fail-closed market state:**
   - Submit entry order with missing market state
   - Verify rejection with `fail_closed_policy` reason
   - Submit exit order with missing market state
   - Verify exit order proceeds (not trapped)

4. **Test canonical range:**
   - Verify all references use 5c-85c range
   - Check profile configuration matches
   - Confirm test documentation updated

---

## Runtime Deployment Notes

**Important:** The running process may need to be restarted to pick up the new `release_slot_by_ticker` method. If logs still show the missing method error after deployment:

1. Verify the updated `global_slot_allocator.py` is deployed
2. Restart the trading process
3. Check import paths are correct
4. Verify no cached .pyc files are using old code

---

## Remaining Monitoring Points

1. **Candidate Generation:** Monitor `[CANDIDATE-BLOCK]` logs to identify which filters are most restrictive
2. **Entry/Exit Separation:** Watch for any new `ENTRY-ORDER-INVARIANT-VIOLATION` messages
3. **Slot Management:** Monitor slot release success rate and PnL tracking
4. **Market State:** Track rejection rates due to stale/missing market state
5. **Price Range:** Verify no orders are rejected due to outdated range checks

---

## Files Modified

1. `merid/risk/global_slot_allocator.py` - Added `release_slot_by_ticker` method
2. `merid/event_venues/kalshi/position_cache.py` - Added `entry_or_exit` to bracket orders
3. `merid/event_venues/kalshi/exit_order_utils.py` - Added bracket marker and enhanced detection
4. `merid/event_venues/kalshi/order_router.py` - Enhanced invariant checks and fail-closed policy
5. `merid/prediction/agent_grid_15m.py` - Added candidate block reason tracking
6. `merid/risk/profiles/crypto_15m_profile.py` - Updated canonical range to 5c-85c
7. `merid/metrics/canonical_buckets.py` - Updated canonical range definition
8. `merid/event_venues/kalshi/risk_parameters.py` - Updated range comment
9. `merid/risk/profiles/test_global_allocator.py` - Updated test message
10. `merid/prediction/test_regime_aware_price_filter.py` - Updated test docstring
11. `merid/prediction/kalshi_15m_invariants.py` - Updated invariant documentation
12. `merid/validation/parity_cycle_diagnostic.py` - Updated diagnostic documentation
13. `merid/prediction/risk/_prediction_risk.py` - Updated spread comment
14. `merid/event_venues/kalshi/invariants.py` - Updated spread comment

---

## Next Steps

1. **Deploy changes** to live environment
2. **Restart trading process** to ensure new code is loaded
3. **Monitor logs** for the new diagnostic messages
4. **Verify** bracket orders no longer cause invariant violations
5. **Check** slot release operations succeed without errors
6. **Review** candidate block reason distribution
7. **Validate** fail-closed policy is working correctly
