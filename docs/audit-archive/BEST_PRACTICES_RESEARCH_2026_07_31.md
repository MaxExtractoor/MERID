# Best Practices Research - Position and Exposure Management

## Executive Summary

This document summarizes best practices from industry research for fixing the identified high-leverage bugs in the MERID trading system.

---

## Research Sources

1. **glitchymagic/trade-state-engine** - Atomic, file-locked state management for autonomous trading systems
2. **Roq Trading Solutions** - Position management with sequence number synchronization
3. **ytrader-bybit** - Thread-safe in-memory position cache with TTL
4. **System Design Handbook** - Stock exchange system design with atomic state transitions
5. **TechRxiv Paper** - Deterministic execution and margin enforcement with atomic transactions
6. **AWS Trading Platform** - High-throughput trading platform with materialized views

---

## Key Best Practices

### 1. Single Source of Truth Pattern

**Problem**: Multiple state stores (position cache, slot allocator, window tracking) with no coordination.

**Best Practice**: Use a single authoritative data source (fills ledger/trade log) and rebuild all derived state from it.

**Implementation**:
```python
# Authoritative source: fills ledger (append-only, never modified)
# Derived state: position cache, slot allocator, window tracking

# Reconciliation cycle (every N minutes)
class StateReconciler:
    def reconcile(self):
        """Rebuild all derived state from fills ledger."""
        fills = fills_ledger.get_all_fills()
        positions = compute_positions_from_fills(fills)
        slots = compute_slots_from_positions(positions)
        windows = compute_windows_from_positions(positions)
        
        # Atomic update of derived state
        position_cache.update_all(positions)
        slot_allocator.update_all(slots)
        window_tracker.update_all(windows)
```

**Benefits**:
- Eliminates state synchronization issues
- Self-healing if derived state drifts
- Single point of failure (fills ledger)
- Easier debugging and auditing

---

### 2. Atomic Operations with Rollback

**Problem**: No atomic transactions across enforcement layers, state changes happen sequentially without rollback.

**Best Practice**: All state changes should happen within a single transaction boundary with rollback on failure.

**Implementation**:
```python
class AtomicPositionManager:
    async def allocate_slot(self, request: AllocationRequest) -> AllocationResult:
        """Atomic slot allocation with rollback on failure."""
        # Start transaction
        transaction = self.begin_transaction()
        
        try:
            # All checks under same lock
            with self._lock:
                # Check limits
                if not self.can_allocate(request):
                    return AllocationResult(success=False, reason="Limit exceeded")
                
                # Allocate slot
                slot_id = self._allocate_slot(request)
                
                # Update exposure
                self._update_exposure(request)
                
                # Update windows
                self._update_windows(request)
                
                # Commit transaction
                transaction.commit()
                
                return AllocationResult(success=True, slot_id=slot_id)
                
        except Exception as e:
            # Rollback on any error
            transaction.rollback()
            logger.error(f"Slot allocation failed, rolled back: {e}")
            return AllocationResult(success=False, reason=str(e))
```

**Benefits**:
- Eliminates race conditions
- Consistent state on failure
- No partial updates
- Easier error handling

---

### 3. Risk Checks Under Lock (TOCTOU Prevention)

**Problem**: Time-of-check-time-of-use (TOCTOU) race conditions where state changes between check and use.

**Best Practice**: All risk checks should happen under the same lock as the write operation.

**Implementation**:
```python
class SafePositionManager:
    def open_position(self, symbol: str, qty: int, price: float) -> bool:
        """Open position with TOCTOU-safe risk checks."""
        with self._lock:  # Single lock for check AND write
            # All risk checks under lock
            if self.position_cap_exceeded(symbol):
                return False
            if self.correlation_limit_exceeded(symbol):
                return False
            if self.loss_cap_exceeded(symbol):
                return False
            
            # Write operation under same lock
            self._positions[symbol] = Position(symbol, qty, price)
            return True
```

**Benefits**:
- Eliminates TOCTOU race conditions
- Deterministic behavior
- No state changes between check and use

---

### 4. Self-Healing with Reconciliation

**Problem**: Derived state can drift from authoritative source, no recovery mechanism.

**Best Practice**: Implement periodic reconciliation to rebuild derived state from authoritative source.

**Implementation**:
```python
class StateReconciler:
    def __init__(self, fills_ledger, position_cache, slot_allocator):
        self.fills_ledger = fills_ledger  # Authoritative source
        self.position_cache = position_cache  # Derived
        self.slot_allocator = slot_allocator  # Derived
        
    async def reconcile(self):
        """Rebuild derived state from fills ledger."""
        # Get authoritative state
        fills = self.fills_ledger.get_all_fills()
        
        # Rebuild positions
        computed_positions = self._compute_positions_from_fills(fills)
        
        # Detect drift
        current_positions = self.position_cache.get_all_positions()
        drift = self._detect_drift(computed_positions, current_positions)
        
        if drift:
            logger.warning(f"Position drift detected: {drift}")
            # Self-heal: rebuild from authoritative source
            self.position_cache.update_all(computed_positions)
            
        # Rebuild slots
        computed_slots = self._compute_slots_from_positions(computed_positions)
        self.slot_allocator.update_all(computed_slots)
```

**Benefits**:
- Automatic recovery from state drift
- Detects corruption early
- Self-healing without manual intervention
- Audit trail of reconciliations

---

### 5. Sequence Number Synchronization

**Problem**: WebSocket and REST sync can update same position concurrently without coordination.

**Best Practice**: Use sequence numbers to order updates and detect conflicts.

