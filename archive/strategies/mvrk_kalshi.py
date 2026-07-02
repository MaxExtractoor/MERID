"""
Full MVRK Strategy Implementation for Kalshi Event Markets

Lean implementation of multivariate volatility regulated Kelly for Kalshi crypto events.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def classical_kelly_weights(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """
    Classical Kelly weights for multiple assets.
    
    Args:
        mu: Expected return vector (n_assets,)
        cov: Covariance matrix (n_assets, n_assets)
        
    Returns:
        Kelly weights vector (n_assets,)
    """
    try:
        inv_cov = np.linalg.inv(cov)
        return inv_cov @ mu  # up to scalar Kelly factor
    except np.linalg.LinAlgError:
        logger.error("Singular covariance matrix - using zero weights")
        return np.zeros_like(mu)

def mvrk_weights(mu: np.ndarray, cov: np.ndarray, theta: float = 1.0) -> np.ndarray:
    """
    Multivariate Volatility Regulated Kelly approximation: shrink weights by portfolio variance.
    
    Args:
        mu: Expected return vector (n_assets,)
        cov: Covariance matrix (n_assets, n_assets)
        theta: Volatility regulation parameter (higher = more conservative)
        
    Returns:
        MVRK weights vector (n_assets,)
    """
    w_kelly = classical_kelly_weights(mu, cov)
    
    # Calculate portfolio variance under Kelly weights
    var_kelly = float(w_kelly.T @ cov @ w_kelly)
    
    if var_kelly <= 0:
        logger.warning("Non-positive portfolio variance - using zero weights")
        return np.zeros_like(w_kelly)
    
    # Shrink weights based on variance and theta
    shrink = 1.0 / (1.0 + theta * var_kelly)
    return w_kelly * shrink

@dataclass
class MVRKResult:
    """Results of MVRK strategy on Kalshi event markets."""
    assets: List[str]
    w_kelly: np.ndarray
    w_mvrk: np.ndarray
    eq_kelly: pd.Series
    eq_mvrk: pd.Series
    theta: float
    portfolio_metrics: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "assets": self.assets,
            "kelly_weights": self.w_kelly.tolist(),
            "mvrk_weights": self.w_mvrk.tolist(),
            "theta": self.theta,
            "final_kelly": float(self.eq_kelly.iloc[-1]) if not self.eq_kelly.empty else 1.0,
            "final_mvrk": float(self.eq_mvrk.iloc[-1]) if not self.eq_mvrk.empty else 1.0,
            "portfolio_metrics": self.portfolio_metrics or {}
        }

def calculate_portfolio_metrics(equity: pd.Series, returns_df: pd.DataFrame, 
                              weights: np.ndarray) -> Dict[str, float]:
    """
    Calculate comprehensive portfolio performance metrics.
    
    Args:
        equity: Portfolio equity curve
        returns_df: Asset returns DataFrame
        weights: Portfolio weights used
        
    Returns:
        Performance metrics dictionary
    """
    if equity.empty:
        return {}
    
    # Basic return metrics
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Calculate portfolio returns
    port_rets = equity.pct_change().dropna()
    
    # Annualization factor (assuming 15m bars)
    periods_per_year = 365 * 24 * 4
    
    # Sharpe ratio
    if len(port_rets) > 1 and port_rets.std() > 0:
        sharpe_ratio = port_rets.mean() / port_rets.std() * np.sqrt(periods_per_year)
    else:
        sharpe_ratio = 0.0
    
    # Sortino ratio
    downside_rets = port_rets[port_rets < 0]
    if len(downside_rets) > 0 and downside_rets.std() > 0:
        sortino_ratio = port_rets.mean() / downside_rets.std() * np.sqrt(periods_per_year)
    else:
        sortino_ratio = 0.0
    
    # Max drawdown
    peak = equity.cummax()
    drawdown = (equity - peak) / peak.replace(0, np.nan)
    max_drawdown = drawdown.min()
    
    # Win rate
    win_rate = (port_rets > 0).sum() / len(port_rets)
    
    # Portfolio volatility
    portfolio_vol = port_rets.std() * np.sqrt(periods_per_year)
    
    # Leverage
    leverage = np.sum(np.abs(weights))
    
    return {
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "portfolio_volatility": portfolio_vol,
        "leverage": leverage,
        "final_capital": equity.iloc[-1]
    }

def run_mvrk_on_kalshi(returns_df: pd.DataFrame, theta: float = 1.0) -> MVRKResult:
    """
    Run MVRK strategy on Kalshi event markets.
    
    Args:
        returns_df: DataFrame with per-trade returns (columns = ['BTC','ETH', ...])
        theta: MVRK theta parameter for volatility regulation
        
    Returns:
        MVRKResult with weights and equity curves
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    assets = list(returns_df.columns)
    logger.info(f"Running MVRK on {len(assets)} assets: {assets}")
    
    # Calculate expected returns and covariance
    mu = returns_df.mean().values
    cov = returns_df.cov().values
    
    # Calculate Kelly and MVRK weights
    w_kelly = classical_kelly_weights(mu, cov)
    w_mvrk = mvrk_weights(mu, cov, theta=theta)
    
    # Normalize to same gross exposure
    w_kelly = w_kelly / np.sum(np.abs(w_kelly))
    w_mvrk = w_mvrk / np.sum(np.abs(w_mvrk))
    
    # Generate portfolio returns
    port_rets_kelly = returns_df.values @ w_kelly
    port_rets_mvrk = returns_df.values @ w_mvrk
    
    # Generate equity curves
    eq_kelly = pd.Series((1 + port_rets_kelly).cumprod(), index=returns_df.index)
    eq_mvrk = pd.Series((1 + port_rets_mvrk).cumprod(), index=returns_df.index)
    
    # Calculate portfolio metrics
    kelly_metrics = calculate_portfolio_metrics(eq_kelly, returns_df, w_kelly)
    mvrk_metrics = calculate_portfolio_metrics(eq_mvrk, returns_df, w_mvrk)
    
    logger.info(f"MVRK completed: Kelly return={kelly_metrics['total_return']:.2%}, "
                f"MVRK return={mvrk_metrics['total_return']:.2%}, theta={theta}")
    
    return MVRKResult(
        assets=assets,
        w_kelly=w_kelly,
        w_mvrk=w_mvrk,
        eq_kelly=eq_kelly,
        eq_mvrk=eq_mvrk,
        theta=theta,
        portfolio_metrics={
            "kelly": kelly_metrics,
            "mvrk": mvrk_metrics
        }
    )

