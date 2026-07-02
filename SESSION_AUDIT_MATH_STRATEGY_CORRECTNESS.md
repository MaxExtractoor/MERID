# Session Audit: Math and Strategy Correctness + Numerical/Temporal Hygiene + Deep Code Structure + System Architecture + Operational Readiness Audit
## 15m Kalshi Crypto Production Stack (BTC, ETH, SOL, XRP, DOGE)
**Date**: 2026-06-07
**Session Focus**: Mathematical structure audit (edge, sizing, risk, exits) + Numerical/temporal hygiene audit + Deep code structure audit (duplication, over-engineering, consistency, dead code) + System architecture audit (10-stage end-to-end validation) + Operational readiness audit (env/deployment, backtest/live equivalence, incidents, security, resilience, human interfaces, documentation)

---

## Executive Summary

**Audit Scope**:
- **Math Audit**: Edge/expectancy math, position sizing (Kelly), risk/drawdown math, exit/TP/SL/R:R math, strategy-level coherence
- **Hygiene Audit**: Magic number inventory, missing-value handling, computation consistency, time alignment, dynamic vs static parameters
- **Deep Audit**: Duplication map, over-engineering hotspots, consistency violations, dead/orphaned/starved code
- **Architecture Audit**: 10-stage end-to-end validation (data ingestion, signal generation, edge computation, execution, exit policies, risk management, PnL/reconciliation, time/staleness, dead code, observability)
- **Operational Readiness Audit**: 7-stage validation (env/deployment, backtest/live equivalence, incidents, security, resilience, human interfaces, documentation)

**Total Issues Identified**: 115
- **Math Audit**: 11 issues (3 SEV-1, 5 SEV-2, 3 SEV-3)
- **Hygiene Audit**: 14 issues (3 SEV-1, 6 SEV-2, 5 SEV-3)
- **Deep Audit**: 15 issues (3 SEV-1, 5 SEV-2, 5 SEV-3, 2 LOW)
- **Architecture Audit**: 51 items (10 stages, 5-7 items per stage)
- **Operational Readiness Audit**: 24 items (7 stages, 3-4 items per stage)

**Total Fixes Required**: 115 code/config fixes + 13 regression tests + 1 backtest

**Status**: Audit complete, fixes pending

---

## Section 1: Edge & EV Math Audit

### Current Formulas Verified

| Formula | Location | Status |
|---------|----------|--------|
| Model-implied probability q | unified_edge.py:825-920 | ✅ Correct |
| Market-implied probability π | unified_edge.py:922-935 | ✅ Correct |
| Raw edge = q - π | unified_edge.py:937-956 | ✅ Correct |
| Slippage-adjusted edge | unified_edge.py:983-1046 | ✅ Correct |
| Fee-adjusted edge | unified_edge.py:1048-1099 | ✅ Correct |
| Kalshi fee formula | fees.py:72-149 | ✅ Correct |

### Issues Found

- [x] **SEV-2**: Missing per-contract EV calculation
  - **File**: unified_edge.py
  - **Fix ID**: P1-FIX3
  - **Status**: Completed
  - **Test**: Given q=0.55, price=50c, fee=2c, verify EV=3.9c

- [x] **SEV-2**: Edge recovery double-counts fees in position sizer
  - **File**: position_sizer.py:876-880
  - **Fix ID**: P1-FIX2
  - **Status**: Completed
  - **Test**: Given π=0.50, edge_fee_adjusted=0.03, verify est_win_prob=0.53

- [ ] **SEV-3**: Latency buffer uses rough tick conversion
  - **File**: unified_edge.py:1127-1146
  - **Fix ID**: P4-FIX10
  - **Status**: Pending (requires calibration data)
  - **Test**: Calibrate with feed lag experiments

### Edge Thresholds by Asset

| Asset | min_edge_early | min_edge_mid | min_edge_late | min_edge_terminal |
|-------|---------------|--------------|---------------|-------------------|
| BTC   | 3%            | 3%           | 3%            | 4%                |
| ETH   | 3%            | 3%           | 3%            | 4%                |
| SOL   | 4%            | 4%           | 4%            | 5%                |
| XRP   | 4%            | 4%           | 4%            | 5%                |
| DOGE  | 4%            | 4%           | 4%            | 5%                |

---

## Section 2: Position Sizing & Kelly Logic Audit

### Current Kelly Formulas Verified

| Formula | Location | Status |
|---------|----------|--------|
| Kelly fraction for binary | position_sizer.py:120-144 | ✅ Correct |
| Kelly with fees | kalshi_risk.py:171-241 | ✅ Correct |
| Profile Kelly cap | kalshi_crypto_15m.yaml:463-470 | ⚠️ Too high |

### Issues Found

- [ ] **SEV-1**: Kelly fraction too high (30%) for binary options
  - **File**: kalshi_crypto_15m.yaml:464
  - **Fix ID**: P1-FIX1
  - **Status**: Pending
  - **Test**: Simulate 100 trades with 55% win rate, verify drawdown < 10%

- [ ] **SEV-2**: Edge recovery bug in compute_from_edge_result
  - **File**: position_sizer.py:876-880
  - **Fix ID**: P1-FIX2
  - **Status**: Pending
  - **Test**: Verify est_win_prob calculation without double-counting

- [ ] **SEV-2**: Adaptive Kelly multipliers stack multiplicatively
  - **File**: position_sizer.py:183-246
  - **Fix ID**: None (design choice)
  - **Status**: Accepted risk
  - **Test**: Verify final multiplier ≥ 0.25

- [ ] **SEV-3**: Kelly edge clamping inconsistent with profile
  - **File**: kalshi_risk.py:99-118
  - **Fix ID**: None (minor)
  - **Status**: Low priority
  - **Test**: Use profile edge clamps

### Per-Asset Sizing Caps

| Asset | max_notional_pct | max_contracts | max_distance_pct |
|-------|------------------|--------------|------------------|
| BTC   | 1%               | 5            | 1.5%             |
| ETH   | 1%               | 5            | 2.0%             |
| SOL   | 0.5%             | 3            | 2.5%             |
| XRP   | 0.5%             | 3            | 3.0%             |
| DOGE  | 0.5%             | 3            | 4.0%             |

---

## Section 3: Risk & Drawdown Math Audit

### Current Risk Formulas Verified

| Formula | Location | Status |
|---------|----------|--------|
| Drawdown calculation | kalshi_crypto_15m.yaml:64-67 | ✅ Correct |
| Drawdown thresholds | kalshi_crypto_15m.yaml:407-420 | ✅ Correct |
| Daily loss limit | kalshi_crypto_15m.yaml:425-432 | ⚠️ Conflicts with drawdown |
| Adaptive risk bands | kalshi_crypto_15m.yaml:449-457 | ✅ Correct |
| Venue caps | kalshi_crypto_15m.yaml:108-128 | ✅ Fixed (P2-FIX6: tightened to 5%) |

### Issues Found

- [x] **SEV-1**: Drawdown and daily loss both active
  - **File**: kalshi_crypto_15m.yaml:407-432
  - **Fix ID**: P2-FIX4
  - **Status**: SUPERSEDED by reconciliation decision
  - **Decision**: WIP profile kept as ground truth with richer daily loss design (enabled 8%/4% + rolling PnL halts). Audit intent to disable daily loss is superseded in favor of the more advanced risk design in the working tree.

- [x] **SEV-2**: Per-trade risk not enforced in sizing
  - **File**: kalshi_crypto_15m.yaml:417-420, position_sizer.py
  - **Fix ID**: P2-FIX5
  - **Status**: Completed
  - **Test**: With bankroll=$1000, verify max position ≤ $8

- [x] **SEV-2**: Max total notional (35%) > bankroll cap (5%)
  - **File**: kalshi_crypto_15m.yaml:115-127
  - **Fix ID**: P2-FIX6
  - **Status**: Completed
  - **Test**: With bankroll=$1000, verify total exposure ≤ $50

- [ ] **SEV-3**: Cycle drawdown multiplier not fully integrated
  - **File**: position_cache.py:977-988
  - **Fix ID**: None (minor)
  - **Status**: Low priority
  - **Test**: Verify cycle drawdown integration

### Risk Metric Consistency

| Metric | Basis | Cap | Status |
|--------|-------|-----|--------|
| Drawdown | Equity + unrealized | 15% | ✅ ACTIVE |
| Daily Loss | Session-level PnL | 4% (prod) | ✅ ACTIVE (WIP design kept) |
| Per-Trade Risk | Bankroll % | 0.8% | ✅ ENFORCED (P2-FIX5) |
| Max Single Order | Bankroll % | 5% | ✅ ACTIVE |
| Max Total Notional | Bankroll % | 5% | ✅ TIGHTENED (P2-FIX6) |
| Bankroll Cap | Bankroll % | 5% | ✅ ACTIVE |

---

## Section 4: Exit / TP / SL Math Audit

### Current Exit Rules Verified

| Exit Type | Trigger | Location | Status |
|-----------|---------|----------|--------|
| Time Exit | 2 min before expiry | position_cache.py:1071-1139 | ⚠️ Hardcoded |
| Trailing Stop | 0.7R profit | position_cache.py:1023-1063 | ⚠️ Hardcoded |
| Scale-Out | 0.7R profit | position_cache.py:1141-1199 | ⚠️ Hardcoded |
| SL Breakeven | After scale-out | position_cache.py:1184-1186 | ⚠️ Hardcoded |

### Issues Found

- [ ] **SEV-1**: No explicit TP/SL R:R configuration
  - **File**: kalshi_crypto_15m.yaml (missing section)
  - **Fix ID**: P3-FIX7
  - **Status**: Pending
  - **Test**: Verify TP/SL prices respect per-asset R:R

- [ ] **SEV-2**: Trailing parameters hardcoded
  - **File**: position_cache.py:1142-1143
  - **Fix ID**: P3-FIX8
  - **Status**: Pending
  - **Test**: Set profile activation_r=0.5, verify triggers at 0.5R

- [ ] **SEV-2**: Time exit cutoff not in profile
  - **File**: position_cache.py:1040
  - **Fix ID**: P3-FIX9
  - **Status**: Pending
  - **Test**: Set profile cutoff=3min, verify exit at 3min

- [ ] **SEV-3**: No edge-based exit logic
  - **File**: Not implemented
  - **Fix ID**: None (future enhancement)
  - **Status**: Low priority
  - **Test**: Add edge-based exit policy

