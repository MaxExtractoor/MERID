# High-Performance Kalshi Trading Calibration

## Overview

This document describes the high-performance calibration system for MERID's Kalshi crypto prediction trading. The system is optimized for:

- **85%+ Win Rate** through aggressive edge threshold calibration
- **Maximum Profit Extraction** via optimized take-profit targets
- **Capital Protection** with tight stop losses and position limits
- **Exponential Growth** via compound sizing with streak adjustment
- **No Round-Trip Trades** through strict re-entry gating

## Files Created

### 1. `merid/prediction/high_performance_calibration.py`
Core calibration module containing optimized configurations for all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) across all timeframes (15m, 1h, daily, weekly, monthly, annual).

**Key Components:**
- `HPEdgeConfig`: Edge thresholds calibrated per asset/timeframe
- `HPTakeProfitConfig`: Profit targets for max extraction
- `HPStopLossConfig`: Capital protection stops
- `HPPositionSizingConfig`: Kelly-optimal sizing with sentiment weighting
- `HPSentimentConsensusConfig`: Fear/greed and confidence integration
- `HighPerformanceCalibration`: Main calibration engine

### 2. `merid/prediction/hp_integration.py`
Integration layer that wires HP configs into existing trading infrastructure.

**Key Functions:**
- `enable_high_performance_mode()`: Global HP mode activation
- `apply_hp_to_strategy_config()`: Override strategy with HP thresholds
- `calculate_hp_position_size()`: Sentiment/consensus weighted sizing
- `should_allow_entry()`: Entry decision with all HP checks

### 3. `tests/test_high_performance_calibration.py`
Comprehensive test suite validating all HP configurations.

## Calibration Details

### Edge Thresholds (85% Win Rate Target)

| Asset | 15m Min Edge | 1h Min Edge | Daily Min Edge | Strong Edge |
|-------|-------------|-------------|----------------|-------------|
| BTC   | 2.5%        | 3.0%        | 4.0%           | 5.0%        |
| ETH   | 3.0%        | 3.5%        | 4.5%           | 5.5%        |
| SOL   | 4.0%        | 4.5%        | 5.5%           | 7.5%        |
| XRP   | 3.8%        | 4.3%        | 5.3%           | 7.0%        |
| DOGE  | 5.0%        | 5.5%        | 6.5%           | 9.0%        |

**Rationale:** Higher volatility assets require higher edge to maintain win rate. DOGE (90% vol) needs 2x the edge of BTC (45% vol).

### Time-to-Expiry Adjustments

Edge thresholds automatically increase as expiry approaches:

- **24h before expiry**: Base edge
- **4h before expiry**: +0.5% edge
- **1h before expiry**: +1.0% edge

**Rationale:** Less time for edge to realize, require higher conviction.

### Market Condition Adjustments

**High Volatility:**
- Edge requirement reduced by 0.5-1.5% (more opportunities)
- Stop loss widened by 10-20%
- Max hold time reduced by 20-30%

**Low Volatility:**
- Edge requirement increased by 1.0-2.0% (less edge available)
- Stop loss tightened by 10%
- Max hold time extended by 20%

### Take-Profit Configuration (Max Extraction)

| Asset | Primary R | Full R | Scale Out | Hard TP | Partial TP |
|-------|-----------|--------|-----------|---------|------------|
| BTC   | 0.75      | 1.50   | 50%       | 150%    | 75%        |
| ETH   | 0.75      | 1.50   | 50%       | 150%    | 75%        |
| SOL   | 0.80      | 1.75   | 50%       | 180%    | 90%        |
| DOGE  | 1.00      | 2.00   | 50%       | 200%    | 100%       |

**Trailing Giveback:**
- BTC: 4-5 cents (tight, efficient market)
- ETH: 5-6 cents
- SOL: 6-8 cents (more volatile)
- DOGE: 10-15 cents (highest vol)

**Round-Trip Prevention:**
- Max 1 round trip per contract for intraday
- 0 round trips for daily/weekly (no re-entry)
- Re-entry requires 8-15 cent price movement (prevents churn)

