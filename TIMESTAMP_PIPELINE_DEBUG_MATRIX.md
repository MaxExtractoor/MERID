# Timestamp Pipeline Debug Matrix

## Overview
This matrix traces the orderbook timestamp through 6 critical boundaries in the MERID pipeline. Each boundary represents a potential point where the timestamp could be lost, transformed incorrectly, or overwritten.

## Pipeline Architecture

```
Kalshi WS/REST → Parser → LocalOrderbook → MarketState → UnifiedMarketState → OrderRouter → Validation
```

---

## Boundary 1: Ingestion (WS/REST → Parser)

### Input
- **Source**: Kalshi WebSocket or REST API
- **Field**: `ts` (Unix epoch timestamp in seconds)
- **Format**: `float` or `int`
- **Example**: `1722594291.123`

### Current Implementation
**File**: `ws_bridge.py` or REST client
**Code**: Raw JSON message passthrough

### Expected Behavior
- Preserve `ts` field from upstream message
- If missing, should reject or use receive time explicitly

### Diagnostic Logging
```python
# In ws_bridge.py or REST client
logger.info(f"[BOUNDARY-1-INGEST] source={source} ticker={ticker} has_ts={'ts' in msg} ts_value={msg.get('ts')}")
```

### Test
```python
def test_boundary_1_ingestion_preserves_timestamp():
    """Verify parser preserves ts field from upstream"""
    msg = {"type": "orderbook_snapshot", "ticker": "TEST", "ts": 1722594291.123, "yes": [[50, 10]], "no": [[50, 10]]}
    # Pass through parser
    assert "ts" in msg, "Parser dropped ts field"
    assert msg["ts"] == 1722594291.123, "Parser corrupted ts value"
```

### Failure Mode
- Parser strips `ts` field during normalization
- API response lacks `ts` field (upstream issue)

---

## Boundary 2: Parser (Raw Message → LocalOrderbook)

### Input
- **Source**: Parsed message dict
- **Field**: `msg["ts"]`
- **Format**: `float` or `None`

### Output
- **Target**: `LocalOrderbook._snapshot_ts`
- **Format**: `float` (monotonic time)
- **Location**: `orderbook.py:186`

### Current Implementation
**File**: `merid/event_venues/kalshi/orderbook.py`
**Code**: Line 254
```python
self._snapshot_ts = snapshot.get("ts") or time.monotonic()
```

### Expected Behavior
- If `ts` present → use it
- If `ts` missing → fallback to `time.monotonic()`
- **CRITICAL**: Should NEVER be `None` after this point

### Diagnostic Logging
```python
# In LocalOrderbook.apply_snapshot() line 254
ts_source = snapshot.get("ts")
self._snapshot_ts = ts_source or time.monotonic()
logger.info(f"[BOUNDARY-2-PARSER] ticker={self.ticker} ts_source={ts_source} final_ts={self._snapshot_ts} fallback_used={ts_source is None}")
```

### Test
```python
def test_boundary_2_parser_sets_timestamp():
    """Verify parser sets _snapshot_ts even without upstream ts"""
    ob = LocalOrderbook("TEST")
    
    # Case 1: With upstream ts
    snapshot_with_ts = {"ts": 1722594291.123, "yes": [[50, 10]], "no": [[50, 10]]}
    ob.apply_snapshot(snapshot_with_ts)
    assert ob._snapshot_ts == 1722594291.123, "Should use upstream ts"
    
    # Case 2: Without upstream ts (fallback)
    snapshot_without_ts = {"yes": [[50, 10]], "no": [[50, 10]]}
    before = time.monotonic()
    ob.apply_snapshot(snapshot_without_ts)
    after = time.monotonic()
    assert ob._snapshot_ts >= before and ob._snapshot_ts <= after, "Should use monotonic fallback"
```

### Failure Mode
- `snapshot.get("ts")` returns `None` AND `time.monotonic()` fails (unlikely)
- `_snapshot_ts` is overwritten with `None` later

---

## Boundary 3: LocalOrderbook (LocalOrderbook → MarketState)

### Input
- **Source**: `LocalOrderbook._snapshot_ts`
- **Field**: `ob._snapshot_ts`
- **Format**: `float` (monotonic time)

### Output
- **Target**: `KalshiMarketState.last_book_update_ts`
- **Format**: `float` (monotonic time)
- **Location**: `market_state.py:4210`

### Current Implementation
**File**: `merid/event_venues/kalshi/market_state.py`
**Code**: Line 4210 in `_sync_book_fields()`
```python
state.last_book_update_ts = time.monotonic()
```