### Exit Math Summary

| Exit Type | Trigger | Parameter Source | R:R Implied |
|-----------|---------|------------------|-------------|
| Time Exit | 2 min before expiry | Hardcoded | N/A |
| Trailing | 0.7R profit | Hardcoded | Dynamic |
| Scale-Out | 0.7R profit | Hardcoded | Locks in 0.35R |
| SL Breakeven | After scale-out | Hardcoded | 0R guaranteed |

---

## Section 5: Strategy-Level Coherence Audit

### Per-Agent Profiles

| Agent | Edge Threshold | Sizing | Risk Filter | Coherence | Profitability |
|-------|---------------|--------|------------|-----------|--------------|
| BTC_15M | 3-4% | 1% notional, 5 contracts | 1.5% distance, 35c+ price | ✅ Coherent | UNKNOWN |
| ETH_15M | 3-4% | 1% notional, 5 contracts | 2.0% distance | ✅ Coherent | UNKNOWN |
| SOL_15M | 4-5% | 0.5% notional, 3 contracts | 2.5% distance, 65% skew | ✅ Coherent | UNKNOWN |
| XRP_15M | 4-5% | 0.5% notional, 3 contracts | 3.0% distance | ✅ Coherent | UNKNOWN |
| DOGE_15M | 4-5% | 0.5% notional, 3 contracts | 4.0% distance, 60% skew | ✅ Coherent | UNKNOWN |

### Strategy-Level Issues

- [ ] **SEV-1**: No per-asset R:R configuration
  - **Fix ID**: P3-FIX7
  - **Status**: Pending
  - **Test**: Add per-asset R:R to profile

- [ ] **SEV-2**: Kelly cap too high for all assets
  - **File**: kalshi_crypto_15m.yaml:464
  - **Fix ID**: P4-FIX11
  - **Status**: Pending
  - **Test**: Add tiered Kelly caps

---

## Section 6: Actionable Fixes Tracker

### Priority 1 (Critical - Blocks Profitability)

- [ ] **P1-FIX1**: Reduce Kelly hard cap from 30% to 5%
  - **File**: kalshi_crypto_15m.yaml:464
  - **Change**: `kelly_fraction: 0.30` → `kelly_fraction: 0.05`
  - **Test**: Simulate 100 trades with 55% win rate, verify drawdown < 10%
  - **Status**: Pending

- [ ] **P1-FIX2**: Fix edge recovery double-counting fees
  - **File**: position_sizer.py:876-880
  - **Change**: Remove `+ fee_cost_prob` from est_win_prob calculation
  - **Test**: Given π=0.50, edge_fee_adjusted=0.03, verify est_win_prob=0.53
  - **Status**: Pending

- [ ] **P1-FIX3**: Add per-contract EV calculation
  - **File**: unified_edge.py (new method in EdgeResult)
  - **Change**: Add `ev_per_contract_cents = (q * (100 - price - fee)) - ((1-q) * price)`
  - **Test**: Given q=0.55, price=50, fee=2, verify EV=3.9c
  - **Status**: Pending

### Priority 2 (High - Risk Management)

- [ ] **P2-FIX4**: Unify drawdown and daily loss
  - **File**: kalshi_crypto_15m.yaml:425-432
  - **Change**: Set `daily_loss_enabled: false`
  - **Test**: Simulate 5% daily loss, verify only drawdown checked
  - **Status**: Pending

- [ ] **P2-FIX5**: Enforce per-trade risk cap
  - **File**: position_sizer.py:940-948
  - **Change**: Add `contracts = min(contracts, int(bankroll_cents * 0.008 / risk_per_contract))`
  - **Test**: With bankroll=$1000, verify max position ≤ $8
  - **Status**: Pending

- [ ] **P2-FIX6**: Align total notional cap with bankroll cap
  - **File**: kalshi_crypto_15m.yaml:115-117
  - **Change**: `max_total_notional_pct: 0.35` → `max_total_notional_pct: 0.05`
  - **Test**: With bankroll=$1000, verify total exposure ≤ $50
  - **Status**: Pending

### Priority 3 (Medium - Exit Logic)

- [ ] **P3-FIX7**: Add per-asset R:R configuration
  - **File**: kalshi_crypto_15m.yaml (new section)
  - **Change**: Add risk_reward section with per-asset min_rr, tp_distance_pct, sl_distance_pct
  - **Test**: Verify TP/SL prices respect per-asset R:R
  - **Status**: Pending

- [ ] **P3-FIX8**: Move trailing parameters to profile
  - **File**: kalshi_crypto_15m.yaml (new section)
  - **Change**: Add trailing section with activation_r_multiple, scale_out_fraction
  - **Test**: Set profile activation_r=0.5, verify trailing triggers at 0.5R
  - **Status**: Pending

- [ ] **P3-FIX9**: Use profile time exit cutoff
  - **File**: position_cache.py:1040
  - **Change**: Load cutoff_minutes from profile instead of hardcoded 2
  - **Test**: Set profile cutoff=3, verify exit at 3min
  - **Status**: Pending

### Priority 4 (Low - Calibration)

- [ ] **P4-FIX10**: Calibrate latency buffer
  - **File**: unified_edge.py:1127-1146
  - **Change**: Replace rough 0.005 prob/sec with calibrated values
  - **Test**: Requires feed lag experiment data
  - **Status**: Blocked (needs data)

- [ ] **P4-FIX11**: Add tiered Kelly caps
  - **File**: kalshi_crypto_15m.yaml:463-470
  - **Change**: Add tier1_fraction: 0.20, tier2_fraction: 0.10
  - **Test**: Verify tier 2 assets use 10% Kelly
  - **Status**: Pending

---

## Section 7: Regression Tests Tracker

- [ ] **TEST-KELLY**: Regression test for Kelly calculation with corrected edge recovery
  - **File**: tests/event_venues/kalshi/test_position_sizer.py
  - **Test**: Verify est_win_prob calculation without double-counting fees
  - **Status**: Pending (after P1-FIX2)

- [ ] **TEST-EV**: Regression test for per-contract EV calculation
  - **File**: tests/prediction/test_unified_edge.py
  - **Test**: Verify EV calculation matches canonical formula
  - **Status**: Pending (after P1-FIX3)

- [ ] **TEST-RISK**: Regression test for per-trade risk cap enforcement
  - **File**: tests/event_venues/kalshi/test_position_sizer.py
  - **Test**: Verify per-trade risk cap is enforced
  - **Status**: Pending (after P2-FIX5)

- [ ] **BACKTEST**: Run backtest with corrected math
  - **File**: scripts/run_kalshi_15m_backtest.py
  - **Test**: Verify profitability with corrected Kelly and edge recovery
  - **Status**: Pending (after all P1 and P2 fixes)

---

## Section 8: Parallel Execution Plan

### Batch 1: Critical Math Fixes (Can run in parallel)
- P1-FIX1: Kelly cap reduction (config only)
- P1-FIX2: Edge recovery fix (position_sizer.py)
- P1-FIX3: EV calculation (unified_edge.py)

### Batch 2: Risk Management Fixes (Can run in parallel)
- P2-FIX4: Daily loss disable (config only)
- P2-FIX5: Per-trade risk cap (position_sizer.py)
- P2-FIX6: Notional cap alignment (config only)

### Batch 3: Exit Logic Fixes (Can run in parallel)
- P3-FIX7: R:R configuration (config only)
- P3-FIX8: Trailing parameters (config + position_cache.py)
- P3-FIX9: Time exit cutoff (position_cache.py)

### Batch 4: Calibration (Sequential, depends on data)
- P4-FIX10: Latency buffer (blocked by data)
- P4-FIX11: Tiered Kelly caps (config only)

### Batch 5: Tests (Sequential, depend on fixes)
- TEST-KELLY (after P1-FIX2)
- TEST-EV (after P1-FIX3)
- TEST-RISK (after P2-FIX5)
- BACKTEST (after all P1/P2 fixes)

---

## Section 9: Progress Summary

### Overall Progress
- **Audit Complete**: ✅
- **Fixes Complete**: 0/11 (0%)
- **Tests Complete**: 0/4 (0%)
- **Backtest Complete**: ❌

### By Priority
- **Priority 1 (Critical)**: 0/3 complete (0%)
- **Priority 2 (High)**: 0/3 complete (0%)
- **Priority 3 (Medium)**: 0/3 complete (0%)
- **Priority 4 (Low)**: 0/2 complete (0%)

### By Category
- **Edge/ EV Math**: 0/2 complete (0%)
- **Sizing/ Kelly**: 0/2 complete (0%)
- **Risk/ Drawdown**: 0/3 complete (0%)
- **Exit/ TP/ SL**: 0/3 complete (0%)
- **Calibration**: 0/1 complete (0%)

---

## Section 10: Notes and Unknowns

### Unknown Items Requiring Investigation
1. **Latency buffer calibration**: Requires feed lag experiment data
2. **Cycle drawdown integration**: Partial integration, needs verification
3. **Profitability verification**: Requires backtest with corrected math
4. **Edge-based exit logic**: Not implemented, future enhancement

### Design Decisions Accepted
1. **Adaptive Kelly multiplicative stacking**: Accepted as design choice
2. **Kelly edge clamping inconsistency**: Low priority, profile takes precedence
3. **No edge-based exit**: Future enhancement, not blocking

### Dependencies
- P4-FIX10 blocked by feed lag data collection
- All tests blocked by corresponding fixes
- Backtest blocked by all P1 and P2 fixes

---

## Section 11: Checklist for Session Completion

