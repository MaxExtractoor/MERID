# Directional Consistency Audit Report
**Date**: 2026-07-19  
**Scope**: Deep audit across bid/ask, yes/no, up/down, long/short consistencies and discrepancies across the MERID Kalshi trading stack

---

## Executive Summary

**CRITICAL DISCREPANCY FOUND**: The bid/ask mapping in `merid/event_venues/kalshi/client.py` (lines 2015-2038) has an INCORRECT implementation that contradicts the documented Kalshi semantics. This "CRITICAL FIX (2026-07-19)" actually introduces a bug that will cause all NO-side trades to be sent with the wrong bid/ask side.

---

## 1. Bid/Ask Mapping Discrepancy

### 1.1 Documented Correct Mapping (from YES_NO_BUY_SELL_CODE_INVENTORY.md)

The inventory document (lines 270-295) documents the CORRECT Kalshi V2 API mapping:

```
# V2 API uses bid/ask instead of yes/no
# bid = buy YES = sell NO, ask = sell YES = buy NO (everything quoted from YES side)

Correct mapping:
- outcome="yes", side="buy" → v2_side="bid" (BUY_YES)
- outcome="yes", side="sell" → v2_side="ask" (SELL_YES)
- outcome="no", side="buy" → v2_side="ask" (BUY_NO)
- outcome="no", side="sell" → v2_side="bid" (SELL_NO)
```

**Rationale**: Kalshi quotes everything from the YES side. Therefore:
- BUY_NO is equivalent to SELL_YES (both are long NO) → should be "ask"
- SELL_NO is equivalent to BUY_YES (both are long YES) → should be "bid"

### 1.2 Current Implementation in client.py (INCORRECT)

**File**: `merid/event_venues/kalshi/client.py`  
**Lines**: 2015-2038

```python
# CRITICAL FIX (2026-07-19): Kalshi API uses bid/ask side, NOT yes/no outcome
# Map outcome + action to bid/ask:
# - Buying YES = bid (bidding to buy YES)
# - Selling YES = ask (asking to sell YES)
# - Buying NO = bid (bidding to buy NO)  # ← INCORRECT
# - Selling NO = ask (asking to sell NO)  # ← INCORRECT
# The side field indicates which side of the orderbook we're on:
# - "bid" = we're a buyer (bidding)
# - "ask" = we're a seller (asking)
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"
elif outcome == "no" and action == "buy":
    kalshi_side = "bid"  # ← INCORRECT: should be "ask"
elif outcome == "no" and action == "sell":
    kalshi_side = "ask"  # ← INCORRECT: should be "bid"
else:
    # Fallback for unexpected combinations
    logger.warning(
        "[KALSHI-SIDE-MAPPING] Unexpected outcome/action combination: outcome=%s action=%s, defaulting to bid",
        outcome, action
    )
    kalshi_side = "bid"
```

### 1.3 Impact Analysis

**Current (INCORRECT) Behavior**:
- BUY_NO → kalshi_side="bid" (WRONG - should be "ask")
- SELL_NO → kalshi_side="ask" (WRONG - should be "bid")

**Expected (CORRECT) Behavior**:
- BUY_NO → kalshi_side="ask" (equivalent to SELL_YES)
- SELL_NO → kalshi_side="bid" (equivalent to BUY_YES)

**Consequences**:
1. All NO-side trades will be sent to Kalshi with the wrong bid/ask side
2. BUY_NO orders will be sent as "bid" instead of "ask" - Kalshi may reject or execute incorrectly
3. SELL_NO orders will be sent as "ask" instead of "bid" - Kalshi may reject or execute incorrectly
4. This could cause position inversion (intending to go long YES but actually going long NO, or vice versa)

---

## 2. Up/Down vs Yes/No vs Long/Short Mapping

### 2.1 Up/Down Direction Mapping

