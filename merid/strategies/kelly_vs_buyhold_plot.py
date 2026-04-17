"""
Kelly vs Buy-Hold Visualization - Strategy Performance Comparison

Plot equity curve from Kelly strategy vs simple buy-and-hold BTC/ETH.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Optional, Tuple
import logging

from .binance_us_data import fetch_klines
from .backtest_15m_meanrev import backtest_meanrev_15m
from .kelly_backtest_integration import build_kelly_profile

logger = logging.getLogger(__name__)

def compute_buy_hold_equity(df: pd.DataFrame, notional: float = 1.0) -> pd.Series:
    """
    Compute buy-and-hold equity curve.
    
    Args:
        df: OHLCV DataFrame
        notional: Starting notional amount
        
    Returns:
        Equity curve for buy-and-hold strategy
    """
    if df.empty:
        return pd.Series()
    
    prices = df["close"].astype(float)
    returns = prices.pct_change().fillna(0.0)
    equity = (1 + returns).cumprod() * notional
    
    return equity

def compute_kelly_equity(df: pd.DataFrame, notional: float = 1.0) -> pd.Series:
    """
    Compute Kelly strategy equity curve.
    
    Args:
        df: OHLCV DataFrame
        notional: Starting notional amount
        
    Returns:
        Equity curve for Kelly strategy
    """
    if df.empty:
        return pd.Series()
    
    # Run backtest
    res = backtest_meanrev_15m(df)
    
    # Get strategy equity (starting from 0 PnL, normalize to notional)
    strat_eq = res.equity_curve.copy()
    
    if strat_eq.empty:
        return pd.Series()
    
    # Normalize to start at notional
    strat_eq_norm = strat_eq - strat_eq.iloc[0] + notional
    
    return strat_eq_norm

def calculate_performance_metrics(equity: pd.Series) -> dict:
    """
    Calculate performance metrics for equity curve.
    
    Args:
        equity: Equity curve
        
    Returns:
        Dictionary with performance metrics
    """
    if equity.empty:
        return {}
    
    # Basic returns
    returns = equity.pct_change().dropna()
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Risk metrics
    volatility = returns.std()
    sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4) if returns.std() > 0 else 0.0
    
    # Drawdown
    peak = equity.cummax()
    drawdown = (equity - peak) / peak.replace(0, np.nan)
    max_drawdown = drawdown.min()
    
    # Win rate (for positive periods)
    win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0.0
    
    return {
        "total_return": total_return,
        "volatility": volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "start_value": equity.iloc[0],
        "end_value": equity.iloc[-1],
        "periods": len(equity)
    }

def plot_kelly_vs_buyhold(df: pd.DataFrame, title: str = "Kelly vs Buy-Hold", 
                         notional: float = 1.0, figsize: Tuple[int, int] = (12, 8),
                         save_path: Optional[str] = None) -> None:
    """
    Plot Kelly strategy vs buy-and-hold equity curves.
    
    Args:
        df: OHLCV DataFrame
        title: Plot title
        notional: Starting notional amount
        figsize: Figure size
        save_path: Path to save plot (optional)
    """
    if df.empty:
        logger.warning("Empty DataFrame for plotting")
        return
    
    # Calculate equity curves
    kelly_eq = compute_kelly_equity(df, notional)
    buy_hold_eq = compute_buy_hold_equity(df, notional)
    
    if kelly_eq.empty or buy_hold_eq.empty:
        logger.warning("Failed to calculate equity curves")
        return
    
    # Calculate performance metrics
    kelly_metrics = calculate_performance_metrics(kelly_eq)
    buy_hold_metrics = calculate_performance_metrics(buy_hold_eq)
    
    # Create plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, gridspec_kw={'height_ratios': [3, 1]})
    
    # Main equity plot
    ax1.plot(kelly_eq.index, kelly_eq.values, label="Kelly Strategy", linewidth=2, color='blue')
    ax1.plot(buy_hold_eq.index, buy_hold_eq.values, label="Buy & Hold", linewidth=2, color='orange', alpha=0.8)
    
    # Formatting
    ax1.set_title(title, fontsize=14, fontweight='bold')
    ax1.set_ylabel("Equity ($)", fontsize=12)
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # Format x-axis
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
    
    # Add performance metrics text box
    metrics_text = (
        f"Kelly Strategy:\n"
        f"  Return: {kelly_metrics.get('total_return', 0):.1%}\n"
        f"  Sharpe: {kelly_metrics.get('sharpe_ratio', 0):.2f}\n"
        f"  Max DD: {kelly_metrics.get('max_drawdown', 0):.1%}\n"
        f"  Win Rate: {kelly_metrics.get('win_rate', 0):.1%}\n\n"
        f"Buy & Hold:\n"
        f"  Return: {buy_hold_metrics.get('total_return', 0):.1%}\n"
        f"  Sharpe: {buy_hold_metrics.get('sharpe_ratio', 0):.2f}\n"
        f"  Max DD: {buy_hold_metrics.get('max_drawdown', 0):.1%}\n"
        f"  Win Rate: {buy_hold_metrics.get('win_rate', 0):.1%}"
    )
    
    ax1.text(0.02, 0.98, metrics_text, transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # Drawdown plot
    kelly_peak = kelly_eq.cummax()
    kelly_dd = (kelly_eq - kelly_peak) / kelly_peak.replace(0, np.nan)
    
    buy_hold_peak = buy_hold_eq.cummax()
    buy_hold_dd = (buy_hold_eq - buy_hold_peak) / buy_hold_peak.replace(0, np.nan)
    
    ax2.fill_between(kelly_dd.index, kelly_dd.values, 0, alpha=0.3, color='blue', label='Kelly DD')
    ax2.fill_between(buy_hold_dd.index, buy_hold_dd.values, 0, alpha=0.3, color='orange', label='Buy & Hold DD')
    
    ax2.set_ylabel("Drawdown", fontsize=10)
    ax2.set_xlabel("Date", fontsize=12)
    ax2.legend(loc='lower right')
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    
    # Format x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    
    plt.tight_layout()
    
    # Save plot if requested
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"Plot saved to {save_path}")
    
    plt.show()

def plot_multiple_assets_comparison(data: Dict[str, pd.DataFrame], 
                                 title: str = "Multi-Asset Kelly vs Buy-Hold Comparison",
                                 notional: float = 1.0,
                                 figsize: Tuple[int, int] = (15, 10),
                                 save_path: Optional[str] = None) -> None:
    """
    Plot Kelly vs buy-hold comparison for multiple assets.
    
    Args:
        data: Dictionary of asset -> DataFrame
        title: Plot title
        notional: Starting notional amount
        figsize: Figure size
        save_path: Path to save plot (optional)
    """
    if not data:
        logger.warning("No data provided for multi-asset comparison")
        return
    
    fig, axes = plt.subplots(len(data), 1, figsize=figsize)
    if len(data) == 1:
        axes = [axes]
    
    for i, (asset, df) in enumerate(data.items()):
        if df.empty:
            continue
        
        ax = axes[i]
        
        # Calculate equity curves
        kelly_eq = compute_kelly_equity(df, notional)
        buy_hold_eq = compute_buy_hold_equity(df, notional)
        
        if kelly_eq.empty or buy_hold_eq.empty:
            continue
        
        # Plot curves
        ax.plot(kelly_eq.index, kelly_eq.values, label="Kelly Strategy", linewidth=2, color='blue')
        ax.plot(buy_hold_eq.index, buy_hold_eq.values, label="Buy & Hold", linewidth=2, color='orange', alpha=0.8)
        
        # Formatting
        ax.set_title(f"{asset} - Kelly vs Buy-Hold", fontsize=12, fontweight='bold')
        ax.set_ylabel("Equity ($)", fontsize=10)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # Add performance summary
        kelly_metrics = calculate_performance_metrics(kelly_eq)
        buy_hold_metrics = calculate_performance_metrics(buy_hold_eq)
        
        summary_text = (
            f"Kelly: {kelly_metrics.get('total_return', 0):.1%} | "
            f"Sharpe: {kelly_metrics.get('sharpe_ratio', 0):.2f} | "
            f"DD: {kelly_metrics.get('max_drawdown', 0):.1%}\n"
            f"Buy-Hold: {buy_hold_metrics.get('total_return', 0):.1%} | "
            f"Sharpe: {buy_hold_metrics.get('sharpe_ratio', 0):.2f} | "
            f"DD: {buy_hold_metrics.get('max_drawdown', 0):.1%}"
        )
        
        ax.text(0.02, 0.98, summary_text, transform=ax.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # Overall title
    fig.suptitle(title, fontsize=14, fontweight='bold')
    
    # Set x-label for last subplot
    axes[-1].set_xlabel("Date", fontsize=12)
    
    plt.tight_layout()
    
    # Save plot if requested
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"Multi-asset plot saved to {save_path}")
    
    plt.show()

def create_performance_comparison_table(data: Dict[str, pd.DataFrame], 
                                     notional: float = 1.0) -> pd.DataFrame:
    """
    Create a comparison table of performance metrics.
    
    Args:
        data: Dictionary of asset -> DataFrame
        notional: Starting notional amount
        
    Returns:
        DataFrame with performance comparison
    """
    results = []
    
    for asset, df in data.items():
        if df.empty:
            continue
        
        # Calculate equity curves
        kelly_eq = compute_kelly_equity(df, notional)
        buy_hold_eq = compute_buy_hold_equity(df, notional)
        
        if kelly_eq.empty or buy_hold_eq.empty:
            continue
        
        # Calculate metrics
        kelly_metrics = calculate_performance_metrics(kelly_eq)
        buy_hold_metrics = calculate_performance_metrics(buy_hold_eq)
        
        # Calculate outperformance
        kelly_outperformance = kelly_metrics.get('total_return', 0) - buy_hold_metrics.get('total_return', 0)
        sharpe_outperformance = kelly_metrics.get('sharpe_ratio', 0) - buy_hold_metrics.get('sharpe_ratio', 0)
        
        results.append({
            'Asset': asset,
            'Kelly_Return': kelly_metrics.get('total_return', 0),
            'BuyHold_Return': buy_hold_metrics.get('total_return', 0),
            'Return_Outperformance': kelly_outperformance,
            'Kelly_Sharpe': kelly_metrics.get('sharpe_ratio', 0),
            'BuyHold_Sharpe': buy_hold_metrics.get('sharpe_ratio', 0),
            'Sharpe_Outperformance': sharpe_outperformance,
            'Kelly_MaxDD': kelly_metrics.get('max_drawdown', 0),
            'BuyHold_MaxDD': buy_hold_metrics.get('max_drawdown', 0),
            'Kelly_WinRate': kelly_metrics.get('win_rate', 0),
            'BuyHold_WinRate': buy_hold_metrics.get('win_rate', 0)
        })
    
    return pd.DataFrame(results)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=1000, freq='15min')
base_price = 50000
price_changes = np.random.randn(1000) * 100
prices = base_price + np.cumsum(price_changes)

df_btc = pd.DataFrame({
    'open': prices,
    'high': prices * (1 + np.abs(np.random.randn(1000) * 0.001)),
    'low': prices * (1 - np.abs(np.random.randn(1000) * 0.001)),
    'close': prices,
    'volume': np.random.randint(1000, 10000, 1000)
}, index=dates)

# Single asset plot
plot_kelly_vs_buyhold(df_btc, title="BTC 15m: Kelly Mean-Reversion vs Buy-Hold")

# Multiple assets comparison
data = {
    "BTC": df_btc,
    "ETH": df_btc.copy()  # Use same data for demo
}

plot_multiple_assets_comparison(data, title="Multi-Asset Kelly vs Buy-Hold Comparison")

# Performance table
comparison_table = create_performance_comparison_table(data)
print(comparison_table)
"""
