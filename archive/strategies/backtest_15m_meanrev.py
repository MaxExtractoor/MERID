"""
Backtest 15m Mean Reversion with Hurst + Z-Score

Simplified single-asset backtest skeleton with Hurst filter and Z-score signals.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
import logging
from typing import List, Optional

from .hurst import hurst_exponent, is_mean_reverting

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Trade record for backtest."""
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    pnl: float
    entry_z: float
    exit_z: float
    holding_bars: int
    hurst_at_entry: float

@dataclass
class BacktestResult:
    """Backtest results summary."""
    trades: List[Trade]
    equity_curve: pd.Series
    max_drawdown: float
    win_rate: float
    avg_win: float
    avg_loss: float
    total_pnl: float
    sharpe_ratio: float
    avg_holding_bars: float
    hurst_stats: dict

def backtest_meanrev_15m(
    df: pd.DataFrame,
    z_window: int = 48,
    z_entry: float = 1.0,
    z_exit: float = 0.1,
    hurst_window: int = 200,
    hurst_max: float = 0.5,
    max_bars_in_trade: int = 16,
    contract_size: int = 1,
    enable_hurst_filter: bool = True
) -> BacktestResult:
    """
    Backtest 15-minute mean reversion strategy with Hurst filter.
    
    Entry logic:
    - Enter long when Z < -z_entry and H < hurst_max (if filter enabled)
    - Exit when Z > -z_exit or max holding bars reached
    
    Args:
        df: DataFrame with OHLCV data
        z_window: Window for Z-score calculation (48 bars = 12 hours)
        z_entry: Z-score threshold for entry (negative for short)
        z_exit: Z-score threshold for exit (closer to zero)
        hurst_window: Window for Hurst calculation
        hurst_max: Maximum Hurst exponent for mean reversion
        max_bars_in_trade: Maximum holding period (16 bars = 4 hours)
        contract_size: Number of contracts per trade
        enable_hurst_filter: Whether to apply Hurst filter
        
    Returns:
        BacktestResult with performance metrics
    """
    logger.info(f"Starting backtest: z_entry={z_entry}, z_exit={z_exit}, "
                f"hurst_max={hurst_max}, max_bars={max_bars_in_trade}")
    
    # Prepare data
    closes = df["close"].astype(float).reset_index(drop=True)
    rets = closes.pct_change().fillna(0.0)
    
    # Calculate Z-scores
    z_mean = rets.rolling(z_window).mean()
    z_std = rets.rolling(z_window).std()
    zscores = (rets - z_mean) / z_std
    zscores = zscores.fillna(0.0)
    
    # Initialize tracking
    equity = 0.0
    equity_curve = []
    in_trade = False
    entry_idx = None
    entry_price = None
    entry_z = None
    trades: List[Trade] = []
    hurst_values = []
    
    # Start from max window to ensure enough data
    start_idx = max(z_window, hurst_window) + 1
    
    for i in range(start_idx, len(closes)):
        price = closes.iloc[i]
        z = zscores.iloc[i]
        
        # Calculate Hurst for this window
        window_prices = closes.iloc[i - hurst_window : i].values
        H = hurst_exponent(window_prices, min_lag=10, max_lag=50)
        hurst_values.append(H)
        
        # Check if we should trade (Hurst filter)
        mean_reverting = True
        if enable_hurst_filter:
            mean_reverting = H < hurst_max
        
        if not in_trade:
            # Entry logic: price significantly below mean in mean-reverting regime
            if mean_reverting and z < -z_entry:
                in_trade = True
                entry_idx = i
                entry_price = price
                entry_z = z
                
                logger.debug(f"Entry at idx {i}: price={price:.2f}, z={z:.2f}, H={H:.3f}")
                
        else:
            holding_bars = i - entry_idx
            
            # Exit logic: Z has reverted towards zero or max holding time
            if z > -z_exit or holding_bars >= max_bars_in_trade:
                pnl = (price - entry_price) * contract_size
                holding_time = holding_bars
                
                trade = Trade(
                    entry_idx=entry_idx,
                    exit_idx=i,
                    entry_price=entry_price,
                    exit_price=price,
                    pnl=pnl,
                    entry_z=entry_z,
                    exit_z=z,
                    holding_bars=holding_time,
                    hurst_at_entry=H
                )
                
                trades.append(trade)
                equity += pnl
                in_trade = False
                entry_idx = None
                entry_price = None
                entry_z = None
                
                logger.debug(f"Exit at idx {i}: pnl={pnl:.2f}, holding={holding_bars} bars")
        
        equity_curve.append(equity)
    
    # Create equity curve series
    ec_series = pd.Series(equity_curve, index=df.index[-len(equity_curve):])
    
    # Calculate performance metrics
    if trades:
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        win_rate = len(wins) / len(pnls)
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(-np.mean(losses)) if losses else 0.0
        total_pnl = sum(pnls)
        avg_holding_bars = np.mean([t.holding_bars for t in trades])
        
        # Calculate Sharpe ratio (annualized)
        if len(ec_series) > 1:
            returns = ec_series.pct_change().dropna()
            if len(returns) > 1 and returns.std() > 0:
                sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4)  # Annualized for 15m
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0
    else:
        win_rate = avg_win = avg_loss = total_pnl = avg_holding_bars = sharpe_ratio = 0.0
    
    # Calculate max drawdown
    running_max = ec_series.cummax()
    drawdowns = ec_series - running_max
    max_dd = float(drawdowns.min()) if not drawdowns.empty else 0.0
    
    # Hurst statistics
    hurst_stats = {
        'mean': np.mean(hurst_values) if hurst_values else 0.5,
        'std': np.std(hurst_values) if hurst_values else 0.0,
        'min': np.min(hurst_values) if hurst_values else 0.5,
        'max': np.max(hurst_values) if hurst_values else 0.5
    }
    
    result = BacktestResult(
        trades=trades,
        equity_curve=ec_series,
        max_drawdown=max_dd,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        total_pnl=total_pnl,
        sharpe_ratio=sharpe_ratio,
        avg_holding_bars=avg_holding_bars,
        hurst_stats=hurst_stats
    )
    
    logger.info(f"Backtest completed: {len(trades)} trades, "
                f"total_pnl=${total_pnl:.2f}, win_rate={win_rate:.2f}, "
                f"max_dd={max_dd:.2%}, sharpe={sharpe_ratio:.2f}")
    
    return result

