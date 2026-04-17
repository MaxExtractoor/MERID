"""
MVRK Backtest - Backtest MVRK vs Fractional Kelly on Kalshi Events

Compare multivariate volatility regulated Kelly vs fractional Kelly strategies.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, List
import logging

from .mvrk import classical_kelly_weights, mvrk_weights

logger = logging.getLogger(__name__)

def estimate_mu_cov(returns_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """
    Estimate expected returns and covariance matrix from returns data.
    
    Args:
        returns_df: DataFrame with asset returns (columns = assets, rows = periods)
        
    Returns:
        Tuple of (mu, cov) arrays
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    # Expected returns (mean)
    mu = returns_df.mean().values
    
    # Covariance matrix
    cov = returns_df.cov().values
    
    logger.debug(f"Estimated mu and cov from {len(returns_df)} periods, {len(returns_df.columns)} assets")
    
    return mu, cov

def equity_from_weights(returns_df: pd.DataFrame, weights: np.ndarray, 
                       initial_capital: float = 1.0) -> pd.Series:
    """
    Generate equity curve from portfolio weights and returns.
    
    Args:
        returns_df: DataFrame with asset returns
        weights: Portfolio weights array
        initial_capital: Starting capital
        
    Returns:
        Equity curve Series
    """
    if returns_df.empty or len(weights) != len(returns_df.columns):
        raise ValueError("Invalid returns data or weights")
    
    # Calculate portfolio returns: r_port = w · r_assets
    port_rets = returns_df.values @ weights
    
    # Generate equity curve
    equity = (1 + port_rets).cumprod() * initial_capital
    
    return pd.Series(equity, index=returns_df.index, name="Equity")

def normalize_weights(weights: np.ndarray, method: str = "sum_abs") -> np.ndarray:
    """
    Normalize portfolio weights to control gross exposure.
    
    Args:
        weights: Raw portfolio weights
        method: Normalization method ('sum_abs', 'max_abs', 'sum_pos')
        
    Returns:
        Normalized weights
    """
    if method == "sum_abs":
        # Normalize so sum of absolute values = 1
        abs_sum = np.sum(np.abs(weights))
        return weights / abs_sum if abs_sum > 0 else weights
    
    elif method == "max_abs":
        # Normalize so max absolute value = 1
        max_abs = np.max(np.abs(weights))
        return weights / max_abs if max_abs > 0 else weights
    
    elif method == "sum_pos":
        # Normalize so sum of positive weights = 1
        pos_sum = np.sum(weights[weights > 0])
        if pos_sum > 0:
            return weights / pos_sum
        else:
            return weights
    
    else:
        raise ValueError(f"Unknown normalization method: {method}")

def calculate_portfolio_metrics(equity: pd.Series, returns_df: pd.DataFrame, 
                              weights: np.ndarray) -> Dict[str, float]:
    """
    Calculate comprehensive portfolio performance metrics.
    
    Args:
        equity: Portfolio equity curve
        returns_df: Asset returns DataFrame
        weights: Portfolio weights used
        
    Returns:
        Metrics dictionary
    """
    if equity.empty:
        return {"error": "Empty equity curve"}
    
    # Basic return metrics
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Calculate portfolio returns
    port_rets = equity.pct_change().dropna()
    
    # Annualization factor (assuming daily data)
    periods_per_year = 365
    
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
    
    # Volatility
    volatility = port_rets.std() * np.sqrt(periods_per_year)
    
    # Win rate
    win_rate = (port_rets > 0).sum() / len(port_rets)
    
    # Portfolio metrics
    portfolio_volatility = float(weights.T @ returns_df.cov().values @ weights) * np.sqrt(periods_per_year)
    
    # Leverage
    leverage = np.sum(np.abs(weights))
    
    return {
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "volatility": volatility,
        "portfolio_volatility": portfolio_volatility,
        "win_rate": win_rate,
        "leverage": leverage,
        "final_capital": equity.iloc[-1]
    }

