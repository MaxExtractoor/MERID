"""
Volatility Targeting on Top of Fractional Kelly

Target a long-run volatility and scale Kelly fraction accordingly.
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def realized_vol(returns: pd.Series, periods_per_year: int) -> float:
    """
    Calculate realized volatility from returns series.
    
    Args:
        returns: Series of returns
        periods_per_year: Number of periods per year for annualization
        
    Returns:
        Realized volatility (annualized)
    """
    if returns.empty:
        return 0.0
    
    sigma = returns.std()
    return float(sigma * np.sqrt(periods_per_year))

def volatility_targeted_fraction(
    base_fraction: float,
    per_trade_returns: pd.Series,
    target_vol: float = 0.20,
    periods_per_year: int = 252 * 24 * 4,  # 15m ~ 4 per hour
) -> float:
    """
    Scale base_fraction so realized volatility matches target volatility.
    
    Args:
        base_fraction: Base Kelly fraction (e.g., half Kelly)
        per_trade_returns: Series of Kelly-sized per-trade returns (pnl * f)
        target_vol: Target annual volatility (default 20%)
        periods_per_year: Number of periods per year
        
    Returns:
        Adjusted Kelly fraction
    """
    if per_trade_returns.empty:
        return base_fraction
    
    current_vol = realized_vol(per_trade_returns, periods_per_year)
    
    if current_vol == 0 or np.isnan(current_vol):
        logger.warning(f"Zero or NaN volatility detected, using base fraction")
        return base_fraction
    
    # Scale factor to match target volatility
    scale = target_vol / current_vol
    
    # Apply scaling to base fraction
    adjusted_fraction = base_fraction * scale
    
    # Apply reasonable bounds
    max_fraction = base_fraction * 2.0  # Don't double the base fraction
    min_fraction = base_fraction * 0.1  # Don't go below 10% of base
    
    adjusted_fraction = max(min_fraction, min(adjusted_fraction, max_fraction))
    
    logger.debug(f"Volatility targeting: current={current_vol:.2%}, target={target_vol:.2%}, "
                f"scale={scale:.2f}, adjusted_fraction={adjusted_fraction:.3f}")
    
    return adjusted_fraction

def adaptive_volatility_targeting(
    base_fraction: float,
    per_trade_returns: pd.Series,
    target_vol: float = 0.20,
    periods_per_year: int = 252 * 24 * 4,
    window: int = 100,
    min_periods: int = 20
) -> pd.Series:
    """
    Adaptive volatility targeting with rolling window.
    
    Args:
        base_fraction: Base Kelly fraction
        per_trade_returns: Series of per-trade returns
        target_vol: Target volatility
        periods_per_year: Periods per year
        window: Rolling window size
        min_periods: Minimum periods for calculation
        
    Returns:
        Series of adjusted fractions
    """
    if per_trade_returns.empty or len(per_trade_returns) < min_periods:
        return pd.Series([base_fraction] * len(per_trade_returns), index=per_trade_returns.index)
    
    # Calculate rolling volatility
    rolling_vol = per_trade_returns.rolling(window=window, min_periods=min_periods).std()
    rolling_vol_annualized = rolling_vol * np.sqrt(periods_per_year)
    
    # Calculate scaling factors
    scaling_factors = target_vol / rolling_vol_annualized
    scaling_factors = scaling_factors.fillna(1.0)  # Use 1.0 for NaN values
    
    # Apply bounds
    scaling_factors = scaling_factors.clip(0.1, 2.0)  # 10% to 200% of base
    
    # Calculate adjusted fractions
    adjusted_fractions = base_fraction * scaling_factors
    
    return adjusted_fractions

def calculate_volatility_metrics(returns: pd.Series, periods_per_year: int = 252 * 24 * 4) -> dict:
    """
    Calculate comprehensive volatility metrics.
    
    Args:
        returns: Series of returns
        periods_per_year: Periods per year
        
    Returns:
        Dictionary with volatility metrics
    """
    if returns.empty:
        return {"error": "Empty returns series"}
    
    # Basic volatility
    vol = realized_vol(returns, periods_per_year)
    
    # Rolling volatilities
    vol_30d = realized_vol(returns.tail(30), periods_per_year / 365 * 30)
    vol_90d = realized_vol(returns.tail(90), periods_per_year / 365 * 90)
    
    # Volatility regime
    vol_mean = vol
    vol_std = returns.std() * np.sqrt(periods_per_year)
    
    # Percentile-based metrics
    vol_95th = returns.quantile(0.95) * np.sqrt(periods_per_year)
    vol_5th = returns.quantile(0.05) * np.sqrt(periods_per_year)
    
    return {
        "current_volatility": vol,
        "volatility_30d": vol_30d,
        "volatility_90d": vol_90d,
        "volatility_mean": vol_mean,
        "volatility_std": vol_std,
        "volatility_95th": vol_95th,
        "volatility_5th": vol_5th,
        "volatility_regime": _classify_volatility_regime(vol),
        "volatility_stability": vol_std / vol_mean if vol_mean > 0 else 0.0
    }

def _classify_volatility_regime(vol: float) -> str:
    """Classify volatility regime."""
    if vol < 0.10:
        return "low"
    elif vol < 0.25:
        return "normal"
    elif vol < 0.50:
        return "high"
    else:
        return "extreme"

def validate_volatility_targeting(
    base_fraction: float,
    target_vol: float,
    current_vol: float,
    adjusted_fraction: float
) -> dict:
    """
    Validate volatility targeting parameters.
    
    Args:
        base_fraction: Base Kelly fraction
        target_vol: Target volatility
        current_vol: Current volatility
        adjusted_fraction: Adjusted fraction
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Validate base fraction
    if not (0.0 < base_fraction <= 1.0):
        validation["warnings"].append(f"Base fraction out of range: {base_fraction}")
        validation["recommendations"].append("Base fraction should be between 0 and 1")
    
    # Validate target volatility
    if not (0.05 <= target_vol <= 1.0):
        validation["warnings"].append(f"Target volatility unusual: {target_vol:.1%}")
        validation["recommendations"].append("Target volatility typically 5-100% annually")
    
    # Validate adjustment magnitude
    adjustment_ratio = adjusted_fraction / base_fraction if base_fraction > 0 else 0
    if adjustment_ratio > 2.0:
        validation["warnings"].append(f"Large adjustment: {adjustment_ratio:.1f}x base fraction")
        validation["recommendations"].append("Consider smaller target volatility")
    elif adjustment_ratio < 0.5:
        validation["warnings"].append(f"Small adjustment: {adjustment_ratio:.1f}x base fraction")
        validation["recommendations"].append("Consider higher target volatility")
    
    # Check volatility regime
    if current_vol > 0.50:
        validation["warnings"].append(f"High current volatility: {current_vol:.1%}")
        validation["recommendations"].append("Consider reducing position size in high volatility")
    elif current_vol < 0.05:
        validation["warnings"].append(f"Low current volatility: {current_vol:.1%}")
        validation["recommendations"].append("Consider increasing position size in low volatility")
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def simulate_volatility_targeting(
    base_fraction: float,
    trade_pnls: list[float],
    target_vol: float = 0.20,
    periods_per_year: int = 252 * 24 * 4,
    n_simulations: int = 1000
) -> dict:
    """
    Simulate volatility targeting with random trade sequences.
    
    Args:
        base_fraction: Base Kelly fraction
        trade_pnls: List of trade PnLs
        target_vol: Target volatility
        periods_per_year: Periods per year
        n_simulations: Number of simulations
        
    Returns:
        Simulation results
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    import numpy as np
    np.random.seed(42)
    
    results = {
        "adjusted_fractions": [],
        "realized_vols": [],
        "final_capitals": []
    }
    
    pnls_array = np.array(trade_pnls)
    
    for i in range(n_simulations):
        # Random permutation of trades
        perm_pnls = np.random.permutation(pnls_array)
        
        # Calculate per-trade returns with base fraction
        per_trade_returns = pd.Series([base_fraction * pnl for pnl in perm_pnls])
        
        # Calculate adjusted fraction
        adj_fraction = volatility_targeted_fraction(
            base_fraction, per_trade_returns, target_vol, periods_per_year
        )
        
        # Calculate realized volatility with adjusted fraction
        adj_returns = pd.Series([adj_fraction * pnl for pnl in perm_pnls])
        realized_vol = realized_vol(adj_returns, periods_per_year)
        
        # Calculate final capital
        capital = 1.0
        for pnl in perm_pnls:
            capital *= (1 + adj_fraction * pnl)
        
        results["adjusted_fractions"].append(adj_fraction)
        results["realized_vols"].append(realized_vol)
        results["final_capitals"].append(capital)
    
    # Calculate statistics
    results["avg_adjusted_fraction"] = np.mean(results["adjusted_fractions"])
    results["avg_realized_vol"] = np.mean(results["realized_vols"])
    results["avg_final_capital"] = np.mean(results["final_capitals"])
    results["vol_target_hit_rate"] = np.mean([abs(vol - target_vol) < 0.05 for vol in results["realized_vols"]])
    
    return results

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample per-trade returns
np.random.seed(42)
base_fraction = 0.3  # Half Kelly
trade_pnls = np.random.choice([0.01, -0.005, 0.015, -0.01, 0.02, -0.015], size=100)

# Calculate per-trade returns
per_trade_returns = pd.Series([base_fraction * pnl for pnl in trade_pnls])

# Apply volatility targeting
adjusted_fraction = volatility_targeted_fraction(
    base_fraction, per_trade_returns, target_vol=0.20
)

print(f"Base fraction: {base_fraction:.3f}")
print(f"Adjusted fraction: {adjusted_fraction:.3f}")

# Adaptive volatility targeting
adjusted_fractions = adaptive_volatility_targeting(
    base_fraction, per_trade_returns, target_vol=0.20
)

print(f"Adaptive fractions (latest): {adjusted_fractions.iloc[-1]:.3f}")

# Volatility metrics
vol_metrics = calculate_volatility_metrics(per_trade_returns)
print(f"Volatility metrics: {vol_metrics}")

# Simulation
sim_results = simulate_volatility_targeting(base_fraction, trade_pnls.tolist())
print(f"Simulation results: {sim_results}")
"""