**Implementation**:
```python
class SequenceNumberedPositionCache:
    def __init__(self):
        self._positions = {}
        self._sequence_numbers = {}  # market_id -> sequence_number
        
    async def on_websocket_update(self, market_id: str, position: Position, seq_no: int):
        """Handle WebSocket update with sequence number."""
        with self._lock:
            current_seq = self._sequence_numbers.get(market_id, 0)
            if seq_no <= current_seq:
                # Stale update, ignore
                logger.debug(f"Ignoring stale WebSocket update: {seq_no} <= {current_seq}")
                return
            
            # Accept update
            self._positions[market_id] = position
            self._sequence_numbers[market_id] = seq_no
            
    async def on_rest_sync(self, market_id: str, position: Position, seq_no: int):
        """Handle REST sync with sequence number."""
        with self._lock:
            current_seq = self._sequence_numbers.get(market_id, 0)
            if seq_no <= current_seq:
                # Stale sync, ignore
                logger.debug(f"Ignoring stale REST sync: {seq_no} <= {current_seq}")
                return
            
            # Accept sync
            self._positions[market_id] = position
            self._sequence_numbers[market_id] = seq_no
```

**Benefits**:
- Deterministic ordering of updates
- Detects stale updates
- Prevents conflicts
- Easy debugging

---

### 6. Idempotent Operations

**Problem**: Duplicate fills or orders can corrupt state if not handled properly.

**Best Practice**: Ensure all operations are idempotent using unique IDs.

**Implementation**:
```python
class IdempotentFillsLedger:
    def __init__(self):
        self._processed_fill_ids = set()
        
    def on_fill(self, fill: KalshiFill) -> None:
        """Handle fill with idempotency."""
        # Deduplicate by fill_id
        if fill.fill_id in self._processed_fill_ids:
            logger.debug(f"Ignoring duplicate fill: {fill.fill_id}")
            return
        
        # Process fill
        self._processed_fill_ids.add(fill.fill_id)
        self._record_fill(fill)
```

**Benefits**:
- Safe to retry operations
- Handles duplicate messages
- No corruption from duplicates
- Exactly-once semantics

---

### 7. Finally Blocks for Cleanup

**Problem**: Resources (slots, windows) not released on all error paths.

**Best Practice**: Use finally blocks to ensure cleanup happens even on exceptions.

**Implementation**:
```python
class SafeSlotAllocator:
    def request_allocation(self, request: AllocationRequest) -> AllocationResult:
        """Request allocation with guaranteed cleanup."""
        slot_id = None
        
        try:
            # Validate request
            if not self._validate_request(request):
                return AllocationResult(success=False, reason="Invalid request")
            
            # Allocate slot
            slot_id = self._allocate_slot(request)
            
            # Update exposure
            self._update_exposure(request)
            
            return AllocationResult(success=True, slot_id=slot_id)
            
        except Exception as e:
            logger.error(f"Allocation failed: {e}")
            return AllocationResult(success=False, reason=str(e))
            
        finally:
            # Guaranteed cleanup
            if not success and slot_id:
                self._release_slot(slot_id)
                logger.info(f"Released slot {slot_id} due to failure")
```

**Benefits**:
- Guaranteed cleanup
- No resource leaks
- Consistent state
- Easier error handling

---

## Application to MERID Bugs

### Bug 1: Position Cache Race Condition
**Fix**: Implement single unified mutex with sequence number synchronization.

### Bug 2: No Validation When Sync Sources Disagree
**Fix**: Implement reconciliation with fills ledger as authoritative source.

### Bug 4: No Slot Release on All Error Paths
**Fix**: Add finally blocks to ensure slot release on all error paths.

### Bug 5: Window Tracking No Persistence
**Fix**: Implement window state persistence or rebuild from position cache on startup.

### Bug 6: Window Not Cleared on All Error Paths
**Fix**: Add finally blocks to ensure window clearing on all rejection paths.

### Bug 8: No Fill Data Validation
**Fix**: Add fill data validation before recording (idempotency + validation).

### Bug 9: Multiple Enforcement Layers
**Fix**: Implement single pre-trade enforcement gate as outlined in Unified Position Manager design.

### Bug 10: No Atomic Transactions
**Fix**: Implement atomic operations with rollback as outlined in Unified Position Manager design.

---

## Implementation Priority

Based on best practices research, implementation should follow this order:

1. **Critical Priority** (Fixes architectural issues):
   - Implement single unified mutex for position cache (Bug 1)
   - Implement reconciliation with fills ledger (Bug 2)
   - Implement single pre-trade enforcement gate (Bug 9)
   - Implement atomic operations with rollback (Bug 10)

2. **High Priority** (Fixes resource leaks):
   - Add finally blocks for slot release (Bug 4)
   - Implement window state persistence (Bug 5)
   - Add finally blocks for window clearing (Bug 6)
   - Add fill data validation (Bug 8)

3. **Medium Priority** (Code quality):
   - Remove dead code (Bug 3)
   - Improve pending order cleanup (Bug 7)

---

## Conclusion

The best practices research confirms that the Unified Position Manager design is the correct long-term solution. The immediate fixes should focus on:

1. **Single Source of Truth**: Use fills ledger as authoritative source
2. **Atomic Operations**: Implement transactions with rollback
3. **Risk Checks Under Lock**: Prevent TOCTOU race conditions
4. **Self-Healing**: Implement reconciliation
5. **Finally Blocks**: Ensure cleanup on all error paths

These practices are industry-standard and will significantly improve the reliability and correctness of the MERID trading system.
