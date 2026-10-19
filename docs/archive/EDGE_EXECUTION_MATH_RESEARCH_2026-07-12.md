# Edge Execution Math Research: Binary Options with $1 Global Slot Allocation

**Date**: 2026-07-12  
**Objective**: Research optimal edge execution mathematics for binary contracts with limited capital ($1 global cap across 5 assets) and compare to current MERID implementation.

---

## Executive Summary

The research reveals significant gaps between MERID's current implementation and optimal mathematical frameworks for binary options trading under capital constraints. While MERID has a robust hard $1 cap, it lacks Kelly-based sizing, portfolio-level optimization, correlation handling, and confidence-weighted position sizing. Implementing these mathematical foundations could significantly improve risk-adjusted returns.

---

## Research Findings

### 1. Kelly Criterion for Binary Options

#### Single-Bet Kelly Formula
```
f* = (bp - q) / b
```

Where:
- `f*` = optimal fraction of bankroll to wager
- `b` = net decimal odds (for binary: `b = (1 - price) / price`)
- `p` = true probability of winning (model_prob)
- `q` = 1 - p = probability of losing

**Example for Prediction Markets**:
- Buy YES at $0.40, win profit $0.60 on $0.40 bet
- `b = 0.60 / 0.40 = 1.50`
- If `p = 0.60`, `q = 0.40`: `f* = (1.50 × 0.60 - 0.40) / 1.50 = 0.10` (10% of bankroll)

#### Fractional Kelly (Critical for Production)
Full Kelly maximizes growth but produces extreme drawdowns (60%+ in simulations). Fractional Kelly is recommended:

| Kelly Fraction | Growth Rate | Variance | Drawdown Reduction |
|--------------|-------------|----------|-------------------|
| Full (1.0) | 100% | 100% | 0% |
| Half (0.5) | 75% | 50% | 50% |
| Quarter (0.25) | 44% | 25% | 75% |

**Recommendation**: Use quarter-Kelly (k = 0.25) as default for autonomous agents. The marginal growth rate lost is small compared to drawdown reduction.

---

### 2. Portfolio Kelly for Multiple Simultaneous Bets

#### The Problem with Single-Bet Kelly
Cannot apply single-bet Kelly independently to multiple bets because:
1. **Budget constraint**: Sum of all positions cannot exceed bankroll
2. **Correlation effects**: Correlated bets compound risk
3. **Interaction effects**: Optimal size for Bet A depends on allocation to Bet B

#### Simultaneous Kelly Optimization
```
Maximize: Σ_i [p_i × log(1 + f_i × b_i) + q_i × log(1 - f_i)]
Subject to: Σ f_i ≤ 1 (total allocation cannot exceed bankroll)
           0 ≤ f_i ≤ f_max for all i (position limits)
```

For N binary events, there are 2^N possible joint outcomes. The expected log growth is:
```
G(f) = Σ P(s) × log(1 + Σ f_i × R_i(s))
```
Where `P(s)` is the probability of joint outcome state `s`, and `R_i(s)` is the return on bet `i` in state `s`.

This is a concave optimization problem (the log of a linear function is concave), so any local maximum is the global maximum. Standard convex optimization solvers can handle it efficiently.

#### Correlation Handling
Joint probabilities encode correlation information. For two bets with marginal probabilities p1, p2 and correlation ρ:
```
P(X1=1, X2=1) = p1p2 + ρ√(p1q1p2q2)
P(X1=1, X2=0) = p1q2 - ρ√(p1q1p2q2)
P(X1=0, X2=1) = q1p2 - ρ√(p1q1p2q2)
P(X1=0, X2=0) = q1q2 + ρ√(p1q1p2q2)
```

For larger portfolios, use a Gaussian copula:
1. Generate N correlated standard normal variables using the correlation matrix
2. Convert each to binary outcome: X_i = 1 if Z_i < Φ^(-1)(p_i), else X_i = 0

---

### 3. Binary Options Specific Challenges

#### Unfavorable Payout Structure
Most retail binary options pay 70-90% on wins while losses are 100%. This means you need a surprisingly high win rate just to break even:

```
p_break-even = 1 / (1 + b)
```

For 80% payout (b = 0.8): need ~55.6% accuracy just to break even. Any less than that, and trading costs money.

