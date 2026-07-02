"""
Edge Rejection Tracker

Tracks and aggregates NO_EDGE rejections for operational visibility
and strategy tuning. This module provides:

- Counters for NO_EDGE rejections by asset and reason
- Structured logging of edge gap details
- Summary statistics for NO_EDGE behavior analysis
- Dashboard-ready data export

This helps distinguish between "too tight on edge" vs "too tight on contract selection"
and enables data-driven tuning of edge thresholds.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


@dataclass
class EdgeRejection:
    """Single edge rejection event."""
    timestamp: str
    agent_id: str
    market_id: str
    asset: str
    side: str
    model_prob: float
    implied_prob: float
    edge_pct: float
    min_edge_pct: float
    edge_gap_pct: float
    confidence: float
    reason: str  # "NO_EDGE_YES" or "NO_EDGE_NO"
    cycle_number: Optional[int] = None


class EdgeRejectionTracker:
    """Tracks edge rejections with per-asset and per-reason aggregation."""

    def __init__(self):
        self._rejections: List[EdgeRejection] = []
        self._counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._edge_gaps: Dict[str, List[float]] = defaultdict(list)

    def record_rejection(
        self,
        agent_id: str,
        market_id: str,
        side: str,
        model_prob: float,
        implied_prob: float,
        edge_pct: float,
        min_edge_pct: float,
        confidence: float,
        reason: str,
        cycle_number: Optional[int] = None,
    ):
        """
        Record an edge rejection event.

        Args:
            agent_id: Agent that generated the signal
            market_id: Kalshi market ID
            side: "yes" or "no"
            model_prob: Model probability
            implied_prob: Implied probability from market
            edge_pct: Actual edge percentage
            min_edge_pct: Minimum edge threshold
            confidence: Model confidence
            reason: "NO_EDGE_YES" or "NO_EDGE_NO"
            cycle_number: Cycle number (optional)
        """
        # Extract asset from market_id (e.g., KXBTC15M-26MAY221215-15 -> BTC)
        asset = self._extract_asset(market_id)

        # Calculate edge gap
        edge_gap_pct = min_edge_pct - edge_pct

        # Create rejection record
        rejection = EdgeRejection(
            timestamp=datetime.utcnow().isoformat(),
            agent_id=agent_id,
            market_id=market_id,
            asset=asset,
            side=side,
            model_prob=model_prob,
            implied_prob=implied_prob,
            edge_pct=edge_pct,
            min_edge_pct=min_edge_pct,
            edge_gap_pct=edge_gap_pct,
            confidence=confidence,
            reason=reason,
            cycle_number=cycle_number,
        )

        # Store rejection
        self._rejections.append(rejection)

        # Update counters
        self._counters[asset][reason] += 1
        self._counters["total"][reason] += 1

        # Track edge gaps for analysis
        self._edge_gaps[asset].append(edge_gap_pct)
        self._edge_gaps["total"].append(edge_gap_pct)

        # Log structured rejection
        logger.info(
            "[NO-EDGE-REJECTION] agent=%s | market=%s | asset=%s | side=%s | "
            "model=%.3f | implied=%.3f | edge=%.2f%% | min_edge=%.2f%% | gap=%.2f%% | "
            "confidence=%.2f | reason=%s | cycle=%s",
            agent_id,
            market_id,
            asset,
            side,
            model_prob,
            implied_prob,
            edge_pct,
            min_edge_pct,
            edge_gap_pct,
            confidence,
            reason,
            cycle_number or "N/A",
        )

    def get_summary(self) -> Dict:
        """
        Get summary statistics for edge rejections.

        Returns:
            Dict with summary statistics
        """
        total_rejections = len(self._rejections)

        # Per-asset breakdown
        asset_breakdown = {}
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if asset in self._counters:
                asset_breakdown[asset] = {
                    "total": sum(self._counters[asset].values()),
                    "no_edge_yes": self._counters[asset].get("NO_EDGE_YES", 0),
                    "no_edge_no": self._counters[asset].get("NO_EDGE_NO", 0),
                    "avg_edge_gap_pct": sum(self._edge_gaps[asset]) / len(self._edge_gaps[asset]) if self._edge_gaps[asset] else 0.0,
                }

        # Overall statistics
        overall = {
            "total_rejections": total_rejections,
            "no_edge_yes_total": self._counters["total"].get("NO_EDGE_YES", 0),
            "no_edge_no_total": self._counters["total"].get("NO_EDGE_NO", 0),
            "avg_edge_gap_pct": sum(self._edge_gaps["total"]) / len(self._edge_gaps["total"]) if self._edge_gaps["total"] else 0.0,
            "asset_breakdown": asset_breakdown,
        }

        return overall

    def get_recent_rejections(self, limit: int = 10) -> List[Dict]:
        """
        Get the most recent rejection events.

        Args:
            limit: Maximum number of rejections to return

        Returns:
            List of rejection dicts
        """
        recent = self._rejections[-limit:] if self._rejections else []
        return [asdict(r) for r in recent]

    def get_edge_gap_distribution(self, asset: Optional[str] = None) -> Dict:
        """
        Get edge gap distribution statistics.

        Args:
            asset: Asset to filter by (None for all assets)

        Returns:
            Dict with distribution statistics
        """
        gaps = self._edge_gaps[asset] if asset else self._edge_gaps["total"]

        if not gaps:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "median": 0}

        gaps_sorted = sorted(gaps)
        return {
            "count": len(gaps),
            "min": gaps_sorted[0],
            "max": gaps_sorted[-1],
            "avg": sum(gaps) / len(gaps),
            "median": gaps_sorted[len(gaps_sorted) // 2],
        }

    def reset(self):
        """Reset all tracking data."""
        self._rejections.clear()
        self._counters.clear()
        self._edge_gaps.clear()
        logger.info("[NO-EDGE-TRACKER] Reset all tracking data")

    def _extract_asset(self, market_id: str) -> str:
        """Extract asset symbol from market ID."""
        # Market ID format: KXBTC15M-26MAY221215-15
        # Extract BTC from KXBTC15M
        if market_id.startswith("KX"):
            # Remove KX prefix and timeframe suffix
            # KXBTC15M -> BTC
            # KXETH -> ETH
            ticker = market_id.split("-")[0]  # Get series ticker part
            # Remove KX prefix
            if ticker.startswith("KX"):
                ticker = ticker[2:]
            # Remove timeframe suffix (15M, H1, D1, W1, etc.)
                import re
                ticker = re.sub(r'(15M|H1|D1|W1|1M|Y)$', '', ticker)
            return ticker
        return "UNKNOWN"


# Global singleton instance
_tracker: Optional[EdgeRejectionTracker] = None


def get_edge_rejection_tracker() -> EdgeRejectionTracker:
    """Get the global edge rejection tracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = EdgeRejectionTracker()
        logger.info("[NO-EDGE-TRACKER] Initialized global tracker")
    return _tracker


def record_no_edge_rejection(
    agent_id: str,
    market_id: str,
    side: str,
    model_prob: float,
    implied_prob: float,
    edge_pct: float,
    min_edge_pct: float,
    confidence: float,
    reason: str,
    cycle_number: Optional[int] = None,
):
    """
    Convenience function to record an edge rejection.

    This is the main entry point for recording NO_EDGE rejections
    from the agent grid.
    """
    tracker = get_edge_rejection_tracker()
    tracker.record_rejection(
        agent_id=agent_id,
        market_id=market_id,
        side=side,
        model_prob=model_prob,
        implied_prob=implied_prob,
        edge_pct=edge_pct,
        min_edge_pct=min_edge_pct,
        confidence=confidence,
        reason=reason,
        cycle_number=cycle_number,
    )
