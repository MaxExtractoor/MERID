# Unified Position Manager Design Document

## Overview

This document describes the design for a Unified Position Manager (UPM) that will serve as the single source of truth for all position and exposure state in the MERID trading system.

## Problem Statement

The current system has position and exposure state scattered across 6+ components:
- Position Cache
- Fills Ledger
- Slot Allocator
- Order Router
- Global Allocator
- Position Monitor

This creates:
- No single source of truth
- Race conditions between enforcement layers
- In-memory state lost on restart
- Corrupted data not validated
- No atomic transactions

## Solution Architecture

### Core Principles

1. **Single Source of Truth:** UPM owns all position and exposure state
2. **Atomic Operations:** All state changes are atomic with rollback
3. **Persistent State:** All state is persisted to disk
4. **Data Validation:** All data is validated before use
5. **Pre-Trade Enforcement:** Single enforcement gate before order submission

### Component Design

#### 1. UnifiedPositionManager (Core Component)

**File:** `merid/risk/unified_position_manager.py`

**Responsibilities:**
- Own all position state (current positions, slots, windows, pending orders)
- Provide atomic operations for position lifecycle transitions
- Persist state to disk for restart recovery
- Validate data integrity before any operation
- Provide single API for all position/exposure queries

**State Schema:**
```python
@dataclass
class UnifiedPositionState:
    """Complete position and exposure state."""
    # Current positions
    positions: Dict[str, Position]  # market_id -> Position
    
    # Allocated slots
    slots: Dict[str, AllocatedSlot]  # slot_id -> AllocatedSlot
    
    # 15-minute windows
    windows: Dict[str, int]  # asset -> window_start_timestamp
    
    # Pending orders
    pending_orders: Dict[str, PendingOrder]  # asset -> PendingOrder
    
    # Exposure tracking
    total_exposure_usd: float
    per_asset_exposure: Dict[str, float]  # asset -> exposure_usd
    
    # Metadata
    last_updated: datetime
    version: int  # For optimistic locking
```

**Key Operations:**

```python
class UnifiedPositionManager:
    async def allocate_slot(self, request: AllocationRequest) -> AllocationResult:
        """Atomically check and allocate a slot for a new position.
        
        This is the ONLY method that should allocate slots. It:
        1. Validates all limits (per-asset, total exposure, 15-minute window)
        2. Checks data integrity (corrupted positions, stale data)
        3. Allocates slot atomically with lock
        4. Persists state to disk
        5. Returns detailed result with reason if rejected
        
        This replaces:
        - global_slot_allocator.request_allocation()
        - global_allocator.allocate()
        - order_router window checks
        """
        pass
    
    async def on_fill(self, fill: KalshiFill) -> None:
        """Handle a fill notification.
        
        This transitions the position from ALLOCATING to FILLED state.
        It:
        1. Updates position state
        2. Updates exposure tracking
        3. Sets 15-minute window
        4. Clears pending order
        5. Persists state to disk
        """
        pass
    
    async def on_exit(self, market_id: str, exit_fill: KalshiFill) -> None:
        """Handle an exit fill notification.
        
        This transitions the position from FILLED to CLOSED state.
        It:
        1. Releases the allocated slot
        2. Clears the 15-minute window
        3. Updates exposure tracking
        4. Persists state to disk
        """
        pass
    
    async def on_order_failure(self, slot_id: str, reason: str) -> None:
        """Handle an order failure.
        
        This rolls back the allocation:
        1. Releases the allocated slot
        2. Clears pending order
        3. Persists state to disk
        """
        pass
    
    def can_allocate(self, asset: str, price_cents: int) -> Tuple[bool, str]:
        """Check if allocation is possible (read-only operation).
        
        This is used for pre-checks without allocating.
        """
        pass
    
    def get_total_exposure(self) -> float:
        """Get total current exposure in USD."""
        pass
    
    def get_asset_exposure(self, asset: str) -> float:
        """Get exposure for a specific asset."""
        pass
    
    def has_position(self, asset: str) -> bool:
        """Check if asset has an open position."""
        pass
    
    async def load_state(self) -> None:
        """Load state from disk on startup."""
        pass
    
    async def persist_state(self) -> None:
        """Persist state to disk."""
        pass
```

**State Machine:**

```
NO_POSITION → ALLOCATING → FILLED → EXITING → CLOSED
     ↑              ↓           ↓          ↓
     └──────────────┴───────────┴──────────┘
                    (on failure)
```

**Transitions:**
- `allocate_slot()`: NO_POSITION → ALLOCATING
- `on_fill()`: ALLOCATING → FILLED
- `on_exit()`: FILLED → EXITING → CLOSED
- `on_order_failure()`: ALLOCATING → NO_POSITION

#### 2. PreTradeEnforcementGate (Enforcement Component)

**File:** `merid/risk/pre_trade_enforcement_gate.py`

