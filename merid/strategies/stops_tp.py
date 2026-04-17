"""
Stops and Take Profit - Fixed Stop Loss and Take Profit in Kelly Strategy

Implement fixed stop/TP in backtest loop with PnL feeding into Kelly sizing.
"""

import pandas as pd
import numpy as np
import logging
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class TradeResult:
    """Result of a trade with stops/TP."""
    entry_price: float
    exit_price: float
    exit_reason: str  # "stop_loss", "take_profit", "signal_exit", "max_bars"
    bars_held: int
    pnl: float
    entry_bar: int
    exit_bar: int

def compute_trade_pnl_with_stops(
    entry_price: float,
    bar_lows: List[float],
    bar_highs: List[float],
    bar_closes: List[float],
    stop_loss_pct: float,
    take_profit_pct: float,
    max_bars: Optional[int] = None
) -> TradeResult:
    """
    Long-only example with stops and take profit.
    
    Args:
        entry_price: Entry price
        bar_lows: Subsequent bar lows after entry
        bar_highs: Subsequent bar highs after entry
        bar_closes: Subsequent bar closes after entry
        stop_loss_pct: Stop loss as fraction (0.01 = 1%)
        take_profit_pct: Take profit as fraction (0.01 = 1%)
        max_bars: Maximum bars to hold (optional)
        
    Returns:
        TradeResult with exit details
    """
    if not bar_lows or len(bar_lows) != len(bar_highs) or len(bar_lows) != len(bar_closes):
        raise ValueError("Bar data lists must be same length and non-empty")
    
    # Calculate stop and take profit levels
    stop_level = entry_price * (1 - stop_loss_pct)
    tp_level = entry_price * (1 + take_profit_pct)
    
    # Default exit at last bar
    exit_price = bar_closes[-1]
    exit_reason = "max_bars"
    bars_held = len(bar_lows)
    exit_bar = bars_held - 1
    
    # Check each bar for stop/TP hit
    for i, (low, high, close) in enumerate(zip(bar_lows, bar_highs, bar_closes)):
        # Check stop loss hit
        if low <= stop_level:
            exit_price = stop_level
            exit_reason = "stop_loss"
            bars_held = i + 1
            exit_bar = i
            break
        
        # Check take profit hit
        if high >= tp_level:
            exit_price = tp_level
            exit_reason = "take_profit"
            bars_held = i + 1
            exit_bar = i
            break
    
    # Check max bars limit
    if max_bars is not None and bars_held >= max_bars:
        exit_price = bar_closes[max_bars - 1]
        exit_reason = "max_bars"
        bars_held = max_bars
        exit_bar = max_bars - 1
    
    # Calculate PnL
    pnl = exit_price - entry_price
    
    return TradeResult(
        entry_price=entry_price,
        exit_price=exit_price,
        exit_reason=exit_reason,
        bars_held=bars_held,
        pnl=pnl,
        entry_bar=0,
        exit_bar=exit_bar
    )

