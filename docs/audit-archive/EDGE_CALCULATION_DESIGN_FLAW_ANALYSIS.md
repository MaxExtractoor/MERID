# Edge Calculation Design Flaw Analysis

## Executive Summary

**CRITICAL DESIGN FLAW IDENTIFIED**: The system has a fundamental design flaw in how it handles the `should_execute` flag from the maker/taker policy engine. The policy engine correctly rejects trades with negative executable edge, but the order router **never checks** this flag before executing orders.

**Impact**: The system is designed to protect against unprofitable trades, but the protection mechanism is not being enforced in the execution pipeline.

---

## 1. Current System Architecture

### 1.1 Edge Calculation Pipeline

**Location**: `merid/prediction/agent_grid_15m.py` (lines 5723-5833)

**Current Logic**:
```python
# Calculate executable edge for both economics modes
executable_edge_maker_pct = edge_pct - maker_fee_pct
executable_edge_taker_pct = edge_pct - spread_pct - taker_fee_pct

# Regime-based execution routing
if regime == "neutral":
    execution_mode = "taker"
    if executable_edge_taker_pct <= 0:
        logger.warning("[EXECUTABLE-EDGE-REJECT] ... -> NO TRADE (taker requires positive edge)")
        return None  # Signal rejected
```

**Fee Structure**:
- Taker fee: `ceil(0.07 × C × P × (1-P))` where C=contracts, P=price
- Maker fee: 25% of taker fee
- Typical taker fee at 38c: 2 cents (5.13%)
- Typical maker fee at 38c: 0.5 cents (1.28%)

### 1.2 Maker/Taker Policy Engine

**Location**: `merid/event_venues/kalshi/maker_taker_policy.py` (lines 217-270)

**Current Logic**:
```python
elif mode == PolicyMode.AGGRESSIVE_CONVICTION:
    edge_net_of_taker = edge_pct - taker_fee_pct
    edge_net_of_maker = edge_pct - maker_fee_pct
    
    if crosses_spread and edge_net_of_taker >= self.aggressive_threshold_pct:
        return RoleDecision(
            recommended_role=LiquidityRole.TAKER,
            should_execute=True,  # ✅ Correctly set
            ...
        )
    else:
        should_execute = edge_net_of_maker > 0 if self.aggressive_threshold_pct > 0 else True
        return RoleDecision(
            recommended_role=LiquidityRole.MAKER,
            should_execute=should_execute,  # ✅ Correctly set
            ...
        )
```

**Threshold**: `AGGRESSIVE_THRESHOLD_PCT = 0.5%` (line 145)

### 1.3 Maker/Taker Integration

**Location**: `merid/event_venues/kalshi/maker_taker_integration.py` (lines 105-163)

**Current Logic**:
```python
role_decision = decide_order_role(...)

# Enrich intent with policy decision metadata
intent.expected_role = role_decision.recommended_role.value
intent.fee_type = role_decision.recommended_role.value
intent.estimated_fee_cents = role_decision.fee_cents_estimate
intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct  # ✅ Stored
intent.policy_mode = policy_mode.name

# ❌ CRITICAL FLAW: should_execute flag is NEVER checked
# The intent has no should_execute field, and the router never checks it
```

### 1.4 Order Router

**Location**: `merid/event_venues/kalshi/order_router.py`

**Current Logic**:
```python
# ❌ CRITICAL FLAW: No check for should_execute flag
# The router processes orders regardless of policy engine recommendation
# It only checks intent.edge_net_of_fees_pct for logging, not for rejection
```

---

## 2. Industry Best Practices

### 2.1 Binary Options Edge Requirements

**Research Sources**:
- Binary Trading Edge Calculator
- SignalBots Break-Even Calculator
- Academic research on binary options strategies

**Key Findings**:

1. **Break-Even Win Rate Formula**:
   ```
   Break-even win rate = 1 / (1 + payout)
   
   At 80% payout: 1 / 1.80 = 55.56%
   At 85% payout: 1 / 1.85 = 54.05%
   ```

2. **Minimum Profitable Edge**:
   - Industry standard: **8%+ EV per trade** to overcome variance
   - Below 5% EV: Variance often eats the edge
   - Below 2% EV: Mathematically positive but practically unprofitable

3. **Kalshi-Specific Research** (UCD Centre for Economic Research):
   - Kalshi fees: `0.07 × C × P × (1-P)` (parabolic fee curve)
   - Average fee at 50c: 3.54% (slightly higher than 3.5% due to rounding)
   - **Contracts must win MORE often than their price percentage to break even**

### 2.2 Our System vs Industry Standards

