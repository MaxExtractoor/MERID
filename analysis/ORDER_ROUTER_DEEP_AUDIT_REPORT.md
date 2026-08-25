# Order Router Deep Audit Report
**Date**: 2026-07-16  
**Scope**: End-to-end audit of order router stack (upstream, midstream, downstream)  
**Focus**: Gaps, wire issues, discrepancies, misalignment, duplicate functions

---

## Executive Summary

This audit identified **critical architectural issues** in the order router stack:

1. **Multiple duplicate functions** across modules causing maintenance burden and potential inconsistencies
2. **Legacy contamination** risk with deprecated components still present in codebase
3. **Risk management fragmentation** with 4 different risk manager classes
4. **Fee calculation redundancy** with 4 different implementations
5. **Data model divergence** with 3 different OrderIntent classes

**Severity**: HIGH - These issues increase maintenance burden, risk of inconsistencies, and potential for bugs due to misaligned implementations.

---

## Architecture Overview

### Entry Points
- **Production**: `merid/event_venues/kalshi/order_router.py`
  - `route_order()` - Sync routing (MOCK/PAPER only)
  - `route_order_async()` - Async routing (LIVE execution)
- **Legacy**: `merid/event_venues/kalshi/order_router_15m.py` (MARKED AS NOT USED IN PRODUCTION)

### Data Flow
```
Upstream (Signal Generation)
├── loop_15m.py
├── agent_grid_15m.py
└── kalshi_tools.py
    ↓ creates OrderIntent
Midstream (Risk & Validation)
├── order_router.py (main routing logic)
├── order_gate.py (pre-trade gate)
├── order_deduplication.py (duplicate detection)
├── unified_risk_manager.py (risk checks)
├── global_slot_allocator.py ($1 exposure cap)
└── resting_order_monitor.py (anti-stacking)
    ↓ validates & routes
Downstream (Execution & Fills)
├── venue_adapter.py (Kalshi API)
├── order_manager.py (lifecycle tracking)
├── position_cache.py (position tracking)
├── fills_ledger.py (fill accounting)
└── ws_bridge.py (WebSocket fill handling)
```

---

## Critical Findings

### 1. DUPLICATE FUNCTIONS

#### 1.1 Fee Calculation (4 implementations)

**Issue**: Fee calculation logic duplicated across 4 modules, creating maintenance burden and risk of inconsistencies.

| Module | Function | Line | Purpose |
|--------|----------|------|---------|
| `order_router.py` | `_kalshi_fee_cents()` | 1727 | Internal fee calc for router |
| `kalshi_risk.py` | `kalshi_fee_cents()` | 63 | Legacy risk manager fee calc |
| `fees.py` | `kalshi_fee_cents()` | 316 | Alias for calculate_kalshi_fee_cents |
| `position_sizer.py` | `kalshi_fee_cents()` | 168 | Position sizing fee calc |

**Canonical Source**: `fees.py` with `calculate_kalshi_fee_cents()` (line 72)

**Recommendation**: 
- Consolidate all fee calculations to use `fees.calculate_kalshi_fee_cents()`
- Remove duplicate implementations from `kalshi_risk.py`, `order_router.py`, `position_sizer.py`
- Keep single canonical implementation in `fees.py`

---

#### 1.2 OrderIntent Classes (3 implementations)

**Issue**: Three different OrderIntent dataclasses exist, creating potential confusion and type mismatches.

| Module | Class | Line | Purpose |
|--------|-------|------|---------|
| `order_router.py` | `OrderIntent` | 1315 | **PRODUCTION** - Main order intent dataclass |
| `order_router_15m.py` | `KalshiOrderIntent` | 65 | **LEGACY** - Mock router intent (marked as not used) |
| `fills_ledger.py` | `OrderIntent` | 364 | Fills ledger specific intent |

**Canonical Source**: `order_router.py` OrderIntent (line 1315)

**Recommendation**:
- Remove `order_router_15m.py` entirely (file header states "NOT USED IN PRODUCTION")
- Consolidate fills_ledger.OrderIntent to use canonical order_router.OrderIntent
- Add type aliases if needed for clarity

---

#### 1.3 Risk Manager Classes (4 implementations)

**Issue**: Four different risk manager classes create fragmentation and potential for inconsistent risk enforcement.

| Module | Class | Line | Purpose |
|--------|-------|------|---------|
| `unified_risk_manager.py` | `UnifiedRiskManager` | 116 | **PRODUCTION** - Single source of truth for risk |
| `kalshi_risk.py` | `KalshiRiskManager` | 1077 | **LEGACY** - Deprecated risk manager |
| `order_group_manager.py` | `OrderGroupRiskManager` | 102 | Order group specific risk |
| `bracket_risk.py` | `BracketRiskManager` | 115 | Bracket order specific risk |

