"""
MERID-ARCHIVE Strategy Autopsy Reports

Post-mortem analysis of strategies that:
- Lost money
- Underperformed expectations
- Were disabled or abandoned

This is how MERID learns from mistakes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("archive.strategy_autopsy")


class StrategyOutcome(Enum):
    """Outcome of a strategy."""
    PROFITABLE = "profitable"
    BREAK_EVEN = "break_even"
    LOSS = "loss"
    ABANDONED = "abandoned"
    DISABLED = "disabled"


class FailureCategory(Enum):
    """Categories of strategy failure."""
    MARKET_REGIME_CHANGE = "market_regime_change"
    OVERFITTING = "overfitting"
    EXECUTION_FAILURE = "execution_failure"
    RISK_LIMIT_HIT = "risk_limit_hit"
    LIQUIDITY_ISSUE = "liquidity_issue"
    DATA_QUALITY = "data_quality"
    MODEL_DECAY = "model_decay"
    BLACK_SWAN = "black_swan"
    HUMAN_ERROR = "human_error"
    UNKNOWN = "unknown"


@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    
    def calculate_metrics(self) -> None:
        """Calculate derived metrics."""
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
        
        if self.winning_trades > 0:
            self.avg_win = self.gross_profit / self.winning_trades
        
        if self.losing_trades > 0:
            self.avg_loss = abs(self.gross_loss) / self.losing_trades
        
        if self.gross_loss != 0:
            self.profit_factor = abs(self.gross_profit / self.gross_loss)
        
        self.net_pnl = self.gross_profit + self.gross_loss
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "net_pnl": round(self.net_pnl, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "win_rate": round(self.win_rate, 3),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 3),
        }


@dataclass
class StrategyAutopsy:
    """Post-mortem analysis of a strategy."""
    autopsy_id: str
    strategy_id: str
    strategy_name: str
    
    # Timeline
    start_date: float
    end_date: float
    duration_days: float
    
    # Outcome
    outcome: StrategyOutcome
    failure_category: Optional[FailureCategory] = None
    
    # Performance
    performance: StrategyPerformance = field(default_factory=StrategyPerformance)
    
    # Analysis
    what_happened: str = ""
    why_it_failed: str = ""
    contributing_factors: List[str] = field(default_factory=list)
    market_conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Lessons
    lessons_learned: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    should_retry: bool = False
    retry_conditions: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "autopsy_id": self.autopsy_id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "duration_days": round(self.duration_days, 1),
            "outcome": self.outcome.value,
            "failure_category": self.failure_category.value if self.failure_category else None,
            "performance": self.performance.to_dict(),
            "what_happened": self.what_happened,
            "why_it_failed": self.why_it_failed,
            "contributing_factors": self.contributing_factors,
            "market_conditions": self.market_conditions,
            "lessons_learned": self.lessons_learned,
            "recommendations": self.recommendations,
            "should_retry": self.should_retry,
            "retry_conditions": self.retry_conditions,
            "created_at": self.created_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
        }


class StrategyAutopsyEngine:
    """
    Generates and manages strategy autopsy reports.
    
    "Those who cannot remember the past are condemned to repeat it."
    """
    
    # Common failure patterns and their indicators
    FAILURE_PATTERNS = {
        FailureCategory.OVERFITTING: [
            "Backtest performance much better than live",
            "Strategy worked in specific period only",
            "Too many parameters",
            "Curve-fitted to historical data",
        ],
        FailureCategory.MARKET_REGIME_CHANGE: [
            "Volatility regime changed",
            "Correlation structure changed",
            "Liquidity conditions changed",
            "New market participants",
        ],
        FailureCategory.EXECUTION_FAILURE: [
            "Slippage higher than expected",
            "Fills worse than simulated",
            "Latency issues",
            "Order rejection",
        ],
        FailureCategory.MODEL_DECAY: [
            "Alpha decayed over time",
            "Edge eroded gradually",
            "More competition",
            "Signal became crowded",
        ],
    }
    
    def __init__(self):
        self._autopsies: Dict[str, StrategyAutopsy] = {}
        self._autopsy_count = 0
        self._lessons_database: List[Dict[str, Any]] = []
        
        logger.info("Strategy autopsy engine initialized")
    
    def create_autopsy(
        self,
        strategy_id: str,
        strategy_name: str,
        start_date: float,
        end_date: float,
        outcome: StrategyOutcome,
        performance: Optional[StrategyPerformance] = None,
    ) -> StrategyAutopsy:
        """Create a new strategy autopsy."""
        self._autopsy_count += 1
        autopsy_id = f"autopsy_{strategy_id}_{self._autopsy_count}"
        
        autopsy = StrategyAutopsy(
            autopsy_id=autopsy_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            duration_days=(end_date - start_date) / 86400,
            outcome=outcome,
            performance=performance or StrategyPerformance(),
        )
        
        # Auto-analyze if loss
        if outcome == StrategyOutcome.LOSS:
            self._auto_analyze(autopsy)
        
        self._autopsies[autopsy_id] = autopsy
        
        logger.info(
            "Created autopsy %s for strategy %s (outcome: %s)",
            autopsy_id, strategy_name, outcome.value
        )
        
        return autopsy
    
    def _auto_analyze(self, autopsy: StrategyAutopsy) -> None:
        """Auto-generate analysis based on performance metrics."""
        perf = autopsy.performance
        perf.calculate_metrics()
        
        # Determine failure category
        if perf.win_rate < 0.3 and perf.total_trades > 20:
            autopsy.failure_category = FailureCategory.OVERFITTING
            autopsy.why_it_failed = "Win rate significantly below expectations, likely overfitted to historical data"
        elif perf.max_drawdown > abs(perf.net_pnl) * 2:
            autopsy.failure_category = FailureCategory.RISK_LIMIT_HIT
            autopsy.why_it_failed = "Drawdown exceeded acceptable limits before strategy could recover"
        elif perf.profit_factor < 0.5 and perf.total_trades < 10:
            autopsy.failure_category = FailureCategory.EXECUTION_FAILURE
            autopsy.why_it_failed = "Poor execution on limited trades suggests execution issues"
        elif autopsy.duration_days > 30 and perf.net_pnl < 0:
            autopsy.failure_category = FailureCategory.MODEL_DECAY
            autopsy.why_it_failed = "Gradual loss over extended period suggests alpha decay"
        else:
            autopsy.failure_category = FailureCategory.UNKNOWN
            autopsy.why_it_failed = "Requires manual analysis to determine root cause"
        
        # Generate what happened
        autopsy.what_happened = (
            f"Strategy ran for {autopsy.duration_days:.0f} days with {perf.total_trades} trades. "
            f"Win rate: {perf.win_rate:.1%}, Net P&L: ${perf.net_pnl:,.2f}, "
            f"Max drawdown: ${perf.max_drawdown:,.2f}"
        )
        
        # Add contributing factors
        if perf.avg_loss > perf.avg_win * 2:
            autopsy.contributing_factors.append("Average loss much larger than average win")
        if perf.losing_trades > perf.winning_trades * 2:
            autopsy.contributing_factors.append("Too many losing trades")
        if perf.max_drawdown > 1000:
            autopsy.contributing_factors.append("Large drawdown eroded capital")
        
        # Generate lessons
        autopsy.lessons_learned = self._generate_lessons(autopsy)
        
        # Generate recommendations
        autopsy.recommendations = self._generate_recommendations(autopsy)
    
    def _generate_lessons(self, autopsy: StrategyAutopsy) -> List[str]:
        """Generate lessons learned from the autopsy."""
        lessons = []
        
        if autopsy.failure_category == FailureCategory.OVERFITTING:
            lessons.extend([
                "Use out-of-sample testing more rigorously",
                "Reduce number of strategy parameters",
                "Test across multiple market regimes",
            ])
        elif autopsy.failure_category == FailureCategory.MODEL_DECAY:
            lessons.extend([
                "Monitor strategy performance decay continuously",
                "Set automatic disable thresholds",
                "Diversify across uncorrelated strategies",
            ])
        elif autopsy.failure_category == FailureCategory.EXECUTION_FAILURE:
            lessons.extend([
                "Account for realistic slippage in backtests",
                "Test with smaller position sizes first",
                "Monitor execution quality metrics",
            ])
        elif autopsy.failure_category == FailureCategory.RISK_LIMIT_HIT:
            lessons.extend([
                "Set tighter stop losses",
                "Reduce position sizing",
                "Implement drawdown-based scaling",
            ])
        
        return lessons
    
    def _generate_recommendations(self, autopsy: StrategyAutopsy) -> List[str]:
        """Generate recommendations based on the autopsy."""
        recommendations = []
        perf = autopsy.performance
        
        if perf.win_rate < 0.4:
            recommendations.append("Improve entry signal quality before retrying")
        
        if perf.profit_factor < 1.0:
            recommendations.append("Strategy is not profitable - do not retry without major changes")
            autopsy.should_retry = False
        elif perf.profit_factor < 1.5:
            recommendations.append("Marginal profitability - consider if edge is worth the risk")
            autopsy.should_retry = True
            autopsy.retry_conditions = [
                "Market conditions similar to profitable period",
                "Reduced position size",
                "Tighter risk limits",
            ]
        
        if autopsy.failure_category == FailureCategory.MARKET_REGIME_CHANGE:
            recommendations.append("Wait for market regime to return to favorable conditions")
            autopsy.should_retry = True
            autopsy.retry_conditions = [
                "Volatility returns to historical average",
                "Correlation structure normalizes",
            ]
        
        return recommendations
    
    def add_lesson(
        self,
        autopsy_id: str,
        lesson: str,
    ) -> bool:
        """Add a lesson to an autopsy."""
        autopsy = self._autopsies.get(autopsy_id)
        if not autopsy:
            return False
        
        autopsy.lessons_learned.append(lesson)
        
        # Also add to lessons database
        self._lessons_database.append({
            "lesson": lesson,
            "strategy_id": autopsy.strategy_id,
            "failure_category": autopsy.failure_category.value if autopsy.failure_category else None,
            "timestamp": time.time(),
        })
        
        return True
    
    def mark_reviewed(
        self,
        autopsy_id: str,
        reviewer: str,
    ) -> bool:
        """Mark an autopsy as reviewed."""
        autopsy = self._autopsies.get(autopsy_id)
        if not autopsy:
            return False
        
        autopsy.reviewed_by = reviewer
        autopsy.reviewed_at = time.time()
        return True
    
    def get_autopsy(self, autopsy_id: str) -> Optional[StrategyAutopsy]:
        """Get an autopsy by ID."""
        return self._autopsies.get(autopsy_id)
    
    def get_autopsies_by_strategy(self, strategy_id: str) -> List[StrategyAutopsy]:
        """Get all autopsies for a strategy."""
        return [a for a in self._autopsies.values() if a.strategy_id == strategy_id]
    
    def get_autopsies_by_category(self, category: FailureCategory) -> List[StrategyAutopsy]:
        """Get autopsies by failure category."""
        return [a for a in self._autopsies.values() if a.failure_category == category]
    
    def get_all_lessons(self) -> List[Dict[str, Any]]:
        """Get all lessons from the database."""
        return self._lessons_database.copy()
    
    def get_lessons_by_category(self, category: FailureCategory) -> List[str]:
        """Get lessons for a specific failure category."""
        return [
            l["lesson"] for l in self._lessons_database
            if l.get("failure_category") == category.value
        ]
    
    def get_failure_statistics(self) -> Dict[str, Any]:
        """Get statistics on strategy failures."""
        autopsies = list(self._autopsies.values())
        
        if not autopsies:
            return {"total": 0}
        
        by_outcome = {}
        for outcome in StrategyOutcome:
            by_outcome[outcome.value] = sum(1 for a in autopsies if a.outcome == outcome)
        
        by_category = {}
        for category in FailureCategory:
            by_category[category.value] = sum(1 for a in autopsies if a.failure_category == category)
        
        losses = [a for a in autopsies if a.outcome == StrategyOutcome.LOSS]
        total_loss = sum(a.performance.net_pnl for a in losses)
        
        return {
            "total": len(autopsies),
            "by_outcome": by_outcome,
            "by_failure_category": by_category,
            "total_loss_usd": round(total_loss, 2),
            "avg_duration_days": sum(a.duration_days for a in autopsies) / len(autopsies),
            "reviewed_count": sum(1 for a in autopsies if a.reviewed_at),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        return {
            "total_autopsies": len(self._autopsies),
            "total_lessons": len(self._lessons_database),
            "failure_statistics": self.get_failure_statistics(),
            "unreviewed_count": sum(1 for a in self._autopsies.values() if not a.reviewed_at),
        }
    
    def get_all_autopsies(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all autopsies."""
        autopsies = sorted(
            self._autopsies.values(),
            key=lambda x: x.created_at,
            reverse=True
        )[:limit]
        return [a.to_dict() for a in autopsies]


# Singleton
_autopsy_engine: Optional[StrategyAutopsyEngine] = None


def get_strategy_autopsy() -> StrategyAutopsyEngine:
    """Get the singleton strategy autopsy engine."""
    global _autopsy_engine
    if _autopsy_engine is None:
        _autopsy_engine = StrategyAutopsyEngine()
    return _autopsy_engine