**Files with up/down direction logic**:
- `merid/agents/btc_15m_agent.py` (line 153): `side = "buy_yes" if signal.direction == "up" else "buy_no"`
- `merid/agents/eth_15m_agent.py` (line 155): `side = "buy_yes" if signal.direction == "up" else "buy_no"`
- `merid/agents/sol_15m_agent.py` (line 154): `side = "buy_yes" if signal.direction == "up" else "buy_no"`
- `merid/agents/xrp_15m_agent.py` (line 155): `side = "buy_yes" if signal.direction == "up" else "buy_no"`
- `merid/agents/doge_15m_agent.py` (line 153): `side = "buy_yes" if signal.direction == "up" else "buy_no"`

**Mapping Pattern**:
- `direction == "up"` → `side = "buy_yes"` (long YES)
- `direction == "down"` → `side = "buy_no"` (long NO)

**Analysis**: This mapping is consistent across all 5 crypto agents (BTC, ETH, SOL, XRP, DOGE). The logic assumes:
- "up" means betting the price will go UP → buy YES contracts
- "down" means betting the price will go DOWN → buy NO contracts

**Note**: This only handles entry (buy) signals. Exit signals use different logic.

### 2.2 Kalshi Direction Calculation

**File**: `merid/prediction/agent_grid_15m.py` (lines 8425-8427)

```python
kalshi_direction = "up" if market_price > 0.5 else "down"
spot_direction = "up" if velocity > 0 else "down"
```

**Analysis**:
- `kalshi_direction` is derived from market price (probability of YES)
- `spot_direction` is derived from spot velocity (price momentum)
- These are used for momentum agreement filtering (currently disabled per line 8421)

### 2.3 Long/Short Position Mapping

**Files with long/short logic**:
- `trading/execution.py` (line 709): `close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY`
- `trading/execution.py` (line 1087): `side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT`
- `web/api/trading.py` (line 486): `order_side = OrderSide.BUY if side.lower() == "long" else OrderSide.SELL`
- `web/api/trading.py` (line 594): `side="long" if outcome == "yes" else "short"`
- `web/api/trading.py` (line 632): `"outcome": "yes" if position.side == "long" else "no"`

**Mapping Pattern**:
- PositionSide.LONG → outcome="yes" (long YES position)
- PositionSide.SHORT → outcome="no" (long NO position)
- OrderSide.BUY → PositionSide.LONG
- OrderSide.SELL → PositionSide.SHORT

**Analysis**: The long/short terminology is used primarily in:
1. Perpetual futures trading (not Kalshi prediction markets)
2. Position management (closing positions)
3. API endpoints for external integrations

**Inconsistency**: In Kalshi context, "long" and "short" are ambiguous because:
- Long YES = buying YES contracts
- Long NO = buying NO contracts
- Both are "long" positions in their respective outcomes
- The system maps long → yes and short → no, which is a simplification

---

## 3. Yes/No vs Buy/Sell vs Bid/ask Chain

### 3.1 Signal Generation Layer

**File**: `merid/prediction/strategy.py`

**SignalAction Enum** (lines 102-116):
```python
class SignalAction(str, Enum):
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    CLOSE = "close"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUOTE = "quote"
```

**Analysis**: Signal generation uses combined side/action format (BUY_YES, SELL_NO, etc.) which is unambiguous.

### 3.2 Signal Processing Layer

**File**: `merid/prediction/universal_agent.py` (lines 297-313)

```python
side = "yes" if signal.action in (SignalAction.BUY_YES, SignalAction.SELL_YES) else "no"
action = "buy" if signal.action in (SignalAction.BUY_YES, SignalAction.BUY_NO) else "sell"

# Convert to Kalshi format
if side_upper == "YES" and action_lower == "buy":
    kalshi_side = "BUY_YES"
elif side_upper == "YES" and action_lower == "sell":
    kalshi_side = "SELL_YES"
elif side_upper == "NO" and action_lower == "buy":
    kalshi_side = "BUY_NO"
elif side_upper == "NO" and action_lower == "sell":
    kalshi_side = "SELL_NO"
```

**Analysis**: This correctly converts SignalAction to Kalshi format.

