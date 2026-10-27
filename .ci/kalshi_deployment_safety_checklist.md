# Kalshi Deployment Safety Checklist

Automated safety checks to prevent "stupid contract" trades from reaching production.

## Purpose

Prevent deployment of changes that could cause:
- Lotto ticket behavior (trading deep OTM/ITM contracts with no edge)
- Model-market probability misalignment (buying when edge is insufficient)
- Unintended position sizing or exit strategy bypass

## Pre-Deployment Checks

### 1. Magic Numbers Compliance
**Status**: ✅ Automated via `tests/test_no_magic_numbers.py`

- Verify no hardcoded 50¢ fallbacks remain
- Verify all risk/sizing thresholds use centralized constants
- Verify probability bounds are enforced

**Run**: `py -m pytest tests/test_no_magic_numbers.py -v`

### 2. Deep OTM/ITM Exposure Check
**Status**: ⏳ To be implemented

Track and alert on contracts traded at extreme prices:
- Contracts below `DEEP_OTM_THRESHOLD_CENTS` (5¢)
- Contracts above `DEEP_ITM_THRESHOLD_CENTS` (95¢)

**Implementation**:
```python
from merid.event_venues.kalshi.risk_parameters import (
    DEEP_OTM_THRESHOLD_CENTS,
    DEEP_ITM_THRESHOLD_CENTS,
)

def check_deep_otm_itm_exposure(trades: List[Dict]) -> Dict[str, Any]:
    """Check for deep OTM/ITM contract exposure."""
    deep_otm = [t for t in trades if t['price_cents'] < DEEP_OTM_THRESHOLD_CENTS]
    deep_itm = [t for t in trades if t['price_cents'] > DEEP_ITM_THRESHOLD_CENTS]
    
    return {
        "deep_otm_count": len(deep_otm),
        "deep_itm_count": len(deep_itm),
        "deep_otm_tickers": [t['ticker'] for t in deep_otm],
        "deep_itm_tickers": [t['ticker'] for t in deep_itm],
        "thresholds": {
            "otm_cents": DEEP_OTM_THRESHOLD_CENTS,
            "itm_cents": DEEP_ITM_THRESHOLD_CENTS,
        }
    }
```

**Prometheus Metrics**:
```yaml
# metrics/prometheus/kalshi_safety_rules.yml
- name: kalshi_deep_otm_trades_total
  type: counter
  help: Total count of trades below deep OTM threshold (5¢)
  labels: [ticker, strategy]
  
- name: kalshi_deep_itm_trades_total
  type: counter
  help: Total count of trades above deep ITM threshold (95¢)
  labels: [ticker, strategy]
```

### 3. Model Probability Distance Check
**Status**: ⏳ To be implemented

Track `abs(model_prob - price_cents/100)` for each trade to detect misaligned entries.

**Implementation**:
```python
from merid.event_venues.kalshi.risk_parameters import MODEL_PROB_DISTANCE_THRESHOLD

def check_model_prob_distance(trades: List[Dict]) -> Dict[str, Any]:
    """Check for model-market probability misalignment."""
    misaligned = []
    
    for trade in trades:
        price_prob = trade['price_cents'] / 100.0
        model_prob = trade.get('model_prob')
        
        if model_prob is None:
            continue
            
        distance = abs(model_prob - price_prob)
        
        if distance > MODEL_PROB_DISTANCE_THRESHOLD:
            misaligned.append({
                "ticker": trade['ticker'],
                "price_cents": trade['price_cents'],
                "model_prob": model_prob,
                "distance": distance,
                "threshold": MODEL_PROB_DISTANCE_THRESHOLD,
            })
    
    return {
        "misaligned_count": len(misaligned),
        "misaligned_trades": misaligned,
        "threshold": MODEL_PROB_DISTANCE_THRESHOLD,
    }
```

**Prometheus Metrics**:
```yaml
- name: kalshi_model_prob_distance_histogram
  type: histogram
  help: Histogram of abs(model_prob - price_cents/100) for all trades
  buckets: [0.01, 0.02, 0.03, 0.05, 0.10, 0.20, 0.50]
  labels: [ticker, strategy]
```

### 4. Spot Regression Checker
**Status**: ⏳ To be implemented

Run dry-run backtest on historical data to check for extreme trades before deployment.

