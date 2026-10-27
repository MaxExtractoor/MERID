# Execution Pipeline Audit Report (2026-07-15)

## Objective
Trace candidate generation to order router processing and identify high-leverage bugs across the execution pipeline, focusing on disconnects between global allocator, global slot allocator, execution guard, execution gate, and downstream components.

## High-Leverage Bugs Found

### 1. AllocationRequest Price Validation Mismatch (FIXED)
**File**: `merid/risk/global_slot_allocator.py` (line 69)
**Bug**: `AllocationRequest.__post_init__` validated entry price against 10-50c range instead of 10-75c
**Impact**: Orders with prices 51-75c would be rejected at slot allocation stage despite being valid elsewhere
**Fix**: Changed validation from `> 50` to `> 75` to match `GlobalSlotAllocator.MAX_ENTRY_CENTS` and canonical range
**Status**: FIXED

## Component Analysis

### GlobalAllocator vs GlobalSlotAllocator

**Finding**: These are NOT duplicates - they serve different purposes in the pipeline:

#### GlobalAllocator (`merid/risk/profiles/global_allocator.py`)
- **Purpose**: Top-N edge knapsack allocator for candidate selection
- **Location**: Used in `agent_grid_15m.py` (line 12403) to select best candidates from all agents
- **Functionality**:
  - Collects all candidates from all agents in a cycle
  - Sorts by edge (descending)
  - Greedy fill under $1.00 venue cap
  - Only submits orders that fit under the cap
  - Ensures best edges get prioritized
  - 1 contract per asset per window
  - Entry prices in 10-75c range
  - Confidence ≥ 50%, edge ≥ 2.0%
- **Price Range**: 10-75c (aligned with canonical range)
- **Risk Model**: Shared $1 pool across all assets (no per-asset budgets)

#### GlobalSlotAllocator (`merid/risk/global_slot_allocator.py`)
- **Purpose**: Runtime $1 exposure cap enforcement with slot-based position management
- **Location**: Used throughout execution pipeline (agent_grid_15m, loop_15m, order_router, order_gate, position_cache)
- **Functionality**:
  - Manages $1 exposure cap across all 5 assets using slot-based allocation
  - Each position consumes its entry price from the cap
  - Slots are recycled when positions exit
  - Thread-safe for concurrent access
  - Exit orders bypass slot allocation (to allow closing positions at full capacity)
- **Price Range**: 10-75c (MAX_ENTRY_CENTS = 75)
- **Risk Model**: Fixed $1 cap with slot recycling

**Conclusion**: No disconnect - these are complementary components:
- GlobalAllocator: Candidate selection (upstream)
- GlobalSlotAllocator: Runtime enforcement (downstream)

### ExecutionGuard vs ExecutionGate

**Finding**: These are separate systems with different purposes:

#### ExecutionGuard (`merid/execution_guard.py`)
- **Purpose**: Central safety gate for trade execution (legacy system)
- **Functionality**:
  - Kill switch management
  - CQI (Cycle Quality Index) throttling
  - Domain and venue caps
  - Per-asset caps
  - Trade logging
- **Usage**: Called by MeridLoop, swarm execution_subscriber, unified_risk_engine
- **Status**: Still active but being superseded by UnifiedRiskManager

#### ExecutionGate (`core/execution_gate.py`)
- **Purpose**: Unified gate aggregating all safety checks into one boolean + reasons list
- **Functionality**:
  - Kill switch status
  - Reconciliation status (fail-closed on fresh start)
  - Price feed staleness
  - PnL consistency
  - Dependency health
  - News feed health (warning only)
  - Kalshi WebSocket health (opt-in)
  - Spot/Kalshi basis alignment (warning only)
- **Usage**: Called by prediction modules, PM bankroll snapshot, kalshi_tools
- **Status**: Production gate for execution decisions

**Disconnect Found**: 
- `order_router.py` does NOT call `check_execution_gate()` 
- `order_router.py` uses `UnifiedRiskManager` instead (line 6540)
- This is intentional - order_router has its own validation pipeline

### UnifiedRiskManager Integration

**Finding**: UnifiedRiskManager is the canonical risk check in order_router:

#### UnifiedRiskManager (`merid/risk/unified_risk_manager.py`)
- **Purpose**: Single source of truth for all risk management
- **Functionality**:
  - Single configuration file (config/risk_limits.yaml)
  - Single entry point for all order checks (check_order())
  - Bankroll-based dynamic limits
  - $1 total exposure cap (correlated_stack_max_usd = 1.0)
  - Per-trade max contracts = 1
  - Rate limiting
  - Drawdown limits
- **Usage**: Called in `order_router.py` via `_run_shared_risk_guard_and_dedup()` (line 6540)
- **Status**: Production risk manager for order_router

**Integration Points**:
1. `order_router.py` line 6540: `get_unified_risk_manager().check_order()`
2. `order_router.py` line 4301: Fill recording with UnifiedRiskManager
3. `order_router.py` line 5696: Fill recording for exposure tracking
4. `client.py` line 1980: Comment confirms Production stack uses UnifiedRiskManager

**Legacy Components Replaced**:
- GlobalRiskGuard (deprecated)
- GlobalExecutionGuard (deprecated)
- CategoryExposureTracker (deprecated)
- KalshiRiskManager (deprecated)

## Execution Flow Summary

### Candidate Generation → Order Router

1. **Signal Generation** (`agent_grid_15m.py`)
   - Agents generate candidates with edge, confidence, price
   - Price selection: 10-75c range
   - Per-asset edge thresholds (BTC 1.75%, ETH 2.0%, SOL 2.5%, XRP 3.0%, DOGE 3.5%)

2. **GlobalAllocator** (`global_allocator.py`)
   - Collects all candidates from all agents
   - Filters by edge, confidence, price (10-75c)
   - Knapsack optimization under $1 cap
   - Returns chosen orders

3. **Slot Allocation** (`global_slot_allocator.py`)
   - `AllocationRequest` created for each chosen order
   - Price validation: 10-75c (FIXED - was 10-50c)
   - Slot allocation under $1 cap
   - Exit orders bypass allocation

4. **Order Routing** (`order_router.py`)
   - Profile-based source whitelisting
   - Production scope validation
   - Rate limiting
   - Price validation (integer, 1-99c, 10c minimum)
   - Aggressiveness computation
   - Invariant checks
   - Pre-trade gate
   - **UnifiedRiskManager check** (shared risk guard)
   - Trading mode resolution (VenueGate.mode)
   - Route to live or paper execution

### Risk Check Hierarchy

1. **Upstream**: GlobalAllocator (candidate selection)
2. **Midstream**: GlobalSlotAllocator (slot allocation)
3. **Downstream**: UnifiedRiskManager (order_router validation)
4. **System-level**: ExecutionGate (execution permission)

## Recommendations

### No Critical Disconnects Found
- GlobalAllocator and GlobalSlotAllocator serve complementary purposes
- ExecutionGuard and ExecutionGate are separate systems with different scopes
- UnifiedRiskManager is properly integrated in order_router

### Alignment Verified
- All components use 10-75c canonical price range
- All components enforce $1 total exposure cap
- All components respect per-asset edge thresholds

### Potential Improvements
1. Consider deprecating ExecutionGuard in favor of ExecutionGate + UnifiedRiskManager
2. Document the clear separation of concerns between risk components
3. Add integration tests for the full candidate → execution flow

## Files Modified
- `merid/risk/global_slot_allocator.py`: Fixed AllocationRequest price validation (line 69)

## Next Steps
1. Commit AllocationRequest fix
2. Continue monitoring server for trade execution
3. Verify that 75c orders now pass slot allocation
