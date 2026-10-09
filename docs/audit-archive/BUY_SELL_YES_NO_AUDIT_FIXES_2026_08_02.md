# BUY/SELL YES/NO Comprehensive Audit Fixes

**Date**: 2026-08-02  
**Scope**: Deep audit across buy yes, buy no, sell yes, sell no functionality  
**Comparison**: Web research on prediction market best practices

## Executive Summary

This audit identified **5 critical issues** and **12 gaps** in the buy/sell yes/no implementation compared to industry best practices. The system has good foundational architecture (binary_price_space.py) but inconsistent enforcement across components.

## Critical Issues Found

### 1. Side Inversion Bugs in Position Cache
**Location**: `merid/event_venues/kalshi/position_cache.py:1000-1039`  
**Severity**: CRITICAL  
**Impact**: Creates phantom negative positions, breaks position accounting

**Issue**: Exit fills without existing positions are rejected to prevent side inversion, but this is reactive rather than preventive. The root cause is desynchronization between intent tracking and position state.

**Current Fix**:
```python
# Exit fill without existing position - rejected to prevent phantom positions
if is_exit_fill:
    logger.critical("[POSITION-CACHE-EXIT-FILL-ERROR] ...")
    return  # Reject fill
```

**Proposed Solution**:
- Add intent-to-position reconciliation before order execution
- Implement position state verification in order_router.py before routing exit orders
- Add circuit breaker that halts trading if desynchronization detected

### 2. Edge Calculation Probability Inversion
**Location**: `merid/event_venues/kalshi/order_router.py:3595-3621`  
**Severity**: HIGH  
**Impact**: Incorrect edge calculations cause valid trades to be rejected or bad trades accepted

**Issue**: BUY_NO orders require probability inversion (using NO prob as canonical YES prob) but the implementation is fragile and has multiple fallback paths that can fail.

**Current Fix**:
```python
if order_side_lower in ("no", "buy_no"):
    if intent.p_hat_no_cents is not None:
        p_hat_cents = intent.p_hat_no_cents
    elif intent.p_hat_yes_cents is not None:
        p_hat_cents = 100.0 - intent.p_hat_yes_cents
    else:
        p_hat_cents = None  # FAILS EDGE CALCULATION
```

**Proposed Solution**:
- Make p_hat_no_cents mandatory for NO-side orders (fail closed if missing)
- Add validation in agent_grid_15m.py to ensure both probabilities are provided
- Create unified probability model that always provides both YES and NO probabilities

### 3. Price Space Validation Inconsistencies
**Location**: `merid/event_venues/kalshi/order_router.py:4207-4221`  
**Severity**: HIGH  
**Impact**: NO-side orders validated against YES-space prices causing incorrect rejections

**Issue**: NO-side price validation requires space conversion but not all validation paths implement this correctly.

**Current Fix**:
```python
if outcome_side == "no":
    validation_ask_cents = 100 - best_bid_cents  # NO ask = 100 - YES bid
    validation_bid_cents = 100 - best_ask_cents  # NO bid = 100 - YES ask
```

**Proposed Solution**:
- Create canonical price space conversion layer in binary_price_space.py
- All price validation must go through this layer
- Add unit tests for all four order types (BUY_YES, BUY_NO, SELL_YES, SELL_NO)

### 4. Entry/Exit Invariant Violations
**Location**: `merid/loop_15m.py:5728-5799`  
**Severity**: MEDIUM  
**Impact**: Can create invalid position states

**Issue**: SELL actions on entry orders violate position-delta invariants but validation may miss edge cases.

**Current Fix**:
```python
if action_raw == "SELL":
    if not is_exit_order:
        # Reject SELL on entry
        return False
```

**Proposed Solution**:
- Move entry/exit validation to order_router.py (before execution)
- Add position state verification for all orders (not just exits)
- Implement invariant checking in fills_ledger.py for all fills

### 5. Duality Invariant Enforcement Gaps
**Location**: `merid/event_venues/kalshi/binary_price_space.py`  
**Severity**: MEDIUM  
**Impact**: Arbitrage opportunities and pricing inconsistencies

**Issue**: Duality invariant (YES + NO = 100) is defined but not consistently enforced across all trading paths.

