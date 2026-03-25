# Kalshi Maker/Taker Implementation Audit

## Overview

This document tracks the implementation of parabolic maker/taker fee functions and the MakerTakerPolicyEngine for Kalshi order routing.

**Status**: ✅ IMPLEMENTED
**Date**: 2026-03-25
**Version**: 1.0

---

## Parabolic Fee Functions

### Specification

Kalshi uses a parabolic fee schedule that is proportional to the expected value of the position:

- **Taker Fee**: `ceil(0.07 × contracts × P × (1-P))` dollars, where P is price in decimal form (0-1)
- **Maker Fee**: `ceil(0.0175 × contracts × P × (1-P))` dollars

Key properties:
- Fees are maximal at P=0.5 (50¢ price point)
- Fees decrease toward extreme prices (near 1¢ or 99¢)
- Maker fees are 1/4 of taker fees (0.0175 vs 0.07 rate)
- Fees scale linearly with contract count

### Implementation

**Location**: `merid/event_venues/kalshi/maker_taker_policy.py`

Functions:
- `kalshi_taker_fee_cents_parabolic(price_cents, contracts)` - Calculate taker fees
- `kalshi_maker_fee_cents(price_cents, contracts)` - Calculate maker fees

**Examples**:
```python
# At 50¢ with 10 contracts (maximal fee point):
kalshi_taker_fee_cents_parabolic(50, 10)  # → 18 cents
kalshi_maker_fee_cents(50, 10)            # → 5 cents

# At 90¢ with 10 contracts (extreme price, lower fees):
kalshi_taker_fee_cents_parabolic(90, 10)  # → 7 cents
kalshi_maker_fee_cents(90, 10)            # → 2 cents
```

### Integration Points

Parabolic fees integrated into:

1. **kalshi_risk.py**:
   - `kalshi_taker_fee_cents_parabolic()` - Primary taker fee function
   - `kalshi_maker_fee_cents()` - Primary maker fee function
   - `kalshi_fee_cents()` - DEPRECATED legacy function (kept for compatibility)
   - `kelly_size_kalshi()` - Updated with `role` parameter
   - `dynamic_position_sizes()` - Updated with `role` parameter
   - `multi_market_kelly_sizes()` - Updated with `role` parameter

2. **position_sizer.py**:
   - `kalshi_fee_cents()` - Updated to use parabolic fees with role parameter
   - Delegates to maker_taker_policy functions

3. **order_router.py**:
   - `simulate_paper_fill()` - Uses parabolic fees based on role
   - `_route_live()` - Calculates fees using parabolic formula
   - `_kalshi_fee_cents()` - DEPRECATED (marked for legacy compatibility)

---

## MakerTakerPolicyEngine

### Policy Modes

The engine implements three distinct policy modes:

#### 1. NEUTRAL_MM (Market Maker Mode)
- **Behavior**: Always post-only (maker)
- **Use Case**: Pure market-making strategies that provide liquidity
- **Fees**: Pays maker fees (1/4 of taker fees)
- **Execution**: Never crosses the spread

```python
decision = engine.decide(
    mode=PolicyMode.NEUTRAL_MM,
    edge_pct=5.0,
    price_cents=55,
    contracts=10,
)
# → decision.role = "maker", post_only = True
```

#### 2. AGGRESSIVE_CONVICTION (Conviction-Based)
- **Behavior**: Takes when edge significantly exceeds taker fees, otherwise makes
- **Use Case**: Directional trading with strong conviction
- **Logic**:
  - Takes if: `edge_pct / taker_fee_pct >= aggressive_edge_multiplier` (default 2.0x)
  - Makes otherwise
- **Minimum Edge**: 1.0% to consider taking (configurable via `min_take_edge_pct`)

```python
# High edge → Take
decision = engine.decide(
    mode=PolicyMode.AGGRESSIVE_CONVICTION,
    edge_pct=5.0,      # Edge 5% >> taker fee ~0.3%
    price_cents=55,
    contracts=10,
)
# → decision.role = "taker"

# Low edge → Make
decision = engine.decide(
    mode=PolicyMode.AGGRESSIVE_CONVICTION,
    edge_pct=0.8,      # Below min threshold
    price_cents=55,
    contracts=10,
)
# → decision.role = "maker"
```

#### 3. ARB_LEG (Arbitrage Leg Mode)
- **Behavior**: Always taker (immediate execution)
- **Use Case**: Arbitrage legs where speed is critical
- **Fees**: Pays taker fees (higher cost for immediacy)
- **Execution**: Crosses the spread immediately

```python
decision = engine.decide(
    mode=PolicyMode.ARB_LEG,
    edge_pct=2.0,
    price_cents=55,
    contracts=10,
)
# → decision.role = "taker", post_only = False
```

### PolicyDecision Output

Each decision returns a comprehensive `PolicyDecision` object:

```python
@dataclass
class PolicyDecision:
    role: str                # "maker" or "taker"
    post_only: bool          # Whether to use post-only flag
    reason: str              # Human-readable reasoning
    taker_fee_cents: int     # Expected taker fee
    maker_fee_cents: int     # Expected maker fee
    edge_pct: float          # Edge used in decision
    fee_edge_ratio: float    # Ratio of edge to applicable fee
```

### Configuration

```python
engine = MakerTakerPolicyEngine(
    aggressive_edge_multiplier=2.0,  # Take when edge > fee × this
    min_take_edge_pct=1.0,           # Min edge to consider taking
)
```

---

## OrderIntent and OrderResult Updates

### OrderIntent (Enhanced)

New fields added to track policy and market data:

```python
@dataclass
class OrderIntent:
    # ... existing fields ...
    post_only: bool = False
    policy_mode: Optional[str] = None        # "neutral_mm", "aggressive_conviction", "arb_leg"
    expected_role: Optional[str] = None      # "maker" or "taker"
    bid_cents: Optional[int] = None          # Best bid for spread-aware routing
    ask_cents: Optional[int] = None          # Best ask for spread-aware routing
    spread_bps: Optional[float] = None       # Spread in basis points
```

### OrderResult (Enhanced)

New fields added to track execution role and fees:

```python
@dataclass
class OrderResult:
    # ... existing fields ...
    expected_role: Optional[str] = None      # Expected role from policy
    actual_role: Optional[str] = None        # Actual execution role
    fee_cents: Optional[int] = None          # Actual fee charged
```

---

## Order Routing Integration

### Paper/Mock Mode

`simulate_paper_fill()` now:
1. Determines role based on `policy_mode` if specified
2. Uses policy engine to make maker/taker decision
3. Calculates fees using parabolic formula based on actual role
4. Returns `actual_role` and `fee_cents` in fill dict

### Live Mode

`_route_live()` now:
1. Determines actual role from Kalshi API response or `post_only` flag
2. Calculates fees using parabolic formula based on actual role
3. Populates `expected_role`, `actual_role`, and `fee_cents` in OrderResult
4. Includes role and fee info in fill dict

### Logging Enhancements

Order routing logs now include role and fee information:
```
[order-router] MOCK fill KXBTCD-25JUN-T100000 buy 10x @ 55c (role=taker, fee=18¢)
[order-router] PAPER fill KXBTCD-25JUN-T100000 buy 10x @ 55c (role=maker, fee=5¢)
```

---

## Risk and Position Sizing Updates

### KalshiRiskManager

**Updated Functions**:
- `kelly_size_kalshi()` - Added `role` parameter (default "taker")
- `dynamic_position_sizes()` - Added `role` parameter (default "taker")
- `multi_market_kelly_sizes()` - Added `role` parameter (default "taker")

**Usage**:
```python
risk = get_kalshi_risk()

# Size for taker execution (default, more conservative)
size_taker = risk.kelly_size_kalshi(
    edge=0.08,
    price_cents=55,
    bankroll_cents=50000,
    role="taker",
)

# Size for maker execution (lower fees = larger size)
size_maker = risk.kelly_size_kalshi(
    edge=0.08,
    price_cents=55,
    bankroll_cents=50000,
    role="maker",
)
```

### PositionSizer

**Updated Function**:
- `kalshi_fee_cents()` - Now accepts `role` parameter and delegates to parabolic fee functions

The `PositionSizer.compute()` method uses the updated `kalshi_fee_cents()` with role-aware fee calculation.

---

## Testing

### Test Coverage

**Location**: `tests/event_venues/kalshi/test_maker_taker_policy.py`

Test classes:
1. `TestParabolicFees` - Comprehensive tests for fee formulas
2. `TestPolicyEngine` - Decision logic for all policy modes
3. `TestPolicySingleton` - Singleton pattern verification
4. `TestPolicyIntegration` - Integration tests combining fees and policies

**Key Test Scenarios**:
- Fee calculations at different price points (50¢, 55¢, 90¢, extremes)
- Fee scaling with contract count
- Maker fees are 1/4 of taker fees
- Policy mode decision logic (NEUTRAL_MM, AGGRESSIVE_CONVICTION, ARB_LEG)
- Edge-to-fee ratio thresholds
- Custom multiplier configuration
- Integration across different sizes and prices

**Run Tests**:
```bash
pytest tests/event_venues/kalshi/test_maker_taker_policy.py -v
```

---

## Migration Notes

### Backward Compatibility

Legacy tiered fee functions are **DEPRECATED** but retained for compatibility:

**Deprecated Functions**:
- `kalshi_fee_cents()` in kalshi_risk.py - Use `kalshi_taker_fee_cents_parabolic()` or `kalshi_maker_fee_cents()`
- `_kalshi_fee_cents()` in order_router.py - Legacy simulation helper
- `kalshi_fee_cents()` in position_sizer.py - Now delegates to parabolic functions