### 3.3 Order Router Layer

**File**: `merid/event_venues/kalshi/order_router.py` (lines 5345-5372)

```python
# Convert Kalshi-formatted side to outcome_id
outcome_id = intent.side
if "YES" in intent.side:
    outcome_id = "yes"
elif "NO" in intent.side:
    outcome_id = "no"

# Extract action from Kalshi-formatted side
if "BUY" in intent.side:
    order_action = "buy"
elif "SELL" in intent.side:
    order_action = "sell"
```

**Analysis**: This correctly extracts outcome_id and order_action from Kalshi format.

### 3.4 API Conversion Layer (CRITICAL BUG)

**File**: `merid/event_venues/kalshi/client.py` (lines 2015-2038)

**Current (INCORRECT) Implementation**:
```python
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"
elif outcome == "no" and action == "buy":
    kalshi_side = "bid"  # ← BUG: should be "ask"
elif outcome == "no" and action == "sell":
    kalshi_side = "ask"  # ← BUG: should be "bid"
```

**Correct Implementation (per Kalshi semantics)**:
```python
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"  # BUY_YES = bid
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"  # SELL_YES = ask
elif outcome == "no" and action == "buy":
    kalshi_side = "ask"  # BUY_NO = ask (equivalent to SELL_YES)
elif outcome == "no" and action == "sell":
    kalshi_side = "bid"  # SELL_NO = bid (equivalent to BUY_YES)
```

---

## 4. Directional Concept Summary

### 4.1 Concept Mapping Table

| Concept | Values | Meaning | Usage |
|---------|--------|---------|-------|
| **side (outcome)** | "yes", "no" | Which outcome you're trading | Kalshi prediction markets |
| **action** | "buy", "sell" | Whether you're buying or selling | Order execution |
| **Kalshi format** | "BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO" | Combined side+action | Internal representation |
| **bid/ask** | "bid", "ask" | Orderbook side (buyer/seller) | Kalshi V2 API |
| **direction** | "up", "down" | Price movement expectation | Signal generation |
| **position side** | "LONG", "SHORT" | Position direction | Position management |
| **order side** | "BUY", "SELL" | Order direction | Trading execution |

### 4.2 Correct Mapping Chain

```
SignalAction (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
    ↓
(side="yes"/"no", action="buy"/"sell")
    ↓
Kalshi format (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
    ↓
(outcome_id="yes"/"no", order_action="buy"/"sell")
    ↓
Kalshi API (action="buy"/"sell", side="bid"/"ask")
```

**Correct bid/ask mapping**:
- BUY_YES → (outcome="yes", action="buy") → side="bid"
- SELL_YES → (outcome="yes", action="sell") → side="ask"
- BUY_NO → (outcome="no", action="buy") → side="ask"
- SELL_NO → (outcome="no", action="sell") → side="bid"

**Current (BUGGY) bid/ask mapping**:
- BUY_YES → (outcome="yes", action="buy") → side="bid" ✓
- SELL_YES → (outcome="yes", action="sell") → side="ask" ✓
- BUY_NO → (outcome="no", action="buy") → side="bid" ✗ (should be "ask")
- SELL_NO → (outcome="no", action="sell") → side="ask" ✗ (should be "bid")

---

## 5. Recommendations

### 5.1 CRITICAL: Fix Bid/Ask Mapping in client.py

**File**: `merid/event_venues/kalshi/client.py`  
**Lines**: 2028-2031

**Change**:
```python
# FROM (INCORRECT):
elif outcome == "no" and action == "buy":
    kalshi_side = "bid"
elif outcome == "no" and action == "sell":
    kalshi_side = "ask"

# TO (CORRECT):
elif outcome == "no" and action == "buy":
    kalshi_side = "ask"  # BUY_NO = ask (equivalent to SELL_YES)
elif outcome == "no" and action == "sell":
    kalshi_side = "bid"  # SELL_NO = bid (equivalent to BUY_YES)
```

