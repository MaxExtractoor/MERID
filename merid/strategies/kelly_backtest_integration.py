"""
Kelly Backtest Integration - Full Kelly Backtest with BinanceUS Data

Plug straight into current backtest stack with per-asset Kelly profiles.
"""

import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional
import logging

from .binance_us_data import fetch_btc_eth_15m
from .backtest_15m_meanrev import backtest_meanrev_15m, BacktestResult
from .rolling_kelly_stats import rolling_win_stats
from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

@dataclass
class AssetKellyProfile:
    """Per-asset Kelly profile from backtest results."""
    asset: str
    win_rate: float
    win_loss_ratio: float
    kelly_full: float
    total_trades: int
    avg_pnl: float
    sharpe_ratio: float
    max_drawdown: float

def build_kelly_profile(df: pd.DataFrame, asset: str = "UNKNOWN") -> AssetKellyProfile:
    """
    Build Kelly profile from backtest results.
    
    Args:
        df: OHLCV DataFrame for backtest
        asset: Asset name for the profile
        
    Returns:
        AssetKellyProfile with statistics
    """
    if df.empty:
        logger.warning(f"Empty DataFrame for {asset}")
        return AssetKellyProfile(asset=asset, win_rate=0.0, win_loss_ratio=0.0, kelly_full=0.0,
                               total_trades=0, avg_pnl=0.0, sharpe_ratio=0.0, max_drawdown=0.0)
    
    # Run backtest
    res: BacktestResult = backtest_meanrev_15m(df)
    
    if not res.trades:
        logger.warning(f"No trades generated for {asset}")
        return AssetKellyProfile(asset=asset, win_rate=0.0, win_loss_ratio=0.0, kelly_full=0.0,
                               total_trades=0, avg_pnl=0.0, sharpe_ratio=0.0, max_drawdown=0.0)
    
    # Extract PnLs
    pnls = pd.Series([t.pnl for t in res.trades], name='pnl')
    
    # Calculate rolling statistics
    window = min(100, len(pnls))
    stats_df = rolling_win_stats(pnls, window=window)
    
    if stats_df.dropna().empty:
        logger.warning(f"No valid statistics for {asset}")
        return AssetKellyProfile(asset=asset, win_rate=0.0, win_loss_ratio=0.0, kelly_full=0.0,
                               total_trades=len(res.trades), avg_pnl=res.total_pnl/len(res.trades),
                               sharpe_ratio=res.sharpe_ratio, max_drawdown=res.max_drawdown)
    
    latest = stats_df.dropna().iloc[-1]
    
    # Calculate Kelly statistics
    ks = KellyStats(win_rate=latest["win_rate"], win_loss_ratio=latest["win_loss_ratio"])
    k_full = kelly_fraction(ks)
    
    profile = AssetKellyProfile(
        asset=asset,
        win_rate=ks.win_rate,
        win_loss_ratio=ks.win_loss_ratio,
        kelly_full=k_full,
        total_trades=len(res.trades),
        avg_pnl=res.total_pnl / len(res.trades),
        sharpe_ratio=res.sharpe_ratio,
        max_drawdown=res.max_drawdown
    )
    
    logger.info(f"Kelly profile for {asset}: win_rate={ks.win_rate:.2%}, "
                f"win_loss_ratio={ks.win_loss_ratio:.2f}, kelly_full={k_full:.3f}")
    
    return profile

def build_btc_eth_kelly_profiles(limit: int = 1000) -> Dict[str, AssetKellyProfile]:
    """
    Build Kelly profiles for BTC and ETH from BinanceUS data.
    
    Args:
        limit: Number of 15m bars to fetch
        
    Returns:
        Dictionary with asset -> AssetKellyProfile mapping
    """
    logger.info(f"Building BTC/ETH Kelly profiles (limit={limit})")
    
    try:
        # Fetch data from BinanceUS
        data = fetch_btc_eth_15m(limit=limit)
        
        profiles = {}
        for asset, df in data.items():
            profile = build_kelly_profile(df, asset)
            profiles[asset] = profile
        
        logger.info(f"Built Kelly profiles: {list(profiles.keys())}")
        
        return profiles
        
    except Exception as e:
        logger.error(f"Failed to build Kelly profiles: {e}")
        return {}