**Migration Path**:
1. Update code to use parabolic fee functions directly
2. Specify `role="maker"` or `role="taker"` explicitly where needed
3. Legacy functions will continue to work but may be less accurate

### Breaking Changes

**None** - All changes are backward compatible with optional parameters.

Existing code continues to work:
- Default `role="taker"` used when not specified (conservative)
- Policy mode is optional in OrderIntent
- Fee calculations gracefully fall back to defaults

---

## Defensive Checks

### Fee Calculation Guards

All fee functions include defensive checks:
- Return 0 for zero or negative contracts
- Return 0 for invalid prices (≤0 or ≥100)
- Handle None/missing parameters gracefully
- Use ceiling function to ensure integer cents

### Policy Engine Guards

Policy engine includes:
- Validation of policy mode enum
- Fallback to maker on unknown modes
- Safe division (check for zero denominators)
- Bounds checking on edge percentages

### Logging

Enhanced logging throughout:
- Policy decisions include reason strings
- Fee calculations log warnings on edge cases
- Order routing logs actual vs expected role mismatches

---

## Upstream Integration

### Strategies

All strategy modules using fees should:
1. Import from `merid.event_venues.kalshi.maker_taker_policy`
2. Specify expected role when creating OrderIntent
3. Use `policy_mode` to delegate maker/taker decision to engine

### Backtest Modules

Backtest modules should:
1. Use parabolic fee functions for accurate historical simulation
2. Track maker vs taker fills separately
3. Compare fees paid vs expected based on role

---

## Downstream Integration

### Fills and PnL

Fill processing should:
1. Read `actual_role` from OrderResult
2. Verify fees match expected based on role
3. Track maker/taker fill ratios for analytics

### Analytics

Analytics modules should track:
- Maker vs taker fill percentage
- Average fees paid for maker vs taker
- Fee savings from maker executions
- Policy mode effectiveness (edge-to-fee ratios)

---

## Performance Considerations

### Computational Cost

Parabolic fee calculation is lightweight:
- Simple arithmetic (multiply, ceil)
- No loops or complex logic
- Comparable to legacy tiered calculation

### Caching

Policy engine can be singleton (already implemented):
```python
engine = get_maker_taker_policy_engine()  # Reuses same instance
```

---

## Future Enhancements

### Potential Improvements

1. **Spread-Aware Routing**: Use `bid_cents`, `ask_cents`, `spread_bps` fields for smarter decisions
2. **Dynamic Multipliers**: Adjust `aggressive_edge_multiplier` based on market conditions
3. **Fill Rate Feedback**: Adjust policy based on historical maker fill rates
4. **Per-Asset Policies**: Different policies for different asset classes
5. **Latency-Aware**: Factor in expected latency for maker orders

### Monitoring Metrics

Track these metrics for ongoing optimization:
- Maker fill rate (% of maker orders that fill)
- Effective fee rate (actual fees / notional)
- Policy adherence (expected vs actual role match rate)
- Fee savings from maker orders vs taker

---

## References

### Code Locations

- **Policy Engine**: `merid/event_venues/kalshi/maker_taker_policy.py`
- **Order Router**: `merid/event_venues/kalshi/order_router.py`
- **Risk Manager**: `merid/event_venues/kalshi/kalshi_risk.py`
- **Position Sizer**: `merid/event_venues/kalshi/position_sizer.py`
- **Tests**: `tests/event_venues/kalshi/test_maker_taker_policy.py`

### Related Documentation

- Kalshi API Documentation: [api.elections.kalshi.com/docs](https://api.elections.kalshi.com/docs)
- Kelly Criterion: [Wikipedia](https://en.wikipedia.org/wiki/Kelly_criterion)
- Maker/Taker Fee Models: Standard exchange fee terminology

---

## Change Log

### v1.0 (2026-03-25)
- ✅ Implemented parabolic fee functions (taker and maker)
- ✅ Created MakerTakerPolicyEngine with 3 policy modes
- ✅ Updated OrderIntent and OrderResult data structures
- ✅ Integrated policy engine into order routing (sync and async)
- ✅ Updated kalshi_risk.py with parabolic fees and role parameter
- ✅ Updated position_sizer.py with parabolic fees
- ✅ Added comprehensive test suite
- ✅ Added defensive checks and logging
- ✅ Created audit documentation

---

## Approval and Sign-off

| Role | Name | Date | Status |
|------|------|------|--------|
| Implementation | Claude Agent | 2026-03-25 | ✅ Complete |
| Code Review | [Pending] | - | ⏳ Pending |
| Testing | Automated Tests | 2026-03-25 | ✅ Pass |
| Documentation | This Audit | 2026-03-25 | ✅ Complete |

---

**End of Audit Document**
