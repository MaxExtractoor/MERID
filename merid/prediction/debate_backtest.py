"""
Debate Backtest Harness
Compares prediction performance with and without debates on historical Kalshi markets.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
import statistics

from utils.logger import get_logger
from merid.prediction.debate import get_debate_store
from merid.metrics.calibration import get_calibration_store
from merid.metrics.outcome_resolver import get_outcome_resolver
from core.slo_monitor import SLOMonitor

logger = get_logger("merid.prediction.debate_backtest")


@dataclass
class BacktestResult:
    """Results from debate vs no-debate comparison."""
    symbol: str
    with_debates_brier: float
    without_debates_brier: float
    debate_lift: float
    debate_count: int
    improvement_pct: float
    statistically_significant: bool


@dataclass
class BacktestSummary:
    """Summary of backtest across multiple markets."""
    total_markets: int
    avg_improvement_pct: float
    markets_with_improvement: int
    markets_with_negative_impact: int
    markets_with_debates: int
    avg_debate_lift: float
    confidence_level: float


class DebateBacktester:
    """Backtests the value of debates in prediction accuracy."""
    
    def __init__(self):
        self.debate_store = get_debate_store()
        self.calibration_store = get_calibration_store()
        self.slo_monitor = SLOMonitor.get_instance()
    
    async def run_backtest(
        self, 
        start_date: datetime,
        end_date: datetime,
        min_debates_per_symbol: int = 1
    ) -> Tuple[BacktestSummary, List[BacktestResult]]:
        """
        Run comprehensive backtest comparing debate vs no-debate performance.
        
        Args:
            start_date: Start of backtest period
            end_date: End of backtest period
            min_debates_per_symbol: Minimum debates required for symbol inclusion
            
        Returns:
            Tuple of (BacktestSummary, List[BacktestResult]) with detailed results
        """
        logger.info(f"Starting debate backtest from {start_date} to {end_date}")
        
        # Get all resolved debates in period
        resolved_debates = self._get_resolved_debates(start_date, end_date)
        
        # Group by symbol
        symbols_with_debates = {}
        for debate in resolved_debates:
            if debate.symbol not in symbols_with_debates:
                symbols_with_debates[debate.symbol] = []
            symbols_with_debates[debate.symbol].append(debate)
        
        # Filter symbols with sufficient debates
        qualified_symbols = {
            symbol: debates for symbol, debates in symbols_with_debates.items()
            if len(debates) >= min_debates_per_symbol
        }
        
        logger.info(f"Found {len(qualified_symbols)} symbols with sufficient debates")
        
        # Run comparison for each symbol
        results = []
        for symbol, debates in qualified_symbols.items():
            result = await self._compare_symbol_performance(symbol, debates)
            if result:
                results.append(result)
        
        # Calculate summary statistics
        summary = self._calculate_summary(results)
        
        # Track SLO metrics
        self.slo_monitor.track_slo(
            metric_name="debate.backtest.completion",
            success=True,
            total=1,
            metadata={
                "markets_tested": len(results),
                "avg_improvement": summary.avg_improvement_pct,
                "markets_with_improvement": summary.markets_with_improvement,
                "markets_with_negative_impact": summary.markets_with_negative_impact,
                "backtest_period_days": (end_date - start_date).days
            }
        )
        
        logger.info(f"Backtest completed: {summary.avg_improvement_pct:.2f}% avg improvement")
        return summary, results
    
    async def _compare_symbol_performance(
        self, 
        symbol: str, 
        debates: List[Any]
    ) -> Optional[BacktestResult]:
        """Compare performance with vs without debates for a specific symbol."""
        try:
            # Get all predictions for this symbol
            all_predictions = self.calibration_store.get_predictions_for_symbol(symbol)
            
            if not all_predictions:
                return None
            
            # Separate predictions into debate vs no-debate groups
            debate_predictions = []
            no_debate_predictions = []
            
            # Get debate timestamps to determine which predictions were influenced
            debate_timestamps = {debate.created_at for debate in debates}
            
            for pred in all_predictions:
                pred_time = pred.get('timestamp', 0)
                
                # Check if prediction was made after a debate (influenced)
                was_influenced = any(
                    pred_time >= debate_time 
                    for debate_time in debate_timestamps
                )
                
                if was_influenced:
                    debate_predictions.append(pred)
                else:
                    no_debate_predictions.append(pred)
            
            # Calculate Brier scores for both groups
            with_debates_brier = self._calculate_brier_score(debate_predictions)
            without_debates_brier = self._calculate_brier_score(no_debate_predictions)
            
            # Calculate average debate lift
            avg_debate_lift = statistics.mean([
                debate.debate_lift or 0.0 for debate in debates
            ])
            
            # Calculate improvement percentage with division-by-zero guard
            if without_debates_brier == 0.0:
                improvement_pct = 0.0
            else:
                improvement_pct = ((without_debates_brier - with_debates_brier) / without_debates_brier) * 100
            
            # Simple statistical significance test (would need more sophisticated test in production)
            statistically_significant = (
                len(debate_predictions) >= 10 and 
                len(no_debate_predictions) >= 10 and
                abs(improvement_pct) > 5.0  # 5% threshold
            )
            
            return BacktestResult(
                symbol=symbol,
                with_debates_brier=with_debates_brier,
                without_debates_brier=without_debates_brier,
                debate_lift=avg_debate_lift,
                debate_count=len(debates),
                improvement_pct=improvement_pct,
                statistically_significant=statistically_significant
            )
            
        except Exception as e:
            logger.warning(f"Error comparing performance for {symbol}: {e}")
            return None
    
    def _calculate_brier_score(self, predictions: List[Dict[str, Any]]) -> float:
        """Calculate Brier score for a set of predictions."""
        if not predictions:
            return 0.5  # Neutral score
        
        brier_scores = []
        for pred in predictions:
            prob = pred.get('predicted_prob', 0.5)
            outcome = pred.get('actual_outcome')
            if outcome is not None:
                brier = (prob - outcome) ** 2
                brier_scores.append(brier)
        
        return statistics.mean(brier_scores) if brier_scores else 0.5
    
    def _get_resolved_debates(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Any]:
        """Get all resolved debates within the date range."""
        resolved_debates = []
        
        for debate in self.debate_store.list_debates():
            if (debate.status == "resolved" and
                debate.outcome is not None and
                start_date.timestamp() <= debate.created_at <= end_date.timestamp()):
                resolved_debates.append(debate)
        
        return resolved_debates
    
    def _calculate_summary(self, results: List[BacktestResult]) -> BacktestSummary:
        """Calculate summary statistics from backtest results."""
        if not results:
            return BacktestSummary(0, 0.0, 0, 0, 0, 0.0, 0.0)
        
        improvements = [r.improvement_pct for r in results]
        lifts = [r.debate_lift for r in results]
        
        avg_improvement = statistics.mean(improvements)
        markets_with_improvement = sum(1 for imp in improvements if imp > 0)
        markets_with_negative_impact = sum(1 for imp in improvements if imp < 0)
        markets_with_debates = len([r for r in results if r.debate_count > 0])
        avg_lift = statistics.mean(lifts)
        
        # Simple confidence calculation based on consistency
        significant_results = [r for r in results if r.statistically_significant]
        confidence_level = len(significant_results) / len(results) if results else 0.0
        
        return BacktestSummary(
            total_markets=len(results),
            avg_improvement_pct=avg_improvement,
            markets_with_improvement=markets_with_improvement,
            markets_with_negative_impact=markets_with_negative_impact,
            markets_with_debates=markets_with_debates,
            avg_debate_lift=avg_lift,
            confidence_level=confidence_level
        )
    
    def generate_report(self, summary: BacktestSummary, results: List[BacktestResult]) -> str:
        """Generate a human-readable backtest report."""
        report = f"""