**Responsibilities:**
- Single enforcement gate for all pre-trade checks
- Config-based limits (cannot be disabled by strategy code)
- Returns detailed rejection reasons
- Logs all enforcement decisions

**Configuration:**
```python
@dataclass
class EnforcementConfig:
    """Enforcement limits configuration."""
    max_total_exposure_usd: float = 1.00
    max_positions_per_asset: int = 1
    max_contracts_per_order: int = 1
    min_entry_cents: int = 1
    max_entry_cents: int = 99
    window_minutes: int = 15
    max_pending_order_age_seconds: int = 30
```

**Enforcement Logic:**

```python
class PreTradeEnforcementGate:
    def __init__(self, config: EnforcementConfig, upm: UnifiedPositionManager):
        self.config = config
        self.upm = upm
    
    async def check_order(self, order: OrderIntent) -> EnforcementResult:
        """Check if order passes all enforcement rules.
        
        This is the ONLY method that should be called before order submission.
        It checks:
        1. Per-asset position limit (1 position per asset)
        2. Total exposure limit ($1 cap)
        3. 15-minute window limit (1 entry per asset per window)
        4. Contract count limit (count=1)
        5. Price range limits (1c-99c)
        6. Pending order limits (no duplicate pending orders)
        7. Data integrity (no corrupted positions)
        
        Returns:
            EnforcementResult with:
            - allowed: bool
            - reason: str (if not allowed)
            - checks_passed: List[str]
            - checks_failed: List[str]
        """
        checks = []
        
        # Check 1: Per-asset position limit
        if self.upm.has_position(order.asset):
            checks.append(("per_asset_position_limit", False, "Asset already has position"))
        
        # Check 2: Total exposure limit
        current_exposure = self.upm.get_total_exposure()
        required_exposure = order.price_cents / 100.0
        if current_exposure + required_exposure > self.config.max_total_exposure_usd:
            checks.append(("total_exposure_limit", False, f"Would exceed ${self.config.max_total_exposure_usd} cap"))
        
        # Check 3: 15-minute window limit
        if self.upm.in_current_window(order.asset):
            checks.append(("window_limit", False, "Asset already has entry in current 15m window"))
        
        # Check 4: Contract count limit
        if order.count != self.config.max_contracts_per_order:
            checks.append(("contract_count_limit", False, f"Count must be {self.config.max_contracts_per_order}"))
        
        # Check 5: Price range limits
        if order.price_cents < self.config.min_entry_cents or order.price_cents > self.config.max_entry_cents:
            checks.append(("price_range_limit", False, f"Price must be {self.config.min_entry_cents}c-{self.config.max_entry_cents}c"))
        
        # Check 6: Pending order limits
        if self.upm.has_pending_order(order.asset):
            checks.append(("pending_order_limit", False, "Asset has pending order"))
        
        # Check 7: Data integrity
        if self.upm.has_corrupted_positions():
            checks.append(("data_integrity", False, "System has corrupted position data"))
        
        # Evaluate results
        failed_checks = [c for c in checks if not c[1]]
        if failed_checks:
            return EnforcementResult(
                allowed=False,
                reason=failed_checks[0][2],
                checks_passed=[c[0] for c in checks if c[1]],
                checks_failed=[c[0] for c in failed_checks]
            )
        
        return EnforcementResult(
            allowed=True,
            reason=None,
            checks_passed=[c[0] for c in checks],
            checks_failed=[]
        )
```

#### 3. Data Validation Layer

**File:** `merid/risk/data_validation.py`

**Responsibilities:**
- Validate position data integrity
- Detect corrupted positions
- Provide data quality metrics
- Automatic recovery from corrupted state

**Validation Rules:**

```python
class DataValidator:
    @staticmethod
    def validate_position(position: Position) -> ValidationResult:
        """Validate a single position.
        
        Checks:
        - avg_price_cents is not None and > 0
        - contracts is not None and >= 0
        - market_id is not None and not empty
        - side is valid (yes/no)
        - last_updated is recent (not stale)
        """
        if position.avg_price_cents is None or position.avg_price_cents <= 0:
            return ValidationResult(
                valid=False,
                reason="avg_price_cents is None or <= 0",
                severity="critical"
            )
        
        if position.contracts is None or position.contracts < 0:
            return ValidationResult(
                valid=False,
                reason="contracts is None or < 0",
                severity="critical"
            )
        
        if not position.market_id or position.market_id.strip() == "":
            return ValidationResult(
                valid=False,
                reason="market_id is empty",
                severity="critical"
            )
        
        if position.side not in ["yes", "no"]:
            return ValidationResult(
                valid=False,
                reason=f"Invalid side: {position.side}",
                severity="critical"
            )
        
        # Check staleness (older than 1 hour)
        if position.last_updated and (datetime.now(timezone.utc) - position.last_updated).total_seconds() > 3600:
            return ValidationResult(
                valid=False,
                reason="Position is stale (older than 1 hour)",
                severity="warning"
            )
        
        return ValidationResult(valid=True, reason=None, severity="ok")
    
    @staticmethod
    def validate_position_cache(cache: PositionCache) -> CacheValidationResult:
        """Validate entire position cache.
        
        Returns:
            - total_positions: int
            - valid_positions: int
            - corrupted_positions: int
            - stale_positions: int
            - corruption_details: List[str]
        """
        pass
```

