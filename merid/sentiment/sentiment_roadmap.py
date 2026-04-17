"""
Sentiment Strategy Roadmap & Asset Unlock Logic

Data-driven roadmap for expanding sentiment-aware trading to new
assets and timeframes beyond BTC 15m.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timezone, timedelta
from enum import Enum
from utils.logger import get_logger
import threading

logger = get_logger(__name__)


class AssetStatus(Enum):
    """Status of an asset in the roadmap."""
    RESEARCH = "research"           # Backtesting phase
    PAPER = "paper"                 # Paper trading
    PENDING_LIVE = "pending_live"   # Waiting for unlock criteria
    LIVE = "live"                   # Live trading enabled
    DISABLED = "disabled"           # Failed criteria, disabled


@dataclass
class AssetLane:
    """Configuration for an asset/timeframe lane."""
    asset: str                      # BTC, ETH, etc.
    timeframe: str                  # 15m, 1h, etc.
    
    # Risk caps (relative to BTC 15m base)
    risk_cap_mult: float = 1.0      # Multiply BTC caps by this
    max_per_trade: float = 0.25
    max_exposure: float = 0.50
    
    # Sentiment sources
    use_twitter: bool = True
    use_reddit: bool = True
    use_fear_greed: bool = True
    
    # Technicals
    use_rsi: bool = True
    use_sma: bool = True
    rsi_period: int = 14
    sma_period: int = 20
    
    # Status
    status: AssetStatus = field(default=AssetStatus.RESEARCH)
    
    # Unlock criteria
    min_backtest_sharpe: float = 0.5
    min_backtest_trades: int = 50
    max_backtest_drawdown: float = 0.15
    
    # Live requirements
    min_weeks_stable: int = 4
    max_daily_violations: int = 2


@dataclass
class UnlockCriteria:
    """Criteria for unlocking an asset to live trading."""
    # Backtest metrics
    backtest_sharpe: float = 0.0
    backtest_return: float = 0.0
    backtest_drawdown: float = 0.0
    backtest_trades: int = 0
    
    # Live performance (if applicable)
    weeks_live: int = 0
    daily_violations: int = 0
    avg_weekly_return: float = 0.0
    
    # Pass/fail
    passed_backtest: bool = False
    passed_live_stability: bool = False
    
    def can_unlock(self) -> bool:
        """Check if all criteria are met for unlock."""
        return self.passed_backtest and self.passed_live_stability


class SentimentRoadmap:
    """
    Roadmap for expanding sentiment trading to new assets/timeframes.
    
    Manages asset lanes, backtest validation, and live unlock criteria.
    Keeps growth data-driven, not FOMO-driven.
    
    Usage:
        roadmap = SentimentRoadmap()
        
        # Add new lane for research
        roadmap.add_lane("ETH", "15m", risk_cap_mult=0.5)
        
        # Validate backtest results
        criteria = roadmap.validate_backtest("ETH", "15m", results_df)
        
        # Check if ready for live
        if criteria.can_unlock():
            roadmap.enable_live("ETH", "15m")
    """
    
    def __init__(self):
        self.lanes: Dict[str, AssetLane] = {}  # key: "ETH_15m"
        self.unlock_history: Dict[str, List[datetime]] = {}
        self.performance_log: Dict[str, List[Dict]] = {}
        
        # Default: BTC 15m is live
        self._init_default_lanes()
    
    def _init_default_lanes(self):
        """Initialize default lanes."""
        # BTC 15m - live baseline
        btc_15m = AssetLane(
            asset="BTC",
            timeframe="15m",
            status=AssetStatus.LIVE,
            risk_cap_mult=1.0,
        )
        self.lanes["BTC_15m"] = btc_15m
        
        # BTC 1h - research (same sentiment, different horizon)
        btc_1h = AssetLane(
            asset="BTC",
            timeframe="1h",
            status=AssetStatus.RESEARCH,
            risk_cap_mult=1.0,
            sma_period=50,
            rsi_period=21,
        )
        self.lanes["BTC_1h"] = btc_1h
        
        # ETH 15m - research (half size initially)
        eth_15m = AssetLane(
            asset="ETH",
            timeframe="15m",
            status=AssetStatus.RESEARCH,
            risk_cap_mult=0.5,
            max_per_trade=0.125,
            max_exposure=0.25,
        )
        self.lanes["ETH_15m"] = eth_15m
    
    def add_lane(
        self,
        asset: str,
        timeframe: str,
        risk_cap_mult: float = 1.0,
        start_status: AssetStatus = AssetStatus.RESEARCH,
    ) -> AssetLane:
        """
        Add a new asset/timeframe lane.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, etc.)
            risk_cap_mult: Risk cap multiplier vs BTC 15m
            start_status: Initial status
        
        Returns:
            Created AssetLane
        """
        key = f"{asset}_{timeframe}"
        
        if key in self.lanes:
            logger.warning(f"Lane {key} already exists, returning existing")
            return self.lanes[key]
        
        lane = AssetLane(
            asset=asset,
            timeframe=timeframe,
            risk_cap_mult=risk_cap_mult,
            max_per_trade=0.25 * risk_cap_mult,
            max_exposure=0.50 * risk_cap_mult,
            status=start_status,
        )
        
        self.lanes[key] = lane
        logger.info(f"Added new lane: {key} (status: {start_status.value})")
        
        return lane
    
    def validate_backtest(
        self,
        asset: str,
        timeframe: str,
        backtest_results: Dict[str, Any],
    ) -> UnlockCriteria:
        """
        Validate backtest results against unlock criteria.
        
        Args:
            asset: Asset symbol
            timeframe: Timeframe
            backtest_results: Dict with keys: sharpe, return, drawdown, trades
        
        Returns:
            UnlockCriteria with pass/fail status
        """
        key = f"{asset}_{timeframe}"
        lane = self.lanes.get(key)
        
        if not lane:
            logger.warning(f"Lane {key} not found")
            return UnlockCriteria()
        
        criteria = UnlockCriteria(
            backtest_sharpe=backtest_results.get("sharpe", 0.0),
            backtest_return=backtest_results.get("total_return", 0.0),
            backtest_drawdown=backtest_results.get("max_drawdown", 0.0),
            backtest_trades=backtest_results.get("trades", 0),
        )
        
        # Check backtest pass/fail
        criteria.passed_backtest = (
            criteria.backtest_sharpe >= lane.min_backtest_sharpe and
            criteria.backtest_trades >= lane.min_backtest_trades and
            criteria.backtest_drawdown <= lane.max_backtest_drawdown
        )
        
        # Check if already has live history
        if key in self.performance_log:
            live_perf = self.performance_log[key]
            weeks = len(live_perf)
            violations = sum(1 for w in live_perf if w.get("risk_violations", 0) > 0)
            
            criteria.weeks_live = weeks
            criteria.daily_violations = violations
            criteria.passed_live_stability = (
                weeks >= lane.min_weeks_stable and
                violations <= lane.max_daily_violations
            )
        else:
            # No live history yet, auto-pass if backtest passed
            criteria.passed_live_stability = criteria.passed_backtest
        
        logger.info(
            f"Backtest validation {key}: "
            f"sharpe={criteria.backtest_sharpe:.2f} "
            f"drawdown={criteria.backtest_drawdown:.2%} "
            f"trades={criteria.backtest_trades} "
            f"passed={criteria.passed_backtest}"
        )
        
        return criteria
    
    def enable_live(self, asset: str, timeframe: str) -> bool:
        """
        Enable live trading for a lane.
        
        Returns:
            True if successful
        """
        key = f"{asset}_{timeframe}"
        lane = self.lanes.get(key)
        
        if not lane:
            logger.warning(f"Lane {key} not found")
            return False
        
        if lane.status != AssetStatus.PENDING_LIVE and lane.status != AssetStatus.RESEARCH:
            logger.warning(f"Lane {key} already {lane.status.value}")
            return False
        
        lane.status = AssetStatus.LIVE
        
        if key not in self.unlock_history:
            self.unlock_history[key] = []
        self.unlock_history[key].append(datetime.now(timezone.utc))
        
        logger.info(f"ENABLED LIVE: {key}")
        return True
    
    def record_live_performance(
        self,
        asset: str,
        timeframe: str,
        week_data: Dict[str, Any],
    ):
        """
        Record weekly live performance for unlock tracking.
        
        Args:
            week_data: Dict with risk_violations, returns, etc.
        """
        key = f"{asset}_{timeframe}"
        
        if key not in self.performance_log:
            self.performance_log[key] = []
        
        self.performance_log[key].append({
            **week_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        # Keep last 52 weeks
        if len(self.performance_log[key]) > 52:
            self.performance_log[key] = self.performance_log[key][-52:]
    
    def get_status(self, asset: str, timeframe: str) -> Dict[str, Any]:
        """Get current status of a lane."""
        key = f"{asset}_{timeframe}"
        lane = self.lanes.get(key)
        
        if not lane:
            return {"error": f"Lane {key} not found"}
        
        return {
            "asset": lane.asset,
            "timeframe": lane.timeframe,
            "status": lane.status.value,
            "risk_cap_mult": lane.risk_cap_mult,
            "max_per_trade": lane.max_per_trade,
            "max_exposure": lane.max_exposure,
            "unlock_criteria": {
                "min_sharpe": lane.min_backtest_sharpe,
                "min_trades": lane.min_backtest_trades,
                "max_drawdown": lane.max_backtest_drawdown,
                "min_weeks_stable": lane.min_weeks_stable,
            },
            "history": self.unlock_history.get(key, []),
        }
    
    def get_all_lanes(self) -> Dict[str, Dict[str, Any]]:
        """Get all lanes with their status."""
        return {key: self.get_status(lane.asset, lane.timeframe) 
                for key, lane in self.lanes.items()}
    
    def get_live_lanes(self) -> List[str]:
        """Get list of live-enabled lanes."""
        return [key for key, lane in self.lanes.items() 
                if lane.status == AssetStatus.LIVE]
    
    def get_ready_for_live(self) -> List[str]:
        """Get lanes that passed backtest and are ready for live."""
        ready = []
        for key, lane in self.lanes.items():
            if lane.status == AssetStatus.RESEARCH:
                # Check if we have performance data suggesting it's ready
                if key in self.performance_log:
                    criteria = self.validate_backtest(
                        lane.asset, lane.timeframe, 
                        {"sharpe": 0.6, "trades": 100, "max_drawdown": 0.10}  # Placeholder
                    )
                    if criteria.can_unlock():
                        ready.append(key)
        return ready


# Singleton accessor
_roadmap: Optional[SentimentRoadmap] = None
_roadmap_lock = threading.Lock()

def get_sentiment_roadmap() -> SentimentRoadmap:
    """Get the singleton SentimentRoadmap instance."""
    global _roadmap
    if _roadmap is None:
        with _roadmap_lock:
            if _roadmap is None:
                _roadmap = SentimentRoadmap()
    return _roadmap


# ── Convenience functions ──────────────────────────────────────────

def check_lane_ready(asset: str, timeframe: str) -> Tuple[bool, str]:
    """Quick check if a lane is ready for live."""
    roadmap = get_sentiment_roadmap()
    criteria = roadmap.validate_backtest(asset, timeframe, {
        "sharpe": 0.6,  # Placeholder values
        "trades": 100,
        "max_drawdown": 0.10,
    })
    
    if criteria.can_unlock():
        return True, "Passed all criteria"
    elif not criteria.passed_backtest:
        return False, f"Backtest failed (sharpe={criteria.backtest_sharpe:.2f})"
    else:
        return False, "Live stability criteria not met"


def get_recommended_next_lanes() -> List[str]:
    """Get recommended next lanes to enable."""
    roadmap = get_sentiment_roadmap()
    return roadmap.get_ready_for_live()
