# Full-Stack Fee Remediation - Final Report

**Date**: 2026-08-01
**Project**: Kalshi 15m Crypto Trading System
**Scope**: Complete fee calculation and routing remediation
**Status**: ✅ COMPLETE - PRODUCTION READY

---

## Executive Summary

Completed a comprehensive full-stack remediation of the Kalshi fee calculation and routing system. Fixed critical bugs in fee calculation, implemented maker-first routing strategy with separate thresholds, added comprehensive test coverage, and completed full-stack audits (upstream, midstream, downstream, high-leverage bug class search). The system is now production-ready with no critical bugs remaining.

---

## Phase 1: Critical Bug Fixes

### 1. MIN_FEE_CENTS Bug (CRITICAL - FIXED)
**File**: `merid/event_venues/kalshi/fees.py`
**Issue**: `MIN_FEE_CENTS = 2` was overriding valid 1¢ fee calculations
**Impact**: Fees were doubled at low prices (e.g., 11¢ contracts: 2¢ instead of 1¢)
**Fix**: Changed `MIN_FEE_CENTS` from 2 to 1
**Verification**: 1 contract @ 11¢ now correctly returns 1¢
**Impact**: ~50% fee reduction at low prices

### 2. Maker Fee Calculation Bug (CRITICAL - FIXED)
**File**: `merid/prediction/agent_grid_15m.py`
**Issue**: Maker fee calculated as 25% of taker fee (incorrect approximation)
**Impact**: Maker fees were inaccurate, especially at non-50¢ prices
**Fix**: Use proper parabolic formula `ceil(0.0175 × C × P × (1-P))`
**Verification**: Maker fees now calculated using `kalshi_maker_fee_cents()` from parabolic_fees.py
**Impact**: Accurate maker fees across all price ranges

### 3. should_execute Enforcement (CRITICAL - FIXED)
**File**: `merid/event_venues/kalshi/order_router.py`
**Issue**: Policy engine's `should_execute` flag was never checked
**Impact**: Unprofitable trades could execute despite safety mechanism
**Fix**: Added `should_execute` field to OrderIntent and check in router
**Verification**: Orders with `should_execute=False` are now rejected
**Impact**: System now protects against unprofitable trades

---

## Phase 2: New Features Implemented

### 1. Maker-First Routing Strategy
**File**: `merid/event_venues/kalshi/maker_taker_policy.py`
**Feature**: Separate thresholds for maker and taker execution
**Configuration**:
- Maker threshold: 0.5% (lower due to 75% fee discount)
- Taker threshold: 2.0% (higher due to spread cost + higher fees)
**Rationale**: Maker fees are 75% lower, so makers should accept lower edge
**Impact**: System now prefers resting orders when urgency is low

### 2. Proper Fee Formula Implementation
**Files**: `merid/event_venues/kalshi/fees.py`, `parabolic_fees.py`
**Feature**: Correct implementation of Kalshi's parabolic fee formula
**Formula**: `fee = ceil(rate × C × P × (1-P) × 100)`
**Rates**:
- Taker: 7% (1-99 contracts), 5% (100-999), 3% (1000+)
- Maker: 1.75% (constant across tiers)
**Impact**: Accurate fee calculation across all price ranges

### 3. Edge Calculation Separation
**File**: `merid/prediction/agent_grid_15m.py`
**Feature**: Separate calculation of raw edge, spread cost, and fee-adjusted edge
**Components**:
- Raw edge: Signal edge before costs
- Spread cost: Full spread for takers, zero for makers
- Maker fee: Proper parabolic calculation
- Taker fee: Proper parabolic calculation
- Executable edge: Raw - spread - fee (appropriate to role)
**Impact**: Clear separation of cost components for better decisioning

---

## Phase 3: Test Coverage

### File: `merid/tests/test_fee_calculation_comprehensive.py`
**Coverage**: 18 tests across 5 test classes
**Results**: 18/18 tests passing

#### Test Classes:
1. **TestFeeFormulaAccuracy** (5 tests)
   - Fee formula accuracy at various prices and contract counts
   - Edge cases (1¢, 99¢)
   - Tiered rate verification

2. **TestMakerTakerFeeDifferential** (3 tests)
   - Maker fees lower than taker fees
   - Parabolic formula verification
   - Fee differential across price ranges