**Canonical Source**: `unified_risk_manager.py` UnifiedRiskManager (line 116)

**Recommendation**:
- Deprecate and remove `KalshiRiskManager` from `kalshi_risk.py`
- Ensure `OrderGroupRiskManager` and `BracketRiskManager` delegate to `UnifiedRiskManager` for core risk checks
- Document that `UnifiedRiskManager.check_order()` is the single entry point for all risk validation

---

#### 1.4 Duplicate Detection (2 implementations)

**Issue**: Duplicate order detection split between router and gate, with different window sizes.

| Module | Function | Line | Window | Purpose |
|--------|----------|------|--------|---------|
| `order_router.py` | `_check_duplicate_order()` | 395 | 5s | Router-level duplicate check |
| `order_gate.py` | `check_duplicate_race()` | 655 | N/A | Gate-level race condition check |
| `order_deduplication.py` | `OrderDeduplicationCache` | 36 | 60s TTL | Cache-based deduplication |

**Canonical Source**: `order_deduplication.py` OrderDeduplicationCache (line 36)

**Recommendation**:
- Consolidate duplicate detection to single module (`order_deduplication.py`)
- Remove `_check_duplicate_order()` from `order_router.py`
- Ensure `order_gate.py` uses the same deduplication cache
- Align TTL windows (currently 5s in router vs 60s in cache)

---

#### 1.5 Position Tracking (3 implementations)

**Issue**: Position tracking split across multiple modules with overlapping responsibilities.

| Module | Class/Function | Line | Purpose |
|--------|---------------|------|---------|
| `position_cache.py` | `KalshiPositionCache` | 240 | **PRODUCTION** - Main position cache |
| `position_sanity_checker.py` | `PositionSanityChecker` | 75 | Position sanity validation |
| `fills_ledger.py` | `compute_position_from_fills()` | 1865 | Position computation from fills |

**Canonical Source**: `position_cache.py` KalshiPositionCache (line 240)

**Recommendation**:
- Ensure `position_sanity_checker.py` only validates, does not store positions
- Ensure `fills_ledger.py` only computes for reconciliation, not primary storage
- Document that `KalshiPositionCache` is the single source of truth for position state

---

### 2. LEGACY CONTAMINATION RISKS

#### 2.1 order_router_15m.py (CRITICAL)

**Issue**: Entire file marked as "NOT USED IN PRODUCTION" but still exists in codebase.

**File Header Warning**:
```python
⚠️ WARNING: THIS MODULE IS NOT USED IN PRODUCTION ⚠️
This module contains a MOCK order router implementation that does NOT execute real orders.
The production system uses merid.event_venues.kalshi.order_router.py instead.
```

**Risk**: 
- Developers may accidentally import and use the legacy router
- Code search may return legacy implementations
- Maintenance burden for unused code

**Recommendation**: 
- **DELETE** `order_router_15m.py` entirely
- Update any imports that reference it to use `order_router.py`
- Add deprecation notice if removal is not immediately possible

---

#### 2.2 KalshiRiskManager (HIGH)

**Issue**: `KalshiRiskManager` in `kalshi_risk.py` is deprecated but still present.

**Evidence**: 
- `UnifiedRiskManager` is documented as "Single Source of Truth"
- Memory indicates percentage-based allocation was pruned (2026-07-16)
- `KalshiRiskManager` still has percentage-based logic

**Risk**:
- Code may still import and use deprecated risk manager
- Inconsistent risk enforcement if both managers are used
- Maintenance burden for deprecated code

**Recommendation**:
- Add deprecation warnings to `KalshiRiskManager` methods
- Search codebase for imports of `KalshiRiskManager` and replace with `UnifiedRiskManager`
- Plan for removal in next major version

---

### 3. WIRING ISSUES

#### 3.1 Multiple Entry Points for Order Routing

**Issue**: Orders can be routed through multiple paths, creating potential for inconsistent behavior.

**Entry Points**:
1. `loop_15m.py` → `kalshi_tools._kalshi_place_order()` → `order_router.route_order_async()`
2. `agent_grid_15m.py` → `kalshi_tools._kalshi_place_order()` → `order_router.route_order_async()`
3. Direct calls to `order_router.route_order_async()` from various modules
4. `offset_hedging.place_hedge_order()` → `order_router.route_order_async()`

**Risk**:
- Different paths may skip certain validations
- Inconsistent error handling across paths
- Difficult to trace order flow in production

