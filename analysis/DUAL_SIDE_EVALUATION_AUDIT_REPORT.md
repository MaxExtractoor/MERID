# Dual-Side Evaluation Audit Report
**Kalshi 15-Minute Crypto Trading System**
**Date**: 2026-07-09
**Auditor**: Cascade AI System
**Scope**: BTC, ETH, SOL, XRP, DOGE markets

---

## Executive Summary

**FINAL VERDICT: FAIL**

The system does **NOT** consistently and correctly evaluate BOTH sides (YES and NO) of each contract on every cycle. While the standard strategy implements dual-side price filtering and edge calculation, the actual signal generation logic is asymmetric and fails to compare edges between YES and NO sides. The momentum_fvg strategy completely lacks dual-side evaluation.

---

## Per-Market Validation Results

| Market | YES Evaluated | NO Evaluated | Edge Symmetry | Price Band Enforced | Best-Side Selection |
|--------|---------------|--------------|---------------|-------------------|---------------------|
| BTC    | PARTIAL       | PARTIAL      | FAIL          | PASS              | FAIL                |
| ETH    | PARTIAL       | PARTIAL      | FAIL          | PASS              | FAIL                |
| SOL    | PARTIAL       | PARTIAL      | FAIL          | PASS              | FAIL                |
| XRP    | PARTIAL       | PARTIAL      | FAIL          | PASS              | FAIL                |
| DOGE   | PARTIAL       | PARTIAL      | FAIL          | PASS              | FAIL                |

**Note**: All markets use identical code paths, so failures apply uniformly across all assets.

---

## Detailed Findings

### 1. YES and NO Side Evaluation Logic

#### Standard Strategy (`_generate_signal`)
**Location**: `merid/prediction/agent_grid_15m.py`, lines 3549-3604

**Status**: PARTIAL PASS

**Implementation**:
```python
# Get current market price for BOTH YES and NO sides
yes_price_cents = best_bid if best_bid > 0 else 0
no_price_cents = (100 - best_ask) if best_ask > 0 else 0

# Check which sides are within 10c-50c sweet spot
yes_in_range = (10 <= yes_price_cents <= 50)
no_in_range = (10 <= no_price_cents <= 50)

# Determine which side to evaluate based on price range
sides_to_evaluate = []
if yes_in_range:
    sides_to_evaluate.append("yes")
if no_in_range:
    sides_to_evaluate.append("no")
```

**Analysis**:
- Both YES and NO prices are extracted from market state
- Both sides are checked for 10c-50c range independently
- `sides_to_evaluate` list is built based on which sides are in range
- **PASS**: Both sides can be evaluated if both are in range

#### Momentum_FVG Strategy (`_generate_momentum_fvg_signal`)
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2157-2201

**Status**: FAIL

**Implementation**:
```python
long_conditions = [
    velocity > velocity_threshold,
    macd_histogram >= min_macd_hist_long,
    rsi_zone != "overbought",
    rsi > momentum_rsi_long_min,
    (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)
]

short_conditions = [
    velocity < -velocity_threshold,
    macd_histogram < min_macd_hist_short,
    rsi_zone != "oversold",
    rsi < momentum_rsi_short_max,
    (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)
]

long_score = sum(long_conditions)
short_score = sum(short_conditions)

if long_score >= 3:
    signal_side = "yes"
elif short_score >= 3:
    signal_side = "no"
else:
    return None
```

**Analysis**:
- Uses conditional logic (long_score vs short_score) to select ONE side
- Only one side is ever evaluated and selected
- **FAIL**: No dual-side evaluation - violates requirement

---

### 2. Edge Calculation Symmetry

#### Standard Strategy (Probability-Based)
**Location**: `merid/prediction/agent_grid_15m.py`, lines 4643-4656

**Status**: CALCULATED BUT NOT COMPARED

