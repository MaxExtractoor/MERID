# Orderbook Timestamp Missing Debug Checklist

## Problem Summary
The order router is rejecting entry orders with `book_timestamp_missing:fail_closed_policy` because `state.book_age_s` returns `float('inf')`, indicating that `UnifiedMarketState.book_updated_ts` is either `None` or not being set.

## Data Flow Analysis

### 1. LocalOrderbook (orderbook.py)
**Location**: `merid/event_venues/kalshi/orderbook.py`

**Timestamp Field**: `_snapshot_ts: Optional[float]` (line 186)

**Timestamp Setting**: 
```python
# In apply_snapshot() method (line 254)
self._snapshot_ts = snapshot.get("ts") or time.monotonic()
```

**Behavior**: 
- If WS message has `ts` field → use it
- If WS message lacks `ts` field → fallback to `time.monotonic()`
- This should ALWAYS set a timestamp (never None)

**Diagnostic Questions**:
- [ ] Is the WS snapshot message actually missing the `ts` field?
- [ ] Is `time.monotonic()` returning a valid timestamp?
- [ ] Is `_snapshot_ts` being overwritten with `None` after initialization?

### 2. KalshiMarketStateStore (market_state.py)
**Location**: `merid/event_venues/kalshi/market_state.py`

**Timestamp Setting in _sync_book_fields()** (line 4210):
```python
state.last_book_update_ts = time.monotonic()
state.last_update_ts = time.monotonic()
```

**Timestamp Setting in _sync_unified_book()** (line 4050):
```python
u.book_updated_ts = time.time()
```

**Critical Observation**: 
- `_sync_book_fields()` uses `time.monotonic()`
- `_sync_unified_book()` uses `time.time()`
- These are different clock sources!

**Diagnostic Questions**:
- [ ] Is `_sync_book_fields()` being called for every orderbook update?
- [ ] Is `_sync_unified_book()` being called for every orderbook update?
- [ ] Is there a code path where neither is called?
- [ ] Is there a race condition where one overwrites the other?

### 3. UnifiedMarketState (unified_market_state.py)
**Location**: `merid/event_venues/kalshi/unified_market_state.py`

**Timestamp Field**: `book_updated_ts: float = 0.0` (line 231)

**book_age_s Property** (lines 262-266):
```python
@property
def book_age_s(self) -> float:
    # 2026 FIX: Handle None timestamp gracefully - return infinity (stale/unknown)
    if self.book_updated_ts is None:
        return float('inf')
    return _time.time() - self.book_updated_ts
```

**Critical Issue**: 
- If `book_updated_ts` is `None`, returns `float('inf')`
- If `book_updated_ts` is `0.0` (default), returns a very large age (current time - 0)
- The field is initialized to `0.0`, not `None`

**Diagnostic Questions**:
- [ ] Is `book_updated_ts` ever being set to `None` explicitly?
- [ ] Is `book_updated_ts` remaining at its default value `0.0`?
- [ ] Is the default value `0.0` causing `book_age_s` to be extremely large?

### 4. OrderRouter (order_router.py)
**Location**: `merid/event_venues/kalshi/order_router.py`

**Check** (lines 5830-5862):
```python
book_age = state.book_age_s if (state is not None and hasattr(state, 'book_age_s')) else float('inf')
if book_age == float('inf'):
    # Reject entry orders (fail-closed)
```

**Behavior**:
- If `book_age_s` returns `float('inf')`, entry orders are rejected
- Exit orders are allowed to proceed

## Root Cause Hypotheses

### Hypothesis 1: WS Messages Missing `ts` Field
**Test**: Add logging in `LocalOrderbook.apply_snapshot()` to check if `snapshot.get("ts")` is None

**Fix**: If WS messages lack timestamps, ensure the fallback to `time.monotonic()` is working correctly

### Hypothesis 2: _sync_unified_book() Not Being Called
**Test**: Add logging in `_sync_unified_book()` to verify it's being called for each ticker

**Fix**: Ensure the call path from `apply_orderbook_message()` → `_sync_unified_book()` is not broken

### Hypothesis 3: Race Condition Between Clock Sources
**Test**: Add logging to compare `time.monotonic()` vs `time.time()` values

**Fix**: Standardize on one clock source (recommend `time.time()` for wall-clock age calculations)

### Hypothesis 4: book_updated_ts Initialized to 0.0
**Test**: Check if `book_updated_ts` is ever set from its default value of `0.0`

**Fix**: Initialize to `None` instead of `0.0` to distinguish "never set" from "set to epoch"

## Diagnostic Steps

### Step 1: Add Timestamp Logging
Add logging at each timestamp setting point:

**In LocalOrderbook.apply_snapshot()**:
```python
ts_source = snapshot.get("ts")
self._snapshot_ts = ts_source or time.monotonic()
logger.info(f"[ORDERBOOK-TS] ticker={self.ticker} ts_source={ts_source} final_ts={self._snapshot_ts}")
```

**In _sync_book_fields()**:
```python
state.last_book_update_ts = time.monotonic()
logger.info(f"[SYNC-BOOK-FIELDS] ticker={ticker} last_book_update_ts={state.last_book_update_ts}")
```