#### Estimation Error Sensitivity
Kelly is highly sensitive to estimation error. If you think your edge is 60% but it's actually 55%, full Kelly becomes dangerous and can rapidly destroy capital. Binary options amplify this because payouts are asymmetric and short-term variance is huge.

#### All-or-Nothing Volatility
Unlike stocks where partial adverse movement still leaves capital invested, binary options settle to either the fixed payout or the full stake loss. This creates larger drawdowns and higher psychological pressure.

---

### 4. Alternative Approaches

#### DEPO (Discrete Entropic Portfolio Optimization)
- Maximizes expected growth rate AND minimizes relative entropy
- Relative entropy measures distance from uniform distribution
- Uniform distribution = minimum risk portfolio for binary assets
- Outperforms Kelly criterion strategies in empirical tests

#### EPEL (Expected Profit and Expected Loss)
- Formulates as linear programming problem
- Maximizes EP subject to EL ≤ λ × EP (risk tolerance)
- Can handle both individual option evaluation and portfolio selection

---

## Current MERID Implementation

### Global Slot Allocator
**File**: `merid/risk/global_slot_allocator.py`

- **Fixed $1 exposure cap** across all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- **Slot-based allocation**: Each position consumes its entry price from the $1 cap
- **Price range**: 10-75c (expanded from 10-50c on 2026-07-12)
- **Max 1 contract per trade**
- **Sequential trading**: new entries blocked until $1 frees up
- **Re-entry allowed** when positions close (slot recycling)
- **Exit orders bypass** slot allocation

### Allocation Request
**File**: `merid/risk/global_slot_allocator.py` (lines 52-78)

```python
@dataclass
class AllocationRequest:
    agent_id: str
    asset: str
    ticker: str
    entry_price_cents: int
    edge_pct: float
    spread_cents: int
    confidence: float = 0.5  # Model confidence (0.0-1.0) for priority/tiebreaker
    is_exit_order: bool = False
```

**Key observation**: Confidence field exists but is only used for priority/tiebreaker, not for sizing.

### Unified Sizing
**File**: `merid/prediction/unified_sizing.py` (lines 751-839)

**Formula**:
1. Use fixed $1 exposure cap from profile
2. Check existing total exposure from slot allocator
3. Available exposure = $1 - existing_exposure
4. If available_exposure >= contract_cost, allow 1 contract
5. Otherwise, reject

**Key observation**: Binary (1 or 0 contracts) - no edge-based sizing.

### Loop 15m Edge Selection
**File**: `merid/loop_15m.py` (lines 1511-1522)

**Confidence-based dynamic edge threshold**:
```python
confidence = candidate.get("confidence", 0.5)
confidence_multiplier = 0.5 + (confidence * 1.5)  # Maps 0.0→0.5, 0.5→1.25, 1.0→2.0
min_edge_threshold = 0.0001 * confidence_multiplier
```

**Best-edge selection**: Execute if edge > min_threshold OR edge > current_best_edge

**Key observation**: Confidence affects execution threshold, not position size.

---

## Comparison: Research vs. MERID

### What MERID Does Well
1. **Hard capital constraint**: $1 cap prevents overexposure
2. **Slot recycling**: Efficient capital reuse when positions close
3. **Confidence integration**: Uses confidence for dynamic edge thresholding
4. **Exit order bypass**: Ensures positions can be closed without waiting
5. **Price range enforcement**: 10-75c canonical range

### Critical Gaps

#### Gap 1: No Kelly-Based Sizing
**Current**: Always 1 contract if price fits in remaining exposure  
**Research**: Should size based on edge, confidence, and odds  
**Impact**: May overbet on low-edge opportunities, underbet on high-edge opportunities

**Example**:
- MERID: 75c contract at $0.25 remaining exposure → 1 contract (100% of remaining)
- Kelly: If edge is small, should allocate fraction of remaining exposure

#### Gap 2: No Portfolio-Level Optimization
**Current**: Simple first-come-first-served allocation  
**Research**: Should optimize allocation across all 5 assets simultaneously  
**Impact**: May miss optimal portfolio construction, ignores correlations

**Example**:
- MERID: BTC signal arrives first → gets slot, ETH signal rejected
- Optimal: Should evaluate all 5 assets together, allocate to best combination

