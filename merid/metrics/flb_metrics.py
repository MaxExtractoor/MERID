"""
FLB (Favorite-Longshot Bias) Performance Metrics Tracking

This module tracks performance metrics for FLB-aware trading decisions.
Based on Bürgi, Deng & Whelan (2026) analysis of 313,972 Kalshi contracts.

Tracks:
- FLB zone exposure (how often we trade in each FLB zone)
- FLB zone performance (PnL by zone)
- FLB edge band performance (special tracking for 88-95¢ NO edge band)
- FLB warnings (how often we get FLB warnings)
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("merid.metrics.flb_metrics")


@dataclass
class FLBZoneMetrics:
    """Metrics for a specific FLB zone."""
    zone_name: str
    total_trades: int = 0
    total_pnl_cents: int = 0
    total_pnl_usd: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_edge_pct: float = 0.0
    avg_position_multiplier: float = 1.0
    last_trade_time: Optional[datetime] = None

    def add_trade(self, pnl_cents: int, edge_pct: float, position_multiplier: float, won: bool):
        """Add a trade to this zone's metrics."""
        self.total_trades += 1
        self.total_pnl_cents += pnl_cents
        self.total_pnl_usd += pnl_cents / 100.0
        if won:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        # Update averages
        self.avg_edge_pct = (self.avg_edge_pct * (self.total_trades - 1) + edge_pct) / self.total_trades
        self.avg_position_multiplier = (self.avg_position_multiplier * (self.total_trades - 1) + position_multiplier) / self.total_trades
        self.last_trade_time = datetime.now(timezone.utc)

    @property
    def win_rate(self) -> float:
        """Calculate win rate for this zone."""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def avg_pnl_per_trade_cents(self) -> float:
        """Calculate average PnL per trade in cents."""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl_cents / self.total_trades

    @property
    def roi_pct(self) -> float:
        """Calculate ROI percentage (average PnL / average position size)."""
        if self.total_trades == 0:
            return 0.0
        # Simplified ROI calculation
        avg_position_cents = 50.0  # Assume $0.50 average position
        return (self.avg_pnl_per_trade_cents / avg_position_cents) * 100.0


