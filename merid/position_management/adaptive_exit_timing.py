"""
Adaptive exit timing for optimal expiry selection.

Research: ML-based optimal expiry selection maximizes risk-adjusted returns
by dynamically selecting the best contract expiry based on market conditions.

Current implementation: Rule-based adaptive timing using historical performance
data to adjust exit timing. Future: ML model for optimal expiry prediction.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, List
import statistics


@dataclass
class ExitTimingRecord:
    """Record of past exit timing performance."""
    market_id: str
    entry_time: datetime
    exit_time: datetime
    hold_duration_seconds: float
    entry_price_cents: int
    exit_price_cents: int
    side: str  # "yes" or "no"
    pnl_cents: int
    r_multiple: float
    exit_reason: str
    
    @property
    def hold_duration_minutes(self) -> float:
        """Hold duration in minutes."""
        return self.hold_duration_seconds / 60.0


@dataclass
class AdaptiveExitConfig:
    """Configuration for adaptive exit timing."""
    min_hold_seconds: float = 60.0  # Minimum 1 minute
    max_hold_seconds: float = 900.0  # Maximum 15 minutes
    lookback_records: int = 50  # Number of past records to analyze
    performance_threshold: float = 0.5  # R-multiple threshold for "good" exit


class AdaptiveExitTiming:
    """
    Adaptive exit timing using historical performance data.
    
    Analyzes past exit performance to determine optimal hold times
    for different market conditions and asset classes.
    """
    
    def __init__(self, config: Optional[AdaptiveExitConfig] = None):
        """
        Initialize adaptive exit timing.
        
        Args:
            config: Configuration for adaptive timing
        """
        self._config = config or AdaptiveExitConfig()
        self._records: Dict[str, List[ExitTimingRecord]] = {}  # market_id -> records
        self._lock = None  # Thread lock for concurrent access
    
    def add_record(self, record: ExitTimingRecord) -> None:
        """
        Add an exit timing record for analysis.
        
        Args:
            record: Exit timing record
        """
        market_id = record.market_id
        if market_id not in self._records:
            self._records[market_id] = []
        
        self._records[market_id].append(record)
        
        # Keep only the most recent records
        if len(self._records[market_id]) > self._config.lookback_records:
            self._records[market_id] = self._records[market_id][-self._config.lookback_records:]
    
    def get_optimal_hold_time(
        self,
        market_id: str,
        side: str,
        current_r_multiple: float
    ) -> float:
        """
        Get optimal hold time based on historical performance.
        
        Args:
            market_id: Market identifier
            side: Position side ("yes" or "no")
            current_r_multiple: Current R-multiple of position
            
        Returns:
            Optimal hold time in seconds
        """
        if market_id not in self._records or len(self._records[market_id]) < 10:
            # Not enough data, use default
            return self._config.max_hold_seconds
        
        # Filter records by side
        side_records = [
            r for r in self._records[market_id]
            if r.side == side
        ]
        
        if len(side_records) < 10:
            return self._config.max_hold_seconds
        
        # Analyze performance by hold duration buckets
        # Bucket 1: 0-3 minutes
        # Bucket 2: 3-6 minutes
        # Bucket 3: 6-9 minutes
        # Bucket 4: 9-12 minutes
        # Bucket 5: 12-15 minutes
        
        buckets = {
            "0-3": [],
            "3-6": [],
            "6-9": [],
            "9-12": [],
            "12-15": []
        }
        
        for record in side_records:
            duration_min = record.hold_duration_minutes
            if duration_min < 3:
                buckets["0-3"].append(record.r_multiple)
            elif duration_min < 6:
                buckets["3-6"].append(record.r_multiple)
            elif duration_min < 9:
                buckets["6-9"].append(record.r_multiple)
            elif duration_min < 12:
                buckets["9-12"].append(record.r_multiple)
            else:
                buckets["12-15"].append(record.r_multiple)
        
        # Find bucket with best average performance
        best_bucket = None
        best_avg_r = -float('inf')
        
        for bucket_name, r_multiples in buckets.items():
            if len(r_multiples) >= 3:  # Need at least 3 samples
                avg_r = statistics.mean(r_multiples)
                if avg_r > best_avg_r:
                    best_avg_r = avg_r
                    best_bucket = bucket_name
        
        if best_bucket:
            # Map bucket to hold time (use midpoint of bucket)
            bucket_mapping = {
                "0-3": 90,      # 1.5 minutes
                "3-6": 270,     # 4.5 minutes
                "6-9": 450,     # 7.5 minutes
                "9-12": 630,    # 10.5 minutes
                "12-15": 810    # 13.5 minutes
            }
            optimal_hold = bucket_mapping.get(best_bucket, self._config.max_hold_seconds)
            
            # Adjust based on current R-multiple
            # If already profitable, reduce hold time to lock in gains
            if current_r_multiple > 0.5:
                optimal_hold *= 0.7  # Reduce by 30%
            elif current_r_multiple > 1.0:
                optimal_hold *= 0.5  # Reduce by 50%
            
            # Clamp to config limits
            optimal_hold = max(
                self._config.min_hold_seconds,
                min(self._config.max_hold_seconds, optimal_hold)
            )
            
            return optimal_hold
        
        return self._config.max_hold_seconds
    
    def should_exit_early(
        self,
        market_id: str,
        side: str,
        hold_duration_seconds: float,
        current_r_multiple: float
    ) -> bool:
        """
        Determine if position should exit early based on adaptive timing.
        
        Args:
            market_id: Market identifier
            side: Position side ("yes" or "no")
            hold_duration_seconds: Current hold duration
            current_r_multiple: Current R-multiple
            
        Returns:
            True if should exit early
        """
        optimal_hold = self.get_optimal_hold_time(market_id, side, current_r_multiple)
        
        # Exit early if we've exceeded optimal hold time
        if hold_duration_seconds > optimal_hold:
            return True
        
        # Exit early if we're profitable and optimal hold time is short
        if current_r_multiple > 0.5 and optimal_hold < 300:  # Less than 5 minutes
            return True
        
        return False
    
    def get_performance_stats(self, market_id: str) -> Dict:
        """
        Get performance statistics for a market.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Dictionary with performance statistics
        """
        if market_id not in self._records:
            return {}
        
        records = self._records[market_id]
        if not records:
            return {}
        
        r_multiples = [r.r_multiple for r in records]
        hold_durations = [r.hold_duration_minutes for r in records]
        
        return {
            "total_exits": len(records),
            "avg_r_multiple": statistics.mean(r_multiples) if r_multiples else 0,
            "median_r_multiple": statistics.median(r_multiples) if r_multiples else 0,
            "avg_hold_minutes": statistics.mean(hold_durations) if hold_durations else 0,
            "win_rate": sum(1 for r in r_multiples if r > 0) / len(r_multiples) if r_multiples else 0,
        }


def get_adaptive_exit_timing() -> AdaptiveExitTiming:
    """Get singleton adaptive exit timing instance."""
    if not hasattr(get_adaptive_exit_timing, "_instance"):
        get_adaptive_exit_timing._instance = AdaptiveExitTiming()
    return get_adaptive_exit_timing._instance
