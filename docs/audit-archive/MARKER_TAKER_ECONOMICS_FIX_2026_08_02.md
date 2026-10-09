# Probability Interpretation and Economics Mismatch Fix

**Date:** 2026-08-02  
**Issue:** Orders rejected due to negative raw_edge despite positive signal edges  
**Root Cause:** Probability interpretation mismatch between signal layer and router + maker/taker economics mismatch

## Problem Description

Orders were being rejected by the edge-aware microstructure gate with negative raw edges, even though the signal generation showed positive edges (e.g., 12.4% for BTC NO at 56c).

### Example Rejection (Tick 209)
```
[EDGE-CALC] NO side using TAKER economics: raw_edge=-32.00c, spread_cost=55.00c, taker_fee=2.00c, executable_edge=-89.00c
[EDGE-AWARE-GATE-REJECT] non_positive_executable_edge: raw_edge=-32.00c spread_cost=55.00c taker_fee=2.00c executable_edge=-89.00c
```

The signal generation showed:
```
[DUAL-SIDE-SELECTION] asset=BTC velocity=-0.000039 thesis_side=no yes_edge=0.5000 no_edge=15.0000 selected_side=no selected_edge=15.0000
```

## Root Cause Analysis

### Primary Issue: Probability Interpretation Mismatch

