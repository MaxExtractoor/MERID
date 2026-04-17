"""
Kalshi Backtest with Sentiment-Based Position Sizing

Backtest framework that incorporates dynamic position sizing based on
sentiment state (FG index, combined sentiment, confidence).
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Result of sentiment-based backtest."""
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    volatility: float
    win_rate: float
    num_trades: int
    avg_position_size: float
    equity_curve: pd.Series
    trades: pd.DataFrame


class KalshiSentimentBacktester:
    """
    Backtest sentiment-based position sizing on Kalshi historical data.
    
    Usage:
        bt = KalshiSentimentBacktester(equity=1000.0)
        
        # Run backtest
        result = bt.backtest(
            hist_df=price_data,
            sent_states=sentiment_by_timestamp,
            base_frac=0.02,
        )
        
        >>> print(f"Return: {result.total_return:.2%}, Sharpe: {result.sharpe_ratio:.2f}")
    """
    
    def __init__(self, equity: float = 1000.0):
        self.start_equity = equity
    
    def size_from_sentiment(
        self,
        equity: float,
        fg_index: int,
        combined_sent: float,
        confidence: float,
        base_frac: float = 0.02,
    ) -> float:
        """
        Compute position size from sentiment state.
        
        Args:
            equity: Current equity
            fg_index: Fear/greed index 0-100
            combined_sent: Combined sentiment -1 to 1
            confidence: Sentiment confidence 0-1
            base_frac: Base risk fraction
        
        Returns:
            Position size in dollars
        """
        base = equity * base_frac
        
        # Extreme check (crowd extreme)
        extreme = (fg_index >= 80 and combined_sent > 0) or \
                  (fg_index <= 20 and combined_sent < 0)
        
        mult = 1.0
        if extreme:
            mult *= 0.6  # Scale down in extremes
        
        # Confidence scaling
        mult *= (0.5 + 0.5 * confidence)
        
        # Hard cap at 3% of equity
        risk = base * mult
        risk = min(risk, 0.03 * equity)
        
        return max(0.0, risk)
    
    def backtest(
        self,
        hist_df: pd.DataFrame,
        sent_states: Dict[datetime, Dict[str, Any]],
        base_frac: float = 0.02,
        kalshi_payoff: bool = True,
        lag_bars: int = 1,
    ) -> BacktestResult:
        """
        Run backtest with sentiment-based sizing.

        Args:
            hist_df: DataFrame indexed by timestamp with 'return' column
            sent_states: Dict mapping timestamp to sentiment state dict
            base_frac: Base risk fraction
            kalshi_payoff: Use Kalshi binary payoff structure
            lag_bars: Number of bars to lag sentiment lookup (default=1).
                      Prevents look-ahead bias: at bar i we only use sentiment
                      from bar i-lag_bars or earlier.

        Returns:
            BacktestResult
        """
        if lag_bars < 1:
            raise ValueError(
                f"lag_bars must be >= 1 to prevent look-ahead bias, got {lag_bars}"
            )

        # Build a sorted list of timestamps so we can do lag-safe lookups
        sorted_sent_ts = sorted(sent_states.keys())

        def _get_lagged_sentiment(current_ts) -> Optional[Dict[str, Any]]:
            """Return the most recent sentiment state strictly before current_ts."""
            eligible = [t for t in sorted_sent_ts if t < current_ts]
            if not eligible:
                return None
            # Apply additional bar lag if requested
            idx = len(eligible) - lag_bars
            if idx < 0:
                return None
            return sent_states.get(eligible[idx])

        equity = self.start_equity
        equity_series = [equity]
        trades = []

        for ts, row in hist_df.iterrows():
            ret = row["return"]

            # Lag-safe sentiment lookup — never uses data from ts or later
            st = _get_lagged_sentiment(ts)
            
            if st is None:
                # No sentiment - use base size
                size = equity * base_frac
                fg_idx = 50
                conf = 0.5
                combined = 0.0
            else:
                fg_idx = st.get("fg_index", 50)
                combined = st.get("combined", 0.0)
                conf = st.get("confidence", 0.5)
                
                size = self.size_from_sentiment(
                    equity, fg_idx, combined, conf, base_frac
                )
            
            # Compute PnL
            if kalshi_payoff:
                # Kalshi: bet returns 1 if correct, 0 if wrong
                # Simplified: use return as proxy for win/loss
                pnl = size * ret
            else:
                pnl = size * ret
            
            equity += pnl
            equity_series.append(equity)
            
            trades.append({
                "timestamp": ts,
                "size": size,
                "return": ret,
                "pnl": pnl,
                "equity": equity,
                "fg_index": fg_idx,
                "sentiment": combined,
                "confidence": conf,
            })
        
        # Compute metrics
        equity_series = pd.Series(equity_series, index=[hist_df.index[0]] + list(hist_df.index))
        returns = equity_series.pct_change().dropna()
        
        total_return = (equity / self.start_equity) - 1
        
        if len(returns) > 0 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(252)  # Annualized
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity_series.cummax()
        drawdown = (peak - equity_series) / peak
        max_dd = drawdown.max()
        
        # Volatility
        vol = returns.std() * np.sqrt(252) if len(returns) > 0 else 0.0
        
        # Win rate
        trades_df = pd.DataFrame(trades)
        wins = len(trades_df[trades_df["pnl"] > 0]) if len(trades_df) > 0 else 0
        win_rate = wins / len(trades_df) if len(trades_df) > 0 else 0.0
        
        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            volatility=vol,
            win_rate=win_rate,
            num_trades=len(trades),
            avg_position_size=trades_df["size"].mean() if len(trades_df) > 0 else 0.0,
            equity_curve=equity_series,
            trades=trades_df,
        )
    
    def compare_strategies(
        self,
        hist_df: pd.DataFrame,
        sent_states: Dict[datetime, Dict[str, Any]],
        base_frac: float = 0.02,
    ) -> Dict[str, BacktestResult]:
        """
        Compare sentiment sizing vs fixed sizing.
        
        Returns:
            Dict with 'sentiment' and 'fixed' backtest results
        """
        # Sentiment-based
        sent_result = self.backtest(hist_df, sent_states, base_frac)
        
        # Fixed sizing (no sentiment states)
        empty_states = {}
        fixed_result = self.backtest(hist_df, empty_states, base_frac)
        
        return {
            "sentiment": sent_result,
            "fixed": fixed_result,
        }
    
    def generate_report(
        self,
        result: BacktestResult,
    ) -> Dict[str, Any]:
        """
        Generate formatted backtest report.
        
        Returns:
            Dict with summary and detailed metrics
        """
        return {
            "summary": {
                "total_return_pct": f"{result.total_return:.2%}",
                "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
                "max_drawdown_pct": f"{result.max_drawdown:.2%}",
                "volatility_annual_pct": f"{result.volatility:.2%}",
                "win_rate_pct": f"{result.win_rate:.1%}",
                "num_trades": result.num_trades,
                "avg_position_size": f"${result.avg_position_size:.2f}",
            },
            "metrics": {
                "total_return": result.total_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "volatility": result.volatility,
                "win_rate": result.win_rate,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_sentiment_backtest(
    hist_df: pd.DataFrame,
    fg_series: pd.Series,
    sent_series: pd.Series,
    conf_series: pd.Series,
    equity: float = 1000.0,
    base_frac: float = 0.02,
) -> Dict[str, Any]:
    """
    Quick one-liner to run sentiment backtest.
    
    Args:
        hist_df: DataFrame with 'return' column
        fg_series: Series of FG index values
        sent_series: Series of combined sentiment
        conf_series: Series of confidence values
        equity: Starting equity
        base_frac: Base risk fraction
    
    Returns:
        Backtest report dict
    """
    # Build sentiment states dict
    sent_states = {}
    for ts in hist_df.index:
        sent_states[ts] = {
            "fg_index": fg_series.get(ts, 50),
            "combined": sent_series.get(ts, 0.0),
            "confidence": conf_series.get(ts, 0.5),
        }
    
    bt = KalshiSentimentBacktester(equity=equity)
    result = bt.backtest(hist_df, sent_states, base_frac)
    
    return bt.generate_report(result)


def compare_sentiment_vs_fixed(
    hist_df: pd.DataFrame,
    sent_states: Dict[datetime, Dict[str, Any]],
    equity: float = 1000.0,
) -> Dict[str, Any]:
    """
    Compare sentiment-based vs fixed sizing.
    
    Returns:
        Comparison dict
    """
    bt = KalshiSentimentBacktester(equity=equity)
    comparison = bt.compare_strategies(hist_df, sent_states)
    
    return {
        "sentiment": bt.generate_report(comparison["sentiment"]),
        "fixed": bt.generate_report(comparison["fixed"]),
        "improvement": {
            "return_diff": comparison["sentiment"].total_return - comparison["fixed"].total_return,
            "sharpe_diff": comparison["sentiment"].sharpe_ratio - comparison["fixed"].sharpe_ratio,
            "drawdown_diff": comparison["sentiment"].max_drawdown - comparison["fixed"].max_drawdown,
        },
    }
