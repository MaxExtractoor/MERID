"""
Backtest Kelly-VIX on Kalshi Yes/No Markets

Full backtest script for Kelly-VIX hybrid sizing on Kalshi markets.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional
import logging

from .vix_data import fetch_vix_with_fallback, calculate_vix_rank
from .kelly_vix_hybrid import hybrid_kelly_fraction
from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Individual trade data structure."""
    entry_idx: int
    exit_idx: int
    entry_price: float  # in dollars (cents/100)
    exit_price: float   # in dollars (cents/100)
    pnl_pct: float      # return per trade (normalized)
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    kelly_fraction: float
    hybrid_fraction: float

@dataclass
class KellyVIXResult:
    """Kelly-VIX backtest results."""
    trades: List[Trade]
    equity_curve: pd.Series
    kelly_fraction: float
    hybrid_fraction: float
    base_kelly_fraction: float
    win_rate: float
    win_loss_ratio: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float

def backtest_kelly_vix_on_market(
    prices: pd.Series,           # yes_price series in cents
    signals: pd.Series,          # +1 long, 0 flat, -1 short
    vix_series: pd.Series,
    base_kelly_fraction: float = 0.15,
    vix_lookback: int = 252,
    commission_bps: float = 2.0,
    slippage_bps: float = 5.0
) -> KellyVIXResult:
    """
    Backtest Kelly-VIX hybrid strategy on Kalshi market.
    
    Args:
        prices: Yes price series in cents
        signals: Trading signals (+1, 0, -1)
        vix_series: VIX price series
        base_kelly_fraction: Base Kelly fraction before VIX scaling
        vix_lookback: Lookback period for VIX rank calculation
        commission_bps: Commission in basis points
        slippage_bps: Slippage in basis points
        
    Returns:
        KellyVIXResult with backtest outcomes
    """
    if prices.empty or signals.empty or vix_series.empty:
        raise ValueError("Empty price, signals, or VIX data")
    
    # Convert prices from cents to dollars
    closes = prices.astype(float) / 100.0
    
    # Align signals with prices
    signals_aligned = signals.reindex(closes.index, method='ffill').fillna(0).astype(int)
    
    # Align VIX with prices
    vix_aligned = vix_series.reindex(closes.index, method='ffill').dropna()
    
    if vix_aligned.empty:
        raise ValueError("No overlapping VIX data with price series")
    
    logger.info(f"Backtesting Kelly-VIX: {len(closes)} periods, base_kelly={base_kelly_fraction:.3f}")
    
    # Generate trades
    trades = []
    in_pos = False
    entry_idx = entry_price = entry_time = None
    
    for i in range(1, len(closes)):
        current_time = closes.index[i]
        current_signal = signals_aligned.iloc[i]
        prev_signal = signals_aligned.iloc[i-1]
        
        # Entry logic: signal flips from 0 -> non-zero
        if not in_pos and prev_signal == 0 and current_signal != 0:
            in_pos = True
            entry_idx = i
            entry_price = closes.iloc[i]
            entry_time = current_time
            
        # Exit logic: signal flips from non-zero -> 0
        elif in_pos and prev_signal != 0 and current_signal == 0:
            exit_idx = i
            exit_price = closes.iloc[i]
            exit_time = current_time
            
            # Calculate PnL with costs
            gross_pnl = (exit_price - entry_price) / entry_price  # Long-only example
            
            # Apply costs (slippage and commission)
            cost_impact = (commission_bps + slippage_bps) / 10000  # Convert bps to decimal
            net_pnl = gross_pnl - cost_impact
            
            trade = Trade(
                entry_idx=entry_idx,
                exit_idx=exit_idx,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=net_pnl,
                entry_time=entry_time,
                exit_time=exit_time,
                kelly_fraction=0.0,  # Will be calculated later
                hybrid_fraction=0.0   # Will be calculated later
            )
            trades.append(trade)
            in_pos = False
    
    if not trades:
        logger.warning("No trades generated in backtest")
        return KellyVIXResult([], pd.Series(dtype=float), 0.0, 0.0, base_kelly_fraction, 0.0, 0.0, 0.0, 0.0, 0.0)
    
    # Calculate Kelly statistics from trades
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Calculate full Kelly fraction
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_full = kelly_fraction(ks)
    
    # Calculate VIX-aligned hybrid fractions for each trade
    hybrid_fractions = []
    
    for i, trade in enumerate(trades):
        # Get VIX data available at trade entry
        vix_at_entry = vix_aligned.loc[trade.entry_time] if trade.entry_time in vix_aligned.index else vix_aligned.iloc[trade.entry_idx]
        
        # Calculate VIX rank using available data up to trade entry
        vix_window = vix_aligned.loc[:trade.entry_time]
        if len(vix_window) >= vix_lookback:
            vix_rank = calculate_vix_rank(vix_window, vix_lookback)
        else:
            vix_rank = calculate_vix_rank(vix_window, len(vix_window))
        
        # Calculate hybrid fraction
        f_hybrid = hybrid_kelly_fraction(f_full, vix_window, lookback=min(vix_lookback, len(vix_window)))
        
        trade.kelly_fraction = f_full
        trade.hybrid_fraction = f_hybrid
        hybrid_fractions.append(f_hybrid)
    
    # Generate equity curve with hybrid Kelly sizing
    capital = 1.0
    equity_values = []
    
    for i, (trade, f_hybrid) in enumerate(zip(trades, hybrid_fractions)):
        capital *= (1 + f_hybrid * trade.pnl_pct)
        equity_values.append(capital)
    
    equity_curve = pd.Series(equity_values, index=range(len(equity_values)))
    
    # Calculate performance metrics
    if len(equity_curve) > 1:
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
        
        # Sharpe ratio (annualized, assuming 15m bars)
        returns = equity_curve.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            periods_per_year = 365 * 24 * 4  # 15m bars
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        else:
            sharpe_ratio = 0.0
        
        # Max drawdown
        peak = equity_curve.cummax()
        drawdown = (equity_curve - peak) / peak.replace(0, np.nan)
        max_drawdown = drawdown.min()
    else:
        total_return = 0.0
        sharpe_ratio = 0.0
        max_drawdown = 0.0
    
    result = KellyVIXResult(
        trades=trades,
        equity_curve=equity_curve,
        kelly_fraction=f_full,
        hybrid_fraction=np.mean(hybrid_fractions),
        base_kelly_fraction=base_kelly_fraction,
        win_rate=win_rate,
        win_loss_ratio=win_loss_ratio,
        total_return=total_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown
    )
    
    logger.info(f"Kelly-VIX backtest completed: {len(trades)} trades, "
                f"return={total_return:.2%}, sharpe={sharpe_ratio:.2f}, "
                f"dd={max_drawdown:.2%}")
    
    return result

