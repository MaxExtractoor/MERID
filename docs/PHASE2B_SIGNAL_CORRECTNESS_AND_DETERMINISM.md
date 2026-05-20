# Phase 2B: Signal Correctness and Determinism

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate signal correctness through offline recompute, cross-asset/timeframe sync, and signal diff detection

---

## Executive Summary

This document defines validation checks for signal correctness, determinism, and consistency across assets and timeframes. All signals must be recomputable offline, deterministic given the same inputs, and synchronized across the 5 crypto assets (BTC/ETH/SOL/XRP/DOGE) and 15-minute timeframe.

---

## Signal Pipeline Architecture

### Current Signal Flow

```
KalshiMarketStateStore (real-time data)
    ↓
KalshiSignalGenerator (edge, liquidity, volume, risk signals)
    ↓
ConsensusGatedSignalGenerator (consensus gating)
    ↓
SignalStore (SQLite persistence)
    ↓
Trading Agents (consume signals)
```

### Signal Types

**Kalshi-Specific Signals:**
- `MarketEdgeSignal` - Edge/EV opportunities from market data
- `LiquiditySignal` - Spread/depth alerts
- `VolumeAnomalySignal` - Volume spike detection
- `KalshiRiskSignal` - Risk events (drawdown, kill switch, rate limits)

**Technical Analysis Signals:**
- RSI, MACD, EMA, SMA indicators
- Fibonacci pivots
- Divergence detection (RSI, MACD)
- Volume z-score

---

## Signal Determinism Requirements

### Requirement 1: Pure Functions

**Statement:** All signal calculations must be pure functions (no side effects, deterministic given same inputs).

**Current Implementation:**
- `TAEngine` is designed as pure functions (no state, thread-safe)
- `KalshiSignalGenerator` has state (`_last_generation`, `_signal_cache`) for caching
- `DriftDetector` has state (`_outcomes`, `_drift_history`)

**Validation:**
- Signal calculation functions must not modify global state
- Signal calculation functions must not depend on external mutable state
- Signal calculation functions must return the same output for the same inputs

**Enforcement Point:** Unit tests for determinism

**Violation Action:** Refactor to pure functions, add state isolation

---

### Requirement 2: Seed-Based Randomness

**Statement:** Any randomness in signal calculations must be seeded for reproducibility.

**Current Implementation:**
- No randomness detected in signal calculations
- All calculations use deterministic formulas (EMA, SMA, RSI, MACD)

**Validation:**
- Search for `random`, `rand`, `shuffle` in signal code
- Verify no calls to `random.random()`, `numpy.random` without seed

**Enforcement Point:** Code review, grep search

**Violation Action:** Seed all random number generators, or eliminate randomness

---

### Requirement 3: Timestamp Determinism

**Statement:** Signal timestamps must be deterministic based on input data timestamps, not wall-clock time.

**Current Implementation:**
- `MarketEdgeSignal.timestamp` uses `time.time()` (wall-clock)
- `LiquiditySignal.timestamp` uses `time.time()` (wall-clock)
- `VolumeAnomalySignal.timestamp` uses `time.time()` (wall-clock)
- `KalshiRiskSignal.timestamp` uses `time.time()` (wall-clock)

**Validation:**
- Signal timestamps should be derived from market data timestamps
- For 15-minute bars: timestamp should be bar close time (e.g., 00:15:00 UTC)
- No wall-clock time in signal generation

**Enforcement Point:** Signal generation code

**Remediation:** Use market data timestamps instead of `time.time()`

---

## Offline Signal Recompute

### Recompute Job 1: Historical Signal Replay

**Purpose:** Recompute all historical signals from stored market data and verify against stored signals.

**Method:**
1. Fetch historical market data from KalshiMarketStateStore or candle storage
2. Recompute signals using the same logic as live generation
3. Compare recomputed signals with stored signals from SignalStore
4. Calculate diff metrics:
   - Signal count match
   - Signal value match (within tolerance)
   - Timestamp match
   - Direction match (long/short/flat)

**Thresholds:**
- Signal count: 100% match
- Signal values: < 0.01% relative drift
- Timestamps: Exact match
- Direction: 100% match

**Enforcement Point:** Scheduled job (daily or weekly)

**Violation Action:** Log error, alert operator, investigate signal logic changes

---

### Recompute Job 2: Feature Snapshot Replay

**Purpose:** Recompute feature snapshots from OHLCV data and verify against stored features.