def compare_theta_values(returns_df: pd.DataFrame, 
                         theta_values: List[float] = None) -> Dict[str, MVRKResult]:
    """
    Compare MVRK performance across different theta values.
    
    Args:
        returns_df: DataFrame with per-trade returns
        theta_values: List of theta values to test
        
    Returns:
        Dictionary of MVRKResult by theta
    """
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0, 5.0]
    
    results = {}
    
    for theta in theta_values:
        try:
            result = run_mvrk_on_kalshi(returns_df, theta=theta)
            results[f"theta_{theta}"] = result
        except Exception as e:
            logger.error(f"Error in theta {theta} comparison: {e}")
            continue
    
    return results

def analyze_theta_performance(results: Dict[str, MVRKResult]) -> Dict[str, Any]:
    """
    Analyze performance across theta values.
    
    Args:
        results: Dictionary of MVRKResult by theta
        
    Returns:
        Performance analysis
    """
    if not results:
        return {"error": "No results to analyze"}
    
    analysis = {}
    
    # Find best performers
    best_sharpe = None
    best_return = None
    lowest_dd = None
    
    for theta_key, result in results.items():
        mvrk_metrics = result.portfolio_metrics.get("mvrk", {})
        
        if not mvrk_metrics:
            continue
        
        if best_sharpe is None or mvrk_metrics["sharpe_ratio"] > best_sharpe[1]["sharpe_ratio"]:
            best_sharpe = (theta_key, mvrk_metrics)
        
        if best_return is None or mvrk_metrics["total_return"] > best_return[1]["total_return"]:
            best_return = (theta_key, mvrk_metrics)
        
        if lowest_dd is None or mvrk_metrics["max_drawdown"] > lowest_dd[1]["max_drawdown"]:
            lowest_dd = (theta_key, mvrk_metrics)
    
    analysis["best_sharpe"] = {"theta": best_sharpe[0], "value": best_sharpe[1]["sharpe_ratio"]}
    analysis["best_return"] = {"theta": best_return[0], "value": best_return[1]["total_return"]}
    analysis["lowest_drawdown"] = {"theta": lowest_dd[0], "value": lowest_dd[1]["max_drawdown"]}
    
    # Compare to classical Kelly
    if "theta_0" in results:
        kelly_metrics = results["theta_0"].portfolio_metrics.get("kelly", {})
        mvrk_metrics = results["theta_0"].portfolio_metrics.get("mvrk", {})
        
        if kelly_metrics and mvrk_metrics:
            analysis["vs_kelly"] = {
                "sharpe_improvement": mvrk_metrics["sharpe_ratio"] - kelly_metrics["sharpe_ratio"],
                "return_improvement": mvrk_metrics["total_return"] - kelly_metrics["total_return"],
                "drawdown_improvement": mvrk_metrics["max_drawdown"] - kelly_metrics["max_drawdown"]
            }
    
    return analysis

