"""
Rolling Kelly Statistics - Dynamic Win Rate and Win/Loss Ratio

Given a trades DataFrame with PnL column, compute rolling stats for Kelly sizing.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)

def rolling_win_stats(
    trade_pnls: pd.Series,
    window: int = 100,
    min_trades: int = 10
) -> pd.DataFrame:
    """
    Calculate rolling win rate and win/loss ratio for Kelly sizing.
    
    Args:
        trade_pnls: Series indexed by trade number or time, values = PnL per trade
        window: Rolling window size (number of trades)
        min_trades: Minimum trades required for valid statistics
        
    Returns:
        DataFrame with rolling win_rate and win_loss_ratio
    """
    df = trade_pnls.to_frame("pnl")
    
    def _win_rate(window_pnls) -> float:
        """Calculate win rate for a window."""
        wins = (window_pnls > 0).sum()
        total = window_pnls.count()
        return wins / total if total >= min_trades else 0.0

    def _win_loss_ratio(window_pnls) -> float:
        """Calculate win/loss ratio for a window."""
        wins = window_pnls[window_pnls > 0]
        losses = window_pnls[window_pnls < 0]
        
        if len(wins) == 0 or len(losses) == 0:
            return 0.0
        
        avg_win = wins.mean()
        avg_loss = -losses.mean()
        
        return avg_win / avg_loss if avg_loss > 0 else 0.0

    # Calculate rolling statistics
    df["win_rate"] = df["pnl"].rolling(window, min_periods=min_trades).apply(_win_rate, raw=False)
    df["win_loss_ratio"] = df["pnl"].rolling(window, min_periods=min_trades).apply(_win_loss_ratio, raw=False)
    
    # Add additional helpful columns
    df["total_trades"] = df["pnl"].rolling(window, min_periods=1).count()
    df["winning_trades"] = df["pnl"].rolling(window, min_periods=1).apply(lambda x: (x > 0).sum(), raw=False)
    df["losing_trades"] = df["pnl"].rolling(window, min_periods=1).apply(lambda x: (x <= 0).sum(), raw=False)
    df["avg_pnl"] = df["pnl"].rolling(window, min_periods=1).mean()
    df["std_pnl"] = df["pnl"].rolling(window, min_periods=2).std()
    
    return df[["win_rate", "win_loss_ratio", "total_trades", "winning_trades", 
              "losing_trades", "avg_pnl", "std_pnl"]]

def rolling_kelly_fraction(
    trade_pnls: pd.Series,
    window: int = 100,
    min_trades: int = 10,
    safety_factor: float = 0.5
) -> pd.Series:
    """
    Calculate rolling Kelly fraction with safety factor.
    
    Args:
        trade_pnls: Series of trade PnLs
        window: Rolling window size
        min_trades: Minimum trades for valid stats
        safety_factor: Safety factor to apply to Kelly (0.5 = 50% Kelly)
        
    Returns:
        Series of rolling Kelly fractions
    """
    stats = rolling_win_stats(trade_pnls, window, min_trades)
    
    def _kelly_fraction(row) -> float:
        """Calculate Kelly fraction from win stats."""
        W = row["win_rate"]
        R = row["win_loss_ratio"]
        
        if R <= 0 or W <= 0 or row["total_trades"] < min_trades:
            return 0.0
        
        # Kelly formula: f* = W - (1-W)/R
        f_star = W - (1 - W) / R
        
        # Apply safety factor and bounds
        f_safe = f_star * safety_factor
        return max(0.0, min(f_safe, 1.0))
    
    kelly_fracs = stats.apply(_kelly_fraction, axis=1)
    
    return kelly_fracs

def adaptive_kelly_sizing(
    trade_pnls: pd.Series,
    capital_usd: float,
    contract_notional_usd: float = 1.0,
    window: int = 100,
    min_trades: int = 10,
    base_kelly_fraction: float = 0.5,
    min_kelly_fraction: float = 0.1,
    max_kelly_fraction: float = 0.5,
    confidence_threshold: float = 0.6
) -> pd.DataFrame:
    """
    Calculate adaptive Kelly position sizing based on recent performance.
    
    Args:
        trade_pnls: Series of trade PnLs
        capital_usd: Total capital available
        contract_notional_usd: Notional value per contract
        window: Rolling window for statistics
        min_trades: Minimum trades for valid stats
        base_kelly_fraction: Base Kelly fraction to use
        min_kelly_fraction: Minimum Kelly fraction (floor)
        max_kelly_fraction: Maximum Kelly fraction (ceiling)
        confidence_threshold: Minimum win rate to use full Kelly
        
    Returns:
        DataFrame with sizing recommendations
    """
    stats = rolling_win_stats(trade_pnls, window, min_trades)
    
    def _adaptive_kelly(row) -> Tuple[float, float, str]:
        """Calculate adaptive Kelly fraction and reasoning."""
        W = row["win_rate"]
        R = row["win_loss_ratio"]
        trades = row["total_trades"]
        
        if trades < min_trades or R <= 0 or W <= 0:
            return 0.0, 0.0, "insufficient_data"
        
        # Calculate raw Kelly
        f_star = W - (1 - W) / R
        
        # Adjust based on confidence
        if W < confidence_threshold:
            # Reduce Kelly fraction when win rate is low
            adjusted_fraction = base_kelly_fraction * (W / confidence_threshold)
            reason = "low_confidence"
        else:
            # Use full base Kelly fraction when confident
            adjusted_fraction = base_kelly_fraction
            reason = "confident"
        
        # Apply bounds
        f_safe = max(min_kelly_fraction, min(max_kelly_fraction, f_star * adjusted_fraction))
        
        # Calculate position size
        risk_usd = capital_usd * f_safe
        contracts = int(risk_usd / contract_notional_usd) if risk_usd > 0 else 0
        
        return f_safe, contracts, reason
    
    # Apply adaptive sizing
    results = stats.apply(lambda row: _adaptive_kelly(row), axis=1, result_type='expand')
    results.columns = ["kelly_fraction", "position_size", "reasoning"]
    
    # Add original stats
    result_df = pd.concat([stats, results], axis=1)
    
    return result_df

def validate_kelly_statistics(trade_pnls: pd.Series, window: int = 100) -> Dict[str, any]:
    """
    Validate Kelly statistics and provide recommendations.
    
    Args:
        trade_pnls: Series of trade PnLs
        window: Window size for rolling statistics
        
    Returns:
        Dictionary with validation results
    """
    if len(trade_pnls) < window:
        return {
            "valid": False,
            "reason": "insufficient_trades",
            "message": f"Need at least {window} trades, have {len(trade_pnls)}"
        }
    
    # Calculate recent statistics
    recent_pnls = trade_pnls.tail(window)
    wins = (recent_pnls > 0).sum()
    losses = (recent_pnls <= 0).sum()
    win_rate = wins / len(recent_pnls)
    
    win_values = recent_pnls[recent_pnls > 0]
    loss_values = recent_pnls[recent_pnls <= 0]
    
    avg_win = win_values.mean() if len(win_values) > 0 else 0.0
    avg_loss = -loss_values.mean() if len(loss_values) > 0 else 1.0  # Avoid division by zero
    
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Validation checks
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "stats": {
            "total_trades": len(recent_pnls),
            "win_rate": win_rate,
            "win_loss_ratio": win_loss_ratio,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "kelly_fraction": max(0.0, win_rate - (1 - win_rate) / win_loss_ratio) if win_loss_ratio > 0 else 0.0
        }
    }
    
    # Check win rate
    if win_rate < 0.5:
        validation["warnings"].append(f"Low win rate: {win_rate:.2%}")
        validation["recommendations"].append("Consider improving signal quality")
    
    # Check win/loss ratio
    if win_loss_ratio < 1.0:
        validation["warnings"].append(f"Win/loss ratio < 1: {win_loss_ratio:.2f}")
        validation["recommendations"].append("Average wins should exceed average losses")
    
    # Check sample size
    if len(recent_pnls) < 50:
        validation["warnings"].append(f"Small sample size: {len(recent_pnls)} trades")
        validation["recommendations"].append("Use larger sample for more reliable statistics")
    
    # Check Kelly fraction
    kelly_frac = validation["stats"]["kelly_fraction"]
    if kelly_frac > 0.25:
        validation["warnings"].append(f"High Kelly fraction: {kelly_frac:.3f}")
        validation["recommendations"].append("Consider using safety factor (0.25-0.5 Kelly)")
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def export_kelly_analysis(trade_pnls: pd.Series, window: int = 100, filename: str = None) -> str:
    """
    Export Kelly analysis to CSV.
    
    Args:
        trade_pnls: Series of trade PnLs
        window: Window size for analysis
        filename: Output filename
        
    Returns:
        Filename of exported file
    """
    from datetime import datetime
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"kelly_analysis_{timestamp}.csv"
    
    # Calculate analysis
    analysis_df = adaptive_kelly_sizing(trade_pnls, capital_usd=100000, window=window)
    
    # Export to CSV
    analysis_df.to_csv(filename)
    
    logger.info(f"Exported Kelly analysis to {filename}")
    
    return filename

# Example usage:
"""
import numpy as np
import pandas as pd

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = pd.Series(
    np.random.choice([100, -50, 75, -25, 150, -75], size=200),
    name='pnl'
)

# Calculate rolling statistics
rolling_stats = rolling_win_stats(trade_pnls, window=50)
print("Rolling Stats (last 5 rows):")
print(rolling_stats.tail())

# Calculate rolling Kelly fractions
kelly_fracs = rolling_kelly_fraction(trade_pnls, window=50)
print(f"\nLatest Kelly fraction: {kelly_fracs.iloc[-1]:.3f}")

# Adaptive sizing
adaptive_sizing = adaptive_kelly_sizing(trade_pnls, capital_usd=100000)
print(f"\nAdaptive Sizing (last 5 rows):")
print(adaptive_sizing[['kelly_fraction', 'position_size', 'reasoning']].tail())

# Validate statistics
validation = validate_kelly_statistics(trade_pnls, window=50)
print(f"\nValidation: {validation}")

# Export analysis
filename = export_kelly_analysis(trade_pnls, window=50)
print(f"\nExported analysis to: {filename}")
"""
