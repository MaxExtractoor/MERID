# Risk Tuning Playbook for kalshi_crypto_15m Profile

## Overview

This playbook provides guidelines for safely adjusting risk parameters in the `kalshi_crypto_15m` profile based on observed performance metrics. The goal is to tune risk to optimize risk-adjusted returns while maintaining strict downside protection.

**Principle:** Small, incremental changes with validation after each adjustment. Never change multiple parameters simultaneously without clear rationale.

## Pre-Tuning Checklist

Before making any risk parameter changes:

1. **Verify baseline performance:**
   - Collect at least 100 trades per asset (BTC/ETH/SOL/XRP/DOGE)
   - Calculate Sharpe ratio, win rate, and max drawdown
   - Verify current profile is active: `MERID_PROFILE=kalshi_crypto_15m_v2`

2. **Run validation tests:**
   ```bash
   pytest tests/test_profile_balance_independence.py tests/test_profile_smoke_test.py tests/test_profile_stress_test.py
   ```

3. **Document current state:**
   - Note current parameter values
   - Record recent performance metrics
   - Identify specific reason for adjustment

## Parameter Categories

### 1. Per-Asset Notional Caps

**Location:** `config/profiles/kalshi_crypto_15m.yaml` → `assets.X.max_notional_usd`

**Current values:**
- BTC: $3,000
- ETH: $2,000
- SOL: $1,500
- XRP: $1,500
- DOGE: $1,000

**When to adjust:**
- **Increase if:** Asset consistently shows high Sharpe (>1.5) with stable win rate (>60%) and low drawdown (<5%)
- **Decrease if:** Asset shows high volatility, low win rate (<50%), or excessive drawdown (>10%)

**Adjustment guidelines:**
- Maximum single adjustment: ±20% of current value
- Minimum time between adjustments: 7 days
- Required validation: 50 trades post-adjustment before further changes

**Example:**
```
BTC Sharpe = 2.0, Win rate = 65%, Max drawdown = 3%
→ Increase BTC max_notional_usd from $3,000 to $3,600 (+20%)
→ Monitor for 50 trades, verify Sharpe remains >1.5
```

### 2. Edge Thresholds

**Location:** `config/profiles/kalshi_crypto_15m.yaml` → `assets.X.min_edge_*`

**Current values (BTC example):**
- min_edge_early: 0.020 (2.0%)
- min_edge_mid: 0.020 (2.0%)
- min_edge_late: 0.020 (2.0%)
- min_edge_terminal: 0.025 (2.5%)

**When to adjust:**
- **Decrease if:** Asset has insufficient trade volume (need more opportunities)
- **Increase if:** Win rate is too low (<50%) or losses are concentrated in low-edge trades

**Adjustment guidelines:**
- Maximum single adjustment: ±0.5 percentage points
- Maintain hierarchy: terminal ≥ late ≥ mid ≥ early
- Required validation: 100 trades post-adjustment

**Example:**
```
BTC trade volume too low, but win rate acceptable (58%)
→ Decrease min_edge_early from 2.0% to 1.5%
→ Monitor trade volume increase, verify win rate doesn't drop below 55%
```

### 3. Kelly Multipliers

**Location:** `config/profiles/kalshi_crypto_15m.yaml` → `confidence.kelly_multiplier_*`

**Current values:**
- kelly_multiplier_no_trade: 0.0
- kelly_multiplier_cautious: 0.5
- kelly_multiplier_quick_win: 0.6
- kelly_multiplier_confident: 1.0

**When to adjust:**
- **Increase if:** System consistently under-sizes positions that would have been profitable
- **Decrease if:** Kelly sizing leads to excessive volatility or drawdown

**Adjustment guidelines:**
- Maximum single adjustment: ±0.1
- Never exceed 1.5 for any multiplier
- Required validation: 100 trades post-adjustment

**Example:**
```
Confident trades show high win rate (70%) but position sizing too conservative
→ Increase kelly_multiplier_confident from 1.0 to 1.1
→ Monitor for increased volatility, verify drawdown stays under 10%
```

### 4. Guardrail Thresholds

**Location:** `config/profiles/kalshi_crypto_15m.yaml` → `guardrails.*`

**Current values:**
- max_spread_cents: 10
- max_slippage_cents: 3
- min_depth_contracts: 5
- min_post_fee_edge: 0.01 (1%)
- drawdown_halt_pct: 0.10 (10%)
- drawdown_unwind_pct: 0.15 (15%)
- max_daily_loss_usd: 200.0

**When to adjust:**
- **Spread/slippage:** Only if market structure changes (rare)
- **Depth:** Only if liquidity profile changes (rare)
- **Post-fee edge:** Adjust if fee structure changes
- **Drawdown thresholds:** Only after extensive analysis and testing

**Adjustment guidelines:**
- Drawdown thresholds: Maximum ±2 percentage points
- Daily loss cap: Maximum ±20% of current value
- Required validation: 200 trades post-adjustment for drawdown changes

**Example:**
```
Market volatility increased, current 10% drawdown halt too tight
→ Increase drawdown_halt_pct from 10% to 12%
→ Monitor for 200 trades, verify risk-adjusted returns improve
```

## Tuning Process

### Step 1: Data Collection

