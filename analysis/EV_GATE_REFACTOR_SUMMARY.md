# EV-Based Gate Refactor Summary (2026-05-13)

## Overview

Replaced the misaligned `prob_edge = |model_prob - 0.5|` gating logic with an EV-based framework that directly uses economic edge (expected value after fees) as the primary gate. This creates dynamic consistency across all 5 crypto 15m markets (BTC/ETH/SOL/XRP/DOGE) by using the same decision rule everywhere.

## Problem Solved

**Previous misalignment:**
- `prob_edge = abs(model_prob - 0.5)` measures distance from 50%, not profitability
- Asset-specific `min_prob_edge` thresholds (BTC: 0.08, SOL: 0.10, XRP/DOGE: 0.12) on a mis-specified metric
- Result: "strong signals" (prob_edge=0.495) with negative net_edge (-0.020) - untradeable
- System blocked trades that passed prob_edge gate but failed net_edge check

**New alignment:**
- `ev_net = model_prob - kalshi_price - fee_per_contract - slippage`
- Single global EV threshold (k * fee_per_contract) applied identically to all assets
- Extreme probability guard with stricter EV requirement when model is very confident
- Terminal phase guard now EV-based instead of prob_edge-based

## Changes Made

### 1. New EV Calculation Function (`merid/prediction/strategy.py:1580-1604`)

```python
def compute_ev_net(
    model_prob: float,
    kalshi_price: float,
    contracts: int = 1,
    slippage: float = 0.0001
) -> tuple[float, float]:
    """Compute expected value net of Kalshi fees.
    
    Returns:
        (ev_net, fee_per_contract)
    """
    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
    
    price_cents = int(kalshi_price * 100)
    fee_cents = calculate_kalshi_fee_cents(contracts, price_cents)
    fee_per_contract = fee_cents / 100.0 / contracts
    
    ev_gross = model_prob - kalshi_price
    ev_net = ev_gross - fee_per_contract - slippage
    
    return ev_net, fee_per_contract
```

### 2. Global EV Gate Parameters (Environment Variables)

```python
k_base = float(os.getenv("MERID_EV_K_BASE", "1.5"))      # Baseline safety margin
k_extreme = float(os.getenv("MERID_EV_K_EXTREME", "2.5")) # Extreme probability margin
k_terminal = float(os.getenv("MERID_EV_K_TERMINAL", "2.0")) # Terminal phase margin
```

### 3. Three-Tier EV Gate Structure

**Tier 1: Hard EV Constraint**
```python
if ev_net <= 0.0:
    block  # Never take negative EV trades
```

**Tier 2: Safety Margin Gate**
```python
min_ev_safety = winner_k_multiplier * fee_per_contract
if ev_net < min_ev_safety:
    block  # Compensate for model error
```

**Tier 3: Extreme Probability Guard**
```python
if p < 0.10 or p > 0.90:
    min_ev_extreme = k_extreme * fee_per_contract
    if ev_net < min_ev_extreme:
        block  # Extra caution in calibration risk zones
```

### 4. Terminal Phase Guard (EV-Based)

Replaced prob_edge-based terminal guard with EV-based version:
```python
min_ev_terminal = k_terminal * fee_per_contract
if ev_net < min_ev_terminal:
    block  # Stricter requirement near expiry
```

### 5. Winner Alignment

Arbiter winners get relaxed threshold:
```python
winner_k_multiplier = k_base * 0.7  # 30% relaxation for winners
```

### 6. Logging Updates

- Pre-gate logging now shows EV metrics instead of prob_edge
- Success logging shows ev_net, safety_k, fee_per_contract
- All gate blocks include EV context in eval_context

## Removed Logic

- Asset-specific `min_prob_edge` thresholds (no longer needed)
- `effective_min_prob_edge` calculation with conviction boost
- Prob_edge gate check (`if prob_edge < winner_min_prob_edge`)
- Final net_edge check (now integrated into EV gate)

## Preserved Logic

- Conviction veto threshold (still used for sizing, not gating)
- Conviction calculation (still used for position sizing)
- Structural conviction factor (still modulates position size)
- Winner alignment mechanism (still applies, but to EV threshold)

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MERID_EV_K_BASE` | 1.5 | Baseline safety margin multiplier |
| `MERID_EV_K_EXTREME` | 2.5 | Extreme probability margin multiplier |
| `MERID_EV_K_TERMINAL` | 2.0 | Terminal phase margin multiplier |

### Asset-Specific Thresholds (Deprecated)

The following are no longer used for gating:
- `min_prob_edge_low_tf` (was: BTC/ETH 0.08, SOL 0.10, XRP/DOGE 0.12)
- `min_prob_edge_high_tf` (was: BTC/ETH 0.05, SOL 0.08, XRP/DOGE 0.10)
- `prob_edge_boost_for_low_conviction` (was: 0.05-0.10)

These are preserved in `crypto_registry.py` for backward compatibility but not used in EV gate.

## Next Steps

### 1. Backtesting Required

Tune the three k parameters on historical data:

```bash
# Test different k_base values (1.0, 1.5, 2.0, 2.5)
MERID_EV_K_BASE=1.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m