#### Gap 3: No Correlation Handling
**Current**: BTC, ETH, SOL, XRP, DOGE treated as independent  
**Research**: Crypto assets are highly correlated (especially BTC/ETH)  
**Impact**: Overexposure to correlated risk, suboptimal portfolio

**Example**:
- MERID: Can hold BTC and ETH simultaneously at full $1
- Optimal: Should reduce allocation when assets are correlated

#### Gap 4: Confidence Not Used for Sizing
**Current**: Confidence affects execution threshold, not position size  
**Research**: Confidence should directly influence bet size (Kelly)  
**Impact**: High-confidence bets not sized appropriately

**Example**:
- MERID: 0.9 confidence and 0.5 confidence both get 1 contract if price fits
- Optimal: 0.9 confidence should get larger allocation

#### Gap 5: No Fractional Kelly
**Current**: All-or-nothing allocation (1 or 0 contracts)  
**Research**: Should use fractional Kelly (quarter-Kelly recommended)  
**Impact**: Excessive volatility, suboptimal growth rate

**Example**:
- MERID: Either allocate full contract cost or nothing
- Optimal: Could allocate fraction of contract (if fractional contracts allowed)

#### Gap 6: No Odds Consideration
**Current**: Size based on price fitting in cap, not on expected value  
**Research**: Kelly uses odds (b = (1 - price) / price) directly  
**Impact**: Doesn't account for favorable/unfavorable odds

**Example**:
- MERID: 50c contract with 60% model_prob → 1 contract if space available
- Kelly: Should calculate b = (1-0.5)/0.5 = 1.0, then f* = (1.0×0.6-0.4)/1.0 = 0.20

---

## Recommendations

### Immediate (High Priority)

#### 1. Implement Kelly-Based Sizing
**Location**: `merid/prediction/unified_sizing.py`

```python
def calculate_kelly_fraction(model_prob: float, price_cents: int) -> float:
    """Calculate Kelly fraction for binary option."""
    price = price_cents / 100.0
    b = (1 - price) / price  # Net odds
    p = model_prob
    q = 1 - p
    kelly = (b * p - q) / b
    return max(0, kelly)  # No negative bets

# In compute_order_size:
kelly_fraction = calculate_kelly_fraction(model_prob, price_cents)
fractional_kelly = 0.25 * kelly_fraction  # Quarter-Kelly
max_contracts = int(fractional_kelly * available_exposure_usd / contract_cost_usd)
count = min(1, max_contracts)  # Cap at 1 for now
```

#### 2. Add Correlation Matrix
**Location**: New file `merid/risk/correlation_matrix.py`

```python
# Estimate correlations from historical spot price movements
# BTC-ETH correlation typically 0.7-0.9
# BTC-SOL correlation typically 0.6-0.8
# etc.

CORRELATION_MATRIX = {
    "BTC": {"BTC": 1.0, "ETH": 0.8, "SOL": 0.7, "XRP": 0.6, "DOGE": 0.5},
    "ETH": {"BTC": 0.8, "ETH": 1.0, "SOL": 0.7, "XRP": 0.6, "DOGE": 0.5},
    # ... etc
}
```

Apply correlation discount to Kelly allocations:
```python
correlation_discount = 1.0 - average_correlation_with_existing_positions
adjusted_kelly = kelly_fraction * correlation_discount
```

#### 3. Portfolio-Level Allocation
**Location**: `merid/risk/global_slot_allocator.py`

Instead of first-come-first-served, evaluate all pending requests together:

```python
def allocate_portfolio(self, requests: List[AllocationRequest]) -> Dict[str, bool]:
    """Optimize allocation across all assets simultaneously."""
    # Use scipy.optimize.minimize to maximize expected log growth
    # Subject to $1 cap and correlation constraints
    pass
```

### Medium Priority

#### 4. Confidence-Weighted Sizing
**Location**: `merid/prediction/unified_sizing.py`

```python
confidence_multiplier = 0.5 + (confidence * 1.5)  # 0.5 to 2.0
adjusted_kelly = fractional_kelly * confidence_multiplier
final_allocation = min(0.25, adjusted_kelly)  # Cap at 25%
```

