# Audit Step 2: Edge and Signal Audit

**Date:** 2026-05-12  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute signals  
**Purpose:** Verify actual live signals and entry/exit rules match intended edge and are internally consistent

---

## Signal Storage and Infrastructure

### Signal Storage
**File:** `merid/signals/store.py`  
**Database:** `data/signals.db` (SQLite, 110MB)  
**Tables:**
- `signal_features` - Cached feature snapshots per symbol/domain
- `signal_snapshots` - Frozen driver snapshots attached to opinions/plans
- `arb_signals` - Detected dislocations
- `arb_plans` - Multi-leg arb/dislocation plans
- `drift_metrics` - Per-domain drift/quality metrics over time
- `cqi_history` - Consensus Quality Index snapshots

**Status:** ✅ Signal storage infrastructure exists and is actively used

---

### Drift Detection
**File:** `merid/signals/drift.py`  
**Metrics Tracked:**
- Per-domain Brier/LogLoss vs baselines
- Feature distribution drift (PSI approximation)
- Decay discipline: frequency of trading on stale vs fresh signals
- CQI (Consensus Quality Index): Composite quality metric

**CQI Formula:** `CQI = w1*brier + w2*pnl_per_risk + w3*(1-drift) + w4*decay_discipline`  
**Bands:** good (>0.65), neutral (0.35-0.65), poor (<0.35)

**Status:** ✅ Drift detection infrastructure exists

---

### Crypto 15m Signal Calculation
**File:** `merid/signals/crypto_15m_indicators.py`  
**Indicator Stack:**
1. Trend baseline - EMA(50) regime filter + EMA(5)/EMA(20) crossover
2. Momentum/overextension - RSI(8) + MACD(8,21,5) + distance-from-EMA in ATR units
3. Volatility gate - 30-60 min realized vol band + ATR(14) + ATR min-move gate
4. Chop filters - Consecutive closes, MACD persistence, histogram magnitude
5. Liquidity filter - Spread width and depth thresholds
6. Fee-aware EV - Mid-curve penalty, per-trade fee calculator
7. Backtest logging - All fields needed for replay and Monte Carlo

**Asset-Specific Configs:**
- BTC/ETH: Faster EMAs (9/21), stricter consecutive closes (3)
- SOL/XRP/DOGE: Slower EMAs (13/34), relaxed consecutive closes (2)

**Status:** ✅ Comprehensive indicator stack with asset-specific tuning

---

### Crypto Edge Production
**File:** `merid/prediction/crypto_edge_production.py`  
**Thresholds Loaded From:** `config/crypto_threshold_matrix.yaml`  
**Profile Selection:** `MERID_CRYPTO_EDGE_PRODUCTION_PROFILE` (default: modern_tradeable_kalshi_v1)

**CryptoEdgeRuntime Components:**
- `edge_floor_profile` - Edge floor profile (strict/medium/loose)
- `mm_consensus_mode` - MM consensus mode (full/soft/bypass)
- `shadow_edge_yes` - Shadow edge threshold for YES
- `shadow_edge_no` - Shadow edge threshold for NO
- `consensus_wait_timeout_ms` - Consensus wait timeout
- `threshold_mode` - "legacy" or "modern" threshold mode

**Security:** Bypass mode is disabled - forces to 'full' if attempted

**Status:** ✅ Production edge configuration with profile-based tuning

---

## Replay Capability

### Replay Session Script
**File:** `scripts/replay_session.py`  
**Purpose:** Replay historical OHLCV through current agent stack  
**Usage:**
```bash
py scripts/replay_session.py --ticker KXBTC-24DEC31-B90000 --years 1 --resolution 1h
py scripts/replay_session.py --ticker KXBTC-24DEC31-B90000 --csv data/btc.csv
```

**Output:**
- `replay_<ticker>_<timestamp>.json` - Machine-readable signal/fill log
- Summary table (stdout)

**ReplaySignal Fields:**
- bar_index, timestamp, OHLC
- model_prob, confidence, edge
- decision (enter_yes/enter_no/hold)
- simulated_fill

**Status:** ✅ Replay capability exists for historical signal validation

---

## Determinism Check

### Current State
**Determinism Enforcement:** Limited
- Found "deterministic" keyword in trading adapters (fallback mocks)
- No explicit determinism validation for signal calculation
- No automated signal diff job comparing replay vs live

**Risk:** Hidden dependencies, race conditions, or config drift could cause non-deterministic signal behavior