class FLBMetricsTracker:
    """Track FLB performance metrics across all trading."""

    def __init__(self):
        # FLB zone metrics
        self.zone_metrics: Dict[str, FLBZoneMetrics] = {
            "high_risk_yes": FLBZoneMetrics("high_risk_yes"),  # YES < 10¢
            "fee_drag_yes": FLBZoneMetrics("fee_drag_yes"),  # YES > 85¢
            "edge_band_no": FLBZoneMetrics("edge_band_no"),  # NO 88-95¢
            "normal_yes": FLBZoneMetrics("normal_yes"),  # YES 10-85¢
            "normal_no": FLBZoneMetrics("normal_no"),  # NO 25-95¢ (excluding edge band)
        }

        # FLB warning counts
        self.flb_warnings: Dict[str, int] = defaultdict(int)

        # Edge band opportunity tracking
        self.edge_band_opportunities: int = 0
        self.edge_band_trades: int = 0

        # Start time
        self.start_time = datetime.now(timezone.utc)

    def record_trade(
        self,
        side: str,
        price_cents: int,
        edge_pct: float,
        position_multiplier: float,
        pnl_cents: int,
        won: bool
    ):
        """Record a trade with FLB zone information."""
        # Determine FLB zone
        zone = self._determine_flb_zone(side, price_cents)

        # Add trade to zone metrics
        self.zone_metrics[zone].add_trade(pnl_cents, edge_pct, position_multiplier, won)

        logger.info(
            "[FLB-METRICS] zone=%s side=%s price=%dc edge=%.2f%% multiplier=%.2f pnl=%dc won=%s "
            "total_trades=%d total_pnl=%.2f¢ win_rate=%.2f%%",
            zone, side, price_cents, edge_pct, position_multiplier, pnl_cents, won,
            self.zone_metrics[zone].total_trades,
            self.zone_metrics[zone].total_pnl_cents,
            self.zone_metrics[zone].win_rate * 100
        )

    def record_flb_warning(self, warning_type: str, side: str, price_cents: int):
        """Record an FLB warning."""
        self.flb_warnings[warning_type] += 1
        logger.info(
            "[FLB-WARNING-METRICS] warning_type=%s side=%s price=%dc total_warnings=%d",
            warning_type, side, price_cents, self.flb_warnings[warning_type]
        )

    def record_edge_band_opportunity(self, side: str, price_cents: int):
        """Record an edge band opportunity."""
        self.edge_band_opportunities += 1
        logger.info(
            "[FLB-EDGE-BAND-METRICS] side=%s price=%dc total_opportunities=%d",
            side, price_cents, self.edge_band_opportunities
        )

    def record_edge_band_trade(self, side: str, price_cents: int):
        """Record an edge band trade execution."""
        self.edge_band_trades += 1
        logger.info(
            "[FLB-EDGE-BAND-METRICS] side=%s price=%dc total_trades=%d opportunity_rate=%.2f%%",
            side, price_cents, self.edge_band_trades,
            (self.edge_band_trades / self.edge_band_opportunities * 100) if self.edge_band_opportunities > 0 else 0.0
        )

    def _determine_flb_zone(self, side: str, price_cents: int) -> str:
        """Determine which FLB zone a trade belongs to."""
        if side == "yes":
            if price_cents < 10:
                return "high_risk_yes"
            elif price_cents > 85:
                return "fee_drag_yes"
            else:
                return "normal_yes"
        else:  # side == "no"
            if 88 <= price_cents <= 95:
                return "edge_band_no"
            elif price_cents >= 25:
                return "normal_no"
            else:
                return "normal_no"  # Should be rare due to FLB checks

    def get_zone_summary(self) -> Dict[str, Dict]:
        """Get summary metrics for all FLB zones."""
        summary = {}
        for zone_name, metrics in self.zone_metrics.items():
            summary[zone_name] = {
                "total_trades": metrics.total_trades,
                "total_pnl_cents": metrics.total_pnl_cents,
                "total_pnl_usd": metrics.total_pnl_usd,
                "win_rate": metrics.win_rate,
                "avg_pnl_per_trade_cents": metrics.avg_pnl_per_trade_cents,
                "roi_pct": metrics.roi_pct,
                "avg_edge_pct": metrics.avg_edge_pct,
                "avg_position_multiplier": metrics.avg_position_multiplier,
                "last_trade_time": metrics.last_trade_time.isoformat() if metrics.last_trade_time else None
            }
        return summary

    def get_warning_summary(self) -> Dict[str, int]:
        """Get summary of FLB warnings."""
        return dict(self.flb_warnings)

    def get_edge_band_summary(self) -> Dict[str, int]:
        """Get summary of edge band metrics."""
        return {
            "opportunities": self.edge_band_opportunities,
            "trades": self.edge_band_trades,
            "opportunity_rate": (self.edge_band_trades / self.edge_band_opportunities * 100) if self.edge_band_opportunities > 0 else 0.0
        }

    def log_summary(self):
        """Log comprehensive FLB metrics summary."""
        logger.info("=" * 80)
        logger.info("[FLB-METRICS-SUMMARY] FLB Performance Metrics Summary")
        logger.info("=" * 80)

        # Zone summary
        logger.info("\n--- FLB Zone Performance ---")
        for zone_name, metrics in self.zone_metrics.items():
            if metrics.total_trades > 0:
                logger.info(
                    f"Zone: {zone_name:20s} | Trades: {metrics.total_trades:4d} | "
                    f"PnL: ${metrics.total_pnl_usd:8.2f} | Win Rate: {metrics.win_rate*100:5.1f}% | "
                    f"Avg Edge: {metrics.avg_edge_pct:5.2f}% | Avg Mult: {metrics.avg_position_multiplier:4.2f}x"
                )

        # Warning summary
        logger.info("\n--- FLB Warnings ---")
        for warning_type, count in self.flb_warnings.items():
            if count > 0:
                logger.info(f"Warning Type: {warning_type:30s} | Count: {count:4d}")

        # Edge band summary
        if self.edge_band_opportunities > 0:
            logger.info("\n--- FLB Edge Band ---")
            logger.info(
                f"Opportunities: {self.edge_band_opportunities:4d} | "
                f"Trades: {self.edge_band_trades:4d} | "
                f"Opportunity Rate: {(self.edge_band_trades / self.edge_band_opportunities * 100):5.1f}%"
            )

        logger.info("=" * 80)


# Global FLB metrics tracker instance
_flb_metrics_tracker: Optional[FLBMetricsTracker] = None


def get_flb_metrics_tracker() -> FLBMetricsTracker:
    """Get the global FLB metrics tracker instance."""
    global _flb_metrics_tracker
    if _flb_metrics_tracker is None:
        _flb_metrics_tracker = FLBMetricsTracker()
    return _flb_metrics_tracker


def record_flb_trade(
    side: str,
    price_cents: int,
    edge_pct: float,
    position_multiplier: float,
    pnl_cents: int,
    won: bool
):
    """Record a trade with FLB zone information (convenience function)."""
    tracker = get_flb_metrics_tracker()
    tracker.record_trade(side, price_cents, edge_pct, position_multiplier, pnl_cents, won)


def record_flb_warning(warning_type: str, side: str, price_cents: int):
    """Record an FLB warning (convenience function)."""
    tracker = get_flb_metrics_tracker()
    tracker.record_flb_warning(warning_type, side, price_cents)


def record_edge_band_opportunity(side: str, price_cents: int):
    """Record an edge band opportunity (convenience function)."""
    tracker = get_flb_metrics_tracker()
    tracker.record_edge_band_opportunity(side, price_cents)


def record_edge_band_trade(side: str, price_cents: int):
    """Record an edge band trade execution (convenience function)."""
    tracker = get_flb_metrics_tracker()
    tracker.record_edge_band_trade(side, price_cents)