# Test different k_extreme values (2.0, 2.5, 3.0)
MERID_EV_K_EXTREME=2.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m

# Test different k_terminal values (1.5, 2.0, 2.5)
MERID_EV_K_TERMINAL=2.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
```

**Metrics to track:**
- Trade count per asset (should be more consistent across assets)
- Win rate per asset (target: 60-70%)
- Sharpe ratio per asset (target: > 1.0)
- Maximum drawdown (target: < 10%)
- EV distribution (should be positive for all trades)

### 2. Optional: Mispricing Magnitude Threshold

If needed, add a secondary gate based on `mispricing_mag = abs(model_prob - kalshi_price)`:

```python
min_mispricing = float(os.getenv("MERID_MIN_MISPRICING", "0.02"))  # 2%
if abs(model_prob - kalshi_price) < min_mispricing:
    block  # Require minimum disagreement with market
```

This would be used for ranking opportunities, not hard blocking.

### 3. Monitor Live Performance

After deployment, monitor:
- EV gate block reasons distribution
- Trade count per asset (should reflect true opportunity, not threshold differences)
- Realized EV vs expected EV
- Calibration by model_prob bucket (especially extremes < 0.10, > 0.90)

## Verification

### Tests Passing

- `tests/test_config_validation.py`: 19/19 passing
- No syntax errors in modified `strategy.py`

### Code Review Checklist

- [x] EV calculation uses canonical Kalshi fee schedule
- [x] Gate is asset-agnostic (no per-asset thresholds)
- [x] Extreme probability guard integrated with EV threshold
- [x] Terminal phase guard converted to EV-based
- [x] Winner alignment preserved
- [x] Logging updated to show EV metrics
- [x] Backward compatibility maintained (prob_edge still computed for logging)
- [x] Environment variables documented
- [ ] Backtesting completed (TODO)
- [ ] Live monitoring setup (TODO)

## Files Modified

- `merid/prediction/strategy.py` (lines 1529-1858)
  - Added compute_ev_net function
  - Replaced prob_edge gate with EV gate
  - Updated terminal phase guard
  - Updated logging

## Files Unchanged (No Modifications Needed)

- `merid/event_venues/kalshi/fees.py` (already has correct fee calculation)
- `merid/prediction/model.py` (compute_edge still used, but gate moved to strategy)
- `merid/sentiment/crypto_registry.py` (thresholds preserved for backward compatibility)
- `config/kalshi_agent_grid.yaml` (no changes needed)

## Migration Notes

### For Operators

1. Set environment variables in your deployment:
   ```bash
   export MERID_EV_K_BASE=1.5
   export MERID_EV_K_EXTREME=2.5
   export MERID_EV_K_TERMINAL=2.0
   ```

2. Monitor logs for new gate reasons:
   - `ev_not_positive` (negative EV)
   - `ev_insufficient_margin` (below safety margin)
   - `extreme_probability_insufficient_ev` (extreme prob, insufficient EV)
   - `terminal_phase_guard_low_ev` (terminal phase, insufficient EV)

3. Update dashboards to show EV metrics instead of prob_edge

### For Developers

- The `prob_edge` variable is still computed for backward compatibility but not used for gating
- Asset-specific thresholds in `crypto_registry.py` are deprecated but not removed
- Conviction thresholds are still used for sizing, not gating
- All EV calculations use the canonical `calculate_kalshi_fee_cents` function

## Tuning Guide

### Overview

The three EV multipliers (k_base, k_extreme, k_terminal) control the safety margin required over fees for trades to pass the gate. These are asset-agnostic and scale with actual Kalshi fees, which vary with price.

### Parameter Descriptions

| Parameter | Default | Purpose | Tuning Range |
|-----------|---------|---------|--------------|
| `MERID_EV_K_BASE` | 1.5 | Baseline safety margin for all trades | 1.0 - 3.0 |
| `MERID_EV_K_EXTREME` | 2.5 | Extra margin when model_prob < 0.10 or > 0.90 | 2.0 - 4.0 |
| `MERID_EV_K_TERMINAL` | 2.0 | Stricter requirement in terminal phase (last hour) | 1.5 - 3.0 |

### Fee Structure

Kalshi fees follow the formula: `fee = rate * contracts * price * (1 - price) * 100`

- **Rate tiers:** 7% (1-100 contracts), 5% (101-1000), 3% (1001+)
- **Price dependence:** Fees are highest at 50c price (0.5 * 0.5 = 0.25), lower at extremes
- **Example:** At 50c with 7% rate: fee = 0.07 * 1 * 50 * 0.5 * 100 = 175 cents = $1.75 per contract

### Tuning Strategy

#### Step 1: Baseline Calibration (k_base)

Start with `MERID_EV_K_BASE=1.5` and run backtests on historical data:

```bash
# Test different k_base values
MERID_EV_K_BASE=1.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=1.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=2.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=2.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
```

**Metrics to track:**
- Trade count per asset (target: 5-20 per day per asset)
- Win rate per asset (target: 60-70%)
- Sharpe ratio per asset (target: > 1.0)
- Maximum drawdown (target: < 10%)
- EV distribution (mean, median, 5th percentile)

**Selection criteria:**
- Choose the lowest k_base that maintains:
  - Win rate ≥ 60%
  - Sharpe ratio ≥ 1.0
  - Drawdown ≤ 10%
- If k_base=1.0 fails, increase to 1.5, then 2.0

#### Step 2: Extreme Probability Calibration (k_extreme)

Once k_base is set, tune k_extreme for calibration safety:

```bash
# Test different k_extreme values (with fixed k_base)
MERID_EV_K_BASE=1.5 MERID_EV_K_EXTREME=2.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=1.5 MERID_EV_K_EXTREME=2.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=1.5 MERID_EV_K_EXTREME=3.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
```

**Metrics to track (for trades with model_prob < 0.10 or > 0.90):**
- Win rate in extreme region (target: 55-65%, slightly lower due to calibration risk)
- Calibration error: |actual win rate - model_prob|
- Trade count in extreme region (target: 10-20% of total trades)

**Selection criteria:**
- Choose k_extreme such that:
  - Extreme region win rate is within 5-10% of model_prob
  - Calibration error < 0.10
  - Not so high that it blocks all extreme trades (should allow some)

#### Step 3: Terminal Phase Calibration (k_terminal)

Tune k_terminal for expiry-phase risk:

```bash
# Test different k_terminal values
MERID_EV_K_BASE=1.5 MERID_EV_K_TERMINAL=1.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=1.5 MERID_EV_K_TERMINAL=2.0 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
MERID_EV_K_BASE=1.5 MERID_EV_K_TERMINAL=2.5 python -m backtesting.run --assets BTC ETH SOL XRP DOGE --timeframe 15m
```

**Metrics to track (for trades in last hour before expiry):**
- Win rate in terminal phase (target: 65-75%, should be higher due to time decay)
- Fill rate (target: > 80%, terminal trades should fill)
- Slippage (target: < 5 cents)

**Selection criteria:**
- Choose k_terminal such that:
  - Terminal phase win rate is highest (time decay favors correct side)
  - Fill rate remains acceptable
  - Not so high that it blocks all terminal trades

### Interaction Effects

The three parameters interact:

- **k_base vs k_extreme:** If k_base is already high (2.5), k_extreme may not need to be much higher
- **k_base vs k_terminal:** Terminal phase is inherently higher risk, so k_terminal should typically be ≥ k_base
- **k_extreme vs k_terminal:** Extreme probabilities in terminal phase are highest risk, may need k_extreme * k_terminal (not implemented, consider if needed)

### Recommended Starting Values

Based on prediction market best practices and Kalshi fee structure:

| Environment | k_base | k_extreme | k_terminal | Rationale |
|-------------|--------|-----------|------------|-----------|
| Development | 1.0 | 2.0 | 1.5 | Loose for testing, more trades |
| Staging | 1.5 | 2.5 | 2.0 | Moderate safety, realistic testing |
| Production | 1.5 | 2.5 | 2.0 | Balanced safety and opportunity |
| Conservative | 2.0 | 3.0 | 2.5 | Maximum safety, fewer trades |

### Monitoring After Deployment

Track these metrics per asset and per tier:

```python
# Example metrics to monitor
ev_gate_blocks_total{tier="TIER1_NEG_EV", asset="BTC"}
ev_gate_blocks_total{tier="TIER2_INSUFFICIENT_MARGIN", asset="BTC"}
ev_gate_blocks_total{tier="TIER3_EXTREME_GUARD", asset="BTC"}
ev_gate_blocks_total{tier="TERMINAL_PHASE_LOW_EV", asset="BTC"}

