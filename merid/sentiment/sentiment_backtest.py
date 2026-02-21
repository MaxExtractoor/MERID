"""
Sentiment Evaluation Backtesting Framework

Compares Twitter vs Reddit sentiment accuracy by backtesting
against actual market outcomes. Tracks prediction accuracy,
regime detection, and signal timing.

Usage:
    from merid.sentiment.sentiment_backtest import SentimentBacktestEngine
    
    engine = SentimentBacktestEngine()
    
    # Backtest Twitter sentiment for BTC
    results = engine.backtest_sentiment_source(
        asset="BTC",
        source="twitter",
        start_date="2026-01-01",
        end_date="2026-02-15",
        horizon_hours=24,  # Predict 24h ahead
    )
    
    # Compare Twitter vs Reddit
    comparison = engine.compare_sources("BTC", "2026-01-01", "2026-02-15")
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import json
import logging
from collections import defaultdict

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

logger = logging.getLogger(__name__)


class SentimentSource(Enum):
    """Social sentiment sources."""
    TWITTER = "twitter"
    REDDIT = "reddit"
    COMBINED = "combined"


class Direction(Enum):
    """Predicted market direction."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class SentimentPrediction:
    """A single sentiment-based prediction."""
    timestamp: datetime
    asset: str
    source: SentimentSource
    sentiment_score: float  # -1.0 to +1.0
    confidence: float
    volume: int
    predicted_direction: Direction
    fear_greed_at_pred: int  # 0-100
    regime: str  # extreme_fear, fear, neutral, greed, extreme_greed


@dataclass
class MarketOutcome:
    """Actual market outcome for evaluation."""
    timestamp: datetime
    asset: str
    price_at_pred: float
    price_at_horizon: float
    return_pct: float
    actual_direction: Direction
    volatility: float


@dataclass
class PredictionResult:
    """Result of a single prediction vs outcome."""
    prediction: SentimentPrediction
    outcome: MarketOutcome
    correct: bool  # Did sentiment direction match actual?
    magnitude_error: float  # |sentiment| - |actual_return|
    timing_score: float  # 0-1 based on how close to horizon


@dataclass
class BacktestResults:
    """Complete backtest results for a sentiment source."""
    asset: str
    source: SentimentSource
    start_date: datetime
    end_date: datetime
    horizon_hours: int
    
    total_predictions: int = 0
    correct_direction: int = 0
    
    # Accuracy by regime
    accuracy_by_regime: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Direction-specific
    bullish_accuracy: float = 0.0
    bearish_accuracy: float = 0.0
    neutral_accuracy: float = 0.0
    
    # Confidence-weighted
    high_conf_accuracy: float = 0.0
    low_conf_accuracy: float = 0.0
    
    # Overall metrics
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    
    # Edge metrics
    avg_sentiment_return_correlation: float = 0.0
    sharpe_of_signal: float = 0.0
    
    # Raw results for drill-down
    results: List[PredictionResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "asset": self.asset,
            "source": self.source.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "horizon_hours": self.horizon_hours,
            "total_predictions": self.total_predictions,
            "correct_direction": self.correct_direction,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "bullish_accuracy": round(self.bullish_accuracy, 4),
            "bearish_accuracy": round(self.bearish_accuracy, 4),
            "neutral_accuracy": round(self.neutral_accuracy, 4),
            "high_conf_accuracy": round(self.high_conf_accuracy, 4),
            "low_conf_accuracy": round(self.low_conf_accuracy, 4),
            "accuracy_by_regime": self.accuracy_by_regime,
            "sentiment_return_correlation": round(self.avg_sentiment_return_correlation, 4),
            "sharpe_of_signal": round(self.sharpe_of_signal, 4),
        }


