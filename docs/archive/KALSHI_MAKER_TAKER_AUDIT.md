# Kalshi Maker/Taker Policy & Parabolic Fee Audit

**Status**: ✅ COMPLETE  
**Last Updated**: 2026-03-24  
**Scope**: End-to-end integration of parabolic fee formulas and MakerTakerPolicyEngine

---

## 1. Executive Summary

This document summarizes the implementation and audit of the Kalshi maker/taker policy engine and parabolic fee integration across the MERID stack. All legacy tiered fee schedules (7%/5%/3%) have been replaced with the canonical parabolic formulas per Kalshi's fee schedule.

### Key Achievements
- ✅ Parabolic fee functions implemented and tested
- ✅ MakerTakerPolicyEngine with 3 policy modes (NEUTRAL_MM, AGGRESSIVE_CONVICTION, ARB_LEG)
- ✅ OrderIntent extended with policy_mode, expected_role, market context
- ✅ OrderResult extended with actual_role, fee_cents, policy tracking
- ✅ All routing paths (MOCK/PAPER/LIVE) populate policy fields
- ✅ Kelly sizing updated to use parabolic fees
- ✅ Comprehensive test coverage with regression table

---

## 2. Ground Truth Fee Specification

**Canonical Formulas** (from Kalshi fee schedule):

```
Taker fee: fee_cents = ceil(0.07 * C * P * (1 - P))
Maker fee: fee_cents = ceil(0.0175 * C * P * (1 - P))
```

Where:
- `P` = contract price in **dollars** (0.55, not 55 cents)
- `C` = contract count
- Maximum taker fee at P=0.5: **1.75¢/contract**
- Maximum maker fee at P=0.5: **0.4375¢/contract**
- `P ∈ (0.01, 0.99)` valid range

### Regression Test Values

| Price ($) | Contracts | Taker Fee (¢) | Maker Fee (¢) |
|-----------|-----------|---------------|---------------|
| 0.01      | 1         | 1             | 1             |
| 0.05      | 10        | 4             | 1             |
| 0.50      | 1         | 2             | 1             |
| 0.50      | 10        | 18            | 5             |
| 0.50      | 100       | 175           | 44            |
| 0.95      | 10        | 4             | 1             |
| 0.99      | 1         | 1             | 1             |

---

## 3. Implementation Files

### Core Fee Module
```
merid/event_venues/kalshi/parabolic_fees.py
```
- `kalshi_taker_fee_cents_parabolic()` - Taker fee calculation
- `kalshi_maker_fee_cents()` - Maker fee calculation
- `kalshi_fee_cents_parabolic()` - Unified fee function with role parameter
- `estimate_fee_for_sizing()` - Helper for sizing code (works in cents)
- `fee_per_contract_cents()` - Per-contract fee for analysis
- `max_fee_cents()` - Maximum theoretical fee at P=0.5

### Policy Engine
```
merid/event_venues/kalshi/maker_taker_policy.py
```
- `MakerTakerPolicyEngine` - Main policy decision engine
- `PolicyMode` enum - NEUTRAL_MM, AGGRESSIVE_CONVICTION, ARB_LEG
- `LiquidityRole` enum - MAKER, TAKER, UNKNOWN
- `RoleDecision` dataclass - Decision result with all metadata
- `decide_order_role()` - Convenience function

### Order Router Integration
```
merid/event_venues/kalshi/order_router.py
```
- `OrderIntent` extended with:
  - `policy_mode: Optional[str]` - Policy mode for this order
  - `expected_role: Optional[str]` - Expected liquidity role
  - `market_best_bid_cents: Optional[int]` - Market bid
  - `market_best_ask_cents: Optional[int]` - Market ask
  - `fair_value_cents: Optional[int]` - Model fair value

- `OrderResult` extended with:
  - `expected_role: Optional[str]` - Expected role at submission
  - `actual_role: Optional[str]` - Actual role from execution
  - `fee_cents: Optional[int]` - Actual fee charged
  - `policy_mode: Optional[str]` - Policy mode applied

- `_kalshi_fee_cents()` - Updated to use parabolic formula with role
- `simulate_paper_fill()` - Captures actual_role and uses parabolic fees
- `_route_live()` / `_route_sync_non_live()` - Populate all policy fields

### Risk & Sizing
```
merid/event_venues/kalshi/kalshi_risk.py
merid/event_venues/kalshi/position_sizer.py
```
- `kalshi_fee_cents()` - Updated to delegate to parabolic_fees
- `kalshi_fee_rate()` - Returns base rates (0.07/0.0175)
- Kelly sizing uses taker fees for conservative estimates

### Tests
```
tests/event_venues/kalshi/test_parabolic_fees_and_policy.py
```
- 20+ test cases covering all price points and contract counts
- Regression tests against hard-coded expected values
- Policy engine tests for all 3 modes
- Edge case tests (missing data, extreme prices)

---

## 4. Policy Modes

### NEUTRAL_MM (Market Making)
- **Behavior**: Always maker, never cross spread
- `post_only=True`
- Executes only if edge > 0
- **Use case**: Passive liquidity provision

