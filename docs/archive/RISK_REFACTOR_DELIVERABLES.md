# Risk Refactor Deliverables

## Summary

Refactored MERID Kalshi crypto trading system to use percent-of-equity risk sizing and enforce momentum-scalping-only trading.

---

## Files Modified

| File | Changes |
|------|---------|
| `config/portfolio_optimizer.yaml` | Replaced USD caps (`min_risk_usd_per_trade`, `max_risk_usd_per_trade`, `global_risk_budget`) with percent-of-equity equivalents. Added momentum-only enforcement config. |
| `merid/portfolio/optimizer.py` | Added `compute_risk_amount()` with edge-aware scaling, `set_equity()`, `is_strategy_allowed()`, dual-mode (USD/percent) risk cap application, momentum enforcement. |
| `tests/test_portfolio_optimizer_pct_equity.py` | **NEW** 16 tests covering percent sizing, edge scaling, global budget, momentum enforcement. |

---

## Updated Configuration Snippet

```yaml
portfolio_optimizer:
  # Percent-of-equity risk per trade (fixed fractional position sizing)
  # Values are fractions of current equity, e.g. 0.01 = 1% of equity
  # Band: 0.5% min → 2.0% max (hard cap per trade)
  min_risk_pct_per_trade: 0.005   # 0.5% minimum risk per trade
  max_risk_pct_per_trade: 0.02    # 2.0% maximum risk per trade (hard cap)
  
  # Global risk budget as percent of equity
  # Default: 3 assets × 2% max = 6% total portfolio risk
  max_risk_pct_global: 0.06       # 6% total portfolio risk budget
  
  # ═══════════════════════════════════════════════════════════════════════════
  # MOMENTUM SCALPING ENFORCEMENT (No Hold-to-Expiry)
  # ═══════════════════════════════════════════════════════════════════════════
  enforce_mean_reversion_only: true  # Block hold-to-expiry strategies
  
  momentum_scalp_config:
    max_hold_minutes: 60
    profit_target_pct: 0.15
    stop_loss_pct: 0.10
    require_price_based_exits: true
  
  # Strategy selection filter
  allowed_strategy_tags:
    - "momentum"
    - "scalping"
    - "mean_reversion"
  
  blocked_strategy_patterns:
    - ".*hold.*expiry.*"
    - ".*resolution.*based.*"
    - ".*expiry.*farmer.*"
  
  # Legacy USD caps (deprecated, kept for rollback compatibility)
  # min_risk_usd_per_trade: 0.40  # DEPRECATED - use min_risk_pct_per_trade
  # max_risk_usd_per_trade: 1.00 # DEPRECATED - use max_risk_pct_per_trade
  # global_risk_budget: 3         # DEPRECATED - use max_risk_pct_global
```

---

## Configuration Notes

### Adjusting Risk Percentages

To adjust risk without code changes, edit `config/portfolio_optimizer.yaml`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_risk_pct_per_trade` | 0.005 (0.5%) | Minimum risk per trade as fraction of equity |
| `max_risk_pct_per_trade` | 0.02 (2.0%) | Maximum risk per trade (hard cap) |
| `max_risk_pct_global` | 0.06 (6.0%) | Total portfolio risk across all positions |

**Examples:**
- Conservative: Set `max_risk_pct_per_trade: 0.01` (1%), `max_risk_pct_global: 0.03` (3%)
- Aggressive: Set `max_risk_pct_per_trade: 0.03` (3%), `max_risk_pct_global: 0.09` (9%)

### Enabling/Disabling Momentum-Only Mode

```yaml
# To enable momentum-only (current requirement)
enforce_mean_reversion_only: true

# To disable (for testing/rollback)
enforce_mean_reversion_only: false
```

When enabled, strategies must have one of the `allowed_strategy_tags` and must not match `blocked_strategy_patterns`.

### Rollback to USD Mode

If you need to rollback to USD-based caps:

```yaml
# Comment out percent caps
# min_risk_pct_per_trade: 0.005
# max_risk_pct_per_trade: 0.02

