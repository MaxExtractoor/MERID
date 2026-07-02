"""
Ratios - Sharpe and Sortino in the Kelly Backtest

Standard practice implementations for risk-adjusted return metrics.
"""

import numpy as np
import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4,  # 15m bars
    min_periods: int = 10
) -> float:
    """
    Calculate Sharpe ratio for returns series.
    
    Args:
        returns: Per-period returns series
        risk_free_rate: Annual risk-free rate (default 0.0)
        periods_per_year: Number of periods per year for annualization
        min_periods: Minimum periods required for calculation
        
    Returns:
        Sharpe ratio (annualized)
    """
    if len(returns) < min_periods:
        logger.warning(f"Insufficient data for Sharpe: {len(returns)} < {min_periods}")
        return 0.0
    
    # Remove NaN values
    clean_returns = returns.dropna()
    
    if len(clean_returns) < min_periods:
        return 0.0
    
    # Calculate excess returns
    excess = clean_returns - risk_free_rate / periods_per_year
    
    # Calculate mean and standard deviation
    mu = excess.mean()
    sigma = excess.std()
    
    # Handle edge cases
    if sigma == 0 or np.isnan(sigma) or np.isnan(mu):
        return 0.0
    
    # Calculate annualized Sharpe ratio
    sharpe = np.sqrt(periods_per_year) * mu / sigma
    
    return float(sharpe)

def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4,  # 15m bars
    min_periods: int = 10
) -> float:
    """
    Calculate Sortino ratio (downside deviation only).
    
    Args:
        returns: Per-period returns series
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year
        min_periods: Minimum periods required
        
    Returns:
        Sortino ratio (annualized)
    """
    if len(returns) < min_periods:
        return 0.0
    
    clean_returns = returns.dropna()
    
    if len(clean_returns) < min_periods:
        return 0.0
    
    # Calculate excess returns
    excess = clean_returns - risk_free_rate / periods_per_year
    
    # Calculate downside deviation (only negative returns)
    downside = excess[excess < 0]
    
    if len(downside) == 0:
        return 0.0
    
    downside_deviation = downside.std()
    
    if downside_deviation == 0 or np.isnan(downside_deviation):
        return 0.0
    
    # Calculate Sortino ratio
    mu = excess.mean()
    sortino = np.sqrt(periods_per_year) * mu / downside_deviation
    
    return float(sortino)

def calculate_all_ratios(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4,
    min_periods: int = 10
) -> dict:
    """
    Calculate comprehensive ratio metrics.
    
    Args:
        returns: Returns series
        risk_free_rate: Risk-free rate
        periods_per_year: Periods per year
        min_periods: Minimum periods
        
    Returns:
        Dictionary with all ratio metrics
    """
    if len(returns) < min_periods:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "information_ratio": 0.0,
            "error": "Insufficient data"
        }
    
    # Basic ratios
    sharpe = sharpe_ratio(returns, risk_free_rate, periods_per_year, min_periods)
    sortino = sortino_ratio(returns, risk_free_rate, periods_per_year, min_periods)
    
    # Calmar ratio (annualized return / max drawdown)
    cumulative = (1 + returns).cumprod()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = drawdown.min()
    
    annual_return = (cumulative.iloc[-1] / cumulative.iloc[0]) ** (periods_per_year / len(returns)) - 1
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0.0
    
    # Information ratio (vs risk-free)
    excess_returns = returns - risk_free_rate / periods_per_year
    info_ratio = excess_returns.mean() / excess_returns.std() * np.sqrt(periods_per_year) if excess_returns.std() > 0 else 0.0
    
    return {
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "information_ratio": info_ratio,
        "annual_return": annual_return,
        "max_drawdown": max_dd,
        "volatility": returns.std() * np.sqrt(periods_per_year),
        "downside_volatility": returns[returns < 0].std() * np.sqrt(periods_per_year)
    }

