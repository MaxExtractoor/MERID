"""
YES/NO skew monitoring and alerting.

CRITICAL FIX (2026-07-22): This module monitors YES/NO trade distribution
to detect any structural bias that might indicate threshold inversion or
other side-selection bugs.

The monitor tracks:
- Per-asset YES/NO trade counts
- Overall YES/NO distribution
- Skew ratio over time windows
- Alerts when skew exceeds thresholds
"""

import time
import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from threading import Lock
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class SkewMetrics:
    """Metrics for YES/NO skew monitoring."""
    yes_count: int = 0
    no_count: int = 0
    total_trades: int = 0
    skew_ratio: float = 0.0  # yes_count / no_count
    window_start: float = field(default_factory=time.time)
    
    @property
    def yes_pct(self) -> float:
        """Percentage of trades that are YES."""
        if self.total_trades == 0:
            return 0.0
        return (self.yes_count / self.total_trades) * 100.0
    
    @property
    def no_pct(self) -> float:
        """Percentage of trades that are NO."""
        if self.total_trades == 0:
            return 0.0
        return (self.no_count / self.total_trades) * 100.0


class YesNoSkewMonitor:
    """
    Monitor YES/NO trade distribution to detect structural bias.
    
    Singleton instance tracks trades across all assets and time windows,
    alerting when skew exceeds healthy thresholds.
    """
    
    _instance: Optional['YesNoSkewMonitor'] = None
    _lock: Lock = Lock()
    
    # Skew thresholds for alerting
    WARNING_SKEW = 2.0  # YES/NO ratio > 2.0 triggers warning
    CRITICAL_SKEW = 4.0  # YES/NO ratio > 4.0 triggers critical alert
    
    # Time window for skew calculation (seconds)
    WINDOW_SIZE = 3600  # 1 hour
    
    def __new__(cls) -> 'YesNoSkewMonitor':
        """Singleton pattern to ensure single monitor instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the skew monitor."""
        if self._initialized:
            return
        
        self._initialized = True
        
        # Per-asset trade tracking
        self._asset_trades: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"yes": 0, "no": 0}
        )
        
        # Overall trade tracking
        self._overall_trades: Dict[str, int] = {"yes": 0, "no": 0}
        
        # Time-windowed tracking (deque of (timestamp, side) tuples)
        self._trade_history: deque = deque()
        
        # Alert state
        self._last_alert_time: float = 0.0
        self._alert_cooldown: float = 300  # 5 minutes between alerts
        
        logger.info("[YES-NO-SKEW-MONITOR] Initialized skew monitor")
    
    def record_trade(self, asset: str, side: str, price_cents: int = 0) -> None:
        """
        Record a trade for skew monitoring.
        
        Args:
            asset: Asset ticker (e.g., "BTC", "ETH")
            side: Trade side ("yes" or "no")
            price_cents: Trade price in cents (optional, for diagnostics)
        """
        if side not in ("yes", "no"):
            logger.warning(f"[YES-NO-SKEW-MONITOR] Invalid side '{side}', expected 'yes' or 'no'")
            return
        
        with self._lock:
            # Record per-asset
            self._asset_trades[asset][side] += 1
            
            # Record overall
            self._overall_trades[side] += 1
            
            # Record in history with timestamp
            self._trade_history.append((time.time(), side, asset, price_cents))
            
            # Prune old trades outside window
            self._prune_old_trades()
            
            # Check for skew after recording
            self._check_skew()
    
    def _prune_old_trades(self) -> None:
        """Remove trades older than the time window."""
        cutoff_time = time.time() - self.WINDOW_SIZE
        while self._trade_history and self._trade_history[0][0] < cutoff_time:
            timestamp, side, asset, price_cents = self._trade_history.popleft()
            # Decrement counters
            self._asset_trades[asset][side] = max(0, self._asset_trades[asset][side] - 1)
            self._overall_trades[side] = max(0, self._overall_trades[side] - 1)
    
    def _check_skew(self) -> None:
        """Check if skew exceeds thresholds and alert if needed."""
        # Skip if not enough trades
        if self._overall_trades["yes"] + self._overall_trades["no"] < 10:
            return
        
        # Calculate skew ratio
        yes_count = self._overall_trades["yes"]
        no_count = self._overall_trades["no"]
        
        if no_count == 0:
            skew_ratio = float('inf')
        else:
            skew_ratio = yes_count / no_count
        
        # Check alert cooldown
        if time.time() - self._last_alert_time < self._alert_cooldown:
            return
        
        # Critical alert
        if skew_ratio >= self.CRITICAL_SKEW:
            self._alert_critical(skew_ratio, yes_count, no_count)
            self._last_alert_time = time.time()
        
        # Warning alert
        elif skew_ratio >= self.WARNING_SKEW:
            self._alert_warning(skew_ratio, yes_count, no_count)
            self._last_alert_time = time.time()
    
    def _alert_critical(self, skew_ratio: float, yes_count: int, no_count: int) -> None:
        """Issue critical skew alert."""
        logger.critical(
            f"[YES-NO-SKEW-ALERT] CRITICAL: YES/NO skew ratio = {skew_ratio:.2f} "
            f"(YES={yes_count}, NO={no_count}). "
            f"This indicates structural YES-side bias - check threshold configuration!"
        )
        
        # Log per-asset breakdown
        for asset, counts in sorted(self._asset_trades.items()):
            if counts["yes"] + counts["no"] > 0:
                asset_skew = counts["yes"] / max(1, counts["no"])
                logger.warning(
                    f"[YES-NO-SKEW-ALERT] Asset {asset}: YES={counts['yes']}, "
                    f"NO={counts['no']}, skew={asset_skew:.2f}"
                )
    
    def _alert_warning(self, skew_ratio: float, yes_count: int, no_count: int) -> None:
        """Issue warning skew alert."""
        logger.warning(
            f"[YES-NO-SKEW-ALERT] WARNING: YES/NO skew ratio = {skew_ratio:.2f} "
            f"(YES={yes_count}, NO={no_count}). "
            f"Monitor for threshold inversion or side-selection bias."
        )
    
    def get_metrics(self) -> SkewMetrics:
        """Get current skew metrics."""
        with self._lock:
            yes_count = self._overall_trades["yes"]
            no_count = self._overall_trades["no"]
            total = yes_count + no_count
            
            if no_count == 0:
                skew_ratio = float('inf') if yes_count > 0 else 0.0
            else:
                skew_ratio = yes_count / no_count
            
            return SkewMetrics(
                yes_count=yes_count,
                no_count=no_count,
                total_trades=total,
                skew_ratio=skew_ratio,
                window_start=time.time() - self.WINDOW_SIZE
            )
    
    def get_asset_metrics(self, asset: str) -> Dict[str, int]:
        """Get trade counts for a specific asset."""
        with self._lock:
            return dict(self._asset_trades.get(asset, {"yes": 0, "no": 0}))
    
    def get_all_asset_metrics(self) -> Dict[str, Dict[str, int]]:
        """Get trade counts for all assets."""
        with self._lock:
            return {asset: dict(counts) for asset, counts in self._asset_trades.items()}
    
    def reset_metrics(self) -> None:
        """Reset all metrics (for testing or after config changes)."""
        with self._lock:
            self._asset_trades.clear()
            self._overall_trades = {"yes": 0, "no": 0}
            self._trade_history.clear()
            self._last_alert_time = 0.0
        
        logger.info("[YES-NO-SKEW-MONITOR] Metrics reset")
    
    def get_skew_summary(self) -> str:
        """Get a human-readable summary of current skew state."""
        metrics = self.get_metrics()
        
        summary = (
            f"YES/NO Skew Summary (last {self.WINDOW_SIZE//60} min):\n"
            f"  Total Trades: {metrics.total_trades}\n"
            f"  YES: {metrics.yes_count} ({metrics.yes_pct:.1f}%)\n"
            f"  NO: {metrics.no_count} ({metrics.no_pct:.1f}%)\n"
            f"  Skew Ratio: {metrics.skew_ratio:.2f}\n"
        )
        
        if metrics.skew_ratio >= self.CRITICAL_SKEW:
            summary += "  Status: CRITICAL (structural YES bias detected)\n"
        elif metrics.skew_ratio >= self.WARNING_SKEW:
            summary += "  Status: WARNING (monitor for bias)\n"
        else:
            summary += "  Status: OK (balanced distribution)\n"
        
        return summary


def get_yes_no_skew_monitor() -> YesNoSkewMonitor:
    """Get the singleton YES/NO skew monitor instance."""
    return YesNoSkewMonitor()