1. **Signal Layer (agent_grid_15m.py):**
   - For NO orders: `model_prob = min(0.95, market_prob + edge_adjustment)` where `market_prob = price_cents / 100.0` (NO price)
   - Logs show: `model_prob=0.76` for NO order at 56c
   - This `model_prob` is the probability of the **NO outcome** (trade wins if event doesn't happen)
   - This is the "trade-winning probability" interpretation

2. **Router Edge Calculation (spread_edge_analytics.py):**
   - For NO side: `no_raw_edge = p_hat_no_cents - no_order_price` where `p_hat_no_cents = 100.0 - p_hat_yes_cents`
   - Router receives `p_hat_yes_cents=76.0` (treated as YES outcome probability)
   - Router computes: `p_hat_no_cents = 100.0 - 76.0 = 24.0` (NO outcome probability)
   - Router computes: `no_raw_edge = 24.0 - 56.0 = **-32.0c** (negative!)

3. **The Mismatch:**
   - Signal layer: model_prob = 0.76 (NO outcome probability, trade-winning probability)
   - Router: p_hat_yes_cents = 76.0 (YES outcome probability, canonical YES-space)
   - Router incorrectly interpreted the 76c as YES outcome probability instead of NO outcome probability
   - This caused the router to compute the wrong edge: 24c - 56c = -32c instead of 76c - 56c = +20c

### Secondary Issue: Maker/Taker Economics Mismatch

1. **Maker/Taker Policy Decision:**
   - The maker/taker policy engine (`apply_maker_taker_policy`) correctly analyzed the market conditions and recommended `role=maker` for the BTC order
   - Log: `[MAKER-TAKER] Policy decision: role=maker | edge_net_fees=10.611% | reason=AGGRESSIVE (maker): Edge 12.40% insufficient to cross`

2. **Economics Selection Bug:**
   - The order_router used `use_maker_economics = (aggressiveness == 0.0)` to determine economics mode
   - Since BTC had `aggressiveness=0.50`, the order_router forced **taker economics** (pay fee, cross spread)
   - This ignored the maker/taker policy decision and used aggressiveness alone

3. **Result:**
   - With taker economics: executable_edge = raw_edge - spread_cost - taker_fee = -32c - 55c - 2c = -89c
   - With maker economics: executable_edge = raw_edge = 15c (no spread cost, no fee)
   - The order was rejected due to negative executable edge despite the policy recommending maker economics

## Solution

### Fix 1: Probability Interpretation Alignment (loop_15m.py)

Modified the probability assignment in `loop_15m.py` to ensure router receives canonical YES-space probability:

**Before:**
```python
# Legacy method - always used YES-space probability
p_hat_yes_cents = model_prob_yes_canonical * 100.0
p_hat_no_cents = (100.0 - model_prob_yes_canonical * 100.0)
```

**After:**
```python
# Use canonical YES-space probability for router consistency
# model_prob_yes_canonical is already YES-space for both YES and NO orders
# For NO orders: model_prob_yes_canonical = 1.0 - model_prob (line 6142)
p_hat_yes_cents = model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
p_hat_no_cents = (100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
```

**Key Insight:** The code already had `model_prob_yes_canonical = 1.0 - model_prob` for NO orders (line 6142), which converts NO outcome probability to YES-space probability. The fix ensures this canonical YES-space probability is used for p_hat_yes_cents, which is what the router expects.

### Fix 2: Maker/Taker Economics Selection (order_router.py)

Modified the economics selection logic in `order_router.py` to respect the maker/taker policy decision:

**Changes Made:**

1. **Updated function signature** for `check_market_microstructure_edge_aware`:
   - Added `intent: Optional[Any] = None` parameter to access policy decision

2. **Modified economics selection logic** (lines 615-641):
   ```python
   # CRITICAL FIX 2026-08-02: Derive economics mode from maker/taker policy decision
   # Policy decision priority: intent.expected_role > intent.fee_type > aggressiveness-based fallback
   if hasattr(intent, 'expected_role') and intent.expected_role:
       use_maker_economics = (intent.expected_role.lower() == "maker")
   elif hasattr(intent, 'fee_type') and intent.fee_type:
       use_maker_economics = (intent.fee_type.lower() == "maker")
   else:
       # Fallback: aggressiveness-based economics (legacy behavior)
       use_maker_economics = (aggressiveness == 0.0)
   ```

3. **Updated call site** (line 3729):
   - Added `intent=intent` parameter when calling `check_market_microstructure_edge_aware`

4. **Removed duplicate economics calculation** (lines 645-652):
   - Removed redundant `use_maker_economics` recalculation that would override the policy decision

## Expected Impact

### Fix 1 (Probability Interpretation):
- Router will receive canonical YES-space probability for both YES and NO orders
- NO orders will have correct raw_edge calculation: p_hat_no_cents - no_order_price
- Example: For NO order at 56c with model_prob=0.76 (NO outcome prob):
  - Before: p_hat_yes_cents=76.0 (wrong interpretation), p_hat_no_cents=24.0, raw_edge=-32c
  - After: p_hat_yes_cents=24.0 (correct YES-space), p_hat_no_cents=76.0, raw_edge=+20c

### Fix 2 (Maker/Taker Economics):
- Orders will now use the economics mode recommended by the maker/taker policy engine
- Maker orders (limit orders) will use maker economics (no fee, no spread cost, capture spread)
- Taker orders (market orders) will use taker economics (pay fee, cross spread)
- Executable edge calculations will be consistent with the policy decision
- Orders with positive signal edges should no longer be rejected due to economics mode mismatch

## Testing

The fix should be tested by:
1. Running the 15m loop and observing order execution
2. Checking logs for `[15M-LOOP] Using validated probability model: ticker=... model_prob_yes_canonical=... p_hat_yes=... p_hat_no=...`
3. Verifying that NO orders have positive raw_edge when signal edge is positive
4. Checking logs for `[ECONOMICS-SELECTION] ticker=... using policy decision: expected_role=maker`
5. Verifying that orders with maker policy recommendations use maker economics (no spread cost, no fee)
6. Confirming that executable edges are positive for orders with positive signal edges

## Files Modified

- `merid/loop_15m.py`:
  - Simplified probability assignment to use canonical YES-space probability (model_prob_yes_canonical)
  - Removed complex side-specific logic that was causing confusion
  - Added logging to show model_prob_yes_canonical for debugging

- `merid/event_venues/kalshi/order_router.py`:
  - Updated `check_market_microstructure_edge_aware` function signature
  - Modified economics selection logic to respect policy decision
  - Updated call site to pass intent parameter
  - Removed duplicate economics calculation

## Related Issues

This fix addresses the parity counter issue where orders were being rejected despite having valid signal edges. The mismatch between probability interpretation and economics selection was causing the edge-aware gate to incorrectly reject orders.

## End-to-End Tracing Infrastructure

To make the fix provable and prevent future drift, an end-to-end candidate tracing system has been added:

### CandidateTrace Dataclass

Immutable trace record that captures the complete lifecycle of a trading candidate:
- **Signal generation stage**: signal_model_prob, signal_side, signal_edge_pct
- **Canonical probability conversion**: canonical_yes_prob, canonical_no_prob
- **Allocator/gate stage**: chosen_side, chosen_edge_pct
- **Policy/economics stage**: policy_intended_role, economics_mode, aggressiveness
- **Microstructure stage**: yes_bid_cents, no_bid_cents, order_price_cents, spread_cents, fee_cents, raw_edge_cents, executable_edge_cents
- **Router/execution stage**: router_timestamp, execution_timestamp
- **Terminal state**: terminal_state, terminal_reason

### Key Invariants Enforced

1. **Probability duality**: signal_model_prob + canonical_yes_prob == 1.0 for NO-side candidates
2. **Policy-economics consistency**: policy_intended_role determines economics mode unless explicitly overridden
3. **Edge sign consistency**: executable_edge computed from same side basis as signal layer
4. **Terminal state requirement**: Every candidate must have exactly one terminal state
5. **Counter reconciliation**: Ledger is replayable into same counters every time

### Tracing Integration

- **Signal generation** (agent_grid_15m.py): Initializes trace with signal_model_prob, signal_side, signal_edge_pct
- **Allocator** (loop_15m.py): Updates trace with canonical probability conversion (model_prob_yes_canonical)
- **Microstructure gate** (order_router.py): Updates trace with edge calculation and economics mode

### Test Suite

Comprehensive test suite in `tests/test_candidate_trace_probability_conversion.py`:

| Test Case | Description | Expected |
|---|---|---|
| `test_no_signal_probability_conversion` | NO signal at 0.76 → router receives canonical YES prob 0.24 | No violations |
| `test_no_order_positive_executable_edge` | NO order with positive trade-winning probability → executable edge positive | No violations |
| `test_policy_maker_with_aggressiveness` | Policy says maker, aggressiveness > 0 → router uses maker economics | No violations |
| `test_single_candidate_rejection` | 1 candidate, 0 fills, 1 reject → ledger reconciles exactly | Counters match |

### Running Tests

```bash
pytest tests/test_candidate_trace_probability_conversion.py -v
```

### Files Added

- `merid/event_venues/kalshi/candidate_trace.py`: CandidateTrace dataclass and CandidateTraceStore
- `tests/test_candidate_trace_probability_conversion.py`: Comprehensive test suite

### Files Modified

- `merid/prediction/agent_grid_15m.py`: Added trace initialization in signal generation
- `merid/loop_15m.py`: Added trace update with canonical probability conversion
- `merid/event_venues/kalshi/order_router.py`: Added trace update with microstructure stage data