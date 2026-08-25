# YES/NO Order Handling Fix - Comprehensive Investigation and Resolution

## Executive Summary

**Issue**: BUY_NO trades were failing to execute despite being generated as valid candidates. The root cause was incorrect price adjustment logic that used YES mid-prices for NO orders, causing BUY_NO orders to be adjusted in the wrong direction and rejected for crossing the spread.

**Impact**: Only BUY_YES trades were executing; BUY_NO trades were being rejected at the price validation stage.

**Resolution**: Applied side-aware price adjustments across the order router to ensure NO orders use NO mid-prices (100 - YES_mid) instead of YES mid-prices.

**Status**: ✅ All fixes implemented and tested. 18 new comprehensive tests added, all passing.

---

## Root Cause Analysis

### The Bug

The order router's price adjustment logic was designed for YES contracts and assumed all orders should use YES mid-price. For NO contracts, this caused incorrect adjustments:

**Example from logs (ETH BUY_NO):**
- Signal price: 37c (correct for NO side)
- YES mid: 63c, so NO mid should be: 100 - 63 = 37c
- **Bug**: Price adjustment used YES mid (63c) instead of NO mid (37c)
- Result: 37c → 42c (sweet spot) → 47c (price adjustment)
- **Rejection**: BUY_NO at 47c above NO ask of 37c (would cross spread)

### Why This Happened

1. **Price Adjustment Function** (`_adjust_order_price_for_fill_rate`):
   - Used `state.mid_cents` (YES mid) for all orders
   - For BUY_NO, this meant adjusting toward YES mid (63c) instead of NO mid (37c)
   - This pushed the price in the wrong direction for NO orders

2. **Sweet Spot Logic** (`_determine_dynamic_order_type`):
   - Designed for YES contracts with optimal range 40-55c
   - Applied to NO orders, which naturally have much lower prices (e.g., 37c when YES is 63c)
   - The 40-55c optimal range is inappropriate for NO contracts

3. **Liquidity Check** (`_check_market_liquidity`):
   - Used YES mid-price to calculate depth in dollars for all orders
   - For NO orders, this incorrectly calculated liquidity using YES prices

---

## Fixes Applied

### Fix 1: Price Adjustment Side-Awareness
**File**: `merid/event_venues/kalshi/order_router.py` (line 3856)

**Change**: Added side-aware mid-price calculation to `_adjust_order_price_for_fill_rate`:

```python
# CRITICAL FIX (2026-07-31): Use side-appropriate mid-price for NO orders
# For BUY_NO/SELL_NO orders, use NO mid-price (100 - YES_mid) instead of YES mid-price
# This prevents price adjustment from incorrectly adjusting NO orders based on YES prices
side_lower = intent.side.lower() if intent.side else ""
is_no_side = "no" in side_lower
if is_no_side:
    # For NO orders, use NO mid-price for price adjustment logic
    original_yes_mid = mid_cents
    mid_cents = 100 - mid_cents
    logger.debug(
        "[PRICE-ADJUSTMENT] ticker=%s side=%s using NO mid=%dc (YES mid=%dc) for price adjustment",
        intent.ticker, intent.side, mid_cents, original_yes_mid
    )
```

**Impact**: BUY_NO orders now adjust toward NO mid-price instead of YES mid-price, preventing incorrect direction adjustments.

### Fix 2: Sweet Spot Logic Disabled for NO Orders
**File**: `merid/event_venues/kalshi/order_router.py` (line 4370)

**Change**: Added early return to skip sweet spot logic for NO orders:

```python
# CRITICAL FIX 2026-07-31: Disable sweet spot logic for NO orders
# The 40-55c optimal range is designed for YES contracts only
# For NO contracts, prices naturally range much lower (e.g., 37c when YES is 63c)
# Applying YES-based sweet spot logic to NO orders causes incorrect price adjustments
side_lower = intent.side.lower() if intent.side else ""
is_no_side = "no" in side_lower
if is_no_side:
    logger.debug(
        "[SWEET-SPOT-EXECUTION] ticker=%s side=%s skipping sweet spot logic (designed for YES contracts only)",
        intent.ticker, intent.side
    )
    return "limit", intent.time_in_force or "gtc"
```

**Impact**: NO orders no longer have YES-based sweet spot adjustments applied, preventing incorrect price targeting.

