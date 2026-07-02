"""
Portfolio Optimization with Half Kelly on Kalshi

Simple two-asset optimizer using classical Kelly weights with half Kelly scaling.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class HalfKellyPortfolio:
    """Half Kelly portfolio optimization results."""
    assets: List[str]
    weights: np.ndarray  # final weights used
    equity: pd.Series
    portfolio_metrics: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "assets": self.assets,
            "weights": self.weights.tolist(),
            "equity": self.equity.tolist() if not self.equity.empty else [],
            "portfolio_metrics": self.portfolio_metrics or {}
        }

def build_half_kelly_portfolio(returns_df: pd.DataFrame) -> HalfKellyPortfolio:
    """
    Build half Kelly portfolio from Kalshi crypto event returns.
    
    Args:
        returns_df: DataFrame with per-trade returns (columns = assets, rows = periods)
        
    Returns:
        HalfKellyPortfolio with optimized weights and equity curve
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    assets = list(returns_df.columns)
    logger.info(f"Building half Kelly portfolio for {len(assets)} assets: {assets}")
    
    # Calculate expected returns and covariance
    mu = returns_df.mean().values
    cov = returns_df.cov().values
    
    # Calculate classical Kelly weights
    try:
        inv_cov = np.linalg.inv(cov)
        w_raw = inv_cov @ mu
    except np.linalg.LinAlgError:
        logger.error("Singular covariance matrix - using equal weights")
        w_raw = np.ones(len(assets)) / len(assets)
    
    # Normalize to sum |w| = 1 (unit gross exposure)
    w_unit = w_raw / np.sum(np.abs(w_raw))
    
    # Apply half Kelly scaling (half Kelly total risk budget)
    w_half = 0.5 * w_unit
    
    # Generate portfolio returns
    port_rets = returns_df.values @ w_half
    
    # Generate equity curve
    equity = pd.Series((1 + port_rets).cumprod(), index=returns_df.index)
    
    # Calculate portfolio metrics
    metrics = calculate_portfolio_metrics(equity, returns_df, w_half)
    
    logger.info(f"Half Kelly portfolio built: return={metrics['total_return']:.2%}, "
                f"sharpe={metrics['sharpe_ratio']:.2f}, leverage={metrics['leverage']:.3f}")
    
    return HalfKellyPortfolio(
        assets=assets,
        weights=w_half,
        equity=equity,
        portfolio_metrics=metrics
    )