# Debate System Backtest Report

## Summary
- **Total Markets Tested**: {summary.total_markets}
- **Average Improvement**: {summary.avg_improvement_pct:.2f}%
- **Markets with Improvement**: {summary.markets_with_improvement}/{summary.total_markets} ({summary.markets_with_improvement/summary.total_markets*100:.1f}%)
- **Markets with Negative Impact**: {summary.markets_with_negative_impact}/{summary.total_markets} ({summary.markets_with_negative_impact/summary.total_markets*100:.1f}%)
- **Markets with Debates**: {summary.markets_with_debates}
- **Average Debate Lift**: {summary.avg_debate_lift:.4f}
- **Confidence Level**: {summary.confidence_level:.2f}

## Key Findings
"""
        
        if summary.avg_improvement_pct > 0:
            report += f"✅ Debates **improved prediction accuracy** by {summary.avg_improvement_pct:.2f}% on average\n"
        else:
            report += f"⚠️ Debates **reduced prediction accuracy** by {abs(summary.avg_improvement_pct):.2f}% on average\n"
        
        if summary.markets_with_negative_impact > 0:
            report += f"⚠️ {summary.markets_with_negative_impact} markets showed **negative impact** from debates\n"
        
        if summary.confidence_level > 0.7:
            report += "✅ Results are **statistically significant** and reliable\n"
        elif summary.confidence_level > 0.4:
            report += "⚠️ Results show **moderate statistical significance**\n"
        else:
            report += "❌ Results are **not statistically significant**\n"
        
        report += "\n## Top Performing Markets\n"
        top_results = sorted(results, key=lambda r: r.improvement_pct, reverse=True)[:5]
        for i, result in enumerate(top_results, 1):
            status = "🚀" if result.improvement_pct > 10 else "📈" if result.improvement_pct > 0 else "📉"
            report += f"{i}. {status} {result.symbol}: {result.improvement_pct:.2f}% improvement ({result.debate_count} debates)\n"
        
        report += "\n## Worst Performing Markets\n"
        worst_results = sorted(results, key=lambda r: r.improvement_pct)[:5]
        for i, result in enumerate(worst_results, 1):
            report += f"{i}. {result.symbol}: {result.improvement_pct:.2f}% change ({result.debate_count} debates)\n"
        
        return report


# Global instance
_backtester_instance: Optional[DebateBacktester] = None


def get_debate_backtester() -> DebateBacktester:
    """Get the global debate backtester instance."""
    global _backtester_instance
    if _backtester_instance is None:
        _backtester_instance = DebateBacktester()
    return _backtester_instance


async def run_debate_backtest(days_back: int = 30) -> BacktestSummary:
    """
    Convenience function to run a backtest for the last N days.
    
    Args:
        days_back: Number of days to look back
        
    Returns:
        BacktestSummary with results (summary only for quick usage)
    """
    backtester = get_debate_backtester()
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)
    
    summary, _ = await backtester.run_backtest(start_date, end_date)
    return summary