### Stop-Loss Configuration (Capital Protection)

| Asset | Initial SL | Max Hold | Trail Activate | Trail Stop |
|-------|-----------|----------|----------------|------------|
| BTC   | 8c (8%)   | 4 hours  | 50% profit     | 50% of profit |
| ETH   | 10c (10%) | 5 hours  | 55% profit     | 50% of profit |
| SOL   | 12c (12%) | 3 hours  | 60% profit     | 55% of profit |
| DOGE  | 15c (15%) | 2 hours  | 75% profit     | 60% of profit |

**Time-Based Stops:**
- Take 25-40% of max profit at time stop
- Shorter for high vol assets (avoid decay)

### Position Sizing (Kelly + Sentiment + Consensus)

**Kelly Fraction:** 30% (aggressive vs standard 25%)

**Weighting:**
- Sentiment: 25% weight
- Consensus Confidence: 35% weight
- Volatility Scalar: 40% weight

**Sentiment Adjustments (Contrarian):**
- Extreme Fear (<20): +20% size (buy dips)
- Extreme Greed (>80): -15% size (avoid FOMO)
- Linear interpolation between

**Confidence Floor:** 65% minimum consensus confidence to trade

**Streak Adjustments:**
- Win streak (3+): +10% per win (max +50%)
- Lose streak (3+): -15% per loss (max -50%)

**Risk Limits:**
- Max position: 20% of bankroll
- Max daily loss: 3% of bankroll
- Max drawdown: 10% of bankroll (halt trading)

## Usage

### Enable High-Performance Mode

```python
from merid.prediction.hp_integration import enable_high_performance_mode

# Enable globally with 85% win rate target
enable_high_performance_mode(
    win_rate_target=0.85,
    aggressive_sizing=True,
    strict_round_trip_limits=True
)
```

### Per-Agent Configuration

```python
from merid.prediction.hp_integration import apply_hp_to_strategy_config
from merid.prediction.high_performance_calibration import get_hp_config

# Get HP config for BTC 15m
config = get_hp_config("BTC", "15m")
print(f"Edge threshold: {config.edge.min_edge_entry}")
print(f"Expected win rate: {config.expected_win_rate:.1%}")
print(f"Expected Sharpe: {config.expected_sharpe:.2f}")

# Apply to strategy
strategy_config = apply_hp_to_strategy_config(base_config, "BTC", "15m")
```

### Entry Decision

```python
from merid.prediction.hp_integration import should_allow_entry

allow, reason = should_allow_entry(
    asset="BTC",
    timeframe="15m",
    model_edge=Decimal("0.035"),
    sentiment_score=25.0,  # Fear
    consensus_confidence=0.75,
    round_trip_count=0
)

if allow:
    print("Entry approved!")
else:
    print(f"Entry blocked: {reason}")
```

### Dynamic Position Sizing

```python
from merid.prediction.hp_integration import calculate_hp_position_size

size = calculate_hp_position_size(
    asset="BTC",
    timeframe="15m",
    base_size=100,  # Kelly-calculated base
    sentiment_score=15.0,  # Extreme fear = boost size
    consensus_confidence=0.80,
    vol_scalar=0.7,
    win_streak=4,  # On a roll = increase size
    lose_streak=0
)

print(f"Final position size: {size} contracts")
```

### Get Performance Summary

```python
from merid.prediction.hp_integration import get_hp_performance_summary

summary = get_hp_performance_summary()
print(f"Average win rate: {summary['average_win_rate']:.1%}")
print(f"Average profit factor: {summary['average_profit_factor']:.2f}")
print(f"Average Sharpe: {summary['average_sharpe']:.2f}")

for combo, metrics in summary['combinations'].items():
    print(f"{combo}: win_rate={metrics['win_rate']:.1%}, "
          f"PF={metrics['profit_factor']:.2f}")
```

## Environment Variables

