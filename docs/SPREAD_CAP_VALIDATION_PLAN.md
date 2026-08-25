# Spread Cap Validation Plan

## Overview

**Temporary bridge → Data-driven calibration.** The cap increases are a temporary measure to restore trading. We must validate with actual spread distribution replay before finalizing the caps.

## Current State

### Temporary Bridge Caps (Deployed August 2, 2026)

| Asset | Previous | Temporary Bridge | Expected Reject Rate |
|-------|----------|------------------|---------------------|
| **BTC** | 10c | 20c | ~3-5% |
| **ETH** | 12c | 24c | ~8-10% |
| **SOL** | 20c | 40c | ~5-7% |
| **XRP** | 20c | 40c | ~7-9% |
| **DOGE** | 30c | 60c | ~9-11% |

**Purpose**: Restore trading execution while we collect real data for proper calibration.

## Validation Process

### Phase 1: Live Data Collection (7 Days)

**Objective**: Collect actual spread distributions during active trading.

**Collection Parameters**:
- Duration: 7 days of active trading
- Sample rate: 1 sample per second per active ticker
- Target: 1000+ samples per asset
- Data points per sample:
  - Timestamp
  - Asset/ticker
  - Time-to-expiry
  - Yes bid/ask
  - No bid/ask
  - Canonical spread
  - Model edge (if available)
  - Order side (YES/NO)
  - Economics mode (maker/taker)
  - Gate decision (accept/reject)
  - Reject reason

**Collection Method**:
```bash
# Run during active trading hours
python examples/spread_replay_example.py --example comprehensive
```

### Phase 2: Distribution Analysis

**For each asset, compute**:

**Overall Statistics**:
- Min, max, median spread
- 25th, 50th, 75th, 90th, 95th, 99th percentiles
- Mean and standard deviation
- Spread distribution histogram

**Time-Bucket Analysis**:
- Same statistics per time bucket (0-3min, 3-6min, 6-10min, 10-13min, 13-15min)
- Identify buckets with extreme spread behavior
- Calculate actual time-bucket multipliers

**Reject Rate Analysis**:
- Actual reject rate under current bridge cap
- False reject count (rejected candidates that would have had positive edge)
- False reject rate
- Missed edge sum (total edge lost from false rejects)

**Maker vs Taker Breakdown**:
- Separate reject rates for maker orders
- Separate reject rates for taker orders
- Edge preservation by economics mode

### Phase 3: Cap Selection Criteria

**Decision Criteria** (in priority order):

1. **Reject Rate Target Band**:
   - BTC: 5-10% (tightest, highest quality)
   - ETH: 8-12% (high quality)
   - SOL: 12-18% (moderate quality)
   - XRP: 15-20% (lower quality)
   - DOGE: 18-25% (lowest quality)

2. **False Reject Minimization**:
   - Target: <2% false reject rate
   - Weight false rejects by edge magnitude
   - Prefer caps that preserve high-edge opportunities

3. **Time-Bucket Stability**:
   - Reject rate variance <5% across time buckets
   - No single bucket >2x the average reject rate
   - Special attention to 0-3min and 13-15min buckets

4. **Maker Preservation**:
   - Target: >95% maker opportunity preservation
   - Maker caps can be 15% tighter than taker caps

5. **Volatility Robustness**:
   - Caps must work during high-volatility periods
   - Test against historical regime shifts
   - Add 20% buffer for SOL, XRP, DOGE

**Selection Algorithm**:

```python
def select_optimal_cap(asset, analysis):
    target = ASSET_TARGET_RANGES[asset]
    
    # Step 1: Find caps in target reject rate band
    viable = [c for c in analysis.cap_analysis 
              if target.min <= c.reject_rate <= target.max]
    
    if not viable:
        # No caps in band, use closest
        viable = sorted(analysis.cap_analysis, 
                      key=lambda c: abs(c.reject_rate - target.mid))
    
    # Step 2: Among viable, minimize false rejects
    optimal = min(viable, key=lambda c: c.false_reject_rate)
    
    # Step 3: Check time-bucket stability
    if not is_stable(optimal, analysis):
        # Adjust to more conservative cap
        optimal = adjust_for_stability(optimal, analysis)
    
    # Step 4: Verify maker preservation
    if optimal.maker_preservation < 0.95:
        # Separate maker cap
        optimal.maker_cap = tighten_maker_cap(optimal)
    
    # Step 5: Volatility robustness
    if not robust_to_volatility(optimal, analysis):
        # Add volatility buffer
        optimal.cap *= 1.2
    
    return optimal
```