def apply_drawdown_stop(equity_curve: pd.Series, dd_limit: float) -> pd.Series:
    """
    Apply maximum drawdown stop to equity curve.
    
    Args:
        equity_curve: Equity curve series
        dd_limit: Maximum drawdown limit (negative, e.g., -0.1 for -10%)
        
    Returns:
        Truncated equity curve where trading stops at drawdown breach
    """
    if equity_curve.empty:
        return equity_curve
    
    peak = equity_curve.iloc[0]
    
    for i, eq in enumerate(equity_curve):
        if eq > peak:
            peak = eq
        
        dd = (eq - peak) / peak if peak != 0 else 0
        
        if dd < dd_limit:
            logger.warning(f"Drawdown limit breached: {dd:.2%} < {dd_limit:.2%}")
            return equity_curve.iloc[:i+1]
    
    return equity_curve

def calculate_performance_metrics(result: BacktestResult) -> dict:
    """
    Calculate detailed performance metrics from backtest result.
    
    Args:
        result: BacktestResult object
        
    Returns:
        Dictionary with detailed metrics
    """
    if not result.trades:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_trade_pnl': 0.0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
            'consecutive_wins': 0,
            'consecutive_losses': 0
        }
    
    pnls = [t.pnl for t in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    # Basic metrics
    total_trades = len(pnls)
    win_rate = len(wins) / total_trades
    profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
    avg_trade_pnl = np.mean(pnls)
    
    # Best/worst trades
    best_trade = max(pnls)
    worst_trade = min(pnls)
    
    # Consecutive wins/losses
    consecutive_wins = 0
    consecutive_losses = 0
    current_streak = 0
    max_wins = 0
    max_losses = 0
    
    for pnl in pnls:
        if pnl > 0:
            if current_streak >= 0:
                current_streak += 1
                max_wins = max(max_wins, current_streak)
            else:
                current_streak = 1
                max_losses = max(max_losses, -current_streak)
        else:
            if current_streak <= 0:
                current_streak -= 1
                max_losses = max(max_losses, -current_streak)
            else:
                current_streak = -1
                max_wins = max(max_wins, current_streak)
    
    consecutive_wins = max_wins
    consecutive_losses = max_losses
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_trade_pnl': avg_trade_pnl,
        'best_trade': best_trade,
        'worst_trade': worst_trade,
        'consecutive_wins': consecutive_wins,
        'consecutive_losses': consecutive_losses
    }

def print_backtest_summary(result: BacktestResult, detailed: bool = False):
    """
    Print a formatted summary of backtest results.
    
    Args:
        result: BacktestResult object
        detailed: Whether to print detailed metrics
    """
    print("\n" + "="*60)
    print("BACKTEST SUMMARY")
    print("="*60)
    
    print(f"Total Trades: {len(result.trades)}")
    print(f"Total PnL: ${result.total_pnl:.2f}")
    print(f"Win Rate: {result.win_rate:.2%}")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"Avg Holding Bars: {result.avg_holding_bars:.1f}")
    
    if detailed:
        print(f"\nDetailed Metrics:")
        print(f"Avg Win: ${result.avg_win:.2f}")
        print(f"Avg Loss: ${result.avg_loss:.2f}")
        
        if result.trades:
            pnls = [t.pnl for t in result.trades]
            print(f"Best Trade: ${max(pnls):.2f}")
            print(f"Worst Trade: ${min(pnls):.2f}")
        
        print(f"\nHurst Statistics:")
        print(f"Mean H: {result.hurst_stats['mean']:.3f}")
        print(f"Std H: {result.hurst_stats['std']:.3f}")
        print(f"Min H: {result.hurst_stats['min']:.3f}")
        print(f"Max H: {result.hurst_stats['max']:.3f}")
        
        # Performance metrics
        metrics = calculate_performance_metrics(result)
        print(f"\nAdvanced Metrics:")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"Avg Trade PnL: ${metrics['avg_trade_pnl']:.2f}")
        print(f"Consecutive Wins: {metrics['consecutive_wins']}")
        print(f"Consecutive Losses: {metrics['consecutive_losses']}")
    
    print("="*60)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample 15m data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=1000, freq='15min')
prices = 50000 + np.cumsum(np.random.randn(1000) * 100)

df = pd.DataFrame({
    'timestamp': dates,
    'open': prices,
    'high': prices * (1 + np.abs(np.random.randn(1000) * 0.001)),
    'low': prices * (1 - np.abs(np.random.randn(1000) * 0.001)),
    'close': prices,
    'volume': np.random.randint(1000, 10000, 1000)
})

# Run backtest
result = backtest_meanrev_15m(
    df,
    z_entry=1.0,
    z_exit=0.1,
    hurst_max=0.5,
    max_bars_in_trade=16,
    enable_hurst_filter=True
)

# Print summary
print_backtest_summary(result, detailed=True)

# Apply drawdown stop
stopped_equity = apply_drawdown_stop(result.equity_curve, dd_limit=-0.1)
print(f"\nEquity after drawdown stop: ${stopped_equity.iloc[-1]:.2f}")
"""
