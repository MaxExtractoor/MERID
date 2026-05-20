# Strategy Research Parameterization Guide

**Last Updated:** 2026-05-15  
**Scope:** Kalshi 15m Crypto Trading Stack (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

## Overview

This guide explains how to parameterize 15m-crypto strategy research using the canonical fee and drawdown primitives as variables rather than constants. This approach aligns with algo risk best practices for stress testing and continuous monitoring, where drawdown limits and exposure caps are part of the research parameter space.

---

## Philosophy

**Old Approach (Anti-Pattern):**
- Hardcoded fee rates in strategy code (e.g., `fee_rate = 0.07`)
- Hardcoded drawdown limits in strategy logic (e.g., `max_dd = 0.10`)
- Custom cost models for backtesting that differ from live
- Difficult to test new risk regimes without code changes

**New Approach (Canonical Primitives):**
- Fee calculation delegated to `fees.py` (single source of truth)
- Drawdown limits loaded from profile YAML (configurable)
- Same primitives used in backtest and live (equivalence)
- Risk regime testing via config changes, not code changes

---

## Research Parameter Space

### Fee Parameters

Fee parameters are controlled by the Kalshi fee schedule in `fees.py`. For research, you can:

1. **Test Sensitivity to Fee Changes**
   - Modify tier rates in `fees.py` temporarily for backtest
   - Run backtest to see PnL impact of fee schedule changes
   - Revert `fees.py` after testing

2. **Simulate New Fee Regimes**
   - Create a test profile with different fee assumptions
   - Use `replay_harness.py` to verify fee calculations
   - Compare backtest results under different fee regimes

**Example: Testing 1% Fee Increase**
```python
# In research backtest (temporary change)
# Original: rate = 0.07 for 1-99 contracts
# Test: rate = 0.08 for 1-99 contracts

# Run backtest
python scripts/backtest.py --profile test_high_fees --days 30

# Compare PnL with baseline
python scripts/compare_backtests.py baseline.json high_fees.json
```

### Drawdown Parameters

Drawdown parameters are controlled by profile YAML. For research, you can:

1. **Test Different Drawdown Limits**
   - Create test profile with modified `drawdown_halt_pct`, `drawdown_unwind_pct`
   - Run backtest to see how tighter/looser limits affect PnL
   - Compare risk-adjusted returns

2. **Stress Test Daily Loss Caps**
   - Create test profile with different `max_daily_loss_usd`
   - Run backtest to see how smaller/larger caps affect strategy
   - Analyze frequency of daily loss breaches

**Example: Testing Tighter Drawdown Limits**
```yaml
# config/profiles/kalshi_crypto_15m_tight_dd.yaml
profile_name: "kalshi_crypto_15m_tight_dd"
guardrails:
  drawdown_halt_pct: 0.05      # 5% halt (vs 10% baseline)
  drawdown_unwind_pct: 0.10    # 10% unwind (vs 15% baseline)
  max_daily_loss_usd: 100.0    # $100 cap (vs $200 baseline)
```

```bash
# Run backtest with tight DD profile
python scripts/backtest.py --profile kalshi_crypto_15m_tight_dd --days 30

# Compare with baseline
python scripts/compare_backtests.py baseline.json tight_dd.json
```

### Notional and Position Limits

Notional and position limits are controlled by profile YAML. For research, you can:

1. **Test Different Position Sizing**
   - Modify `max_notional_usd` in test profile
   - Modify `max_yes_position` / `max_no_position` in test profile
   - Analyze impact on PnL and risk

2. **Test Exposure Caps**
   - Modify `venue_max_single_order_pct` in test profile
   - Modify `max_cycle_risk_pct` in test profile
   - Analyze impact on trading frequency and PnL

**Example: Testing Larger Position Sizes**
```yaml
# config/profiles/kalshi_crypto_15m_large_size.yaml
agent_defaults:
  max_notional_usd: 2000.0    # $2000 (vs $1000 baseline)
  max_yes_position: 5          # 5 contracts (vs 3 baseline)
  max_no_position: 5           # 5 contracts (vs 3 baseline)
```

---

## Research Workflow

### Step 1: Define Research Question

Start with a clear research question about risk parameters:

- "How would PnL change if we halved the daily loss cap?"
- "What's the impact of a 1% fee increase on strategy profitability?"
- "Would tighter drawdown limits improve risk-adjusted returns?"
- "How does position sizing affect strategy performance?"

### Step 2: Create Test Profile

Copy the baseline profile and modify the parameters you want to test:

```bash
cp config/profiles/kalshi_crypto_15m.yaml config/profiles/kalshi_crypto_15m_research.yaml
# Edit the test profile with your research parameters
```

### Step 3: Run Backtest with Test Profile

Run the backtest using the test profile:

```bash
python scripts/backtest.py \
  --profile kalshi_crypto_15m_research \
  --start_date 2026-01-01 \
  --end_date 2026-04-30 \
  --output backtest_research.json
```

### Step 4: Compare with Baseline

Compare results with the baseline profile:

```bash
python scripts/compare_backtests.py \
  --baseline backtest_baseline.json \
  --test backtest_research.json \
  --output comparison.json
```

### Step 5: Analyze Results

Analyze the comparison to answer your research question:

- PnL difference
- Risk-adjusted returns (Sharpe ratio)
- Drawdown frequency and severity
- Trade frequency
- Fee impact

### Step 6: Document Findings

Document your findings in a research note:

```markdown
# Research Note: Daily Loss Cap Sensitivity

**Question:** How would PnL change if we halved the daily loss cap from $200 to $100?

**Method:**
- Created test profile with max_daily_loss_usd: 100.0
- Ran backtest for Q1 2026
- Compared with baseline ($200 cap)

**Results:**
- PnL decreased by 15% ($1200 → $1020)
- Sharpe ratio increased by 20% (0.5 → 0.6)
- Daily loss breaches increased from 2 to 8 days
- Maximum drawdown decreased from 12% to 8%

**Conclusion:** Tighter daily loss cap reduces PnL but improves risk-adjusted returns. Trade-off depends on risk appetite.
```

---

## Using Replay Harness for Research

The `replay_harness.py` script can be used for research to verify behavior under different parameters:

### Example: Fee Sensitivity Analysis

```bash
# Test with current fee schedule
python scripts/replay_harness.py \
  --fills q1_2026_fills.json \
  --profile kalshi_crypto_15m_v2 \
  --output replay_baseline.json

# Test with hypothetical higher fees (modify fees.py temporarily)
python scripts/replay_harness.py \
  --fills q1_2026_fills.json \
  --profile kalshi_crypto_15m_v2 \
  --output replay_high_fees.json

# Compare
python scripts/compare_replays.py replay_baseline.json replay_high_fees.json
```

### Example: Drawdown Path Analysis

```bash
# Test with baseline drawdown limits
python scripts/replay_harness.py \
  --fills q1_2026_fills.json \
  --profile kalshi_crypto_15m_v2 \
  --output replay_baseline_dd.json

# Test with tighter drawdown limits
python scripts/replay_harness.py \
  --fills q1_2026_fills.json \
  --profile kalshi_crypto_15m_tight_dd \
  --output replay_tight_dd.json

# Compare halt/unwind events
python scripts/compare_replays.py replay_baseline_dd.json replay_tight_dd.json
```

---

## Stress Testing Best Practices

### 1. Parameter Grid Search

Test a grid of parameter combinations to find optimal risk-return trade-off:

```python
# Example: Test different drawdown halt/unwind combinations
halt_pcts = [0.05, 0.10, 0.15]
unwind_pcts = [0.10, 0.15, 0.20]

for halt in halt_pcts:
    for unwind in unwind_pcts:
        if unwind <= halt:
            continue  # Invalid combination
        
        # Create test profile
        create_test_profile(halt, unwind)
        
        # Run backtest
        result = run_backtest(profile_name)
        
        # Store results
        grid_results.append((halt, unwind, result))
```

### 2. Monte Carlo Simulation

Use Monte Carlo simulation to test strategy robustness under parameter uncertainty:

```python
# Example: Test fee schedule uncertainty
fee_scenarios = [
    {'rate_1_99': 0.06, 'rate_100_999': 0.04, 'rate_1000': 0.02},  # Lower fees
    {'rate_1_99': 0.07, 'rate_100_999': 0.05, 'rate_1000': 0.03},  # Baseline
    {'rate_1_99': 0.08, 'rate_100_999': 0.06, 'rate_1000': 0.04},  # Higher fees
]

for scenario in fee_scenarios:
    # Modify fees.py temporarily
    apply_fee_scenario(scenario)
    
    # Run backtest
    result = run_backtest()
    
    # Store results
    monte_carlo_results.append((scenario, result))
```

### 3. Historical Stress Testing

Test strategy performance during historical stress periods (e.g., market crashes, high volatility):

```bash
# Test during Bitcoin crash (example date range)
python scripts/backtest.py \
  --profile kalshi_crypto_15m_v2 \
  --start_date 2022-05-01 \
  --end_date 2022-06-30 \
  --output backtest_crash.json

# Compare with normal period
python scripts/compare_backtests.py backtest_normal.json backtest_crash.json
```

---

## Integration with Live System

### Research to Production Workflow

When research identifies a better parameter set:

1. **Validate with Replay Harness**
   ```bash
   python scripts/replay_harness.py \
     --fills recent_fills.json \
     --profile new_profile \
     --output validation.json
   ```

2. **Generate Risk Snapshot**
   ```bash
   python scripts/generate_risk_snapshot.py \
     --output research_snapshot.json
   ```

3. **Compare with Current Profile**
   ```bash
   python scripts/compare_profiles.py \
     --current kalshi_crypto_15m_v2 \
     --proposed new_profile \
     --output profile_diff.json
   ```

4. **Get Risk Team Approval**
   - Present findings to risk team
   - Get approval for parameter changes

5. **Deploy with Monitoring**
   - Deploy new profile
   - Monitor dashboards closely for first 24 hours
   - Run surveillance reconciliation daily for first week

### Rollback Procedure

If new parameters cause issues:

1. **Trigger Kill-Switch**
   ```bash
   export MERID_KILL_SWITCH=true
   ```

2. **Revert Profile**
   ```bash
   # Revert to previous profile YAML
   git checkout HEAD~1 config/profiles/kalshi_crypto_15m.yaml
   ```

3. **Deploy Rollback**
   ```bash
   # Deploy rollback
   ```

4. **Post-Mortem**
   - Document what went wrong
   - Analyze why research didn't predict the issue
   - Update research methodology

---

## Common Research Pitfalls

### Pitfall 1: Overfitting to Historical Data

**Problem:** Optimizing parameters for historical performance that doesn't generalize.

**Solution:**
- Use walk-forward validation
- Test on out-of-sample data
- Consider parameter stability over time

### Pitfall 2: Ignoring Fee Impact

**Problem:** Optimizing for gross PnL without considering fee drag.

**Solution:**
- Always use `fees.py` in backtests
- Report net PnL (after fees)
- Analyze fee rate as a function of position size

### Pitfall 3: Ignoring Drawdown Impact

**Problem:** Optimizing for total return without considering drawdown risk.

**Solution:**
- Report risk-adjusted metrics (Sharpe ratio, Sortino ratio)
- Analyze maximum drawdown
- Consider drawdown duration

### Pitfall 4: Not Testing Parameter Robustness

**Problem:** Parameters work in one regime but fail in another.

**Solution:**
- Test across different market conditions
- Use Monte Carlo simulation
- Stress test with historical crises

---

## Research Tools

### Backtest Runner
```bash
python scripts/backtest.py --profile PROFILE --days 30
```

### Replay Harness
```bash
python scripts/replay_harness.py --fills FILLS.json --profile PROFILE
```

### Risk Snapshot Generator
```bash
python scripts/generate_risk_snapshot.py --output snapshot.json
```

### Surveillance Reconciliation
```bash
python scripts/surveillance_reconciliation.py --days 7
```

### Profile Comparator
```bash
python scripts/compare_profiles.py --current PROFILE1 --proposed PROFILE2
```

---

## References

- `docs/risk_primitives.md` - Canonical primitives documentation
- `config/profiles/kalshi_crypto_15m_template.yaml` - Profile template
- `scripts/replay_harness.py` - Backtest/live equivalence verification
- `scripts/surveillance_reconciliation.py` - Post-trade surveillance
- `docs/STRATEGY_ONBOARDING.md` - Strategy onboarding guide
