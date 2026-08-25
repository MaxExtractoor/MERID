# Spread Cap Calibration Plan

## Overview

This document outlines the data-driven calibration strategy for spread caps in 15-minute Kalshi crypto markets. The goal is to set realistic caps that:
- Reject obvious garbage books
- Preserve most maker-intended positive-edge opportunities
- Keep reject rates stable across the 15-minute window

## Calibration Framework

### 1. Asset-Specific Base Caps

Each asset gets a base cap reflecting its liquidity characteristics:

| Asset | Liquidity Profile | Base Cap Strategy | Target 90th Percentile |
|-------|------------------|-------------------|----------------------|
| **BTC** | Highest liquidity, tightest spreads | Strictest caps | 15-20c |
| **ETH** | High liquidity, slightly wider than BTC | Strict caps | 18-25c |
| **SOL** | Moderate liquidity, regime-sensitive | Moderate caps | 25-35c |
| **XRP** | Moderate liquidity, thin books | Moderate caps | 30-40c |
| **DOGE** | Lowest liquidity, highest volatility | Loosest caps | 40-60c |

### 2. Time-Bucket Adjustments

Spread behavior varies significantly by time-to-expiry:

```python
TIME_BUCKET_MULTIPLIERS = {
    "0-3min": 1.5,    # Market open: high volatility, widest spreads
    "3-6min": 1.2,    # Early window: elevated spreads
    "6-10min": 1.0,   # Mid window: normal trading, tightest spreads
    "10-13min": 1.1,  # Late window: spreads begin to widen
    "13-15min": 1.8,  # Near expiry: highest volatility, extreme spreads
}
```

**Dynamic Cap Formula:**
```
effective_cap = base_cap * time_bucket_multiplier * volatility_adjustment
```

### 3. Empirical Reject-Rate Targets

Target reject rates per asset based on historical quality:

| Asset | Target Reject Rate | Rationale |
|-------|-------------------|-----------|
| **BTC** | 5-10% | High-quality books, can afford strict filtering |
| **ETH** | 8-12% | Good quality, slightly looser than BTC |
| **SOL** | 12-18% | Moderate quality, need more flexibility |
| **XRP** | 15-20% | Lower quality, higher tolerance for wider spreads |
| **DOGE** | 20-25% | Lowest quality, maximum flexibility |

### 4. Maker vs Taker Evaluation

Separate evaluation paths:

**Maker Economics:**
- No spread cost (resting orders)
- No taker fee
- Can tolerate tighter caps
- Target: Preserve 95%+ of maker opportunities

**Taker Economics:**
- Full spread cost
- Taker fee applies
- Need looser caps to account for costs
- Target: Preserve 80-90% of taker opportunities

## Replay Analysis Plan

### Phase 1: Data Collection

**Duration:** 7 days of active trading (or 100+ market windows per asset)

**Sample Rate:** 1 sample per second per active ticker

**Data Points per Sample:**
- Timestamp
- Asset/ticker
- Time-to-expiry
- Yes bid/ask
- No bid/ask
- Canonical spread
- Model edge (if available)
- Order side (YES/NO)
- Economics mode (maker/taker)

### Phase 2: Distribution Analysis

For each asset, compute:

**Overall Statistics:**
- Min, max, median spread
- 25th, 50th, 75th, 90th, 95th, 99th percentiles
- Mean and standard deviation
- Spread distribution histogram

**Time-Bucket Analysis:**
- Same statistics per time bucket
- Identify buckets with extreme spread behavior
- Calculate time-bucket multipliers

**Volatility Regime Analysis:**
- Identify high-volatility periods
- Calculate volatility adjustment factors
- Detect regime shifts (especially for SOL, XRP, DOGE)

### Phase 3: Reject Rate Simulation

For each asset, test cap levels:

**Test Range:** 50% to 200% of current cap in 10% increments

**Metrics per Cap Level:**
- Total candidates
- Rejected count
- Reject rate
- False reject count (would have had positive edge)
- False reject rate
- Missed edge sum (total edge lost)
- Preserved maker opportunities
- Preserved taker opportunities

**Maker vs Taker Breakdown:**
- Separate reject rates for maker orders
- Separate reject rates for taker orders
- Edge preservation by economics mode

### Phase 4: Cap Selection

**Decision Criteria:**

1. **Reject Rate Target:**
   - Select cap that achieves target reject rate
   - Prefer cap slightly above target if close to threshold

2. **False Reject Minimization:**
   - Among caps meeting reject rate target, minimize false rejects
   - Weight false rejects by edge magnitude

3. **Time-Bucket Stability:**
   - Ensure reject rates are stable across time buckets
   - Reject caps that cause extreme variance (e.g., 5% in mid-window, 40% at expiry)

4. **Maker Preservation:**
   - Ensure >95% of maker opportunities preserved
   - Maker caps can be tighter than taker caps

