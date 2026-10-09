# Staging Soak Checklist and Metrics
**Date**: 2026-08-02  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Purpose**: Validate microstructure gate stability under production-like traffic

## Executive Summary

Comprehensive staging soak checklist to validate the 15-minute microstructure gate under production-like conditions. Focus on rejection reason distribution, false reject rate, maker vs taker hit rate, asset-level behavior differences, and drift in quote freshness or book quality.

---

# STAGING SOAK OBJECTIVES

## Primary Objectives
1. **Validate gate stability** under production-like traffic patterns
2. **Verify rejection reason distribution** matches expectations
3. **Measure false reject rate** against historical baseline
4. **Compare maker vs taker hit rate** to validate economics mode
5. **Monitor asset-level behavior differences** for calibration validation
6. **Detect drift in quote freshness** and book quality under real flow

## Success Criteria
- **Rejection rate**: Within expected range (20-40% for 15m markets)
- **False reject rate**: < 5% of total rejections
- **Maker hit rate**: > 70% of maker orders accepted
- **Asset consistency**: Each asset behaves according to calibration
- **Quote freshness**: > 95% of quotes within freshness threshold
- **No silent failures**: All rejections have clear, logged reasons

---

# PRE-STAGING VALIDATION

## Infrastructure Readiness
- [ ] **Staging environment** mirrors production configuration
- [ ] **Market data feeds** active and reliable for all 5 assets
- [ ] **Order submission** endpoint functional in staging
- [ ] **Monitoring/alerting** configured and tested
- [ ] **Log aggregation** capturing gate decision traces
- [ ] **Metrics collection** enabled for all key metrics

## Configuration Validation
- [ ] **Asset-specific calibration** loaded correctly (BTC, ETH, SOL, XRP, DOGE)
- [ ] **Time-to-expiry scaling** enabled and functional
- [ ] **Gate orchestration** active as single decision path
- [ ] **Legacy gates** disabled or tagged
- [ ] **Fee-aware gate** deprecation enforced for 15m markets
- [ ] **Maker/taker economics** distinction preserved

## Data Validation
- [ ] **Historical baseline data** available for comparison
- [ ] **Shadow replay results** documented for comparison
- [ ] **Expected rejection distribution** calculated from calibration
- [ ] **Asset-specific thresholds** documented and validated

---

# STAGING SOAK EXECUTION

## Phase 1: Traffic Ramp-Up (Hours 0-2)

### Objectives
- Gradually increase traffic to production-like levels
- Monitor system stability under increasing load
- Validate gate decision latency and throughput

### Traffic Levels
- **Hour 0**: 10% of production traffic
- **Hour 1**: 50% of production traffic  
- **Hour 2**: 100% of production traffic

### Monitoring Focus
- **Gate decision latency**: < 100ms p95
- **System stability**: No crashes or errors
- **Decision consistency**: Rejection rate stable across traffic levels

### Success Criteria
- [ ] Gate decision latency < 100ms p95 at all traffic levels
- [ ] No system crashes or errors during ramp-up
- [ ] Rejection rate stable (±5%) across traffic levels

## Phase 2: Steady-State Operation (Hours 2-24)

### Objectives
- Operate at production-like traffic levels
- Collect comprehensive metrics on gate behavior
- Validate asset-specific calibration under real conditions

### Monitoring Focus
- **Rejection reason distribution**
- **False reject rate**
- **Maker vs taker hit rate**
- **Asset-level behavior differences**
- **Quote freshness and book quality**

### Success Criteria
- [ ] Rejection rate within expected range (20-40%)
- [ ] False reject rate < 5% of total rejections
- [ ] Maker hit rate > 70% of maker orders
- [ ] Each asset behaves according to calibration
- [ ] Quote freshness > 95% within threshold

## Phase 3: Replay Diff Validation (Hours 24-48)

### Objectives
- Compare live staging outcomes with shadow replay predictions
- Identify any discrepancies between expected and actual behavior
- Validate calibration values against real market conditions

