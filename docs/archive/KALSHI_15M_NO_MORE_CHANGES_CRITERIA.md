# Kalshi 15m Microstructure v1 — No More Changes Criteria

**Version:** kalshi-15m-microstructure-v1
**Date:** 2026-05-13
**Purpose:** Define quantitative gates for freezing the lean 15m Kalshi stack and only allowing data-backed parameter nudges.

---

## Overview

The lean 15m Kalshi stack is now a microstructure-driven engine with:
- RTI, orderbook, volume, funding as core inputs
- SignalFusion microstructure signals: orderflow_bias, onchain_velocity
- Probability-space Kelly sizing tied to Kalshi prices
- Sentiment/social/news agents disabled

This document defines the criteria under which this stack is considered "stable" and should only be modified for:
- Breaking bugs
- Exchange changes
- Clear, data-backed parameter nudges

---

## 1. Minimum Sample Size Requirements

### Per Asset (BTC, ETH, SOL, XRP, DOGE)

**Minimum trades per asset:** 200 trades

**Rationale:** 
- 200 trades provides sufficient statistical power for hit rate estimation (±7% at 95% confidence for 50% base rate)
- At 96 15m periods/day, this represents ~2 days of continuous trading per asset
- Allows meaningful calibration analysis across p_model bins

**Alternative time-based gate:** 2 weeks of live trading

**Implementation:**
```python
MIN_TRADES_PER_ASSET = 200
MIN_WEEKS_LIVE = 2
```

### Total Sample Size

**Minimum total trades across all assets:** 500 trades

**Rationale:** 
- Provides sufficient data for cross-asset calibration and boost performance comparison
- Enables detection of regime shifts or market structure changes

---

## 2. Calibration Error Criteria

### p_model Bin Calibration

**Bins:** [0.40-0.45, 0.45-0.50, 0.50-0.55, 0.55-0.60, 0.60-0.65, 0.65-0.70]

**Acceptable calibration error per bin:** ±0.05 (±5 percentage points)

**Definition:**
```
calibration_error = realized_win_rate - avg_p_model
```

**Rationale:**
- ±5% allows for sampling noise while catching systematic mis-calibration
- If p_model predicts 55% win rate but realized is 45%, edge estimates are off by 10¢ - significant for binary options
- Based on microstructure literature showing short-horizon prediction errors typically <5% for well-calibrated models [arxiv:2602.00776]

**Action thresholds:**
- **Warning zone:** calibration error > 0.08 for any bin with n ≥ 20 trades
- **Critical zone:** calibration error > 0.12 for any bin with n ≥ 20 trades → require parameter adjustment

### Edge Estimate vs. Realized Outcome

**Acceptable edge error:** ±3¢ per trade

**Definition:**
```
edge_error = edge_estimate - realized_outcome
where realized_outcome = (100 - entry_price) if win else -entry_price
```

**Rationale:**
- 3¢ is ~6% of a 50¢ contract price
- Allows for market impact and timing noise while catching systematic edge overestimation

---

## 3. Max Drawdown Criteria

### Per Asset

**Maximum acceptable drawdown:** 15% of bankroll per asset

**Rationale:**
- 15% drawdown allows for volatility while preventing catastrophic losses
- With 5 assets, 15% each = 75% total theoretical exposure (unrealistic due to correlation)
- Fractional Kelly (0.25 shrink) and 10% cap should naturally limit drawdowns to <10% in well-behaved markets

### Total Portfolio

**Maximum acceptable drawdown:** 25% of total bankroll

**Rationale:**
- Accounts for correlated drawdowns across crypto assets
- Below typical "ruin" threshold (30-40%)
- Aligns with risk management best practices for crypto trading [flipster]

### Drawdown Duration

**Maximum drawdown duration:** 7 days

**Rationale:**
- 7-day drawdowns suggest regime shift or strategy breakdown
- Triggers review of strategy parameters and market conditions

---

## 4. Boost Performance Delta Criteria

### Boost vs. No-Boost Comparison

**Minimum performance uplift to justify keeping boosts:** 2% absolute hit rate improvement

**Definition:**
```
boost_hit_rate = wins / total_trades where prob_boost > 0
no_boost_hit_rate = wins / total_trades where prob_boost = 0
performance_delta = boost_hit_rate - no_boost_hit_rate
```

**Acceptable ranges:**
- **Keep boosts:** performance_delta ≥ 0.02 (2% absolute improvement)
- **Review zone:** 0.01 ≤ performance_delta < 0.02 (1-2% improvement)
- **Remove boosts:** performance_delta < 0.01 (less than 1% improvement)

**Rationale:**
- 2% absolute improvement is statistically significant for 200+ trades
- Justifies added complexity of SignalFusion integration
- Based on empirical studies showing orderflow imbalance provides 2-5% edge in short-horizon crypto [efmaefm]

### EV Uplift

**Minimum EV uplift:** 1¢ per trade

**Definition:**
```
boost_avg_ev = avg_pnl where prob_boost > 0
no_boost_avg_ev = avg_pnl where prob_boost = 0
ev_uplift = boost_avg_ev - no_boost_avg_ev
```

**Acceptable range:** ev_uplift ≥ 1¢

**Rationale:**
- 1¢ covers fees (Kalshi fee ~0.7¢ on 50¢ contract) and provides margin
- Ensures boosts add economic value, not just hit rate

---

## 5. Kelly Fraction Sanity Criteria

### Kelly Fraction Distribution

