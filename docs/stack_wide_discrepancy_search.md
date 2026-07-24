# Stack-Wide Discrepancy Search Results
## Date: 2026-07-21

### 1. Canonical Identity Handling ✅ COMPLETED

**Status**: Fixed and verified

**Discrepancies Found**:
- 10 files using ad-hoc asset extraction (split, replace, substring matching)
- Inconsistent asset extraction logic across layers

**Files Fixed**:
1. `merid/utils/kalshi_identity.py` - Created canonical identity helper module
2. `merid/loop_15m.py` - Replaced ad-hoc extraction with `extract_asset_window_key()`
3. `merid/event_venues/kalshi/order_router.py` - Replaced ad-hoc extraction with canonical helper
4. `merid/test_loop_15m_edge_improvement.py` - Replaced ad-hoc extraction with canonical helper
5. `merid/risk/profiles/window_allocator_integration.py` - Replaced ad-hoc extraction with canonical helper
6. `merid/risk/unified_risk_engine.py` - Replaced ad-hoc extraction with canonical helper
7. `merid/reconciliation/reconciliation_metrics.py` - Replaced ad-hoc extraction with canonical helper
8. `merid/prediction/unified_sizing.py` - Replaced ad-hoc extraction with canonical helper
9. `merid/prediction/strategy.py` - Replaced ad-hoc extraction with canonical helper
10. `merid/prediction/portfolio_risk_agent.py` - Replaced ad-hoc extraction with canonical helper

**Canonical Helper Functions**:
- `extract_asset(ticker)` - Extract canonical asset symbol (BTC/ETH/SOL/XRP/DOGE)
- `extract_window_id(ticker)` - Extract 15-minute window ID
- `extract_asset_window_key(ticker)` - Generate asset:window key
- `extract_series(ticker)` - Extract series identifier (KXBTC15M)
- `extract_market_id(ticker)` - Extract full market ID
- `parse_kalshi_ticker(ticker)` - Parse all components at once

**Verification**: All layers now use the same canonical extraction logic, ensuring consistency.

---

### 2. Limit and Cap Enforcement at All Layers ✅ FIXED

**Status**: High-leverage bug identified and fixed

**Layers Checked**:
- ✅ Signal selection: Agent grid uses global allocator
- ✅ Loop-level candidate filtering: Loop checks asset-window keys
- ✅ Router-level pre-trade gate: Router checks position cache, resting monitor, allocator
- ✅ **Legacy execution paths now route through router**

**Critical Finding (FIXED)**:
`merid/swarm/execution_subscriber.py` was calling `_kalshi_place_order` directly, bypassing all validation gates.

**Fixes Applied**:

1. **Hard deprecated `_kalshi_place_order` in production** (`merid/prediction/kalshi_tools.py`)
   - Added production guard that blocks direct execution
   - Checks `MERID_ENV` and `MERID_PM_PROFILE` for production mode
   - Added `ALLOW_DIRECT_EXECUTION` feature flag (default False)
   - Logs critical alert on bypass attempts
   - Returns PERMISSION_DENIED error in production

2. **Refactored execution_subscriber.py** (`merid/swarm/execution_subscriber.py`)
   - Replaced direct `_kalshi_place_order` calls with `order_router.route_order_async`
   - Converts execution_subscriber parameters to OrderIntent
   - Now enforces all router validation gates
   - Added proper error handling and logging

3. **Updated router source whitelist** (`merid/event_venues/kalshi/order_router.py`)
   - Added `execution_subscriber` to allowed sources for kalshi_crypto_15m_v2 profile
   - Maintains safety net against unexpected callers

**Execution Flow (NOW CORRECT)**:
```
execution_subscriber → order_router.route_order_async → validation gates → venue
```

**Validation Gates Now Enforced**:
- ✅ Asset-window duplicate checks
- ✅ Global $1 exposure cap
- ✅ One-contract-per-asset-per-15-minute rule
- ✅ Position cache validation
- ✅ Resting order monitor checks
- ✅ Global allocator pending order checks
- ✅ Slot allocator can_allocate checks

---

### 3. State Synchronization (Fills, Partial Fills, Rejections, Cancels) ✅ INVESTIGATED

**Status**: Investigation complete - existing protections are robust

**Position Cache Fill Updates** (`merid/event_venues/kalshi/position_cache.py`):
- ✅ `apply_fill()` method with mutex protection (async with self._ensure_mutex())
- ✅ Action-aware fill processing (buy vs sell, open vs close)
- ✅ Wrong-direction position change detection with critical alarms
- ✅ Expected post-size reconciliation logging
- ✅ `sync_from_rest()` with thesis_side preservation (immutable invariant)
- ✅ REST sync validation checks for side mismatches

**Resting Order Monitor State Updates** (`merid/event_venues/kalshi/resting_order_monitor.py`):
- ✅ `find_open_order()` checks for live (non-terminal, unfilled) orders
- ✅ Case-insensitive ticker/side/action matching
- ✅ Skips TERMINAL_STATUSES and remaining_size <= 0
- ✅ `get_orders_by_ticker()` for duplicate exit order detection
- ✅ Used by router anti-stacking guard