### Phase 4: Regression Tests

**Gate Reject Rate Tests**:

```python
def test_gate_reject_rates():
    """Regression test for gate reject rates"""
    results = run_spread_replay(duration_hours=24)
    
    for asset, analysis in results.items():
        target = ASSET_TARGET_RANGES[asset]
        
        # Test 1: Reject rate in target band
        assert target.min <= analysis.reject_rate <= target.max, \
            f"{asset} reject rate {analysis.reject_rate:.2%} outside target {target}"
        
        # Test 2: False reject rate < 2%
        assert analysis.false_reject_rate < 0.02, \
            f"{asset} false reject rate {analysis.false_reject_rate:.2%} too high"
        
        # Test 3: Time-bucket stability
        bucket_variance = calculate_bucket_variance(analysis)
        assert bucket_variance < 0.05, \
            f"{asset} time-bucket variance {bucket_variance:.2%} too high"
        
        # Test 4: Maker preservation
        assert analysis.maker_preservation > 0.95, \
            f"{asset} maker preservation {analysis.maker_preservation:.2%} too low"
```

**Time-Bucket Stability Tests**:

```python
def test_time_bucket_stability():
    """Test that reject rates are stable across time buckets"""
    results = run_spread_replay(duration_hours=24)
    
    for asset, analysis in results.items():
        bucket_rates = analysis.time_bucket_reject_rates
        
        # No bucket should be >2x the average
        avg_rate = statistics.mean(bucket_rates.values())
        for bucket, rate in bucket_rates.items():
            assert rate < avg_rate * 2.0, \
                f"{asset} {bucket} reject rate {rate:.2%} >2x average {avg_rate:.2%}"
```

**Volatility Robustness Tests**:

```python
def test_volatility_robustness():
    """Test caps work during high-volatility periods"""
    # Replay during known high-volatility periods
    high_vol_results = run_spread_replay(
        duration_hours=24,
        filter_regime="HIGH_VOLATILITY"
    )
    
    for asset, analysis in high_vol_results.items():
        # Reject rate should not explode during high volatility
        normal_rate = get_normal_reject_rate(asset)
        vol_rate = analysis.reject_rate
        
        assert vol_rate < normal_rate * 1.5, \
            f"{asset} reject rate during volatility {vol_rate:.2%} >1.5x normal {normal_rate:.2%}"
```

## Implementation Timeline

### Week 1 (Current)
- ✅ Deploy temporary bridge caps
- 🔄 Begin live data collection
- 🔄 Monitor trade execution resumes

### Week 2
- Complete 7-day data collection
- Run distribution analysis
- Generate calibration report
- Identify optimal caps per asset

### Week 3
- Implement calibrated caps
- Deploy time-bucket adjustment logic
- Implement separate maker/taker caps
- Add regression tests

### Week 4
- Monitor calibrated caps for 7 days
- Validate against regression tests
- Fine-tune if needed
- Schedule weekly recalibration

## Success Criteria

A calibration is successful when:

1. **Reject Rate Targets Met**: Each asset achieves its target band
2. **False Rejects < 2%**: False reject rate below threshold
3. **Time-Bucket Stable**: Reject rate variance <5% across buckets
4. **Maker Preservation > 95%**: Most maker opportunities preserved
5. **Volatility Robust**: Caps work during high-volatility periods
6. **Regression Tests Pass**: All automated tests pass

## Risk Mitigation

### If Temporary Caps Are Too Loose
- Monitor for increased bad book executions
- Track P&L impact of wider spreads
- Be prepared to tighten if quality degrades

### If Temporary Caps Are Still Too Strict
- Monitor for continued low execution rates
- Track false reject occurrences
- Be prepared to loosen further if needed

### If Data Collection Fails
- Extend collection period
- Use historical data if available
- Fall back to conservative calibration

## Next Actions

1. **Immediate**: Monitor temporary caps during next trading window
2. **This Week**: Begin 7-day data collection
3. **Next Week**: Run calibration analysis
4. **Following Week**: Deploy calibrated caps with regression tests

## References

- [Kalshi Market Integrity - Prediction Markets 101](https://kalshi.com/market-integrity/prediction-markets-101)
- [Moltbook - Kalshi Crypto Prediction Markets](https://moltbook.com/post/70f293e0-b887-410b-a9cc-fafa6bd9083a)
- Spread Distribution Replay Framework: `merid/event_venues/kalshi/spread_distribution_replay.py`
- Calibration Engine: `merid/event_venues/kalshi/spread_cap_calibrator.py`
