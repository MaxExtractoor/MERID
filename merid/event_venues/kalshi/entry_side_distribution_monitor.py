"""
Entry Side Distribution Monitor for YES Bias Detection.

This module tracks the distribution of YES vs NO entries per asset over time windows.
A healthy system should have a balanced mix of YES and NO entries in mixed regimes.
A 95-100% YES share indicates structural YES bias.

Usage:
    from merid.event_venues.kalshi.entry_side_distribution_monitor import get_entry_side_distribution_monitor
    monitor = get_entry_side_distribution_monitor()
    monitor.record_entry(asset="BTC", side="yes", strategy_intent="bullish_event")
    monitor.record_entry(asset="BTC", side="no", strategy_intent="bearish_event")
    stats = monitor.get_distribution_stats()
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import threading

logger = logging.getLogger(__name__)


@dataclass
class EntryRecord:
    """Record of a single entry."""
    timestamp: datetime
    asset: str
    side: str  # "yes" or "no"
    strategy_intent: str  # "bullish_event" or "bearish_event"
    market_id: str


@dataclass
class DistributionStats:
    """Statistics for entry side distribution."""
    asset: str
    total_entries: int
    yes_entries: int
    no_entries: int
    yes_share: float
    no_share: float
    bullish_count: int
    bearish_count: int
    time_window: str  # e.g., "1h", "24h"
    window_start: datetime
    window_end: datetime


class EntrySideDistributionMonitor:
    """Monitor entry side distribution to detect YES bias."""

    def __init__(self):
        self._entries: List[EntryRecord] = []
        self._lock = threading.Lock()
        self._max_entries = 10000  # Keep last 10k entries
        self._alert_threshold_yes_share = 0.95  # Alert if YES share > 95%

    def record_entry(self, asset: str, side: str, strategy_intent: str, market_id: str = "unknown"):
        """Record an entry for distribution tracking."""
        with self._lock:
            entry = EntryRecord(
                timestamp=datetime.utcnow(),
                asset=asset.upper(),
                side=side.lower(),
                strategy_intent=strategy_intent.lower(),
                market_id=market_id
            )
            self._entries.append(entry)

            # Prune old entries
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

            logger.debug(
                "[ENTRY-SIDE-DISTRIBUTION] Recorded entry: asset=%s side=%s intent=%s total_entries=%d",
                asset, side, strategy_intent, len(self._entries)
            )

    def get_distribution_stats(self, time_window_hours: int = 24) -> Dict[str, DistributionStats]:
        """Get distribution statistics for all assets over the specified time window."""
        with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)
            recent_entries = [e for e in self._entries if e.timestamp >= cutoff_time]

            # Group by asset
            asset_entries: Dict[str, List[EntryRecord]] = defaultdict(list)
            for entry in recent_entries:
                asset_entries[entry.asset].append(entry)

            # Calculate stats per asset
            stats = {}
            for asset, entries in asset_entries.items():
                total = len(entries)
                yes_count = sum(1 for e in entries if e.side == "yes")
                no_count = sum(1 for e in entries if e.side == "no")
                bullish_count = sum(1 for e in entries if e.strategy_intent == "bullish_event")
                bearish_count = sum(1 for e in entries if e.strategy_intent == "bearish_event")

                yes_share = yes_count / total if total > 0 else 0.0
                no_share = no_count / total if total > 0 else 0.0

                stats[asset] = DistributionStats(
                    asset=asset,
                    total_entries=total,
                    yes_entries=yes_count,
                    no_entries=no_count,
                    yes_share=yes_share,
                    no_share=no_share,
                    bullish_count=bullish_count,
                    bearish_count=bearish_count,
                    time_window=f"{time_window_hours}h",
                    window_start=cutoff_time,
                    window_end=datetime.utcnow()
                )

            return stats

    def check_for_bias(self, time_window_hours: int = 24) -> List[str]:
        """Check for YES bias and return alert messages."""
        stats = self.get_distribution_stats(time_window_hours)
        alerts = []

        for asset, stat in stats.items():
            if stat.total_entries >= 10:  # Only check if we have enough data
                if stat.yes_share >= self._alert_threshold_yes_share:
                    alert = (
                        f"[YES-BIAS-ALERT] asset={asset} YES share={stat.yes_share:.1%} "
                        f"(threshold={self._alert_threshold_yes_share:.1%}) "
                        f"over {stat.time_window} window: "
                        f"{stat.yes_entries} YES vs {stat.no_entries} NO entries "
                        f"({stat.total_entries} total). "
                        f"This indicates structural YES bias."
                    )
                    alerts.append(alert)
                    logger.warning(alert)

        return alerts

    def get_summary_table(self, time_window_hours: int = 24) -> str:
        """Generate a summary table of entry side distribution."""
        stats = self.get_distribution_stats(time_window_hours)

        lines = [
            f"\nEntry Side Distribution Summary (last {time_window_hours}h)",
            "=" * 100,
            f"{'Asset':<8} {'Total':<8} {'YES':<8} {'NO':<8} {'YES%':<10} {'NO%':<10} {'Bullish':<10} {'Bearish':<10}",
            "-" * 100
        ]

        for asset in sorted(stats.keys()):
            stat = stats[asset]
            lines.append(
                f"{stat.asset:<8} {stat.total_entries:<8} {stat.yes_entries:<8} {stat.no_entries:<8} "
                f"{stat.yes_share:<10.1%} {stat.no_share:<10.1%} {stat.bullish_count:<10} {stat.bearish_count:<10}"
            )

        lines.append("=" * 100)

        # Add bias alerts
        alerts = self.check_for_bias(time_window_hours)
        if alerts:
            lines.append("\nBIAS ALERTS:")
            for alert in alerts:
                lines.append(f"  {alert}")
        else:
            lines.append("\nNo bias alerts (YES share < 95% for all assets with sufficient data)")

        return "\n".join(lines)

    def clear_old_entries(self, hours_to_keep: int = 168):  # 7 days default
        """Clear entries older than specified hours."""
        with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours_to_keep)
            original_count = len(self._entries)
            self._entries = [e for e in self._entries if e.timestamp >= cutoff_time]
            removed = original_count - len(self._entries)
            logger.info(
                "[ENTRY-SIDE-DISTRIBUTION] Cleared %d old entries (kept last %dh), %d entries remaining",
                removed, hours_to_keep, len(self._entries)
            )


# Singleton instance
_monitor: Optional[EntrySideDistributionMonitor] = None
_monitor_lock = threading.Lock()


def get_entry_side_distribution_monitor() -> EntrySideDistributionMonitor:
    """Get the singleton entry side distribution monitor."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = EntrySideDistributionMonitor()
                logger.info("[ENTRY-SIDE-DISTRIBUTION] Initialized singleton monitor")
    return _monitor