5. **Volatility Robustness:**
   - Test caps against high-volatility periods
   - Ensure caps don't fail during regime shifts

**Selection Algorithm:**

```python
def select_optimal_cap(asset, analysis):
    # Step 1: Filter caps meeting reject rate target
    target_rate = ASSET_TARGET_REJECT_RATES[asset]
    viable_caps = [c for c in analysis.cap_analysis 
                   if c.reject_rate <= target_rate]
    
    # Step 2: Among viable, minimize false rejects
    optimal = min(viable_caps, key=lambda c: c.false_reject_rate)
    
    # Step 3: Check time-bucket stability
    if not is_stable_across_buckets(optimal, analysis):
        # Adjust to more conservative cap
        optimal = adjust_for_stability(optimal, analysis)
    
    # Step 4: Verify maker preservation
    if optimal.maker_preservation < 0.95:
        # Tighten maker cap separately
        optimal.maker_cap = tighten_maker_cap(optimal)
    
    # Step 5: Volatility robustness check
    if not robust_to_volatility(optimal, analysis):
        # Add volatility buffer
        optimal.cap *= 1.2
    
    return optimal
```

## Implementation Plan

### Step 1: Enhanced Data Collection

Modify `SpreadDataCollector` to capture:
- Model edge data
- Order side
- Economics mode (maker/taker)
- Volatility metrics

### Step 2: Advanced Analyzer

Extend `SpreadDistributionAnalyzer` with:
- Volatility regime detection
- Maker vs taker separation
- Time-bucket stability scoring
- False reject edge weighting

### Step 3: Calibration Engine

Create `SpreadCapCalibrator` module:
- Implements selection algorithm
- Generates calibration reports
- Produces cap recommendations
- Validates against historical data

### Step 4: Dynamic Cap System

Implement time-bucket adjustment:
- Real-time cap calculation based on time-to-expiry
- Volatility adjustment based on recent spread variance
- Separate maker vs taker caps

### Step 5: Validation & Monitoring

Add continuous monitoring:
- Track actual reject rates vs targets
- Alert on regime shifts
- Periodic recalibration (weekly)
- A/B testing framework for cap changes

## Calibration Output Format

### Per-Asset Report

```json
{
  "asset": "BTC",
  "base_cap_cents": 18.0,
  "time_bucket_caps": {
    "0-3min": 27.0,
    "3-6min": 21.6,
    "6-10min": 18.0,
    "10-13min": 19.8,
    "13-15min": 32.4
  },
  "maker_cap_cents": 15.0,
  "taker_cap_cents": 18.0,
  "target_reject_rate": 0.08,
  "expected_reject_rate": 0.075,
  "expected_false_reject_rate": 0.015,
  "maker_preservation_rate": 0.96,
  "taker_preservation_rate": 0.88,
  "time_bucket_stability_score": 0.92,
  "volatility_robustness_score": 0.89,
  "calibration_confidence": "HIGH"
}
```

### Summary Dashboard

```
SPREAD CAP CALIBRATION SUMMARY
==============================

BTC: 18c base (27c at open, 32c at expiry) | 7.5% reject rate | 96% maker preserved
ETH: 22c base (33c at open, 40c at expiry) | 9.2% reject rate | 95% maker preserved
SOL: 30c base (45c at open, 54c at expiry) | 14.8% reject rate | 94% maker preserved
XRP: 35c base (53c at open, 63c at expiry) | 17.5% reject rate | 93% maker preserved
DOGE: 50c base (75c at open, 90c at expiry) | 22.1% reject rate | 92% maker preserved

Overall: All caps meet stability and robustness criteria
Next calibration: 2026-08-09
```

## Success Criteria

A calibration is successful when:

1. **Reject Rate Targets Met:** Each asset achieves its target reject rate ±2%
2. **False Rejects Minimized:** False reject rate < 2% for all assets
3. **Maker Preservation:** >95% of maker opportunities preserved
4. **Time-Bucket Stability:** Reject rate variance < 5% across buckets
5. **Volatility Robustness:** Caps work during high-volatility periods
6. **No Regime Failures:** Caps handle regime shifts (especially SOL, XRP, DOGE)

## Next Steps

1. **Run Phase 1 collection** during next 7 days of active trading
2. **Implement Phase 2-3 analysis** once sufficient data collected
3. **Generate Phase 4 recommendations** using calibration engine
4. **Implement dynamic cap system** with time-bucket adjustments
5. **Deploy with monitoring** and validate against targets
6. **Schedule weekly recalibration** to adapt to market changes

## References

- [Kalshi Market Integrity - Prediction Markets 101](https://kalshi.com/market-integrity/prediction-markets-101)
- [Moltbook - Kalshi Crypto Prediction Markets](https://moltbook.com/post/70f293e0-b887-410b-a9cc-fafa6bd9083a)
- [CEPR - Economics of Kalshi Prediction Market](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market)