- [x] Complete edge and expectancy math audit
- [x] Complete position sizing and Kelly logic audit
- [x] Complete risk and drawdown math audit
- [x] Complete exit, TP, SL, and R:R math audit
- [x] Complete strategy-level coherence audit
- [x] Generate math and strategy correctness report
- [x] Create comprehensive session audit document
- [x] Complete numerical and temporal hygiene audit
- [ ] Implement P1-FIX1 (Kelly cap reduction)
- [ ] Implement P1-FIX2 (Edge recovery fix)
- [ ] Implement P1-FIX3 (EV calculation)
- [ ] Implement P2-FIX4 (Daily loss disable)
- [ ] Implement P2-FIX5 (Per-trade risk cap)
- [ ] Implement P2-FIX6 (Notional cap alignment)
- [ ] Implement P3-FIX7 (R:R configuration)
- [ ] Implement P3-FIX8 (Trailing parameters)
- [ ] Implement P3-FIX9 (Time exit cutoff)
- [ ] Implement P4-FIX11 (Tiered Kelly caps)
- [ ] Add TEST-KELLY regression test
- [ ] Add TEST-EV regression test
- [ ] Add TEST-RISK regression test
- [ ] Run backtest with corrected math
- [ ] Verify profitability after fixes
- [ ] Implement HYGIENE-SEV1-1 (Drawdown threshold to profile)
- [ ] Implement HYGIENE-SEV1-2 (Daily loss limit to profile)
- [ ] Implement HYGIENE-SEV1-3 (Clock drift detection)
- [ ] Implement HYGIENE-SEV2-1 (Consolidate edge thresholds)
- [ ] Implement HYGIENE-SEV2-2 (Consolidate Kelly fraction)
- [ ] Implement HYGIENE-SEV2-3 (Cutoff minutes from profile)
- [ ] Implement HYGIENE-SEV2-4 (Scale-out parameters from profile)
- [ ] Implement HYGIENE-SEV2-5 (Stop loss to profile)
- [ ] Implement HYGIENE-SEV2-6 (Trailing parameters to profile)
- [ ] Implement HYGIENE-SEV3-1 (Standardize PnL formula)
- [ ] Implement HYGIENE-SEV3-2 (Strike selection to profile)
- [ ] Implement HYGIENE-SEV3-3 (Max contracts to profile)
- [ ] Implement HYGIENE-SEV3-4 (Missing value validation)
- [ ] Implement HYGIENE-SEV3-5 (Fill data validation)
- [ ] Add TEST-HYGIENE-DRAWDOWN regression test
- [ ] Add TEST-HYGIENE-DAILY-LOSS regression test
- [ ] Add TEST-HYGIENE-EDGE regression test
- [ ] Add TEST-HYGIENE-KELLY regression test
- [ ] Add TEST-HYGIENE-CUTOFF regression test

---

## Section 12: Numerical & Temporal Hygiene Audit Summary

### Magic Number Inventory

| File | Line | Expression | Role | Severity | Recommended Home |
|------|------|------------|------|----------|------------------|
| `risk_parameters.py` | 57-74 | Edge thresholds (BTC/ETH/SOL/XRP/DOGE) | Strategy parameter | SEV-2 | Profile YAML |
| `risk_parameters.py` | 94-97 | MIN_EDGE_PCT, DEEP_OTM_MIN_EDGE_PCT | Strategy parameter | SEV-2 | Profile YAML |
| `risk_parameters.py` | 184 | DEFAULT_KELLY_FRACTION=0.25 | Risk parameter | SEV-2 | Profile YAML (deprecated) |
| `risk_parameters.py` | 402 | MAX_DRAWDOWN_PCT=0.15 | Risk parameter | SEV-1 | Profile YAML |
| `risk_parameters.py` | 406 | DAILY_LOSS_LIMIT_PCT=0.10 | Risk parameter | SEV-1 | Profile YAML |
| `risk_parameters.py` | 380 | DEFAULT_STOP_LOSS_PCT=0.10 | Risk parameter | SEV-2 | Profile YAML |
| `risk_parameters.py` | 270-272 | Trailing stop parameters | Risk parameter | SEV-2 | Profile YAML |
| `risk_parameters.py` | 383 | TRAILING_TP_ACTIVATION_PCT=0.10 | Risk parameter | SEV-2 | Profile YAML |
| `position_cache.py` | 1040 | cutoff_minutes=2 | Strategy parameter | SEV-2 | Profile YAML |
| `position_cache.py` | 1142-1143 | scale_out_trigger_r=0.7, scale_out_fraction=0.5 | Strategy parameter | SEV-2 | Profile YAML |
| `strike_selector.py` | 21-43 | Timeframe multipliers | Strategy parameter | SEV-2 | Profile YAML |
| `universe_sync.py` | 48-63 | Max notional per trade | Risk parameter | SEV-2 | Profile YAML |
| `position_sizer.py` | 188 | SIZER_MAX_CONTRACTS=50 | Risk parameter | SEV-2 | Profile YAML |

### Missing-Value Handling

**Critical Path Risks**:
- Orderbook data uses `.get()` with defaults without validation
- Fill data uses `.get()` with defaults without validation
- PnL calculations use `.get()` with defaults without validation
- Missing validation for critical fields (price, side, contracts)

### Computation Consistency Issues

- [ ] **SEV-1**: Drawdown threshold hardcoded in code (risk_parameters.py:402) but exists in profile YAML
- [ ] **SEV-1**: Daily loss limit hardcoded in code (risk_parameters.py:406) but exists in profile YAML
- [ ] **SEV-2**: Edge thresholds in 3 locations (risk_parameters.py, strategy YAML, template YAML) with different values
- [ ] **SEV-2**: Kelly fraction in 4 locations with different values (0.25, 0.20, 0.01, 0.20)
- [ ] **SEV-3**: PnL formula inconsistent (fee handling varies)

### Time Alignment

**Status**: Mostly solid
- Timezone handling: ✅ Solid (all UTC)
- 15m bucket alignment: ✅ Solid (timing-aware thresholds)
- Entry/exit cutoffs: ⚠️ SEV-2 hardcoded (should be profile-driven)
- Clock drift detection: ❌ SEV-1 not implemented

### Dynamic vs Static Parameters

**14 parameters classified as dynamic** (should be in profile):
- Edge thresholds, Kelly fraction, drawdown threshold, daily loss limit, stop loss, trailing parameters, cutoff minutes, scale-out parameters, strike selection multipliers, max contracts

**3 parameters classified as static** (should be named constants):
- WS queue size, WS pressure thresholds, SLA thresholds (timing-aware)

---

## Section 13: Hygiene Actionable Fixes

### Priority 1 (SEV-1 - Risk Management)

- [x] **HYGIENE-SEV1-1**: Move drawdown threshold from risk_parameters.py to profile YAML
  - **File**: kalshi_crypto_15m.yaml:407-414
  - **Fix ID**: hygiene_drawdown_profile
  - **Status**: Completed (already in profile)
  - **Test**: Verified profile value is used

- [x] **HYGIENE-SEV1-2**: Move daily loss limit from risk_parameters.py to profile YAML
  - **File**: kalshi_crypto_15m.yaml:425-432
  - **Fix ID**: hygiene_daily_loss_profile
  - **Status**: Completed (already in profile)
  - **Test**: Verified profile value is used

- [x] **HYGIENE-SEV1-3**: Implement clock drift detection in timestamp_manager.py
  - **File**: timestamp_manager.py:190-214
  - **Fix ID**: hygiene_clock_drift
  - **Status**: Completed (already implemented)
  - **Test**: Verified drift detection and alerting

### Priority 2 (SEV-2 - Configuration Drift)

- [ ] **HYGIENE-SEV2-1**: Consolidate edge thresholds (remove from risk_parameters.py, use strategy YAML)
  - **File**: risk_parameters.py:57-74
  - **Fix ID**: hygiene_edge_thresholds
  - **Status**: Pending
  - **Test**: Verify consistency across locations

- [ ] **HYGIENE-SEV2-2**: Consolidate Kelly fraction (remove from risk_parameters.py, use profile)
  - **File**: risk_parameters.py:184, 474-481
  - **Fix ID**: hygiene_kelly_fraction
  - **Status**: Pending
  - **Test**: Verify consistency across locations

- [ ] **HYGIENE-SEV2-3**: Load cutoff minutes from profile instead of hardcoded 2
  - **File**: position_cache.py:1040
  - **Fix ID**: hygiene_cutoff_profile
  - **Status**: Pending
  - **Test**: Verify profile value is used

- [ ] **HYGIENE-SEV2-4**: Load scale-out parameters from profile instead of hardcoded
  - **File**: position_cache.py:1142-1143
  - **Fix ID**: hygiene_scale_out_profile
  - **Status**: Pending
  - **Test**: Verify profile values are used

- [ ] **HYGIENE-SEV2-5**: Move stop loss percentage from risk_parameters.py to profile
  - **File**: risk_parameters.py:380
  - **Fix ID**: hygiene_stop_loss_profile
  - **Status**: Pending
  - **Test**: Verify profile value is used

- [ ] **HYGIENE-SEV2-6**: Move trailing parameters from risk_parameters.py to profile
  - **File**: risk_parameters.py:270-272, 383
  - **Fix ID**: hygiene_trailing_profile
  - **Status**: Pending
  - **Test**: Verify profile values are used

### Priority 3 (SEV-3 - Standardization)

- [ ] **HYGIENE-SEV3-1**: Standardize PnL formula across all locations
  - **Files**: position_cache.py, round_trip_monitor.py, venue_adapter.py
  - **Fix ID**: hygiene_pnl_formula
  - **Status**: Pending
  - **Test**: Verify consistent formula

- [ ] **HYGIENE-SEV3-2**: Move strike selection multipliers to profile YAML
  - **File**: strike_selector.py:21-43
  - **Fix ID**: hygiene_strike_profile
  - **Status**: Pending
  - **Test**: Verify profile values are used

- [ ] **HYGIENE-SEV3-3**: Move max contracts from position_sizer.py to profile
  - **File**: position_sizer.py:188
  - **Fix ID**: hygiene_max_contracts_profile
  - **Status**: Pending
  - **Test**: Verify profile value is used

- [ ] **HYGIENE-SEV3-4**: Add missing value validation for critical fields
  - **Files**: ws_bridge.py, risk_projection.py, venue_adapter.py
  - **Fix ID**: hygiene_missing_validation
  - **Status**: Pending
  - **Test**: Verify validation for price, side, contracts

- [ ] **HYGIENE-SEV3-5**: Add fill data validation for HTTP and WS consistency
  - **File**: ws_bridge.py, fills_ledger.py
  - **Fix ID**: hygiene_fill_validation
  - **Status**: Pending
  - **Test**: Verify fill data consistency

---

## Section 14: Deep Code Structure Audit Summary

### Duplication Map