| Metric | Industry Standard | Our System | Assessment |
|--------|------------------|------------|------------|
| Minimum edge threshold | 8%+ EV | 0.5% net of fees | ❌ Too low |
| Break-even calculation | `1 / (1 + payout)` | Edge - fees | ✅ Correct |
| Fee structure | Parabolic curve | Parabolic curve | ✅ Correct |
| Maker fee | 25% of taker | 25% of taker | ✅ Correct |
| Execution protection | Should be enforced | Not enforced | ❌ Design flaw |

---

## 3. Design Flaws Identified

### 3.1 CRITICAL: `should_execute` Flag Not Checked

**Flaw**: The maker/taker policy engine correctly sets `should_execute=False` for unprofitable trades, but the order router never checks this flag.

**Evidence**:
```python
# maker_taker_policy.py line 257
should_execute = edge_net_of_maker > 0 if self.aggressive_threshold_pct > 0 else True
return RoleDecision(
    should_execute=should_execute,  # ✅ Set correctly
    ...
)

# maker_taker_integration.py line 117-120
intent.expected_role = role_decision.recommended_role.value
intent.fee_type = role_decision.recommended_role.value
intent.estimated_fee_cents = role_decision.fee_cents_estimate
intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct
# ❌ should_execute flag is NOT copied to intent

# order_router.py
# ❌ No check for should_execute anywhere in the execution pipeline
```

**Impact**: 
- Trades with negative executable edge can still execute
- The safety mechanism exists but is not enforced
- System may execute unprofitable trades despite having protection logic

### 3.2 Threshold Too Low

**Flaw**: The `AGGRESSIVE_THRESHOLD_PCT = 0.5%` is far below industry standards (8%+).

**Evidence**:
```python
# maker_taker_policy.py line 145
AGGRESSIVE_THRESHOLD_PCT = 0.5  # 0.5% minimum edge

# Industry research shows:
# - 8%+ EV needed to overcome variance
# - Below 5% EV: variance eats the edge
# - Below 2% EV: practically unprofitable
```

**Impact**:
- System may execute trades with very low edge
- High likelihood of losing money over time due to variance
- Not aligned with industry best practices

### 3.3 Double Edge Calculation

**Flaw**: Edge is calculated twice - once in `agent_grid_15m.py` and once in `maker_taker_policy.py`.

**Evidence**:
```python
# agent_grid_15m.py lines 5825-5828
executable_edge_maker_pct = edge_pct - maker_fee_pct
executable_edge_taker_pct = edge_pct - spread_pct - taker_fee_pct

# maker_taker_policy.py lines 219-220
edge_net_of_taker = edge_pct - taker_fee_pct
edge_net_of_maker = edge_pct - maker_fee_pct
```

**Impact**:
- Potential for inconsistency between calculations
- Unnecessary computational overhead
- Maintenance burden (two places to update)

---

## 4. Proposed Fixes

### 4.1 Fix 1: Enforce `should_execute` Flag (CRITICAL)

**Priority**: CRITICAL - This is the main design flaw

**Implementation**:

1. **Add `should_execute` field to OrderIntent**:
```python
# order_router.py line 2016
edge_net_of_fees_pct: Optional[float] = None
should_execute: Optional[bool] = None  # ✅ ADD THIS FIELD
policy_mode: Optional[str] = None
```

2. **Copy `should_execute` from policy decision**:
```python
# maker_taker_integration.py line 120
intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct
intent.should_execute = role_decision.should_execute  # ✅ ADD THIS LINE
intent.policy_mode = policy_mode.name
```

3. **Check `should_execute` in order router**:
```python
# order_router.py (add before order submission)
if intent.should_execute is False:
    logger.warning(
        f"[ORDER-ROUTER] Rejected by policy engine: ticker={intent.ticker} "
        f"edge_net_fees={intent.edge_net_of_fees_pct:.3f}% "
        f"reason={intent.policy_mode}"
    )
    return None  # Reject the order
```

### 4.2 Fix 2: Increase Threshold to Industry Standard

**Priority**: HIGH - Align with industry best practices

**Implementation**:

```python
# maker_taker_policy.py line 145
# OLD: AGGRESSIVE_THRESHOLD_PCT = 0.5
# NEW: AGGRESSIVE_THRESHOLD_PCT = 2.0  # 2% minimum edge (conservative)
# OR: AGGRESSIVE_THRESHOLD_PCT = 5.0  # 5% minimum edge (industry standard)
```

**Rationale**:
- 2%: Conservative threshold, allows more trades but still protects against very low edge
- 5%: Industry standard, aligns with research on profitable binary options trading
- 8%: Aggressive threshold, only trades with high-confidence signals

