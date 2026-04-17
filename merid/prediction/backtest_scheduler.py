"""
Nightly Debate Backtest Scheduler
Automatically runs debate performance backtests and tracks trends over time.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import logging

from merid.prediction.debate_backtest import get_debate_backtester, run_debate_backtest
from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.backtest_scheduler")


@dataclass
class BacktestTrend:
    """Trend data for debate performance over time."""
    date: datetime
    avg_improvement_pct: float
    markets_with_improvement: int
    markets_with_negative_impact: int
    total_markets: int
    confidence_level: float


class NightlyBacktestScheduler:
    """Scheduler for nightly debate backtests and trend tracking."""
    
    def __init__(self):
        self.backtester = get_debate_backtester()
        self.slo_monitor = SLOMonitor.get_instance()
        self.trend_history: List[BacktestTrend] = []
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
    
    async def start_nightly_schedule(self, hour: int = 2, minute: int = 0):
        """
        Start the nightly backtest scheduler.
        
        Args:
            hour: Hour to run backtest (UTC) - default 2 AM
            minute: Minute to run backtest - default 0
        """
        if self.is_running:
            logger.warning("Nightly backtest scheduler already running")
            return
        
        self.is_running = True
        logger.info(f"Starting nightly backtest scheduler at {hour:02d}:{minute:02d} UTC")
        
        try:
            while self.is_running:
                # Calculate next run time
                now = datetime.now(timezone.utc)
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If next run is in the past, schedule for tomorrow
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                # Sleep until next run time
                sleep_seconds = (next_run - now).total_seconds()
                logger.info(f"Next nightly backtest scheduled for {next_run.isoformat()} (in {sleep_seconds/3600:.1f} hours)")
                
                await asyncio.sleep(sleep_seconds)
                
                # Run the nightly backtest
                if self.is_running:
                    await self._run_nightly_backtest()
                    
        except asyncio.CancelledError:
            logger.info("Nightly backtest scheduler cancelled")
        except Exception as e:
            logger.error(f"Error in nightly backtest scheduler: {e}")
        finally:
            self.is_running = False
    
    async def _run_nightly_backtest(self):
        """Execute the nightly backtest and track trends."""
        try:
            logger.info("Starting nightly debate backtest")
            start_time = time.time()
            
            # Run 7-day backtest for recent performance
            summary, results = await self.backtester.run_backtest(
                start_date=datetime.now(timezone.utc) - timedelta(days=7),
                end_date=datetime.now(timezone.utc),
                min_debates_per_symbol=1
            )
            
            duration = time.time() - start_time
            
            # Store trend data
            trend = BacktestTrend(
                date=datetime.now(timezone.utc),
                avg_improvement_pct=summary.avg_improvement_pct,
                markets_with_improvement=summary.markets_with_improvement,
                markets_with_negative_impact=summary.markets_with_negative_impact,
                total_markets=summary.total_markets,
                confidence_level=summary.confidence_level
            )
            
            self.trend_history.append(trend)
            
            # Keep only last 90 days of trends
            if len(self.trend_history) > 90:
                self.trend_history = self.trend_history[-90:]
            
            # Track SLO metrics
            self.slo_monitor.track_slo(
                metric_name="debate.backtest.nightly.duration",
                success=duration < 300,  # 5 minute threshold
                total=1,
                metadata={
                    "duration": duration,
                    "avg_improvement": summary.avg_improvement_pct,
                    "total_markets": summary.total_markets
                }
            )
            
            # Track performance trend
            if len(self.trend_history) >= 7:
                # Calculate 7-day trend
                recent_avg = sum(t.avg_improvement_pct for t in self.trend_history[-7:]) / 7
                older_avg = sum(t.avg_improvement_pct for t in self.trend_history[-14:-7]) / 7 if len(self.trend_history) >= 14 else recent_avg
                
                trend_direction = "improving" if recent_avg > older_avg else "declining" if recent_avg < older_avg else "stable"
                
                self.slo_monitor.track_slo(
                    metric_name="debate.backtest.performance_trend",
                    success=trend_direction == "improving",
                    total=1,
                    metadata={
                        "trend_direction": trend_direction,
                        "recent_7day_avg": recent_avg,
                        "previous_7day_avg": older_avg,
                        "trend_change": recent_avg - older_avg
                    }
                )
            
            logger.info(
                f"Nightly backtest completed: {summary.avg_improvement_pct:.2f}% avg improvement, "
                f"{summary.markets_with_improvement}/{summary.total_markets} markets improved, "
                f"duration: {duration:.1f}s"
            )
            
            # Alert on concerning trends
            await self._check_alert_conditions(summary, trend)
            
        except Exception as e:
            logger.error(f"Error running nightly backtest: {e}")
            self.slo_monitor.track_slo(
                metric_name="debate.backtest.nightly.error",
                success=False,
                total=1,
                metadata={"error": str(e)}
            )
    
    async def _check_alert_conditions(self, summary, trend: BacktestTrend):
        """Check for alert conditions and trigger notifications."""
        # Alert on high negative impact rate
        negative_impact_rate = trend.markets_with_negative_impact / trend.total_markets if trend.total_markets > 0 else 0.0
        
        if negative_impact_rate > 0.3:  # 30% negative impact threshold
            logger.warning(
                f"High negative impact rate detected: {negative_impact_rate:.1%} "
                f"({trend.markets_with_negative_impact}/{trend.total_markets} markets)"
            )
            
            self.slo_monitor.track_slo(
                metric_name="debate.backtest.alert.high_negative_impact",
                success=False,
                total=1,
                metadata={
                    "negative_impact_rate": negative_impact_rate,
                    "negative_markets": trend.markets_with_negative_impact,
                    "total_markets": trend.total_markets
                }
            )
        
        # Alert on declining performance
        if len(self.trend_history) >= 14:
            recent_avg = sum(t.avg_improvement_pct for t in self.trend_history[-7:]) / 7
            older_avg = sum(t.avg_improvement_pct for t in self.trend_history[-14:-7]) / 7
            
            if recent_avg < older_avg - 2.0:  # 2% decline threshold
                logger.warning(
                    f"Debate performance declining: {recent_avg:.2f}% vs {older_avg:.2f}% (7-day avg)"
                )
                
                self.slo_monitor.track_slo(
                    metric_name="debate.backtest.alert.performance_decline",
                    success=False,
                    total=1,
                    metadata={
                        "recent_avg": recent_avg,
                        "older_avg": older_avg,
                        "decline_amount": older_avg - recent_avg
                    }
                )
    
    def get_performance_trends(self, days: int = 30) -> List[BacktestTrend]:
        """Get performance trends for the last N days."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        return [t for t in self.trend_history if t.date >= cutoff_date]
    
    def get_latest_summary(self) -> Optional[BacktestTrend]:
        """Get the most recent backtest summary."""
        return self.trend_history[-1] if self.trend_history else None
    
    async def stop(self):
        """Stop the nightly scheduler."""
        self.is_running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Nightly backtest scheduler stopped")


# Global instance
_scheduler_instance: Optional[NightlyBacktestScheduler] = None


def get_backtest_scheduler() -> NightlyBacktestScheduler:
    """Get the global backtest scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = NightlyBacktestScheduler()
    return _scheduler_instance


async def start_nightly_backtests(hour: int = 2, minute: int = 0):
    """
    Start the nightly backtest scheduler.
    
    Args:
        hour: Hour to run backtest (UTC) - default 2 AM
        minute: Minute to run backtest - default 0
        
    Returns:
        The scheduler task for management
    """
    scheduler = get_backtest_scheduler()
    task = asyncio.create_task(scheduler.start_nightly_schedule(hour, minute))
    scheduler.task = task
    return task