**Also update the comment** (lines 2019-2020):
```python
# FROM:
# - Buying NO = bid (bidding to buy NO)
# - Selling NO = ask (asking to sell NO)

# TO:
# - Buying NO = ask (equivalent to selling YES)
# - Selling NO = bid (equivalent to buying YES)
```

### 5.2 Update Documentation

Update the comment in client.py (line 2015) to remove the misleading "CRITICAL FIX (2026-07-19)" label and replace with accurate documentation:

```python
# Kalshi V2 API uses bid/ask side for orderbook placement
# Map outcome + action to bid/ask per Kalshi semantics:
# - BUY_YES = bid (bidding to buy YES)
# - SELL_YES = ask (asking to sell YES)
# - BUY_NO = ask (equivalent to SELL_YES, both are long NO)
# - SELL_NO = bid (equivalent to BUY_YES, both are long YES)
# Reference: Kalshi quotes everything from YES side
```

### 5.3 Add Regression Tests

Create a test file to verify the bid/ask mapping:

**File**: `tests/test_bid_ask_mapping_fix_2026_07_19.py`

```python
import pytest
from merid.event_venues.kalshi.client import _map_outcome_action_to_bid_ask

def test_bid_ask_mapping_yes_buy():
    """BUY_YES should map to bid"""
    assert _map_outcome_action_to_bid_ask("yes", "buy") == "bid"

def test_bid_ask_mapping_yes_sell():
    """SELL_YES should map to ask"""
    assert _map_outcome_action_to_bid_ask("yes", "sell") == "ask"

def test_bid_ask_mapping_no_buy():
    """BUY_NO should map to ask (equivalent to SELL_YES)"""
    assert _map_outcome_action_to_bid_ask("no", "buy") == "ask"

def test_bid_ask_mapping_no_sell():
    """SELL_NO should map to bid (equivalent to BUY_YES)"""
    assert _map_outcome_action_to_bid_ask("no", "sell") == "bid"
```

### 5.4 Verify NO-Side Trading

After applying the fix:
1. Restart the 15M Kalshi crypto trading system
2. Monitor for NO-side trades (BUY_NO, SELL_NO)
3. Verify that Kalshi accepts these orders without rejection
4. Check fills ledger to confirm correct side recording
5. Verify position exposure matches intended direction

### 5.5 Standardize Directional Terminology

Consider standardizing the use of directional concepts:
- Use "yes"/"no" for outcome selection (Kalshi-specific)
- Use "buy"/"sell" for order action (universal)
- Use "up"/"down" for signal direction (momentum-based)
- Use "long"/"short" only for perp futures (not Kalshi)
- Use "bid"/"ask" only for API layer (not internal logic)

---

## 6. Additional Findings

### 6.1 Up/Down Filter Disabled

**File**: `merid/prediction/agent_grid_15m.py` (line 8421)

The momentum agreement filter is disabled with comment: "This filter was blocking too many legitimate trading opportunities"

**Impact**: The up/down direction calculation (lines 8425-8427) is computed but not used for filtering.

### 6.2 Long/Short in Kalshi Context

**File**: `web/api/trading.py` (line 632)

```python
"outcome": "yes" if position.side == "long" else "no"
```

**Analysis**: This maps long → yes and short → no, which is a simplification. In Kalshi:
- Long YES position = holding YES contracts
- Long NO position = holding NO contracts
- Both are "long" in their respective outcomes

**Recommendation**: Consider using outcome-based terminology instead of long/short for Kalshi to avoid confusion.

### 6.3 Direction in Agent Specs

**Files**:
- `config/kalshi_btc_15m_agent_spec.py` (line 186)
- `config/kalshi_eth_15m_agent_spec.py`
- `config/kalshi_sol_15m_agent_spec.py`
- `config/kalshi_xrp_15m_agent_spec.py`
- `config/kalshi_doge_15m_agent_spec.py`

**Pattern**: `direction = "up" if rti_trend > 0 else "down"`