### Monitoring Focus
- **Live vs shadow decision match rate**
- **Rejection reason consistency**
- **Asset-specific threshold effectiveness**
- **Time-to-expiry scaling accuracy**

### Success Criteria
- [ ] Live vs shadow decision match rate > 90%
- [ ] Rejection reasons consistent with expectations
- [ ] Asset-specific thresholds effective
- [ ] Time-to-expiry scaling accurate

---

# KEY METRICS TO WATCH

## Rejection Reason Distribution

### Overall Metrics
- **Total rejection rate**: % of candidates rejected
- **Rejection by reason**: % breakdown by rejection reason
- **First reject stage**: % of rejections by gate stage

### Expected Distribution
- **Spread too wide**: 40-60% of rejections
- **Insufficient depth**: 20-30% of rejections
- **Crossed book**: 5-10% of rejections
- **Stale quote**: 5-10% of rejections
- **Other reasons**: 5-10% of rejections

### Per-Asset Metrics
- **BTC rejection rate**: Expected 25-35%
- **ETH rejection rate**: Expected 25-35%
- **SOL rejection rate**: Expected 30-40%
- **XRP rejection rate**: Expected 30-40%
- **DOGE rejection rate**: Expected 35-45%

### Alerting Thresholds
- **Alert if**: Rejection rate > 50% (indicates over-blocking)
- **Alert if**: Rejection rate < 10% (indicates under-blocking)
- **Alert if**: Any single reason > 70% (indicates gate imbalance)

## False Reject Rate

### Definition
- **False reject**: Candidate rejected but should have been accepted based on shadow replay
- **False reject rate**: False rejects / total rejections

### Measurement Method
- **Shadow replay comparison**: Run rejected candidates through shadow replay
- **Manual review**: Sample rejected candidates for manual validation
- **Historical comparison**: Compare with historical acceptance patterns

### Expected Performance
- **False reject rate**: < 5% of total rejections
- **False positive rate**: < 2% of total candidates

### Per-Asset Metrics
- **BTC false reject rate**: < 5%
- **ETH false reject rate**: < 5%
- **SOL false reject rate**: < 5%
- **XRP false reject rate**: < 5%
- **DOGE false reject rate**: < 5%

### Alerting Thresholds
- **Alert if**: False reject rate > 10% (indicates gate too strict)
- **Alert if**: False reject rate > 15% for any single asset

## Maker vs Taker Hit Rate

### Definition
- **Maker hit rate**: % of maker orders accepted
- **Taker hit rate**: % of taker orders accepted

### Expected Performance
- **Maker hit rate**: > 70% (makers should have higher acceptance due to no spread cost)
- **Taker hit rate**: > 50% (takers have higher spread cost, lower acceptance)

### Per-Asset Metrics
- **BTC maker hit rate**: > 75%
- **ETH maker hit rate**: > 75%
- **SOL maker hit rate**: > 70%
- **XRP maker hit rate**: > 70%
- **DOGE maker hit rate**: > 65%

### Alerting Thresholds
- **Alert if**: Maker hit rate < 60% (indicates maker economics broken)
- **Alert if**: Taker hit rate > maker hit rate (indicates economics inversion)

## Asset-Level Behavior Differences

### Calibration Validation
- **BTC**: Should have lowest rejection rate (tightest calibration)
- **ETH**: Should have low rejection rate (tight calibration)
- **SOL**: Should have medium rejection rate (medium calibration)
- **XRP**: Should have medium rejection rate (medium calibration)
- **DOGE**: Should have highest rejection rate (loosest calibration)

### Threshold Effectiveness
- **Spread cap**: Verify asset-specific spread caps are effective
- **Depth threshold**: Verify asset-specific depth thresholds are effective
- **Ratio threshold**: Verify asset-specific ratio thresholds are effective

### Expected Behavior
- **BTC**: Rejection rate 25-35%, spread cap 10c effective
- **ETH**: Rejection rate 25-35%, spread cap 12c effective
- **SOL**: Rejection rate 30-40%, spread cap 20c effective
- **XRP**: Rejection rate 30-40%, spread cap 20c effective
- **DOGE**: Rejection rate 35-45%, spread cap 30c effective