def apply_stops_to_backtest(
    df: pd.DataFrame,
    signals: List[Dict],
    stop_loss_pct: float = 0.02,  # 2%
    take_profit_pct: float = 0.04,  # 4%
    max_bars: int = 16,
    z_exit_threshold: float = 0.1
) -> List[TradeResult]:
    """
    Apply stops and take profit to backtest signals.
    
    Args:
        df: OHLCV DataFrame
        signals: List of signal dictionaries with entry info
        stop_loss_pct: Stop loss percentage
        take_profit_pct: Take profit percentage
        max_bars: Maximum bars to hold
        z_exit_threshold: Z-score threshold for signal exit
        
    Returns:
        List of TradeResult objects
    """
    trades = []
    
    for signal in signals:
        if signal.get('side') == 'flat':
            continue
        
        entry_bar = signal.get('entry_bar', 0)
        entry_price = signal.get('entry_price', df['close'].iloc[entry_bar])
        
        # Get subsequent bars data
        if entry_bar >= len(df) - 1:
            continue  # Not enough data
        
        subsequent_bars = min(max_bars, len(df) - entry_bar - 1)
        bar_lows = df['low'].iloc[entry_bar + 1 : entry_bar + 1 + subsequent_bars].tolist()
        bar_highs = df['high'].iloc[entry_bar + 1 : entry_bar + 1 + subsequent_bars].tolist()
        bar_closes = df['close'].iloc[entry_bar + 1 : entry_bar + 1 + subsequent_bars].tolist()
        
        # Check for Z-score exit (signal-based)
        z_exit_hit = False
        if 'z_scores' in signal and len(signal['z_scores']) > entry_bar:
            for i, z_score in enumerate(signal['z_scores'][entry_bar + 1 : entry_bar + 1 + subsequent_bars]):
                if signal['side'] == 'long_up' and z_score > -z_exit_threshold:
                    # Exit at this bar
                    exit_price = bar_closes[i]
                    trades.append(TradeResult(
                        entry_price=entry_price,
                        exit_price=exit_price,
                        exit_reason="signal_exit",
                        bars_held=i + 1,
                        pnl=exit_price - entry_price,
                        entry_bar=entry_bar,
                        exit_bar=entry_bar + i + 1
                    ))
                    z_exit_hit = True
                    break
                elif signal['side'] == 'long_down' and z_score < z_exit_threshold:
                    # Exit at this bar
                    exit_price = bar_closes[i]
                    trades.append(TradeResult(
                        entry_price=entry_price,
                        exit_price=exit_price,
                        exit_reason="signal_exit",
                        bars_held=i + 1,
                        pnl=exit_price - entry_price,
                        entry_bar=entry_bar,
                        exit_bar=entry_bar + i + 1
                    ))
                    z_exit_hit = True
                    break
        
        if not z_exit_hit:
            # Use stops/TP
            trade_result = compute_trade_pnl_with_stops(
                entry_price, bar_lows, bar_highs, bar_closes,
                stop_loss_pct, take_profit_pct, max_bars
            )
            trade_result.entry_bar = entry_bar
            trade_result.exit_bar = entry_bar + trade_result.bars_held
            trades.append(trade_result)
    
    return trades

def analyze_stop_performance(trades: List[TradeResult]) -> Dict[str, any]:
    """
    Analyze performance of stops and take profit.
    
    Args:
        trades: List of TradeResult objects
        
    Returns:
        Performance analysis dictionary
    """
    if not trades:
        return {"error": "No trades to analyze"}
    
    # Basic statistics
    total_trades = len(trades)
    profitable_trades = len([t for t in trades if t.pnl > 0])
    losing_trades = len([t for t in trades if t.pnl <= 0])
    
    # Exit reason statistics
    exit_reasons = {}
    for trade in trades:
        reason = trade.exit_reason
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    
    # Performance by exit reason
    performance_by_reason = {}
    for reason in exit_reasons.keys():
        reason_trades = [t for t in trades if t.exit_reason == reason]
        if reason_trades:
            avg_pnl = np.mean([t.pnl for t in reason_trades])
            win_rate = len([t for t in reason_trades if t.pnl > 0]) / len(reason_trades)
            avg_bars = np.mean([t.bars_held for t in reason_trades])
            
            performance_by_reason[reason] = {
                "count": len(reason_trades),
                "avg_pnl": avg_pnl,
                "win_rate": win_rate,
                "avg_bars_held": avg_bars
            }
    
    # Overall performance
    total_pnl = sum(t.pnl for t in trades)
    avg_pnl = total_pnl / total_trades
    win_rate = profitable_trades / total_trades
    avg_bars_held = np.mean([t.bars_held for t in trades])
    
    # Stop loss effectiveness
    stop_loss_trades = [t for t in trades if t.exit_reason == "stop_loss"]
    stop_loss_rate = len(stop_loss_trades) / total_trades
    stop_loss_avg_pnl = np.mean([t.pnl for t in stop_loss_trades]) if stop_loss_trades else 0.0
    
    # Take profit effectiveness
    tp_trades = [t for t in trades if t.exit_reason == "take_profit"]
    tp_rate = len(tp_trades) / total_trades
    tp_avg_pnl = np.mean([t.pnl for t in tp_trades]) if tp_trades else 0.0
    
    return {
        "total_trades": total_trades,
        "profitable_trades": profitable_trades,
        "losing_trades": losing_trades,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "win_rate": win_rate,
        "avg_bars_held": avg_bars_held,
        "exit_reasons": exit_reasons,
        "performance_by_reason": performance_by_reason,
        "stop_loss_rate": stop_loss_rate,
        "stop_loss_avg_pnl": stop_loss_avg_pnl,
        "take_profit_rate": tp_rate,
        "take_profit_avg_pnl": tp_avg_pnl
    }