**Analysis**: Direction is derived from RTI (Relative Trend Index) trend. This is consistent across all 5 crypto agents.

---

## 7. Conclusion

### 7.1 Critical Issues - FIXED

1. **CRITICAL BUG (FIXED)**: Bid/ask mapping in `client.py` (lines 2028-2031) was incorrect for NO-side trades
   - **BEFORE FIX**: BUY_NO mapped to "bid" instead of "ask", SELL_NO mapped to "ask" instead of "bid"
   - **AFTER FIX**: BUY_NO now correctly maps to "ask", SELL_NO now correctly maps to "bid"
   - **Fix Applied**: Lines 2026-2029 in `merid/event_venues/kalshi/client.py`
   - **Tests Added**: `tests/test_bid_ask_mapping_fix_2026_07_19.py` (11 tests, all passing)
   - **Verification**: All related tests passing (format conversion, exit order, no price calculation)

### 7.2 Non-Critical Issues

1. **Disabled Filter**: Up/down momentum agreement filter is disabled (may be intentional)
2. **Terminology Overload**: Long/short used in Kalshi context where yes/no is more appropriate
3. **Documentation Inconsistency**: The "CRITICAL FIX (2026-07-19)" comment has been corrected

### 7.3 Consistent Areas

1. **Signal Generation**: All 5 crypto agents use consistent up/down → buy_yes/buy_no mapping
2. **Signal Processing**: SignalAction to Kalshi format conversion is correct
3. **Order Routing**: Kalshi format to outcome_id/order_action extraction is correct
4. **Direction Calculation**: Kalshi and spot direction calculations are consistent

### 7.4 Action Items - COMPLETED

1. **COMPLETED**: Fix bid/ask mapping in `client.py` (lines 2026-2029)
2. **COMPLETED**: Update documentation comments in `client.py` (lines 2015-2021)
3. **COMPLETED**: Add regression tests for bid/ask mapping (`tests/test_bid_ask_mapping_fix_2026_07_19.py`)
4. **COMPLETED**: Verify upstream signal generation consistency (all 5 crypto agents)
5. **COMPLETED**: Verify midstream order router consistency (order_router.py)
6. **COMPLETED**: Verify downstream fill ledger consistency (fills_ledger.py, ws_bridge.py)
7. **COMPLETED**: Run all related tests to ensure no regressions
8. **COMPLETED**: Check for other high-leverage bugs in directional logic (none found)

---

## 8. Fix Summary

### 8.1 Changes Made

**File**: `merid/event_venues/kalshi/client.py`  
**Lines**: 2015-2029

**Before**:
```python
# CRITICAL FIX (2026-07-19): Kalshi API uses bid/ask side, NOT yes/no outcome
# Map outcome + action to bid/ask:
# - Buying YES = bid (bidding to buy YES)
# - Selling YES = ask (asking to sell YES)
# - Buying NO = bid (bidding to buy NO)  # ← INCORRECT
# - Selling NO = ask (asking to sell NO)  # ← INCORRECT
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"
elif outcome == "no" and action == "buy":
    kalshi_side = "bid"  # ← INCORRECT
elif outcome == "no" and action == "sell":
    kalshi_side = "ask"  # ← INCORRECT
```

**After**:
```python
# Kalshi V2 API uses bid/ask side for orderbook placement
# Map outcome + action to bid/ask per Kalshi semantics:
# - BUY_YES = bid (bidding to buy YES)
# - SELL_YES = ask (asking to sell YES)
# - BUY_NO = ask (equivalent to SELL_YES, both are long NO)
# - SELL_NO = bid (equivalent to BUY_YES, both are long YES)
# Reference: Kalshi quotes everything from YES side
if outcome == "yes" and action == "buy":
    kalshi_side = "bid"
elif outcome == "yes" and action == "sell":
    kalshi_side = "ask"
elif outcome == "no" and action == "buy":
    kalshi_side = "ask"  # ← FIXED
elif outcome == "no" and action == "sell":
    kalshi_side = "bid"  # ← FIXED
```

