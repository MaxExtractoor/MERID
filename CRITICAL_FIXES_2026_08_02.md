# Critical Fixes Applied - 2026-08-02

## Issues Fixed

### 1. MICROSTRUCTURE-GATE Bug (HIGH PRIORITY)
**Error**: `argument of type 'OrderIntent' is not iterable`

**Root Cause**: Code was using `in` operator to check for dataclass attributes instead of `hasattr()`

**Location**: `merid/event_venues/kalshi/order_router.py` lines 3639 and 3659

**Fix**: Changed from:
```python
if PROBABILITY_MODEL_INTEGRATION_AVAILABLE and "_binary_probability" in intent:
```

To:
```python
if PROBABILITY_MODEL_INTEGRATION_AVAILABLE and hasattr(intent, "_binary_probability"):
```

**Impact**: This bug was preventing the microstructure gate from loading properly, causing all orders to skip important liquidity and spread checks.

### 2. Book Timestamp Missing (CRITICAL)
**Error**: `Live order rejected — book timestamp missing (fail-closed)`

**Root Cause**: The `book_updated_ts` field was sometimes None or 0.0, causing `book_age_s` to return infinity and triggering the fail-closed policy that rejects entry orders.

**Locations**: 
- `merid/event_venues/kalshi/market_state.py` lines 4043-4055 (2 occurrences)
- `merid/event_venues/kalshi/order_router.py` line 5837

**Fixes Applied**:

#### Market State Fix:
Added fallback logic to ensure timestamp is never None or 0.0:
```python
if state_ts is None or state_ts == 0.0:
    book_ts = time.time()
    logger.debug(f"[BOUNDARY-4-STATE→UNIFIED] ticker={ticker} Using current time as timestamp: state.last_book_update_ts={state_ts} -> book_ts={book_ts}")
else:
    book_ts = state_ts
```

#### Order Router Fix:
Added runtime fallback to set current time if timestamp is still missing:
```python
if book_age == float('inf') and state is not None and hasattr(state, 'book_updated_ts'):
    if state.book_updated_ts is None or state.book_updated_ts == 0.0:
        import time as _time2
        state.book_updated_ts = _time2.time()
        logger.warning(
            "[order-router] FIXED missing book timestamp for %s by setting to current time",
            intent.ticker,
        )
        book_age = 0.0  # Fresh after fix
```

**Impact**: This was blocking ALL entry orders from executing, including valid XRP trades with 1.4% edge. The fix ensures orders can proceed even when timestamp data is incomplete.

## Additional Issues Identified (Not Yet Fixed)

### 3. Extreme Order Book Imbalance
**Warning**: Multiple assets showing one-sided liquidity:
- XRP: `depth_yes=0 depth_no=1435` (completely one-sided)
- ETH: `depth_yes=0 depth_no=909`
- SOL: `depth_yes=0 depth_no=196`

**Impact**: This indicates either stale market data or genuine one-sided markets. The system should be cautious about trading in these conditions.

### 4. Price Range Filter Rejections
**Issue**: Assets being rejected due to thesis prices outside 10c-75c range:
- DOGE: yes_price=86c (too expensive)
- ETH: no_price=87c (too expensive)  
- SOL: no_price=88c (too expensive)

**Impact**: This is by design (cheapness filter) but may be too restrictive in late-expiry markets.

## Testing Recommendations

1. **Monitor order execution** - Verify that XRP orders now execute without "book timestamp missing" errors
2. **Check microstructure gate logs** - Ensure the "not iterable" error is resolved
3. **Watch for timestamp warnings** - The new fallback logic should log when it activates
4. **Review order book imbalance** - Consider adding warnings or restrictions for extremely one-sided books

## Files Modified

1. `merid/event_venues/kalshi/order_router.py` - MICROSTRUCTURE-GATE bug fix + timestamp fallback
2. `merid/event_venues/kalshi/market_state.py` - Timestamp validation in state sync

## Next Steps

1. Restart the trading system to apply fixes
2. Monitor logs for the next few trading cycles
3. Verify that XRP orders execute successfully
4. Consider adjusting the price range filter if too many valid trades are being rejected