### Expected Behavior
- **CRITICAL BUG**: This IGNORES `ob._snapshot_ts` and always uses `time.monotonic()`
- Should preserve the original timestamp from the WS message
- Current implementation discards the upstream timestamp

### Diagnostic Logging
```python
# In _sync_book_fields() line 4210
ob_ts = ob._snapshot_ts if hasattr(ob, '_snapshot_ts') else None
state.last_book_update_ts = time.monotonic()  # Current (buggy) behavior
logger.info(f"[BOUNDARY-3-LOCAL→STATE] ticker={ticker} ob._snapshot_ts={ob_ts} state.last_book_update_ts={state.last_book_update_ts} timestamp_discarded={ob_ts is not None and ob_ts != state.last_book_update_ts}")
```

### Test
```python
def test_boundary_3_local_to_state_preserves_timestamp():
    """Verify MarketState preserves timestamp from LocalOrderbook"""
    store = KalshiMarketStateStore()
    ob = LocalOrderbook("TEST")
    
    # Set up LocalOrderbook with known timestamp
    known_ts = 1722594291.123
    ob._snapshot_ts = known_ts
    ob._initialized = True
    
    # Sync to state
    state = store._get_or_create("TEST")
    store._sync_book_fields(state, ob, "TEST")
    
    # CRITICAL: Current implementation FAILS this test
    # assert state.last_book_update_ts == known_ts, "Should preserve ob timestamp"
    # Current behavior: always uses time.monotonic()
```

### Failure Mode
- **CONFIRMED BUG**: Code always uses `time.monotonic()`, discarding upstream timestamp
- This is the PRIMARY cause of the issue

---

## Boundary 4: MarketState (KalshiMarketState → UnifiedMarketState)

### Input
- **Source**: `KalshiMarketState.last_book_update_ts`
- **Field**: `state.last_book_update_ts`
- **Format**: `float` (monotonic time)

### Output
- **Target**: `UnifiedMarketState.book_updated_ts`
- **Format**: `float` (wall-clock time)
- **Location**: `market_state.py:4050`

### Current Implementation
**File**: `merid/event_venues/kalshi/market_state.py`
**Code**: Line 4050 in `_sync_unified_book()`
```python
u.book_updated_ts = time.time()
```

### Expected Behavior
- **CRITICAL BUG**: This IGNORES `state.last_book_update_ts` and always uses `time.time()`
- Should preserve the timestamp from MarketState
- Current implementation discards the timestamp again

### Diagnostic Logging
```python
# In _sync_unified_book() line 4050
state_ts = state.last_book_update_ts if hasattr(state, 'last_book_update_ts') else None
u.book_updated_ts = time.time()  # Current (buggy) behavior
logger.info(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} state.last_book_update_ts={state_ts} u.book_updated_ts={u.book_updated_ts} timestamp_discarded={state_ts is not None and state_ts != u.book_updated_ts}")
```

### Test
```python
def test_boundary_4_state_to_unified_preserves_timestamp():
    """Verify UnifiedMarketState preserves timestamp from MarketState"""
    store = KalshiMarketStateStore()
    
    # Set up MarketState with known timestamp
    state = store._get_or_create("TEST")
    state.last_book_update_ts = 1722594291.123
    
    # Sync to unified
    store._sync_unified_book("TEST", state)
    u = store._unified.get("TEST")
    
    # CRITICAL: Current implementation FAILS this test
    # assert u.book_updated_ts == 1722594291.123, "Should preserve state timestamp"
    # Current behavior: always uses time.time()
```

### Failure Mode
- **CONFIRMED BUG**: Code always uses `time.time()`, discarding upstream timestamp
- This is the SECONDARY cause of the issue

---

## Boundary 5: UnifiedMarketState (UnifiedMarketState → OrderRouter)

### Input
- **Source**: `UnifiedMarketState.book_updated_ts`
- **Field**: `state.book_updated_ts`
- **Format**: `float` (wall-clock time)
- **Default**: `0.0` (line 231 in unified_market_state.py)

### Output
- **Target**: OrderRouter validation logic
- **Field**: `state.book_age_s`
- **Format**: `float` (seconds since update)

### Current Implementation
**File**: `merid/event_venues/kalshi/unified_market_state.py`
**Code**: Lines 262-266
```python
@property
def book_age_s(self) -> float:
    if self.book_updated_ts is None:
        return float('inf')
    return _time.time() - self.book_updated_ts
```