```python
# Collect performance metrics for each asset
metrics = {
    'BTC': {'sharpe': 1.8, 'win_rate': 0.62, 'max_dd': 0.04, 'trades': 150},
    'ETH': {'sharpe': 1.2, 'win_rate': 0.55, 'max_dd': 0.08, 'trades': 120},
    'SOL': {'sharpe': 0.9, 'win_rate': 0.48, 'max_dd': 0.12, 'trades': 100},
    'XRP': {'sharpe': 1.5, 'win_rate': 0.58, 'max_dd': 0.06, 'trades': 130},
    'DOGE': {'sharpe': 0.7, 'win_rate': 0.45, 'max_dd': 0.15, 'trades': 110},
}
```

### Step 2: Identify Adjustment Targets

Based on metrics:
- **BTC:** High Sharpe, low drawdown → Candidate for notional cap increase
- **SOL/DOGE:** Low Sharpe, high drawdown → Candidates for notional cap decrease
- **ETH/XRP:** Within acceptable range → No change needed

### Step 3: Plan Adjustment

```
Adjustment Plan:
1. Increase BTC max_notional_usd: $3,000 → $3,600 (+20%)
2. Decrease SOL max_notional_usd: $1,500 → $1,200 (-20%)
3. Decrease DOGE max_notional_usd: $1,000 → $800 (-20%)

Rationale:
- BTC shows strong risk-adjusted returns, can handle more exposure
- SOL/DOGE show weak performance, reduce exposure to limit downside

Validation: Monitor for 50 trades per asset post-adjustment
```

### Step 4: Implement Change

1. Update `config/profiles/kalshi_crypto_15m.yaml`
2. Update `docs/kalshi_crypto_15m_risk_model.md` if semantics changed
3. Run validation tests
4. Deploy with profile active

### Step 5: Monitor and Validate

```bash
# After 50 trades per asset, check:
- Sharpe ratio improved or maintained
- Max drawdown within acceptable bounds (<10%)
- Win rate stable or improved
- No new risk violations

If metrics degrade:
- Revert change
- Investigate root cause
- Consider smaller adjustment
```

## Risk Management During Tuning

### Safe Guards

1. **Never change multiple parameter categories simultaneously**
   - Only adjust notional caps OR edge thresholds OR Kelly multipliers at once
   - Wait for validation before next category

2. **Maintain invariant hierarchy**
   - Per-asset caps must be ≤ venue caps
   - Edge thresholds must maintain temporal hierarchy
   - Kelly multipliers must be ≤ 1.5

3. **Revert quickly if metrics degrade**
   - Have rollback plan ready before implementing change
   - Set clear stop-loss on performance metrics

### Warning Signs

**Immediate rollback required if:**
- Win rate drops below 40%
- Max drawdown exceeds 15%
- Sharpe ratio drops below 0.5
- New risk violations appear in logs

**Investigate required if:**
- Trade volume drops significantly (>50%)
- Win rate drops 10+ percentage points
- Position sizing behavior changes unexpectedly

## Emergency Procedures

### If risk limit breach occurs:

1. **Immediate action:**
   - Halt all 15m crypto trading
   - Check profile is active: `MERID_PROFILE=kalshi_crypto_15m_v2`
   - Verify profile values are correct

2. **Investigation:**
   - Review logs for breach reason
   - Check if profile was modified incorrectly
   - Verify gating logic is working

3. **Recovery:**
   - If profile error: Revert to last known good version
   - If gating error: Fix gating logic, re-run tests
   - If market condition: Adjust profile appropriately

### If system behaves unexpectedly:

1. **Disable profile temporarily:**
   ```bash
   unset MERID_PROFILE  # Fall back to legacy mode
   ```

2. **Investigate:**
   - Review recent profile changes
   - Check test results
   - Verify profile YAML syntax

3. **Re-enable when confident:**
   ```bash
   export MERID_PROFILE=kalshi_crypto_15m_v2
   # Run runtime self-check
   python -c "from merid.risk.profiles.crypto_15m_profile import runtime_profile_self_check; runtime_profile_self_check()"
   ```

## Documentation Requirements

Every profile adjustment must be documented in:

1. **Profile YAML changelog** (add comment in YAML):
   ```yaml
   # 2026-05-13: Increased BTC max_notional_usd to $3,600 based on Sharpe=2.0, WinRate=65%
   ```

2. **Design doc update** (if semantics changed):
   - Update `docs/kalshi_crypto_15m_risk_model.md`
   - Document rationale and expected impact

3. **Git commit message:**
   ```
   feat(kalshi_crypto_15m): Increase BTC max_notional_usd to $3,600

   Based on performance metrics: Sharpe=2.0, WinRate=65%, MaxDD=3%
   Validation: 50 trades post-adjustment required
   ```

## Reference Metrics

**Healthy ranges for 15m crypto trading:**

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Sharpe ratio | >1.0 | 0.5-1.0 | <0.5 |
| Win rate | >55% | 45-55% | <45% |
| Max drawdown | <8% | 8-12% | >12% |
| Trade frequency | >5/day | 2-5/day | <2/day |
| Position accuracy | >90% | 80-90% | <80% |

**Asset-specific considerations:**

- **BTC:** Lower volatility, can handle higher notional caps
- **ETH:** Moderate volatility, balanced approach
- **SOL/XRP:** Higher volatility, conservative caps
- **DOGE:** Highest volatility, most conservative caps

## Contact and Escalation

**For profile-related issues:**
- Review this playbook first
- Check test results: `pytest tests/test_profile_*.py`
- Review design doc: `docs/kalshi_crypto_15m_risk_model.md`
- Check runtime self-check logs

**For emergency rollback:**
- Revert profile YAML to last known good version
- Restart with profile disabled if needed
- Contact risk team if breach exceeds emergency thresholds