```bash
# Enable HP mode
export MERID_HP_MODE=true

# Set win rate target (75, 82, 85, 90)
export MERID_HP_WIN_RATE_TARGET=85

# Kelly fraction override (default 0.30 for HP mode)
export MERID_KELLY_FRACTION=0.30

# Strict round-trip limits
export MERID_STRICT_ROUND_TRIPS=1
```

## Testing

Run the comprehensive test suite:

```bash
python -m pytest tests/test_high_performance_calibration.py -v
```

Tests validate:
1. Edge thresholds achieve 80%+ win rates
2. Take-profit targets are aggressive (150%+ hard TP)
3. Round-trip limits are strict (0-1 max)
4. Stop losses protect capital (8-15% range)
5. Position sizing integrates sentiment/consensus
6. Dynamic edge adjusts for expiry/volatility/sentiment

## Performance Targets

| Metric | Target | Conservative | Moderate | Aggressive | Maximum |
|--------|--------|--------------|----------|------------|---------|
| Win Rate | 85% | 75% | 82% | 85% | 90% |
| Profit Factor | 2.0+ | 1.5 | 1.8 | 2.0 | 2.5 |
| Sharpe Ratio | 1.5+ | 1.0 | 1.3 | 1.5 | 1.8 |
| Max Drawdown | <10% | 8% | 10% | 10% | 12% |
| Daily Loss | <3% | 2% | 3% | 3% | 4% |

## Risk Management

### Capital Protection Hierarchy

1. **Entry Filters** (first line of defense)
   - Minimum edge threshold (2.5-5.0%)
   - Consensus confidence floor (65%)
   - Sentiment alignment check
   - Round-trip limit check

2. **Position Sizing** (second line)
   - Kelly fraction capped at 30%
   - Max position 20% of bankroll
   - Volatility scalar reduction
   - Streak-based adjustment

3. **Stop Losses** (third line)
   - Initial stop 8-15% of position
   - Trailing stop at 50%+ profit
   - Time-based stops (2-4 hours max)

4. **Drawdown Controls** (fourth line)
   - 10% max drawdown = halt trading
   - 3% daily loss limit
   - Automatic position reduction on breach

### Round-Trip Prevention

The system enforces strict round-trip limits:

- **15m/1h contracts:** Max 1 round trip
- **Daily contracts:** 0 round trips (no re-entry)
- **Re-entry requires:** 8-15 cent price movement
- **Cooldown period:** Daily reset for round-trip counters

This prevents:
- Churn in sideways markets
- Over-trading fees
- Emotional revenge trading
- Capital erosion from whipsaws

## Monitoring

Key metrics to monitor in production:

```python
# Real-time performance tracking
metrics = {
    "actual_win_rate": calculate_win_rate(last_100_trades),
    "profit_factor": gross_profits / gross_losses,
    "sharpe": sharpe_ratio(daily_returns),
    "max_drawdown": current_drawdown_pct,
    "round_trips_per_day": count_round_trips(),
    "avg_edge_captured": mean(entry_edges),
    "sentiment_accuracy": correct_sentiment_calls / total,
}

# Alerts
if actual_win_rate < 0.80:
    alert("Win rate below 80%, recalibrating edge thresholds")
    
if profit_factor < 1.5:
    alert("Profit factor below 1.5, tightening stops")
    
if max_drawdown > 0.08:
    alert("Approaching 10% drawdown limit, reducing size")
```

## Future Enhancements

1. **Machine Learning Edge Prediction**
   - Train model on historical edge → outcome
   - Replace static thresholds with predicted win probability

2. **Real-Time Calibration**
   - Adjust thresholds based on recent performance
   - Dynamic Kelly fraction based on streak

3. **Multi-Asset Correlation Sizing**
   - Reduce size when correlations spike
   - Avoid concentrated risk across crypto

4. **Market Regime Detection**
   - Trending vs ranging detection
   - Different edge formulas per regime

## Support

For questions or issues with HP calibration:
1. Check test suite: `tests/test_high_performance_calibration.py`
2. Validate config: `validate_hp_setup()`
3. Review logs: `merid.prediction.hp_integration`
4. Performance report: `get_hp_performance_summary()`