**Recommendation**:
- Document all valid entry points
- Add caller authorization checks (already partially implemented in `route_order_async()`)
- Consider creating a single facade function for all order routing

---

#### 3.2 Risk Check Fragmentation

**Issue**: Risk checks performed at multiple layers with potential for misalignment.

**Risk Check Locations**:
1. `order_router.py`: `_check_intent_risk()`, `_check_bankroll_risk_cap()`, `_check_market_regime_gate()`
2. `order_gate.py`: Pre-trade gate with lease check, dedup, fill awareness
3. `unified_risk_manager.py`: `check_order()` - single source of truth
4. `global_slot_allocator.py`: Slot allocation and $1 cap enforcement
5. `resting_order_monitor.py`: Anti-stacking guard

**Risk**:
- Checks may be redundant or inconsistent
- Order of checks may vary across paths
- Difficult to ensure all checks are applied consistently

**Recommendation**:
- Document the canonical order of risk checks
- Ensure all paths go through the same check sequence
- Consider consolidating to a single risk validation function

---

### 4. DATA MODEL MISALIGNMENT

#### 4.1 OrderIntent Field Differences

**Issue**: Different OrderIntent classes have different fields, creating potential for data loss or errors.

**order_router.py OrderIntent** (line 1315):
- ticker, side, action, price_cents, count
- agent_id, source, rationale, edge_pct
- snapshot_ts, mode, aggressiveness
- post_only, time_in_force
- take_profit_r_multiple, stop_loss_price_cents
- intent_id, client_order_id

**order_router_15m.py KalshiOrderIntent** (line 65):
- ticker, side, action, price_cents, count
- client_order_id, risk_checked (minimal fields)

**Risk**:
- Converting between intents may lose data
- Type hints may not catch mismatches
- Validation may be inconsistent

**Recommendation**:
- Remove legacy `KalshiOrderIntent`
- Ensure all code uses canonical `OrderIntent`
- Add validation for required fields

---

#### 4.2 Price Range Constants

**Issue**: Price range constants (10-75c) defined in multiple places.

**Locations**:
- `risk_parameters.py`: `MAX_OPEN_PRICE_CENTS = 75`, `DEFAULT_KALSHI_PRICE_CENTS = 42`
- `global_slot_allocator.py`: `MAX_ENTRY_CENTS = 75`
- `order_router.py`: Price clamping `max(10, min(75, ...))`
- `loop_15m.py`: Price clamping `max(10, min(75, ...))`
- Profile YAML: `guardrails.max_contract_price_cents: 75`

**Risk**:
- Changing range requires updating multiple files
- Inconsistent ranges may cause validation failures
- Memory indicates this was a recent change (2026-07-12)

**Recommendation**:
- Define price range constants in single location (`risk_parameters.py`)
- All other modules should import from there
- Add tests to verify consistency across modules

---

### 5. GAPS IN ORDER FLOW

#### 5.1 Fill Handling Inconsistency

**Issue**: Fill handling split between WebSocket and REST with potential for duplicates or missed fills.

**Fill Sources**:
1. WebSocket fills via `ws_bridge._handle_kalshi_user_fill()`
2. REST polling via `fills_poller.py`
3. REST sync on reconnect via `ws_bridge._sync_fills_with_rest_on_reconnect()`

**Risk**:
- Duplicate fill processing if both WS and REST deliver same fill
- Missed fills if WS fails and REST polling is delayed
- Inconsistent fill accounting across sources

**Recommendation**:
- Implement fill deduplication by fill ID
- Ensure REST sync only fills gaps in WS stream
- Add metrics to track fill source consistency

---

#### 5.2 Position Cache Synchronization

**Issue**: Position cache may diverge from actual Kalshi positions.

**Sync Mechanisms**:
1. Real-time updates from fills
2. Periodic REST sync via `position_cache.sync_from_rest()`
3. Reconciliation with fills ledger

**Risk**:
- Cache may become stale if fills are missed
- REST sync may be too infrequent
- Manual reconciliation may be needed

**Recommendation**:
- Implement position cache health checks
- Add alerts for position discrepancies
- Ensure REST sync runs frequently enough

---

## Recommendations Summary

### Immediate Actions (P0)

1. **DELETE** `order_router_15m.py` - marked as not used in production
2. **Consolidate fee calculation** to single canonical implementation in `fees.py`
3. **Add deprecation warnings** to `KalshiRiskManager` in `kalshi_risk.py`
4. **Consolidate duplicate detection** to `order_deduplication.py` only

### Short-term Actions (P1)