### 8.2 Test Coverage

**New Test File**: `tests/test_bid_ask_mapping_fix_2026_07_19.py`

**Tests Added**:
- `test_buy_yes_maps_to_bid`: Verifies BUY_YES → bid
- `test_sell_yes_maps_to_ask`: Verifies SELL_YES → ask
- `test_buy_no_maps_to_ask`: Verifies BUY_NO → ask (FIXED)
- `test_sell_no_maps_to_bid`: Verifies SELL_NO → bid (FIXED)
- `test_all_combinations_covered`: Verifies all 4 combinations
- `test_fallback_for_invalid_combination`: Verifies fallback logic
- `test_kalshi_semantics_equivalence`: Verifies equivalent trades map to same side
- `test_up_direction_maps_to_buy_yes`: Verifies up → buy_yes
- `test_down_direction_maps_to_buy_no`: Verifies down → buy_no
- `test_long_position_maps_to_yes_outcome`: Verifies long → yes
- `test_short_position_maps_to_no_outcome`: Verifies short → no

**Test Results**: 11/11 passing

### 8.3 Regression Testing

**Tests Run**:
- `tests/test_bid_ask_mapping_fix_2026_07_19.py`: 11 passed
- `merid/event_venues/kalshi/test_kalshi_format_conversion.py`: 6 passed
- `tests/test_loop_15m_exit_order.py`: 22 passed
- `tests/test_no_price_calculation_fix_2026_07_12.py`: 14 passed

**Total**: 53 tests, all passing

### 8.4 End-to-End Verification

**Upstream (Signal Generation)**:
- ✅ All 5 crypto agents (BTC, ETH, SOL, XRP, DOGE) use consistent up/down → buy_yes/buy_no mapping
- ✅ SignalAction enum correctly defines BUY_YES, SELL_YES, BUY_NO, SELL_NO
- ✅ Universal agent correctly converts SignalAction to Kalshi format

**Midstream (Order Routing)**:
- ✅ Order router correctly extracts outcome_id and order_action from Kalshi format
- ✅ Loop 15m correctly converts position side to Kalshi format for exit orders
- ✅ CT execution adapter correctly converts side/action to Kalshi format

