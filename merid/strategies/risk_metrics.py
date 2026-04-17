"""
Risk Metrics - Sharpe Ratio and Maximum Drawdown

Standard risk metrics used in trading analytics and performance evaluation.
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4,  # 15m bars ~ 4 per hour * 24 * 365
    min_periods: int = 10
) -> float:
    """
    Calculate Sharpe ratio for returns series.
    
    Args:
        returns: Per-period returns (not cumulative)
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
    periods_per_year: int = 365 * 24 * 4,
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
    downside_returns = excess[excess < 0]
    
    if len(downside_returns) == 0:
        return 0.0
    
    downside_deviation = downside_returns.std()
    
    if downside_deviation == 0 or np.isnan(downside_deviation):
        return 0.0
    
    # Calculate Sortino ratio
    sortino = np.sqrt(periods_per_year) * excess.mean() / downside_deviation
    
    return float(sortino)

def max_drawdown(equity: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity: Cumulative PnL or equity over time
        
    Returns:
        Maximum drawdown as negative number (e.g., -0.15 for -15%)
    """
    if equity.empty:
        return 0.0
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Calculate drawdown
    dd = (equity - peak) / peak.replace(0, np.nan)
    
    # Return maximum drawdown
    max_dd = dd.min()
    
    return float(max_dd) if not np.isnan(max_dd) else 0.0

def max_drawdown_duration(equity: pd.Series) -> Tuple[int, pd.Timestamp, pd.Timestamp]:
    """
    Calculate maximum drawdown duration.
    
    Args:
        equity: Equity curve
        
    Returns:
        Tuple of (duration in periods, start_time, end_time)
    """
    if equity.empty:
        return 0, None, None
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Find drawdown periods
    in_drawdown = equity < peak
    
    if not in_drawdown.any():
        return 0, None, None
    
    # Find drawdown periods
    drawdown_periods = []
    start = None
    
    for i, (timestamp, is_dd) in enumerate(in_drawdown.items()):
        if is_dd and start is None:
            start = timestamp
        elif not is_dd and start is not None:
            drawdown_periods.append((start, equity.index[i-1]))
            start = None
    
    # Handle ongoing drawdown
    if start is not None:
        drawdown_periods.append((start, equity.index[-1]))
    
    if not drawdown_periods:
        return 0, None, None
    
    # Find longest drawdown period
    max_duration = 0
    max_start, max_end = None, None
    
    for start, end in drawdown_periods:
        duration = len(equity.loc[start:end])
        if duration > max_duration:
            max_duration = duration
            max_start, max_end = start, end
    
    return max_duration, max_start, max_end

def calmar_ratio(equity: pd.Series, periods_per_year: int = 365 * 24 * 4) -> float:
    """
    Calculate Calmar ratio (annualized return / max drawdown).
    
    Args:
        equity: Equity curve
        periods_per_year: Number of periods per year
        
    Returns:
        Calmar ratio
    """
    if equity.empty or len(equity) < 2:
        return 0.0
    
    # Calculate total return
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Calculate max drawdown
    max_dd = max_drawdown(equity)
    
    if max_dd == 0 or np.isnan(max_dd):
        return 0.0
    
    # Annualize return
    periods = len(equity)
    annual_return = (1 + total_return) ** (periods_per_year / periods) - 1
    
    # Calculate Calmar ratio
    calmar = annual_return / abs(max_dd)
    
    return float(calmar)

def value_at_risk(
    returns: pd.Series,
    confidence_level: float = 0.05,
    min_periods: int = 10
) -> float:
    """
    Calculate Value at Risk (VaR).
    
    Args:
        returns: Returns series
        confidence_level: Confidence level (e.g., 0.05 for 5% VaR)
        min_periods: Minimum periods required
        
    Returns:
        VaR at specified confidence level
    """
    if len(returns) < min_periods:
        return 0.0
    
    clean_returns = returns.dropna()
    
    if len(clean_returns) < min_periods:
        return 0.0
    
    var = clean_returns.quantile(confidence_level)
    
    return float(var)

def conditional_value_at_risk(
    returns: pd.Series,
    confidence_level: float = 0.05,
    min_periods: int = 10
) -> float:
    """
    Calculate Conditional Value at Risk (CVaR/Expected Shortfall).
    
    Args:
        returns: Returns series
        confidence_level: Confidence level
        min_periods: Minimum periods required
        
    Returns:
        CVaR at specified confidence level
    """
    if len(returns) < min_periods:
        return 0.0
    
    clean_returns = returns.dropna()
    
    if len(clean_returns) < min_periods:
        return 0.0
    
    var = value_at_risk(clean_returns, confidence_level)
    
    # CVaR is mean of returns below VaR
    cvar = clean_returns[clean_returns <= var].mean()
    
    return float(cvar)

def calculate_all_metrics(
    equity: pd.Series,
    returns: Optional[pd.Series] = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4
) -> Dict[str, float]:
    """
    Calculate comprehensive risk metrics.
    
    Args:
        equity: Equity curve (cumulative PnL)
        returns: Returns series (optional, will calculate from equity if not provided)
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year
        
    Returns:
        Dictionary with all risk metrics
    """
    metrics = {}
    
    # Calculate returns if not provided
    if returns is None:
        returns = equity.pct_change().dropna()
    
    # Basic metrics
    metrics["total_return"] = (equity.iloc[-1] / equity.iloc[0]) - 1 if len(equity) > 1 else 0.0
    metrics["max_drawdown"] = max_drawdown(equity)
    
    # Drawdown duration
    dd_duration, dd_start, dd_end = max_drawdown_duration(equity)
    metrics["max_dd_duration"] = dd_duration
    
    # Risk-adjusted ratios
    metrics["sharpe_ratio"] = sharpe_ratio(returns, risk_free_rate, periods_per_year)
    metrics["sortino_ratio"] = sortino_ratio(returns, risk_free_rate, periods_per_year)
    metrics["calmar_ratio"] = calmar_ratio(equity, periods_per_year)
    
    # VaR metrics
    metrics["var_5"] = value_at_risk(returns, 0.05)
    metrics["var_1"] = value_at_risk(returns, 0.01)
    metrics["cvar_5"] = conditional_value_at_risk(returns, 0.05)
    metrics["cvar_1"] = conditional_value_at_risk(returns, 0.01)
    
    # Additional statistics
    metrics["volatility"] = returns.std()
    metrics["downside_volatility"] = returns[returns < 0].std()
    metrics["skewness"] = returns.skew()
    metrics["kurtosis"] = returns.kurtosis()
    
    return metrics

def rolling_metrics(
    returns: pd.Series,
    window: int = 100,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 4
) -> pd.DataFrame:
    """
    Calculate rolling risk metrics.
    
    Args:
        returns: Returns series
        window: Rolling window size
        risk_free_rate: Risk-free rate
        periods_per_year: Periods per year
        
    Returns:
        DataFrame with rolling metrics
    """
    def _rolling_sharpe(window_returns):
        return sharpe_ratio(window_returns, risk_free_rate, periods_per_year, min_periods=10)
    
    def _rolling_sortino(window_returns):
        return sortino_ratio(window_returns, risk_free_rate, periods_per_year, min_periods=10)
    
    def _rolling_var(window_returns):
        return value_at_risk(window_returns, 0.05, min_periods=10)
    
    def _rolling_cvar(window_returns):
        return conditional_value_at_risk(window_returns, 0.05, min_periods=10)
    
    # Calculate rolling metrics
    rolling_df = pd.DataFrame({
        'sharpe_ratio': returns.rolling(window).apply(_rolling_sharpe),
        'sortino_ratio': returns.rolling(window).apply(_rolling_sortino),
        'volatility': returns.rolling(window).std(),
        'var_5': returns.rolling(window).apply(_rolling_var),
        'cvar_5': returns.rolling(window).apply(_rolling_cvar),
        'mean_return': returns.rolling(window).mean(),
        'skewness': returns.rolling(window).skew(),
        'kurtosis': returns.rolling(window).kurt()
    })
    
    return rolling_df

def validate_risk_metrics(equity: pd.Series, returns: Optional[pd.Series] = None) -> Dict[str, any]:
    """
    Validate risk metrics and provide recommendations.
    
    Args:
        equity: Equity curve
        returns: Returns series (optional)
        
    Returns:
        Dictionary with validation results
    """
    if returns is None:
        returns = equity.pct_change().dropna()
    
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "metrics": {}
    }
    
    if len(equity) < 50:
        validation["valid"] = False
        validation["warnings"].append(f"Insufficient data: {len(equity)} periods")
        return validation
    
    # Calculate metrics
    metrics = calculate_all_metrics(equity, returns)
    validation["metrics"] = metrics
    
    # Check Sharpe ratio
    if metrics["sharpe_ratio"] < 0.5:
        validation["warnings"].append(f"Low Sharpe ratio: {metrics['sharpe_ratio']:.2f}")
        validation["recommendations"].append("Consider improving risk-adjusted returns")
    
    # Check max drawdown
    if metrics["max_drawdown"] < -0.20:  # More than 20% drawdown
        validation["warnings"].append(f"High max drawdown: {metrics['max_drawdown']:.2%}")
        validation["recommendations"].append("Consider implementing risk controls")
    
    # Check volatility
    if metrics["volatility"] > 0.05:  # More than 5% per period volatility
        validation["warnings"].append(f"High volatility: {metrics['volatility']:.2%}")
        validation["recommendations"].append("Consider position sizing adjustments")
    
    # Check skewness (negative skew indicates more downside risk)
    if metrics["skewness"] < -0.5:
        validation["warnings"].append(f"Negative skew: {metrics['skewness']:.2f}")
        validation["recommendations"].append("Consider tail risk protection")
    
    return validation

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample returns
np.random.seed(42)
returns = pd.Series(np.random.randn(500) * 0.01, name='returns')

# Create equity curve
equity = (1 + returns).cumprod() * 100000

# Calculate metrics
metrics = calculate_all_metrics(equity, returns)
print("Risk Metrics:")
for key, value in metrics.items():
    print(f"  {key}: {value:.4f}")

# Rolling metrics
rolling = rolling_metrics(returns, window=100)
print(f"\nRolling Sharpe (latest): {rolling['sharpe_ratio'].iloc[-1]:.2f}")

# Validation
validation = validate_risk_metrics(equity, returns)
print(f"\nValidation: {validation['valid']}")
if validation['warnings']:
    for warning in validation['warnings']:
        print(f"  Warning: {warning}")
"""