def optimize_stop_parameters(
    df: pd.DataFrame,
    signals: List[Dict],
    stop_loss_range: List[float] = None,
    take_profit_range: List[float] = None,
    max_bars_range: List[int] = None
) -> Dict[str, any]:
    """
    Optimize stop loss and take profit parameters.
    
    Args:
        df: OHLCV DataFrame
        signals: List of signal dictionaries
        stop_loss_range: Range of stop loss percentages to test
        take_profit_range: Range of take profit percentages to test
        max_bars_range: Range of max bars to test
        
    Returns:
        Optimization results
    """
    if stop_loss_range is None:
        stop_loss_range = [0.01, 0.015, 0.02, 0.025, 0.03]
    
    if take_profit_range is None:
        take_profit_range = [0.02, 0.03, 0.04, 0.05, 0.06]
    
    if max_bars_range is None:
        max_bars_range = [8, 12, 16, 20, 24]
    
    results = []
    
    for sl in stop_loss_range:
        for tp in take_profit_range:
            for max_bars in max_bars_range:
                try:
                    trades = apply_stops_to_backtest(
                        df, signals, sl, tp, max_bars
                    )
                    
                    if trades:
                        analysis = analyze_stop_performance(trades)
                        
                        # Calculate score (risk-adjusted return)
                        score = analysis["total_pnl"] / abs(analysis.get("max_drawdown", 0.01)) if analysis.get("max_drawdown", 0.01) != 0 else analysis["total_pnl"]
                        
                        results.append({
                            "stop_loss_pct": sl,
                            "take_profit_pct": tp,
                            "max_bars": max_bars,
                            "total_trades": analysis["total_trades"],
                            "total_pnl": analysis["total_pnl"],
                            "win_rate": analysis["win_rate"],
                            "score": score,
                            "stop_loss_rate": analysis["stop_loss_rate"],
                            "take_profit_rate": analysis["take_profit_rate"],
                            "avg_bars_held": analysis["avg_bars_held"]
                        })
                
                except Exception as e:
                    logger.error(f"Error in optimization for sl={sl}, tp={tp}, max_bars={max_bars}: {e}")
                    continue
    
    # Sort by score
    results.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "best_parameters": results[0] if results else None,
        "all_results": results,
        "optimization_summary": {
            "stop_loss_range": stop_loss_range,
            "take_profit_range": take_profit_range,
            "max_bars_range": max_bars_range,
            "total_combinations": len(results)
        }
    }