**Recommendation**: Start with 2% and monitor performance, increase to 5% if needed.

### 4.3 Fix 3: Consolidate Edge Calculation

**Priority**: MEDIUM - Reduce complexity and inconsistency

**Implementation**:

1. **Move edge calculation to a single utility function**:
```python
# merid/utils/edge_calculator.py (new file)
def calculate_executable_edge(
    edge_pct: float,
    price_cents: int,
    contracts: int,
    spread_cents: float = 0.0,
) -> ExecutableEdge:
    """Calculate executable edge after fees."""
    # Single source of truth for edge calculation
    ...
```

2. **Update both modules to use the utility function**:
```python
# agent_grid_15m.py
from merid.utils.edge_calculator import calculate_executable_edge
executable_edge = calculate_executable_edge(...)

# maker_taker_policy.py
from merid.utils.edge_calculator import calculate_executable_edge
executable_edge = calculate_executable_edge(...)
```

---

## 5. Immediate Action Required

### 5.1 Critical Fix (Implement Now)

**Fix 1**: Enforce `should_execute` flag in order router

**Files to modify**:
1. `merid/event_venues/kalshi/order_router.py` - Add field and check
2. `merid/event_venues/kalshi/maker_taker_integration.py` - Copy flag from policy decision

**Estimated time**: 30 minutes

**Risk**: LOW - This is adding a safety check that should have been there

### 5.2 High Priority Fix (Implement This Week)

**Fix 2**: Increase threshold to 2%

**Files to modify**:
1. `merid/event_venues/kalshi/maker_taker_policy.py` - Change `AGGRESSIVE_THRESHOLD_PCT`

**Estimated time**: 5 minutes

**Risk**: LOW - Will reduce trade frequency but improve profitability

### 5.3 Medium Priority Fix (Implement Next Sprint)

**Fix 3**: Consolidate edge calculation

**Files to modify**:
1. Create `merid/utils/edge_calculator.py`
2. Update `merid/prediction/agent_grid_15m.py`
3. Update `merid/event_venues/kalshi/maker_taker_policy.py`

**Estimated time**: 2 hours

**Risk**: MEDIUM - Requires testing to ensure consistency

---

## 6. Testing Recommendations

### 6.1 Unit Tests

1. **Test `should_execute` enforcement**:
```python
def test_should_execute_false_rejects_order():
    intent = OrderIntent(...)
    intent.should_execute = False
    result = order_router.execute_order(intent)
    assert result is None  # Order rejected
```

2. **Test threshold enforcement**:
```python
def test_low_edge_rejected():
    edge_pct = 0.3  # Below 2% threshold
    decision = policy_engine.decide(edge_pct=edge_pct, ...)
    assert decision.should_execute is False
```

### 6.2 Integration Tests

1. **End-to-end test with low edge**:
```python
def test_low_edge_signal_rejected():
    signal = Signal(edge_pct=0.3, ...)
    result = loop_15m.process_signal(signal)
    assert result.executed is False
```

2. **End-to-end test with high edge**:
```python
def test_high_edge_signal_executed():
    signal = Signal(edge_pct=5.0, ...)
    result = loop_15m.process_signal(signal)
    assert result.executed is True
```

---

## 7. Conclusion

**Summary**: The system has a critical design flaw where the `should_execute` flag from the maker/taker policy engine is not checked in the order router. This means the safety mechanism designed to prevent unprofitable trades is not being enforced.

**Impact**: 
- System may execute trades with negative executable edge
- Not aligned with industry best practices for profitable binary options trading
- High likelihood of losing money over time

**Recommendation**: 
1. **IMMEDIATE**: Implement Fix 1 (enforce `should_execute` flag)
2. **THIS WEEK**: Implement Fix 2 (increase threshold to 2%)
3. **NEXT SPRINT**: Implement Fix 3 (consolidate edge calculation)

**Expected Outcome**: After implementing these fixes, the system will:
- ✅ Enforce executable edge protection
- ✅ Align with industry best practices
- ✅ Only execute trades with sufficient edge to be profitable
- ✅ Reduce likelihood of losses due to low-edge trades

---

## 8. References

1. Binary Trading Edge Calculator: https://www.binarytrading.com/traders-edge-calculator/
2. SignalBots Break-Even Calculator: https://signalbots.ai/tools/binary-options/break-even-win-rate
3. Kalshi Pricing Math: https://kalshiview.com/blog/math-behind-kalshi-pricing-implied-probability/
4. UCD Centre for Economic Research - Kalshi Fee Analysis: https://www.ucd.ie/economics/t4media/WP2025_19.pdf
5. Binary Options Expected Value Research: https://doi.org/10.3390/risks10110212
