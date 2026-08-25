# Pre-Trade Invariant Checklist
## One-Contract-Per-Asset-Per-15-Minute Rule Enforcement

**Purpose**: Ensure the system enforces one contract per asset per 15-minute window at execution time, not just signal time. This prevents duplicate orders, exposure violations, and race conditions.

**Date**: 2026-07-21  
**Context**: Fix for repeated buys in same asset despite $1.00 global cap and one-contract-per-asset rules.

---

## Critical Invariants (Must Hold Before Every Order Submission)

### 1. Asset-Window Identity Consistency
- [ ] **Canonical asset extraction**: Both loop and router use the same asset extraction logic (BTC/ETH/SOL/XRP/DOGE substring match)
- [ ] **Canonical window ID extraction**: Both loop and router extract window ID from ticker using `ticker.split("-")[-2]`
- [ ] **Asset-window key format**: Both loop and router use `f"{asset}:{window_id}"` format
- [ ] **Ticker normalization**: Both loop and router uppercase ticker before extraction

**Verification**: Log asset-window keys from both loop and router for the same candidate and confirm they match.

---

### 2. Source of Truth Alignment
- [ ] **Position cache**: Loop and router both query `get_position_cache().get_all_positions()` for existing positions
- [ ] **Resting order monitor**: Loop and router both query `get_resting_order_monitor().find_open_order()` for pending orders
- [ ] **Global allocator**: Router checks `global_allocator.has_pending_order(asset)` for allocator-level pending state
- [ ] **Slot allocator**: Router checks `slot_allocator.can_allocate()` for exposure cap enforcement

**Verification**: Ensure no stale cache reads by logging timestamp of last position cache sync before each check.

---

### 3. Blocking States (All Must Block New Orders)
- [ ] **Filled position**: Any position with `contracts > 0` in the same asset+window blocks new orders
- [ ] **Partial fill**: Even partial fills (e.g., 0.5 contracts) block new orders in the same asset+window
- [ ] **Resting order**: Any open resting order in the same asset+window blocks new orders
- [ ] **Pending order**: Any pending order tracked by global allocator blocks new orders
- [ ] **Allocated budget**: If global allocator has assigned budget to that asset+window, block new orders

**Verification**: Test with partial fill scenario - order 1 fills 0.5 contracts, order 2 should be rejected.

---

### 4. Edge Case Handling
- [ ] **Side flip**: If signal flips from YES to NO mid-window, still block if asset already has exposure
- [ ] **Price change**: Different price in same asset+window still blocks (asset+window key, not ticker+side+price)
- [ ] **Rejection retry**: Rejected order retried in same window should still be blocked if exposure exists
- [ ] **Cooldown expiry**: After cooldown expires, still check for existing positions/orders before allowing re-entry
- [ ] **Concurrent signals**: Multiple workers reading same open slot before allocator commit - allocator should serialize

**Verification**: Run concurrent signal test - two workers submit orders for same asset+window simultaneously, only one should succeed.

---

### 5. Global Cap Enforcement
- [ ] **$1.00 exposure cap**: Router checks `slot_allocator.get_total_exposure() + order_notional <= 1.00`
- [ ] **Per-asset limit**: Router checks `slot_allocator.can_allocate()` for MAX_POSITIONS_PER_ASSET=1
- [ ] **Venue cap**: Router checks venue-level limits before order submission
- [ ] **Exit order bypass**: Exit orders bypass all caps (position closure, not new exposure)

**Verification**: Test with 5 assets each at $0.20 exposure - 6th asset order should be rejected due to $1.00 cap.

---

## Test Matrix (Run Before Deployment)

### Test Case 1: First Order in Fresh Window
- **Setup**: No positions, no pending orders, fresh 15-minute window
- **Action**: Submit order for BTC in window W1
- **Expected**: Order accepted, position created
- **Verification**: Position cache shows BTC:W1 with contracts=1

### Test Case 2: Second Order Same Asset Same Window Different Price
- **Setup**: BTC:W1 has position with contracts=1 at price=50c
- **Action**: Submit order for BTC in window W1 at price=55c
- **Expected**: Order rejected (asset_window_position_exists)
- **Verification**: Router logs "asset_window_position_exists:BTC:W1"

### Test Case 3: Second Order Same Asset Same Window Opposite Side
- **Setup**: BTC:W1 has YES position with contracts=1
- **Action**: Submit NO order for BTC in window W1
- **Expected**: Order rejected (asset_window_position_exists)
- **Verification**: Router logs "asset_window_position_exists:BTC:W1"

### Test Case 4: Retry After Rejection
- **Setup**: BTC:W1 order rejected due to cap
- **Action**: Retry same order immediately
- **Expected**: Still rejected (position state unchanged)
- **Verification**: Router logs same rejection reason

### Test Case 5: Retry After Partial Fill
- **Setup**: BTC:W1 order partially filled (0.5 contracts)
- **Action**: Submit second order for BTC in window W1
- **Expected**: Order rejected (contracts > 0 blocks)
- **Verification**: Router logs "asset_window_position_exists:BTC:W1 (contracts=0.5)"