## Implementation Plan

### Phase 1: Critical Fixes (Immediate)

1. **Fix Position Cache Corruption Handling**
   - Add data validation to reject positions with avg_price_cents = 0
   - Add validation in agent_grid_15m.py when building current_positions
   - Add validation in global_allocator.py when checking positions
   - Add validation in order_router.py when checking positions

2. **Fix Slot Release on Order Failure**
   - Ensure slots are released when orders fail
   - Add slot release in all error paths
   - Add timeout-based slot cleanup

### Phase 2: Core Infrastructure (High Priority)

3. **Implement UnifiedPositionManager**
   - Create the core class with state schema
   - Implement atomic operations (allocate_slot, on_fill, on_exit, on_order_failure)
   - Implement state persistence to disk
   - Implement state loading on startup
   - Add comprehensive unit tests

4. **Implement PreTradeEnforcementGate**
   - Create the enforcement gate class
   - Implement all enforcement checks
   - Add configuration-based limits
   - Add detailed logging
   - Add comprehensive unit tests

### Phase 3: Integration (High Priority)

5. **Integrate UPM into Order Router**
   - Replace slot_allocator calls with UPM calls
   - Replace window tracking with UPM calls
   - Replace position cache queries with UPM calls
   - Add lifecycle callbacks (on_fill, on_exit, on_order_failure)

6. **Integrate UPM into Global Allocator**
   - Replace current_positions logic with UPM queries
   - Replace pending order tracking with UPM state
   - Simplify global_allocator to just generate candidates

### Phase 4: Data Validation (Medium Priority)

7. **Implement Data Validation Layer**
   - Create DataValidator class
   - Add validation rules for positions
   - Add validation for position cache
   - Add automatic recovery from corrupted state

8. **Add Validation to All Position Queries**
   - Add validation before using position data
   - Add warnings for stale data
   - Add alerts for corrupted data

### Phase 5: Persistence (Medium Priority)

9. **Implement State Persistence**
   - Add database schema for UPM state
   - Implement save/load operations
   - Add state versioning for migrations
   - Add backup/restore functionality

10. **Implement Window Persistence**
    - Replace in-memory windows with database-backed windows
    - Add window cleanup job
    - Add window rebuild from positions on startup

### Phase 6: Monitoring (Low Priority)

11. **Add Monitoring and Alerts**
    - Add metrics for enforcement decisions
    - Add alerts for corrupted data
    - Add alerts for enforcement failures
    - Add dashboards for position/exposure state

## Migration Strategy

### Step 1: Parallel Operation
- Run UPM alongside existing components
- Compare UPM state with existing state
- Validate UPM correctness

### Step 2: Gradual Migration
- Migrate one component at a time
- Start with order router (most critical)
- Then migrate global allocator
- Finally migrate slot allocator

### Step 3: Decommission Old Components
- Once all components are migrated
- Decommission old position cache
- Decommission old slot allocator
- Decommission old window tracking

## Testing Strategy

### Unit Tests
- Test each UPM operation independently
- Test enforcement gate with various scenarios
- Test data validation with corrupted data
- Test state persistence and loading

### Integration Tests
- Test UPM integration with order router
- Test UPM integration with global allocator
- Test end-to-end order flow with UPM
- Test restart recovery with persisted state

### Stress Tests
- Test with high order volume
- Test with concurrent orders
- Test with server restarts
- Test with corrupted data

### Regression Tests
- Ensure existing functionality still works
- Compare enforcement decisions before/after
- Validate exposure calculations
- Validate position tracking

## Rollback Plan

If issues are discovered after deployment:

1. **Feature Flags:** Add feature flags to disable UPM
2. **Parallel Operation:** Keep old components running
3. **State Sync:** Keep UPM state in sync with old state
4. **Quick Rollback:** Disable UPM and revert to old components

## Success Criteria

1. **Single Source of Truth:** UPM is the only component that owns position state
2. **Atomic Operations:** All state changes are atomic with rollback
3. **Persistent State:** All state survives server restarts
4. **Data Validation:** Corrupted data is detected and rejected
5. **Pre-Trade Enforcement:** Single enforcement gate before order submission
6. **No Race Conditions:** No concurrent access issues
7. **Correct Enforcement:** All limits are correctly enforced
8. **Performance:** No significant performance degradation

## Conclusion

The Unified Position Manager will provide a robust, production-ready solution for position and exposure management. It addresses all the gaps identified in the current architecture and follows best practices from the industry.

The implementation should be done in phases, starting with critical fixes and gradually building out the full infrastructure. This approach minimizes risk while delivering immediate improvements.