**Method:**
1. Fetch OHLCV data for a given asset and timeframe
2. Recompute TA indicators using TAEngine
3. Compare recomputed features with stored features in SignalStore
4. Calculate diff metrics for each indicator:
   - EMA, SMA values
   - RSI value
   - MACD line, signal, histogram
   - ATR value
   - Volume z-score
   - Fibonacci pivots

**Thresholds:**
- EMA/SMA: < 0.01% relative drift
- RSI: < 0.1 absolute drift
- MACD: < 0.01% relative drift
- ATR: < 0.01% relative drift
- Volume z-score: < 0.05 absolute drift
- Fib pivots: < 0.01% relative drift

**Enforcement Point:** Scheduled job (daily)

**Violation Action:** Log error, alert operator, investigate TAEngine changes

---

### Recompute Job 3: Edge Signal Replay

**Purpose:** Recompute edge signals from market data and consensus data.

**Method:**
1. Fetch historical market data (implied_prob from Kalshi)
2. Fetch historical consensus data (model_prob from swarm)
3. Recompute edge: `edge = model_prob - implied_prob`
4. Recompute EV: `ev_cents = edge * 100`
5. Recompute edge_pct: `edge_pct = edge * 100`
6. Compare with stored MarketEdgeSignal

**Thresholds:**
- Edge value: < 0.0001 absolute drift
- EV cents: < 0.01 cent drift
- Edge percentage: < 0.01% drift
- Confidence bucket: Exact match

**Enforcement Point:** Scheduled job (daily)

**Violation Action:** Log error, alert operator, investigate edge calculation changes

---

## Cross-Asset Synchronization

### Sync Check 1: Asset Coverage

**Purpose:** Verify all 5 assets (BTC/ETH/SOL/XRP/DOGE) have signals generated for each 15-minute bar.

**Method:**
1. For each 15-minute bar timestamp in the last 24 hours
2. Check if signals exist for all 5 assets
3. Check if signals exist for all timeframes (15m only for production)
4. Calculate coverage metrics:
   - Per-asset signal count
   - Per-timestamp signal count
   - Missing signal gaps

**Thresholds:**
- Asset coverage: 100% for production assets (BTC/ETH/SOL/XRP/DOGE)
- Timestamp coverage: > 95% (allow for brief gaps)
- Missing signal gaps: < 5% of bars

**Enforcement Point:** Coverage check job (every 15 minutes)

**Violation Action:** Log warning, alert if coverage drops below 90%

---

### Sync Check 2: Signal Freshness Alignment

**Purpose:** Verify all assets have similar signal freshness (no stale signals for some assets).

**Method:**
1. Fetch latest signal timestamp for each asset
2. Calculate age of each signal (current_time - signal_timestamp)
3. Compare ages across assets
4. Calculate max age difference:
   - `max_age - min_age` should be < 60 seconds

**Thresholds:**
- Max age difference: < 60 seconds
- Individual signal age: < 120 seconds

**Enforcement Point:** Freshness check job (every minute)

**Violation Action:** Log warning, alert if max age difference > 120 seconds

---

### Sync Check 3: Cross-Asset Correlation Check

**Purpose:** Verify cross-asset signal correlations are within expected ranges.

**Method:**
1. Fetch signal directions (long/short/flat) for all assets over last 100 bars
2. Calculate correlation matrix between assets
3. Compare with expected correlation ranges:
   - BTC/ETH: 0.6-0.9 (highly correlated)
   - BTC/SOL: 0.4-0.7 (moderately correlated)
   - BTC/XRP: 0.3-0.6 (moderately correlated)
   - BTC/DOGE: 0.1-0.4 (weakly correlated)

**Thresholds:**
- Correlation drift: < 0.2 from expected range
- Sudden correlation drop: Alert if correlation drops > 0.3 in 1 hour

**Enforcement Point:** Correlation check job (hourly)

**Violation Action:** Log warning, alert operator, investigate regime change

---

## Timeframe Synchronization

### Timeframe Check 1: 15-Minute Bar Alignment

**Purpose:** Verify all 15-minute signals are aligned to :00, :15, :30, :45 UTC.

**Method:**
1. Fetch all signals for 15-minute timeframe
2. Check signal timestamps: `timestamp % 900 == 0`
3. Count misaligned signals
4. Calculate misalignment rate

**Thresholds:**
- Misalignment rate: 0% (all signals must be aligned)
- Misaligned signals: 0 allowed

**Enforcement Point:** Alignment check job (every 15 minutes)

**Violation Action:** Log error, reject misaligned signals, fix timestamp logic

---