### AGGRESSIVE_CONVICTION (Directional)
- **Behavior**: Takes liquidity when edge >> fees + threshold
- Threshold: Default 2% (configurable)
- Falls back to maker if edge insufficient
- **Use case**: High-conviction directional trades

### ARB_LEG (Arbitrage)
- **Behavior**: Prefers taker for speed, verifies edge covers fees
- Minimum edge: Default 0.5% (configurable)
- Falls back to maker if edge too small
- **Use case**: Arb leg execution where speed matters

---

## 5. Invariants Checklist

| Invariant | Status | Notes |
|-----------|--------|-------|
| Fees always computed in cents using ceil | ✅ | `math.ceil()` used everywhere |
| P always interpreted as dollars | ✅ | Validated in `_validate_price()` |
| Maker fee = 25% of taker fee | ✅ | 0.0175 / 0.07 = 0.25 |
| Max taker fee at P=0.5 is 1.75¢ | ✅ | Verified in tests |
| Max maker fee at P=0.5 is 0.4375¢ | ✅ | Verified in tests |
| Role classification matches execution | ✅ | `post_only` determines actual_role |
| Policy engine is fully wired | ✅ | All route paths populate fields |
| PnL calculations use actual fees | ✅ | Fee captured in OrderResult |

---

## 6. Integration Status

### Upstream (Strategies/Sizing)
- ✅ Kelly sizing uses parabolic fees
- ✅ Position sizer uses taker fees for conservative estimates
- ✅ Risk manager fee calculations updated

### Core (Order Routing)
- ✅ OrderIntent accepts policy_mode and market context
- ✅ OrderResult captures expected_role, actual_role, fee_cents
- ✅ All routing paths (MOCK/PAPER/LIVE) populate fields
- ✅ Paper fill simulation uses parabolic fees

### Downstream (PnL/Analytics)
- ✅ Fill dict includes actual_role and post_only
- ✅ OrderResult includes fee_cents for PnL attribution
- ✅ Policy mode tracked for analytics

---

## 7. Known Limitations

1. **Live role inference**: `actual_role` is inferred from `post_only` flag rather than exchange-reported maker/taker status. Kalshi API does not explicitly report this in fills.

2. **Fee estimation in sizing**: Uses single-contract taker fee scaled linearly. True parabolic fee on sized position may differ slightly due to ceiling effects.

3. **Market data requirements**: Policy engine requires `market_best_bid_cents` and `market_best_ask_cents` for crossing detection. If not provided, defaults to conservative maker behavior.

---

## 8. Migration Notes

### For Strategy Developers
1. Set `policy_mode` on OrderIntent:
   ```python
   intent = OrderIntent(
       ticker="KXBTC-250324",
       side="yes",
       action="buy",
       price_cents=55,
       count=10,
       policy_mode="AGGRESSIVE_CONVICTION",  # or "NEUTRAL_MM", "ARB_LEG"
       expected_role="maker",  # or "taker"
       market_best_bid_cents=54,
       market_best_ask_cents=56,
   )
   ```

2. Check result for actual execution details:
   ```python
   result = await route_order_async(intent)
   print(f"Expected: {result.expected_role}, Actual: {result.actual_role}")
   print(f"Fee: {result.fee_cents}¢, Policy: {result.policy_mode}")
   ```

### For Backtest/Sim Developers
- Replace any hardcoded 7%/5%/3% fee logic with `kalshi_fee_cents_parabolic()`
- Use `estimate_fee_for_sizing()` for sizing code that works in cents

---

## 9. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Fee underestimation in sizing | Low | Uses taker fee (conservative), ceiling ensures fees never under-reported |
| Role misclassification | Low | post_only flag is ground truth for maker intent |
| Missing market data | Low | Defaults to maker behavior (safest) |
| Price in wrong units | Medium | Validated and clamped in `_validate_price()` |

---

## 10. Testing Commands

```bash
# Run parabolic fee and policy tests
python -m pytest tests/event_venues/kalshi/test_parabolic_fees_and_policy.py -v

# Run all Kalshi tests
python -m pytest tests/event_venues/kalshi/ -v

# Verify module imports
python -c "from merid.event_venues.kalshi.parabolic_fees import kalshi_taker_fee_cents_parabolic; print('✅ Parabolic fees module OK')"
python -c "from merid.event_venues.kalshi.maker_taker_policy import MakerTakerPolicyEngine; print('✅ Policy engine module OK')"
```

---

## 11. Files Modified

### New Files
- `merid/event_venues/kalshi/parabolic_fees.py` - Core fee calculations
- `merid/event_venues/kalshi/maker_taker_policy.py` - Policy engine
- `tests/event_venues/kalshi/test_parabolic_fees_and_policy.py` - Test suite

### Modified Files
- `merid/event_venues/kalshi/order_router.py` - Policy fields in OrderIntent/Result
- `merid/event_venues/kalshi/kalshi_risk.py` - Updated fee functions
- `merid/event_venues/kalshi/position_sizer.py` - Parabolic fees in sizing

---

**End of Document**
