"""Monte Carlo simulation for portfolio risk analysis.

CRITICAL: The 15m Kalshi crypto system uses a fixed $1 global exposure cap
(MERID_FIXED_EXPOSURE_CAP_USD). This module is DEPRECATED for the production
15m crypto stack. The production system uses slot-based allocation via
GlobalSlotAllocator with a hard $1 cap across all assets.

Legacy Features (NOT USED IN PRODUCTION):
- Portfolio value at risk (VaR) estimation
- Expected shortfall calculation
- Scenario analysis for different market conditions
- Stress testing of allocation strategies
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("merid.risk.monte_carlo")


@dataclass
class SimulationResult:
    """Results from a Monte Carlo simulation."""
    mean_return: float
    std_return: float
    var_95: float  # Value at risk at 95% confidence
    var_99: float  # Value at risk at 99% confidence
    expected_shortfall_95: float  # Expected shortfall at 95% confidence
    percentile_5: float  # 5th percentile
    percentile_95: float  # 95th percentile
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float


def run_monte_carlo_simulation(
    initial_portfolio_value: float,
    expected_returns: Dict[str, float],
    volatilities: Dict[str, float],
    correlation_matrix: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
    num_simulations: int = 10000,
    time_horizon_days: int = 1,
    confidence_level: float = 0.95
) -> SimulationResult:
    """
    Run Monte Carlo simulation for portfolio risk analysis.
    
    Args:
        initial_portfolio_value: Starting portfolio value in USD
        expected_returns: Dict mapping asset to expected daily return
        volatilities: Dict mapping asset to daily volatility
        correlation_matrix: Correlation matrix between assets
        weights: Dict mapping asset to portfolio weight (sum to 1.0)
        num_simulations: Number of Monte Carlo paths to simulate
        time_horizon_days: Time horizon in days
        confidence_level: Confidence level for VaR (default 0.95)
    
    Returns:
        SimulationResult with risk metrics
    """
    assets = list(expected_returns.keys())
    n_assets = len(assets)
    
    if n_assets == 0:
        logger.warning("[MONTE-CARLO] No assets provided, returning zero result")
        return SimulationResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    
    # Filter to only assets that have both expected returns and weights
    assets = [a for a in assets if a in weights]
    n_assets = len(assets)
    
    if n_assets == 0:
        logger.warning("[MONTE-CARLO] No assets with both returns and weights, returning zero result")
        return SimulationResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    
    # Filter weights to only include assets in expected_returns
    weights = {a: weights[a] for a in assets}
    
    # Re-normalize weights after filtering
    total_weight = sum(weights.values())
    if total_weight > 0:
        weights = {k: v / total_weight for k, v in weights.items()}
    
    # Filter expected_returns, volatilities, and correlation_matrix to only include assets in weights
    expected_returns = {a: expected_returns[a] for a in assets}
    volatilities = {a: volatilities[a] for a in assets if a in volatilities}
    correlation_matrix = {
        a: {b: correlation_matrix[a].get(b, 0.0) for b in assets}
        for a in assets
    }
    
    # Validate inputs
    if abs(sum(weights.values()) - 1.0) > 0.01:
        logger.warning(
            "[MONTE-CARLO] Weights do not sum to 1.0 (sum=%.2f), normalizing",
            sum(weights.values())
        )
        total_weight = sum(weights.values())
        weights = {k: v / total_weight for k, v in weights.items()}
    
    # Build covariance matrix from volatilities and correlations
    cov_matrix = np.zeros((n_assets, n_assets))
    for i, asset_i in enumerate(assets):
        for j, asset_j in enumerate(assets):
            corr = correlation_matrix.get(asset_i, {}).get(asset_j, 0.0)
            cov_matrix[i, j] = corr * volatilities[asset_i] * volatilities[asset_j]
    
    # Cholesky decomposition for correlated random variables
    try:
        chol = np.linalg.cholesky(cov_matrix)
    except np.linalg.LinAlgError:
        logger.warning("[MONTE-CARLO] Covariance matrix not positive definite, using diagonal")
        cov_matrix = np.diag([volatilities[a] ** 2 for a in assets])
        chol = np.linalg.cholesky(cov_matrix)
    
    # Generate random returns
    np.random.seed(42)  # For reproducibility
    random_shocks = np.random.randn(num_simulations, n_assets)
    correlated_shocks = random_shocks @ chol.T
    
    # Calculate portfolio returns for each simulation
    portfolio_returns = np.zeros(num_simulations)
    for i in range(num_simulations):
        asset_returns = expected_returns_array = np.array([expected_returns[a] for a in assets])
        shocks = correlated_shocks[i]
        simulated_returns = asset_returns + shocks
        portfolio_returns[i] = sum(weights[a] * simulated_returns[j] for j, a in enumerate(assets))
    
    # Scale by time horizon (assuming independence across days)
    portfolio_returns *= np.sqrt(time_horizon_days)
    
    # Calculate portfolio values
    portfolio_values = initial_portfolio_value * (1 + portfolio_returns)
    
    # Calculate statistics
    mean_return = np.mean(portfolio_returns)
    std_return = np.std(portfolio_returns)
    
    # Value at Risk
    var_95 = np.percentile(portfolio_returns, 5)  # 5th percentile for 95% VaR
    var_99 = np.percentile(portfolio_returns, 1)  # 1st percentile for 99% VaR
    
    # Expected Shortfall (average of worst 5%)
    worst_5_pct = portfolio_returns[portfolio_returns <= np.percentile(portfolio_returns, 5)]
    expected_shortfall_95 = np.mean(worst_5_pct) if len(worst_5_pct) > 0 else var_95
    
    # Percentiles
    percentile_5 = np.percentile(portfolio_values, 5)
    percentile_95 = np.percentile(portfolio_values, 95)
    
    # Max drawdown (simplified)
    cumulative_returns = np.cumprod(1 + portfolio_returns / 100)  # Convert to multiplier
    peak = np.maximum.accumulate(cumulative_returns)
    drawdown = (peak - cumulative_returns) / peak
    max_drawdown = np.max(drawdown)
    
    # Sharpe ratio (assuming 0% risk-free rate)
    sharpe_ratio = mean_return / std_return if std_return > 0 else 0.0
    
    # Win rate
    win_rate = np.sum(portfolio_returns > 0) / num_simulations
    
    result = SimulationResult(
        mean_return=mean_return,
        std_return=std_return,
        var_95=var_95,
        var_99=var_99,
        expected_shortfall_95=expected_shortfall_95,
        percentile_5=percentile_5,
        percentile_95=percentile_95,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        win_rate=win_rate
    )
    
    logger.info(
        "[MONTE-CARLO] Simulation complete: %d paths, horizon=%d days, "
        "mean_return=%.2f%%, std=%.2f%%, VaR_95=%.2f%%, Sharpe=%.2f",
        num_simulations, time_horizon_days, mean_return * 100, std_return * 100,
        var_95 * 100, sharpe_ratio
    )
    
    return result


def stress_test_allocation(
    current_allocation: Dict[str, float],
    stress_scenarios: List[Dict[str, float]],
    correlation_matrix: Dict[str, Dict[str, float]],
    volatilities: Dict[str, float]
) -> Dict[str, SimulationResult]:
    """
    Stress test current allocation against different market scenarios.
    
    DEPRECATED: This function is NOT used in the 15m Kalshi crypto production stack.
    The production system uses fixed $1 slot allocation instead of percentage-based
    allocation weights.
    
    Args:
        current_allocation: Current portfolio weights (percentage-based, deprecated)
        stress_scenarios: List of scenario dicts with asset returns
        correlation_matrix: Correlation matrix
        volatilities: Asset volatilities
    
    Returns:
        Dict mapping scenario name to SimulationResult
    """
    results = {}
    
    for scenario in stress_scenarios:
        scenario_name = scenario.get("name", "unnamed")
        scenario_returns = {k: v for k, v in scenario.items() if k != "name"}
        
        # Use scenario returns as expected returns for simulation
        result = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,  # Normalized to $1
            expected_returns=scenario_returns,
            volatilities=volatilities,
            correlation_matrix=correlation_matrix,
            weights=current_allocation,
            num_simulations=5000,
            time_horizon_days=1
        )
        
        results[scenario_name] = result
    
    return results


def generate_stress_scenarios() -> List[Dict[str, float]]:
    """
    Generate standard stress test scenarios for crypto assets.
    
    Returns:
        List of scenario dicts with asset returns
    """
    scenarios = [
        {
            "name": "baseline",
            "BTC": 0.001,
            "ETH": 0.001,
            "SOL": 0.0015,
            "XRP": 0.001,
            "DOGE": 0.002
        },
        {
            "name": "bull_market",
            "BTC": 0.05,
            "ETH": 0.06,
            "SOL": 0.08,
            "XRP": 0.07,
            "DOGE": 0.10
        },
        {
            "name": "bear_market",
            "BTC": -0.05,
            "ETH": -0.06,
            "SOL": -0.08,
            "XRP": -0.07,
            "DOGE": -0.10
        },
        {
            "name": "crash",
            "BTC": -0.15,
            "ETH": -0.18,
            "SOL": -0.20,
            "XRP": -0.15,
            "DOGE": -0.25
        },
        {
            "name": "btc_outperform",
            "BTC": 0.03,
            "ETH": 0.01,
            "SOL": 0.00,
            "XRP": -0.01,
            "DOGE": -0.02
        }
    ]
    
    return scenarios


def calculate_portfolio_risk_metrics(
    allocation: Dict[str, float],
    correlation_matrix: Dict[str, Dict[str, float]],
    volatilities: Dict[str, float]
) -> Dict[str, float]:
    """
    Calculate analytical portfolio risk metrics (no simulation).
    
    DEPRECATED: This function is NOT used in the 15m Kalshi crypto production stack.
    The production system uses fixed $1 slot allocation instead of percentage-based
    allocation weights.
    
    Args:
        allocation: Portfolio weights (percentage-based, deprecated)
        correlation_matrix: Correlation matrix
        volatilities: Asset volatilities
    
    Returns:
        Dict with risk metrics
    """
    assets = list(allocation.keys())
    n = len(assets)
    
    if n == 0:
        return {"portfolio_volatility": 0.0, "diversification_ratio": 0.0}
    
    # Calculate portfolio variance
    portfolio_variance = 0.0
    for i, asset_i in enumerate(assets):
        for j, asset_j in enumerate(assets):
            corr = correlation_matrix.get(asset_i, {}).get(asset_j, 0.0)
            portfolio_variance += (
                allocation[asset_i] * allocation[asset_j] *
                volatilities[asset_i] * volatilities[asset_j] * corr
            )
    
    portfolio_volatility = np.sqrt(portfolio_variance)
    
    # Calculate weighted average volatility (undiversified)
    weighted_avg_vol = sum(allocation[a] * volatilities[a] for a in assets)
    
    # Diversification ratio
    diversification_ratio = weighted_avg_vol / portfolio_volatility if portfolio_volatility > 0 else 0.0
    
    return {
        "portfolio_volatility": portfolio_volatility,
        "diversification_ratio": diversification_ratio,
        "weighted_avg_volatility": weighted_avg_vol
    }