### Timeframe Check 2: Multi-Timeframe Consistency

**Purpose:** Verify signals are consistent across timeframes (if multiple timeframes are used).

**Method:**
1. Fetch signals for 15m, 1h, daily timeframes for the same asset
2. Check consistency:
   - 15m long signal should align with 1h long signal (majority of 15m bars)
   - 15m short signal should align with 1h short signal
   - Daily trend should align with shorter timeframe trends
3. Calculate consistency rate

**Thresholds:**
- 15m vs 1h consistency: > 70%
- 1h vs daily consistency: > 60%
- Sudden inconsistency: Alert if consistency drops > 30% in 1 hour

**Enforcement Point:** Consistency check job (hourly)

**Violation Action:** Log warning, alert operator, investigate timeframe divergence

---

## Signal Diff Detection

### Diff Job 1: Live vs Stored Signal Diff

**Purpose:** Compare live-generated signals with stored signals from previous runs.

**Method:**
1. Generate live signals for current timestamp
2. Fetch stored signals for same timestamp (if available)
3. Compare signal values:
   - Edge values
   - Confidence scores
   - Directions
   - Rationale tags
4. Calculate diff metrics:
   - Value diff: `abs(live - stored)`
   - Relative diff: `abs(live - stored) / stored`
   - Direction match: boolean
   - Tag match: boolean

**Thresholds:**
- Value diff: < 0.01 absolute
- Relative diff: < 0.1%
- Direction match: 100%
- Tag match: > 90%

**Enforcement Point:** Diff check job (every 15 minutes)

**Violation Action:** Log warning, alert if direction mismatch or value drift > 1%

---

### Diff Job 2: Signal Drift Over Time

**Purpose:** Detect gradual signal drift over time (e.g., edge values slowly changing).

**Method:**
1. Fetch signal history for last 7 days
2. Calculate rolling mean and std for each signal type
3. Detect drift using z-score:
   - `z_score = (current_value - rolling_mean) / rolling_std`
4. Alert if z-score exceeds threshold

**Thresholds:**
- Z-score threshold: 3.0 (3 sigma)
- Drift alert: If z-score > 3.0 for 3 consecutive periods
- Sudden jump: Alert if z-score > 5.0

**Enforcement Point:** Drift detection job (hourly)

**Violation Action:** Log warning, alert operator, investigate model drift

---

### Diff Job 3: Feature Distribution Drift

**Purpose:** Detect feature distribution drift using Population Stability Index (PSI).

**Method:**
1. Establish baseline feature distribution (from first week of data)
2. Calculate current feature distribution (last 24 hours)
3. Compute PSI for each feature:
   - `PSI = sum((actual_i - expected_i) * ln(actual_i / expected_i))`
4. Alert if PSI exceeds threshold

**Thresholds:**
- PSI threshold: 0.2 (significant drift)
- PSI warning: 0.1 (moderate drift)
- PSI critical: 0.3 (severe drift)

**Enforcement Point:** PSI calculation job (daily)

**Violation Action:** Log warning, alert if PSI > 0.2, investigate feature drift

---

## Drift Detection Integration

### Drift Metrics (from drift.py)

**Current Implementation:**
- `DomainDriftMetric` tracks per-domain drift metrics
- `ConsensusQualityIndex` (CQI) composite quality metric
- `DriftDetector` computes Brier score, log loss, PnL per risk, feature PSI, decay discipline

**CQI Components:**
- Brier component: `1 - brier_score * 4` (accuracy)
- PnL component: normalized PnL per risk
- Drift component: `1 - feature_psi * 5` (feature stability)
- Decay component: decay discipline score

**CQI Bands:**
- Good: > 0.65
- Neutral: 0.35-0.65
- Poor: < 0.35

**Validation:**
- CQI should be computed daily for each domain
- CQI history should be stored in SignalStore
- Risk adjustments should be applied based on CQI band

**Enforcement Point:** CQI calculation job (daily)

**Violation Action:** Log warning, apply risk adjustments if CQI poor

---

## Automated Test Plan

### Test Suite: `tests/signals/test_signal_correctness_and_determinism.py`

**Test Classes:**

1. `TestSignalDeterminism`
   - Test: pure function returns same output for same inputs
   - Test: no side effects in signal calculation
   - Test: seeded randomness produces reproducible results
   - Test: timestamp determinism (derived from data, not wall-clock)

2. `TestOfflineSignalRecompute`
   - Test: historical signal replay matches stored signals
   - Test: feature snapshot replay matches stored features
   - Test: edge signal replay matches stored edge signals
   - Test: TA indicators recomputed from OHLCV match stored values

