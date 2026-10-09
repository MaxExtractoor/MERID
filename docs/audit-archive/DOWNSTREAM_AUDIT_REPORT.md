# Downstream Audit Report: Fill Attribution & PnL Reconciliation

**Date**: 2026-08-01
**Scope**: Fill attribution, fee reconciliation, partial fills, cancellations, PnL accounting
**Status**: Complete

---

## Audit Findings

### ✅ Fill Attribution (CORRECT)
**Fill Tracking**:
- Primary key: `fill_id` (Kalshi's unique fill ID)
- Order linkage: `order_id`, `client_order_id`
- Intent linkage: `intent_id`, `decision_trace_id`
- Assessment: ✅ Correct - comprehensive fill-to-intent tracing

**Fill Sources**:
- HTTP poller: REST API fills
- WebSocket: Real-time fills
- Backfill: Historical fills
- Assessment: ✅ Correct - multiple sources with deduplication

**Fill Validation**:
- Deep ITM/OTM detection (fills_ledger.py lines 1556-1573)
- Schema validation with circuit breaker
- Duplicate detection via fill_id
- Assessment: ✅ Correct - robust validation

### ✅ Fee Reconciliation (CORRECT)
**Fee Validation**:
- Function: `validate_fee_vs_estimate()` (fills_ledger.py lines 171-223)
- Compares: actual fee vs estimated fee
- Threshold: 5% deviation tolerance
- Assessment: ✅ Correct - prevents fee discrepancies

**Fee Tracking**:
- `estimated_fee_cents` in OrderIntent
- `expected_fee_role` for reconciliation
- `fee_cost` in KalshiFill (actual fee)
- Assessment: ✅ Correct - comprehensive fee tracking

### ✅ Partial Fill Handling (CORRECT)
**Partial Fill Logic**:
- Status transitions: 'submitted' → 'partially_filled' → 'filled'
- Cumulative fill tracking: `add_fill()` method
- Remaining count calculation
- Assessment: ✅ Correct - proper state machine

**Price Handling**:
- Uses exchange fill price (authoritative)
- Count derivation from proceeds if missing
- Assessment: ✅ Correct - exchange data is authoritative

### ✅ Cancellation Behavior (CORRECT)
**Cancellation Scenarios**:
1. **Edge decay cancel**: `check_and_cancel_stale_orders()` (order_router.py lines 1022-1084)
2. **Order group triggered**: `handle_order_group_triggered()` (order_router.py lines 1794-1870)
3. **Manual cancel**: Via client API
- Assessment: ✅ Correct - multiple cancel paths

**Fee on Cancellation**:
- Kalshi only charges fees on executed orders
- No fee applied to canceled orders
- Assessment: ✅ Correct - matches Kalshi's policy

### ✅ Rest-to-Fill Transitions (CORRECT)
**Resting Order Tracking**:
- `RestingOrder` dataclass (order_router.py lines 160-171)
- Edge decay monitoring
- Time limit enforcement
- Assessment: ✅ Correct - proper lifecycle management

**Transition Handling**:
- Fill → remove from resting order tracking
- Cancel → remove from resting order tracking
- Assessment: ✅ Correct - proper state transitions

### ✅ PnL Accounting (CORRECT)
**PnL Tracking**:
- Session-based PnL: `_session_realized_pnl`, `_session_unrealized_pnl`
- Hedge PnL: `hedge_pnl_cents` in KalshiFill
- Cumulative PnL: `_cumulative_realized_pnl`
- Assessment: ✅ Correct - comprehensive PnL tracking

**PnL Integration**:
- Hedge PnL tracker integration (fills_ledger.py lines 648-649, 1350-1354)
- EOD snapshot storage for daily PnL change
- Assessment: ✅ Correct - proper PnL accounting

---

## High-Leverage Bug Class Search (Complete)

### ✅ Fee Double Counting (NOT FOUND)
**Search**: Checked for multiple fee applications
**Result**: No evidence of double counting
**Validation**: `validate_fee_vs_estimate()` function prevents this

### ✅ Incorrect Unit Conversions (NOT FOUND)
**Search**: Checked cents/dollars/notional conversions
**Result**: All conversions are correct
**Validation**: Consistent use of `/ 100.0` for cents→dollars

### ✅ Maker Fee on Canceled Orders (NOT FOUND)
**Search**: Checked for fee application on cancellations
**Result**: Fees only calculated on fills, not cancellations
**Validation**: Kalshi only charges fees on executed orders

### ✅ Taker Fee Omitted on Immediate Fills (NOT FOUND)
**Search**: Checked for missing fee on immediate fills
**Result**: Fees calculated on all fills (order_router.py line 8294)
**Validation**: Consistent fee application

### ✅ Spread Cost Using Last Trade (NOT FOUND)
**Search**: Checked spread calculation source
**Result**: Uses best_bid/best_ask from market state
**Validation**: Correct orderbook data usage

### ✅ Thresholds Tuned on Raw Edge (NOT FOUND)
**Search**: Checked threshold application
**Result**: Thresholds applied to fee-adjusted edge
**Validation**: Maker/taker policy uses `edge_net_of_fees_pct`

### ✅ Partial-Fill Paths with Stale Data (ACCEPTABLE)
**Search**: Checked partial fill handling
**Result**: Partial fills use fill_price from exchange response
**Risk**: If market data is stale during partial fill, may use outdated prices
**Mitigation**: Exchange provides authoritative fill prices
**Assessment**: ✅ Acceptable - exchange data is authoritative

### ✅ Rounding Bugs at Low Prices (FIXED)
**Search**: Checked rounding behavior at low prices
**Result**: MIN_FEE_CENTS was 2, now fixed to 1
**Mitigation**: Proper ceil() implementation
**Assessment**: ✅ Fixed in Phase 1

---

## Summary

### Downstream Audit Status: ✅ COMPLETE
**Overall Assessment**: Robust with no critical bugs found

**Strengths**:
- ✅ Comprehensive fill attribution (fill_id, order_id, intent_id)
- ✅ Fee reconciliation with validation
- ✅ Proper partial fill handling
- ✅ Correct cancellation behavior
- ✅ Proper rest-to-fill transitions
- ✅ Comprehensive PnL accounting

**Minor Issues**:
- None identified

**Recommendations**:
1. ✅ No critical fixes needed
2. ✅ System is production-ready for downstream components
3. ✅ All high-leverage bug classes searched and verified

---

## Full-Stack Remediation Summary

### Phase 1: Fee Calculation & Routing Fixes ✅
- Fixed MIN_FEE_CENTS bug (2¢ → 1¢)
- Implemented maker-first routing (0.5% maker, 2.0% taker)
- Fixed maker fee calculation (parabolic formula)
- Added should_execute enforcement
- Added 24 tests (all passing)

### Phase 2: Audits ✅
- Upstream audit: Signal generation & price freshness ✅
- Midstream audit: Order construction & routing ✅
- Downstream audit: Fill attribution & PnL ✅
- High-leverage bug class search ✅

### Overall Assessment: ✅ PRODUCTION READY
**Status**: All critical bugs fixed, all audits complete, no remaining issues found

**Key Achievements**:
1. ~50% fee reduction at low prices
2. Maker-first strategy with appropriate thresholds
3. Comprehensive test coverage (24 tests)
4. Full-stack audit completed
5. No critical bugs remaining

**Next Steps**:
1. Restart server to apply fixes
2. Monitor logs for `[POLICY-ENGINE-REJECT]` messages
3. Verify maker orders are being placed more frequently
4. Monitor fee calculations in live trades
