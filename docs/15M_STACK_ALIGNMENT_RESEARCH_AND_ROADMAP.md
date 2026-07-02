# 15m Crypto Trading Stack Alignment Research & Implementation Roadmap

**Date**: 2026-06-24  
**Objective**: Align the 15m Kalshi crypto trading system with peer-reviewed best practices for short-horizon trading systems

---

## Executive Summary

Based on comprehensive research across academic and industrial trading system literature, the current 15m crypto trading system has a solid architectural foundation but requires alignment in the **model/probability layer** to match modern best practices. The main misalignment is that production code enforces a probability/edge-centric policy layer while the 15m agent uses a bare velocity heuristic with ad-hoc mappings into those quantities.

**Key Finding**: The system architecture is already well-structured with clean separation of concerns. The primary gap is in the **signal generation layer** where velocity is used as a heuristic without an explicit probability model.

**Recommended Approach**: Implement a minimal logistic mapping from velocity → probability/edge to make the 15m agent a "first-class model" that integrates cleanly with existing router invariants.

---

## 1. Research Findings: Best Practices Architecture

### 1.1 Standard Trading System Architecture

**Source**: Quant Trading Systems: Architecture & Infrastructure (Brenndoerfer)

**Standard Pipeline Stages**:
1. **Data Infrastructure**: Market data feeds, alternative data, historical storage
2. **Strategy Engine**: Model scoring → explicit probability/edge
3. **Portfolio/Risk Block**: Sizing, limits, risk management
4. **Execution/Routing**: Venue policies, order routing

**Design Principles**:
- **Separation of concerns**: Strategy engine shouldn't know how orders are routed
- **Determinism and reproducibility**: Same inputs → same outputs
- **Fail-safe defaults**: System assumes safest state when uncertain

**Current System Status**: ✅ ALIGNED
- Clean separation between data, strategy, risk, and execution layers
- Deterministic signal generation
- Fail-safe defaults in risk envelope

### 1.2 Model Interface Standards

**Expected Model Outputs** (per academic/industrial practice):
- `p_model ∈ (0,1)`: Predicted probability of YES outcome
- `edge_estimate`: Expected return or log-odds vs price
- `confidence/uncertainty`: Measure of prediction certainty
- `features_used`: For logging/audit (not routing)

**Router Contract** (standard practice):
- Price/probability consistency (`p_model` vs mid)
- Min edge, min confidence per strategy/profile
- Risk caps, per-symbol caps, no-lotto rules

**Current System Status**: ⚠️ PARTIALLY ALIGNED
- Router expects `model_prob`, `edge_pct`, `confidence` ✅
- 15m agent bypasses model layer with velocity heuristic ⚠️
- Ad-hoc mappings in loop rather than in signal generation ⚠️

---

## 2. Research Findings: Probability/Edge-Based Design

### 2.1 Black-Scholes for Prediction Markets

**Sources**: 
- SimpleFunctions: "From Black-Scholes to Binary Markets"
- DEV Community: "Black-Scholes on Polymarket"
- Alpha in Academia: "Prediction Market Trading"

**Key Insights**:
- **What Ports**: Risk-neutral pricing framework applies to prediction markets
  - Market price = risk-neutral probability (modulo small rate adjustment)
  - First fundamental theorem of asset pricing holds (no arbitrage)
- **What Does Not Port**: Vol surface machinery
  - No underlying continuous price to be volatile against
  - No σ to fit from traditional options
  - Binary contracts have events, not continuous paths

**Implication for 15m System**:
- Current approach of using market price as `model_prob` is **fundamentally incorrect**
- Market price is the crowd's estimate, not the model's estimate
- Need explicit model that produces `p_model` independent of market price
- Edge = `p_model - p_mkt` (difference between model and market)

### 2.2 Kalshi Market Calibration

**Source**: CW Data Solutions: "Calibration and Skill of Kalshi Prediction Markets"

**Key Findings**:
- Kalshi markets show Brier Skill Score (BSS) ranging from 0.25 to 0.62
- Predictive skill improves as market approaches close (more information)
- Markets are not perfectly calibrated → investment opportunities exist
- Base event rate across 8,476 markets: 28.7%

