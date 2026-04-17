"""
VADER Threshold Optimizer for Kalshi Sentiment Strategies.

Grid search optimizer for finding best VADER thresholds on historical data.
Evaluates combinations of pos_th and neg_th to maximize Sharpe ratio.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
from utils.logger import get_logger
from datetime import datetime, timezone

logger = get_logger(__name__)


@dataclass
class ThresholdResult:
    """Result of a threshold combination evaluation."""
    pos_th: float
    neg_th: float
    sharpe: float
    total_return: float
    max_drawdown: float
    win_rate: float
    trades: int
    score: float  # Combined objective


class VaderThresholdOptimizer:
    """
    Optimize VADER thresholds for sentiment trading on Kalshi.
    
    Performs grid search over pos_th and neg_th combinations,
    evaluating each on historical data using Sharpe ratio and drawdown.
    
    Usage:
        optimizer = VaderThresholdOptimizer()
        best = optimizer.optimize(sentiment_df, price_df)
        >>> print(f"Best thresholds: pos={best.pos_th:.2f}, neg={best.neg_th:.2f}")
    """
    
    def __init__(
        self,
        pos_th_range: Tuple[float, float] = (0.05, 0.4),
        neg_th_range: Tuple[float, float] = (-0.4, -0.05),
        n_steps: int = 7,
        risk_free_rate: float = 0.0,
    ):
        self.pos_range = pos_th_range
        self.neg_range = neg_th_range
        self.n_steps = n_steps
        self.risk_free_rate = risk_free_rate
        self.results: List[ThresholdResult] = []
    
    def generate_signals(
        self,
        combined_sentiment: np.ndarray,
        pos_th: float,
        neg_th: float,
    ) -> np.ndarray:
        """
        Generate -1/0/1 signals from sentiment series.
        
        Args:
            combined_sentiment: Array of sentiment scores
            pos_th: Positive threshold
            neg_th: Negative threshold
        
        Returns:
            Array of signals (-1=bearish, 0=neutral, 1=bullish)
        """
        signals = np.zeros_like(combined_sentiment)
        signals[combined_sentiment >= pos_th] = 1
        signals[combined_sentiment <= neg_th] = -1
        return signals
    
    def backtest_strategy(
        self,
        returns: np.ndarray,
        signals: np.ndarray,
    ) -> Dict[str, float]:
        """
        Backtest strategy returns.
        
        Args:
            returns: Asset returns array
            signals: Signal array (-1, 0, 1)
        
        Returns:
            Dict with metrics
        """
        # Lag signals by 1 to avoid lookahead bias
        signals_lag = np.roll(signals, 1)
        signals_lag[0] = 0
        
        # Strategy returns
        strategy_ret = signals_lag * returns
        
        # Cumulative returns
        cumulative = np.cumprod(1 + strategy_ret)
        
        # Metrics
        total_return = cumulative[-1] - 1
        
        # Sharpe ratio (annualized, assuming daily data)
        if np.std(strategy_ret) > 0:
            sharpe = (np.mean(strategy_ret) - self.risk_free_rate) / np.std(strategy_ret) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Max drawdown
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / peak
        max_dd = np.max(drawdown)
        
        # Win rate
        trades = strategy_ret[signals_lag != 0]
        if len(trades) > 0:
            win_rate = np.sum(trades > 0) / len(trades)
        else:
            win_rate = 0
        
        return {
            "sharpe": sharpe,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "trades": np.sum(signals_lag != 0),
        }
    
    def evaluate_thresholds(
        self,
        sentiment: np.ndarray,
        returns: np.ndarray,
        pos_th: float,
        neg_th: float,
    ) -> ThresholdResult:
        """Evaluate a single threshold combination."""
        signals = self.generate_signals(sentiment, pos_th, neg_th)
        metrics = self.backtest_strategy(returns, signals)
        
        # Combined score: Sharpe - 0.1 * drawdown
        score = metrics["sharpe"] - 0.1 * metrics["max_drawdown"]
        
        return ThresholdResult(
            pos_th=pos_th,
            neg_th=neg_th,
            sharpe=metrics["sharpe"],
            total_return=metrics["total_return"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            trades=metrics["trades"],
            score=score,
        )
    
    def optimize(
        self,
        sentiment_series: np.ndarray,
        returns_series: np.ndarray,
    ) -> ThresholdResult:
        """
        Run grid search optimization.
        
        Args:
            sentiment_series: Combined sentiment scores
            returns_series: Asset returns
        
        Returns:
            Best ThresholdResult
        """
        self.results = []
        
        # Generate grid
        pos_thresholds = np.linspace(self.pos_range[0], self.pos_range[1], self.n_steps)
        neg_thresholds = np.linspace(self.neg_range[0], self.neg_range[1], self.n_steps)
        
        logger.info(f"Starting grid search: {len(pos_thresholds)} x {len(neg_thresholds)} combinations")
        
        best = None
        for pos_th in pos_thresholds:
            for neg_th in neg_thresholds:
                result = self.evaluate_thresholds(
                    sentiment_series,
                    returns_series,
                    pos_th,
                    neg_th,
                )
                self.results.append(result)
                
                if best is None or result.score > best.score:
                    best = result
                    logger.debug(f"New best: pos={pos_th:.2f}, neg={neg_th:.2f}, score={result.score:.3f}")
        
        logger.info(f"Optimization complete. Best: pos={best.pos_th:.2f}, neg={best.neg_th:.2f}, sharpe={best.sharpe:.3f}")
        return best
    
    def get_top_results(self, n: int = 5) -> List[ThresholdResult]:
        """Get top N results by score."""
        sorted_results = sorted(self.results, key=lambda r: r.score, reverse=True)
        return sorted_results[:n]
    
    def to_dataframe(self):
        """Convert results to pandas DataFrame."""
        import pandas as pd
        
        data = [
            {
                "pos_th": r.pos_th,
                "neg_th": r.neg_th,
                "sharpe": r.sharpe,
                "total_return": r.total_return,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "trades": r.trades,
                "score": r.score,
            }
            for r in self.results
        ]
        
        return pd.DataFrame(data)


def quick_optimize(
    sentiment_history: List[float],
    price_history: List[float],
) -> Dict[str, Any]:
    """
    Quick one-liner to optimize thresholds on historical data.
    
    Args:
        sentiment_history: List of combined sentiment scores
        price_history: List of prices (Kalshi or underlying)
    
    Returns:
        Dict with best thresholds and metrics
    """
    # Calculate returns
    prices = np.array(price_history)
    returns = np.diff(prices) / prices[:-1]
    
    # Align sentiment (remove first element to match returns length)
    sentiment = np.array(sentiment_history[1:])
    
    optimizer = VaderThresholdOptimizer()
    best = optimizer.optimize(sentiment, returns)
    
    return {
        "pos_th": round(best.pos_th, 3),
        "neg_th": round(best.neg_th, 3),
        "sharpe": round(best.sharpe, 3),
        "total_return": round(best.total_return, 4),
        "max_drawdown": round(best.max_drawdown, 4),
        "win_rate": round(best.win_rate, 3),
        "trades": best.trades,
        "score": round(best.score, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── API Endpoint Helper ──────────────────────────────────────────────

def run_threshold_optimization(
    asset: str,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Run threshold optimization for an asset using historical data.
    
    Args:
        asset: Asset symbol
        days: Lookback period in days
    
    Returns:
        Optimization results with best thresholds
    """
    # In production, this would load actual historical data
    # For now, generate synthetic data for demonstration
    
    np.random.seed(42)
    n_points = days * 24  # Hourly data
    
    # Synthetic sentiment (mean-reverting around 0)
    sentiment = np.cumsum(np.random.randn(n_points) * 0.1)
    sentiment = np.clip(sentiment, -1, 1)
    
    # Synthetic returns (slightly correlated with sentiment)
    returns = np.random.randn(n_points) * 0.02 + sentiment * 0.01
    
    optimizer = VaderThresholdOptimizer(n_steps=10)
    best = optimizer.optimize(sentiment, returns)
    top5 = optimizer.get_top_results(5)
    
    return {
        "asset": asset,
        "lookback_days": days,
        "best": {
            "pos_th": round(best.pos_th, 3),
            "neg_th": round(best.neg_th, 3),
            "sharpe": round(best.sharpe, 3),
            "max_drawdown": round(best.max_drawdown, 4),
            "win_rate": round(best.win_rate, 3),
            "trades": best.trades,
        },
        "top_5": [
            {
                "pos_th": round(r.pos_th, 3),
                "neg_th": round(r.neg_th, 3),
                "sharpe": round(r.sharpe, 3),
                "score": round(r.score, 4),
            }
            for r in top5
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
