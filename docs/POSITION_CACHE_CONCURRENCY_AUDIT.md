# PositionCache Concurrency Audit

## Overview
Audit of `KalshiPositionCache` for race conditions between multiple async sources (WebSocket fills, REST sync, price updates).

---

## Components Audited

### 1. Lock Protection

#### Singleton Initialization Lock
```python
import threading as _threading
_position_cache_instance: "KalshiPositionCache | None" = None
_position_cache_lock = _threading.Lock()

def get_position_cache() -> "KalshiPositionCache":
    """Get the global position cache singleton."""
    global _position_cache_instance
    if _position_cache_instance is None:
        with _position_cache_lock:
            if _position_cache_instance is None:
                _position_cache_instance = KalshiPositionCache()
    return _position_cache_instance
```

**Strengths:**
- ✅ Double-checked locking pattern for thread-safe singleton
- ✅ Uses `threading.Lock()` for cross-thread safety

**Weaknesses:**
- ⚠️ None - correctly implemented

---

#### Mutex for Dict Mutations
```python
# BUG-FIX: Add mutex for thread safety during concurrent WebSocket fill events
self._mutex = asyncio.Lock()
```

**Strengths:**
- ✅ Async lock for async context
- ✅ Protects all dict mutations

**Weaknesses:**
- ⚠️ None - correctly implemented

---

### 2. Write Operations

#### on_fill() (Lines 245-386)
**Purpose:** Handle a fill event from WebSocket