3. `TestCrossAssetSync`
   - Test: all 5 assets have signals for each 15m bar
   - Test: signal freshness aligned across assets
   - Test: cross-asset correlations within expected ranges
   - Test: missing asset coverage alerts

4. `TestTimeframeSync`
   - Test: 15m signals aligned to :00, :15, :30, :45 UTC
   - Test: multi-timeframe consistency (15m vs 1h vs daily)
   - Test: timeframe divergence detection
   - Test: misaligned signal rejection

5. `TestSignalDiffDetection`
   - Test: live vs stored signal diff within thresholds
   - Test: signal drift over time detection
   - Test: feature distribution drift (PSI) calculation
   - Test: sudden jump detection

6. `TestDriftDetection`
   - Test: Brier score calculation
   - Test: log loss calculation
   - Test: feature PSI calculation
   - Test: CQI component calculation
   - Test: CQI band classification
   - Test: risk adjustment recommendations

7. `TestTAEngineDeterminism`
   - Test: EMA calculation deterministic
   - Test: SMA calculation deterministic
   - Test: RSI calculation deterministic
   - Test: MACD calculation deterministic
   - Test: ATR calculation deterministic
   - Test: Fibonacci pivots deterministic
   - Test: divergence detection deterministic

8. `TestKalshiSignalGeneratorDeterminism`
   - Test: edge signal generation deterministic
   - Test: liquidity signal generation deterministic
   - Test: volume signal generation deterministic
   - Test: risk signal generation deterministic
   - Test: consensus gating deterministic

**Total Target:** 80+ signal correctness tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify Kalshi signal generator
- ✅ Identify drift detector
- ✅ Identify signal store
- ✅ Identify TA engine
- ✅ Document signal flow

### Step 2: Define Validation Checks (DONE)
- ✅ Define signal determinism requirements
- ✅ Define offline recompute jobs
- ✅ Define cross-asset sync checks
- ✅ Define timeframe sync checks
- ✅ Define signal diff detection
- ✅ Define drift detection integration

### Step 3: Implement Validation Scripts (NEXT)
- [ ] Create `scripts/audit/recompute_signals.py`
- [ ] Create `scripts/audit/check_asset_coverage.py`
- [ ] Create `scripts/audit/check_timeframe_sync.py`
- [ ] Create `scripts/audit/detect_signal_diff.py`
- [ ] Create `scripts/audit/calculate_psi.py`

### Step 4: Add Runtime Validation
- [ ] Add determinism checks to signal generation
- [ ] Add timestamp validation (use data timestamps, not wall-clock)
- [ ] Add coverage checks to signal generator
- [ ] Add freshness checks to signal store

### Step 5: Implement Scheduled Jobs
- [ ] Create daily signal recompute job
- [ ] Create hourly asset coverage check
- [ ] Create hourly timeframe sync check
- [ ] Create daily PSI calculation job
- [ ] Create daily CQI calculation job

### Step 6: Implement Test Suite
- [ ] Create `tests/signals/test_signal_correctness_and_determinism.py`
- [ ] Implement all 8 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

### Step 7: Add Monitoring and Alerting
- [ ] Add Prometheus metrics for signal quality
- [ ] Add alerting for signal drift
- [ ] Add dashboard for signal health
- [ ] Add CQI dashboard

---

## Success Criteria

Phase 2B is complete when:

1. ✅ This design document is approved
2. [ ] All validation scripts are implemented and passing
3. [ ] Runtime validation is added to signal generation
4. [ ] All scheduled jobs are running and alerting
5. [ ] All 80+ signal correctness tests are implemented and passing
6. [ ] Monitoring and alerting are wired
7. [ ] CI pipeline includes signal correctness test suite
8. [ ] No signal drift > thresholds detected in production
9. [ ] CQI computed daily for all domains
10. [ ] Risk adjustments applied based on CQI band

---

## References

- `merid/signals/kalshi_signals.py` - Kalshi signal generator
- `merid/signals/drift.py` - Drift detector and CQI
- `merid/signals/store.py` - SignalStore persistence
- `merid/signals/ta_engine.py` - Technical analysis engine
- `merid/signals/ta_models.py` - TA data models
- `merid/swarm/consensus_aggregator.py` - Consensus aggregator
- Kalshi API Documentation (v2)

---

**Next Phase:** Phase 3 - Edge/contract/sizing audit (venue specs registry, sizing correctness, portfolio limits, drawdown limits)