def backtest_fixed_kelly_on_market(
    prices: pd.Series,
    signals: pd.Series,
    kelly_fraction: float = 0.15,
    commission_bps: float = 2.0,
    slippage_bps: float = 5.0
) -> KellyVIXResult:
    """
    Backtest fixed Kelly strategy for comparison.
    
    Args:
        prices: Yes price series in cents
        signals: Trading signals
        kelly_fraction: Fixed Kelly fraction to use
        commission_bps: Commission in basis points
        slippage_bps: Slippage in basis points
        
    Returns:
        KellyVIXResult with fixed Kelly outcomes
    """
    # Use VIX series as dummy (not used in fixed Kelly)
    dummy_vix = pd.Series([20.0] * len(prices), index=prices.index)
    
    result = backtest_kelly_vix_on_market(
        prices, signals, dummy_vix, 
        base_kelly_fraction=kelly_fraction,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps
    )
    
    # Update hybrid fraction to match Kelly fraction for comparison
    result.hybrid_fraction = kelly_fraction
    
    return result

def compare_kelly_vix_strategies(
    prices: pd.Series,
    signals: pd.Series,
    vix_series: pd.Series,
    base_kelly_fraction: float = 0.15,
    fixed_fractions: List[float] = None
) -> Dict[str, KellyVIXResult]:
    """
    Compare Kelly-VIX hybrid vs fixed Kelly strategies.
    
    Args:
        prices: Yes price series in cents
        signals: Trading signals
        vix_series: VIX price series
        base_kelly_fraction: Base Kelly fraction
        fixed_fractions: List of fixed Kelly fractions to compare
        
    Returns:
        Dictionary with results for each strategy
    """
    if fixed_fractions is None:
        fixed_fractions = [0.25, 0.5, 0.75, 1.0]  # Fractions of base Kelly
    
    results = {}
    
    # Kelly-VIX hybrid strategy
    try:
        hybrid_result = backtest_kelly_vix_on_market(
            prices, signals, vix_series, base_kelly_fraction
        )
        results["kelly_vix_hybrid"] = hybrid_result
    except Exception as e:
        logger.error(f"Kelly-VIX hybrid backtest failed: {e}")
    
    # Fixed Kelly strategies
    for frac in fixed_fractions:
        try:
            fixed_kelly = base_kelly_fraction * frac
            fixed_result = backtest_fixed_kelly_on_market(
                prices, signals, fixed_kelly
            )
            results[f"fixed_kelly_{frac:.1f}"] = fixed_result
        except Exception as e:
            logger.error(f"Fixed Kelly {frac:.1f} backtest failed: {e}")
    
    return results