def validate_stop_parameters(stop_loss_pct: float, take_profit_pct: float, max_bars: int) -> Dict[str, any]:
    """
    Validate stop parameters and provide recommendations.
    
    Args:
        stop_loss_pct: Stop loss percentage
        take_profit_pct: Take profit percentage
        max_bars: Maximum bars to hold
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Validate ranges
    if not (0.005 <= stop_loss_pct <= 0.10):  # 0.5% to 10%
        validation["warnings"].append(f"Stop loss outside typical range: {stop_loss_pct:.1%}")
        validation["recommendations"].append("Consider 1-3% stop loss for crypto")
    
    if not (0.01 <= take_profit_pct <= 0.15):  # 1% to 15%
        validation["warnings"].append(f"Take profit outside typical range: {take_profit_pct:.1%}")
        validation["recommendations"].append("Consider 2-6% take profit for crypto")
    
    if not (4 <= max_bars <= 48):  # 1 hour to 12 hours (15m bars)
        validation["warnings"].append(f"Max bars outside typical range: {max_bars}")
        validation["recommendations"].append("Consider 8-24 bars for 15m crypto")
    
    # Validate risk/reward ratio
    risk_reward_ratio = take_profit_pct / stop_loss_pct
    if risk_reward_ratio < 1.0:
        validation["warnings"].append(f"Risk/reward ratio < 1: {risk_reward_ratio:.2f}")
        validation["recommendations"].append("Take profit should be at least equal to stop loss")
    elif risk_reward_ratio > 5.0:
        validation["warnings"].append(f"Very high risk/reward ratio: {risk_reward_ratio:.2f}")
        validation["recommendations"].append("Consider more realistic risk/reward ratio")
    
    # Overall assessment
    if validation["warnings"]:
        validation["valid"] = False
    else:
        validation["recommendations"].append("Parameters look reasonable")
    
    return validation

def print_stop_analysis(trades: List[TradeResult]):
    """
    Print formatted analysis of stop performance.
    
    Args:
        trades: List of TradeResult objects
    """
    if not trades:
        print("No trades to analyze")
        return
    
    analysis = analyze_stop_performance(trades)
    
    print("\n" + "="*60)
    print("STOP/TAKE PROFIT ANALYSIS")
    print("="*60)
    
    print(f"\nOverall Performance:")
    print(f"  Total Trades: {analysis['total_trades']}")
    print(f"  Total PnL: ${analysis['total_pnl']:.2f}")
    print(f"  Win Rate: {analysis['win_rate']:.1%}")
    print(f"  Avg Bars Held: {analysis['avg_bars_held']:.1f}")
    
    print(f"\nExit Reasons:")
    for reason, count in analysis['exit_reasons'].items():
        percentage = count / analysis['total_trades'] * 100
        print(f"  {reason}: {count} ({percentage:.1f}%)")
    
    print(f"\nPerformance by Exit Reason:")
    for reason, perf in analysis['performance_by_reason'].items():
        print(f"  {reason}:")
        print(f"    Count: {perf['count']}")
        print(f"    Avg PnL: ${perf['avg_pnl']:.2f}")
        print(f"    Win Rate: {perf['win_rate']:.1%}")
        print(f"    Avg Bars: {perf['avg_bars_held']:.1f}")
    
    print(f"\nStop Loss Effectiveness:")
    print(f"  Stop Loss Rate: {analysis['stop_loss_rate']:.1%}")
    print(f"  Stop Loss Avg PnL: ${analysis['stop_loss_avg_pnl']:.2f}")
    
    print(f"\nTake Profit Effectiveness:")
    print(f"  Take Profit Rate: {analysis['take_profit_rate']:.1%}")
    print(f"  Take Profit Avg PnL: ${analysis['take_profit_avg_pnl']:.2f}")
    
    print("="*60)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=100, freq='15min')
base_price = 50000
prices = base_price + np.cumsum(np.random.randn(100) * 100)

df = pd.DataFrame({
    'open': prices,
    'high': prices * (1 + np.abs(np.random.randn(100) * 0.001)),
    'low': prices * (1 - np.abs(np.random.randn(100) * 0.001)),
    'close': prices,
    'volume': np.random.randint(1000, 10000, 100)
}, index=dates)

# Sample signals
signals = [
    {'entry_bar': 10, 'entry_price': 50100, 'side': 'long_up'},
    {'entry_bar': 30, 'entry_price': 50200, 'side': 'long_up'},
    {'entry_bar': 50, 'entry_price': 50300, 'side': 'long_down'},
]

# Apply stops
trades = apply_stops_to_backtest(df, signals, stop_loss_pct=0.02, take_profit_pct=0.04, max_bars=16)

# Analyze performance
print_stop_analysis(trades)

# Validate parameters
validation = validate_stop_parameters(0.02, 0.04, 16)
print(f"\nValidation: {validation}")
"""