**Target median Kelly fraction:** 0.02 - 0.05 (2-5% of max position)

**Acceptable range:** 0.005 - 0.10 (0.5% - 10%)

**Rationale:**
- Median 2-5% indicates conservative sizing aligned with fractional Kelly (0.25 shrink)
- Upper bound of 10% is enforced by max_kelly_cap
- Lower bound of 0.5% ensures meaningful position sizes when edge is positive

### Kelly Fraction vs. p_model Calibration

**Expected relationship:**
```
kelly_fraction ≈ (p_model - p_market) / (p_market * (1 - p_market)) * 0.25
```

**Acceptable deviation:** ±20% from expected value

**Rationale:**
- Ensures Kelly sizing is consistent with probability estimates
- Catches bugs in Kelly calculation or edge estimation

---

## 6. On-Chain Velocity Gate Effectiveness

### Size Multiplier Distribution

**Expected distribution:**
- 0.5x multiplier: 20-40% of trades (when onchain_velocity < 0)
- 1.0x multiplier: 40-60% of trades (baseline)
- 1.2x multiplier: 10-20% of trades (when onchain_velocity > 1.0 and vol elevated)

**Acceptable deviation:** ±10% from expected ranges

**Rationale:**
- Ensures on-chain velocity gate is firing as expected
- Prevents gate from being always-on or always-off

### Performance by Multiplier

**Expected performance:**
- 1.2x trades: higher hit rate than 1.0x trades (by ≥1%)
- 0.5x trades: lower hit rate than 1.0x trades (by ≥1%)

**Rationale:**
- Validates that on-chain velocity is predictive of short-term moves
- If 1.2x trades underperform, gate is mis-calibrated

---

## 7. Parameter Nudge Procedure

When criteria indicate a parameter needs adjustment:

1. **Identify the failing metric** (e.g., calibration error > 0.12 in 0.55-0.60 bin)
2. **Propose a minimal adjustment** (e.g., reduce prob_boost from 0.03 to 0.025)
3. **Document the rationale** with data backing the change
4. **Implement in kalshi_btc_15m_agent_spec.py**
5. **Re-run validation criteria** after 100 trades with new parameters
6. **Commit with descriptive message** referencing this criteria document

### Allowed Parameters for Nudging

- `kelly_shrink` (current: 0.25)
- `max_kelly_cap` (current: 0.10)
- `prob_boost` thresholds (current: 0.02 moderate, 0.03 strong)
- `orderflow_bias` thresholds (current: 0.1 neutral, 0.2 moderate, 0.5 strong)
- `onchain_velocity` thresholds (current: 1.0 for size-up)
- `vol_baseline_multiplier` (for on-chain gate)

### Forbidden Changes Without Major Version Bump

- Adding new signal sources (e.g., new sentiment indicators)
- Changing the Kelly formula structure
- Removing microstructure signals (orderflow_bias, onchain_velocity)
- Re-enabling news/social sentiment agents
- Changing the fundamental regime signal generation logic

---

## 8. Freeze Conditions

The stack is considered "frozen" as **Kalshi 15m Microstructure v1** when:

1. ✅ All assets have ≥200 trades OR ≥2 weeks live
2. ✅ All p_model bins have calibration error within ±0.05
3. ✅ Max drawdown per asset <15%, total <25%
4. ✅ Boost performance delta ≥0.02 (2% hit rate improvement)
5. ✅ Kelly fraction distribution within 0.005 - 0.10 range
6. ✅ On-chain velocity gate firing within expected ranges

**Upon freeze:**
- Tag release as `kalshi-15m-microstructure-v1`
- Document final parameter values
- Create baseline performance report
- Only allow changes per Section 7 (Parameter Nudge Procedure)

---

## 9. Monitoring Dashboard Requirements

To enforce these criteria, build three dashboards:

### Calibration Dashboard
- p_model bins vs. realized win rate
- Calibration error per bin with warning/critical thresholds
- Edge estimate vs. realized outcome scatter plot

### Boost Performance Dashboard
- Hit rate comparison: prob_boost = 0 vs. > 0
- EV uplift comparison
- Performance by boost tier (none, moderate 0.02, strong 0.03)

### Risk Sanity Dashboard
- Kelly fraction histogram with target range overlay
- Drawdown curve per asset and total
- On-chain velocity gate multiplier distribution
- Pessimistic p_model simulation (shift -3% points, recompute Kelly)

---

## 10. Exception Handling

### Allowed Emergency Changes

**Breaking bugs:**
- Server crashes (e.g., access violations)
- Data corruption (e.g., position cache errors)
- API breaking changes (e.g., Kalshi endpoint deprecation)

**Exchange changes:**
- New asset listings
- Contract specification changes
- Settlement methodology updates

These changes bypass the criteria but must be:
- Documented in CHANGELOG.md
- Tagged with `[EMERGENCY]` in commit message
- Re-validated against criteria after deployment

---

## References

- Microstructure literature on orderflow imbalance: [efmaefm](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2025-Greece/papers/OrderFlowpaper.pdf)
- On-chain velocity as predictive signal: [coinrule](https://coinrule.com/blog/learn/the-impact-of-on-chain-and-trading-volumes-on-market-analysis/)
- Kelly criterion for crypto: [flipster](https://flipster.io/blog/position-sizing-strategies-for-crypto-trading/)
- Short-horizon crypto prediction: [arxiv:2602.00776](https://arxiv.org/html/2602.00776v1)
