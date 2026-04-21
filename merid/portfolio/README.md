# Kalshi Crypto Portfolio Optimizer

Mean-variance portfolio optimizer specifically designed for Kalshi crypto prediction markets. Supports BTC, ETH, SOL, XRP, DOGE with a maximum 3-asset cardinality constraint and per-trade risk caps of 1-3 USD.

## Quick Start

```python
from merid.portfolio import PortfolioOptimizer, PortfolioDataAdapter

# Initialize optimizer
opt = PortfolioOptimizer({
    "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
    "max_concurrent_assets": 3,
    "min_risk_usd_per_trade": 1,
    "max_risk_usd_per_trade": 3,
    "global_risk_budget": 9,  # 3 assets * $3
    "lookback_days": 60,
})

# Load historical returns
adapter = PortfolioDataAdapter()
returns = adapter.get_asset_return_matrix(
    assets=["BTC", "ETH", "SOL"],
    timeframe="daily",
    lookback_days=60
)
opt.load_returns(returns)

# Get optimal portfolios (top 3 by Sharpe)
portfolios = opt.select_optimal_portfolios(max_assets=3, num_choices=3)

for p in portfolios:
    print(f"Assets: {p.assets_selected}")
    print(f"Weights: {p.weights}")
    print(f"Sharpe: {p.sharpe:.3f}, Vol: {p.volatility:.3f}")
    print()
```

## Architecture

### Components

1. **PortfolioDataAdapter** - Normalizes input data into return matrices
2. **PortfolioOptimizer** - Core mean-variance optimization engine
3. **PortfolioSelection** - Result dataclass with metadata
4. **RebalanceAction** - Rebalance recommendation dataclass

### Key Constraints

- **Cardinality**: Max 3 concurrent assets
- **Risk Caps**: $1-3 USD per trade per asset
- **Asset Universe**: BTC, ETH, SOL, XRP, DOGE only

## Configuration

See `config/portfolio_optimizer.yaml`:

```yaml
portfolio_optimizer:
  enabled: true
  assets: ["BTC", "ETH", "SOL", "XRP", "DOGE"]
  max_concurrent_assets: 3
  min_risk_usd_per_trade: 1
  max_risk_usd_per_trade: 3
  global_risk_budget: 9
  risk_free_rate: 0.0
  lookback_days: 60
```

## Integration with MERID

### Before Trading (SIZE/EXECUTE)

```python
from merid.portfolio import get_portfolio_optimizer

# Get singleton instance
optimizer = get_portfolio_optimizer()

# Get best portfolios
best = optimizer.get_best_portfolios()
allowed_assets = best[0].assets_selected if best else []

# Only trade allowed assets
if asset not in allowed_assets:
    logger.info(f"Skipping {asset}: not in optimal selection")
    return
```

### Rebalancing

```python
# Current positions
current = {
    "BTC": {"contracts": 10, "value_usd": 10},
    "ETH": {"contracts": 5, "value_usd": 5},
}

# Get rebalance suggestions
actions = optimizer.suggest_rebalance(
    current_positions=current,
    max_assets=3
)

for action in actions:
    if action.action_type == "exit":
        close_position(action.asset)
    elif action.action_type == "entry":
        open_position(action.asset, action.estimated_trade_risk_usd)
```

## Tuning Guide

### Lookback Period

| Timeframe | Recommended | Reason |
|-----------|-------------|--------|
| Daily | 30-90 days | Balance recency vs statistical significance |
| Hourly | 7-30 days | More data points, faster adaptation |
| 15m | 3-7 days | Very responsive to recent trends |

### Risk Budget

The `global_risk_budget` controls total portfolio risk allocation:

- Conservative: $6 (2 assets × $3)
- Moderate: $9 (3 assets × $3)
- Aggressive: $9+ with higher per-trade caps

### Cardinality

- **1 asset**: Highest conviction, concentrated risk
- **2 assets**: Diversification with focus
- **3 assets**: Maximum diversification (default)

## Testing

Run the test suite:

```bash
py -m pytest tests/portfolio/test_optimizer.py -v
```

Test coverage includes:
- Optimization mathematics
- Cardinality constraint enforcement
- Risk cap validation
- Selection ranking logic
- Rebalance behavior
- Edge cases and robustness

## Data Sources

The `PortfolioDataAdapter` can extract returns from:

1. **KalshiPositionCache** - Realized PnL from live trading
2. **Paper trading history** - Simulated returns
3. **Backtest results** - Historical simulation
4. **Synthetic data** - For testing (deterministic seed)

## API Reference

### PortfolioOptimizer

```python
class PortfolioOptimizer:
    def __init__(self, config: dict)
    def load_returns(self, returns_df: pd.DataFrame) -> bool
    def estimate_parameters() -> (pd.Series, pd.DataFrame)  # mu, Sigma
    def efficient_frontier(num_points: int) -> list[dict]
    def select_optimal_portfolios(max_assets, num_choices, objective) -> list[PortfolioSelection]
    def suggest_rebalance(current_positions, max_assets) -> list[RebalanceAction]
    def get_best_portfolios() -> list[PortfolioSelection]
    def get_config() -> dict
    def summary() -> dict
```

### PortfolioSelection

```python
@dataclass
class PortfolioSelection:
    assets_selected: list[str]      # Non-zero weight assets
    weights: dict[str, float]        # Portfolio weights
    expected_return: float
    volatility: float
    sharpe: float
    metadata: dict                    # Risk USD, update time, etc.
```

### RebalanceAction

```python
@dataclass
class RebalanceAction:
    asset: str
    target_weight: float
    current_weight: float
    estimated_trade_risk_usd: float
    action_type: str  # "entry", "scale_up", "scale_down", "exit", "hold"
    reason: str
```

## Performance Considerations

- Optimization runs in <100ms for 5 assets
- Data adapter caches return matrices (5min TTL)
- Use singleton `get_portfolio_optimizer()` to avoid re-initialization

## References

- PyPortfolioOpt documentation
- Modern Portfolio Theory (Markowitz, 1952)
- Kalshi Crypto Markets: https://help.kalshi.com/en/articles/13823838-crypto-markets