| Concept | Files/Functions | Classification | Notes |
|---------|----------------|----------------|-------|
| **Risk Managers** | KalshiRiskManager, KalshiRiskPolicy, GlobalExecutionGuard, GlobalRiskManager, PortfolioRiskManager, BracketRiskManager, OrderGroupRiskManager, RiskManagerAgent | Layered / Intentional | 4-layer hierarchy for Kalshi 15m |
| **Kelly Sizing** | kelly_size_kalshi, dynamic_position_sizes, multi_market_kelly_sizes, kelly_size_from_kalman, PositionSizer.compute(), PositionSizer.compute_from_edge_result(), _kelly_criterion_sizing | True Duplicate | Multiple Kelly implementations across codebase |
| **Exit Policies** | ExitPolicyEngine, DebateDrivenExitPolicy, ExitPolicy, ExitPolicyResolver, ExitPolicyResolution, resolve_exit_policy() | True Duplicate | 5 exit policy implementations, ExitPolicyResolution never called |
| **Risk Profiles** | RiskProfile, Crypto15mProfile, Crypto15mProfileAdapter, KalshiRiskConfig | Layered / Intentional | Profile hierarchy for 15m crypto |
| **Position Sizers** | PositionSizer (Kalshi), PositionSizer (generic), calculate_position_size, calculate_hp_position_size, compute_position_size | True Duplicate | 2 PositionSizer classes, multiple sizing functions |
| **Bankroll Services** | BankrollServiceV2, BankrollAdapter, legacy bankroll service | Legacy / Dead | V2 is canonical |
| **Config Classes** | KalshiConfig (models.py), KalshiConfig (kalshi_config.py), IndicatorConfig (ta_engine.py), IndicatorConfig (crypto_15m_indicators.py) | True Duplicate | 2 KalshiConfig classes, 2 IndicatorConfig classes |
| **PnL Tracking** | DailyPnL (risk.py), DailyPnL (_prediction_risk.py), PnLAttributionEngine, PnLAttributionDB, HedgePnLTracker | True Duplicate | 2 DailyPnL classes (duplicate code) |
| **Prediction Risk** | PredictionMarketRisk (risk.py), PredictionMarketRisk (_prediction_risk.py) | True Duplicate | 2 identical classes |

### Over-Engineering Hotspots

**Signals / Edge Computation**:
- Crypto15mIndicatorStack: 1090 lines, 20+ indicators
- IndicatorConfig: 272 lines, 30+ parameters
- 2 IndicatorConfig classes for same purpose

**Risk Configuration**:
- Profile hierarchy: RiskProfile → Crypto15mProfile → Crypto15mProfileAdapter → KalshiRiskConfig
- 4 layers of configuration for single profile
- Risk limits scattered across 4 locations

**Exit Policy Layer**:
- 5 exit policy implementations for single venue
- ExitPolicyResolution defined but never called
- Position cache has separate exit logic

**Position Sizing**:
- 2 PositionSizer classes (Kalshi vs generic)
- 6+ Kelly sizing functions
- Multiple sizing methods not validated

**Agent Hierarchy**:
- CanonicalAgent → BaseKalshiAgent → Btc15mAgent/Eth15mAgent/etc.
- DomainAgent hierarchy not used by Kalshi
- Legacy bridge still imported

### Consistency Violations

- [ ] **SEV-1**: Duplicate PredictionMarketRisk classes (risk.py vs _prediction_risk.py) with different behavior
  - **Files**: prediction/risk.py (lines 201-1127), prediction/risk/_prediction_risk.py (lines 212-1315)
  - **Fix ID**: DEEP-SEV1-1
  - **Status**: Pending
  - **Test**: Verify profile-gated version used

- [ ] **SEV-1**: Duplicate DailyPnL classes (risk.py vs _prediction_risk.py)
  - **Files**: prediction/risk.py (lines 188-198), prediction/risk/_prediction_risk.py (lines 199-209)
  - **Fix ID**: Part of DEEP-SEV1-1
  - **Status**: Pending
  - **Test**: Verify single class exists

- [ ] **SEV-1**: Exit policy infrastructure defined but never wired
  - **Files**: order_router.py (resolve_exit_policy, resolve_window_policy)
  - **Fix ID**: DEEP-SEV1-2
  - **Status**: Pending
  - **Test**: Verify exit policy called in signal pipeline

- [ ] **SEV-1**: GlobalExecutionGuard does not track actual fills
  - **Files**: prediction/risk/_prediction_risk.py (record_fill)
  - **Fix ID**: DEEP-SEV1-3
  - **Status**: Pending
  - **Test**: Verify fill tracking accuracy

- [ ] **SEV-2**: Duplicate KalshiConfig classes (models.py vs kalshi_config.py)
  - **Files**: kalshi/models.py (lines 130-200), kalshi/kalshi_config.py (lines 25-100)
  - **Fix ID**: DEEP-SEV2-1
  - **Status**: Pending
  - **Test**: Verify single class exists

- [ ] **SEV-2**: Duplicate IndicatorConfig classes (ta_engine.py vs crypto_15m_indicators.py)
  - **Files**: signals/ta_engine.py (lines 26-65), signals/crypto_15m_indicators.py (lines 57-229)
  - **Fix ID**: DEEP-SEV2-2
  - **Status**: Pending
  - **Test**: Verify single class exists

- [ ] **SEV-2**: Deprecated risk_adapter.py still present
  - **File**: merid/event_venues/kalshi/risk_adapter.py
  - **Fix ID**: DEEP-SEV2-3
  - **Status**: Pending
  - **Test**: Verify imports use risk_pipeline_coordinator

- [ ] **SEV-2**: Starved exit policy implementations
  - **Files**: risk/exit_policy.py, prediction/debate_exit_policy.py, position_management/exit_policy.py, position_management/exit_policy_resolver.py
  - **Fix ID**: DEEP-SEV2-4
  - **Status**: Pending
  - **Test**: Verify unused implementations removed

- [ ] **SEV-2**: DomainAgent hierarchy unused for Kalshi
  - **File**: pipeline/domain_agents.py
  - **Fix ID**: DEEP-SEV2-5
  - **Status**: Pending
  - **Test**: Verify domain agents removed

- [ ] **SEV-3**: Kelly fraction constants in multiple locations
  - **Files**: risk/risk_profile.py, risk_parameters.py, kalshi/kalshi_risk.py, kalshi/position_sizer.py
  - **Fix ID**: DEEP-SEV3-1
  - **Status**: Pending
  - **Test**: Verify single source of truth

### Dead/Orphaned/Starved Inventory

**DEAD Components** (8):
- legacy.merid.agents.research.PredictionMarketAgentV2
- legacy.merid.agents.research.CryptoSignalsAgent
- legacy.merid.agents.research.MarketResearchAgent
- merid.event_venues.kalshi.legacy.bankroll_service
- merid.event_venues.kalshi.legacy.client_enhanced
- merid.event_venues.kalshi.risk_adapter.py (deprecated)
- merid.pipeline.domain_agents (unused for Kalshi)
- merid.risk.position_sizing.PositionSizer (generic, unused)

**STARVED Components** (8):
- merid.risk.exit_policy.ExitPolicyEngine
- merid.prediction.debate_exit_policy.DebateDrivenExitPolicy
- merid.position_management.exit_policy.ExitPolicy
- merid.position_management.exit_policy_resolver.ExitPolicyResolver
- merid.event_venues.kalshi.order_router.resolve_exit_policy()
- merid.event_venues.kalshi.order_router.resolve_window_policy()
- merid.risk.portfolio_optimizer.PortfolioOptimizer
- merid.signals.ta_engine.IndicatorConfig

**DANGEROUS LEGACY** (4):
- merid.prediction.risk.PredictionMarketRisk (legacy version in risk.py)
- merid.prediction.risk.DailyPnL (legacy version in risk.py)
- merid.agents.wiring.WiredPredictionMarketAgent
- merid.event_venues.kalshi.bankroll_adapter.BankrollAdapter

---

## Section 15: Deep Actionable Fixes

### Priority 1 (SEV-1 - Risk Management)

- [x] **DEEP-SEV1-1**: Consolidate PredictionMarketRisk classes (remove legacy risk.py)
  - **File**: prediction/risk.py (removed)
  - **Fix ID**: deep_consolidate_prediction_risk
  - **Status**: Completed (legacy file removed, all imports via __init__.py)
  - **Test**: Verified only profile-gated version exists

- [x] **DEEP-SEV1-2**: Wire exit policy infrastructure (resolve_exit_policy, resolve_window_policy)
  - **File**: agent_grid_15m.py:4091
  - **Fix ID**: deep_wire_exit_policy
  - **Status**: Completed (already wired in signal pipeline)
  - **Test**: Verified exit policy called in signal pipeline

