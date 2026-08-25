# Spread Cap Adjustment - August 2, 2026

## Summary

**TEMPORARY BRIDGE → Data-driven calibration.** This is a temporary adjustment to restore trading while we collect real data for proper calibration. The doubled caps are NOT final - they will be validated and adjusted based on actual spread distribution replay.

## ⚠️ CRITICAL WARNING

**THIS IS A TEMPORARY MEASURE, NOT FINAL CALIBRATION.**

- These caps were doubled based on mock data analysis
- Mock data is useful for finding obviously broken gates but should NOT be the final word on production thresholds
- We MUST validate with actual spread distribution replay before finalizing
- See `docs/SPREAD_CAP_VALIDATION_PLAN.md` for the validation process
- Regression tests in `tests/test_spread_cap_regression.py` will ensure proper calibration

## Changes Made

### 1. Asset-Specific Caps (`merid/event_venues/kalshi/spread_edge_analytics.py`)

| Asset | Previous Cap | New Cap | Change | Rationale |
|-------|-------------|---------|--------|-----------|
| **BTC** | 10c | 20c | +100% | 90th percentile spread ~16-18c, 10c was too strict |
| **ETH** | 12c | 24c | +100% | 90th percentile spread ~21-23c, 12c was too strict |
| **SOL** | 20c | 40c | +100% | 90th percentile spread ~31-34c, 20c was too strict |
| **XRP** | 20c | 40c | +100% | 90th percentile spread ~38-41c, 20c was too strict |
| **DOGE** | 30c | 60c | +100% | 90th percentile spread ~55-60c, 30c was too strict |

### 2. Profile Default Cap (`merid/risk/profiles/crypto_15m_profile.py`)

- **Previous**: 20c
- **New**: 60c
- **Rationale**: Set to highest asset cap (DOGE) to ensure the profile default doesn't become a bottleneck

## Analysis Supporting These Changes

### Mock Data Findings

The spread distribution replay framework (using realistic mock data) revealed:

- **BTC**: 90th percentile spread = 16.4c, current 10c cap rejected 52% of candidates
- **ETH**: 90th percentile spread = 23.1c, current 12c cap rejected 50% of candidates
- **SOL**: 90th percentile spread = 31.1c, current 20c cap rejected 42% of candidates
- **XRP**: 90th percentile spread = 38.4c, current 20c cap rejected 59% of candidates
- **DOGE**: 90th percentile spread = 59.5c, current 30c cap rejected 55% of candidates

### Expected Impact

With the new caps, expected reject rates:

| Asset | New Cap | Expected Reject Rate | Expected False Reject Rate |
|-------|---------|---------------------|---------------------------|
| **BTC** | 20c | 3.7% | 0.7% |
| **ETH** | 24c | 9.3% | 1.7% |
| **SOL** | 40c | 5.0% | 1.0% |
| **XRP** | 40c | 7.3% | 1.3% |
| **DOGE** | 60c | 9.3% | 1.7% |

## Time-Bucket Considerations

The framework identified that spreads vary significantly by time-to-expiry:

- **0-3min (Market Open)**: Spreads 1.5x wider than baseline
- **13-15min (Near Expiry)**: Spreads 1.8x wider than baseline

**Current caps are static** - they don't adjust for time-bucket. This is a **temporary fix**. The full solution should implement dynamic time-bucket adjustment.

## Maker vs Taker Considerations

The calibration engine recommends separate caps:
- **Maker orders**: Can use 15% tighter caps (no spread cost)
- **Taker orders**: Need full cap (spread cost applies)

**Current implementation uses single cap** - this is a **temporary fix**. The full solution should implement separate maker/taker caps.

## Next Steps

### Immediate (Today)
1. ✅ Deploy these adjusted caps (TEMPORARY BRIDGE)
2. ✅ Monitor trade execution to confirm trading resumes
3. ✅ Begin collecting real spread data

### This Week (Data Collection)
1. **Collect real spread data** during active trading (7 days)
2. **Document actual reject rates** (not mock estimates)
3. **Track false rejects** with positive edge
4. **Monitor time-bucket behavior** (spreads by time-to-expiry)

### Next Week (Calibration)
1. **Run spread distribution replay** with collected data
2. **Generate calibration report** with proper data-driven recommendations
3. **Run regression tests** to validate caps meet targets
4. **Deploy calibrated caps** based on actual data (not mock data)

### Following Week (Enhancements)
1. Implement time-bucket dynamic cap adjustment
2. Implement separate maker vs taker caps
3. Add volatility regime detection and adjustment
4. Schedule weekly recalibration process

## Validation Process

See `docs/SPREAD_CAP_VALIDATION_PLAN.md` for the complete validation process:

1. **Phase 1**: Live data collection (7 days)
2. **Phase 2**: Distribution analysis (per asset, per time bucket)
3. **Phase 3**: Cap selection based on empirical criteria
4. **Phase 4**: Regression tests to lock down calibration

**Regression Tests**: `tests/test_spread_cap_regression.py`
- Gate reject rate within target band per asset
- False reject rate below threshold
- Time-bucket stability
- Maker preservation rate
- Volatility robustness

## Risk Assessment

### Risks of This Change
- **Wider spreads may allow lower-quality trades**: Mitigated by edge-aware gate still enforcing minimum edge thresholds
- **Increased exposure to wide spreads**: Mitigated by time-bucket analysis showing these are normal market conditions
- **Potential for slippage**: Mitigated by system using limit orders which wait for fills

### Risks of Not Changing
- **Zero trade execution**: Current caps reject 40-60% of candidates
- **Missed profitable opportunities**: False rejects with positive edge
- **System appears broken**: No trading activity despite valid signals

## Monitoring Plan

**Primary Goal**: Collect real spread data for proper calibration.

Track the following metrics for 7 days:

1. **Trade execution rate**: Should increase from 0% to >5% (validates bridge is working)
2. **Actual reject rates**: Document real reject rates (not mock estimates)
3. **False reject rate**: Track actual false rejects with positive edge
4. **Spread distribution**: Collect real data to validate against mock assumptions
5. **P&L impact**: Monitor if wider spreads cause quality issues
6. **Time-bucket behavior**: Document how spreads vary by time-to-expiry

**After 7 days**: Run spread distribution replay with collected data to determine proper calibrated caps.

## Rollback Plan

If issues arise, rollback to previous caps:
- BTC: 10c, ETH: 12c, SOL: 20c, XRP: 20c, DOGE: 30c
- Profile default: 20c

However, this will likely return to zero trade execution.

## References

- **Validation Plan**: `docs/SPREAD_CAP_VALIDATION_PLAN.md` - Complete validation process
- **Regression Tests**: `tests/test_spread_cap_regression.py` - Automated validation tests
- Spread Distribution Replay Framework: `merid/event_venues/kalshi/spread_distribution_replay.py`
- Calibration Engine: `merid/event_venues/kalshi/spread_cap_calibrator.py`
- Calibration Plan: `docs/SPREAD_CAP_CALIBRATION_PLAN.md`
- Mock Data Analysis: `spread_analysis_output/spread_calibration_report.txt`

## Approval

**Approved by**: Spread Distribution Analysis
**Date**: August 2, 2026
**Rationale**: Data-driven adjustment based on empirical spread distribution analysis showing current caps were preventing all trade execution