def validate_kelly_profiles(profiles: Dict[str, AssetKellyProfile]) -> Dict[str, any]:
    """
    Validate Kelly profiles and provide recommendations.
    
    Args:
        profiles: Dictionary of asset profiles
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "profile_summary": {}
    }
    
    for asset, profile in profiles.items():
        asset_validation = {
            "valid": True,
            "issues": []
        }
        
        # Check win rate
        if profile.win_rate < 0.5:
            asset_validation["issues"].append(f"Low win rate: {profile.win_rate:.2%}")
        
        # Check win/loss ratio
        if profile.win_loss_ratio < 1.0:
            asset_validation["issues"].append(f"Win/loss ratio < 1: {profile.win_loss_ratio:.2f}")
        
        # Check Kelly fraction
        if profile.kelly_full > 0.25:
            asset_validation["issues"].append(f"High Kelly fraction: {profile.kelly_full:.3f}")
        
        # Check trade count
        if profile.total_trades < 50:
            asset_validation["issues"].append(f"Low trade count: {profile.total_trades}")
        
        # Check Sharpe ratio
        if profile.sharpe_ratio < 0.5:
            asset_validation["issues"].append(f"Low Sharpe ratio: {profile.sharpe_ratio:.2f}")
        
        # Check drawdown
        if profile.max_drawdown < -0.15:
            asset_validation["issues"].append(f"High drawdown: {profile.max_drawdown:.2%}")
        
        asset_validation["valid"] = len(asset_validation["issues"]) == 0
        
        if not asset_validation["valid"]:
            validation["warnings"].append(f"{asset}: {', '.join(asset_validation['issues'])}")
        
        # Store summary
        validation["profile_summary"][asset] = {
            "win_rate": profile.win_rate,
            "win_loss_ratio": profile.win_loss_ratio,
            "kelly_full": profile.kelly_full,
            "total_trades": profile.total_trades,
            "sharpe_ratio": profile.sharpe_ratio,
            "max_drawdown": profile.max_drawdown,
            "valid": asset_validation["valid"]
        }
    
    # Overall recommendations
    if validation["warnings"]:
        validation["valid"] = False
        validation["recommendations"].append("Review asset performance before live trading")
        validation["recommendations"].append("Consider using 25-50% Kelly fraction for safety")
    else:
        validation["recommendations"].append("Profiles look good for live trading")
        validation["recommendations"].append("Use conservative Kelly fraction (0.25-0.5)")
    
    return validation

def calculate_safe_kelly_fractions(profiles: Dict[str, AssetKellyProfile], 
                                 safety_factor: float = 0.3) -> Dict[str, float]:
    """
    Calculate safe Kelly fractions with safety factor.
    
    Args:
        profiles: Asset Kelly profiles
        safety_factor: Safety factor to apply (0.25-0.5 typical)
        
    Returns:
        Dictionary of asset -> safe Kelly fraction
    """
    safe_fractions = {}
    
    for asset, profile in profiles.items():
        if profile.kelly_full > 0:
            safe_fraction = profile.kelly_full * safety_factor
            safe_fractions[asset] = min(safe_fraction, 0.25)  # Cap at 25%
        else:
            safe_fractions[asset] = 0.0
    
    return safe_fractions

def export_kelly_profiles(profiles: Dict[str, AssetKellyProfile], filename: str = None) -> str:
    """
    Export Kelly profiles to CSV.
    
    Args:
        profiles: Asset Kelly profiles
        filename: Output filename
        
    Returns:
        Filename of exported file
    """
    from datetime import datetime
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"kelly_profiles_{timestamp}.csv"
    
    # Convert to DataFrame
    data = []
    for asset, profile in profiles.items():
        data.append({
            'asset': asset,
            'win_rate': profile.win_rate,
            'win_loss_ratio': profile.win_loss_ratio,
            'kelly_full': profile.kelly_full,
            'total_trades': profile.total_trades,
            'avg_pnl': profile.avg_pnl,
            'sharpe_ratio': profile.sharpe_ratio,
            'max_drawdown': profile.max_drawdown
        })
    
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    
    logger.info(f"Exported Kelly profiles to {filename}")
    
    return filename

def print_kelly_profiles_summary(profiles: Dict[str, AssetKellyProfile]):
    """
    Print formatted summary of Kelly profiles.
    
    Args:
        profiles: Asset Kelly profiles
    """
    if not profiles:
        print("No Kelly profiles to display")
        return
    
    print("\n" + "="*80)
    print("KELLY PROFILES SUMMARY")
    print("="*80)
    
    print(f"\n{'Asset':<6} {'Win Rate':<10} {'W/L Ratio':<10} {'Kelly':<8} {'Trades':<8} {'Sharpe':<8} {'DD':<8}")
    print("-" * 80)
    
    for asset, profile in profiles.items():
        print(f"{asset:<6} {profile.win_rate:<10.2%} {profile.win_loss_ratio:<10.2f} "
              f"{profile.kelly_full:<8.3f} {profile.total_trades:<8} {profile.sharpe_ratio:<8.2f} "
              f"{profile.max_drawdown:<8.2%}")
    
    # Validation
    validation = validate_kelly_profiles(profiles)
    
    print(f"\nValidation: {'✅ Valid' if validation['valid'] else '⚠️ Issues'}")
    
    if validation['warnings']:
        print("\nWarnings:")
        for warning in validation['warnings']:
            print(f"  - {warning}")
    
    if validation['recommendations']:
        print("\nRecommendations:")
        for rec in validation['recommendations']:
            print(f"  - {rec}")
    
    # Safe Kelly fractions
    safe_fractions = calculate_safe_kelly_fractions(profiles, safety_factor=0.3)
    print(f"\nSafe Kelly Fractions (30% safety factor):")
    for asset, fraction in safe_fractions.items():
        print(f"  {asset}: {fraction:.3f} ({fraction*100:.1f}% of capital)")
    
    print("="*80)

# Example usage:
"""
# Build Kelly profiles
profiles = build_btc_eth_kelly_profiles(limit=1000)

# Print summary
print_kelly_profiles_summary(profiles)

# Validate profiles
validation = validate_kelly_profiles(profiles)
print(f"Validation: {validation}")

# Calculate safe fractions
safe_fractions = calculate_safe_kelly_fractions(profiles, safety_factor=0.3)
print(f"Safe Kelly fractions: {safe_fractions}")

# Export profiles
filename = export_kelly_profiles(profiles)
print(f"Exported to: {filename}")
"""