def rolling_ratios(
    returns: pd.Series,
    window: int = 100,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4,
    min_periods: int = 10
) -> pd.DataFrame:
    """
    Calculate rolling ratio metrics.
    
    Args:
        returns: Returns series
        window: Rolling window size
        risk_free_rate: Risk-free rate
        periods_per_year: Periods per year
        min_periods: Minimum periods per calculation
        
    Returns:
        DataFrame with rolling metrics
    """
    def _rolling_sharpe(window_returns):
        return sharpe_ratio(window_returns, risk_free_rate, periods_per_year, min_periods)
    
    def _rolling_sortino(window_returns):
        return sortino_ratio(window_returns, risk_free_rate, periods_per_year, min_periods)
    
    def _rolling_calmar(window_returns):
        if len(window_returns) < min_periods:
            return 0.0
        cumulative = (1 + window_returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak
        max_dd = drawdown.min()
        
        annual_return = (cumulative.iloc[-1] / cumulative.iloc[0]) ** (periods_per_year / len(window_returns)) - 1
        return annual_return / abs(max_dd) if max_dd != 0 else 0.0
    
    # Calculate rolling metrics
    rolling_df = pd.DataFrame({
        'sharpe_ratio': returns.rolling(window, min_periods=min_periods).apply(_rolling_sharpe),
        'sortino_ratio': returns.rolling(window, min_periods=min_periods).apply(_rolling_sortino),
        'calmar_ratio': returns.rolling(window, min_periods=min_periods).apply(_rolling_calmar),
        'volatility': returns.rolling(window, min_periods=min_periods).std() * np.sqrt(periods_per_year),
        'downside_volatility': returns.rolling(window, min_periods=min_periods).apply(
            lambda x: x[x < 0].std() * np.sqrt(periods_per_year) if len(x[x < 0]) > 0 else 0.0
        ),
        'mean_return': returns.rolling(window, min_periods=min_periods).mean() * periods_per_year
    })
    
    return rolling_df

def validate_ratio_inputs(returns: pd.Series, risk_free_rate: float = 0.0) -> dict:
    """
    Validate inputs for ratio calculations.
    
    Args:
        returns: Returns series
        risk_free_rate: Risk-free rate
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Check data length
    if len(returns) < 10:
        validation["valid"] = False
        validation["warnings"].append(f"Insufficient data: {len(returns)} periods")
        validation["recommendations"].append("Need at least 10 periods for reliable ratios")
        return validation
    
    # Check for NaN values
    nan_count = returns.isna().sum()
    if nan_count > 0:
        validation["warnings"].append(f"Missing data: {nan_count} NaN values")
        validation["recommendations"].append("Handle missing data before calculation")
    
    # Check for constant returns
    if returns.std() == 0:
        validation["warnings"].append("Zero volatility detected")
        validation["recommendations"].append("Returns may be constant, check data quality")
    
    # Check risk-free rate
    if not (0 <= risk_free_rate <= 1):
        validation["warnings"].append(f"Unusual risk-free rate: {risk_free_rate}")
        validation["recommendations"].append("Risk-free rate should be between 0 and 1")
    
    return validation

def compare_ratios_across_periods(returns: pd.Series, periods_list: list[int]) -> pd.DataFrame:
    """
    Compare ratios across different time periods.
    
    Args:
        returns: Returns series
        periods_list: List of periods to use
        
    Returns:
        DataFrame with ratio comparisons
    """
    results = []
    
    for periods in periods_list:
        if len(returns) >= periods:
            period_returns = returns.tail(periods)
            ratios = calculate_all_ratios(period_returns)
            ratios["periods"] = periods
            results.append(ratios)
    
    return pd.DataFrame(results).set_index("periods")

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample returns
np.random.seed(42)
returns = pd.Series(np.random.randn(200) * 0.01, name='returns')

# Calculate ratios
sharpe = sharpe_ratio(returns)
sortino = sortino_ratio(returns)
print(f"Sharpe: {sharpe:.2f}")
print(f"Sortino: {sortino:.2f}")

# All ratios
all_ratios = calculate_all_ratios(returns)
print(f"All ratios: {all_ratios}")

# Rolling ratios
rolling = rolling_ratios(returns, window=50)
print(f"Rolling Sharpe (latest): {rolling['sharpe_ratio'].iloc[-1]:.2f}")

# Validation
validation = validate_ratio_inputs(returns)
print(f"Validation: {validation}")
"""