def calculate_portfolio_metrics(equity: pd.Series, 
                              returns_df: pd.DataFrame,
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
    
    # Calmar ratio
    if max_drawdown != 0:
        calmar_ratio = total_return / abs(max_drawdown)
    else:
        calmar_ratio = 0.0
    
    return {
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "portfolio_volatility": portfolio_vol,
        "leverage": leverage,
        "calmar_ratio": calmar_ratio,
        "final_capital": equity.iloc[-1]
    }

def compare_kelly_scalings(returns_df: pd.DataFrame,
                           scalings: List[float] = None) -> Dict[str, HalfKellyPortfolio]:
    """
    Compare different Kelly scaling factors.
    
    Args:
        returns_df: DataFrame with per-trade returns
        scalings: List of scaling factors (e.g., [0.25, 0.5, 0.75, 1.0])
        
    Returns:
        Dictionary of HalfKellyPortfolio by scaling factor
    """
    if scalings is None:
        scalings = [0.125, 0.25, 0.5, 0.75, 1.0]  # Eighth, quarter, half, three-quarters, full
    
    results = {}
    
    for scaling in scalings:
        try:
            # Calculate classical Kelly weights
            mu = returns_df.mean().values
            cov = returns_df.cov().values
            
            try:
                inv_cov = np.linalg.inv(cov)
                w_raw = inv_cov @ mu
            except np.linalg.LinAlgError:
                w_raw = np.ones(len(returns_df.columns)) / len(returns_df.columns)
            
            # Normalize and apply scaling
            w_unit = w_raw / np.sum(np.abs(w_raw))
            w_scaled = scaling * w_unit
            
            # Generate portfolio returns and equity
            port_rets = returns_df.values @ w_scaled
            equity = pd.Series((1 + port_rets).cumprod(), index=returns_df.index)
            
            # Calculate metrics
            metrics = calculate_portfolio_metrics(equity, returns_df, w_scaled)
            
            results[f"scaling_{scaling:.3f}"] = HalfKellyPortfolio(
                assets=list(returns_df.columns),
                weights=w_scaled,
                equity=equity,
                portfolio_metrics=metrics
            )
            
        except Exception as e:
            logger.error(f"Error in scaling {scaling:.3f}: {e}")
            continue
    
    return results

def analyze_kelly_scalings(results: Dict[str, HalfKellyPortfolio]) -> Dict[str, Any]:
    """
    Analyze performance across different Kelly scalings.
    
    Args:
        results: Dictionary of HalfKellyPortfolio by scaling factor
        
    Returns:
        Performance analysis
    """
    if not results:
        return {"error": "No results to analyze"}
    
    analysis = {}
    
    # Extract metrics for comparison
    scaling_metrics = {}
    
    for scaling_key, portfolio in results.items():
        scaling = float(scaling_key.split("_")[1])
        metrics = portfolio.portfolio_metrics
        
        if metrics:
            scaling_metrics[scaling] = metrics
    
    # Find best performers
    best_sharpe = max(scaling_metrics.items(), key=lambda x: x[1]["sharpe_ratio"])
    best_return = max(scaling_metrics.items(), key=lambda x: x[1]["total_return"])
    lowest_dd = min(scaling_metrics.items(), key=lambda x: x[1]["max_drawdown"])
    best_calmar = max(scaling_metrics.items(), key=lambda x: x[1]["calmar_ratio"])
    
    analysis["best_sharpe"] = {"scaling": best_sharpe[0], "value": best_sharpe[1]["sharpe_ratio"]}
    analysis["best_return"] = {"scaling": best_return[0], "value": best_return[1]["total_return"]}
    analysis["lowest_drawdown"] = {"scaling": lowest_dd[0], "value": lowest_dd[1]["max_drawdown"]}
    analysis["best_calmar"] = {"scaling": best_calmar[0], "value": best_calmar[1]["calmar_ratio"]}
    
    # Risk-reward analysis
    half_kelly = scaling_metrics.get(0.5, {})
    quarter_kelly = scaling_metrics.get(0.25, {})
    
    if half_kelly and quarter_kelly:
        analysis["half_vs_quarter"] = {
            "sharpe_improvement": half_kelly["sharpe_ratio"] - quarter_kelly["sharpe_ratio"],
            "return_improvement": half_kelly["total_return"] - quarter_kelly["total_return"],
            "drawdown_penalty": half_kelly["max_drawdown"] - quarter_kelly["max_drawdown"]
        }
    
    # Optimal scaling recommendation
    def composite_score(metrics):
        # Composite score: Sharpe + Return - Drawdown penalty
        return metrics["sharpe_ratio"] + metrics["total_return"] * 10 - abs(metrics["max_drawdown"]) * 5
    
    best_overall = max(scaling_metrics.items(), key=lambda x: composite_score(x[1]))
    analysis["optimal_scaling"] = {"scaling": best_overall[0], "score": composite_score(best_overall[1])}
    
    return analysis

def print_portfolio_results(portfolio: HalfKellyPortfolio, title: str = "Half Kelly Portfolio Results"):
    """
    Print formatted portfolio results.
    
    Args:
        portfolio: HalfKellyPortfolio to display
        title: Results title
    """
    print(f"\n{title}")
    print("=" * 60)
    
    print(f"\nAssets: {portfolio.assets}")
    
    print(f"\nOptimal Weights:")
    print("-" * 40)
    print(f"{'Asset':<12} {'Weight':<10} {'Allocation':<12}")
    print("-" * 40)
    
    for asset, weight in zip(portfolio.assets, portfolio.weights):
        allocation = abs(weight) * 100  # Percentage allocation
        direction = "Long" if weight > 0 else "Short"
        print(f"{asset:<12} {weight:<10.3f} {allocation:<10.1f}% ({direction})")
    
    # Performance metrics
    if portfolio.portfolio_metrics:
        metrics = portfolio.portfolio_metrics
        
        print(f"\nPerformance Metrics:")
        print("-" * 50)
        print(f"  Total Return: {metrics['total_return']:.2%}")
        print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        print(f"  Sortino Ratio: {metrics['sortino_ratio']:.2f}")
        print(f"  Max Drawdown: {metrics['max_drawdown']:.2%}")
        print(f"  Win Rate: {metrics['win_rate']:.1%}")
        print(f"  Portfolio Volatility: {metrics['portfolio_volatility']:.2%}")
        print(f"  Leverage: {metrics['leverage']:.3f}")
        print(f"  Calmar Ratio: {metrics['calmar_ratio']:.2f}")
        print(f"  Final Capital: {metrics['final_capital']:.3f}")
    
    print("=" * 60)

def print_scaling_comparison(results: Dict[str, HalfKellyPortfolio]):
    """
    Print formatted comparison of Kelly scalings.
    
    Args:
        results: Dictionary of HalfKellyPortfolio by scaling factor
    """
    if not results:
        print("No results to compare")
        return
    
    print("\n" + "="*80)
    print("KELLY SCALING COMPARISON")
    print("="*80)
    
    print(f"\nPerformance Summary:")
    print("-" * 80)
    print(f"{'Scaling':<12} {'Return':<10} {'Sharpe':<8} {'Max DD':<10} {'Calmar':<8} {'Leverage':<10}")
    print("-" * 80)
    
    for scaling_key, portfolio in results.items():
        scaling = float(scaling_key.split("_")[1])
        metrics = portfolio.portfolio_metrics
        
        if metrics:
            print(f"{scaling:<12.3f} {metrics['total_return']:<10.2%} "
                  f"{metrics['sharpe_ratio']:<8.2f} {metrics['max_drawdown']:<10.2%} "
                  f"{metrics['calmar_ratio']:<8.2f} {metrics['leverage']:<10.3f}")
    
    # Analysis
    analysis = analyze_kelly_scalings(results)
    
    if "error" not in analysis:
        print(f"\nBest Performers:")
        print("-" * 50)
        print(f"  Highest Sharpe: {analysis['best_sharpe']['scaling']} ({analysis['best_sharpe']['value']:.2f})")
        print(f"  Highest Return: {analysis['best_return']['scaling']} ({analysis['best_return']['value']:.2%})")
        print(f"  Lowest Drawdown: {analysis['lowest_drawdown']['scaling']} ({analysis['lowest_drawdown']['value']:.2%})")
        print(f"  Best Calmar: {analysis['best_calmar']['scaling']} ({analysis['best_calmar']['value']:.2f})")
        
        if "optimal_scaling" in analysis:
            print(f"  Optimal Overall: {analysis['optimal_scaling']['scaling']} (score: {analysis['optimal_scaling']['score']:.2f})")
        
        if "half_vs_quarter" in analysis:
            hvq = analysis["half_vs_quarter"]
            print(f"\nHalf vs Quarter Kelly:")
            print(f"  Sharpe Improvement: {hvq['sharpe_improvement']:.2f}")
            print(f"  Return Improvement: {hvq['return_improvement']:.2%}")
            print(f"  Drawdown Penalty: {hvq['drawdown_penalty']:.2%}")
    
    print("="*80)

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

# Build half Kelly portfolio
portfolio = build_half_kelly_portfolio(returns_df)
print_portfolio_results(portfolio)

# Compare different scalings
scaling_results = compare_kelly_scalings(returns_df, scalings=[0.125, 0.25, 0.5, 0.75, 1.0])
print_scaling_comparison(scaling_results)

# Analyze and get recommendations
analysis = analyze_kelly_scalings(scaling_results)
print(f"\nRecommended scaling: {analysis['optimal_scaling']['scaling']}")

# Use optimal weights for live trading
optimal_portfolio = scaling_results[f"scaling_{analysis['optimal_scaling']['scaling']:.3f}"]
optimal_weights = dict(zip(optimal_portfolio.assets, optimal_portfolio.weights))
print(f"Optimal weights: {optimal_weights}")
"""