**Global Allocator Pending Order Tracking** (`merid/risk/profiles/global_allocator.py`):
- ✅ `_pending_orders` dict tracks asset -> order_id
- ✅ `_pending_order_timestamps` for staleness detection
- ✅ `has_pending_order()` with timeout-based cleanup (stale orders auto-cleared)
- ✅ Pending orders cleared on order submission success/failure
- ✅ Timeout: `_pending_order_timeout` prevents indefinite blocking

**Slot Allocator Slot Release** (`merid/risk/global_slot_allocator.py`):
- ✅ `release_slot()` for position closure
- ✅ `release_by_agent()` for agent-level cleanup
- ✅ `release_by_asset()` for asset-level cleanup
- ✅ Emergency reset for crash recovery
- ✅ Router calls `_release_allocated_slot()` on rejection

**Router Rejection Handling** (`merid/event_venues/kalshi/order_router.py`):
- ✅ `mark_rejected()` releases gate record and allocated slot
- ✅ Called on all early-exit rejection paths
- ✅ Uses intent_id as fallback when client_tag missing
- ✅ Prevents slot leaks on rejections

**Potential Issues Identified**:
- ⚠️ Resting order monitor polling latency (30s) could cause stale state in fast-moving markets
- ⚠️ Global allocator pending order timeout may not be configured for 15m cycle
- ⚠️ No explicit partial fill handling in slot allocator (assumes full fills)

**Recommendations**:
1. Verify `_pending_order_timeout` is appropriate for 15m cycle (should be < 900s)
2. Consider reducing resting order monitor polling interval for faster state updates
3. Add explicit partial fill handling in slot allocator if partial fills are possible

---

### 4. Kalshi Expectations Alignment ✅ INVESTIGATED

**Status**: Investigation complete - alignment is correct

**Upstream (Discovery & Market Catalog)** (`merid/event_venues/kalshi/market_catalog.py`):
- ✅ Status filtering: `active_only=True` parameter, checks `api_status` (open/closed/settled)
- ✅ Health status normalization: `health_status` (ok/expired/invalid_metadata)
- ✅ Close time extraction: Multiple fallbacks (close_ts, close_time, expected_expiration_time)
- ✅ UTC timezone handling: Converts naive datetimes to UTC
- ✅ Window alignment: Validates close_time matches 15m window end (1s tolerance)
- ✅ Robust discovery: Falls back to `active_only=False` if no active markets found
- ✅ Invariant check: Exactly ONE active 15m market per asset at any time

**Midstream (Signal, Allocation, Filtering)** (`merid/prediction/agent_grid_15m.py`):
- ✅ Probability calculations: Market-implied probability from price_cents
- ✅ Kelly sizing: Correct probability conversion (YES vs NO outcomes)
- ✅ Edge calculation: Probability adjustment capped at reasonable range
- ✅ Liquidity gates: Session-based (US-Europe overlap, US, Europe, Asia)
- ✅ Depth checks: One-sided regime classification (yes_depth, no_depth thresholds)
- ✅ Spread validation: Rejects if no liquidity on either side
- ✅ Adaptive liquidity: Optional AdaptiveLiquidityCalculator for dynamic thresholds

**Downstream (Order Submission & Lifecycle)** (`merid/event_venues/kalshi/order_router.py`):
- ✅ Order type support: "limit" orders (market orders converted to limit)
- ✅ Size handling: `non_positive_size` validation, liquidity-based capping
- ✅ Dynamic order type: `_determine_dynamic_order_type()` based on market conditions
- ✅ Time-in-force: "gtc" for resting, "ioc" for marketable
- ✅ Size limits: Cap at 80% of available liquidity with minimum 1 contract
- ✅ Error handling: Comprehensive rejection reasons and logging

**Potential Issues Identified**:
- ⚠️ Market catalog uses multiple close_time fallbacks - may indicate API inconsistency
- ⚠️ Asian session disabled for low liquidity - may miss opportunities
- ⚠️ No explicit check for Kalshi API version changes
- ⚠️ Liquidity thresholds are hardcoded (not from API metadata)

**Recommendations**:
1. Monitor Kalshi API changelog for close_time field changes
2. Consider making liquidity thresholds configurable via profile
3. Add API version check on startup to detect breaking changes
4. Consider enabling Asian session with reduced size limits

---

## Summary

### Completed ✅
1. Canonical identity handling - All layers now use consistent asset/window extraction
2. Router bypass eliminated - All execution paths now through order_router
3. State synchronization investigation - Existing protections are robust
4. Kalshi expectations alignment - Upstream/midstream/downstream aligned correctly

### Critical Issues Fixed 🚨
1. **execution_subscriber bypasses router validation** - FIXED: Now routes through order_router with all validation gates
2. **_kalshi_place_order bypasses router validation** - FIXED: Hard deprecated in production with ALLOW_DIRECT_EXECUTION flag

### Potential Issues Identified ⚠️
1. Resting order monitor polling latency (30s) could cause stale state
2. Global allocator pending order timeout may not be configured for 15m cycle
3. No explicit partial fill handling in slot allocator
4. Market catalog uses multiple close_time fallbacks (API inconsistency)
5. Asian session disabled for low liquidity
6. No explicit Kalshi API version check
7. Liquidity thresholds are hardcoded

### Next Steps
1. Create automated tests for contract identity invariants
2. Create automated tests for exposure invariants
3. Create automated tests for lifecycle invariants
4. Create automated tests for Kalshi compatibility invariants
5. Set up monitoring and logging alerts for high-leverage bugs