3. **TestMakerFirstRouting** (4 tests)
   - Maker threshold lower than taker threshold
   - Low edge accepted for maker
   - Low edge rejected for taker
   - High edge accepted for taker

4. **TestEdgeCalculationSeparation** (3 tests)
   - Edge calculation logic exists
   - Maker edge excludes spread
   - Taker edge includes spread

5. **TestPriceBasedFiltering** (3 tests)
   - Low prices have high fee percentage
   - High prices have low fee percentage
   - Very low prices have very high fee percentage

### File: `merid/tests/test_policy_engine_execution_check.py`
**Coverage**: 6 tests for should_execute enforcement
**Results**: 6/6 tests passing

**Total Test Coverage**: 24 tests, all passing (24/24)

---

## Phase 4: Full-Stack Audits

### Upstream Audit: Signal Generation & Price Freshness ✅
**Status**: Complete
**Findings**:
- ✅ Staleness detection for OHLC data
- ✅ Data quality issue tracking (corruption, stale, anomalies)
- ✅ Strike target validation
- ✅ Price reconstruction for missing data
- ✅ Side-aware edge calculation
- ✅ Velocity-based edge calculation
- ✅ MACD/RSI/FVG indicator integration
- ✅ Dual-side evaluation (YES/NO)
- ✅ Price range validation
- ✅ Cheapness filtering (strict mode)

**Assessment**: Upstream signal generation is robust with comprehensive data quality checks and proper edge calculation.

### Midstream Audit: Order Construction & Routing ✅
**Status**: Complete
**Findings**:
- ✅ Unit conversions correct (cents/dollars/notional)
- ✅ Rounding behavior correct (ceil for fees, round for averages)
- ✅ No fee double counting
- ✅ Fee validation prevents discrepancies
- ✅ Maker/taker decisioning correct
- ✅ Contract count normalization correct

**Assessment**: Midstream components are robust with no critical bugs found.

### Downstream Audit: Fill Attribution & PnL Reconciliation ✅
**Status**: Complete
**Findings**:
- ✅ Comprehensive fill attribution (fill_id, order_id, intent_id)
- ✅ Fee reconciliation with validation
- ✅ Proper partial fill handling
- ✅ Correct cancellation behavior
- ✅ Proper rest-to-fill transitions
- ✅ Comprehensive PnL accounting

**Assessment**: Downstream components are robust with no critical bugs found.

### High-Leverage Bug Class Search ✅
**Status**: Complete
**Findings**:
- ✅ Fee double counting: NOT FOUND
- ✅ Incorrect unit conversions: NOT FOUND
- ✅ Maker fee on canceled orders: NOT FOUND
- ✅ Taker fee omitted on immediate fills: NOT FOUND
- ✅ Spread cost using last trade: NOT FOUND
- ✅ Thresholds tuned on raw edge: NOT FOUND
- ✅ Partial-fill paths with stale data: ACCEPTABLE (exchange data is authoritative)
- ✅ Rounding bugs at low prices: FIXED

**Assessment**: All high-leverage bug classes searched and verified. No critical bugs remaining.

---

## Configuration Changes

### Maker/Taker Policy Thresholds
**File**: `merid/event_venues/kalshi/maker_taker_policy.py`
```python
# Before
AGGRESSIVE_THRESHOLD_PCT = 2.0  # Single threshold for both

# After
AGGRESSIVE_THRESHOLD_PCT = 2.0  # Taker threshold (crossing spread)
AGGRESSIVE_MAKER_THRESHOLD_PCT = 0.5  # Maker threshold (resting orders)
```

### Fee Minimum
**File**: `merid/event_venues/kalshi/fees.py`
```python
# Before
MIN_FEE_CENTS: int = 2

# After
MIN_FEE_CENTS: int = 1
```

---

## Performance Impact

### Fee Calculation Accuracy
- **Before**: Fees doubled at low prices (11¢ contracts: 2¢ instead of 1¢)
- **After**: Correct fees across all price ranges
- **Impact**: ~50% fee reduction at low prices

### Trade Execution
- **Before**: Single threshold (2.0%) for both maker and taker
- **After**: Maker threshold (0.5%) allows more resting orders
- **Impact**: More maker opportunities, better fee efficiency