5. **Align TTL windows** for duplicate detection (5s vs 60s mismatch)
6. **Document canonical order** of risk checks across all paths
7. **Consolidate OrderIntent classes** to single canonical implementation
8. **Define price range constants** in single location (`risk_parameters.py`)

### Long-term Actions (P2)

9. **Remove KalshiRiskManager** after deprecation period
10. **Create single facade** for order routing to ensure consistent path
11. **Implement fill deduplication** across WS and REST sources
12. **Add position cache health checks** and discrepancy alerts

---

## Appendix: Complete Function Inventory

### Order Router Functions (order_router.py)
- `route_order()` - Sync routing (line 6367)
- `route_order_async()` - Async routing (line 7121)
- `_route_live()` - Live execution path (line 4000)
- `_route_sync_non_live()` - Mock/paper path (line 3846)
- `_check_duplicate_order()` - Duplicate detection (line 395)
- `_check_open_resting_order()` - Anti-stacking guard (line 327)
- `_check_intent_risk()` - Risk validation (line 1942)
- `_validate_price_band()` - Price range validation (line 2261)
- `_kalshi_fee_cents()` - Fee calculation (line 1727)
- `simulate_paper_fill()` - Paper fill simulation (line 1739)

### Risk Check Functions
- `unified_risk_manager.py`: `check_order()` (line 340)
- `kalshi_risk.py`: `check_order()` (line 1174) - LEGACY
- `order_router.py`: `_check_bankroll_risk_cap()` (line 3509)
- `order_router.py`: `_check_market_regime_gate()` (line 3641)

### Validation Functions
- `order_router.py`: `_validate_price_band()` (line 2261)
- `order_router.py`: `_validate_signal_metadata()` (line 2414)
- `order_router.py`: `_validate_prob_price_consistency()` (line 2666)
- `order_router.py`: `_validate_deep_otm_policy()` (line 2726)
- `order_router.py`: `_validate_underlying_plausibility()` (line 3304)
- `order_router.py`: `_validate_position_lifecycle()` (line 3355)
- `order_router.py`: `_validate_deployment_safety()` (line 3405)

### Fee Calculation Functions
- `fees.py`: `calculate_kalshi_fee_cents()` (line 72) - CANONICAL
- `fees.py`: `kalshi_fee_cents()` (line 316) - Alias
- `kalshi_risk.py`: `kalshi_fee_cents()` (line 63) - LEGACY
- `order_router.py`: `_kalshi_fee_cents()` (line 1727) - Internal
- `position_sizer.py`: `kalshi_fee_cents()` (line 168) - Internal

### Duplicate Detection Functions
- `order_deduplication.py`: `OrderDeduplicationCache.get_or_create()` (line 68) - CANONICAL
- `order_router.py`: `_check_duplicate_order()` (line 395) - Router-level
- `order_gate.py`: `check_duplicate_race()` (line 655) - Gate-level

### Position Tracking Functions
- `position_cache.py`: `KalshiPositionCache.get_position()` (line 1152) - CANONICAL
- `position_cache.py`: `KalshiPositionCache.get_all_positions()` (line 1156)
- `position_sanity_checker.py`: `PositionSanityChecker.get_position()` (line 238)
- `fills_ledger.py`: `compute_position_from_fills()` (line 1865)

---

## Test Coverage Gaps

### Missing Tests
1. Integration tests for order routing through all entry points
2. Tests for duplicate detection window alignment
3. Tests for fee calculation consistency across modules
4. Tests for position cache synchronization
5. Tests for fill deduplication across WS and REST

### Recommended Test Additions
1. `test_order_router_canonical_path.py` - Test all valid entry points
2. `test_fee_calculation_consistency.py` - Test all fee implementations match
3. `test_duplicate_detection_alignment.py` - Test TTL window consistency
4. `test_fill_deduplication.py` - Test WS/REST fill deduplication
5. `test_position_cache_sync.py` - Test position cache reconciliation

---

## Conclusion

The order router stack has significant architectural debt due to:

1. **Legacy code** that should have been removed (`order_router_15m.py`, `KalshiRiskManager`)
2. **Duplicate implementations** of core functions (fee calculation, duplicate detection)
3. **Fragmented risk management** across multiple managers
4. **Multiple data models** for the same concepts (OrderIntent classes)

**Priority**: Address P0 issues immediately to reduce maintenance burden and risk of inconsistencies. P1 and P2 issues can be addressed incrementally.

**Risk Assessment**: 
- **Current Risk**: MEDIUM - System functions but has maintenance burden
- **Future Risk**: HIGH - Without cleanup, inconsistencies will accumulate
- **Remediation Effort**: MEDIUM - Can be addressed incrementally without disrupting production