### Test Case 6: Concurrent Signal Arrival
- **Setup**: Two workers submit orders for BTC:W1 simultaneously
- **Action**: Both call route_order_async at same time
- **Expected**: One succeeds, one rejected (allocator serializes)
- **Verification**: Position cache shows exactly 1 contract, not 2

### Test Case 7: Cross-Asset Budget Competition
- **Setup**: BTC:W1 (0.20), ETH:W1 (0.20), SOL:W1 (0.20), XRP:W1 (0.20), DOGE:W1 (0.20)
- **Action**: Submit order for 6th asset at $0.20
- **Expected**: Order rejected (hard_exposure_cap_exceeded)
- **Verification**: Router logs "current_exposure=$1.00 + order_notional=$0.20 > $1.00 cap"

### Test Case 8: Side Flip Mid-Window
- **Setup**: BTC:W1 has YES position with contracts=1
- **Action**: Signal flips to NO, submit NO order for BTC:W1
- **Expected**: Order rejected (asset_window_position_exists)
- **Verification**: Router logs "asset_window_position_exists:BTC:W1"

### Test Case 9: Cooldown Expiry with Existing Position
- **Setup**: BTC:W1 has position, cooldown expires
- **Action**: Submit new order for BTC:W1
- **Expected**: Order rejected (position still exists)
- **Verification**: Router logs "asset_window_position_exists:BTC:W1"

### Test Case 10: Window Transition
- **Setup**: BTC:W1 has position, window transitions to W2
- **Action**: Submit order for BTC:W2
- **Expected**: Order accepted (different window)
- **Verification**: Position cache shows BTC:W1 and BTC:W2 both with contracts=1

---

## Failure Mode Diagnostics

### If Duplicate Orders Still Occur:
1. **Check asset-window key consistency**: Log keys from loop and router - they must match exactly
2. **Check position cache staleness**: Log timestamp of last sync - may be lagging
3. **Check resting order monitor**: May not be polling frequently enough
4. **Check global allocator state**: May not be writing pending order state before next cycle
5. **Check race condition**: Multiple workers may be reading before allocator writes

### If False Positives (Orders Rejected Incorrectly):
1. **Check window ID extraction**: May be extracting wrong window ID from ticker
2. **Check asset extraction**: May be misclassifying asset (e.g., DOGE vs DOGE-USD)
3. **Check position cache**: May have stale positions from previous windows
4. **Check resting order monitor**: May have stale orders from previous windows
5. **Check window transition logic**: May not be clearing state on window change

### If Exposure Cap Not Enforced:
1. **Check slot allocator**: May not be tracking exposure correctly
2. **Check order notional calculation**: May be using wrong price or count
3. **Check exit order bypass**: Exit orders may be incorrectly bypassing caps
4. **Check global allocator**: May not be enforcing per-asset limits

---

## Implementation Checklist

### Code Changes Required:
- [x] **agent_grid_15m.py**: Return candidates instead of executing directly
- [x] **loop_15m.py**: Add `_get_asset_window_key()` with canonical asset extraction
- [x] **loop_15m.py**: Add asset-window check using position cache and resting order monitor
- [x] **loop_15m.py**: Track asset-window key in `_executed_candidates_this_window`
- [x] **order_router.py**: Add asset-window check using position cache and resting order monitor
- [x] **order_router.py**: Use canonical asset extraction matching loop logic

### Logging Required:
- [ ] **Loop**: Log asset-window key for each candidate check
- [ ] **Router**: Log asset-window key for each order check
- [ ] **Position cache**: Log timestamp of last sync before each check
- [ ] **Resting order monitor**: Log open order ID when found
- [ ] **Global allocator**: Log pending order state when checked

### Monitoring Required:
- [ ] **Metric**: `asset_window_duplicate_rejections` - count of rejections due to existing asset-window exposure
- [ ] **Metric**: `position_cache_staleness_ms` - time since last position cache sync
- [ ] **Metric**: `resting_order_monitor_lag_ms` - time since last resting order poll
- [ ] **Metric**: `global_allocator_pending_orders` - count of pending orders per asset
- [ ] **Alert**: If asset-window duplicate rejection rate > 5% (indicates possible bug)

---

## Rollback Plan

If issues detected after deployment:
1. **Disable asset-window checks**: Set feature flag `ENABLE_ASSET_WINDOW_CHECKS=False`
2. **Fallback to ticker+side+price**: Revert to original duplicate check only
3. **Monitor exposure**: Closely monitor slot allocator for exposure violations
4. **Manual intervention**: If exposure cap exceeded, manually close positions
5. **Root cause analysis**: Review logs to identify specific failure mode

---

## References

- **Files Modified**:
  - `merid/prediction/agent_grid_15m.py` - Execution path fix
  - `merid/loop_15m.py` - Asset-window guard
  - `merid/event_venues/kalshi/order_router.py` - Pre-trade gate

- **Related Memories**:
  - Percentage-Based Allocation Pruning (2026-07-16)
  - Execution Disconnect Fix (2026-07-12)
  - Duplicate Order Bug Fix (2026-07-12)
  - Thesis Side Invariant Fix (2026-07-21)

- **Test Files**:
  - `tests/test_robustness_fixes_2026.py` - Duplicate detection tests
  - `tests/test_risk_parameter_alignment.py` - Risk limit tests