### Fix 3: Liquidity Check Side-Awareness
**File**: `merid/event_venues/kalshi/order_router.py` (line 3975)

**Change**: Added side-aware mid-price calculation to `_check_market_liquidity`:

```python
# CRITICAL FIX (2026-07-31): Use side-appropriate mid-price for NO orders
# For NO orders, use NO mid-price (100 - YES_mid) for liquidity calculation
side_lower = intent.side.lower() if intent.side else ""
is_no_side = "no" in side_lower
mid_cents = getattr(state, 'mid_cents', 50) or 50
if is_no_side:
    # For NO orders, use NO mid-price for liquidity calculation
    mid_cents = 100 - mid_cents
    logger.debug(
        "[LIQUIDITY-CHECK] ticker=%s side=%s using NO mid=%dc (YES mid=%dc) for liquidity calculation",
        intent.ticker, intent.side, mid_cents, 100 - mid_cents
    )
```

**Impact**: Liquidity calculations for NO orders now use correct NO prices, ensuring accurate depth assessments.

---

## Web Research Validation

### Kalshi YES/NO Mechanics

From Kalshi documentation and industry research:

1. **Duality Invariant**: YES_price + NO_price = 100c (always)
   - YES ask = 100 - NO bid
   - NO ask = 100 - YES bid
   - NO mid = 100 - YES mid

2. **Order Book Structure**:
   - Kalshi provides YES bids and NO bids (not asks)
   - Asks must be derived using duality
   - This is a YES-centric API design

3. **Price Validation Best Practices**:
   - Buy orders should not be above ask (would cross spread)
   - Sell orders should not be below bid (would cross spread)
   - For NO orders, must convert YES prices to NO space for validation

4. **Limit Order Execution**:
   - Unmarketable limit orders: price doesn't cross spread (rest on book)
   - Marketable limit orders: price crosses spread (immediate fill)
   - Maker orders (resting) pay no fees on Kalshi
   - Taker orders (crossing spread) pay fees

### Industry Standards

From binary options and prediction market research:

1. **Binary Contract Structure**:
   - Settles at $1.00 (YES wins) or $0.00 (NO wins)
   - Prices reflect implied probabilities
   - YES at 25c = 25% probability, risking 25c to win 75c

2. **Spread Crossing Prevention**:
   - Critical for limit order execution
   - Crossing spread causes rejection or immediate fill at unfavorable price
   - Must validate against side-appropriate ask/bid

3. **Side-Aware Pricing**:
   - NO contracts have inverted price space relative to YES
   - Algorithms designed for YES prices fail on NO prices without conversion
   - Duality invariant must be maintained throughout the pipeline

---

## Test Coverage

### New Test Suite
**File**: `merid/tests/test_yes_no_price_adjustment_fix_2026_07_31.py`

**18 comprehensive tests covering**:

1. **Price Adjustment Tests** (5 tests):
   - BUY_NO uses NO mid-price for adjustment
   - BUY_NO below NO mid adjusts correctly
   - BUY_YES still uses YES mid-price
   - SELL_NO uses NO mid-price for adjustment
   - SELL_YES still uses YES mid-price

2. **Sweet Spot Logic Tests** (4 tests):
   - BUY_NO skips sweet spot logic
   - SELL_NO skips sweet spot logic
   - BUY_YES still uses sweet spot logic
   - SELL_YES still uses sweet spot logic

3. **Price Validation Tests** (2 tests):
   - BUY_NO validated against NO ask (100 - YES bid)
   - SELL_NO validated against NO bid (100 - YES ask)

4. **Duality Consistency Tests** (4 tests):
   - YES + NO = 100c invariant
   - NO mid = 100 - YES mid
   - NO ask = 100 - YES bid
   - NO bid = 100 - YES ask

5. **Real-World Scenario Tests** (2 tests):
   - ETH BUY_NO scenario from logs (exact failing case)
   - BTC BUY_YES scenario (ensure YES orders still work)

6. **All Order Types Test** (1 test):
   - BUY_YES, SELL_YES, BUY_NO, SELL_NO all use correct mid-prices

**Test Results**: ✅ All 18 tests passing

### Existing Test Validation

Ran existing YES/NO related tests to ensure no regressions:

1. `test_side_aware_simple.py` - ✅ 5/5 passing
2. `test_order_router_logging_fix.py` - ✅ 6/6 passing
3. `test_edge_calculation_no_order_fix.py` - ✅ 7/7 passing

---

## End-to-End Verification

### Upstream (Signal Generation)
- ✅ Signal generation already uses side-aware probability calculations
- ✅ NO orders use correct NO probabilities (1 - YES probability)
- ✅ Edge calculations are side-aware

### Midstream (Order Routing)
- ✅ Price adjustment now side-aware (Fix 1)
- ✅ Sweet spot logic disabled for NO orders (Fix 2)
- ✅ Liquidity check now side-aware (Fix 3)
- ✅ Price validation already side-aware (existing fix)
- ✅ Order type determination already side-aware (existing fix)

### Downstream (Execution)
- ✅ Kalshi API integration uses correct side formatting
- ✅ Order submission uses side-appropriate price fields
- ✅ Position tracking handles both YES and NO contracts

### End-to-End Flow
- ✅ Signal → Order Intent → Price Adjustment → Validation → Execution
- ✅ All four order types (BUY_YES, SELL_YES, BUY_NO, SELL_NO) work correctly
- ✅ Duality invariant maintained throughout pipeline

---

## High-Leverage Bugs Identified and Fixed

### Bug 1: Price Adjustment Direction Inversion (HIGH SEVERITY)
- **Impact**: BUY_NO orders adjusted toward YES mid instead of NO mid
- **Effect**: Orders pushed above NO ask, causing rejection
- **Fix**: Side-aware mid-price calculation in `_adjust_order_price_for_fill_rate`
- **Leverage**: Affects all NO orders, blocking entire NO-side trading

### Bug 2: Sweet Spot Logic Inappropriate for NO Orders (MEDIUM SEVERITY)
- **Impact**: YES-based optimal range (40-55c) applied to NO orders
- **Effect**: NO orders targeted at YES prices, causing mispricing
- **Fix**: Disabled sweet spot logic for NO orders
- **Leverage**: Affects NO orders in sub-40c range (most NO orders)

### Bug 3: Liquidity Calculation Using Wrong Prices (LOW SEVERITY)
- **Impact**: Liquidity checks used YES mid for NO orders
- **Effect**: Incorrect liquidity assessment for NO orders
- **Fix**: Side-aware mid-price in `_check_market_liquidity`
- **Leverage**: Could cause false liquidity rejections for NO orders

---

## Best Practices Applied

1. **Side-Aware Design Pattern**:
   - All price-related functions now check order side
   - Convert YES prices to NO space when needed
   - Maintain duality invariant throughout

2. **Explicit Logging**:
   - Added debug logs for NO mid-price usage
   - Track when sweet spot logic is skipped
   - Log liquidity calculation conversions

3. **Comprehensive Testing**:
   - Unit tests for each fix
   - Integration tests for real-world scenarios
   - Regression tests for existing functionality

4. **Documentation**:
   - Clear comments explaining duality relationships
   - References to Kalshi API conventions
   - Links to industry best practices

---

## Recommendations

### Immediate (Completed)
- ✅ Fix price adjustment side-awareness
- ✅ Disable sweet spot logic for NO orders
- ✅ Fix liquidity check side-awareness
- ✅ Add comprehensive test coverage

### Short-Term
- Consider adding NO-specific optimal range if needed (e.g., 60-75c for NO)
- Monitor NO order execution rates in production
- Add metrics for NO vs YES order success rates

### Long-Term
- Architectural review to ensure all price-related code is side-aware by default
- Consider creating a unified PriceSpace abstraction
- Add formal verification of duality invariant in CI/CD

---

## Conclusion

The BUY_NO trade failure was caused by a fundamental assumption in the order router that all orders should use YES mid-prices. This was appropriate for YES contracts but incorrect for NO contracts due to the duality invariant (YES + NO = 100c).

The fix involved making three key functions side-aware:
1. Price adjustment (`_adjust_order_price_for_fill_rate`)
2. Sweet spot logic (`_determine_dynamic_order_type`)
3. Liquidity check (`_check_market_liquidity`)

All fixes are backed by comprehensive tests (18 new tests, all passing) and validated against existing test suites. The solution is consistent with Kalshi's YES-centric API design and industry best practices for binary options trading.

**Status**: ✅ READY FOR PRODUCTION