# Uncomment and set USD caps
min_risk_usd_per_trade: 0.40
max_risk_usd_per_trade: 1.00
global_risk_budget: 3
```

The system automatically detects USD mode when `min_risk_usd_per_trade > 0` or `max_risk_usd_per_trade > 0`.

---

## API Usage

### Setting Equity for Percent-Based Sizing

```python
from merid.portfolio.optimizer import PortfolioOptimizer

config = {
    "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
    "max_concurrent_assets": 3,
    "min_risk_pct_per_trade": 0.005,  # 0.5%
    "max_risk_pct_per_trade": 0.02,   # 2.0%
    "max_risk_pct_global": 0.06,      # 6%
}

optimizer = PortfolioOptimizer(config)
optimizer.set_equity(1000.0)  # $1000 account equity

# Get optimal portfolios with edge-aware sizing
portfolios = optimizer.select_optimal_portfolios(max_assets=3, num_choices=3)
```

### Computing Risk with Edge Scaling

```python
# Compute risk for a trade given equity and edge
risk = optimizer.compute_risk_amount(equity=1000.0, edge=0.05)
# With 0.5-2% band: 5% edge gives ~1.25% risk = $12.50
```

### Checking Strategy Eligibility

```python
# Check if strategy is allowed under momentum-only mode
is_allowed = optimizer.is_strategy_allowed(
    "BTC_Momentum", 
    strategy_tags=["momentum", "crypto"]
)
# Returns True if momentum-only is disabled OR tags include allowed tags
```

---

## Test Verification

Run the new test suite:

```bash
pytest tests/test_portfolio_optimizer_pct_equity.py -v
```

**Expected output:**
```
16 passed, 2 warnings in ~3s
```

Test categories:
- `TestPercentOfEquitySizing`: Edge scaling, clamping, linearity
- `TestGlobalRiskBudget`: Global budget enforcement
- `TestMomentumScalpingEnforcement`: Strategy filtering
- `TestPortfolioSelectionWithPercentSizing`: Top-N selection
- `TestConfigSerialization`: Config round-trip

---

## Key Implementation Details

### Edge-Aware Sizing Formula

```python
MAX_EDGE_FOR_SCALING = 0.10  # 10% edge = full scaling
edge_ratio = min(abs(edge), MAX_EDGE_FOR_SCALING) / MAX_EDGE_FOR_SCALING
risk_fraction = min_risk_pct + edge_ratio * (max_risk_pct - min_risk_pct)
risk_fraction = clamp(risk_fraction, min_risk_pct, max_risk_pct)
risk_amount = equity * risk_fraction
```

- Low edge (0-1%) → Near minimum risk
- Medium edge (5%) → Mid-range risk
- High edge (≥10%) → Maximum risk (hard capped at 2%)

### Dual-Mode Risk Caps

The `_apply_risk_caps()` method supports both modes:

1. **Percent mode** (new default): Uses `compute_risk_amount(equity, edge)` and scales by weight
2. **USD mode** (deprecated): Uses fixed USD values from config

Mode is auto-detected: USD mode activates when `min_risk_usd > 0` or `max_risk_usd > 0`.

---

## Notes

1. **No new public surface area**: All changes are config-level or internal wiring. No new endpoints or external APIs.

2. **Backward compatibility**: Legacy USD configs still work. The system detects mode based on which caps are set.

3. **Existing strategies already momentum-scalping**: The audit confirmed all crypto strategies (`Crypto15MStrategy`, `KalshiStrategy`) already use price-based TP/SL exits, not expiry-based. The enforcement flag is for future-proofing.

4. **Edge-aware sizing preserves top-3 selection**: The portfolio optimizer still ranks by Sharpe/return and selects top N, but now computes risk per asset using edge-adjusted percent sizing.