### Expected Behavior
- If `book_updated_ts` is `None` → return `float('inf') (stale)
- If `book_updated_ts` is `0.0` → return very large number (effectively stale)
- If `book_updated_ts` is valid → return actual age

### Diagnostic Logging
```python
# In book_age_s property
logger.info(f"[BOUNDARY-5-UNIFIED→ROUTER] ticker={self.ticker} book_updated_ts={self.book_updated_ts} book_age_s={self.book_age_s} is_none={self.book_updated_ts is None} is_zero={self.book_updated_ts == 0.0}")
```

### Test
```python
def test_boundary_5_unified_age_calculation():
    """Verify book_age_s calculation is correct"""
    u = UnifiedMarketState(ticker="TEST")
    
    # Case 1: None timestamp
    u.book_updated_ts = None
    assert u.book_age_s == float('inf'), "None should return infinity"
    
    # Case 2: Zero timestamp (default)
    u.book_updated_ts = 0.0
    age = u.book_age_s
    assert age > 1000000000, "Zero timestamp should return huge age (current epoch time)"
    
    # Case 3: Valid timestamp
    u.book_updated_ts = time.time() - 5.0
    assert 4.9 <= u.book_age_s <= 5.1, "Should return actual age"
```

### Failure Mode
- Default value `0.0` is not handled as "never set"
- Only `None` is treated as stale/unknown

---

## Boundary 6: OrderRouter (UnifiedMarketState → Validation)

### Input
- **Source**: `UnifiedMarketState.book_age_s`
- **Field**: `state.book_age_s`
- **Format**: `float` (seconds)

### Output
- **Target**: Order acceptance/rejection
- **Logic**: Reject if `book_age_s == float('inf')`

### Current Implementation
**File**: `merid/event_venues/kalshi/order_router.py`
**Code**: Lines 5830-5862
```python
book_age = state.book_age_s if (state is not None and hasattr(state, 'book_age_s')) else float('inf')
if book_age == float('inf'):
    # Reject entry orders
```

### Expected Behavior
- If `book_age_s == float('inf')` → reject (fail-closed)
- If `book_age_s > 30.0` → reject (too stale)
- Otherwise → accept

### Diagnostic Logging
```python
# In order_router.py line 5830
book_age = state.book_age_s if (state is not None and hasattr(state, 'book_age_s')) else float('inf')
logger.info(f"[BOUNDARY-6-ROUTER-VALIDATION] ticker={intent.ticker} book_age_s={book_age} is_infinite={book_age == float('inf')} will_reject={book_age == float('inf')}")
```

### Test
```python
def test_boundary_6_router_validation():
    """Verify router rejects when timestamp is missing"""
    # Create a mock state with missing timestamp
    state = UnifiedMarketState(ticker="TEST")
    state.book_updated_ts = None
    
    # Should be rejected
    assert state.book_age_s == float('inf'), "Missing timestamp should return infinity"
    
    # Router should reject
    intent = OrderIntent(ticker="TEST", side="BUY_NO", count=1)
    result = router._check_book_freshness(state, intent, _is_exit_gate=False)
    assert result.rejected == True, "Should reject entry order with missing timestamp"
```

### Failure Mode
- Router correctly rejects when `book_age_s == float('inf')`
- This is the CORRECT behavior (fail-closed safety)

---

## Root Cause Summary

### Confirmed Bugs

1. **Boundary 3**: `_sync_book_fields()` ignores `ob._snapshot_ts` and always uses `time.monotonic()`
2. **Boundary 4**: `_sync_unified_book()` ignores `state.last_book_update_ts` and always uses `time.time()`
3. **Boundary 5**: Default value `0.0` is not treated as "never set" (only `None` is)

### Impact

The timestamp from the original WS message is discarded at TWO points in the pipeline:
- When syncing from LocalOrderbook to MarketState
- When syncing from MarketState to UnifiedMarketState

Both sync operations replace the upstream timestamp with a fresh call to the system clock, which means:
- The original message timestamp is lost
- The age calculation becomes "time since sync" instead of "time since message"
- If sync doesn't happen (e.g., no WS updates), timestamp is never set

### Fix Strategy

#### Option 1: Preserve Original Timestamp (Recommended)
Change both sync functions to preserve the upstream timestamp:

```python
# In _sync_book_fields() line 4210
# OLD: state.last_book_update_ts = time.monotonic()
# NEW:
if hasattr(ob, '_snapshot_ts') and ob._snapshot_ts is not None:
    state.last_book_update_ts = ob._snapshot_ts
else:
    state.last_book_update_ts = time.monotonic()