**Implication for 15m System**:
- Market prices are noisy and not perfectly calibrated
- Opportunity exists for models to outperform crowd consensus
- Need calibration over time (Platt scaling, isotonic regression)

---

## 3. Research Findings: Velocity-Based Models

### 3.1 Velocity as a Trading Signal

**Source**: Trinity Logic: "Price Velocity and Market Momentum"

**Key Insights**:
- Velocity = rate of change of Last Traded Price over fixed time window
- Positive velocity = price shortening (steam), negative = lengthening (drift)
- Velocity is a **lagging signal** (price has already moved before you act)
- Best used in combination with leading indicators (Weight of Money, order book pressure)
- Thresholds depend on market type and time to expiry
- Window size matters: 30s for 2-5 min before off, 15s closer to off
- Filter by minimum matched volume to avoid noise in thin markets

**Current System Status**: ⚠️ PARTIALLY ALIGNED
- Uses 1-minute velocity from Coinbase ✅
- No volume filtering ⚠️
- Fixed window size (no adaptation to time to expiry) ⚠️
- Used alone without leading indicators ⚠️

### 3.2 Momentum & Mean Reversion (Polymarket Bot)

**Source**: Polymarket Bot Documentation

**Architecture**:
- **Momentum (ROC)**: Rate of change across 10s, 30s, 60s windows
- **Mean Reversion**: Deviation from 2-minute SMA
- **Logit-Space Fusion**: Combine signals via logit arithmetic
- **Platt Calibration**: Post-hoc probability recalibration

**Multi-Window Combination**:
```
ROC_combined = 0.5 * ROC_10s + 0.3 * ROC_30s + 0.2 * ROC_60s
```

**Logit-Space Fusion**:
```
logit_adj = logit(base_prob) + 
            weight_momentum * momentum_factor + 
            weight_reversion * reversion_factor
final_prob = sigmoid(logit_adj)
```

**Implication for 15m System**:
- Current single-window velocity is too simple
- Multi-window momentum would improve signal quality
- Logit-space fusion is mathematically sound for probability combination
- Platt calibration should be added for probability refinement

---

## 4. Research Findings: Probability Calibration

### 4.1 Platt Scaling

**Sources**: 
- MQL5: "Probability Calibration for Financial Machine Learning"
- Wikipedia: "Platt scaling"
- Scientific papers on Platt scaling appropriateness

**Key Insights**:
- Platt scaling fits logistic regression to classifier scores
- Maps raw scores to calibrated probabilities via sigmoid
- Formula: `p_calibrated = sigmoid(A * p_raw + B)`
- Parameters A, B learned via maximum likelihood
- **Preferred when**: Calibration dataset is small (<200 observations)
- **Assumes**: Log-linear miscalibration (sigmoidal distortion)
- **Alternative**: Isotonic regression for larger datasets (>200 obs)

**Online Platt Scaling**:
- Combines Platt scaling with online logistic regression
- Adapts between i.i.d. and non-i.i.d. settings with distribution drift
- Guaranteed calibration for adversarial outcome sequences

**Implication for 15m System**:
- Should implement Platt scaling for probability calibration
- Start with offline calibration, move to online as data accumulates
- Use isotonic regression once 200+ prediction/outcome pairs available

### 4.2 Calibration Metrics

**Key Metrics**:
- **Brier Score**: Mean squared error of predicted probabilities
- **Expected Calibration Error (ECE)**: Weighted average of calibration errors
- **Maximum Calibration Error (MCE)**: Worst calibration error across bins

**Best Practice**:
- Track calibration metrics continuously
- Use out-of-fold predictions to avoid temporal leakage
- Purge and embargo data to prevent look-ahead bias

---

## 5. Research Findings: Router/Risk Layer Design

### 5.1 Pre-Trade Risk Checks

**Source**: Quant Trading Systems Architecture

**Standard Pre-Trade Checks**:
- Position limits (per symbol, per portfolio)
- Exposure limits (notional, Greeks)
- Liquidity checks (minimum depth, volume)
- Price bands (prevent extreme prices)
- Circuit breakers (halt on anomalies)

**Current System Status**: ✅ WELL ALIGNED
- Comprehensive pre-trade checks in `route_order_async`
- Risk envelope with per-asset caps
- Liquidity filters (depth, volume)
- Price band restrictions (48-52c for standard strategies)

