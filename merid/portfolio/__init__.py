"""
Kalshi Crypto Portfolio Optimization for MERID

Mean-variance portfolio optimizer for Kalshi crypto prediction markets.
Supports BTC, ETH, SOL, XRP, DOGE with max 3-asset constraint and
per-trade risk caps of 1-3 USD.

Example usage:
    from merid.portfolio import PortfolioOptimizer, PortfolioDataAdapter
    
    # Initialize
    opt = PortfolioOptimizer({
        "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        "max_concurrent_assets": 3,
        "min_risk_usd_per_trade": 1,
        "max_risk_usd_per_trade": 3,
    })
    
    # Load historical data
    adapter = PortfolioDataAdapter()
    returns = adapter.get_asset_return_matrix(["BTC", "ETH"], "daily")
    opt.load_returns(returns)
    
    # Get optimal portfolios (top 3 by Sharpe ratio)
    portfolios = opt.select_optimal_portfolios(max_assets=3, num_choices=3)
    
    # Get rebalance suggestions
    current = {"BTC": {"value_usd": 5}, "ETH": {"value_usd": 3}}
    actions = opt.suggest_rebalance(current)
"""

from .optimizer import (
    PortfolioOptimizer,
    PortfolioDataAdapter,
    PortfolioSelection,
    RebalanceAction,
    KALSHI_CRYPTO_ASSETS,
    get_portfolio_optimizer,
)

from .config import (
    PortfolioOptimizerConfig,
    ConfigValidationError,
    load_portfolio_config,
    validate_config_consistency,
    get_effective_config,
)

__all__ = [
    # Optimizer
    "PortfolioOptimizer",
    "PortfolioDataAdapter",
    "PortfolioSelection",
    "RebalanceAction",
    "KALSHI_CRYPTO_ASSETS",
    "get_portfolio_optimizer",
    # Config
    "PortfolioOptimizerConfig",
    "ConfigValidationError",
    "load_portfolio_config",
    "validate_config_consistency",
    "get_effective_config",
]