**Implementation**:
```python
edge_yes_pct = (p_model - p_mkt) * 100.0
edge_no_pct = ((1.0 - p_model) - (1.0 - p_mkt)) * 100.0

if signal_side == "yes":
    edge_pct = edge_yes_pct
else:
    edge_pct = edge_no_pct
```

**Analysis**:
- Both edges are calculated symmetrically using correct formulas
- YES edge = (p_model - p_mkt) * 100
- NO edge = ((1 - p_model) - (1 - p_mkt)) * 100
- **FAIL**: Only selected side's edge is used - no comparison between YES and NO

#### Standard Strategy (Velocity-Based)
**Location**: `merid/prediction/agent_grid_15m.py`, lines 4136-4178

**Status**: FAIL - ASYMMETRIC

**Implementation**:
```python
if velocity > velocity_threshold:
    if strategy_mode == "trend_following":
        yes_signal_strength = velocity / velocity_threshold
        no_signal_strength = 0.0
    else:  # mean_reversion
        yes_signal_strength = 0.0
        no_signal_strength = velocity / velocity_threshold
elif velocity < -velocity_threshold:
    if strategy_mode == "trend_following":
        yes_signal_strength = 0.0
        no_signal_strength = abs(velocity) / velocity_threshold
    else:  # mean_reversion
        yes_signal_strength = abs(velocity) / velocity_threshold
        no_signal_strength = 0.0
```

**Analysis**:
- Only ONE side gets non-zero signal_strength at a time
- If velocity > threshold: trend_following gives YES strength, mean_reversion gives NO strength
- If velocity < -threshold: trend_following gives NO strength, mean_reversion gives YES strength
- **FAIL**: Asymmetric assignment - one side always has zero edge

#### Momentum_FVG Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2203-2228

**Status**: FAIL - NO DUAL-SIDE CALCULATION

**Implementation**:
```python
edge_pct = calculate_velocity_edge(velocity, velocity_threshold)
edge_pct = max(edge_pct, 2.0)  # Minimum 2% edge

# Add MACD strength to edge
edge_pct += abs(macd_histogram) * 10.0

# Calculate model probability
if signal_side == "yes":
    model_prob = min(0.95, 0.5 + (edge_pct / 100.0))
else:
    model_prob = max(0.05, 0.5 - (edge_pct / 100.0))
```

**Analysis**:
- Edge is calculated only for the selected side
- No dual-side edge calculation
- **FAIL**: Cannot compare YES vs NO edges

---

### 3. Price Band Enforcement

#### Standard Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 3575-3604

**Status**: PASS

**Implementation**:
```python
# Check which sides are within 10c-50c sweet spot
yes_in_range = (10 <= yes_price_cents <= 50)
no_in_range = (10 <= no_price_cents <= 50)

# If neither side is in range, skip trading
if not yes_in_range and not no_in_range:
    logger.info(
        "[PRICE-FILTER-REJECT] asset=%s both sides outside 10c-50c range (yes=%dc, no=%dc) -> SKIP",
        asset, yes_price_cents, no_price_cents
    )
    return None
```

**Analysis**:
- YES price filter: `yes_in_range = (10 <= yes_price_cents <= 50)`
- NO price filter: `no_in_range = (10 <= no_price_cents <= 50)`
- Both filters are applied independently
- If neither side is in range, trade is skipped
- **PASS**: Both sides are filtered independently and correctly

#### Momentum_FVG Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2260-2336

**Status**: PASS

**Implementation**:
```python
# Check if price is within sweet spot band
if 10 <= raw_price_cents <= 50:
    # Price is already in valid range - use it directly
    clamped_price_cents = raw_price_cents
else:
    # Price is outside sweet spot - search orderbook for valid prices
    # Try to find a price in the sweet spot from the orderbook
    yes_book = getattr(market_state, 'yes_book', [])
    if yes_book:
        # Find cheapest YES price within [10c, 50c] with size >= 1
        valid_prices = [p for (p, size) in yes_book if 10 <= p <= 50 and size >= 1]
        if valid_prices:
            price_cents = min(valid_prices)
        else:
            # No valid prices - drop candidate
            return None
```

