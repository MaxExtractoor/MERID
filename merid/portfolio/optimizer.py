"""
Kalshi Crypto Portfolio Optimizer for MERID

Mean-variance portfolio optimizer specifically designed for Kalshi crypto prediction markets.
Supports BTC, ETH, SOL, XRP, DOGE with a max 3-asset cardinality constraint and
percent-of-equity risk sizing (default: 0.5-2% per trade, 6% global).

Key Features:
- Percent-of-equity risk sizing with edge-aware scaling
- Momentum scalping enforcement (no hold-to-expiry)
- Top-N selection with risk budget validation

Usage:
    from merid.portfolio.optimizer import PortfolioOptimizer, PortfolioDataAdapter
    
    # Initialize with percent-based config (recommended)
    config = {
        "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        "max_concurrent_assets": 3,
        "min_risk_pct_per_trade": 0.005,  # 0.5%
        "max_risk_pct_per_trade": 0.02,   # 2.0%
        "max_risk_pct_global": 0.06,      # 6%
        "enforce_mean_reversion_only": True,
        "risk_free_rate": 0.0,
        "lookback_days": 60,
    }
    optimizer = PortfolioOptimizer(config)
    
    # Set current equity for percent-based calculations
    optimizer.set_equity(1000.0)  # $1000 account
    
    # Load data and optimize
    adapter = PortfolioDataAdapter()
    returns_df = adapter.get_asset_return_matrix(["BTC", "ETH"], "daily")
    optimizer.load_returns(returns_df)
    
    # Get optimal portfolios with edge-aware sizing
    portfolios = optimizer.select_optimal_portfolios(max_assets=3, num_choices=3)
    
    # Get rebalance suggestions
    current_positions = {"BTC": {"contracts": 10}, "ETH": {"contracts": 5}}
    actions = optimizer.suggest_rebalance(current_positions)
"""

import itertools
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from utils.logger import get_logger

logger = get_logger("merid.portfolio.optimizer")

# Kalshi crypto asset universe
KALSHI_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Minimum weight threshold for considering an asset "active"
MIN_WEIGHT_EPSILON = 1e-4


@dataclass
class PortfolioSelection:
    """Selected optimal portfolio with metadata."""
    assets_selected: List[str]
    weights: Dict[str, float]
    expected_return: float
    volatility: float
    sharpe: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RebalanceAction:
    """Single rebalance action recommendation."""
    asset: str
    target_weight: float
    current_weight: float = 0.0
    estimated_trade_risk_usd: float = 0.0
    action_type: str = ""  # "entry", "scale_up", "scale_down", "exit", "hold"
    reason: str = ""