def print_kelly_vix_results(results: Dict[str, KellyVIXResult], title: str = "Kelly-VIX Backtest Results"):
    """
    Print formatted Kelly-VIX backtest results.
    
    Args:
        results: Dictionary of backtest results
        title: Results title
    """
    if not results:
        print("No results to display")
        return
    
    print(f"\n{title}")
    print("=" * 80)
    
    print(f"\nStrategy Performance Summary:")
    print("-" * 80)
    print(f"{'Strategy':<20} {'Trades':<8} {'Return':<10} {'Sharpe':<8} {'Max DD':<10} {'Kelly':<8}")
    print("-" * 80)
    
    for strategy_name, result in results.items():
        print(f"{strategy_name:<20} {len(result.trades):<8} "
              f"{result.total_return:<10.2%} {result.sharpe_ratio:<8.2f} "
              f"{result.max_drawdown:<10.2%} {result.kelly_fraction:<8.3f}")
    
    # Find best performers
    if len(results) > 1:
        best_sharpe = max(results.items(), key=lambda x: x[1].sharpe_ratio)
        best_return = max(results.items(), key=lambda x: x[1].total_return)
        lowest_dd = min(results.items(), key=lambda x: x[1].max_drawdown)
        
        print(f"\nBest Performers:")
        print("-" * 50)
        print(f"  Highest Sharpe: {best_sharpe[0]} ({best_sharpe[1].sharpe_ratio:.2f})")
        print(f"  Highest Return: {best_return[0]} ({best_return[1].total_return:.2%})")
        print(f"  Lowest Drawdown: {lowest_dd[0]} ({lowest_dd[1].max_drawdown:.2%})")
    
    # Trade analysis
    hybrid_result = results.get("kelly_vix_hybrid")
    if hybrid_result:
        print(f"\nKelly-VIX Hybrid Analysis:")
        print("-" * 50)
        print(f"  Base Kelly: {hybrid_result.base_kelly_fraction:.3f}")
        print(f"  Full Kelly: {hybrid_result.kelly_fraction:.3f}")
        print(f"  Avg Hybrid: {hybrid_result.hybrid_fraction:.3f}")
        print(f"  Win Rate: {hybrid_result.win_rate:.1%}")
        print(f"  Win/Loss Ratio: {hybrid_result.win_loss_ratio:.2f}")
        print(f"  Total Trades: {len(hybrid_result.trades)}")
        
        # Trade duration analysis
        if hybrid_result.trades:
            durations = [(t.exit_idx - t.entry_idx) for t in hybrid_result.trades]
            print(f"  Avg Trade Duration: {np.mean(durations):.1f} periods")
            print(f"  Max Trade Duration: {max(durations)} periods")
    
    print("=" * 80)