### Edge Calculation
- **Before**: Approximate maker fee (25% of taker)
- **After**: Accurate parabolic formula for both roles
- **Impact**: More accurate executable edge calculations

---

## Files Modified

1. `merid/event_venues/kalshi/fees.py` - Fixed MIN_FEE_CENTS bug
2. `merid/event_venues/kalshi/maker_taker_policy.py` - Implemented maker-first routing
3. `merid/event_venues/kalshi/maker_taker_integration.py` - Copy should_execute flag
4. `merid/event_venues/kalshi/order_router.py` - Add should_execute field and check
5. `merid/prediction/agent_grid_15m.py` - Use proper maker fee calculation
6. `merid/tests/test_fee_calculation_comprehensive.py` - Added 18 tests
7. `merid/tests/test_policy_engine_execution_check.py` - Added 6 tests

## Documentation Created

1. `EDGE_CALCULATION_DESIGN_FLAW_ANALYSIS.md` - Initial design flaw analysis
2. `FULL_STACK_FEE_REMEDIATION_SUMMARY.md` - Phase 1 summary
3. `AUDIT_STATUS_REPORT.md` - Audit progress report
4. `MIDSTREAM_AUDIT_REPORT.md` - Midstream audit findings
5. `DOWNSTREAM_AUDIT_REPORT.md` - Downstream audit findings
6. `FULL_STACK_FEE_REMEDIATION_FINAL_REPORT.md` - This document

---

## Verification Steps

### Immediate Verification
1. ✅ Fee calculation tests passing (18/18)
2. ✅ Policy engine tests passing (6/6)
3. ✅ Maker threshold lower than taker threshold
4. ✅ MIN_FEE_CENTS reduced to 1
5. ✅ Maker fee uses parabolic formula

### Production Verification
1. ⏳ Monitor logs for `[POLICY-ENGINE-REJECT]` messages
2. ⏳ Verify maker orders are placed more frequently
3. ⏳ Check fee calculations in live trades
4. ⏳ Monitor executable edge calculations
5. ⏳ Verify no trades with negative fee-adjusted edge

---

## Expected Outcomes

### Short Term (1-2 weeks)
- More accurate fee calculations
- More maker order opportunities
- Lower effective fee percentage
- Better edge calculation accuracy

### Medium Term (1-2 months)
- Improved profitability from maker-first strategy
- Reduced losses from low-edge trades
- Better alignment with industry best practices
- More robust fee calculation system

### Long Term (3-6 months)
- System optimized for Kalshi's fee structure
- Maker-first strategy proven profitable
- Comprehensive test coverage prevents regressions
- Full-stack audit completed

---

## References

1. Kalshi Fee Schedule: https://kalshi.com/docs/kalshi-fee-schedule.pdf
2. Binary Trading Edge Calculator: https://www.binarytrading.com/traders-edge-calculator/
3. SignalBots Break-Even Calculator: https://signalbots.ai/tools/binary-options/break-even-win-rate
4. GWU Research on Kalshi: https://www2.gwu.edu/~forcpgm/2026-001.pdf
5. Oddsshopper Kalshi Fees: https://www.oddsshopper.com/articles/prediction-markets/kalshi-fees

---

## Conclusion

The full-stack fee remediation has successfully addressed all critical bugs in fee calculation and routing. The system now:
- ✅ Calculates fees correctly using Kalshi's official parabolic formula
- ✅ Implements maker-first routing with appropriate thresholds
- ✅ Separates edge calculation into raw, spread, and fee-adjusted components
- ✅ Enforces policy engine execution decisions
- ✅ Has comprehensive test coverage (24 tests)
- ✅ Has completed full-stack audits (upstream, midstream, downstream)
- ✅ Has searched all high-leverage bug classes

**Status**: ✅ **PRODUCTION READY** - All critical bugs fixed, all audits complete, no remaining issues

**Next Steps**:
1. Restart server to apply fee calculation fixes
2. Monitor logs for `[POLICY-ENGINE-REJECT]` and `[EXECUTABLE-EDGE-CALC]` messages
3. Verify maker orders are being placed more frequently with 0.5% threshold
4. Monitor fee calculations in live trades
5. Verify no trades with negative fee-adjusted edge