**Lock Usage:**
```python
async def on_fill(
    self,
    market_id: str,
    contracts: int,
    price_cents: int,
    fee_cents: int,
    side: str,
    client_order_id: Optional[str] = None,
    fill_id: Optional[str] = None,
    action: str = "buy",
) -> None:
    """Handle a fill event from WebSocket.

    BUG-FIX: Now async with mutex protection to prevent race conditions
    during concurrent WebSocket fill events.
    """
    async with self._mutex:  # ✅ Protected by mutex
        # Task 2: Look up fill_source from fills_ledger if fill_id provided
        fill_source = await self._lookup_fill_source(fill_id, client_order_id)

        # Look up TP targets from pending registry
        tp_targets = {}
        if client_order_id:
            tp_targets = self._pending_tp_targets.get(client_order_id, {}) or {}

        position = self._positions.get(market_id)

        if position is None:
            # New position - capture TP targets from the opening order
            new_position = CachedPosition(...)
            self._positions[market_id] = new_position
            
            # Submit resting bracket orders
            if fill_source != "hedge" and new_position.take_profit_price_cents:
                await self._submit_resting_bracket(new_position)
        else:
            # Update existing
            pre_contracts = position.contracts
            position.apply_fill(contracts, price_cents, fee_cents, side, action=action)
            
            # Cancel resting brackets when position is fully closed
            if position.contracts == 0:
                if position.tp_bracket_client_tag or position.sl_bracket_client_tag:
                    await self._cancel_brackets(position)
                self._pending_tp_targets.pop(client_order_id, None)
                del self._positions[market_id]
            
            # Resize bracket when position grows
            elif action == "buy" and side == position.side and position.contracts > pre_contracts:
                await self._cancel_brackets(position)
                await self._submit_resting_bracket(position)
            
            self._pending_tp_targets.pop(client_order_id, None)
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Single fill processed quickly (minimal lock hold time)
- ✅ Handles new positions and updates
- ✅ Manages TP targets and bracket orders

**Weaknesses:**
- ⚠️ **Long-held lock** - `_submit_resting_bracket()` and `_cancel_brackets()` are async calls that happen under lock
- ⚠️ Could block other fills while waiting for bracket order API calls

**Recommendations:**
1. Move bracket order submission outside lock (queue for later execution)
2. Or use a separate lock for bracket order management

---

#### sync_from_rest() (Lines 434-479)
**Purpose:** Sync cache with REST API positions (fallback/reconciliation)

**Lock Usage:**
```python
async def sync_from_rest(self, positions: list) -> None:
    """Sync cache with REST API positions (fallback/reconciliation).
    
    BUG-FIX: Now async with mutex protection for thread safety.
    PRODUCTION FIX (2026-05-10): Filter out test positions to prevent bleeding into production.
    PRODUCTION FIX (2026-05-11): Filter out closed positions (contracts=0) to prevent phantom positions.
    """
    async with self._mutex:  # ✅ Protected by mutex
        try:
            self._positions.clear()  # ⚠️ Clears entire cache
            for pos in positions:
                market_id = pos.get("market_id") or pos.get("ticker")
                if not market_id:
                    continue
                
                # Filter out test positions
                if _is_test_ticker(market_id):
                    logger.debug(f"Skipping test ticker in position cache sync: {market_id}")
                    continue

                contracts = int(pos.get("contracts", 0))
                
                # Only cache open positions (contracts > 0)
                if contracts == 0:
                    logger.debug(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
                    continue

                self._positions[market_id] = CachedPosition(...)

            self._last_sync = datetime.now(timezone.utc)
            logger.info(f"Position cache synced from REST: {len(self._positions)} positions (test & closed filtered)")
        except Exception as e:
            logger.error(f"Position cache sync from REST failed: {e}")
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Filters out test positions
- ✅ Filters out closed positions
- ✅ Updates `_last_sync` timestamp

**Weaknesses:**
- ⚠️ **Clears entire cache** - loses TP targets from existing positions
- ⚠️ No drift detection - doesn't compare old vs new positions before clearing
- ⚠️ No reconciliation of partial fills - assumes REST API is always correct

**Recommendations:**
1. Preserve TP targets from existing cache during sync (like venue_adapter.py does)
2. Add drift detection before clearing cache
3. Log positions being removed for audit trail

---

#### update_position_price() (Lines 387-399)
**Purpose:** Update current price and unrealized PnL when market price changes

**Lock Usage:**
```python
async def update_position_price(self, market_id: str, price_cents: int) -> None:
    """Update current price and unrealized PnL when market price changes.
    
    CRITICAL FIX: This updates current_price_cents for micro-scalp PnL calculation.
    Without this, micro-scalp exits with $0 PnL because current_price_cents is stale.
    
    BUG-FIX: Now async with mutex protection for thread safety.
    """
    async with self._mutex:  # ✅ Protected by mutex
        position = self._positions.get(market_id)
        if position:
            position.current_price_cents = price_cents
            position.update_unrealized_pnl(price_cents)
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Fast operation (minimal lock hold time)
- ✅ Updates both price and PnL atomically

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### clear() (Lines 481-488)
**Purpose:** Clear all cached positions

**Lock Usage:**
```python
async def clear(self) -> None:
    """Clear all cached positions.
    
    BUG-FIX: Now async with mutex protection for thread safety.
    """
    async with self._mutex:  # ✅ Protected by mutex
        self._positions.clear()
        logger.info("Position cache cleared")
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Fast operation

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 3. Read Operations

#### get_position() (Lines 401-403)
**Purpose:** Get cached position for a market

**Lock Usage:**
```python
def get_position(self, market_id: str) -> Optional[CachedPosition]:
    """Get cached position for a market."""
    return self._positions.get(market_id)  # ⚠️ NOT protected by mutex
```

**Strengths:**
- ✅ Fast read from dict

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated position during on_fill()

**Recommendation:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")

---

#### get_all_positions() (Lines 405-422)
**Purpose:** Get all cached positions

**Lock Usage:**
```python
def get_all_positions(self, validate_freshness: bool = True) -> Dict[str, CachedPosition]:
    """Get all cached positions.
    
    Args:
        validate_freshness: If True, checks if cache is stale and logs warning.
        
    Returns:
        Dict of market_id -> CachedPosition
    """
    if validate_freshness and self._last_sync:
        from datetime import datetime, timezone
        staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
        if staleness_seconds > 300:  # 5 minutes
            logger.warning(
                f"[POSITION-CACHE-STALE] Cache is {staleness_seconds:.0f}s old. "
                f"Consider calling sync_from_rest() before get_all_positions()."
            )
    return dict(self._positions)  # ⚠️ NOT protected by mutex
```

**Strengths:**
- ✅ Returns dict copy (prevents external mutation)
- ✅ Validates staleness

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated positions during on_fill()

**Recommendation:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")

---

#### get_open_positions() (Lines 424-432)
**Purpose:** Get all open positions for a market

**Lock Usage:**
```python
def get_open_positions(self, market_id: str) -> List[CachedPosition]:
    """Get all open positions for a market (returns list for compatibility).
    
    Returns empty list if no position, or list with single position if exists.
    """
    position = self._positions.get(market_id)  # ⚠️ NOT protected by mutex
    if position and position.contracts > 0:
        return [position]
    return []
```

**Strengths:**
- ✅ Fast read from dict

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated position during on_fill()

**Recommendation:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")

---

### 4. TP Target Registry

#### register_tp_targets() (Lines 191-214)
**Purpose:** Register TP targets for an order before it fills

**Lock Usage:**
```python
def register_tp_targets(
    self,
    client_order_id: str,
    take_profit_price_cents: Optional[int] = None,
    take_profit_r_multiple: Optional[float] = None,
    stop_loss_price_cents: Optional[int] = None,
) -> None:
    """Register TP targets for an order before it fills.

    Called by order_router when placing orders with TP targets.
    Targets are looked up by client_order_id when fills arrive.
    """
    self._pending_tp_targets[client_order_id] = {  # ⚠️ NOT protected by mutex
        "tp_price": take_profit_price_cents,
        "tp_r": take_profit_r_multiple,
        "sl_price": stop_loss_price_cents,
        "registered_at": time.time(),
    }
    # Opportunistic GC every 100 registrations to keep the dict bounded.
    if len(self._pending_tp_targets) % 100 == 0:
        self._purge_stale_tp_targets()
```

**Strengths:**
- ✅ Fast dict write
- ✅ Opportunistic GC to prevent unbounded growth

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could race with on_fill() reading from same dict
- ⚠️ Could see stale data if on_fill() reads before write completes

**Recommendation:**
1. Add `async with self._mutex` for consistency

---

#### _purge_stale_tp_targets() (Lines 216-235)
**Purpose:** Remove tp_target entries older than max_age_seconds

**Lock Usage:**
```python
def _purge_stale_tp_targets(self, max_age_seconds: float = 86400.0) -> int:
    """Remove tp_target entries older than ``max_age_seconds`` (default 24h).

    Returns the number of entries removed. Called opportunistically from
    register_tp_targets and on demand from operators / tests.
    """
    cutoff = time.time() - max_age_seconds
    stale_ids = [
        coid
        for coid, target in self._pending_tp_targets.items()  # ⚠️ NOT protected by mutex
        if float(target.get("registered_at", 0.0)) < cutoff
    ]
    for coid in stale_ids:
        self._pending_tp_targets.pop(coid, None)  # ⚠️ NOT protected by mutex
    if stale_ids:
        logger.info(
            "[TP-TARGET-GC] purged %d stale TP targets (>%ds old)",
            len(stale_ids), int(max_age_seconds),
        )
    return len(stale_ids)
```

**Strengths:**
- ✅ Prevents unbounded growth
- ✅ Returns count of removed entries

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could race with register_tp_targets() or on_fill()
- ⚠️ Could miss entries added during iteration

**Recommendation:**
1. Add `async with self._mutex` for consistency

---

#### discard_tp_targets() (Lines 237-243)
**Purpose:** Explicitly drop TP targets for a canceled / rejected order

**Lock Usage:**
```python
def discard_tp_targets(self, client_order_id: str) -> bool:
    """Explicitly drop TP targets for a canceled / rejected order.

    Called by order_router when an order is canceled before any fill so
    the registry doesn't leak the (never-used) targets.
    """
    return self._pending_tp_targets.pop(client_order_id, None) is not None  # ⚠️ NOT protected by mutex
```

**Strengths:**
- ✅ Fast dict operation
- ✅ Returns bool indicating if entry existed

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could race with register_tp_targets() or on_fill()

**Recommendation:**
1. Add `async with self._mutex` for consistency

---

### 5. Reconciliation

#### reconcile_with_fills_ledger() (Lines 522-582)
**Purpose:** Reconcile position cache with fills_ledger for consistency

**Lock Usage:**
```python
async def reconcile_with_fills_ledger(
    self,
    ledger: Optional[Any] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Reconcile position cache with fills_ledger for consistency.
    
    Task 4: Detects discrepancies between cache and ledger hedge fill tracking.
    
    Args:
        ledger: KalshiFillsLedger instance (uses self._fills_ledger if None)
        dry_run: If True, only reports issues without correcting them
    """
    # ... reconciliation logic ...
    # ⚠️ NOT protected by mutex - reads from self._positions directly
```

**Strengths:**
- ✅ Detects discrepancies between cache and ledger
- ✅ Dry-run mode for safe testing

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated positions during on_fill()

**Recommendation:**
1. Add `async with self._mutex` for consistency

---

## Race Condition Analysis

### Potential Race Conditions

#### 1. Concurrent on_fill() Calls
**Scenario:** Two WS fills arrive concurrently for the same market

**Current Protection:**
- Both use `async with self._mutex`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Recommendation:** None - correctly protected

---

#### 2. on_fill() During sync_from_rest()
**Scenario:** WS fill arrives while REST sync is clearing cache

**Current Protection:**
- Both use `async with self._mutex`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Impact:**
- If sync_from_rest() wins: fill is lost (cache cleared before fill applied)
- If on_fill() wins: fill is applied, then immediately cleared by sync

**Recommendation:**
1. Preserve fills during sync (don't clear entire cache)
2. Or queue fills during sync and apply after sync completes

---

#### 3. Read During Write
**Scenario:** `get_position()` called while `on_fill()` is updating position

**Current Protection:**
- Write is protected by mutex
- Read is NOT protected by mutex

**Risk:** MEDIUM - could read inconsistent state (partially updated position)

**Impact:**
- Could see position with old contracts but new price
- Could see position before fill_source is set
- Could see position before TP targets are applied

**Recommendation:**
1. Add mutex protection to read operations (or document as "eventually consistent")

---

#### 4. TP Target Registry Race
**Scenario:** `register_tp_targets()` called while `on_fill()` is reading from registry

**Current Protection:**
- Neither operation is protected by mutex

**Risk:** MEDIUM - could see stale data or miss updates

**Impact:**
- on_fill() could miss TP targets if register happens mid-read
- Could cause fills to not have TP targets applied

**Recommendation:**
1. Add mutex protection to TP target registry operations

---

#### 5. Bracket Order Submission Under Lock
**Scenario:** `on_fill()` submits bracket order under lock, blocking other fills

**Current Protection:**
- Bracket order submission happens under mutex

**Risk:** MEDIUM - long-held lock blocks other fills

**Impact:**
- Other fills wait for bracket order API call to complete
- Could cause fill processing backlog under high volume

**Recommendation:**
1. Move bracket order submission outside lock (queue for later execution)
2. Or use a separate lock for bracket order management

---

## Recommendations

### High Priority
1. **Add mutex protection to read operations**
   - `get_position()`, `get_all_positions()`, `get_open_positions()`
   - Or document as "eventually consistent" and accept race condition risk

2. **Add mutex protection to TP target registry**
   - `register_tp_targets()`, `_purge_stale_tp_targets()`, `discard_tp_targets()`
   - Prevents race conditions with on_fill() reading from registry

3. **Move bracket order submission outside lock**
   - Queue bracket orders for later execution
   - Reduces lock hold time during on_fill()

4. **Preserve fills during sync_from_rest()**
   - Don't clear entire cache - preserve TP targets
   - Or queue fills during sync and apply after sync completes

### Medium Priority
5. **Add lock timeout to mutex acquisitions**
   - Use `asyncio.wait_for(self._mutex.acquire(), timeout=5.0)`
   - Prevents deadlocks if exception occurs

6. **Add drift detection before cache clear**
   - Compare old vs new positions before clearing
   - Log positions being removed for audit trail

### Low Priority
7. **Add metrics for lock contention**
   - Track mutex wait time
   - Track mutex acquisition failures
   - Alert on high contention

---

## Conclusion

**Overall Assessment:** The concurrency protection is **partially implemented** with good write protection but **missing read protection** and **TP target registry protection**.

**Strengths:**
- All write operations protected by `asyncio.Lock`
- Singleton initialization correctly protected
- Good filtering (test positions, closed positions)
- Staleness detection

**Weaknesses:**
- Read operations NOT protected by mutex
- TP target registry NOT protected by mutex
- Long-held lock during bracket order submission
- Cache clear loses TP targets

**Critical Fixes Needed:**
1. Add mutex protection to read operations (or document as eventually consistent)
2. Add mutex protection to TP target registry
3. Move bracket order submission outside lock
4. Preserve fills during sync_from_rest()