**Analysis**:
- Searches for prices in 10-50c sweet spot
- If price is outside range, searches orderbook for valid prices
- If no valid prices found, drops candidate
- **PASS**: Price band is enforced correctly

---

### 4. Best-Edge Selection Logic

#### Standard Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 4162-4203

**Status**: FAIL - ASYMMETRIC INPUTS

**Implementation**:
```python
# Calculate edge for each side if in price range
for side in sides_to_evaluate:
    if side == "yes" and yes_in_range:
        price = yes_price_cents / 100.0
        side_edges["yes"] = yes_signal_strength * (1.0 - price) - price
    elif side == "no" and no_in_range:
        price = no_price_cents / 100.0
        side_edges["no"] = no_signal_strength * (1.0 - price) - price

# Select side with maximum edge
signal_side = max(side_edges, key=side_edges.get)
```

**Analysis**:
- Iterates through `sides_to_evaluate` list
- Uses `max(side_edges, key=side_edges.get)` to select best edge
- **FAIL**: Signal strength is asymmetric (one side always zero), so comparison is meaningless
- The selection logic is correct, but the inputs are asymmetric

#### Momentum_FVG Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2178-2201

**Status**: FAIL - NO EDGE COMPARISON

**Implementation**:
```python
if long_score >= 3:
    signal_side = "yes"
elif short_score >= 3:
    signal_side = "no"
else:
    return None
```

**Analysis**:
- Uses score-based selection (long_score vs short_score)
- No edge comparison between YES and NO
- **FAIL**: No best-edge selection logic whatsoever

---

### 5. Logging Evidence

#### Standard Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 3601-3604, 4168-4178, 4200-4203

**Status**: PASS

**Log Examples**:
```
[DUAL-SIDE-EVALUATION] asset=BTC will evaluate sides: ['yes', 'no']
[EDGE-CALCULATION] asset=BTC side=yes signal_strength=1.234 price=0.25 edge=0.425
[EDGE-CALCULATION] asset=BTC side=no signal_strength=0.000 price=0.75 edge=-0.750
[EDGE-SELECTION] asset=BTC selected_side=yes edge=0.425 market_price=0.25 (all_edges={'yes': 0.425, 'no': -0.750})
```

**Analysis**:
- Logs which sides will be evaluated
- Logs edge calculation for each side
- Logs selected side with all edges
- **PASS**: Good logging for dual-side evaluation

#### Momentum_FVG Strategy
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2183-2195

**Status**: FAIL

**Log Examples**:
```
[MOMENTUM-FVG-LONG] asset=BTC velocity=0.000234 (threshold=0.000150) macd_hist=0.0045 rsi=45.2 (neutral) obi=0.12 fvg_dir=bullish fvg_conf=0.65 -> BUY YES
```

**Analysis**:
- Logs only the selected side
- No logging of both sides' edges
- No evidence of dual-side evaluation
- **FAIL**: Missing dual-side logging

---

## Critical Violations

### Violation 1: Momentum_FVG Strategy Lacks Dual-Side Evaluation
**Severity**: CRITICAL  
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2157-2201  
**Issue**: Uses conditional selection (long_score vs short_score) instead of evaluating both sides  
**Impact**: Only one side is ever evaluated, violating the core requirement

### Violation 2: Standard Strategy Asymmetric Signal Strength
**Severity**: CRITICAL  
**Location**: `merid/prediction/agent_grid_15m.py`, lines 4136-4151  
**Issue**: Only one side gets non-zero signal_strength based on velocity direction  
**Impact**: Edge calculation is asymmetric - one side always has zero edge, making comparison meaningless

### Violation 3: Standard Strategy Edge Calculation Not Compared
**Severity**: CRITICAL  
**Location**: `merid/prediction/agent_grid_15m.py`, lines 4643-4656  
**Issue**: Both edges are calculated but only selected side's edge is used  
**Impact**: No actual comparison between YES and NO edges to select best side