### 5.2 Strategy-Specific Policies

**Best Practice**: Allow per-strategy policy overrides
- Different strategies may have different risk tolerances
- Heuristic strategies may need relaxed invariants
- Model-based strategies may enforce strict prob/edge consistency

**Current System Status**: ⚠️ NEEDS ALIGNMENT
- Router uses `caller_module` as hidden switch (not explicit)
- No clear strategy ID in `OrderIntent`
- Strategy-specific policies not formalized

---

## 6. Research Findings: Model-Based vs Heuristic Strategies

### 6.1 Heuristic Strategies

**Characteristics**:
- Rule-based, often simple thresholds
- Fast to implement and understand
- Limited adaptability to market conditions
- Hard to calibrate systematically
- Often lack explicit probability estimates

**When Appropriate**:
- Rapid prototyping
- Markets with limited data
- Simple, stable regimes
- As baseline for comparison

### 6.2 Model-Based Strategies

**Characteristics**:
- Explicit probability/edge estimates
- Calibrated outputs
- Systematic improvement possible
- Better integration with risk layer
- Clearer attribution of performance

**When Appropriate**:
- Production systems
- Markets with sufficient data
- Complex regimes
- When regulatory/compliance requirements exist

**Current System Status**: ⚠️ HYBRID (needs clarification)
- 15m agent is heuristic (velocity-based)
- Router expects model-based (prob/edge/confidence)
- Mismatch causes friction and potential invariants violations

---

## 7. Current System vs Best Practices Gap Analysis

### 7.1 Architecture Layer

| Component | Best Practice | Current System | Gap |
|-----------|---------------|----------------|-----|
| Data Infrastructure | Clean separation, validated storage | ✅ KalshiVenueClient, market state store | None |
| Strategy Engine | Explicit probability/edge model | ⚠️ Velocity heuristic with ad-hoc mapping | **High** |
| Risk Layer | Profile-driven, consistent | ✅ RiskEnvelopeService | None |
| Execution Layer | Venue policies, smart routing | ✅ order_router.py | None |
| Monitoring | Telemetry, logging | ✅ pipeline_telemetry.py | None |

### 7.2 Signal Generation Layer

| Aspect | Best Practice | Current System | Gap |
|--------|---------------|----------------|-----|
| Model Output | `p_model`, `edge`, `confidence` | ⚠️ `velocity` only, mapped in loop | **High** |
| Probability Source | Model prediction | ⚠️ Market price (incorrect) | **High** |
| Edge Definition | `p_model - p_mkt` | ⚠️ `abs(velocity) * 100` | **High** |
| Confidence | Distance from 0.5, uncertainty | ⚠️ `0.50 + abs(velocity) * 100` | **Medium** |
| Calibration | Platt/isotonic scaling | ❌ None | **High** |
| Signal Fusion | Logit-space combination | ❌ Single window only | **Medium** |

### 7.3 Router Layer

| Aspect | Best Practice | Current System | Gap |
|--------|---------------|----------------|-----|
| Strategy ID | Explicit strategy identifier | ⚠️ Uses `caller_module` as switch | **Medium** |
| Prob/Edge Checks | Required for model-based | ✅ Implemented | None |
| Strategy Overrides | Per-strategy policy relaxations | ⚠️ Hidden via caller_module | **Medium** |
| Regime Propagation | Carry regime from signal | ⚠️ Recomputed in loop | **Low** |

---

## 8. Implementation Roadmap

### Phase 1: Minimal Model Layer (Immediate - Week 1)

**Objective**: Make 15m agent a first-class model with explicit probability/edge

**Changes Required**:

1. **Add Logistic Mapping to `_generate_signal`**
   ```python
   # In LeanAgent15m._generate_signal
   
   # Current market probability (from mid price)
   mid_cents = (best_bid + best_ask) // 2 if best_bid and best_ask else 50
   p_mkt = mid_cents / 100.0
   
   # Logistic mapping from velocity to model probability
   # Coefficients from profile (per-asset)
   alpha_0 = self.config.alpha_0  # Intercept
   alpha_1 = self.config.alpha_1  # Velocity coefficient
   raw = alpha_0 + alpha_1 * velocity
   p_model = 1.0 / (1.0 + math.exp(-raw))
   
   # Edge as difference between model and market
   edge_pct = (p_model - p_mkt) * 100.0
   
   # Confidence as distance from 0.5
   confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
   
   signal.update({
       "model_prob": p_model,
       "edge_pct": edge_pct,
       "confidence": confidence,
   })
   ```