def print_mvrk_results(result: MVRKResult, title: str = "MVRK Strategy Results"):
    """
    Print formatted MVRK results.
    
    Args:
        result: MVRKResult to display
        title: Results title
    """
    print(f"\n{title}")
    print("=" * 60)
    
    print(f"\nAssets: {result.assets}")
    print(f"Theta: {result.theta}")
    
    # Weight comparison
    print(f"\nWeight Comparison:")
    print("-" * 40)
    print(f"{'Asset':<8} {'Kelly':<10} {'MVRK':<10} {'Change':<10}")
    print("-" * 40)
    
    for asset, kelly_w, mvrk_w in zip(result.assets, result.w_kelly, result.w_mvrk):
        change = mvrk_w - kelly_w
        print(f"{asset:<8} {kelly_w:<10.3f} {mvrk_w:<10.3f} {change:<10.3f}")
    
    # Performance metrics
    kelly_metrics = result.portfolio_metrics.get("kelly", {})
    mvrk_metrics = result.portfolio_metrics.get("mvrk", {})
    
    if kelly_metrics and mvrk_metrics:
        print(f"\nPerformance Metrics:")
        print("-" * 50)
        print(f"{'Metric':<15} {'Kelly':<12} {'MVRK':<12} {'Improvement':<12}")
        print("-" * 50)
        
        metrics = ["total_return", "sharpe_ratio", "max_drawdown", "win_rate"]
        
        for metric in metrics:
            kelly_val = kelly_metrics.get(metric, 0.0)
            mvrk_val = mvrk_metrics.get(metric, 0.0)
            
            if metric == "max_drawdown":
                # Drawdown improvement (less negative is better)
                improvement = (mvrk_val - kelly_val) / abs(kelly_val) if kelly_val != 0 else 0.0
                imp_str = f"{improvement:.1%}"
            else:
                improvement = (mvrk_val - kelly_val) / abs(kelly_val) if kelly_val != 0 else 0.0
                imp_str = f"{improvement:.1%}"
            
            print(f"{metric:<15} {kelly_val:<12.3f} {mvrk_val:<12.3f} {imp_str:<12}")
    
    print("=" * 60)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample Kalshi crypto event returns
np.random.seed(42)
n_periods = 200

returns_df = pd.DataFrame({
    'BTC15M': np.random.normal(0.001, 0.02, n_periods),
    'ETH15M': np.random.normal(0.0015, 0.025, n_periods),
})

# Run MVRK strategy
result = run_mvrk_on_kalshi(returns_df, theta=1.0)
print_mvrk_results(result)

# Compare across theta values
theta_results = compare_theta_values(returns_df, theta_values=[0.0, 0.5, 1.0, 2.0])

# Analyze performance
analysis = analyze_theta_performance(theta_results)
print(f"Best Sharpe: {analysis['best_sharpe']['theta']} ({analysis['best_sharpe']['value']:.2f})")
print(f"Best Return: {analysis['best_return']['theta']} ({analysis['best_return']['value']:.2%})")

# Use results for live trading
best_result = theta_results[analysis['best_sharpe']['theta']]
optimal_weights = best_result.w_mvrk
print(f"Optimal weights: {dict(zip(best_result.assets, optimal_weights))}")
"""