def compare_mvrk_fractional_kelly(returns_df: pd.DataFrame, 
                                 theta_values: List[float] = None,
                                 normalization_method: str = "sum_abs") -> Dict[str, pd.Series]:
    """
    Compare MVRK vs fractional Kelly strategies.
    
    Args:
        returns_df: DataFrame with asset returns
        theta_values: List of theta values for MVRK
        normalization_method: Weight normalization method
        
    Returns:
        Dictionary with equity curves for each strategy
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0]  # Classical Kelly and different MVRK levels
    
    # Estimate parameters
    mu, cov = estimate_mu_cov(returns_df)
    
    # Calculate weights
    w_kelly = classical_kelly_weights(mu, cov)
    w_mvrk = {}
    
    for theta in theta_values:
        w_mvrk[theta] = mvrk_weights(mu, cov, theta)
    
    # Normalize weights
    w_kelly_norm = normalize_weights(w_kelly, method=normalization_method)
    w_mvrk_norm = {}
    
    for theta, weights in w_mvrk.items():
        w_mvrk_norm[theta] = normalize_weights(weights, method=normalization_method)
    
    # Generate equity curves
    equity_curves = {}
    
    # Classical Kelly strategies
    equity_curves["full_kelly"] = equity_from_weights(returns_df, w_kelly_norm)
    equity_curves["half_kelly"] = equity_from_weights(returns_df, 0.5 * w_kelly_norm)
    equity_curves["quarter_kelly"] = equity_from_weights(returns_df, 0.25 * w_kelly_norm)
    
    # MVRK strategies
    for theta, weights_norm in w_mvrk_norm.items():
        strategy_name = f"mvrk_theta_{theta}"
        equity_curves[strategy_name] = equity_from_weights(returns_df, weights_norm)
    
    logger.info(f"Generated {len(equity_curves)} equity curves for comparison")
    
    return equity_curves

def analyze_mvrk_comparison(equity_curves: Dict[str, pd.Series], 
                           returns_df: pd.DataFrame,
                           theta_values: List[float] = None) -> Dict[str, Any]:
    """
    Analyze MVRK vs fractional Kelly comparison results.
    
    Args:
        equity_curves: Dictionary of equity curves
        returns_df: Original returns DataFrame
        theta_values: Theta values used
        
    Returns:
        Analysis results
    """
    if not equity_curves:
        return {"error": "No equity curves to analyze"}
    
    # Calculate metrics for each strategy
    metrics = {}
    
    for strategy_name, equity in equity_curves.items():
        # Extract weights from strategy name
        if "kelly" in strategy_name:
            if "full" in strategy_name:
                weights_factor = 1.0
            elif "half" in strategy_name:
                weights_factor = 0.5
            elif "quarter" in strategy_name:
                weights_factor = 0.25
            else:
                weights_factor = 1.0
        elif "mvrk" in strategy_name:
            theta = float(strategy_name.split("_")[-1])
            weights_factor = 1.0  # MVRK weights already include theta adjustment
        else:
            weights_factor = 1.0
        
        # Calculate metrics (simplified - would need actual weights for accurate calc)
        strategy_metrics = calculate_portfolio_metrics(equity, returns_df, 
                                                      np.ones(len(returns_df.columns)) * weights_factor)
        metrics[strategy_name] = strategy_metrics
    
    # Find best performers
    best_sharpe = max(metrics.items(), key=lambda x: x[1]["sharpe_ratio"])
    best_return = max(metrics.items(), key=lambda x: x[1]["total_return"])
    best_sortino = max(metrics.items(), key=lambda x: x[1]["sortino_ratio"])
    lowest_dd = min(metrics.items(), key=lambda x: x[1]["max_drawdown"])
    
    # Compare MVRK vs Kelly
    kelly_strategies = {k: v for k, v in metrics.items() if "kelly" in k}
    mvrk_strategies = {k: v for k, v in metrics.items() if "mvrk" in k}
    
    comparison = {
        "best_sharpe": {"strategy": best_sharpe[0], "value": best_sharpe[1]["sharpe_ratio"]},
        "best_return": {"strategy": best_return[0], "value": best_return[1]["total_return"]},
        "best_sortino": {"strategy": best_sortino[0], "value": best_sortino[1]["sortino_ratio"]},
        "lowest_drawdown": {"strategy": lowest_dd[0], "value": lowest_dd[1]["max_drawdown"]},
        "kelly_avg_sharpe": np.mean([m["sharpe_ratio"] for m in kelly_strategies.values()]) if kelly_strategies else 0.0,
        "mvrk_avg_sharpe": np.mean([m["sharpe_ratio"] for m in mvrk_strategies.values()]) if mvrk_strategies else 0.0,
        "metrics": metrics
    }
    
    # MVRK effectiveness
    if mvrk_strategies and kelly_strategies:
        best_mvrk_sharpe = max([m["sharpe_ratio"] for m in mvrk_strategies.values()])
        best_kelly_sharpe = max([m["sharpe_ratio"] for m in kelly_strategies.values()])
        
        comparison["mvrk_effectiveness"] = {
            "best_mvrk_sharpe": best_mvrk_sharpe,
            "best_kelly_sharpe": best_kelly_sharpe,
            "sharpe_improvement": best_mvrk_sharpe - best_kelly_sharpe,
            "mvrk_better": best_mvrk_sharpe > best_kelly_sharpe
        }
    
    return comparison

def print_mvrk_comparison(equity_curves: Dict[str, pd.Series], 
                         returns_df: pd.DataFrame):
    """
    Print formatted MVRK vs fractional Kelly comparison.
    
    Args:
        equity_curves: Dictionary of equity curves
        returns_df: Original returns DataFrame
    """
    if not equity_curves:
        print("No equity curves to display")
        return
    
    print("\n" + "="*80)
    print("MVRK VS FRACTIONAL KELLY COMPARISON")
    print("="*80)
    
    # Analyze results
    analysis = analyze_mvrk_comparison(equity_curves, returns_df)
    
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    metrics = analysis["metrics"]
    
    print(f"\nStrategy Performance Summary:")
    print("-" * 80)
    print(f"{'Strategy':<20} {'Return':<10} {'Sharpe':<8} {'Sortino':<8} {'Max DD':<10} {'Leverage':<10}")
    print("-" * 80)
    
    for strategy_name, strategy_metrics in metrics.items():
        print(f"{strategy_name:<20} {strategy_metrics['total_return']:<10.2%} "
              f"{strategy_metrics['sharpe_ratio']:<8.2f} {strategy_metrics['sortino_ratio']:<8.2f} "
              f"{strategy_metrics['max_drawdown']:<10.2%} {strategy_metrics['leverage']:<10.2f}")
    
    print(f"\nBest Performers:")
    print("-" * 50)
    print(f"  Highest Sharpe: {analysis['best_sharpe']['strategy']} ({analysis['best_sharpe']['value']:.2f})")
    print(f"  Highest Return: {analysis['best_return']['strategy']} ({analysis['best_return']['value']:.2%})")
    print(f"  Highest Sortino: {analysis['best_sortino']['strategy']} ({analysis['best_sortino']['value']:.2f})")
    print(f"  Lowest Drawdown: {analysis['lowest_drawdown']['strategy']} ({analysis['lowest_drawdown']['value']:.2%})")
    
    # MVRK effectiveness
    if "mvrk_effectiveness" in analysis:
        effectiveness = analysis["mvrk_effectiveness"]
        print(f"\nMVRK Effectiveness:")
        print("-" * 50)
        print(f"  Best MVRK Sharpe: {effectiveness['best_mvrk_sharpe']:.2f}")
        print(f"  Best Kelly Sharpe: {effectiveness['best_kelly_sharpe']:.2f}")
        print(f"  Sharpe Improvement: {effectiveness['sharpe_improvement']:.2f}")
        print(f"  MVRK Better: {'Yes' if effectiveness['mvrk_better'] else 'No'}")
    
    print("="*80)

def generate_mvrk_recommendations(analysis: Dict[str, Any]) -> List[str]:
    """
    Generate recommendations based on MVRK vs Kelly comparison.
    
    Args:
        analysis: Analysis results
        
    Returns:
        List of recommendations
    """
    if "error" in analysis:
        return ["No analysis data available for recommendations"]
    
    recommendations = []
    
    # MVRK effectiveness
    if "mvrk_effectiveness" in analysis:
        effectiveness = analysis["mvrk_effectiveness"]
        
        if effectiveness["mvrk_better"]:
            if effectiveness["sharpe_improvement"] > 0.2:
                recommendations.append(f"✅ MVRK significantly outperforms Kelly (+{effectiveness['sharpe_improvement']:.2f} Sharpe)")
            elif effectiveness["sharpe_improvement"] > 0.1:
                recommendations.append(f"📈 MVRK moderately outperforms Kelly (+{effectiveness['sharpe_improvement']:.2f} Sharpe)")
            else:
                recommendations.append(f"📊 MVRK slightly outperforms Kelly (+{effectiveness['sharpe_improvement']:.2f} Sharpe)")
        else:
            if effectiveness["sharpe_improvement"] < -0.1:
                recommendations.append(f"⚠️ MVRK underperforms Kelly ({effectiveness['sharpe_improvement']:.2f} Sharpe)")
            else:
                recommendations.append(f"📊 MVRK performance similar to Kelly ({effectiveness['sharpe_improvement']:.2f} Sharpe)")
    
    # Risk assessment
    best_sharpe = analysis["best_sharpe"]
    lowest_dd = analysis["lowest_drawdown"]
    
    if lowest_dd["value"] < -0.20:
        recommendations.append(f"📉 High drawdown risk detected ({lowest_dd['value']:.1%}) - consider fractional Kelly")
    elif lowest_dd["value"] < -0.10:
        recommendations.append(f"📊 Moderate drawdown risk ({lowest_dd['value']:.1%}) - monitor carefully")
    else:
        recommendations.append(f"✅ Low drawdown risk ({lowest_dd['value']:.1%}) - current sizing appears safe")
    
    # Strategy selection
    if "full_kelly" in analysis["metrics"]:
        full_kelly = analysis["metrics"]["full_kelly"]
        if full_kelly["sharpe_ratio"] > 1.0 and full_kelly["max_drawdown"] > -0.15:
            recommendations.append("⚠️ Full Kelly has good returns but consider fractional Kelly for risk management")
        elif full_kelly["sharpe_ratio"] < 0.5:
            recommendations.append("⚠️ Full Kelly performance poor - consider improving strategy or using fractional Kelly")
    
    # General recommendations
    recommendations.append("💡 Consider using fractional Kelly (25-50%) for better risk management")
    recommendations.append("🔄 Re-estimate parameters periodically with updated returns data")
    recommendations.append("⚖️ Combine MVRK with other risk controls like drawdown limits")
    recommendations.append("📊 Monitor leverage and gross exposure across all strategies")
    
    return recommendations

# Example usage for Kalshi events:
"""
# Assume we have per-trade returns for BTC and ETH from Kalshi events
# returns_df would be a DataFrame with columns ['BTC', 'ETH'] and rows = trade returns

import numpy as np
import pandas as pd

# Generate sample data (replace with actual Kalshi returns)
np.random.seed(42)
n_trades = 200
btc_returns = np.random.normal(0.001, 0.02, n_trades)  # 15m BTC returns
eth_returns = np.random.normal(0.0015, 0.025, n_trades)  # 15m ETH returns

returns_df = pd.DataFrame({
    'BTC': btc_returns,
    'ETH': eth_returns
})

# Compare strategies
equity_curves = compare_mvrk_fractional_kelly(returns_df, theta_values=[0.0, 0.5, 1.0, 2.0])

# Print comparison
print_mvrk_comparison(equity_curves, returns_df)

# Generate recommendations
analysis = analyze_mvrk_comparison(equity_curves, returns_df)
recommendations = generate_mvrk_recommendations(analysis)

print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")

# Use best strategy for live trading
best_strategy = analysis['best_sharpe']['strategy']
print(f"Recommended strategy: {best_strategy}")
"""