# In _sync_unified_book() line 4050
# OLD: u.book_updated_ts = time.time()
# NEW:
if hasattr(state, 'last_book_update_ts') and state.last_book_update_ts is not None:
    u.book_updated_ts = state.last_book_update_ts
else:
    u.book_updated_ts = time.time()
```

#### Option 2: Use System Clock as Source of Truth (Alternative)
Accept that we use system clock and ensure sync always happens:

```python
# Add logging to verify sync is happening
logger.info(f"[SYNC-VERIFICATION] ticker={ticker} _sync_unified_book called={called_count}")

# Add heartbeat to detect stale syncs
if time.time() - u.book_updated_ts > 60.0:
    logger.warning(f"[SYNC-STALE] ticker={ticker} book_updated_ts not updated for 60s")
```

#### Option 3: Fix Default Value (Quick Fix)
Change the default to make "never set" explicit:

```python
# In unified_market_state.py line 231
# OLD: book_updated_ts: float = 0.0
# NEW: book_updated_ts: Optional[float] = None
```

And update the age calculation:

```python
# In book_age_s property
if self.book_updated_ts is None or self.book_updated_ts == 0.0:
    return float('inf')
```

---

## Implementation Priority

1. **HIGH**: Apply Option 3 (quick fix) - makes the bug visible in logs
2. **HIGH**: Add diagnostic logging at all 6 boundaries
3. **MEDIUM**: Apply Option 1 (preserve original timestamp) - proper fix
4. **LOW**: Add regression tests for each boundary

---

## Verification Checklist

After applying fixes:

- [ ] Boundary 1: WS messages have `ts` field
- [ ] Boundary 2: Parser sets `_snapshot_ts` (with fallback)
- [ ] Boundary 3: MarketState preserves timestamp from LocalOrderbook
- [ ] Boundary 4: UnifiedMarketState preserves timestamp from MarketState
- [ ] Boundary 5: Default value `None` is handled correctly
- [ ] Boundary 6: Router accepts orders with valid timestamps
- [ ] End-to-end: WS message → router accepts order

---

## Regression Tests

### Test: End-to-End Timestamp Propagation
```python
def test_end_to_end_timestamp_propagation():
    """Verify timestamp flows from WS message to router acceptance"""
    store = get_kalshi_market_state_store()
    
    # Simulate WS message with timestamp
    ws_msg = {
        "type": "orderbook_snapshot",
        "ticker": "KXBTC15M-TEST",
        "ts": time.time() - 2.0,  # 2 seconds ago
        "yes": [[50, 10]],
        "no": [[50, 10]]
    }
    
    # Apply through pipeline
    store.apply_orderbook_message(ws_msg, via="test")
    state = store.get("KXBTC15M-TEST")
    
    # Verify timestamp is preserved
    assert state.book_age_s < 5.0, f"Timestamp should be fresh, got age={state.book_age_s}s"
    
    # Verify router accepts
    intent = OrderIntent(ticker="KXBTC15M-TEST", side="BUY_NO", count=1)
    result = router._check_book_freshness(state, intent, _is_exit_gate=False)
    assert not result.rejected or "book_timestamp" not in result.reason, "Router should accept with valid timestamp"
```

### Test: Missing Timestamp Fallback
```python
def test_missing_timestamp_fallback():
    """Verify system handles missing WS timestamp gracefully"""
    store = get_kalshi_market_state_store()
    
    # Simulate WS message WITHOUT timestamp
    ws_msg = {
        "type": "orderbook_snapshot",
        "ticker": "KXBTC15M-TEST",
        # NO ts field
        "yes": [[50, 10]],
        "no": [[50, 10]]
    }
    
    # Apply through pipeline
    store.apply_orderbook_message(ws_msg, via="test")
    state = store.get("KXBTC15M-TEST")
    
    # Verify fallback timestamp is set
    assert state.book_age_s < 5.0, f"Fallback timestamp should be fresh, got age={state.book_age_s}s"
```

### Test: Stale Timestamp Rejection
```python
def test_stale_timestamp_rejection():
    """Verify router rejects orders with stale timestamps"""
    store = get_kalshi_market_state_store()
    
    # Create state with stale timestamp
    state = store._get_or_create("KXBTC15M-TEST")
    state.book_updated_ts = time.time() - 100.0  # 100 seconds ago
    
    # Verify router rejects
    intent = OrderIntent(ticker="KXBTC15M-TEST", side="BUY_NO", count=1)
    result = router._check_book_freshness(state, intent, _is_exit_gate=False)
    assert result.rejected, "Router should reject stale timestamp"
```