trades_passed_ev_gate_total{asset="BTC"}

ev_net_distribution_p50{asset="BTC"}
ev_net_distribution_p95{asset="BTC"}
ev_net_distribution_p99{asset="BTC"}
```

**Alert thresholds:**
- If TIER1_NEG_EV blocks > 50% of trades: Model is mis-calibrated, investigate
- If TIER2_INSUFFICIENT_MARGIN blocks > 80% of trades: k_base too high, consider lowering
- If TIER3_EXTREME_GUARD blocks > 30% of trades: k_extreme too high, consider lowering
- If trade count per asset drops by > 50% week-over-week: Gate too tight, investigate

### Backtest Command Reference

```bash
# Full backtest with all parameters
python -m backtesting.run \
  --assets BTC ETH SOL XRP DOGE \
  --timeframe 15m \
  --start_date 2026-01-01 \
  --end_date 2026-04-30 \
  --k_base 1.5 \
  --k_extreme 2.5 \
  --k_terminal 2.0 \
  --output backtest_results.json

# Quick validation test (1 week)
python -m backtesting.run \
  --assets BTC \
  --timeframe 15m \
  --days 7 \
  --k_base 1.5
```

## References

- Kalshi fee schedule: https://kalshi.com/fee-schedule
- Prediction market EV calculator: https://startpolymarket.com/tools/ev-calculator/
- CFTC prediction market rules: https://www.cftc.gov/sites/default/files/filings/orgrules/22/09/rule091222kexdcm003.pdf