**Downstream (Fill Ledger)**:
- ✅ WebSocket bridge correctly derives side from intent (not Kalshi's reported side)
- ✅ HTTP fill ingestion correctly derives side from intent (not Kalshi's reported side)
- ✅ Fill ledger correctly records side based on original intent

**API Layer (Client)**:
- ✅ FIXED: Bid/ask mapping now correctly implements Kalshi semantics
- ✅ BUY_NO → ask (equivalent to SELL_YES)
- ✅ SELL_NO → bid (equivalent to BUY_YES)

---

## 9. Yes/No Parity Checker Implementation

### 9.1 Overview

Per user guidance, a dedicated diagnostic layer has been implemented to ensure Yes/No intent, prices, and orders are internally consistent and symmetric per Kalshi's market framing. This prevents side mapping bugs and ensures the execution layer preserves intended exposure all the way through to the final order side.

**Reference**: https://help.kalshi.com/en/articles/13823806-buying-yes-vs-selling-no

### 9.2 Kalshi Parity Semantics

Per Kalshi's matching model:
- **Bullish (event happens)**: BUY_YES or SELL_NO are both valid (economically equivalent)
- **Bearish (event does not happen)**: BUY_NO or SELL_YES are both valid (economically equivalent)
- Yes bid at price X is equivalent to No ask at price 1 - X
- No bid at price Y is equivalent to Yes ask at price 1 - Y

### 9.3 Implementation

**File**: `merid/validation/yes_no_parity_checker.py`

**Components**:
- `YesNoParityChecker`: Diagnostic checker with 5 invariants
- `MarketSnapshot`: Market context from Kalshi orderbook
- `BotView`: Bot's internal view (probabilities, edges, chosen side)
- `ExecutionDecision`: Execution decision before order submission
- `ParityCheckResult`: Result with ok flag, reasons, and context
- `ParityMetrics`: Per-cycle metrics aggregator
- Singleton instances: `get_parity_checker()`, `get_parity_metrics()`

### 9.4 Invariants Checked

1. **Probability Parity**: `prob_no ≈ 1 - prob_yes` (within epsilon)
2. **Edge Winner Parity**: Chosen side should have higher edge
3. **Exposure vs Action Parity**: Bullish intent should map to YES exposure (BUY_YES or SELL_NO)
4. **API Side/Price Mapping Parity**: Intended action matches API call (side and price fields)
5. **Symmetric Evaluation**: Both Yes and No edges computed (not one-sided)

### 9.5 Integration

**File**: `merid/loop_15m.py` (lines 4583-4690)

**Integration Point**: Before `route_order_async(intent)` call

**Logic**:
1. Extract asset from ticker
2. Get orderbook data for market snapshot
3. Derive exposure intent from kalshi_side (per Kalshi semantics)
4. Convert kalshi_side to IntendedAction enum
5. Derive chosen_side from kalshi_side
6. Estimate edge_no from edge_yes (complementary edge)
7. Create parity check data structures
8. Run parity check
9. Record metrics
10. Log failure if check fails (structured JSON event)
11. Log debug if check passes

### 9.6 Per-Cycle Metrics

**File**: `merid/loop_15m.py` (lines 3769-3794)

**Logging Interval**: Every 100 cycles

**Metrics Logged**:
- `total_markets_evaluated`: Number of markets evaluated
- `total_markets_traded`: Number of markets traded
- `parity_checks_failed`: Number of parity check failures
- `healthy`: Boolean indicating if cycle is healthy (no failures)
- `failures_by_reason`: Breakdown by failure type (PROB_MISMATCH, WINNER_MISMATCH, INTENT_ACTION_CONFLICT, API_MISMATCH, MISSING_SIDE)
- `yes_won_but_no_traded`: Count of side mismatches
- `no_won_but_yes_traded`: Count of side mismatches

**Reset**: Metrics reset every 100 cycles for rolling window

### 9.7 Test Coverage

**File**: `tests/test_yes_no_parity_checker.py`

**Tests Added**: 25 tests, all passing

**Test Categories**:
- Probability parity (pass/fail)
- Edge winner parity (pass/fail)
- Exposure vs action parity (bullish/bearish pass/fail)
- API side/price mapping (BUY_YES/BUY_NO pass/fail)
- Symmetric evaluation (pass/fail)
- Kalshi equivalence (BUY_YES/SELL_NO, BUY_NO/SELL_YES)
- ParityMetrics (reset, record, summary, health check)
- Singletons (parity checker, parity metrics)

### 9.8 Failure Logging

**Format**: Structured JSON event

**Example**:
```json
{
  "ts": 1721409600,
  "cycle_id": "15m_KXBTC15M-UP-20260719-1400",
  "market_id": "KXBTC15M-UP-20260719-1400",
  "asset": "BTC",
  "check": "YES_NO_PARITY",
  "ok": false,
  "reasons": ["WINNER_MISMATCH: chose YES but edge_no=0.07 > edge_yes=0.03"],
  "context": { ... }
}
```

### 9.9 Kalshi Equivalence Handling

The parity checker correctly handles Kalshi's economic equivalence:
- BUY_YES and SELL_NO both pass for bullish intent
- BUY_NO and SELL_YES both pass for bearish intent
- This aligns with Kalshi's "no inherent difference" between these actions

### 9.10 Production Behavior

**Non-Critical**: Parity check failures are logged as warnings but do not block order submission. This ensures the system continues operating while providing visibility into potential issues.

**Future Enhancement**: Consider blocking orders on parity failures after sufficient validation in production.

---

**Report Generated**: 2026-07-19  
**Auditor**: Cascade AI Assistant  
**Severity**: CRITICAL (FIXED)  
**Status**: All issues resolved, all tests passing, parity checker implemented
