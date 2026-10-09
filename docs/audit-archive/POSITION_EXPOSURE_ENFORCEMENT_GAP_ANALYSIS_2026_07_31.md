# Position and Exposure Enforcement Gap Analysis

## Executive Summary

Based on comprehensive audit of the MERID codebase and web research best practices, this document identifies critical gaps in the position and exposure enforcement architecture that are causing the system to violate the core rules:

1. **1 contract per asset until exit** - NOT being enforced properly
2. **$1 total exposure cap across all assets** - NOT being enforced properly
3. **15-minute window limits** - NOT being enforced properly

## Current Enforcement Architecture

### Layer 1: Global Slot Allocator (Primary Enforcement)
**File:** `merid/risk/global_slot_allocator.py`

**Hard Limits:**
- MAX_EXPOSURE_USD = 1.00
- MAX_POSITIONS_PER_ASSET = 1
- MAX_CONTRACTS_PER_ORDER = 1

**Enforcement Points:**
1. `can_allocate()` - Checks per-asset position limit
2. `request_allocation()` - Atomic check-and-allocate
3. Contract count validation - Enforces count=1

### Layer 2: Global Allocator (Signal-Level Enforcement)
**File:** `merid/risk/profiles/global_allocator.py`

**Enforcement Points:**
4. Per-asset position filter - Filters candidates with existing positions
5. Contract count filter - Filters candidates with count != 1
6. Venue cap knapsack - Total notional <= $1.00

### Layer 3: Order Router (Execution-Time Enforcement)
**File:** `merid/event_venues/kalshi/order_router.py`

**Enforcement Points:**
7. Per-asset entry window tracking - 1 entry per asset per 15-minute window
8. Side-aware position check - Block same-side positions
9. Slot allocator pre-submit check - Delegates to global_slot_allocator
10. Slot allocation before submission - Atomic allocation before order
11. 15-minute window enforcement - Check if asset has exposure in current window
12. Per-side position limits - Max yes/no positions per asset

## Critical Gaps Identified

### GAP 1: Multiple Enforcement Layers Without Single Source of Truth

**Problem:** The system has 3 different enforcement layers (Slot Allocator, Global Allocator, Order Router) that maintain separate state and make independent decisions. This creates:

1. **State Synchronization Issues:** Each layer maintains its own view of positions:
   - Slot Allocator: Internal `_slots` dict
   - Global Allocator: Internal `_asset_positions` dict + external `current_positions` parameter
   - Order Router: In-memory `_asset_entry_windows` dict + position cache queries

2. **Race Conditions:** Multiple checks happen at different times:
   - Global Allocator checks at signal generation time
   - Slot Allocator checks at order submission time
   - Order Router checks again during execution
   - Between these checks, state can change

3. **Inconsistent Enforcement:** If one layer fails or has stale data, other layers may not catch it

**Best Practice Violation:** According to web research, "Limits live in config, where strategy code can't disable them" and "A strategy should never be able to disable its own risk check." The current architecture has risk checks scattered across multiple modules with no single authoritative source.

### GAP 2: Position Cache Not Authoritative for Slot Allocation

**Problem:** The Slot Allocator's `get_slots_by_asset()` method queries the position cache, but:

1. **Stale Data:** Position cache may not reflect real-time positions if fills haven't been processed
2. **Corrupted Data:** Positions with `avg_price_cents = 0` are included in position checks
3. **No Validation:** Slot Allocator doesn't validate position cache freshness before using it

**Evidence from Audit:**
```python
# global_slot_allocator.py line 162-216
def get_slots_by_asset(self, asset: str) -> List[AllocatedSlot]:
    """Get all slots for a specific asset."""
    return [slot for slot in self._slots.values() if slot.asset == asset]
```

The Slot Allocator relies on its internal `_slots` dict, not the position cache. This creates a disconnect between actual positions and allocated slots.

### GAP 3: 15-Minute Window Logic In-Memory Only

**Problem:** The 15-minute window tracking is stored in-memory:

```python
# order_router.py line 128
_asset_entry_windows: Dict[str, int] = {}  # asset -> window_start timestamp
```

**Critical Failure Modes:**
1. **Server Restart:** All window state is lost on restart
2. **No Persistence:** If the system crashes, window state is lost
3. **No Recovery:** No mechanism to rebuild window state from positions
4. **Stale Windows:** Windows can persist even if positions are closed

**Best Practice Violation:** According to web research, "The Position Manager owns position state" and should persist state for restart recovery.

### GAP 4: Exit Orders Not Properly Tracked

**Problem:** The system doesn't properly track when positions are exited:

1. **Slot Release:** Slots are released on order failure, but not systematically on position exit
2. **Window Clearing:** 15-minute windows are not cleared when positions are exited
3. **Pending Order Cleanup:** Pending orders are cleared by timeout (30s), not by actual fill confirmation

**Evidence from Audit:**
```python
# global_allocator.py line 162-172
# CRITICAL FIX (2026-07-31): Clear pending orders for assets that already have positions
for asset in list(self._pending_orders.keys()):
    if asset in current_positions and current_positions[asset] > 0:
        logger.warning("[GLOBAL-ALLOCATOR] Clearing stale pending order for %s...")
        del self._pending_orders[asset]
```