class PortfolioDataAdapter:
    """
    Adapter for loading and normalizing portfolio data.
    
    Handles conversion from MERID-native structures or raw DataFrames
    into clean return matrices suitable for mean-variance optimization.
    """
    
    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_lock = threading.Lock()
    
    def normalize_returns(self, data: Union[pd.DataFrame, List[Dict], Dict]) -> pd.DataFrame:
        """
        Normalize input data into a clean return matrix.
        
        Expected input schema:
        - asset: str (BTC, ETH, SOL, XRP, DOGE)
        - timestamp: datetime or ISO string
        - pnl or return: float (per-period return or PnL)
        - timeframe: str (optional, e.g., "daily", "hourly", "15m")
        
        Returns:
            DataFrame with index=timestamp, columns=assets, values=returns
        """
        if isinstance(data, pd.DataFrame):
            return self._normalize_dataframe(data)
        elif isinstance(data, list):
            return self._normalize_records(data)
        elif isinstance(data, dict):
            return self._normalize_records([data])
        else:
            raise ValueError(f"Unsupported data type: {type(data)}")
    
    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize an existing DataFrame."""
        # Check if already in return matrix format (assets as columns)
        # If the columns contain crypto assets, assume it's already wide format
        crypto_cols = [col for col in df.columns if col in KALSHI_CRYPTO_ASSETS]
        if crypto_cols and len(crypto_cols) > 0 and "asset" not in df.columns:
            return df.copy()
        
        # Long format: convert to wide
        required_cols = ["asset", "timestamp"]
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"DataFrame must have columns: {required_cols} or have crypto asset columns")
        
        # Determine return column
        return_col = None
        for col in ["return", "pnl", "returns", "daily_return", "period_return"]:
            if col in df.columns:
                return_col = col
                break
        
        if return_col is None:
            raise ValueError("DataFrame must contain a return column (return/pnl/returns/daily_return/period_return)")
        
        # Convert to return matrix
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")
        
        # Pivot to wide format
        returns_matrix = df.pivot(index="timestamp", columns="asset", values=return_col)
        
        # Fill missing values (forward fill for missing periods, then fill remaining with 0)
        returns_matrix = returns_matrix.ffill().fillna(0)
        
        return returns_matrix
    
    def _normalize_records(self, records: List[Dict]) -> pd.DataFrame:
        """Normalize a list of record dicts."""
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        return self._normalize_dataframe(df)
    
    def get_asset_return_matrix(
        self,
        assets: List[str],
        timeframe: str,
        lookback_days: int = 60,
        data_source: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Get return matrix for specified assets and timeframe.
        
        Args:
            assets: List of asset symbols (BTC, ETH, etc.)
            timeframe: Kalshi timeframe identifier (daily, hourly, 15m, weekly)
            lookback_days: Number of days of history to include
            data_source: Optional MERID data source (e.g., KalshiPositionCache, backtest results)
        
        Returns:
            DataFrame with index=timestamp, columns=assets, values=per-period returns
        """
        cache_key = f"{','.join(sorted(assets))}:{timeframe}:{lookback_days}"
        
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key].copy()
        
        # If data_source provided, extract from MERID structures
        if data_source is not None:
            returns_df = self._extract_from_merid_source(data_source, assets, timeframe, lookback_days)
        else:
            # Create synthetic/placeholder data for testing
            returns_df = self._create_synthetic_returns(assets, lookback_days)
        
        with self._cache_lock:
            self._cache[cache_key] = returns_df.copy()
        
        return returns_df
    
    def _extract_from_merid_source(
        self,
        data_source: Any,
        assets: List[str],
        timeframe: str,
        lookback_days: int
    ) -> pd.DataFrame:
        """Extract returns from MERID-native data sources."""
        # This integrates with existing MERID components like:
        # - KalshiPositionCache for realized PnL
        # - Backtest result stores
        # - Paper trading history
        
        records = []
        cutoff = datetime.now() - timedelta(days=lookback_days)
        
        # Try to extract from data_source based on its type
        if hasattr(data_source, 'get_position_history'):
            # KalshiPositionCache style
            for asset in assets:
                history = data_source.get_position_history(asset, since=cutoff)
                for entry in history:
                    records.append({
                        "asset": asset,
                        "timestamp": entry.get("timestamp", entry.get("closed_at", datetime.now())),
                        "pnl": entry.get("realized_pnl", entry.get("pnl", 0.0))
                    })
        elif hasattr(data_source, 'get_trade_history'):
            # Generic trade history
            trades = data_source.get_trade_history(since=cutoff)
            for trade in trades:
                asset = trade.get("asset", trade.get("ticker", "")).replace("KX", "").replace("-D", "").replace("-W", "")
                if asset in assets:
                    records.append({
                        "asset": asset,
                        "timestamp": trade.get("timestamp", trade.get("filled_at", datetime.now())),
                        "pnl": trade.get("realized_pnl", trade.get("pnl", 0.0))
                    })
        elif isinstance(data_source, pd.DataFrame):
            # Direct DataFrame input
            return self._normalize_dataframe(data_source)
        
        if not records:
            logger.warning(f"No data extracted from source for {assets}, using synthetic data")
            return self._create_synthetic_returns(assets, lookback_days)
        
        return self._normalize_records(records)
    
    def _create_synthetic_returns(self, assets: List[str], days: int) -> pd.DataFrame:
        """Create synthetic return data for testing."""
        np.random.seed(42)  # Deterministic for testing
        dates = pd.date_range(end=datetime.now(), periods=days, freq="D")
        
        # Base returns with different volatilities
        base_params = {
            "BTC": (0.001, 0.03),  # (mean, std)
            "ETH": (0.0008, 0.035),
            "SOL": (0.0012, 0.05),
            "XRP": (0.0005, 0.04),
            "DOGE": (0.0003, 0.06),
        }
        
        data = {}
        for asset in assets:
            mean, std = base_params.get(asset, (0.0, 0.03))
            data[asset] = np.random.normal(mean, std, days)
        
        return pd.DataFrame(data, index=dates)
    
    def clear_cache(self):
        """Clear the data cache."""
        with self._cache_lock:
            self._cache.clear()