2. **Add Coefficients to Profile**
   ```yaml
   # config/profiles/kalshi_crypto_15m_v2.yaml
   
   velocity_model:
     BTC:
       alpha_0: 0.0
       alpha_1: 50.0  # Sensitivity to velocity
     ETH:
       alpha_0: 0.0
       alpha_1: 50.0
     SOL:
       alpha_0: 0.0
       alpha_1: 40.0  # Higher volatility → lower sensitivity
     XRP:
       alpha_0: 0.0
       alpha_1: 40.0
     DOGE:
       alpha_0: 0.0
       alpha_1: 30.0  # Highest volatility → lowest sensitivity
   ```

3. **Remove Ad-Hoc Mappings from Loop**
   - Remove `edge_pct = abs(velocity) * 100` from loop
   - Remove `confidence = 0.50 + abs(velocity) * 100` from loop
   - Remove `model_prob = price_cents / 100.0` from loop
   - Use values from candidate dict directly

4. **Tune Profile Thresholds**
   ```yaml
   # Lower min_edge for velocity-based model
   strategy_policy_min_edge: 0.3  # 0.3% (was 0.5%)
   
   # Lower min_confidence for initial model
   strategy_policy_min_confidence: 0.55  # 55% (was 60%)
   ```

**Expected Outcome**:
- Router invariants work correctly with explicit model probability
- Edge is genuine (model vs market, not scaled feature)
- System aligned with best practices
- Minimal code changes (isolated to signal generation)

### Phase 2: Multi-Window Momentum (Week 2-3)

**Objective**: Improve signal quality with multi-timeframe momentum

**Changes Required**:

1. **Add Multi-Window Velocity Calculation**
   ```python
   # In LeanAgent15m.__init__
   self._velocity_windows = [10, 30, 60]  # seconds
   self._velocity_history = {
       window: collections.deque(maxlen=window)
       for window in self._velocity_windows
   }
   
   # In _generate_signal
   velocities = []
   for window in self._velocity_windows:
       if len(self._velocity_history[window]) >= 2:
           recent = list(self._velocity_history[window])[-2:]
           vel = (recent[1] - recent[0]) / window
           velocities.append(vel)
   
   # Combine with weights
   velocity = 0.5 * velocities[0] + 0.3 * velocities[1] + 0.2 * velocities[2]
   ```

2. **Add Mean Reversion Signal**
   ```python
   # Calculate 2-minute SMA
   sma_window = 120  # 2 minutes at 1-second intervals
   if len(self._spot_price_history[asset]) >= sma_window:
       prices = list(self._spot_price_history[asset])[-sma_window:]
       sma = sum(prices) / len(prices)
       current_price = prices[-1]
       deviation = (current_price - sma) / sma
   
       # Mean reversion signal (opposes deviation)
       if abs(deviation) > 0.003:  # 0.3% threshold
           reversion_signal = -np.sign(deviation)
       else:
           reversion_signal = 0.0
   ```

3. **Logit-Space Fusion**
   ```python
   # Combine momentum and reversion in logit space
   logit_p_mkt = math.log(p_mkt / (1 - p_mkt))
   
   momentum_weight = 2.0  # From profile
   reversion_weight = 1.5  # From profile
   
   logit_adj = logit_p_mkt + momentum_weight * velocity + reversion_weight * reversion_signal
   p_model = 1.0 / (1.0 + math.exp(-logit_adj))
   ```

**Expected Outcome**:
- More robust signal from multiple timeframes
- Better signal-to-noise ratio
- Improved probability estimates

### Phase 3: Probability Calibration (Week 4-5)

**Objective**: Add Platt scaling for probability calibration

**Changes Required**:

1. **Implement Platt Scaler**
   ```python
   # merid/risk/probability/platt_scaler.py
   
   class PlattScaler:
       def __init__(self):
           self.A = 0.0
           self.B = 0.0
           self.fitted = False
           self.samples = []
       
       def add_sample(self, p_raw, outcome):
           self.samples.append((p_raw, outcome))
       
       def fit(self):
           if len(self.samples) < 50:
               return
           # Fit logistic regression via maximum likelihood
           # p_calibrated = sigmoid(A * p_raw + B)
           from sklearn.linear_model import LogisticRegression
           X = np.array([p for p, _ in self.samples]).reshape(-1, 1)
           y = np.array([outcome for _, outcome in self.samples])
           model = LogisticRegression()
           model.fit(X, y)
           self.A = model.coef_[0][0]
           self.B = model.intercept_[0]
           self.fitted = True
       
       def calibrate(self, p_raw):
           if not self.fitted:
               return p_raw
           logit = self.A * p_raw + self.B
           return 1.0 / (1.0 + math.exp(-logit))
   ```

2. **Integrate into Signal Generation**
   ```python
   # In LeanAgent15m
   def __init__(self, ...):
       self._platt_scaler = PlattScaler()
   
   def _generate_signal(self, ...):
       # ... compute p_model ...
       
       # Calibrate if enough samples
       if self._platt_scaler.fitted:
           p_model = self._platt_scaler.calibrate(p_model)
       
       # Clamp to [0.01, 0.99]
       p_model = max(0.01, min(0.99, p_model))
   ```

3. **Add Outcome Recording**
   ```python
   # After market resolution
   def record_outcome(self, ticker, p_predicted, actual_outcome):
       self._platt_scaler.add_sample(p_predicted, actual_outcome)
       if len(self._platt_scaler.samples) >= 50 and not self._platt_scaler.fitted:
           self._platt_scaler.fit()
   ```

**Expected Outcome**:
- Better calibrated probabilities over time
- Improved expected value calculations
- Systematic improvement from data

### Phase 4: Strategy-Specific Policies (Week 6)

**Objective**: Formalize heuristic vs model-based strategy handling

**Changes Required**:

1. **Add Strategy ID to OrderIntent**
   ```python
   # In _execute_candidate
   intent = OrderIntent(
       ...
       strategy_id="kalshi_15m_velocity_v1",  # Explicit ID
       strategy_type="heuristic_velocity",  # Type for router logic
   )
   ```

2. **Update Router to Use Strategy ID**
   ```python
   # In route_order_async
   if intent.strategy_type == "heuristic_velocity":
       # Relaxed invariants for heuristic strategies
       # Skip strict prob/edge consistency checks
       # Use only velocity and risk envelope limits
       pass
   elif intent.strategy_type == "model_based":
       # Full invariants for model-based strategies
       # Require prob/edge/confidence semantics
       pass
   ```

3. **Add Strategy-Specific Price Band**
   ```yaml
   # config/profiles/kalshi_crypto_15m_v2.yaml
   
   strategies:
     kalshi_15m_velocity_v1:
       type: heuristic_velocity
       price_band:
         min_cents: 40  # Allow 40-60c range
         max_cents: 60
       min_edge: 0.2  # Lower edge threshold
       min_confidence: 0.50  # Lower confidence threshold
   ```

**Expected Outcome**:
- Clear separation between heuristic and model-based strategies
- Explicit strategy policies in configuration
- Router logic more maintainable

### Phase 5: Regime Propagation (Week 7)

**Objective**: Propagate regime from signal to policies/router

**Changes Required**:

1. **Add Regime to Candidate**
   ```python
   # In collect_order_candidate
   regime = self._classify_market_state(market_state)
   candidate["regime"] = regime
   ```

2. **Propagate Through Loop**
   ```python
   # In _execute_candidate
   regime = candidate.get("regime", "unknown")
   intent.regime = regime
   ```

3. **Use in Policies**
   ```python
   # In resolve_window_policy
   def resolve_window_policy(regime, ...):
       if regime == "one_sided_yes":
           # Adjust window for one-sided markets
           pass
   ```

**Expected Outcome**:
- Consistent regime classification across components
- No recomputation in downstream layers
- Better alignment between agent and router

---

## 9. Coefficient Calibration Strategy

### 9.1 Initial Coefficients (Heuristic)

Start with reasonable defaults based on research:

```yaml
velocity_model:
  BTC:
    alpha_0: 0.0
    alpha_1: 50.0  # Moderate sensitivity
  ETH:
    alpha_0: 0.0
    alpha_1: 50.0
  SOL:
    alpha_0: 0.0
    alpha_1: 40.0  # Lower sensitivity for higher volatility
  XRP:
    alpha_0: 0.0
    alpha_1: 40.0
  DOGE:
    alpha_0: 0.0
    alpha_1: 30.0  # Lowest sensitivity for highest volatility
```

### 9.2 Calibration Process

1. **Collect Data** (Week 1-2)
   - Log velocity, price, outcomes for all trades
   - Minimum 100 samples per asset

2. **Fit Logistic Regression** (Week 3)
   ```python
   from sklearn.linear_model import LogisticRegression
   
   # X: velocity values
   # y: binary outcomes (1 if YES, 0 if NO)
   model = LogisticRegression()
   model.fit(X.reshape(-1, 1), y)
   
   alpha_0 = model.intercept_[0]
   alpha_1 = model.coef_[0][0]
   ```

3. **Validate** (Week 4)
   - Check calibration metrics (Brier score, ECE)
   - Validate on out-of-sample data
   - Adjust if overfitting

4. **Iterate** (Ongoing)
   - Recalibrate monthly or on regime change
   - Use online Platt scaling for continuous adaptation

---

## 10. Risk Mitigation

### 10.1 Implementation Risks

| Risk | Mitigation |
|------|------------|
| Wrong coefficients cause poor performance | Start with conservative thresholds, extensive backtesting |
| Model overfits to historical data | Use out-of-sample validation, regular calibration |
| Probability miscalibration | Implement Platt scaling, track calibration metrics |
| Strategy ID confusion | Clear documentation, explicit type checking |
| Regime misclassification | Validate regime logic, add logging |

### 10.2 Rollback Plan

If Phase 1 causes issues:
1. Revert to current velocity-based logic
2. Keep ad-hoc mappings in loop as fallback
3. Disable new model probability checks in router
4. Investigate logs to identify root cause

---

## 11. Success Metrics

### 11.1 Calibration Metrics

- **Brier Score**: Target < 0.25 (current Kalshi baseline)
- **Expected Calibration Error (ECE)**: Target < 10%
- **Maximum Calibration Error (MCE)**: Target < 20%

### 11.2 Trading Metrics

- **Candidate→Order Conversion Rate**: Monitor changes
- **Top Rejection Reasons**: Should shift from "edge/confidence" to other factors
- **Sharpe Ratio**: Target improvement over baseline
- **Max Drawdown**: Should not increase

### 11.3 System Metrics

- **Router Invariant Violations**: Should decrease
- **Strategy Consistency**: Clear separation between strategies
- **Telemetry Quality**: Better signal attribution

---

## 12. Timeline Summary

| Phase | Duration | Priority | Dependencies |
|-------|----------|----------|--------------|
| Phase 1: Minimal Model Layer | Week 1 | **Critical** | None |
| Phase 2: Multi-Window Momentum | Week 2-3 | High | Phase 1 |
| Phase 3: Probability Calibration | Week 4-5 | High | Phase 1 |
| Phase 4: Strategy-Specific Policies | Week 6 | Medium | Phase 1 |
| Phase 5: Regime Propagation | Week 7 | Low | Phase 1 |

**Total Timeline**: 7 weeks

**Critical Path**: Phase 1 → Phase 2 → Phase 3

**Parallel Work**: Phase 4 and 5 can be done in parallel with Phase 2-3

---

## 13. Conclusion

The research confirms that the current 15m crypto trading system has a solid architectural foundation that aligns with best practices in most areas. The primary gap is in the **signal generation layer** where velocity is used as a heuristic without an explicit probability model.

The recommended approach is to implement a **minimal logistic mapping** from velocity to probability/edge, which will:

1. Make the 15m agent a "first-class model" that integrates cleanly with existing router invariants
2. Enable all existing probability/edge-based risk checks to work correctly
3. Provide a clear path for future model improvements (multi-window momentum, calibration)
4. Align the system with peer-reviewed best practices

This approach requires minimal code changes (isolated to signal generation) and can be implemented incrementally, with each phase providing value and reducing risk.

---

**Next Steps**:
1. Review and approve this roadmap
2. Begin Phase 1 implementation
3. Set up telemetry to track success metrics
4. Iterate based on results