**Current State**:
```python
def validate_duality(yes_price_cents: int, no_price_cents: int, tolerance_cents: int = 1) -> bool:
    return abs((yes_price_cents + no_price_cents) - 100) <= tolerance_cents
```

**Proposed Solution**:
- Add duality validation to all market state updates
- Add duality validation to order execution path
- Create duality violation alerts for arbitrage detection

## Gaps Compared to Best Practices

### 1. Missing Unified Side Mapping
**Best Practice**: Single canonical function for all side mapping (your system has this but inconsistent usage)

**Gap**: Some code paths still use lowercase "yes"/"no" instead of Kalshi format "BUY_YES"/"BUY_NO"

**Solution**: Enforce Kalshi format everywhere, add validation layer

### 2. Missing Probability Model Unification
**Best Practice**: Probability models should provide both YES and NO probabilities atomically

**Gap**: System sometimes has only p_hat_yes_cents, requiring fragile fallbacks

**Solution**: Make both probabilities mandatory in all trading paths

### 3. Missing Side-Aware Order Book Validation
**Best Practice**: Each side has independent order books requiring separate validation

**Gap**: Some validation paths still use YES-space for NO-side orders

**Solution**: Create side-aware validation layer that always uses correct price space

### 4. Missing Entry/Exit State Machine
**Best Practice**: Clear state machine for position lifecycle (entry → managed → exit)

**Gap**: Entry/exit logic scattered across multiple files

**Solution**: Create unified position state machine

### 5. Missing Invariant Monitoring
**Best Practice**: Continuous monitoring of all trading invariants

**Gap**: Invariants checked only at specific points, not continuously

**Solution**: Add invariant monitoring service that checks all invariants continuously

## Implementation Priority

### P0 (Critical - Fix Immediately)
1. Side inversion bug prevention in position_cache.py
2. Edge calculation probability inversion robustness
3. Price space validation consistency

### P1 (High - Fix This Week)
4. Entry/exit invariant enforcement
5. Duality invariant monitoring
6. Unified side mapping enforcement

### P2 (Medium - Fix This Month)
7. Probability model unification
8. Side-aware order book validation layer
9. Position state machine implementation

### P3 (Low - Technical Debt)
10. Invariant monitoring service
11. Unit test coverage for all order types
12. Documentation updates

## Recommended Architecture Changes

### 1. Create Canonical Trading Layer
```
binary_price_space.py (existing)
    ↓
side_aware_trading_layer.py (NEW)
    ↓
order_router.py (existing)
    ↓
trading.py (existing)
```

### 2. Unified Probability Model
```python
@dataclass
class BinaryProbability:
    yes_cents: float  # 0-100
    no_cents: float   # 0-100
    
    def __post_init__(self):
        assert 0 <= self.yes_cents <= 100
        assert 0 <= self.no_cents <= 100
        assert abs((self.yes_cents + self.no_cents) - 100) <= 1.0  # Duality invariant
```

### 3. Position State Machine
```python
class PositionState(Enum):
    NO_POSITION = "no_position"
    ENTERING = "entering"  # Order placed, not filled
    OPEN = "open"  # Position established
    EXITING = "exiting"  # Exit order placed
    CLOSED = "closed"  # Position fully exited
```

## Testing Recommendations

1. Add comprehensive unit tests for all four order types
2. Add integration tests for side inversion scenarios
3. Add property-based tests for duality invariant
4. Add chaos tests for desynchronization scenarios
5. Add performance tests for high-frequency trading paths

## Monitoring Recommendations

1. Add metrics for side inversion attempts
2. Add metrics for duality violations
3. Add metrics for entry/exit invariant violations
4. Add alerts for probability model failures
5. Add alerts for price space validation failures

## Conclusion

The MERID system has a solid foundation with binary_price_space.py providing the correct theoretical framework. However, implementation consistency across components is the main issue. The proposed fixes focus on:

1. **Enforcing consistency** across all trading paths
2. **Making invariants explicit** and continuously validated
3. **Preventing rather than reacting** to invalid states
4. **Following industry best practices** from prediction market research

Implementing these fixes will significantly improve system reliability and prevent the side inversion and pricing inconsistencies that currently exist.