#### 5. Dynamic Risk Adjustment
**Location**: `merid/risk/global_slot_allocator.py`

```python
# Reduce allocation during drawdowns
drawdown_multiplier = 1.0 - (current_drawdown_pct / 0.20)  # Reduce at 20% drawdown
final_allocation = base_allocation * drawdown_multiplier
```

### Long-Term (Research)

#### 6. DEPO Implementation
Consider discrete entropic portfolio optimization:
- Balances growth rate with relative entropy (diversification)
- May be more robust than Kelly for binary options
- Requires numerical optimization

#### 7. Monte Carlo Simulation
- Simulate portfolio performance with different allocation strategies
- Stress-test with historical data
- Validate assumptions about edge and correlations

---

## Proposed Mathematical Framework for MERID

### Kelly-Based Allocation Formula

For each asset i:
```python
p_i = model_prob  # From agent grid
market_price_i = price_cents / 100
b_i = (1 - market_price_i) / market_price_i  # Net odds
q_i = 1 - p_i
kelly_i = (b_i * p_i - q_i) / b_i
fractional_kelly_i = 0.25 * kelly_i  # Quarter-Kelly
```

### Portfolio Optimization

```python
Maximize: Σ_i [p_i × log(1 + f_i × b_i) + q_i × log(1 - f_i)]
Subject to: Σ f_i ≤ 1.0  # $1 cap
           0 ≤ f_i ≤ 0.25  # Max 25% per asset
           Correlation adjustments applied
```

### Confidence Integration

```python
confidence_multiplier = 0.5 + (confidence * 1.5)  # 0.5 to 2.0
adjusted_kelly_i = fractional_kelly_i * confidence_multiplier
final_allocation_i = min(0.25, adjusted_kelly_i)  # Cap at 25%
```

### Correlation Adjustment

```python
# Calculate average correlation with existing positions
existing_assets = [slot.asset for slot in self._slots.values()]
avg_correlation = mean([CORRELATION_MATRIX[asset][existing] for existing in existing_assets])
correlation_discount = 1.0 - (avg_correlation * 0.5)  # 50% correlation → 25% discount
final_allocation_i *= correlation_discount
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
1. Implement Kelly fraction calculation in `unified_sizing.py`
2. Add confidence-weighted sizing
3. Unit tests for Kelly calculations

### Phase 2: Correlation (Week 2)
1. Create correlation matrix module
2. Estimate correlations from historical data
3. Apply correlation discount to allocations
4. Integration tests

### Phase 3: Portfolio Optimization (Week 3-4)
1. Implement portfolio-level allocation in `global_slot_allocator.py`
2. Add numerical optimization (scipy.optimize.minimize)
3. Portfolio-level tests and simulations

### Phase 4: Validation (Week 5)
1. Monte Carlo simulations
2. Backtesting with historical data
3. A/B testing vs current implementation
4. Performance metrics and risk analysis

---

## Conclusion

MERID's current implementation provides a solid foundation with its hard $1 cap and slot-based allocation. However, significant improvements are possible by incorporating Kelly-based sizing, portfolio-level optimization, correlation handling, and confidence-weighted position sizing. These mathematical foundations are well-established in the literature and could substantially improve risk-adjusted returns.

The recommended approach is to implement these changes incrementally, starting with Kelly-based sizing (highest impact, lowest complexity) and progressing to portfolio-level optimization (highest impact, highest complexity). Each phase should be thoroughly tested before proceeding to the next.

---

## References

1. **Kelly Criterion**: Kelly, J. L. (1956). "A New Interpretation of Information Rate"
2. **Fractional Kelly**: MacLean, Thorp, Ziemba (2010). "The Kelly Capital Growth Investment Criterion"
3. **Portfolio Kelly**: Thorp (2008). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market"
4. **DEPO**: Mercurio et al. (2020). "Portfolio Optimization for Binary Options Based on Relative Entropy"
5. **Binary Options Money Management**: BinaryOptions.net (2026). "How to Trade Binary Options 8: Money Management & Probability"
6. **Prediction Markets**: Datafield.dev (2026). "Chapter 17: Portfolio Construction and Risk Management"
7. **Agent Kelly**: AgentBets.ai (2026). "The Kelly Criterion: Optimal Bet Sizing for Autonomous Agents"