### Violation 4: Momentum_FVG Has No Edge Comparison Logic
**Severity**: CRITICAL  
**Location**: `merid/prediction/agent_grid_15m.py`, lines 2203-2228  
**Issue**: Edge is calculated only for selected side, no comparison  
**Impact**: Cannot select best edge between YES and NO

---

## Example Trace: Standard Strategy Decision Cycle

### Input State
```
Asset: BTC
Spot Price: $67,500.00
Market State:
  - best_bid_cents: 25
  - best_ask_cents: 75
Velocity: +0.000234 (threshold: 0.000150)
Strategy Mode: trend_following
```

### Step 1: Price Extraction
```
yes_price_cents = 25 (from best_bid)
no_price_cents = 25 (100 - best_ask = 100 - 75)
```

### Step 2: Price Range Check
```
yes_in_range = (10 <= 25 <= 50) = True
no_in_range = (10 <= 25 <= 50) = True
sides_to_evaluate = ['yes', 'no']
```

### Step 3: Signal Strength Assignment (ASYMMETRIC)
```
velocity > threshold (+0.000234 > +0.000150)
strategy_mode = trend_following

yes_signal_strength = 0.000234 / 0.000150 = 1.56
no_signal_strength = 0.0  # ZERO due to asymmetric logic
```

### Step 4: Edge Calculation
```
For YES side:
  price = 25 / 100.0 = 0.25
  edge_yes = 1.56 * (1.0 - 0.25) - 0.25 = 1.56 * 0.75 - 0.25 = 1.17 - 0.25 = 0.92

For NO side:
  price = 25 / 100.0 = 0.25
  edge_no = 0.0 * (1.0 - 0.25) - 0.25 = 0.0 - 0.25 = -0.25  # ZERO signal strength
```

### Step 5: Edge Selection
```
side_edges = {'yes': 0.92, 'no': -0.25}
signal_side = max(side_edges, key=side_edges.get) = 'yes'
```

### Step 6: Final Decision
```
Selected Side: YES
Selected Edge: 0.92
Market Price: $0.25
```

### Analysis of Trace
- **FAIL**: NO side edge is artificially low (-0.25) due to zero signal strength
- **FAIL**: Comparison is meaningless because one side is handicapped
- **FAIL**: System would never select NO side even if it had better true edge

---

## Example Trace: Momentum_FVG Strategy Decision Cycle

### Input State
```
Asset: BTC
Spot Price: $67,500.00
Velocity: +0.000234 (threshold: 0.000150)
MACD Histogram: +0.0045
RSI: 45.2 (neutral)
OBI: +0.12 (weak bullish)
FVG Direction: bullish
FVG Confidence: 0.65
```

### Step 1: Condition Evaluation
```
long_conditions = [
  velocity > threshold: True (+0.000234 > +0.000150)
  macd_histogram >= min_macd_hist_long: True (+0.0045 >= 0.0)
  rsi_zone != "overbought": True (neutral != overbought)
  rsi > momentum_rsi_long_min: True (45.2 > 30.0)
  (obi > 0 and obi_strong) or (fvg bullish): True (fvg bullish with 0.65 confidence)
]
long_score = 5

short_conditions = [
  velocity < -threshold: False (+0.000234 is not < -0.000150)
  macd_histogram < min_macd_hist_short: False (+0.0045 is not < 0.0)
  rsi_zone != "oversold": True (neutral != oversold)
  rsi < momentum_rsi_short_max: True (45.2 < 70.0)
  (obi < 0 and obi_strong) or (fvg bearish): False (fvg is bullish)
]
short_score = 2
```

### Step 2: Side Selection
```
long_score (5) >= 3 → SELECT YES
short_score (2) < 3 → NO NOT SELECTED
```