This is a reactive fix, not a proactive lifecycle management system.

### GAP 5: No Atomic Transaction Across Enforcement Layers

**Problem:** When an order is submitted, the enforcement checks happen sequentially:

1. Global Allocator filters candidates (signal level)
2. Slot Allocator checks and allocates slot (pre-submit)
3. Order Router checks window and positions (execution time)
4. Order submitted to exchange

**Failure Mode:** If the order fails after slot allocation (e.g., exchange rejection), the slot may not be released properly, creating a "phantom slot" that blocks future orders.

**Evidence from Audit:**
```python
# order_router.py line 7430-7497
allocated, reason, _allocated_slot_id = slot_allocator.request_allocation(allocation_request)
if not allocated:
    return OrderResult(status="rejected", reason=f"slot_allocation_failed:{reason}")

intent._allocated_slot_id = _allocated_slot_id
```

The slot is allocated and stored in `intent._allocated_slot_id`, but if the order fails later, the slot release logic may not execute properly.

### GAP 6: Position Cache Corruption Not Handled

**Problem:** Positions with corrupted data (avg_price_cents = 0) are included in enforcement checks:

1. **Global Allocator:** Uses corrupted position data to compute exposure
2. **Order Router:** Uses corrupted position data for position checks
3. **Slot Allocator:** May allocate slots based on corrupted position state

**Evidence from Logs:**
```
Found 12 positions on Kalshi REST API
Processing position: market=KXETH15M-26JUL312330-30 count=2 price=0c side=yes
```

All positions have `price=0c`, which breaks exposure calculations and causes the global allocator to block all trades.

### GAP 7: No Unified Position Lifecycle Manager

**Problem:** Position lifecycle is managed across multiple components:

1. **Position Cache:** Stores position state
2. **Fills Ledger:** Records fill history
3. **Slot Allocator:** Manages allocation slots
4. **Order Router:** Manages order execution
5. **Global Allocator:** Manages pending orders
6. **Position Monitor:** Monitors positions for exits

**Best Practice Violation:** According to web research, "The Position Manager owns position state" and should be a single authoritative source. The current architecture has position state scattered across 6+ components.

## Root Cause Analysis

The fundamental issue is that the system has **no single authoritative source of truth** for position and exposure state. Instead, it has:

1. **Multiple independent state stores** (Slot Allocator, Global Allocator, Order Router, Position Cache)
2. **No unified lifecycle management** (each component manages its own piece of the lifecycle)
3. **No atomic transactions** (state changes happen sequentially without rollback)
4. **No persistence for critical state** (15-minute windows, slot allocations)
5. **No validation of data integrity** (corrupted positions are used in calculations)

## Best Practices from Web Research

Based on web research, production trading systems should:

1. **Single Source of Truth:** "The Position Manager owns position state"
2. **Pre-Trade Limits:** "Every order must pass a pre-trade check against these three limits before it reaches the exchange"
3. **Config-Based Limits:** "Limits live in config, where strategy code can't disable them"
4. **State Machine:** "The position is now a state machine. Every transition evolves the same position object."
5. **Persistence:** Position state must be persisted for restart recovery
6. **Atomic Operations:** Check-and-allocate should be atomic to prevent race conditions

## Recommended Solution Architecture

### 1. Unified Position Manager (Single Source of Truth)

Create a `UnifiedPositionManager` that:
- Owns all position state (current positions, slots, windows, pending orders)
- Provides atomic operations for position lifecycle transitions
- Persists state to disk for restart recovery
- Validates data integrity before any operation
- Provides a single API for all position/exposure queries

### 2. Pre-Trade Enforcement Gate

Create a single `PreTradeEnforcementGate` that:
- Checks all limits in one atomic operation
- Lives in config (not in strategy code)
- Cannot be disabled by strategy code
- Returns detailed rejection reasons
- Logs all enforcement decisions

### 3. State Machine for Position Lifecycle

Implement a proper state machine for positions:
- States: NO_POSITION, ALLOCATING, FILLED, EXITING, CLOSED
- Transitions: allocate → fill → exit → close
- Each transition is atomic and validated
- State is persisted after each transition

### 4. Persistent Window Tracking

Replace in-memory window tracking with:
- Database-backed window state
- Rebuild from positions on startup
- Automatic cleanup of stale windows
- Queryable by all components

### 5. Data Validation Layer

Add validation for all position data:
- Reject positions with corrupted prices (avg_price_cents = 0)
- Validate position cache freshness before use
- Detect and alert on data inconsistencies
- Automatic recovery from corrupted state

## Implementation Priority

1. **CRITICAL:** Fix position cache corruption handling (immediate)
2. **HIGH:** Implement Unified Position Manager
3. **HIGH:** Implement Pre-Trade Enforcement Gate
4. **MEDIUM:** Implement State Machine for Position Lifecycle
5. **MEDIUM:** Implement Persistent Window Tracking
6. **LOW:** Add comprehensive data validation layer

## Conclusion

The current enforcement architecture has fundamental design flaws that prevent proper enforcement of position and exposure limits. The system needs a unified, stateful, persistent position manager with atomic operations and pre-trade enforcement gates to ensure the core rules are always enforced.