### Alerting Thresholds
- **Alert if**: Asset rejection rate deviates > 10% from expected
- **Alert if**: Asset behavior rank order changes (e.g., DOGE < BTC)

## Quote Freshness and Book Quality

### Quote Freshness
- **Definition**: Time since market data last updated
- **Threshold**: Quotes older than 30 seconds considered stale

### Expected Performance
- **Quote freshness**: > 95% of quotes within 30-second threshold
- **Stale quote rate**: < 5% of quotes

### Book Quality Metrics
- **Crossed book rate**: < 1% of market snapshots
- **Zero depth rate**: < 2% of market snapshots
- **Extreme spread rate**: < 5% of market snapshots

### Alerting Thresholds
- **Alert if**: Quote freshness < 90%
- **Alert if**: Stale quote rate > 10%
- **Alert if**: Crossed book rate > 5%

---

# PER-ASSET METRICS DASHBOARD

## BTC Metrics
- **Rejection rate**: Target 25-35%
- **False reject rate**: Target < 5%
- **Maker hit rate**: Target > 75%
- **Spread cap effectiveness**: 10c cap should reject wide spreads
- **Depth threshold effectiveness**: 50 contracts should filter low liquidity
- **Ratio threshold effectiveness**: 0.6-0.3 range should filter poor economics

## ETH Metrics
- **Rejection rate**: Target 25-35%
- **False reject rate**: Target < 5%
- **Maker hit rate**: Target > 75%
- **Spread cap effectiveness**: 12c cap should reject wide spreads
- **Depth threshold effectiveness**: 40 contracts should filter low liquidity
- **Ratio threshold effectiveness**: 0.7-0.4 range should filter poor economics

## SOL Metrics
- **Rejection rate**: Target 30-40%
- **False reject rate**: Target < 5%
- **Maker hit rate**: Target > 70%
- **Spread cap effectiveness**: 20c cap should reject wide spreads
- **Depth threshold effectiveness**: 25 contracts should filter low liquidity
- **Ratio threshold effectiveness**: 0.9-0.5 range should filter poor economics

## XRP Metrics
- **Rejection rate**: Target 30-40%
- **False reject rate**: Target < 5%
- **Maker hit rate**: Target > 70%
- **Spread cap effectiveness**: 20c cap should reject wide spreads
- **Depth threshold effectiveness**: 25 contracts should filter low liquidity
- **Ratio threshold effectiveness**: 0.9-0.5 range should filter poor economics

## DOGE Metrics
- **Rejection rate**: Target 35-45%
- **False reject rate**: Target < 5%
- **Maker hit rate**: Target > 65%
- **Spread cap effectiveness**: 30c cap should reject wide spreads
- **Depth threshold effectiveness**: 15 contracts should filter low liquidity
- **Ratio threshold effectiveness**: 1.0-0.6 range should filter poor economics

---

# ALERTING CONFIGURATION

## Critical Alerts (Immediate Action Required)
- **System crash**: Any gate component crashes
- **Silent failure**: Orders rejected without clear reason
- **Data feed failure**: Market data feed down for any asset
- **Calibration error**: Asset-specific calibration not loaded

## High-Priority Alerts (Action Within 1 Hour)
- **Rejection rate > 50%**: Indicates over-blocking
- **Rejection rate < 10%**: Indicates under-blocking
- **False reject rate > 10%**: Indicates gate too strict
- **Maker hit rate < 60%**: Indicates maker economics broken
- **Quote freshness < 90%**: Indicates data quality issue

## Medium-Priority Alerts (Action Within 4 Hours)
- **Asset rejection rate deviation > 10%**: Indicates calibration issue
- **Single rejection reason > 70%**: Indicates gate imbalance
- **Stale quote rate > 10%**: Indicates data quality issue
- **Crossed book rate > 5%**: Indicates market data issue