### Step 3: Edge Calculation (YES only)
```
edge_pct = calculate_velocity_edge(0.000234, 0.000150) = 2.0 (minimum)
edge_pct += abs(0.0045) * 10.0 = 2.0 + 0.045 = 2.045
edge_pct = min(2.045, 15.0) = 2.045
```

### Step 4: Final Decision
```
Selected Side: YES
Edge: 2.045%
Model Probability: 0.5 + (2.045 / 100.0) = 0.52045
```

### Analysis of Trace
- **FAIL**: NO side was never evaluated
- **FAIL**: No edge calculation for NO side
- **FAIL**: No comparison between YES and NO edges
- **FAIL**: Decision based on condition scores, not edge comparison

---

## Recommendations

### Immediate Actions Required

1. **Fix Standard Strategy Signal Strength Assignment**
   - Remove asymmetric signal strength assignment
   - Calculate signal strength for both sides independently
   - Use symmetric formula: `signal_strength = abs(velocity) / velocity_threshold` for both sides

2. **Implement True Dual-Side Evaluation in Momentum_FVG**
   - Remove conditional side selection based on scores
   - Calculate long_score and short_score for both sides
   - Calculate edges for both YES and NO
   - Select side with higher positive edge

3. **Add Edge Comparison Logic**
   - After calculating both edges, compare directly
   - Select side with higher positive edge
   - If both edges negative or below threshold → no trade

4. **Enhance Logging**
   - Log both YES and NO edges in all strategies
   - Log edge comparison decision
   - Log selected side with justification

### Code Changes Required

#### Fix 1: Standard Strategy Signal Strength (lines 4136-4151)
```python
# CURRENT (ASYMMETRIC):
if velocity > velocity_threshold:
    if strategy_mode == "trend_following":
        yes_signal_strength = velocity / velocity_threshold
        no_signal_strength = 0.0
    else:
        yes_signal_strength = 0.0
        no_signal_strength = velocity / velocity_threshold

# PROPOSED (SYMMETRIC):
signal_magnitude = abs(velocity) / velocity_threshold
yes_signal_strength = signal_magnitude
no_signal_strength = signal_magnitude
```

#### Fix 2: Momentum_FVG Dual-Side Evaluation (lines 2157-2201)
```python
# CURRENT (CONDITIONAL):
if long_score >= 3:
    signal_side = "yes"
elif short_score >= 3:
    signal_side = "no"

# PROPOSED (DUAL-SIDE):
# Calculate edges for both sides
edge_yes = calculate_edge_from_score(long_score, yes_price_cents)
edge_no = calculate_edge_from_score(short_score, no_price_cents)

# Select best edge
if edge_yes > edge_no and edge_yes > min_edge_threshold:
    signal_side = "yes"
elif edge_no > edge_yes and edge_no > min_edge_threshold:
    signal_side = "no"
else:
    return None  # No positive edge
```

---

## Conclusion

The system **FAILS** the dual-side evaluation audit. While price band enforcement is correctly implemented for both sides, the actual signal generation logic is fundamentally asymmetric:

1. **Momentum_FVG strategy** completely lacks dual-side evaluation - it uses conditional selection based on indicator scores
2. **Standard strategy** implements dual-side price filtering but assigns asymmetric signal strengths, making edge comparison meaningless
3. Neither strategy truly compares YES vs NO edges to select the best side
4. Edge calculations exist but are not used for comparison in the decision logic

**Root Cause**: The system was designed with directional signal generation (velocity-based momentum) rather than true dual-side edge comparison. The dual-side price filtering and logging infrastructure exists, but the core signal generation logic does not leverage it for actual decision-making.

**Impact**: The system may miss profitable opportunities on the side with better true edge because it never evaluates or compares both sides symmetrically. This violates the audit requirement that "the system must be consistently and correctly evaluating BOTH sides (YES and NO) of each contract and selecting the side with the strongest edge within the defined trading range."

---

**Audit Completed**: 2026-07-09  
**Status**: FAIL  
**Next Review**: After implementation of recommended fixes