**Status:** ⚠️ Determinism checks are NOT automated

---

## Edge Sanity Checks

### Hit Rate Tracking
**Locations:**
- `web/api/kalshi_api.py:5972` - Win rate insight alerts
- `web/api/band_strategy_api.py:379` - Min win rate thresholds
- `web/api/betting_consensus_api.py:228` - Betting performance metrics

**Alert Threshold:** Win rate below 45% triggers degradation alert

**Status:** ✅ Hit rate tracking exists with alerting

---

### Expectancy Tracking
**Locations:**
- `web/api/paper_session_api.py:150` - Min expectancy cents
- `web/api/paper_trading.py:215` - Win rate calculation

**Status:** ✅ Expectancy tracking exists

---

### Backtest Capability
**Locations:**
- `merid/strategies/backtest_15m_meanrev.py` - Single-asset backtest skeleton
- `merid/sentiment/sentiment_backtest.py` - Sentiment signal backtesting
- `scripts/run_band_backtest.py` - Band strategy backtest runner

**Status:** ✅ Backtest capability exists

---

## Critical Findings

### 🔴 CRITICAL: No Automated Signal Determinism Check

**Issue:** There is no automated job that re-runs signal code on recorded raw data and diffs against stored signals.

**Impact:** Hidden dependencies, race conditions, or config drift could cause non-deterministic signal behavior without detection.

**Risk:** High - Signals could diverge from expected behavior without alerts.

**Recommendation:** Implement a nightly signal determinism job that:
1. Captures raw input data for a sample of 15m bars
2. Stores computed signal outputs
3. Re-runs signal code on same inputs
4. Diffs outputs and alerts on mismatch

---

### 🟡 WARNING: Terminal Phase Trading Ban Disabled (from Step 1)

**File:** `merid/prediction/strategy.py:1634`  
**Issue:** Terminal phase trading ban (weak edge protection) is disabled due to MarketMoodBus issue.

**Impact:** Trades allowed in last hour of contracts even when model has weak edge (< 3%).

**Risk:** High - Bypasses critical risk control.

**Recommendation:** Re-enable immediately after fixing MarketMoodBus context population.

---

### 🟢 INFO: Signal Infrastructure is Well-Designed

**Positive Findings:**
- Comprehensive SQLite signal storage with 110MB of historical data
- Drift detection with CQI composite quality metric
- Asset-specific indicator tuning (BTC/ETH vs SOL/XRP/DOGE)
- Profile-based edge configuration with modern defaults
- Replay capability for historical validation
- Hit rate and expectancy tracking with alerting
- Multiple backtest frameworks

---

## Missing Capabilities

### 1. Automated Signal Snapshots
**Current:** No automated extraction of signal snapshots for past N weeks  
**Needed:** Job to dump all 15m signals with timestamps, feature values, and trade decisions

---

### 2. Signal Diff Job
**Current:** No automated comparison of replay vs live signals  
**Needed:** Nightly job to re-run signal code on recorded data and diff

---

### 3. Per-Asset Edge Statistics
**Current:** Win rate tracked globally, not per-asset  
**Needed:** Hit rate, average win/loss, expectancy, trade frequency per asset (BTC/ETH/SOL/XRP/DOGE)

---

### 4. Signal Delay Detection
**Current:** No detection of missing or delayed signals for 15m bars  
**Needed:** Monitor for gaps in signal generation timeline

---

## Next Steps for Step 2

1. ✅ Identify signal storage infrastructure - DONE
2. ✅ Identify drift detection capability - DONE
3. ✅ Identify replay capability - DONE
4. ⏳ Extract live signal snapshots for past N weeks - NEED PRODUCTION ACCESS
5. ⏳ Run determinism check - NEED PRODUCTION DATA
6. ⏳ Compute per-asset edge statistics - NEED PRODUCTION DATA

---

## Summary

**Obviously Broken:**
1. No automated signal determinism check (CRITICAL)
2. Terminal phase trading ban disabled (from Step 1, CRITICAL)

**Probably Fine:**
- Signal storage infrastructure is comprehensive (SQLite, 110MB)
- Drift detection with CQI exists
- Replay capability exists
- Hit rate and expectancy tracking exists

**Weird/Unclear:**
- No per-asset edge statistics (BTC/ETH/SOL/XRP/DOGE tracked together)
- No signal delay detection
- MarketMoodBus context population issue causing terminal phase ban to be disabled
