# Orderbook Timestamp Issue - Quick Reference

## The Problem
Entry orders are being rejected with `book_timestamp_missing:fail_closed_policy` because the orderbook snapshot lacks a valid timestamp, causing `state.book_age_s` to return `float('inf')`.

## Key Code Locations

| Component | File | Key Line | Field |
|-----------|------|----------|-------|
| LocalOrderbook | `orderbook.py` | 186 | `_snapshot_ts` |
| LocalOrderbook | `orderbook.py` | 254 | `self._snapshot_ts = snapshot.get("ts") or time.monotonic()` |
| MarketState | `market_state.py` | 4210 | `state.last_book_update_ts = time.monotonic()` |
| MarketState | `market_state.py` | 4050 | `u.book_updated_ts = time.time()` |
| UnifiedState | `unified_market_state.py` | 231 | `book_updated_ts: float = 0.0` |
| UnifiedState | `unified_market_state.py` | 262-266 | `book_age_s` property |
| OrderRouter | `order_router.py` | 5830 | `book_age = state.book_age_s` |
| OrderRouter | `order_router.py` | 5836-5862 | Rejection logic |

## The Data Flow

```
WS Message (snapshot)
    ↓
LocalOrderbook.apply_snapshot()
    ↓ sets _snapshot_ts (from msg.ts or time.monotonic())
    ↓
KalshiMarketStateStore._sync_book_fields()
    ↓ sets state.last_book_update_ts (time.monotonic())
    ↓
KalshiMarketStateStore._sync_unified_book()
    ↓ sets u.book_updated_ts (time.time())
    ↓
UnifiedMarketState.book_age_s
    ↓ returns time.time() - book_updated_ts
    ↓
OrderRouter checks book_age_s
    ↓ Rejects if float('inf')
```

## Critical Issues Found

### Issue 1: Clock Source Mismatch
- `_sync_book_fields()` uses `time.monotonic()`
- `_sync_unified_book()` uses `time.time()`
- `book_age_s` uses `time.time()`
- **Impact**: Inconsistent timestamp sources

### Issue 2: Default Value Problem
- `book_updated_ts` initialized to `0.0` (not `None`)
- `book_age_s` only checks for `None`, not `0.0`
- **Impact**: If never set, `book_age_s` = current_time - 0 = huge number (not infinity)

### Issue 3: Missing Fallback Validation
- No logging to verify `time.monotonic()` fallback is working
- No logging to verify `_sync_unified_book()` is being called
- **Impact**: Silent failures in the timestamp pipeline

## Most Likely Root Causes (In Priority Order)

1. **WS messages lack `ts` field** → fallback to `time.monotonic()` should work, but not verified
2. **`_sync_unified_book()` not being called** → `book_updated_ts` never set from `0.0`
3. **Clock source mismatch** → timestamps being set but not propagated correctly
4. **Race condition** → concurrent updates overwriting timestamps

## Quick Diagnostic Command

Add this logging to identify the issue:

```python
# In apply_orderbook_message() after snapshot application
logger.info(f"[TS-DIAG] ticker={ticker} snapshot_ts={payload.get('ts')} ob._snapshot_ts={ob._snapshot_ts} unified_ts={u.book_updated_ts}")
```

## Immediate Fix (Low Risk)

Change the default value in `unified_market_state.py` line 231:

```python
# Before
book_updated_ts: float = 0.0

# After  
book_updated_ts: Optional[float] = None
```

This makes the "never set" case explicit and allows the existing `None` check to work correctly.

## Verification Steps

1. Add the diagnostic logging above
2. Run the system and observe logs
3. Check if `snapshot_ts` is present in WS messages
4. Check if `ob._snapshot_ts` is being set
5. Check if `unified_ts` is being set
6. Apply fix based on which step fails

## Related Files

- `ORDERBOOK_TIMESTAMP_DEBUG_CHECKLIST.md` - Full diagnostic checklist
- `merid/event_venues/kalshi/orderbook.py` - LocalOrderbook implementation
- `merid/event_venues/kalshi/market_state.py` - MarketStateStore sync logic
- `merid/event_venues/kalshi/unified_market_state.py` - UnifiedMarketState schema
- `merid/event_venues/kalshi/order_router.py` - OrderRouter validation logic