class PortfolioOptimizer:
    """
    Mean-variance portfolio optimizer for Kalshi crypto assets.
    
    Enforces constraints:
    - Max 3 concurrent assets (cardinality constraint)
    - Per-trade risk cap of 1-3 USD per asset
    
    Key methods:
    - load_returns(): Load historical return data
    - estimate_parameters(): Compute expected returns and covariance
    - efficient_frontier(): Build efficient frontier portfolios
    - select_optimal_portfolios(): Get top portfolios satisfying constraints
    - suggest_rebalance(): Generate rebalance actions from current positions
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize optimizer with configuration.
        
        Config options:
        - assets: List of assets to consider (default: all 5 crypto assets)
        - max_concurrent_assets: Max positions (default: 3)
        - min_risk_pct_per_trade: Min risk per trade as fraction of equity (default: 0.005 = 0.5%)
        - max_risk_pct_per_trade: Max risk per trade as fraction of equity (default: 0.02 = 2%)
        - risk_free_rate: Annual risk-free rate (default: 0.0)
        - lookback_days: Default lookback for data loading (default: 60)
        - num_frontier_points: Points on efficient frontier (default: 50)
        - max_risk_pct_global: Total portfolio risk budget as fraction of equity (default: 0.06 = 6%)
        - _validated: Internal marker that config passed validation (default: False)
        
        Deprecated (kept for backward compatibility):
        - min_risk_usd_per_trade: Use min_risk_pct_per_trade instead
        - max_risk_usd_per_trade: Use max_risk_pct_per_trade instead
        - global_risk_budget: Use max_risk_pct_global instead
        """
        self.config = config or {}
        
        # Runtime invariant: assert config was validated before use
        self._assert_config_validated()
        
        # Asset universe
        self.assets = self.config.get("assets", KALSHI_CRYPTO_ASSETS.copy())
        self._validate_assets()
        
        # Constraints - percent-of-equity sizing (new default)
        self.max_concurrent_assets = self.config.get("max_concurrent_assets", 3)
        
        # Percent-of-equity risk parameters (0.005 = 0.5%, 0.02 = 2%)
        self.min_risk_pct = self.config.get("min_risk_pct_per_trade", 0.005)
        self.max_risk_pct = self.config.get("max_risk_pct_per_trade", 0.02)
        
        self.risk_free_rate = self.config.get("risk_free_rate", 0.0)
        self.lookback_days = self.config.get("lookback_days", 60)
        self.num_frontier_points = self.config.get("num_frontier_points", 50)
        
        # Global risk budget as percent of equity (default: 3 assets × 3% = 9%)
        self.max_risk_pct_global = self.config.get("max_risk_pct_global", 
                                                    self.max_concurrent_assets * self.max_risk_pct)
        
        # Current equity for percent-based calculations (must be set via set_equity)
        self._current_equity: float = 0.0
        
        # Momentum scalping enforcement (no hold-to-expiry)
        self.enforce_mean_reversion = self.config.get("enforce_mean_reversion_only", True)
        self.momentum_scalp_config = self.config.get("momentum_scalp_config", {
            "max_hold_minutes": 60,
            "profit_target_pct": 0.15,
            "stop_loss_pct": 0.10,
            "require_price_based_exits": True,
        })
        self.allowed_strategy_tags = set(self.config.get("allowed_strategy_tags", ["momentum", "scalping", "mean_reversion"]))
        self.blocked_strategy_patterns = self.config.get("blocked_strategy_patterns", [
            ".*hold.*expiry.*",
            ".*resolution.*based.*",
            ".*expiry.*farmer.*",
        ])
        
        # Data storage
        self.returns_df: Optional[pd.DataFrame] = None
        self.expected_returns: Optional[pd.Series] = None
        self.cov_matrix: Optional[pd.DataFrame] = None
        self.last_update: Optional[datetime] = None
        
        # Optimization state
        self._last_selections: List[PortfolioSelection] = []
        self._lock = threading.Lock()
        
        # Startup logging of key caps for observability
        self._log_startup_caps()
    
    def _assert_config_validated(self):
        """
        Runtime invariant: Config must be validated before use.
        
        Raises:
            RuntimeError: If config lacks the _validated marker
        """
        if not self.config.get("_validated", False):
            logger.warning(
                "PortfolioOptimizer initialized with unvalidated config. "
                "Use load_portfolio_config() or get_effective_config() to ensure "
                "config passes schema validation and cross-config checks."
            )
            # In production, this could raise RuntimeError; for now, warn
    
    def _log_startup_caps(self):
        """Log key caps at INFO level for production observability."""
        # Percent-of-equity mode (only mode)
        mode_tag = "MOMENTUM-ONLY" if self.enforce_mean_reversion else "STANDARD"
        logger.info(
            "[PORTFOLIO_OPTIMIZER] Runtime caps initialized (percent-of-equity mode) | "
            f"mode={mode_tag} | "
            f"assets={self.assets} | "
            f"max_concurrent={self.max_concurrent_assets} | "
            f"risk_range_pct=[{self.min_risk_pct*100:.2f}%, {self.max_risk_pct*100:.2f}%] | "
            f"global_budget_pct={self.max_risk_pct_global*100:.2f}% | "
            f"lookback_days={self.lookback_days} | "
            f"objective={self.config.get('objective', 'sharpe')}"
        )
    
    def is_strategy_allowed(self, strategy_name: str, strategy_tags: Optional[List[str]] = None) -> bool:
        """Check if a strategy is allowed under momentum-only enforcement.
        
        Args:
            strategy_name: Name of the strategy
            strategy_tags: Optional list of tags associated with the strategy
            
        Returns:
            True if strategy is allowed, False otherwise
        """
        if not self.enforce_mean_reversion:
            return True  # No enforcement
        
        # Check blocked patterns
        import re
        for pattern in self.blocked_strategy_patterns:
            if re.match(pattern, strategy_name, re.IGNORECASE):
                logger.warning(f"Strategy '{strategy_name}' blocked by pattern: {pattern}")
                return False
        
        # Check allowed tags
        if strategy_tags:
            has_allowed_tag = any(tag in self.allowed_strategy_tags for tag in strategy_tags)
            if not has_allowed_tag:
                logger.warning(
                    f"Strategy '{strategy_name}' rejected: no allowed tags. "
                    f"Tags={strategy_tags}, allowed={self.allowed_strategy_tags}"
                )
                return False
        
        return True
    
    def _validate_assets(self):
        """Validate that all assets are in the allowed universe."""
        invalid = set(self.assets) - set(KALSHI_CRYPTO_ASSETS)
        if invalid:
            raise ValueError(f"Invalid assets: {invalid}. Must be subset of {KALSHI_CRYPTO_ASSETS}")
    
    def load_returns(self, returns_df: pd.DataFrame) -> bool:
        """
        Load historical return data.
        
        Args:
            returns_df: DataFrame with index=timestamp, columns=assets, values=returns
        
        Returns:
            True if successful
        """
        try:
            # Validate columns
            missing = set(self.assets) - set(returns_df.columns)
            if missing:
                logger.warning(f"Missing assets in returns data: {missing}")
                # Use available subset
                available = list(set(self.assets) & set(returns_df.columns))
                if len(available) < 2:
                    raise ValueError(f"Need at least 2 assets, only have: {available}")
                self.assets = available
            
            with self._lock:
                self.returns_df = returns_df[self.assets].copy()
                self.last_update = datetime.now()
            
            logger.info(f"Loaded returns for {len(self.assets)} assets, "
                       f"{len(self.returns_df)} periods")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load returns: {e}")
            return False
    
    def estimate_parameters(self) -> Tuple[pd.Series, pd.DataFrame]:
        """
        Compute expected returns (mu) and covariance matrix (Sigma).
        
        Returns:
            (expected_returns, cov_matrix)
        """
        if self.returns_df is None or self.returns_df.empty:
            raise ValueError("No returns data loaded. Call load_returns() first.")
        
        with self._lock:
            # Expected returns = historical mean
            self.expected_returns = self.returns_df.mean()
            
            # Covariance matrix
            self.cov_matrix = self.returns_df.cov()
            
            return self.expected_returns.copy(), self.cov_matrix.copy()
    
    def _calculate_sharpe(self, expected_return: float, volatility: float) -> float:
        """Calculate Sharpe ratio."""
        if volatility <= 0:
            return 0.0
        return (expected_return - self.risk_free_rate) / volatility
    
    def _optimize_subset(self, subset_assets: List[str]) -> Optional[Dict]:
        """
        Optimize portfolio for a specific subset of assets.
        
        Uses scipy.optimize to find max Sharpe portfolio for the subset.
        """
        if len(subset_assets) == 0:
            return None
        
        # Ensure parameters are estimated
        if self.expected_returns is None:
            self.estimate_parameters()
        
        if len(subset_assets) == 1:
            # Single asset: weight = 1.0
            asset = subset_assets[0]
            if asset not in self.expected_returns.index:
                return None
            
            expected_ret = self.expected_returns[asset]
            volatility = np.sqrt(self.cov_matrix.loc[asset, asset])
            sharpe = self._calculate_sharpe(expected_ret, volatility)
            
            return {
                "assets": subset_assets,
                "weights": {asset: 1.0},
                "expected_return": expected_ret,
                "volatility": volatility,
                "sharpe": sharpe
            }
        
        # Multi-asset optimization
        n = len(subset_assets)
        
        # Extract subset parameters
        mu = self.expected_returns[subset_assets].values
        sigma = self.cov_matrix.loc[subset_assets, subset_assets].values
        
        # Objective: maximize Sharpe = minimize negative Sharpe
        def neg_sharpe(weights):
            port_return = np.dot(weights, mu)
            port_vol = np.sqrt(np.dot(weights, np.dot(sigma, weights)))
            if port_vol <= 0:
                return 0.0
            return -(port_return - self.risk_free_rate) / port_vol
        
        # Constraints: weights sum to 1
        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        
        # Bounds: 0 <= weight <= 1 (no shorting)
        bounds = [(0.0, 1.0) for _ in range(n)]
        
        # Initial guess: equal weights
        x0 = np.array([1.0 / n] * n)
        
        # Optimize
        try:
            result = minimize(
                neg_sharpe,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-9, "disp": False, "maxiter": 1000}
            )
            
            if not result.success:
                return None
            
            weights = result.x
            port_return = np.dot(weights, mu)
            port_vol = np.sqrt(np.dot(weights, np.dot(sigma, weights)))
            sharpe = self._calculate_sharpe(port_return, port_vol)
            
            return {
                "assets": subset_assets,
                "weights": dict(zip(subset_assets, weights)),
                "expected_return": port_return,
                "volatility": port_vol,
                "sharpe": sharpe
            }
            
        except Exception as e:
            logger.debug(f"Optimization failed for {subset_assets}: {e}")
            return None
    
    def efficient_frontier(self, num_points: int = 50) -> List[Dict]:
        """
        Build efficient frontier by optimizing across target returns.
        
        Note: This ignores cardinality constraints. Use select_optimal_portfolios()
        for production recommendations with max 3 asset constraint.
        """
        if self.expected_returns is None:
            self.estimate_parameters()
        
        n_assets = len(self.assets)
        mu = self.expected_returns.values
        sigma = self.cov_matrix.values
        
        # Min and max possible returns
        min_return = mu.min()
        max_return = mu.max()
        
        target_returns = np.linspace(min_return, max_return, num_points)
        frontier = []
        
        for target in target_returns:
            # Minimize variance subject to target return
            def portfolio_var(weights):
                return np.dot(weights, np.dot(sigma, weights))
            
            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {"type": "eq", "fun": lambda w: np.dot(w, mu) - target}
            ]
            bounds = [(0.0, 1.0) for _ in range(n_assets)]
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            try:
                result = minimize(
                    portfolio_var, x0, method="SLSQP",
                    bounds=bounds, constraints=constraints,
                    options={"ftol": 1e-9, "disp": False}
                )
                
                if result.success:
                    weights = result.x
                    vol = np.sqrt(result.fun)
                    ret = target
                    sharpe = self._calculate_sharpe(ret, vol)
                    
                    frontier.append({
                        "weights": dict(zip(self.assets, weights)),
                        "expected_return": ret,
                        "volatility": vol,
                        "sharpe": sharpe
                    })
            except Exception:
                pass
        
        return frontier
    
    def _apply_risk_caps(
        self, 
        portfolio: Dict, 
        global_budget: Optional[float] = None,
        equity: Optional[float] = None,
        edge_by_asset: Optional[Dict[str, float]] = None
    ) -> Optional[Dict]:
        """
        Apply per-trade risk caps to portfolio weights.
        
        Supports both legacy USD mode and new percent-of-equity mode.
        In percent-of-equity mode, uses compute_risk_amount() for edge-aware sizing.
        
        Args:
            portfolio: Portfolio dict with "weights" key
            global_budget: Legacy USD budget (deprecated, use equity instead)
            equity: Current account equity for percent-based sizing
            edge_by_asset: Optional dict of edge values per asset for edge-aware sizing
        
        Returns:
            None if portfolio cannot satisfy risk constraints.
            Otherwise returns portfolio with adjusted weights and risk info.
        """
        weights = portfolio["weights"]
        
        # Calculate per-asset risk allocation (percent-of-equity mode only)
        asset_risks = {}
        feasible = True
        total_risk = 0.0
        
        for asset, weight in weights.items():
            if weight < MIN_WEIGHT_EPSILON:
                continue
            
            if equity is not None and equity > 0:
                # Percent-of-equity mode with edge-aware sizing
                edge = edge_by_asset.get(asset, 0.05) if edge_by_asset else 0.05  # Default 5% edge
                risk_usd = self.compute_risk_amount(equity, edge)
                
                # Scale by portfolio weight
                risk_usd = risk_usd * weight
            else:
                # No equity provided, cannot size
                feasible = False
                break
            
            asset_risks[asset] = risk_usd
            total_risk += risk_usd
        
        if not feasible:
            return None
        
        # Check global budget constraint
        if equity is not None:
            max_total = equity * self.max_risk_pct_global
            if total_risk > max_total:
                # Scale down proportionally
                scale = max_total / total_risk if total_risk > 0 else 0
                asset_risks = {a: r * scale for a, r in asset_risks.items()}
                total_risk = max_total
        
        # Create adjusted portfolio
        adjusted = portfolio.copy()
        adjusted["asset_risks_usd"] = asset_risks
        adjusted["total_risk_usd"] = total_risk
        adjusted["sizing_mode"] = "percent_equity" if use_percent_mode else "legacy_usd"
        
        return adjusted
    
    def select_optimal_portfolios(
        self,
        max_assets: int = 3,
        num_choices: int = 3,
        objective: str = "sharpe"
    ) -> List[PortfolioSelection]:
        """
        Select optimal portfolios satisfying cardinality and risk constraints.
        
        Strategy:
        1. Generate all valid asset combinations (1 to max_assets)
        2. Optimize max-Sharpe portfolio for each combination
        3. Filter by risk caps
        4. Rank by objective and return top num_choices
        
        Args:
            max_assets: Maximum number of assets (default 3)
            num_choices: Number of portfolios to return
            objective: Ranking objective ("sharpe", "return", "return_per_vol")
        
        Returns:
            List of PortfolioSelection objects, ranked by objective
        """
        if self.expected_returns is None:
            self.estimate_parameters()
        
        candidates = []
        
        # Generate all valid asset combinations (1 to max_assets)
        for k in range(1, min(max_assets, len(self.assets)) + 1):
            for subset in itertools.combinations(self.assets, k):
                subset_assets = list(subset)
                
                # Optimize this subset
                result = self._optimize_subset(subset_assets)
                if result is None:
                    continue
                
                # Apply risk caps with current equity if available
                equity = self._current_equity if self._current_equity > 0 else None
                adjusted = self._apply_risk_caps(result, equity=equity)
                if adjusted is None:
                    continue
                
                candidates.append(adjusted)
        
        if not candidates:
            logger.warning("No feasible portfolios found satisfying constraints")
            return []
        
        # Rank by objective
        if objective == "sharpe":
            candidates.sort(key=lambda x: x["sharpe"], reverse=True)
        elif objective == "return":
            candidates.sort(key=lambda x: x["expected_return"], reverse=True)
        elif objective == "return_per_vol":
            candidates.sort(key=lambda x: x["expected_return"] / max(x["volatility"], 1e-6), reverse=True)
        
        # Build PortfolioSelection objects
        selections = []
        for c in candidates[:num_choices]:
            # Filter to non-zero weights
            active_weights = {a: w for a, w in c["weights"].items() if w >= MIN_WEIGHT_EPSILON}
            
            sel = PortfolioSelection(
                assets_selected=list(active_weights.keys()),
                weights=active_weights,
                expected_return=c["expected_return"],
                volatility=c["volatility"],
                sharpe=c["sharpe"],
                metadata={
                    "asset_risks_usd": c.get("asset_risks_usd", {}),
                    "total_risk_usd": c.get("total_risk_usd", 0),
                    "timeframe": self.lookback_days,
                    "num_periods": len(self.returns_df) if self.returns_df is not None else 0,
                    "last_update": self.last_update.isoformat() if self.last_update else None
                }
            )
            selections.append(sel)
        
        with self._lock:
            self._last_selections = selections.copy()
        
        logger.info(f"Selected {len(selections)} optimal portfolios (objective={objective})")
        return selections
    
    def suggest_rebalance(
        self,
        current_positions: Dict[str, Dict],
        as_of_time: Optional[datetime] = None,
        max_assets: int = 3,
        global_risk_budget: Optional[float] = None
    ) -> List[RebalanceAction]:
        """
        Generate rebalance suggestions based on current positions vs optimal portfolio.
        
        Args:
            current_positions: Dict of {asset: {contracts: int, value_usd: float, ...}}
            as_of_time: Timestamp for the rebalance (default: now)
            max_assets: Max assets to hold after rebalance
            global_risk_budget: Total risk budget in USD
        
        Returns:
            List of RebalanceAction recommendations
        """
        as_of_time = as_of_time or datetime.now()
        budget = global_risk_budget or self.global_risk_budget
        
        # Get current portfolio value
        current_value = sum(
            pos.get("value_usd", pos.get("contracts", 0) * 1.0)
            for pos in current_positions.values()
        )
        
        if current_value <= 0:
            current_value = budget  # Assume full budget
        
        # Calculate current weights
        current_weights = {}
        for asset, pos in current_positions.items():
            value = pos.get("value_usd", pos.get("contracts", 0) * 1.0)
            current_weights[asset] = value / current_value if current_value > 0 else 0
        
        # Get optimal portfolio
        optimal = self.select_optimal_portfolios(max_assets=max_assets, num_choices=1)
        if not optimal:
            logger.warning("No optimal portfolio available for rebalance suggestion")
            return []
        
        target = optimal[0]
        target_weights = target.weights
        
        # Generate actions
        actions = []
        all_assets = set(current_weights.keys()) | set(target_weights.keys())
        
        for asset in all_assets:
            current_w = current_weights.get(asset, 0.0)
            target_w = target_weights.get(asset, 0.0)
            
            # Determine action type
            if current_w < MIN_WEIGHT_EPSILON and target_w >= MIN_WEIGHT_EPSILON:
                action_type = "entry"
                reason = "New optimal asset entry"
            elif current_w >= MIN_WEIGHT_EPSILON and target_w < MIN_WEIGHT_EPSILON:
                action_type = "exit"
                reason = "Asset no longer optimal"
            elif target_w > current_w * 1.1:
                action_type = "scale_up"
                reason = "Increase allocation"
            elif target_w < current_w * 0.9:
                action_type = "scale_down"
                reason = "Decrease allocation"
            else:
                action_type = "hold"
                reason = "Allocation within tolerance"
            
            # Calculate trade risk (percent-of-equity mode only)
            if current_value > 0:
                # Percent-of-equity mode: use compute_risk_amount for edge-aware sizing
                # Default 5% edge for rebalancing (conservative)
                trade_risk = self.compute_risk_amount(current_value, 0.05) * abs(target_w - current_w)
                # Clamp to min/max per-trade limits
                min_trade = current_value * self.min_risk_pct
                max_trade = current_value * self.max_risk_pct
                trade_risk = max(min_trade, min(max_trade, trade_risk))
            else:
                # No current value, skip sizing
                trade_risk = 0
            
            actions.append(RebalanceAction(
                asset=asset,
                target_weight=target_w,
                current_weight=current_w,
                estimated_trade_risk_usd=trade_risk,
                action_type=action_type,
                reason=reason
            ))
        
        # If over max_assets, prioritize by Sharpe contribution and exit weakest
        active_actions = [a for a in actions if a.action_type != "exit"]
        if len(active_actions) > max_assets:
            # Sort by target weight (proxy for importance)
            active_actions.sort(key=lambda a: a.target_weight, reverse=True)
            
            # Mark excess assets for exit
            for action in active_actions[max_assets:]:
                action.action_type = "exit"
                action.reason = f"Exceeds max {max_assets} assets constraint"
                action.target_weight = 0.0
        
        # Sort actions: exits first, then entries/scales
        actions.sort(key=lambda a: (
            0 if a.action_type == "exit" else 1,
            0 if a.action_type == "entry" else 1,
            -a.target_weight
        ))
        
        # Observability: Log current state vs constraints
        open_assets = len([a for a in actions if a.action_type != "exit"])
        use_percent_mode = (self.min_risk_usd <= 0 and self.max_risk_usd <= 0)
        
        if use_percent_mode and current_value > 0:
            logger.info(
                f"[PORTFOLIO_REBALANCE] actions={len(actions)} | "
                f"current_assets={len(current_positions)} | "
                f"target_open={open_assets} | "
                f"max_allowed={self.max_concurrent_assets} | "
                f"risk_range_pct=[{self.min_risk_pct*100:.2f}%, {self.max_risk_pct*100:.2f}%] | "
                f"current_equity=${current_value:.2f}"
            )
        else:
            logger.info(
                f"[PORTFOLIO_REBALANCE] actions={len(actions)} | "
                f"current_assets={len(current_positions)} | "
                f"target_open={open_assets} | "
                f"max_allowed={self.max_concurrent_assets} | "
                f"risk_range_usd=[{self.min_risk_usd}, {self.max_risk_usd}]"
            )
        
        return actions
    
    def get_best_portfolios(self, as_of_time: Optional[datetime] = None) -> List[PortfolioSelection]:
        """
        Simple API for MERID agents to get best portfolios.
        
        This is the main integration point - upstream agents call this
        to decide which 1-3 assets to trade.
        """
        return self.select_optimal_portfolios(
            max_assets=self.max_concurrent_assets,
            num_choices=3
        )
    
    def set_equity(self, equity: float) -> None:
        """Set current equity for percent-based risk calculations.
        
        Args:
            equity: Current account equity in USD
        """
        self._current_equity = max(0.0, equity)
    
    def compute_risk_amount(self, equity: float, edge: float) -> float:
        """Compute dollar risk for a single trade based on fixed fractional sizing.
        
        Uses min/max_risk_pct_per_trade from config and scales within that band 
        using edge (higher edge = larger position, up to max).
        
        Formula:
            base_risk_pct = min_risk_pct + (edge / max_edge) * (max_risk_pct - min_risk_pct)
            risk_amount = equity * clamp(base_risk_pct, min_risk_pct, max_risk_pct)
        
        Args:
            equity: Current account equity in USD
            edge: Edge value (e.g., 0.03 for 3% edge)
            
        Returns:
            Dollar risk amount for the trade
        """
        if equity <= 0:
            return 0.0
        
        # Edge scaling: linear ramp from min to max risk based on edge magnitude
        # Assume max meaningful edge is 10% (0.10) for scaling purposes
        MAX_EDGE_FOR_SCALING = 0.10
        
        # Normalize edge to 0-1 scale (capped at MAX_EDGE_FOR_SCALING)
        edge_ratio = min(abs(edge), MAX_EDGE_FOR_SCALING) / MAX_EDGE_FOR_SCALING
        
        # Scale risk percentage: start at min, scale up to max based on edge
        risk_fraction = self.min_risk_pct + edge_ratio * (self.max_risk_pct - self.min_risk_pct)
        
        # Clamp to hard limits (safety)
        risk_fraction = max(self.min_risk_pct, min(self.max_risk_pct, risk_fraction))
        
        return equity * risk_fraction
    
    def get_config(self) -> Dict[str, Any]:
        """Get current optimizer configuration."""
        return {
            "assets": self.assets.copy(),
            "max_concurrent_assets": self.max_concurrent_assets,
            "min_risk_pct_per_trade": self.min_risk_pct,
            "max_risk_pct_per_trade": self.max_risk_pct,
            "max_risk_pct_global": self.max_risk_pct_global,
            # Momentum scalping enforcement
            "enforce_mean_reversion_only": self.enforce_mean_reversion,
            "momentum_scalp_config": self.momentum_scalp_config,
            "allowed_strategy_tags": list(self.allowed_strategy_tags),
            "blocked_strategy_patterns": self.blocked_strategy_patterns,
            # Legacy fields (deprecated)
            "risk_free_rate": self.risk_free_rate,
            "lookback_days": self.lookback_days,
            "num_frontier_points": self.num_frontier_points,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "data_periods": len(self.returns_df) if self.returns_df is not None else 0
        }
    
    def summary(self) -> Dict[str, Any]:
        """Get optimizer summary for monitoring/debugging."""
        with self._lock:
            selections = self._last_selections.copy()
        
        return {
            "config": self.get_config(),
            "status": "active" if self.returns_df is not None else "no_data",
            "last_selections": [
                {
                    "assets": s.assets_selected,
                    "weights": s.weights,
                    "sharpe": s.sharpe,
                    "volatility": s.volatility
                }
                for s in selections[:3]
            ]
        }
    
    def log_effective_caps(self, current_positions: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
        """
        Log effective caps for observability.
        
        This method should be called periodically (e.g., every N cycles) to log
        the current effective risk caps and open assets count for production
        monitoring.
        
        Args:
            current_positions: Optional current positions to log against caps
        
        Returns:
            Dict with logged metrics for potential metric emission
        """
        # Count open assets if positions provided
        open_count = 0
        position_risks = []
        if current_positions:
            open_count = len(current_positions)
            for asset, pos in current_positions.items():
                value = pos.get("value_usd", pos.get("contracts", 0) * 1.0)
                position_risks.append(f"{asset}=${value:.2f}")
        
        # Check constraint status
        at_capacity = open_count >= self.max_concurrent_assets
        
        metrics = {
            "open_assets_count": open_count,
            "max_concurrent_assets": self.max_concurrent_assets,
            "at_capacity": at_capacity,
            "position_details": position_risks if position_risks else None,
            "constraint_compliance": "ok" if not at_capacity else "at_limit"
        }
        
        logger.info(
            f"[PORTFOLIO_CAPS] open={open_count}/{self.max_concurrent_assets} | "
            f"status={'AT_LIMIT' if at_capacity else 'OK'}"
        )
        
        return metrics


# Singleton instance for MERID integration
_optimizer_instance: Optional[PortfolioOptimizer] = None
_optimizer_lock = threading.Lock()


def get_portfolio_optimizer(config: Optional[Dict[str, Any]] = None) -> PortfolioOptimizer:
    """
    Get or create the global PortfolioOptimizer singleton.
    
    If no config provided, loads and validates config from YAML automatically.
    This ensures the runtime invariant check passes.
    
    Usage:
        optimizer = get_portfolio_optimizer()
        portfolios = optimizer.get_best_portfolios()
    """
    global _optimizer_instance
    
    if _optimizer_instance is None:
        with _optimizer_lock:
            if _optimizer_instance is None:
                # If no config provided, load validated config
                if config is None:
                    try:
                        from merid.portfolio.config import get_effective_config
                        from merid.settings import settings
                        config_obj = get_effective_config(settings)
                        config = config_obj.to_optimizer_dict()
                    except Exception as e:
                        logger.warning(
                            f"Failed to load validated config: {e}. "
                            f"Using defaults (config will be unvalidated)."
                        )
                        config = None
                
                _optimizer_instance = PortfolioOptimizer(config)
    
    return _optimizer_instance