class SentimentBacktestEngine:
    """
    Backtesting engine for evaluating sentiment signal accuracy.
    
    Loads historical sentiment snapshots and market outcomes,
    evaluates directional accuracy, and compares sources.
    """
    
    def __init__(
        self,
        sentiment_history_path: Optional[str] = None,
        price_history_path: Optional[str] = None,
    ):
        self.sentiment_path = sentiment_history_path or "data/sentiment_history.jsonl"
        self.price_path = price_history_path or "data/price_history.jsonl"
        
        self._sentiment_cache: Dict[str, List[SentimentPrediction]] = {}
        self._price_cache: Dict[str, List[MarketOutcome]] = {}
    
    def _load_historical_sentiment(
        self,
        asset: str,
        source: SentimentSource,
        start: datetime,
        end: datetime,
    ) -> List[SentimentPrediction]:
        """Load historical sentiment snapshots from storage."""
        # In production, this loads from time-series DB (e.g., ClickHouse)
        # For now, generate synthetic data for testing
        
        predictions = []
        current = start
        
        while current < end:
            # Generate synthetic sentiment with some signal
            # In production: query actual historical sentiment from DB
            base_sentiment = 0.1 * np.sin(current.timestamp() / 86400) if np else 0
            noise = (np.random.randn() * 0.3 if np else 0)
            sentiment = max(-1, min(1, base_sentiment + noise))
            
            # Determine direction from sentiment
            if sentiment > 0.2:
                direction = Direction.BULLISH
            elif sentiment < -0.2:
                direction = Direction.BEARISH
            else:
                direction = Direction.NEUTRAL
            
            # Varying confidence
            confidence = 0.4 + abs(sentiment) * 0.5 + (np.random.rand() * 0.1 if np else 0)
            confidence = min(1.0, confidence)
            
            # Fear/greed cycles
            fg = 50 + int(30 * np.sin(current.timestamp() / 43200)) if np else 50
            
            if fg <= 20:
                regime = "extreme_fear"
            elif fg <= 40:
                regime = "fear"
            elif fg <= 60:
                regime = "neutral"
            elif fg <= 80:
                regime = "greed"
            else:
                regime = "extreme_greed"
            
            predictions.append(SentimentPrediction(
                timestamp=current,
                asset=asset,
                source=source,
                sentiment_score=sentiment,
                confidence=confidence,
                volume=50 + int(np.random.exponential(100) if np else 0),
                predicted_direction=direction,
                fear_greed_at_pred=fg,
                regime=regime,
            ))
            
            # Sample every 4 hours
            current += timedelta(hours=4)
        
        return predictions
    
    def _load_historical_outcomes(
        self,
        asset: str,
        start: datetime,
        end: datetime,
        horizon_hours: int,
    ) -> Dict[datetime, MarketOutcome]:
        """Load historical price outcomes for evaluation."""
        # In production: query actual OHLC data
        # For now, generate synthetic outcomes
        
        outcomes = {}
        current = start
        
        # Generate price series
        price = 50000.0  # Starting BTC price
        
        while current <= end + timedelta(hours=horizon_hours):
            # Random walk with slight mean reversion
            drift = -0.001 if price > 52000 else 0.001 if price < 48000 else 0
            ret = (drift + (np.random.randn() * 0.02 if np else 0))
            price = price * (1 + ret)
            
            outcomes[current] = MarketOutcome(
                timestamp=current,
                asset=asset,
                price_at_pred=price,
                price_at_horizon=price,  # Will be updated
                return_pct=ret * 100,
                actual_direction=Direction.BULLISH if ret > 0 else Direction.BEARISH,
                volatility=abs(ret) * 100,
            )
            
            current += timedelta(hours=1)
        
        # Fill in horizon prices
        for ts, outcome in list(outcomes.items()):
            horizon_ts = ts + timedelta(hours=horizon_hours)
            if horizon_ts in outcomes:
                horizon_price = outcomes[horizon_ts].price_at_pred
                ret_pct = ((horizon_price - outcome.price_at_pred) / outcome.price_at_pred) * 100
                outcome.price_at_horizon = horizon_price
                outcome.return_pct = ret_pct
                outcome.actual_direction = (
                    Direction.BULLISH if ret_pct > 0.5
                    else Direction.BEARISH if ret_pct < -0.5
                    else Direction.NEUTRAL
                )
        
        return outcomes
    
    def backtest_sentiment_source(
        self,
        asset: str,
        source: SentimentSource,
        start_date: str,
        end_date: str,
        horizon_hours: int = 24,
    ) -> BacktestResults:
        """
        Run backtest for a single sentiment source.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            source: Twitter, Reddit, or Combined
            start_date: ISO date string (e.g., "2026-01-01")
            end_date: ISO date string
            horizon_hours: How far ahead to predict
        
        Returns:
            BacktestResults with accuracy metrics
        """
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        # Load data
        predictions = self._load_historical_sentiment(asset, source, start, end)
        outcomes = self._load_historical_outcomes(asset, start, end, horizon_hours)
        
        # Match predictions to outcomes
        results = []
        for pred in predictions:
            horizon_ts = pred.timestamp + timedelta(hours=horizon_hours)
            
            # Find closest outcome
            closest_ts = min(
                outcomes.keys(),
                key=lambda ts: abs((ts - horizon_ts).total_seconds())
            )
            outcome = outcomes.get(closest_ts)
            
            if not outcome:
                continue
            
            # Evaluate
            correct = pred.predicted_direction == outcome.actual_direction
            mag_error = abs(pred.sentiment_score) - abs(outcome.return_pct / 100)
            timing = max(0, 1 - abs((closest_ts - horizon_ts).total_seconds()) / 3600)
            
            results.append(PredictionResult(
                prediction=pred,
                outcome=outcome,
                correct=correct,
                magnitude_error=mag_error,
                timing_score=timing,
            ))
        
        # Calculate metrics
        total = len(results)
        if total == 0:
            return BacktestResults(
                asset=asset,
                source=source,
                start_date=start,
                end_date=end,
                horizon_hours=horizon_hours,
                total_predictions=0,
            )
        
        correct = sum(1 for r in results if r.correct)
        accuracy = correct / total
        
        # By direction
        bullish = [r for r in results if r.prediction.predicted_direction == Direction.BULLISH]
        bearish = [r for r in results if r.prediction.predicted_direction == Direction.BEARISH]
        neutral = [r for r in results if r.prediction.predicted_direction == Direction.NEUTRAL]
        
        bullish_acc = sum(1 for r in bullish if r.correct) / len(bullish) if bullish else 0
        bearish_acc = sum(1 for r in bearish if r.correct) / len(bearish) if bearish else 0
        neutral_acc = sum(1 for r in neutral if r.correct) / len(neutral) if neutral else 0
        
        # By confidence
        high_conf = [r for r in results if r.prediction.confidence >= 0.7]
        low_conf = [r for r in results if r.prediction.confidence < 0.7]
        
        high_conf_acc = sum(1 for r in high_conf if r.correct) / len(high_conf) if high_conf else 0
        low_conf_acc = sum(1 for r in low_conf if r.correct) / len(low_conf) if low_conf else 0
        
        # By regime
        regime_stats = defaultdict(lambda: {"correct": 0, "total": 0})
        for r in results:
            regime = r.prediction.regime
            regime_stats[regime]["total"] += 1
            if r.correct:
                regime_stats[regime]["correct"] += 1
        
        regime_accuracy = {
            regime: {
                "accuracy": round(stats["correct"] / stats["total"], 4),
                "count": stats["total"],
            }
            for regime, stats in regime_stats.items()
        }
        
        # Precision/recall (treating bullish as positive class)
        true_pos = sum(1 for r in results if r.correct and r.prediction.predicted_direction == Direction.BULLISH)
        false_pos = sum(1 for r in results if not r.correct and r.prediction.predicted_direction == Direction.BULLISH)
        false_neg = sum(1 for r in results if not r.correct and r.prediction.predicted_direction != Direction.BULLISH and r.outcome.actual_direction == Direction.BULLISH)
        
        precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 0
        recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        # Correlation
        if np and len(results) > 10:
            sentiments = [r.prediction.sentiment_score for r in results]
            returns = [r.outcome.return_pct / 100 for r in results]
            correlation = np.corrcoef(sentiments, returns)[0, 1]
        else:
            correlation = 0.0
        
        return BacktestResults(
            asset=asset,
            source=source,
            start_date=start,
            end_date=end,
            horizon_hours=horizon_hours,
            total_predictions=total,
            correct_direction=correct,
            accuracy_by_regime=regime_accuracy,
            bullish_accuracy=bullish_acc,
            bearish_accuracy=bearish_acc,
            neutral_accuracy=neutral_acc,
            high_conf_accuracy=high_conf_acc,
            low_conf_accuracy=low_conf_acc,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            avg_sentiment_return_correlation=correlation,
            sharpe_of_signal=correlation * np.sqrt(total) if np else 0,
            results=results,
        )
    
    def compare_sources(
        self,
        asset: str,
        start_date: str,
        end_date: str,
        horizon_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        Compare Twitter vs Reddit vs Combined sentiment accuracy.
        
        Returns side-by-side comparison with winner identification.
        """
        twitter_results = self.backtest_sentiment_source(
            asset, SentimentSource.TWITTER, start_date, end_date, horizon_hours
        )
        reddit_results = self.backtest_sentiment_source(
            asset, SentimentSource.REDDIT, start_date, end_date, horizon_hours
        )
        combined_results = self.backtest_sentiment_source(
            asset, SentimentSource.COMBINED, start_date, end_date, horizon_hours
        )
        
        sources = {
            "twitter": twitter_results,
            "reddit": reddit_results,
            "combined": combined_results,
        }
        
        # Determine winner by accuracy
        winner = max(sources.items(), key=lambda x: x[1].accuracy)[0]
        
        # Identify best regime for each
        best_regimes = {}
        for name, results in sources.items():
            if results.accuracy_by_regime:
                best_regime = max(
                    results.accuracy_by_regime.items(),
                    key=lambda x: x[1]["accuracy"]
                )[0]
                best_regimes[name] = best_regime
        
        return {
            "asset": asset,
            "period": {"start": start_date, "end": end_date, "horizon_hours": horizon_hours},
            "winner": winner,
            "twitter": twitter_results.to_dict(),
            "reddit": reddit_results.to_dict(),
            "combined": combined_results.to_dict(),
            "best_regimes": best_regimes,
            "recommendation": (
                f"Use {winner} sentiment as primary signal. "
                f"Best performance in {best_regimes.get(winner, 'neutral')} regime."
            ),
        }
    
    def generate_report(
        self,
        asset: str,
        start_date: str,
        end_date: str,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a markdown report of sentiment backtest results.
        
        Args:
            asset: Asset to analyze
            start_date: Start of backtest period
            end_date: End of backtest period
            output_path: Optional file to write report to
        
        Returns:
            Markdown-formatted report string
        """
        comparison = self.compare_sources(asset, start_date, end_date)
        
        lines = [
            f"# Sentiment Backtest Report: {asset}",
            "",
            f"**Period:** {start_date} to {end_date}",
            f"**Horizon:** {comparison['period']['horizon_hours']} hours",
            "",
            "## Summary",
            "",
            f"**Winner:** {comparison['winner'].upper()}",
            "",
            comparison['recommendation'],
            "",
            "## Accuracy Comparison",
            "",
            "| Source | Accuracy | Precision | Recall | F1 | Correlation |",
            "|--------|----------|-----------|--------|----|-------------|",
        ]
        
        for source in ["twitter", "reddit", "combined"]:
            data = comparison[source]
            lines.append(
                f"| {source.upper():8} | {data['accuracy']:.1%} | "
                f"{data['precision']:.3f} | {data['recall']:.3f} | "
                f"{data['f1_score']:.3f} | {data['sentiment_return_correlation']:+.3f} |"
            )
        
        lines.extend([
            "",
            "## Performance by Regime",
            "",
        ])
        
        for source in ["twitter", "reddit", "combined"]:
            data = comparison[source]
            lines.extend([
                f"### {source.upper()}",
                "",
            ])
            
            if data['accuracy_by_regime']:
                lines.append("| Regime | Accuracy | Count |")
                lines.append("|--------|----------|-------|")
                for regime, stats in data['accuracy_by_regime'].items():
                    lines.append(f"| {regime:15} | {stats['accuracy']:.1%} | {stats['count']} |")
                lines.append("")
            else:
                lines.append("*No regime data available*\n")
        
        lines.extend([
            "",
            "## Direction-Specific Accuracy",
            "",
            "| Source | Bullish | Bearish | Neutral |",
            "|--------|---------|---------|---------|",
        ])
        
        for source in ["twitter", "reddit", "combined"]:
            data = comparison[source]
            lines.append(
                f"| {source.upper():8} | {data['bullish_accuracy']:.1%} | "
                f"{data['bearish_accuracy']:.1%} | {data['neutral_accuracy']:.1%} |"
            )
        
        lines.extend([
            "",
            "## Confidence Analysis",
            "",
            "| Source | High Conf (≥0.7) | Low Conf (<0.7) |",
            "|--------|-----------------|-----------------|",
        ])
        
        for source in ["twitter", "reddit", "combined"]:
            data = comparison[source]
            lines.append(
                f"| {source.upper():8} | {data['high_conf_accuracy']:.1%} | "
                f"{data['low_conf_accuracy']:.1%} |"
            )
        
        lines.extend([
            "",
            "---",
            f"*Report generated at {datetime.now(timezone.utc).isoformat()}*",
        ])
        
        report = "\n".join(lines)
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
            logger.info(f"Report written to {output_path}")
        
        return report


# Convenience functions
def quick_backtest(
    asset: str,
    source: str = "twitter",
    days: int = 30,
) -> Dict[str, Any]:
    """Quick one-liner to backtest sentiment for an asset."""
    engine = SentimentBacktestEngine()
    
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    
    source_enum = SentimentSource(source)
    results = engine.backtest_sentiment_source(
        asset=asset,
        source=source_enum,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        horizon_hours=24,
    )
    
    return results.to_dict()


def compare_twitter_reddit(asset: str, days: int = 30) -> Dict[str, Any]:
    """Compare Twitter vs Reddit for an asset over recent history."""
    engine = SentimentBacktestEngine()
    
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    
    return engine.compare_sources(
        asset=asset,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        horizon_hours=24,
    )