def generate_kelly_vix_recommendations(results: Dict[str, KellyVIXResult]) -> List[str]:
    """
    Generate recommendations based on Kelly-VIX backtest results.
    
    Args:
        results: Dictionary of backtest results
        
    Returns:
        List of recommendations
    """
    if not results:
        return ["No backtest results available for recommendations"]
    
    recommendations = []
    
    hybrid_result = results.get("kelly_vix_hybrid")
    fixed_results = {k: v for k, v in results.items() if k.startswith("fixed_kelly")}
    
    # Compare hybrid vs fixed Kelly
    if hybrid_result and fixed_results:
        best_fixed = max(fixed_results.items(), key=lambda x: x[1].sharpe_ratio)
        
        sharpe_diff = hybrid_result.sharpe_ratio - best_fixed[1].sharpe_ratio
        return_diff = hybrid_result.total_return - best_fixed[1].total_return
        dd_diff = hybrid_result.max_drawdown - best_fixed[1].max_drawdown
        
        if sharpe_diff > 0.1:
            recommendations.append(f"✅ Kelly-VIX hybrid significantly outperforms fixed Kelly (+{sharpe_diff:.2f} Sharpe)")
        elif sharpe_diff > 0.05:
            recommendations.append(f"📈 Kelly-VIX hybrid modestly outperforms fixed Kelly (+{sharpe_diff:.2f} Sharpe)")
        elif sharpe_diff > 0:
            recommendations.append(f"📊 Kelly-VIX hybrid slightly outperforms fixed Kelly (+{sharpe_diff:.2f} Sharpe)")
        else:
            recommendations.append(f"⚠️ Fixed Kelly outperforms Kelly-VIX hybrid ({sharpe_diff:.2f} Sharpe)")
        
        if return_diff > 0.05:
            recommendations.append(f"🚈 Kelly-VIX hybrid improves returns (+{return_diff:.1%})")
        elif return_diff < -0.05:
            recommendations.append(f"📉 Kelly-VIX hybrid reduces returns ({return_diff:.1%})")
        
        if dd_diff < 0.02:  # Less negative is better
            recommendations.append(f"🛡️ Kelly-VIX hybrid reduces drawdowns ({dd_diff:.1%})")
    
    # Risk assessment
    if hybrid_result:
        if hybrid_result.max_drawdown < -0.30:
            recommendations.append(f"📉 High drawdown risk ({hybrid_result.max_drawdown:.1%}) - consider reducing Kelly fraction")
        elif hybrid_result.max_drawdown < -0.15:
            recommendations.append(f"📊 Moderate drawdown risk ({hybrid_result.max_drawdown:.1%}) - monitor carefully")
        else:
            recommendations.append(f"✅ Low drawdown risk ({hybrid_result.max_drawdown:.1%}) - current sizing appears safe")
        
        if hybrid_result.sharpe_ratio > 1.5:
            recommendations.append(f"🚀 Excellent risk-adjusted returns (Sharpe: {hybrid_result.sharpe_ratio:.2f})")
        elif hybrid_result.sharpe_ratio > 1.0:
            recommendations.append(f"📈 Good risk-adjusted returns (Sharpe: {hybrid_result.sharpe_ratio:.2f})")
        elif hybrid_result.sharpe_ratio > 0.5:
            recommendations.append(f"📊 Moderate risk-adjusted returns (Sharpe: {hybrid_result.sharpe_ratio:.2f})")
        else:
            recommendations.append(f"⚠️ Low risk-adjusted returns (Sharpe: {hybrid_result.sharpe_ratio:.2f}) - improve strategy")
    
    # Trade quality assessment
    if hybrid_result and hybrid_result.trades:
        if hybrid_result.win_rate > 0.6:
            recommendations.append(f"✅ High win rate ({hybrid_result.win_rate:.1%}) - strategy quality good")
        elif hybrid_result.win_rate > 0.5:
            recommendations.append(f"📊 Moderate win rate ({hybrid_result.win_rate:.1%}) - acceptable performance")
        else:
            recommendations.append(f"⚠️ Low win rate ({hybrid_result.win_rate:.1%}) - improve signal quality")
        
        if hybrid_result.win_loss_ratio > 1.5:
            recommendations.append(f"✅ Strong win/loss ratio ({hybrid_result.win_loss_ratio:.2f}) - good risk management")
        elif hybrid_result.win_loss_ratio > 1.0:
            recommendations.append(f"📊 Positive win/loss ratio ({hybrid_result.win_loss_ratio:.2f}) - acceptable")
        else:
            recommendations.append(f"⚠️ Poor win/loss ratio ({hybrid_result.win_loss_ratio:.2f}) - improve exit strategy")
    
    # General recommendations
    recommendations.append("💡 Consider combining Kelly-VIX with other risk controls like drawdown limits")
    recommendations.append("🔄 Re-run backtest periodically with updated market data")
    recommendations.append("⚖️ Monitor VIX regime changes and adjust parameters accordingly")
    recommendations.append("📊 Use fractional Kelly (25-50%) for better risk management in live trading")
    
    return recommendations

# Example usage:
"""
# Fetch Kalshi market data
from merid.strategies.kalshi_market_data import get_crypto_markets, fetch_market_history

# Get BTC markets
btc_markets = get_crypto_markets("BTC", status="open")

if not btc_markets.empty:
    # Get price history for a specific market
    market_ticker = btc_markets.iloc[0]["ticker"]
    price_history = fetch_market_history(market_ticker, limit=1000)
    
    if not price_history.empty and 'yes_price' in price_history.columns:
        # Generate sample signals (replace with actual strategy signals)
        import numpy as np
        np.random.seed(42)
        signals = pd.Series(np.random.choice([0, 1, -1], size=len(price_history)), 
                          index=price_history.index)
        
        # Get VIX data
        from merid.strategies.vix_data import fetch_vix_with_fallback
        vix_data = fetch_vix_with_fallback()
        
        # Align VIX with price data
        vix_aligned = vix_data.reindex(price_history.index, method='ffill').dropna()
        
        if not vix_aligned.empty:
            # Run backtest
            results = compare_kelly_vix_strategies(
                price_history['yes_price'], signals, vix_aligned
            )
            
            # Print results
            print_kelly_vix_results(results)
            
            # Generate recommendations
            recommendations = generate_kelly_vix_recommendations(results)
            print("Recommendations:")
            for rec in recommendations:
                print(f"  {rec}")
"""
