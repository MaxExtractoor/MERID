"""
ATR-Based Volatility Sizing - Layered on Kelly Position Sizing

ATR-based sizing: position_size = risk_dollars / (ATR * ATR_multiplier)
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ATR calculation period (default 14)
        
    Returns:
        Series with ATR values
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    # True Range is the maximum of:
    # 1. High - Low
    # 2. |High - Previous Close|
    # 3. |Low - Previous Close|
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    return atr

def atr_kelly_position_size(
    capital_usd: float,
    kelly_fraction: float,
    atr_value: float,
    atr_multiplier: float,
    price_usd: float,
    contract_notional_usd: float = 1.0,
    min_contracts: int = 1,
    max_contracts: Optional[int] = None
) -> int:
    """
    Combine Kelly fraction with ATR-based sizing.
    
    Risk per trade = capital * kelly_fraction.
    Stop distance ~ ATR * atr_multiplier.
    Contracts ~ risk / (ATR * multiplier).
    
    Args:
        capital_usd: Total capital available
        kelly_fraction: Kelly fraction (0-1)
        atr_value: Current ATR value
        atr_multiplier: Multiplier for ATR (stop distance)
        price_usd: Current price of the asset
        contract_notional_usd: Notional value per contract
        min_contracts: Minimum number of contracts
        max_contracts: Maximum number of contracts (optional)
        
    Returns:
        Number of contracts to trade
    """
    # Validate inputs
    if capital_usd <= 0 or kelly_fraction <= 0 or atr_value <= 0 or price_usd <= 0:
        logger.warning("Invalid inputs for ATR Kelly sizing")
        return 0
    
    # Calculate risk amount in USD
    risk_usd = capital_usd * kelly_fraction
    
    # Calculate risk per unit (ATR * multiplier)
    # For derivatives, this approximates the stop distance in price terms
    per_unit_risk = atr_value * atr_multiplier
    
    # Calculate position size
    units = risk_usd / per_unit_risk
    
    # Convert to contracts
    contracts = int(units / contract_notional_usd)
    
    # Apply bounds
    contracts = max(contracts, min_contracts)
    if max_contracts is not None:
        contracts = min(contracts, max_contracts)
    
    logger.debug(f"ATR Kelly sizing: risk=${risk_usd:.2f}, ATR={atr_value:.2f}, "
                f"multiplier={atr_multiplier}, units={units:.1f}, contracts={contracts}")
    
    return contracts

def adaptive_atr_multiplier(
    atr_values: pd.Series,
    price_values: pd.Series,
    window: int = 20,
    base_multiplier: float = 2.0,
    min_multiplier: float = 1.0,
    max_multiplier: float = 4.0
) -> pd.Series:
    """
    Calculate adaptive ATR multiplier based on recent volatility.
    
    Args:
        atr_values: Series of ATR values
        price_values: Series of price values
        window: Window for volatility calculation
        base_multiplier: Base ATR multiplier
        min_multiplier: Minimum multiplier (for low volatility)
        max_multiplier: Maximum multiplier (for high volatility)
        
    Returns:
        Series of adaptive ATR multipliers
    """
    # Calculate ATR as percentage of price (volatility measure)
    atr_pct = (atr_values / price_values) * 100
    
    # Calculate rolling average and standard deviation
    atr_pct_mean = atr_pct.rolling(window).mean()
    atr_pct_std = atr_pct.rolling(window).std()
    
    # Calculate z-score of current volatility
    volatility_z = (atr_pct - atr_pct_mean) / atr_pct_std
    
    # Adaptive multiplier: higher multiplier for high volatility, lower for low
    adaptive_multiplier = base_multiplier + (volatility_z * 0.5)
    
    # Apply bounds
    adaptive_multiplier = adaptive_multiplier.clip(min_multiplier, max_multiplier)
    
    return adaptive_multiplier.fillna(base_multiplier)

def volatility_adjusted_kelly(
    trade_pnls: pd.Series,
    price_data: pd.DataFrame,
    capital_usd: float,
    window: int = 100,
    atr_period: int = 14,
    base_kelly_fraction: float = 0.3,
    atr_multiplier: float = 2.0,
    adaptive_atr: bool = True
) -> pd.DataFrame:
    """
    Calculate volatility-adjusted Kelly position sizing.
    
    Args:
        trade_pnls: Series of trade PnLs
        price_data: DataFrame with OHLC data
        capital_usd: Total capital
        window: Window for rolling Kelly statistics
        atr_period: ATR calculation period
        base_kelly_fraction: Base Kelly fraction
        atr_multiplier: Base ATR multiplier
        adaptive_atr: Whether to use adaptive ATR multiplier
        
    Returns:
        DataFrame with sizing recommendations
    """
    from .rolling_kelly_stats import adaptive_kelly_sizing
    
    # Calculate Kelly statistics
    kelly_stats = adaptive_kelly_sizing(
        trade_pnls, capital_usd, window=window
    )
    
    # Calculate ATR
    atr = compute_atr(price_data, period=atr_period)
    
    # Get current price
    current_prices = price_data['close']
    
    # Align data
    # Use forward fill to handle different frequencies
    kelly_stats_aligned = kelly_stats.reindex(atr.index, method='ffill')
    prices_aligned = current_prices.reindex(atr.index, method='ffill')
    
    # Calculate adaptive ATR multiplier if requested
    if adaptive_atr:
        adaptive_mult = adaptive_atr_multiplier(atr, prices_aligned)
        final_multiplier = adaptive_mult
    else:
        final_multiplier = pd.Series(atr_multiplier, index=atr.index)
    
    # Calculate ATR-adjusted position sizes
    position_sizes = []
    kelly_fractions = []
    atr_values_used = []
    multipliers_used = []
    
    for idx in atr.index:
        if idx not in kelly_stats_aligned.index or idx not in prices_aligned.index:
            position_sizes.append(0)
            kelly_fractions.append(0.0)
            atr_values_used.append(0.0)
            multipliers_used.append(0.0)
            continue
        
        kelly_frac = kelly_stats_aligned.loc[idx, 'kelly_fraction']
        atr_val = atr.loc[idx]
        price = prices_aligned.loc[idx]
        mult = final_multiplier.loc[idx]
        
        # Calculate position size
        contracts = atr_kelly_position_size(
            capital_usd=capital_usd,
            kelly_fraction=kelly_frac,
            atr_value=atr_val,
            atr_multiplier=mult,
            price_usd=price
        )
        
        position_sizes.append(contracts)
        kelly_fractions.append(kelly_frac)
        atr_values_used.append(atr_val)
        multipliers_used.append(mult)
    
    # Create result DataFrame
    result_df = pd.DataFrame({
        'kelly_fraction': kelly_fractions,
        'atr_value': atr_values_used,
        'atr_multiplier': multipliers_used,
        'position_size': position_sizes,
        'current_price': prices_aligned.reindex(atr.index, method='ffill')
    }, index=atr.index)
    
    return result_df

def validate_atr_sizing(
    price_data: pd.DataFrame,
    atr_period: int = 14,
    min_periods: int = 20
) -> dict:
    """
    Validate ATR calculation and provide recommendations.
    
    Args:
        price_data: DataFrame with OHLC data
        atr_period: ATR calculation period
        min_periods: Minimum periods for validation
        
    Returns:
        Dictionary with validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "stats": {}
    }
    
    if len(price_data) < min_periods:
        validation["valid"] = False
        validation["warnings"].append(f"Insufficient data: {len(price_data)} < {min_periods}")
        return validation
    
    # Calculate ATR
    atr = compute_atr(price_data, period=atr_period)
    
    # Basic statistics
    atr_stats = {
        "current_atr": atr.iloc[-1],
        "avg_atr": atr.mean(),
        "atr_std": atr.std(),
        "atr_min": atr.min(),
        "atr_max": atr.max(),
        "atr_pct_of_price": (atr.iloc[-1] / price_data['close'].iloc[-1]) * 100
    }
    
    validation["stats"] = atr_stats
    
    # Check ATR stability
    atr_cv = atr.std() / atr.mean()  # Coefficient of variation
    if atr_cv > 0.5:
        validation["warnings"].append(f"High ATR volatility: CV = {atr_cv:.2f}")
        validation["recommendations"].append("Consider longer ATR period for stability")
    
    # Check ATR magnitude
    atr_pct = atr_stats["atr_pct_of_price"]
    if atr_pct > 5.0:  # ATR > 5% of price
        validation["warnings"].append(f"High ATR relative to price: {atr_pct:.2f}%")
        validation["recommendations"].append("Consider reducing position size or using wider stops")
    elif atr_pct < 0.5:  # ATR < 0.5% of price
        validation["warnings"].append(f"Low ATR relative to price: {atr_pct:.2f}%")
        validation["recommendations"].append("Consider tighter stops for better risk/reward")
    
    # Check for price gaps
    price_changes = price_data['close'].pct_change().abs()
    large_gaps = (price_changes > atr_pct / 100).sum()  # Gaps larger than ATR
    if large_gaps > len(price_data) * 0.1:  # More than 10% gaps
        validation["warnings"].append(f"Many price gaps: {large_gaps} > ATR")
        validation["recommendations"].append("Be cautious with stop placement during volatile periods")
    
    return validation

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample OHLC data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=100, freq='15min')
base_price = 50000
price_changes = np.random.randn(100) * 100
prices = base_price + np.cumsum(price_changes)

df = pd.DataFrame({
    'open': prices,
    'high': prices * (1 + np.abs(np.random.randn(100) * 0.001)),
    'low': prices * (1 - np.abs(np.random.randn(100) * 0.001)),
    'close': prices,
    'volume': np.random.randint(1000, 10000, 100)
}, index=dates)

# Calculate ATR
atr = compute_atr(df, period=14)
print(f"Current ATR: {atr.iloc[-1]:.2f}")

# ATR Kelly sizing
contracts = atr_kelly_position_size(
    capital_usd=100000,
    kelly_fraction=0.3,
    atr_value=atr.iloc[-1],
    atr_multiplier=2.0,
    price_usd=df['close'].iloc[-1]
)
print(f"Position size: {contracts} contracts")

# Validate ATR
validation = validate_atr_sizing(df)
print(f"ATR validation: {validation}")
"""