## Low-Priority Alerts (Action Within 24 Hours)
- **Gate decision latency > 200ms**: Indicates performance issue
- **Asset behavior rank change**: Indicates calibration drift
- **Time-to-expiry scaling inaccuracy**: Indicates calibration issue

---

# REPLAY DIFF VALIDATION

## Live vs Shadow Comparison

### Decision Match Rate
- **Target**: > 90% match rate between live and shadow decisions
- **Measurement**: Compare live staging decisions with shadow replay predictions
- **Analysis**: Investigate mismatches to identify calibration or logic issues

### Rejection Reason Consistency
- **Target**: > 85% match rate for rejection reasons
- **Measurement**: Compare live rejection reasons with shadow replay predictions
- **Analysis**: Investigate reason mismatches to identify logic issues

### Asset-Specific Validation
- **Target**: Each asset within 5% of expected rejection rate
- **Measurement**: Compare live asset behavior with shadow replay predictions
- **Analysis**: Investigate asset deviations to identify calibration issues

## Calibration Validation

### Threshold Effectiveness
- **Spread cap**: Verify asset-specific spread caps reject expected % of candidates
- **Depth threshold**: Verify asset-specific depth thresholds filter expected % of candidates
- **Ratio threshold**: Verify asset-specific ratio thresholds filter expected % of candidates

### Time-to-Expiry Scaling
- **Ratio decay**: Verify sigmoid decay functions as expected over time
- **Spread cap decay**: Verify linear decay functions as expected over time
- **Asset consistency**: Verify scaling consistent across all assets

---

# SUCCESS CRITERIA SUMMARY

## Phase 1: Traffic Ramp-Up
- [ ] Gate decision latency < 100ms p95 at all traffic levels
- [ ] No system crashes or errors during ramp-up
- [ ] Rejection rate stable (±5%) across traffic levels

## Phase 2: Steady-State Operation
- [ ] Rejection rate within expected range (20-40%)
- [ ] False reject rate < 5% of total rejections
- [ ] Maker hit rate > 70% of maker orders
- [ ] Each asset behaves according to calibration
- [ ] Quote freshness > 95% within threshold

## Phase 3: Replay Diff Validation
- [ ] Live vs shadow decision match rate > 90%
- [ ] Rejection reasons consistent with expectations
- [ ] Asset-specific thresholds effective
- [ ] Time-to-expiry scaling accurate

---

# ROLLBACK CRITERIA

## Immediate Rollback
- **System crash**: Any gate component crashes
- **Data corruption**: Market data corruption detected
- **Calibration error**: Asset-specific calibration not loaded correctly
- **Silent failures**: Orders rejected without clear reason

## Rollback After Investigation
- **Rejection rate > 60%**: Indicates severe over-blocking
- **False reject rate > 20%**: Indicates gate too strict
- **Maker hit rate < 40%**: Indicates maker economics severely broken
- **Asset behavior completely inverted**: Indicates fundamental calibration issue

---

# POST-STAGING ACTIONS

## If Staging Successful
1. **Deploy to production** with monitoring enabled
2. **Continue monitoring** for first 24-48 hours
3. **Compare production vs staging** metrics
4. **Adjust calibration** if needed based on production data

## If Staging Issues Found
1. **Investigate root cause** of issues
2. **Fix issues** in staging environment
3. **Re-run staging soak** with fixes
4. **Validate fixes** before production deployment

## Calibration Tuning
1. **Analyze staging data** for calibration optimization opportunities
2. **Adjust v1 calibration values** if needed
3. **Validate new calibration** through shadow replay
4. **Deploy updated calibration** to staging for validation

---

# REFERENCES

- Microstructure gate spec: `MICROSTRUCTURE_GATE_15M_SPEC_2026_08_02.md`
- Shadow replay analysis: `SHADOW_REPLAY_ANALYSIS_2026_08_02.md`
- Gate orchestrator: `merid/event_venues/kalshi/gate_orchestrator.py`
- Shadow replay execution: `merid/event_venues/kalshi/shadow_replay_execution.py`