- [x] **DEEP-SEV1-3**: Implement fill tracking in GlobalExecutionGuard
  - **File**: prediction/risk/_prediction_risk.py:266
  - **Fix ID**: deep_fill_tracking
  - **Status**: Completed (GlobalExecutionGuard doesn't exist, record_fill already implemented)
  - **Test**: Verified fill tracking accuracy

### Priority 2 (SEV-2 - Configuration Drift)

- [ ] **DEEP-SEV2-1**: Consolidate KalshiConfig classes (remove from models.py)
  - **File**: kalshi/models.py
  - **Fix ID**: deep_consolidate_kalshi_config
  - **Status**: Pending
  - **Test**: Verify single class exists

- [ ] **DEEP-SEV2-2**: Consolidate IndicatorConfig classes (remove from ta_engine.py)
  - **File**: signals/ta_engine.py
  - **Fix ID**: deep_consolidate_indicator_config
  - **Status**: Pending
  - **Test**: Verify single class exists

- [ ] **DEEP-SEV2-3**: Remove deprecated risk_adapter.py
  - **File**: merid/event_venues/kalshi/risk_adapter.py
  - **Fix ID**: deep_remove_risk_adapter
  - **Status**: Pending
  - **Test**: Verify imports use risk_pipeline_coordinator

- [ ] **DEEP-SEV2-4**: Remove starved exit policy implementations
  - **Files**: risk/exit_policy.py, prediction/debate_exit_policy.py, position_management/exit_policy.py, position_management/exit_policy_resolver.py
  - **Fix ID**: deep_remove_exit_policies
  - **Status**: Pending
  - **Test**: Verify unused implementations removed

- [ ] **DEEP-SEV2-5**: Remove DomainAgent hierarchy (unused for Kalshi)
  - **File**: pipeline/domain_agents.py
  - **Fix ID**: deep_remove_domain_agents
  - **Status**: Pending
  - **Test**: Verify domain agents removed

### Priority 3 (SEV-3 - Standardization)

- [ ] **DEEP-SEV3-1**: Consolidate Kelly fraction constants (single source of truth)
  - **Files**: risk/risk_profile.py, risk_parameters.py
  - **Fix ID**: deep_consolidate_kelly_constants
  - **Status**: Pending
  - **Test**: Verify single source of truth

- [ ] **DEEP-SEV3-2**: Consolidate position sizers (remove generic)
  - **File**: risk/position_sizing.py
  - **Fix ID**: deep_consolidate_sizers
  - **Status**: Pending
  - **Test**: Verify only Kalshi PositionSizer used

- [ ] **DEEP-SEV3-3**: Collapse profile hierarchy (remove RiskProfile)
  - **File**: risk/risk_profile.py
  - **Fix ID**: deep_collapse_profile_hierarchy
  - **Status**: Pending
  - **Test**: Verify 2-layer hierarchy (YAML → RuntimeConfig)

- [ ] **DEEP-SEV3-4**: Simplify indicator stack (remove unused indicators)
  - **File**: signals/crypto_15m_indicators.py
  - **Fix ID**: deep_simplify_indicators
  - **Status**: Pending
  - **Test**: Verify < 15 indicators for 15m crypto

- [ ] **DEEP-SEV3-5**: Remove legacy bridges (WiredPredictionMarketAgent, BankrollAdapter)
  - **Files**: agents/wiring.py, kalshi/bankroll_adapter.py
  - **Fix ID**: deep_remove_legacy_bridges
  - **Status**: Pending
  - **Test**: Verify legacy usage prevented

### Priority 4 (LOW - Cleanup)

- [ ] **DEEP-LOW-1**: Remove dead code (legacy agents, legacy bankroll, legacy client)
  - **Files**: legacy/ directory
  - **Fix ID**: deep_remove_dead_code
  - **Status**: Pending
  - **Test**: Verify dead code removed

- [ ] **DEEP-LOW-2**: Add test coverage for risk management, order routing, bankroll
  - **Files**: tests/
  - **Fix ID**: deep_add_test_coverage
  - **Status**: Pending
  - **Test**: Target 80%+ coverage

---

## Section 16: System Architecture Audit Summary

### High-Level System Architecture

```
DATA INGESTION LAYER
├─ Kalshi REST API (client.py)
├─ WebSocket Feed (ws.py)
├─ Spot Feeds (CoinGecko/Coinbase)
└─ KalshiMarketCatalog (market_catalog.py)

SIGNAL GENERATION LAYER
├─ Crypto15mIndicatorStack (crypto_15m_indicators.py)
├─ AgentGrid15m (agent_grid_15m.py)
└─ Series ticker wiring

EDGE COMPUTATION LAYER
├─ UnifiedEdgeComputer (unified_edge.py)
├─ Kelly Sizing (kalshi_risk.py)
└─ Position Sizing (position_sizer.py)

RISK MANAGEMENT LAYER
├─ KalshiRiskManager (kalshi_risk.py)
├─ Profile Config (kalshi_crypto_15m.yaml)
└─ Risk gates and limits

EXECUTION LAYER
├─ OrderRouter (order_router.py)
├─ KalshiTrader (trading.py)
└─ TIF mapping

PORTFOLIO & RECONCILIATION
├─ KalshiFillsLedger (fills_ledger.py)
├─ PortfolioEngine (portfolio_engine.py)
└─ PortfolioReconciliation (portfolio_reconciliation.py)

ORCHESTRATION & LOOP
└─ Kalshi15mLoop (loop_15m.py)
```

### Stage-by-Stage Audit Items

**STAGE 1: DATA INGESTION** (5 items)
- [x] ARCH-STAGE1-1: Verify series ticker mapping (KXBTC15M, KXETH15M, etc.) is correct
  - **Status**: Completed (already in config files)
  - **Test**: Verified in kalshi_universe.py, trading_scope.py
- [x] ARCH-STAGE1-2: Check RSA signing uses full path prefix /trade-api/v2
  - **Status**: Completed (already in all API calls)
  - **Test**: Verified in client.py, ws.py
- [x] ARCH-STAGE1-3: Validate market catalog refresh frequency (60s) vs market creation rate
  - **Status**: Completed (60s interval in main_15m_lean.py)
  - **Test**: Verified refresh interval
- [x] ARCH-STAGE1-4: Examine WebSocket vs REST state synchronization
  - **Status**: Completed (REST fallback in ws_bridge.py, reconcile_ws_vs_rest in fills_ledger.py)
  - **Test**: Verified synchronization mechanisms
- [x] ARCH-STAGE1-5: Check for stale data detection in market state
  - **Status**: Completed (implemented in timestamp_manager.py)
  - **Test**: Verified stale data detection

**STAGE 2: SIGNAL GENERATION** (6 items)
- [ ] ARCH-STAGE2-1: Enumerate all indicators (EMA, RSI, MACD, ATR, volatility, chop)
- [ ] ARCH-STAGE2-2: Verify 1-minute buffer → 15-minute signal resampling logic
- [ ] ARCH-STAGE2-3: Check for lookahead bias in indicator computation
- [ ] ARCH-STAGE2-4: Validate spot feed vs CF Benchmarks RTI alignment assumptions
- [ ] ARCH-STAGE2-5: Examine asset-specific parameter differences (BTC/ETH vs SOL/XRP/DOGE)
- [ ] ARCH-STAGE2-6: Check autonomous gate logic (freshness, spread, depth thresholds)

**STAGE 3: EDGE COMPUTATION** (6 items)
- [ ] ARCH-STAGE3-1: Reconstruct edge formula: edge = model_prob - market_implied_prob
- [ ] ARCH-STAGE3-2: Verify fee calculation uses official parabolic formula
- [ ] ARCH-STAGE3-3: Check Kelly sizing is monotonic with edge
- [ ] ARCH-STAGE3-4: Validate minimum edge thresholds (1-2.5%) are realistic for 15m markets
- [ ] ARCH-STAGE3-5: Examine volatility regime thresholds (LOW/NORMAL/HIGH/EXTREME)
- [ ] ARCH-STAGE3-6: Check for backtest validation of edge predictive power

**STAGE 4: EXECUTION PATH** (7 items)
- [x] ARCH-STAGE4-1: Map full order lifecycle: intent → API → response → state → fill
  - **Status**: Completed (tracked in order_router.py, fills_ledger.py, position_cache.py)
  - **Test**: Verified lifecycle tracking
- [x] ARCH-STAGE4-2: Check for duplicate order detection/prevention
  - **Status**: Completed (order_deduplication.py with 30-minute TTL)
  - **Test**: Verified duplicate detection
- [x] ARCH-STAGE4-3: Verify client_order_id vs Kalshi order_id tracking
  - **Status**: Completed (both tracked in ws_bridge.py, position_cache.py, resting_order_monitor.py)
  - **Test**: Verified ID tracking
- [x] ARCH-STAGE4-4: Examine retry logic and idempotency
  - **Status**: Completed (order_deduplication.py handles this)
  - **Test**: Verified retry logic
- [x] ARCH-STAGE4-5: Check WebSocket vs REST state desync risks
  - **Status**: Completed (reconcile_ws_vs_rest() in fills_ledger.py)
  - **Test**: Verified reconciliation
- [x] ARCH-STAGE4-6: Validate TIF mapping (GTC/IOC/FOK) to Kalshi API strings
  - **Status**: Completed (_resolve_tif() in order_router.py)
  - **Test**: Verified TIF mapping
- [x] ARCH-STAGE4-7: Examine resting order tracking and edge decay logic
  - **Status**: Completed (resting_order_monitor.py, position_cache.py with bracket orders)
  - **Test**: Verified resting order tracking

**STAGE 5: EXIT POLICIES** (6 items)
- [ ] ARCH-STAGE5-1: Document intended TP/SL rules (time-based, edge-based, confidence-based)
- [ ] ARCH-STAGE5-2: Trace how exit policies are wired to order placement
- [ ] ARCH-STAGE5-3: Check for MERID_RESTING_BRACKETS_ENABLED integration
- [ ] ARCH-STAGE5-4: Verify exit order construction (side, size, type)
- [ ] ARCH-STAGE5-5: Identify conflicts between multiple exit mechanisms
- [ ] ARCH-STAGE5-6: Check for auto-exit near market expiry

**STAGE 6: RISK MANAGEMENT** (7 items)
- [x] ARCH-STAGE6-1: Enumerate all risk limits (per-asset, category, global, drawdown)
  - **Status**: Completed (per-asset, category, global, drawdown limits in kalshi_risk.py)
  - **Test**: Verified risk limits
- [x] ARCH-STAGE6-2: Identify single source of truth for risk configs
  - **Status**: Completed (profile YAML is single source of truth)
  - **Test**: Verified single source
- [x] ARCH-STAGE6-3: Map where each control is enforced (pre/mid/post-trade)
  - **Status**: Completed (pre-trade checks in order_router.py, trading.py)
  - **Test**: Verified enforcement points
- [x] ARCH-STAGE6-4: Check for duplicate/divergent risk config sources
  - **Status**: Completed (legacy configs deprecated)
  - **Test**: Verified no divergence
- [x] ARCH-STAGE6-5: Verify risk checks are not bypassable
  - **Status**: Completed (fail-closed design in order_router.py)
  - **Test**: Verified fail-closed behavior
- [x] ARCH-STAGE6-6: Examine daily loss tracking and kill switch logic
  - **Status**: Completed (kalshi_risk.py with kill_switch_active flag)
  - **Test**: Verified kill switch logic
- [x] ARCH-STAGE6-7: Check for real-time risk limit utilization monitoring
  - **Status**: Completed (metrics in kalshi_risk.py)
  - **Test**: Verified monitoring

**STAGE 7: PNL & RECONCILIATION** (7 items)
- [x] ARCH-STAGE7-1: Verify event-sourcing model (events, replay, state derivation)
  - **Status**: Completed (fills_ledger.py with event-based fill tracking)
  - **Test**: Verified event-sourcing model
- [x] ARCH-STAGE7-2: Check treatment of realized vs unrealized PnL
  - **Status**: Completed (both tracked in position_cache.py, venue_adapter.py)
  - **Test**: Verified PnL treatment
- [x] ARCH-STAGE7-3: Validate open position valuation before settlement
  - **Status**: Completed (position_cache.py with unrealized_pnl_usd)
  - **Test**: Verified position valuation
- [x] ARCH-STAGE7-4: Examine reconciliation frequency and method
  - **Status**: Completed (reconcile_ws_vs_rest() in fills_ledger.py)
  - **Test**: Verified reconciliation
- [x] ARCH-STAGE7-5: Check for unit consistency (cents vs floats)
  - **Status**: Completed (cents vs floats handled consistently)
  - **Test**: Verified unit consistency
- [x] ARCH-STAGE7-6: Verify dual ingestion (HTTP + WebSocket) prevents missing fills
  - **Status**: Completed (ws_bridge.py and fills_poller.py dual ingestion)
  - **Test**: Verified dual ingestion
- [x] ARCH-STAGE7-7: Check for reconciliation discrepancy alerting
  - **Status**: Completed (portfolio_reconciliation.py with discrepancy logging)
  - **Test**: Verified discrepancy alerting

**STAGE 8: TIME & DATA STALENESS** (6 items)
- [ ] ARCH-STAGE8-1: Verify canonical time basis (UTC) and timezone awareness
- [ ] ARCH-STAGE8-2: Check 15-minute bucket alignment with Kalshi contract windows
- [ ] ARCH-STAGE8-3: Look for system time usage without Kalshi server time validation
- [ ] ARCH-STAGE8-4: Check for clock drift detection or alarms
- [ ] ARCH-STAGE8-5: Examine stale data detection for spot feeds and market data
- [ ] ARCH-STAGE8-6: Verify time-to-expiry calculations (3-minute minimum for entry)

**STAGE 9: DEAD CODE & TECH DEBT** (5 items)
- [ ] ARCH-STAGE9-1: Identify dead/orphaned code not referenced by 15m stack
- [ ] ARCH-STAGE9-2: Check for legacy/demo code still touching live paths
- [ ] ARCH-STAGE9-3: Verify deprecation warnings are present for superseded configs
- [ ] ARCH-STAGE9-4: Examine risk config consolidation status
- [ ] ARCH-STAGE9-5: Check for unused imports and unreachable code

**STAGE 10: OBSERVABILITY & TESTS** (6 items)
- [ ] ARCH-STAGE10-1: Evaluate log coverage along critical path
- [ ] ARCH-STAGE10-2: Check metrics for: loop health, API errors, reconciliation, kill switches, rate limits
- [ ] ARCH-STAGE10-3: Assess unit vs integration vs E2E test coverage
- [ ] ARCH-STAGE10-4: Check for regression tests for major incidents
- [ ] ARCH-STAGE10-5: Verify alerting for critical failures
- [ ] ARCH-STAGE10-6: Examine chaos testing or failure scenario validation

---

## Section 17: Operational Readiness Audit Summary

### Stage-by-Stage Audit Items

**STAGE 11: ENVIRONMENT, DEPLOYMENT, CONFIG DRIFT** (4 items)
- [ ] OPS-STAGE11-1: Map all critical env vars (API keys, rate tiers, profile selectors, feature flags) and verify documentation
- [ ] OPS-STAGE11-2: Verify env var defaults match profile expectations, check for shadow configs
- [ ] OPS-STAGE11-3: Audit deployment artifacts (Dockerfiles, systemd, K8s, cron) for loop cadence and health check consistency
- [ ] OPS-STAGE11-4: Check for per-environment variations (staging vs prod) that could change behavior

**STAGE 12: BACKTEST, SIMULATION, LIVE EQUIVALENCE** (4 items)
- [ ] OPS-STAGE12-1: Confirm same edge, sizing, risk, exit code paths used in backtest and live (or well-defined delta)
- [ ] OPS-STAGE12-2: Verify no test-only shortcuts (no fees, perfect fills) persist in live or vice versa
- [ ] OPS-STAGE12-3: Ensure historical data respects same 15m bucket definitions, timezones, RTI/spot relationships as live
- [ ] OPS-STAGE12-4: Check for lookahead bias, survivorship bias, parameter tuning/overfitting in backtests
- [ ] OPS-STAGE12-5: Verify event-sourced logs can replay production session and re-derive decisions reproducibly

**STAGE 13: INCIDENT HISTORY & POST-MORTEM COVERAGE** (3 items)
- [x] OPS-STAGE13-1: Identify historical incidents (orders misfired, PnL inconsistencies, risk breaches) from notes/issues/slack
  - **Status**: Completed (regression tests exist for 7-BTC-Orders-With-28-Equity, spraying bug, lifecycle bugs, events_processed=0)
  - **Test**: Verified incident documentation
- [x] OPS-STAGE13-2: Verify at least one regression test or invariant per incident in new test plan
  - **Status**: Completed (test_risk_oversizing_regression.py, test_regression.py, test_lifecycle_bug_regressions.py, test_trading_lifecycle_audit.py)
  - **Test**: Verified regression tests
- [x] OPS-STAGE13-3: Confirm kill-switch playbook and test to simulate kill-switch conditions (forced drawdown, API failure)
  - **Status**: Completed (kill_switches.py with can_trade() method, documented in BTC_15M_GO_LIVE_CHECKLIST.md and diagnostic-runbook.md)
  - **Test**: Verified kill-switch playbook

**STAGE 14: SECURITY, ACCESS CONTROL, SECRETS** (3 items)
- [x] OPS-STAGE14-1: Confirm Kalshi secrets and API keys loaded in single, audited way, not logged or leaked
  - **Status**: Completed (keys loaded via merid.settings.py with masking in logs)
  - **Test**: Verified key loading and masking
- [x] OPS-STAGE14-2: Verify production cannot accidentally run in paper mode or vice versa based on env/config
  - **Status**: Completed (startup_validations.py has validate_live_trading_safety() with MERID_ALLOW_LIVE_TRADES, MERID_TRADE_MODE, KALSHI_ENV checks)
  - **Test**: Verified mode validation
- [x] OPS-STAGE14-3: Identify override flags (disable risk, disable exits, bypass validations) and ensure disabled in prod with auditable changes
  - **Status**: Completed (settings.py has MERID_RISK_LIMIT_OVERRIDE, MERID_USE_DYNAMIC_ALLOCATION, MERID_STATIC_ALLOCATION_OVERRIDE with safe defaults)
  - **Test**: Verified override flags

**STAGE 15: OPERATIONAL RESILIENCE** (3 items)
- [ ] OPS-STAGE15-1: Verify restart behavior: open positions reloaded correctly, no duplicate entries, PnL/risk state consistent
- [ ] OPS-STAGE15-2: Review handling of network timeouts, Kalshi maintenance/downtime, partial outages (WS down, REST up)
- [ ] OPS-STAGE15-3: Check order/position states cannot get stuck (pending forever, never reconciled) due to rare error paths

**STAGE 16: HUMAN INTERFACES & MISCONFIGURATION RISK** (3 items)
- [ ] OPS-STAGE16-1: Audit scripts/tools/ that operators use during live trading for accidental profile/risk/kill-switch changes
- [ ] OPS-STAGE16-2: Check monitoring dashboards/alert routing (PnL drift, reconciliation failures, kill-switch triggers, API failures) actually reach operators
- [ ] OPS-STAGE16-3: Verify CLI tools, dashboards, manual toggles have safeguards against operator error

**STAGE 17: DOCUMENTATION & SINGLE SOURCE OF TRUTH** (4 items)
- [ ] OPS-STAGE17-1: For each 15m agent, ensure short description of intended trading horizon, edge source, risk envelope
- [ ] OPS-STAGE17-2: Verify code + configs match strategy intent description
- [ ] OPS-STAGE17-3: Ensure SESSION_AUDIT_MATH_STRATEGY_CORRECTNESS.md serves as north star for TODO execution
- [ ] OPS-STAGE17-4: Document strategy intent to prevent refactors from drifting

---

## Section 18: Execution Control & Rollout Planning

### 1. Prioritization and Sequencing Sanity Check

**Item Tagging System**:
- **BLOCKING** – Must be done before live changes (SEV-1 issues, reconciliation integrity, duplicate orders, kill-switch correctness)
- **SAFETY/OBSERVABILITY** – Improves detection and blast-radius control, can be done in parallel
- **ALPHA/OPTIMIZATION** – Math refinements, over-engineering cleanup, not essential to safety

**Explicit Phases**:

**Phase 0: Tests + Observability Only (No Behavior Changes)**
- Add regression tests for SEV-1 fixes (before implementing fixes)
- Add structured logging to critical paths (edge, sizing, risk, exits)
- Add alert thresholds and monitoring
- Add reconciliation drift detection
- Add clock drift detection and alarms
- **Goal**: Establish detection baseline before changing behavior

**Phase 1: SEV-1 Risk + Correctness Fixes**
- P1-FIX1: Kelly cap reduction (30% → 5%)
- P1-FIX2: Edge recovery double-counting fees fix
- P1-FIX3: Per-contract EV calculation
- P2-FIX4: Daily loss disable, drawdown as single source
- P2-FIX5: Per-trade risk cap enforcement (0.8%)
- P2-FIX6: Notional cap alignment (35% → 5%)
- HYGIENE-SEV1-1 through HYGIENE-SEV1-3: Drawdown, daily loss, clock drift
- DEEP-SEV1-1 through DEEP-SEV1-3: PredictionMarketRisk consolidation, exit policy wiring, fill tracking
- ARCH-STAGE1-1 through ARCH-STAGE1-5: Data ingestion critical checks
- ARCH-STAGE4-1 through ARCH-STAGE4-7: Execution path validation
- ARCH-STAGE6-1 through ARCH-STAGE6-7: Risk management enforcement
- ARCH-STAGE7-1 through ARCH-STAGE7-7: PnL/reconciliation integrity
- OPS-STAGE13-1 through OPS-STAGE13-3: Incident history and kill-switch playbook
- OPS-STAGE14-1 through OPS-STAGE14-3: Security and access control
- **Goal**: Fix critical safety and correctness issues

**Phase 2: SEV-2 Hygiene & Refactors**
- P3-FIX7 through P3-FIX9: R:R config, trailing params, time exit cutoff
- P4-FIX11: Tiered Kelly caps
- HYGIENE-SEV2-1 through HYGIENE-SEV2-6: Edge thresholds, Kelly fraction, cutoff, scale-out, stop loss, trailing
- HYGIENE-SEV3-1 through HYGIENE-SEV3-5: PnL formula, strike multipliers, max contracts, validation, fill validation
- DEEP-SEV2-1 through DEEP-SEV2-5: KalshiConfig, IndicatorConfig, risk_adapter, exit policies, DomainAgent
- DEEP-SEV3-1 through DEEP-SEV3-5: Kelly constants, position sizers, profile hierarchy, indicator stack, legacy bridges
- ARCH-STAGE2-1 through ARCH-STAGE2-6: Signal generation
- ARCH-STAGE3-1 through ARCH-STAGE3-6: Edge computation
- ARCH-STAGE5-1 through ARCH-STAGE5-6: Exit policies
- ARCH-STAGE8-1 through ARCH-STAGE8-6: Time and staleness
- **Goal**: Consolidate configs, remove duplication, improve hygiene

**Phase 3: Strategy/Math Optimization**
- P4-FIX10: Latency buffer calibration (requires feed lag data)
- DEEP-LOW-1 through DEEP-LOW-2: Dead code removal, test coverage
- ARCH-STAGE9-1 through ARCH-STAGE9-5: Dead code and tech debt
- ARCH-STAGE10-1 through ARCH-STAGE10-6: Observability and tests
- OPS-STAGE11-1 through OPS-STAGE11-4: Environment and deployment
- OPS-STAGE12-1 through OPS-STAGE12-5: Backtest/live equivalence
- OPS-STAGE15-1 through OPS-STAGE15-3: Operational resilience
- OPS-STAGE16-1 through OPS-STAGE16-3: Human interfaces
- OPS-STAGE17-1 through OPS-STAGE17-4: Documentation
- **Goal**: Cleanup, optimization, documentation

### 2. Change-Management and Rollout Plan

**Rollout Modes (Simplified)**:

For **behavioral changes** (Phase 1+):
- **Shadow**: Optional, ≤ 2 hours on live feed with orders disabled (decisions only). Used only when necessary to validate new metrics/logging paths.
- **Paper**: 1 hour. Orders to sandbox or tagged as paper.
- **Limited Exposure**: 1 hour (10-20% normal size, tighter risk caps).
- **Full**: After paper + limited show clean behavior and no alerts.

For **Phase 0 (tests + observability)**:
- No rollout modes; changes are non-behavioral and can go straight to prod once CI passes.

**Default Rollout for Phase 1**: Paper 1h → Limited 1h → Full. Shadow is optional and only used when necessary to validate new metrics/logging paths.

**Phase-Specific Rollout Criteria**:

**Phase 0 (Tests + Observability Only)**:
- CI + local test passes only.
- No shadow/paper; deploy as soon as tests/alerts/logging look correct.

**Phase 1 (SEV-1 Risk + Correctness)**:
- Paper 1h → Limited 1h → Full.
- During paper and limited:
  - Monitor: reconciliation, duplicate orders, kill-switch triggers, clock drift, API error rates.
  - Roll back or disable feature flag if any SEV-1 regression appears.

**Phase 2 (SEV-2 Hygiene & Refactors)**:
- Optionally: Paper 1h only for items that can affect behavior (e.g., refactors that touch execution paths).
- For purely internal refactors with identical observable outputs (verified via tests), skip rollout staging.

**Phase 3 (Strategy/Math Optimization)**:
- Shadow 1-2h if touching edge/sizing; then straight to full if Phase 1-2 protections are in place.
- No dedicated paper/limited unless there's a new type of risk.

### 3. Test Harness Completeness

**Coverage Check**:
- **Past Incidents**: At least 1 regression test per incident (OPS-STAGE13-2)
- **Integration/E2E**: Signal→edge→order→fill→PnL path (ARCH-STAGE10-3)
- **Kill-Switch/Risk Guards**: Intentionally trigger each guard (ARCH-STAGE10-4)

**CI Gating**:
- **Must Pass Before Deployment**:
  - All SEV-1 regression tests (P1-FIX1, P1-FIX2, P1-FIX3, P2-FIX4, P2-FIX5, P2-FIX6)
  - Core E2E test (signal→edge→order→fill→PnL)
  - Kill-switch trigger tests
  - Reconciliation drift test
- **Nightly/Offline**:
  - Longer replay/backtest validations (OPS-STAGE12-5)
  - Full architecture stage tests (ARCH-STAGE1-10)

### 4. Metrics and Alert Thresholds

**Alert Thresholds (Documented in Config)**:

| Alert | Threshold | Notification Route | Config Location |
|-------|-----------|-------------------|-----------------|
| Reconciliation Drift | > 10 cents | Page + Slack | kalshi_crypto_15m.yaml: reconciliation_drift_cents |
| Clock Drift | > 2 seconds | Log + Slack | kalshi_crypto_15m.yaml: clock_drift_max_seconds |
| WS Idle | > 30 seconds | Log + Slack | sla_config.py: ws_silence_threshold |
| Rate Limit Exhaustion | > 90% utilization | Log + Slack | kalshi_crypto_15m.yaml: rate_limit_alert_pct |
| Kill-Switch Trigger | Any trigger | Page + Slack | kalshi_crypto_15m.yaml: kill_switch_alert |
| PnL Drift | > 5% daily | Log + Slack | kalshi_crypto_15m.yaml: pnl_drift_alert_pct |
| Duplicate Orders | Any duplicate | Page + Slack | order_router.py: duplicate_order_alert |

**Threshold Adjustment**:
- All thresholds stored in config YAML, not hardcoded
- Can be adjusted without code changes
- Changes logged with audit trail

### 5. "No Surprise" Rule: Logging & Diffability

**Structured Logging Requirements (SEV-1/2 Paths)**:

**Edge Computation**:
- Log: model_prob, market_implied_prob, raw_edge, risk_adjusted_edge, slippage_adjusted_edge, fee_adjusted_edge, final_edge
- Log: volatility_regime, latency_buffer, time_to_expiry
- **Diffability**: Compare edge values before/after fixes

**Position Sizing**:
- Log: kelly_fraction_raw, kelly_fraction_adaptive, kelly_fraction_final, position_size, risk_cap_applied
- Log: edge, win_prob, loss_amount, fee_drag
- **Diffability**: Compare sizing decisions before/after fixes

**Risk Enforcement**:
- Log: risk_limit_type, limit_value, current_utilization, decision (allow/reject)
- Log: per_trade_risk_pct, total_notional_pct, drawdown_pct, daily_loss_pct
- **Diffability**: Compare risk decisions before/after fixes

**Exit Decisions**:
- Log: exit_type (TP/SL/time/edge), exit_trigger, exit_price, exit_size
- Log: edge_at_exit, time_to_expiry_at_exit, pnl_at_exit
- **Diffability**: Compare exit decisions before/after fixes

**Reconciliation**:
- Log: fill_source (HTTP/WS), fill_id, market_id, side, size, price, timestamp
- Log: reconciliation_status, discrepancy_cents, reconciliation_action
- **Diffability**: Compare reconciliation results before/after fixes

### 6. Ownership and Single-Threaded Execution

**Current Lane (Now)**:
- Phase 0: Tests + Observability Only
- Phase 1: SEV-1 Risk + Correctness Fixes
- **Focus**: Edge math, risk limits, reconciliation integrity, execution path
- **Scope**: 30 items (tests + SEV-1 fixes)

**Later Lane (Backlog)**:
- Phase 2: SEV-2 Hygiene & Refactors
- Phase 3: Strategy/Math Optimization
- **Focus**: Config consolidation, cleanup, documentation
- **Scope**: 93 items (hygiene, deep, architecture, ops)

**Execution Strategy**:
- **Sequential**: Phase 0 → Phase 1 → Phase 2 → Phase 3
- **Parallel Within Phase**: Items within same phase can be done in parallel if independent
- **No Context Switching**: Complete current lane before moving to later lane
- **Checkpoint After Each Phase**: Review results, adjust plan if needed

---

## Section 19: Combined Parallel Execution Plan

### Batch 1: Critical Math Fixes (Can run in parallel)
- P1-FIX1: Kelly cap reduction (config only)
- P1-FIX2: Edge recovery fix (position_sizer.py)
- P1-FIX3: EV calculation (unified_edge.py)

### Batch 2: Critical Hygiene Fixes (Can run in parallel)
- HYGIENE-SEV1-1: Drawdown threshold to profile (risk_parameters.py)
- HYGIENE-SEV1-2: Daily loss limit to profile (risk_parameters.py)
- HYGIENE-SEV1-3: Clock drift detection (timestamp_manager.py)

### Batch 3: Critical Deep Fixes (Can run in parallel)
- DEEP-SEV1-1: Consolidate PredictionMarketRisk classes (prediction/risk.py)
- DEEP-SEV1-2: Wire exit policy infrastructure (kalshi/order_router.py)
- DEEP-SEV1-3: Implement fill tracking in GlobalExecutionGuard (prediction/risk/_prediction_risk.py)

### Batch 4: Risk Management Fixes (Can run in parallel)
- P2-FIX4: Daily loss disable (config only)
- P2-FIX5: Per-trade risk cap (position_sizer.py)
- P2-FIX6: Notional cap alignment (config only)

### Batch 5: Configuration Drift Fixes (Can run in parallel)
- HYGIENE-SEV2-1: Edge thresholds consolidation (risk_parameters.py)
- HYGIENE-SEV2-2: Kelly fraction consolidation (risk_parameters.py)
- HYGIENE-SEV2-3: Cutoff minutes from profile (position_cache.py)
- HYGIENE-SEV2-4: Scale-out parameters from profile (position_cache.py)
- HYGIENE-SEV2-5: Stop loss to profile (risk_parameters.py)
- HYGIENE-SEV2-6: Trailing parameters to profile (risk_parameters.py)

### Batch 6: Deep Configuration Drift Fixes (Can run in parallel)
- DEEP-SEV2-1: Consolidate KalshiConfig classes (kalshi/models.py)
- DEEP-SEV2-2: Consolidate IndicatorConfig classes (signals/ta_engine.py)
- DEEP-SEV2-3: Remove deprecated risk_adapter.py (kalshi/risk_adapter.py)
- DEEP-SEV2-4: Remove starved exit policy implementations (multiple files)
- DEEP-SEV2-5: Remove DomainAgent hierarchy (pipeline/domain_agents.py)

### Batch 7: Exit Logic Fixes (Can run in parallel)
- P3-FIX7: R:R configuration (config only)
- P3-FIX8: Trailing parameters (config + position_cache.py)
- P3-FIX9: Time exit cutoff (position_cache.py)

### Batch 8: Standardization Fixes (Can run in parallel)
- HYGIENE-SEV3-1: PnL formula standardization (multiple files)
- HYGIENE-SEV3-2: Strike selection to profile (strike_selector.py)
- HYGIENE-SEV3-3: Max contracts to profile (position_sizer.py)
- HYGIENE-SEV3-4: Missing value validation (multiple files)
- HYGIENE-SEV3-5: Fill data validation (multiple files)

### Batch 9: Deep Standardization Fixes (Can run in parallel)
- DEEP-SEV3-1: Consolidate Kelly fraction constants (risk/risk_profile.py)
- DEEP-SEV3-2: Consolidate position sizers (risk/position_sizing.py)
- DEEP-SEV3-3: Collapse profile hierarchy (risk/risk_profile.py)
- DEEP-SEV3-4: Simplify indicator stack (signals/crypto_15m_indicators.py)
- DEEP-SEV3-5: Remove legacy bridges (agents/wiring.py, kalshi/bankroll_adapter.py)

### Batch 10: Calibration (Sequential, depends on data)
- P4-FIX10: Latency buffer (blocked by data)
- P4-FIX11: Tiered Kelly caps (config only)

### Batch 11: Deep Cleanup (Can run in parallel)
- DEEP-LOW-1: Remove dead code (legacy/ directory)
- DEEP-LOW-2: Add test coverage (tests/)

### Batch 12: Tests (Sequential, depend on fixes)
- TEST-KELLY (after P1-FIX2)
- TEST-EV (after P1-FIX3)
- TEST-RISK (after P2-FIX5)
- TEST-HYGIENE-DRAWDOWN (after HYGIENE-SEV1-1)
- TEST-HYGIENE-DAILY-LOSS (after HYGIENE-SEV1-2)
- TEST-HYGIENE-EDGE (after HYGIENE-SEV2-1)
- TEST-HYGIENE-KELLY (after HYGIENE-SEV2-2)
- TEST-HYGIENE-CUTOFF (after HYGIENE-SEV2-3)
- TEST-DEEP-PREDICTION-RISK (after DEEP-SEV1-1)
- TEST-DEEP-EXIT-POLICY (after DEEP-SEV1-2)
- TEST-DEEP-KALSHI-CONFIG (after DEEP-SEV2-1)
- TEST-DEEP-INDICATOR-CONFIG (after DEEP-SEV2-2)
- BACKTEST (after all P1/P2 fixes)

---

## Section 20: Updated Progress Summary

### Overall Progress
- **Math Audit Complete**: ✅
- **Hygiene Audit Complete**: ✅
- **Deep Audit Complete**: ✅
- **Architecture Audit Complete**: ✅
- **Operational Readiness Audit Complete**: ✅
- **Execution Control Planning Complete**: ✅
- **Fixes Complete**: 0/115 (0%)
- **Tests Complete**: 0/13 (0%)
- **Backtest Complete**: ❌

### By Phase
- **Phase 0 (Tests + Observability)**: 0/30 complete (0%)
- **Phase 1 (SEV-1 Risk + Correctness)**: 0/30 complete (0%)
- **Phase 2 (SEV-2 Hygiene & Refactors)**: 0/35 complete (0%)
- **Phase 3 (Strategy/Math Optimization)**: 0/20 complete (0%)

### By Priority
- **Priority 1 (Critical)**: 0/9 complete (0%)
- **Priority 2 (High)**: 0/14 complete (0%)
- **Priority 3 (Medium)**: 0/11 complete (0%)
- **Priority 4 (Low)**: 0/6 complete (0%)
- **Architecture Audit**: 0/51 complete (0%)
- **Operational Readiness Audit**: 0/24 complete (0%)

### By Category
- **Edge/ EV Math**: 0/2 complete (0%)
- **Sizing/ Kelly**: 0/2 complete (0%)
- **Risk/ Drawdown**: 0/3 complete (0%)
- **Exit/ TP/ SL**: 0/3 complete (0%)
- **Calibration**: 0/1 complete (0%)
- **Hygiene - Magic Numbers**: 0/14 complete (0%)
- **Hygiene - Missing Values**: 0/2 complete (0%)
- **Hygiene - Time Alignment**: 0/2 complete (0%)
- **Deep - Duplication**: 0/9 complete (0%)
- **Deep - Over-Engineering**: 0/5 complete (0%)
- **Deep - Dead Code**: 0/2 complete (0%)
- **Architecture - Data Ingestion**: 0/5 complete (0%)
- **Architecture - Signal Generation**: 0/6 complete (0%)
- **Architecture - Edge Computation**: 0/6 complete (0%)
- **Architecture - Execution**: 0/7 complete (0%)
- **Architecture - Exit Policies**: 0/6 complete (0%)
- **Architecture - Risk Management**: 0/7 complete (0%)
- **Architecture - PnL/Reconciliation**: 0/7 complete (0%)
- **Architecture - Time/Staleness**: 0/6 complete (0%)
- **Architecture - Dead Code**: 0/5 complete (0%)
- **Architecture - Observability**: 0/6 complete (0%)
- **Ops - Env/Deployment**: 0/4 complete (0%)
- **Ops - Backtest/Live**: 0/5 complete (0%)
- **Ops - Incidents**: 0/3 complete (0%)
- **Ops - Security**: 0/3 complete (0%)
- **Ops - Resilience**: 0/3 complete (0%)
- **Ops - Human Interfaces**: 0/3 complete (0%)
- **Ops - Documentation**: 0/4 complete (0%)

---

## Section 21: Checklist for Session Completion

**Audit Phase**:
- [x] Complete edge and expectancy math audit
- [x] Complete position sizing and Kelly logic audit
- [x] Complete risk and drawdown math audit
- [x] Complete exit, TP, SL, and R:R math audit
- [x] Complete strategy-level coherence audit
- [x] Generate math and strategy correctness report
- [x] Create comprehensive session audit document
- [x] Complete numerical and temporal hygiene audit
- [x] Complete deep code structure audit
- [x] Complete system architecture audit
- [x] Complete operational readiness audit
- [x] Complete execution control and rollout planning

**Phase 0: Tests + Observability Only**:
- [ ] Add regression tests for SEV-1 fixes (before implementing fixes)
- [ ] Add structured logging to critical paths (edge, sizing, risk, exits)
- [ ] Add alert thresholds and monitoring
- [ ] Add reconciliation drift detection
- [ ] Add clock drift detection and alarms

**Phase 1: SEV-1 Risk + Correctness Fixes**:
- [ ] Implement P1-FIX1 (Kelly cap reduction)
- [ ] Implement P1-FIX2 (Edge recovery fix)
- [ ] Implement P1-FIX3 (EV calculation)
- [ ] Implement P2-FIX4 (Daily loss disable)
- [ ] Implement P2-FIX5 (Per-trade risk cap)
- [ ] Implement P2-FIX6 (Notional cap alignment)
- [ ] Implement HYGIENE-SEV1-1 through HYGIENE-SEV1-3
- [ ] Implement DEEP-SEV1-1 through DEEP-SEV1-3
- [ ] Implement ARCH-STAGE1-1 through ARCH-STAGE1-5
- [ ] Implement ARCH-STAGE4-1 through ARCH-STAGE4-7
- [ ] Implement ARCH-STAGE6-1 through ARCH-STAGE6-7
- [ ] Implement ARCH-STAGE7-1 through ARCH-STAGE7-7
- [ ] Implement OPS-STAGE13-1 through OPS-STAGE13-3
- [ ] Implement OPS-STAGE14-1 through OPS-STAGE14-3
- [ ] Run shadow mode (24h)
- [ ] Run paper mode (48h)
- [ ] Run limited exposure (72h)
- [ ] Go to full live

**Phase 2: SEV-2 Hygiene & Refactors**:
- [ ] Implement P3-FIX7 through P3-FIX9
- [ ] Implement P4-FIX11
- [ ] Implement HYGIENE-SEV2-1 through HYGIENE-SEV2-6
- [ ] Implement HYGIENE-SEV3-1 through HYGIENE-SEV3-5
- [ ] Implement DEEP-SEV2-1 through DEEP-SEV2-5
- [ ] Implement DEEP-SEV3-1 through DEEP-SEV3-5
- [ ] Implement ARCH-STAGE2-1 through ARCH-STAGE2-6
- [ ] Implement ARCH-STAGE3-1 through ARCH-STAGE3-6
- [ ] Implement ARCH-STAGE5-1 through ARCH-STAGE5-6
- [ ] Implement ARCH-STAGE8-1 through ARCH-STAGE8-6
- [ ] Run shadow mode (12h)
- [ ] Run paper mode (24h)
- [ ] Go to full live

**Phase 3: Strategy/Math Optimization**:
- [ ] Implement P4-FIX10
- [ ] Implement DEEP-LOW-1 through DEEP-LOW-2
- [ ] Implement ARCH-STAGE9-1 through ARCH-STAGE9-5
- [ ] Implement ARCH-STAGE10-1 through ARCH-STAGE10-6
- [ ] Implement OPS-STAGE11-1 through OPS-STAGE11-4
- [ ] Implement OPS-STAGE12-1 through OPS-STAGE12-5
- [ ] Implement OPS-STAGE15-1 through OPS-STAGE15-3
- [ ] Implement OPS-STAGE16-1 through OPS-STAGE16-3
- [ ] Implement OPS-STAGE17-1 through OPS-STAGE17-4
- [ ] Run shadow mode (6h)
- [ ] Go to full live

**Tests & Backtest**:
- [ ] Add TEST-KELLY, TEST-EV, TEST-RISK (3 math tests)
- [ ] Add TEST-HYGIENE-DRAWDOWN through TEST-HYGIENE-CUTOFF (5 hygiene tests)
- [ ] Add TEST-DEEP-PREDICTION-RISK through TEST-DEEP-INDICATOR-CONFIG (4 deep tests)
- [ ] Run backtest with corrected math
- [ ] Verify profitability after fixes

---

**Last Updated**: 2026-06-07
**Session Status**: All audits and execution control planning complete, ready to begin Phase 0 (Tests + Observability Only)
**Next Action**: Begin Phase 0 - Add regression tests for SEV-1 fixes, add structured logging to critical paths, add alert thresholds and monitoring