**In _sync_unified_book()**:
```python
u.book_updated_ts = time.time()
logger.info(f"[SYNC-UNIFIED-BOOK] ticker={ticker} book_updated_ts={u.book_updated_ts}")
```

### Step 2: Check WS Message Format
Add logging in `apply_orderbook_message()` to inspect incoming WS messages:

```python
if channel == "orderbook_snapshot":
    payload = msg.get("msg", msg)
    logger.info(f"[WS-SNAPSHOT-INSPECT] ticker={ticker} has_ts={'ts' in payload} ts_value={payload.get('ts')}")
```

### Step 3: Verify Call Path
Add logging to verify the complete call chain:

```python
# In apply_orderbook_message() after snapshot application
logger.info(f"[CALL-PATH] ticker={ticker} via={via} channel={channel} will_call_sync_unified=True")
```

### Step 4: Check State Initialization
Add logging when UnifiedMarketState is created:

```python
# In _get_or_create_unified()
if ticker not in self._unified:
    logger.info(f"[UNIFIED-CREATE] ticker={ticker} book_updated_ts={u.book_updated_ts}")
```

## Regression Tests

### Test 1: Timestamp Propagation
```python
def test_timestamp_propagation():
    """Verify timestamp flows from WS message to UnifiedMarketState"""
    store = get_kalshi_market_state_store()
    
    # Simulate WS snapshot with timestamp
    snapshot_msg = {
        "type": "orderbook_snapshot",
        "ticker": "KXBTC15M-TEST",
        "ts": time.time(),
        "yes": [[50, 10]],
        "no": [[50, 10]]
    }
    
    store.apply_orderbook_message(snapshot_msg, via="test")
    state = store.get("KXBTC15M-TEST")
    
    # Verify timestamp is set
    assert state.book_age_s < 1.0, f"book_age_s should be fresh, got {state.book_age_s}"
```

### Test 2: Missing Timestamp Fallback
```python
def test_missing_timestamp_fallback():
    """Verify fallback to time.monotonic() when WS lacks ts"""
    store = get_kalshi_market_state_store()
    
    # Simulate WS snapshot WITHOUT timestamp
    snapshot_msg = {
        "type": "orderbook_snapshot",
        "ticker": "KXBTC15M-TEST",
        # NO ts field
        "yes": [[50, 10]],
        "no": [[50, 10]]
    }
    
    store.apply_orderbook_message(snapshot_msg, via="test")
    state = store.get("KXBTC15M-TEST")
    
    # Verify timestamp is still set (via fallback)
    assert state.book_age_s < 1.0, f"Fallback should set timestamp, got book_age_s={state.book_age_s}"
```

### Test 3: Router Accepts Valid Timestamp
```python
def test_router_accepts_valid_timestamp():
    """Verify router accepts orders when timestamp is valid"""
    # Setup: Create a market state with fresh timestamp
    store = get_kalshi_market_state_store()
    # ... setup code ...
    
    # Create intent
    intent = OrderIntent(ticker="KXBTC15M-TEST", side="BUY_NO", count=1)
    
    # Should not reject for timestamp
    result = router.execute_order(intent)
    assert result.status != "rejected" or result.reason != "book_timestamp_missing"
```

### Test 4: Router Rejects Missing Timestamp
```python
def test_router_rejects_missing_timestamp():
    """Verify router rejects orders when timestamp is missing"""
    # Setup: Create a market state with book_updated_ts = None
    store = get_kalshi_market_state_store()
    # ... force book_updated_ts to None ...
    
    # Create intent
    intent = OrderIntent(ticker="KXBTC15M-TEST", side="BUY_NO", count=1)
    
    # Should reject for timestamp
    result = router.execute_order(intent)
    assert result.status == "rejected"
    assert "book_timestamp_missing" in result.reason
```

## Immediate Fixes

### Fix 1: Initialize book_updated_ts to None
**File**: `unified_market_state.py`
**Line**: 231

Change:
```python
book_updated_ts: float = 0.0
```

To:
```python
book_updated_ts: Optional[float] = None
```

This makes the "never set" case explicit.

### Fix 2: Add Defensive Check in _sync_unified_book
**File**: `market_state.py`
**Line**: 4050

Add validation:
```python
u.book_updated_ts = time.time()
logger.info(f"[SYNC-UNIFIED-BOOK] ticker={ticker} book_updated_ts={u.book_updated_ts} (defensive check)")
```

### Fix 3: Standardize Clock Source
**File**: `market_state.py`
**Line**: 4210

Change:
```python
state.last_book_update_ts = time.monotonic()
```

To:
```python
state.last_book_update_ts = time.time()  # Use wall clock for age calculations
```

This aligns with `book_age_s` which uses `time.time()`.

## Investigation Priority

1. **HIGH**: Add logging to verify WS messages have `ts` field
2. **HIGH**: Add logging to verify `_sync_unified_book()` is being called
3. **MEDIUM**: Check if `book_updated_ts` is being set to `None` somewhere
4. **MEDIUM**: Verify clock source consistency
5. **LOW**: Check for race conditions in concurrent updates

## Next Steps

1. Add the diagnostic logging to identify which hypothesis is correct
2. Run the system and observe the logs
3. Apply the appropriate fix based on findings
4. Add regression tests to prevent recurrence