**Implementation**:
```python
# scripts/ci/kalshi_spot_regression_check.py

def run_spot_regression_check(
    historical_date: str,
    strategy_fn: Callable,
) -> Dict[str, Any]:
    """
    Run dry-run backtest on historical data to detect regressions.
    
    Checks:
    - Top 50 largest trades by size
    - 50 most extreme prices (lowest and highest)
    - Trades violating PF/expectancy gates
    - Trades without proper exit plans
    """
    # Load historical snapshots for date
    snapshots = load_historical_snapshots(historical_date)
    
    # Run backtest in dry-run mode
    result = backtest(
        snapshots,
        initial_cash_cents=500_000,
        strategy_fn=strategy_fn,
        dry_run=True,  # Don't actually execute
    )
    
    # Analyze trades
    trades = result.trade_log
    
    # Find extreme trades
    largest_trades = sorted(trades, key=lambda t: t['count'], reverse=True)[:50]
    lowest_prices = sorted(trades, key=lambda t: t['price_cents'])[:50]
    highest_prices = sorted(trades, key=lambda t: t['price_cents'], reverse=True)[:50]
    
    # Check for violations
    from merid.event_venues.kalshi.risk_parameters import (
        SIZER_PF_MIN_FOR_SCALING,
        SIZER_EXPECTANCY_MIN_CENTS,
    )
    
    pf_violations = [
        t for t in trades 
        if t.get('profit_factor', 0) < SIZER_PF_MIN_FOR_SCALING
    ]
    
    expectancy_violations = [
        t for t in trades 
        if t.get('expectancy_cents', 0) < SIZER_EXPECTANCY_MIN_CENTS
    ]
    
    return {
        "date": historical_date,
        "total_trades": len(trades),
        "largest_trades": largest_trades,
        "lowest_prices": lowest_prices,
        "highest_prices": highest_prices,
        "pf_violations": pf_violations,
        "expectancy_violations": expectancy_violations,
        "pass": len(pf_violations) == 0 and len(expectancy_violations) == 0,
    }
```

**CI Integration**:
```yaml
# .github/workflows/kalshi-deployment-safety.yml
name: Kalshi Deployment Safety Checks

on:
  pull_request:
    paths:
      - 'merid/event_venues/kalshi/**'
      - 'merid/trading/kalshi_continuous_trader.py'
  push:
    branches: [main, develop]

jobs:
  safety-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest prometheus-client
          
      - name: Run magic numbers test
        run: py -m pytest tests/test_no_magic_numbers.py -v
        
      - name: Run spot regression check
        run: python scripts/ci/kalshi_spot_regression_check.py --date 2026-05-10
        
      - name: Check for regressions
        run: |
          python scripts/ci/kalshi_safety_check.py \
            --check deep_otm_itm \
            --check model_prob_distance \
            --threshold 0.05
```

## Deployment Gate

**Required**: All checks must pass before deployment to production.

- ✅ Magic numbers compliance (automated test)
- ✅ Deep OTM/ITM exposure < 5% of total trades
- ✅ Model probability distance violations < 2% of total trades
- ✅ Spot regression check shows no PF/expectancy violations
- ✅ No trades without exit plans

## Emergency Override

In case of emergency deployment (e.g., critical bug fix), the following override process applies:

1. Document the reason for override in deployment ticket
2. Get approval from 2 of: Tech Lead, Risk Owner, or Engineering Manager
3. Set `EMERGENCY_DEPLOYMENT=true` environment variable
4. CI will mark checks as "WARN" instead of "FAIL"
5. Post-deployment, run full safety check and document any issues found

## Monitoring

After deployment, monitor the following Prometheus metrics for 24 hours:

- `kalshi_deep_otm_trades_total` - should be 0 or very low
- `kalshi_deep_itm_trades_total` - should be 0 or very low
- `kalshi_model_prob_distance_histogram` - should cluster near 0
- PnL drawdown - should not exceed normal variance
- Position count - should not spike unexpectedly

Alert thresholds:
- Deep OTM/ITM trades > 10 in 1 hour → WARNING
- Deep OTM/ITM trades > 50 in 1 hour → CRITICAL
- Model prob distance > 0.10 on > 5% of trades → WARNING
- Model prob distance > 0.20 on > 1% of trades → CRITICAL

## References

- [Kalshi: How to Read Probabilities](https://news.kalshi.com/p/how-to-read-probabilities)
- [Kalshi Fee Schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
- [3Commas: AI Trading Bot Risk Management Guide](https://3commas.io/blog/ai-trading-bot-risk-management-guide-2025)
- [BitFinance: How to Build a Bot That Finds Mispricings](https://bitfinance.substack.com/p/how-to-build-a-bot-that-finds-mispricings)
