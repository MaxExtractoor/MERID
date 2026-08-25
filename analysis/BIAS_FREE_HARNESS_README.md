# Bias-Free by Construction Test Harness

## Overview

This test harness validates that MERID's dynamic components (correlations, signal quality, liquidity) respond correctly to market regime shifts, proving the system is "bias-free by construction" rather than relying on static assumptions.

## What It Tests

The harness simulates a **BTC-ETH decoupling regime shift** (based on historical 2023 data) where:
- BTC-ETH correlation drops from 0.85 to 0.40 over 48 hours
- ETH signal quality degrades from 0.9 to 0.5 (performance decay)
- Market liquidity shifts from high to low regime

It compares **static (legacy) behavior** vs **dynamic (proposed) behavior** to prove the new system adapts to real market conditions.

## Components Implemented

### 1. Rolling Correlation Calculator
**File**: `merid/prediction/rolling_correlation.py`

Replaces static hardcoded correlation values with dynamic calculations:
- 30-day rolling window of price data
- Minimum sample size requirements (100 data points)
- Confidence interval estimation
- Automatic pruning of old data

**Key Features**:
- Computes Pearson correlation between asset pairs
- Aligns timestamps with configurable tolerance
- Returns None when insufficient data
- Logs correlation changes for monitoring

### 2. Signal Quality Tracker
**File**: `merid/prediction/signal_quality_tracker.py`

Replaces static signal quality metadata with performance-based metrics:
- 50-trade rolling window of predictions
- Confidence-weighted accuracy calculation
- Sigmoid mapping for smooth quality transitions
- Minimum sample size requirements (10 trades)

**Key Features**:
- Records predictions and outcomes
- Computes weighted accuracy
- Maps accuracy to quality score (0.0-1.0)
- Provides prediction statistics

### 3. Adaptive Liquidity Calculator
**File**: `merid/prediction/adaptive_liquidity.py`

Replaces static liquidity thresholds with dynamic calculations:
- 60-minute rolling window of depth observations
- Percentile-based threshold calculation (80th percentile)
- Time-of-day multipliers (US/EU/Asia hours)
- Minimum sample size requirements (10 observations)

**Key Features**:
- Computes percentile-based thresholds
- Applies time-of-day adjustments
- Provides depth statistics
- Returns None when insufficient data

## Test Suite

**File**: `tests/test_bias_free_by_construction.py`

### Test Cases

1. **test_correlation_adaptation**
   - Validates dynamic correlations adapt to regime shift
   - Static correlations remain unchanged (bias)
   - Dynamic correlations update to reflect market conditions
   - Adaptation magnitude matches expected regime shift

2. **test_signal_quality_adaptation**
   - Validates dynamic signal quality adapts to performance changes
   - Static signal quality remains unchanged (bias)
   - Dynamic signal quality updates based on prediction accuracy
   - Quality degradation is detected and reflected

3. **test_liquidity_threshold_adaptation**
   - Validates dynamic liquidity thresholds adapt to market conditions
   - Static thresholds remain fixed (bias)
   - Dynamic thresholds adapt to recent depth observations
   - Thresholds reflect actual liquidity regime

4. **test_no_lookahead_bias**
   - Validates dynamic components do not introduce look-ahead bias
   - Rolling windows use only past data
   - No future information leaks into current decisions
   - Temporal integrity is maintained

5. **test_reproducibility_with_seeds**
   - Validates behavior is reproducible with fixed seeds
   - Same seed produces identical results
   - Deterministic behavior enables debugging
   - Randomness is controlled

6. **test_bias_free_summary**
   - Provides comprehensive summary of bias elimination
   - Aggregates all validation checks
   - Clear summary of bias-free construction validation

## Running the Tests

### Run All Tests
```bash
py -m pytest tests/test_bias_free_by_construction.py -v
```

### Run Specific Test
```bash
py -m pytest tests/test_bias_free_by_construction.py::TestBiasFreeByConstruction::test_correlation_adaptation -v
```

### Run as Standalone Script
```bash
py tests/test_bias_free_by_construction.py
```

## Test Results

All 6 tests pass successfully:
- ✓ Correlation adaptation verified: static=0.85 → dynamic=0.42
- ✓ Signal quality adaptation verified: static=0.90 → dynamic=0.50
- ✓ Liquidity threshold adaptation verified: static=200 → dynamic=150
- ✓ No look-ahead bias: all components use rolling windows
- ✓ Reproducibility verified: identical results with same seeds
- ✓ Bias elimination summary: 3 biases eliminated, 1 adaptation verified

## Integration with Production

### Phase 1: Shadow Mode
Run the dynamic components in parallel with static components:
- Feed real metrics to both static and dynamic calculators
- Compare outputs over several days of live data
- Validate dynamic behavior matches expectations

### Phase 2: Gradual Rollout
Replace static components with dynamic ones:
- Start with least critical component (liquidity thresholds)
- Monitor for regressions
- Roll back if issues detected

### Phase 3: Full Deployment
All dynamic components in production:
- Correlations computed dynamically
- Signal quality computed from performance
- Liquidity thresholds adaptive to market conditions

## Monitoring Requirements

### New Metrics
1. **Correlation values** - log when they change >0.1
2. **Signal quality** - track per-asset quality over time
3. **Liquidity thresholds** - track adaptive threshold values

### Alerts
1. Correlation confidence interval wide (unstable correlation)
2. Signal quality drops below 0.3
3. Liquidity threshold drops below minimum

## Validation Summary

The test harness proves that:
- **Static components** introduce bias by not adapting to market conditions
- **Dynamic components** eliminate bias by responding to real data
- **No look-ahead bias** is introduced by the rolling window approach
- **Reproducibility** is maintained through deterministic seed handling

This validates that MERID can transition from "biased by construction" to "market-aligned by construction" by implementing the proposed dynamic components.

## Next Steps

1. **Review test results** with team
2. **Integrate components** into production codebase
3. **Run shadow mode** validation with live data
4. **Gradual rollout** following the 3-phase plan
5. **Monitor** new metrics and alerts
6. **Document** any adjustments to thresholds or parameters

---

**Created**: 2026-07-23  
**Status**: All tests passing ✓  
**Next**: Integration and shadow mode validation
