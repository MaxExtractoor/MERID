"""ExecutionQuality — Fill quality tracking and feedback loop.

Implements critical fixes:
- E-001 (HIGH): Fill quality feedback loop (slippage/latency metrics → execution strategy)
- E-002 (MEDIUM): Iceberg order support for large sizes

Tracks:
1. Per-market fill quality (slippage, latency, partial fill rate)
2. Time-of-day execution patterns
3. Adaptive execution strategy based on observed quality
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import statistics

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.execution_quality")


# ── Fill Quality Tracking ────────────────────────────────────────────────────


@dataclass
class FillQualityMetrics:
    """Metrics for a single fill."""
    market_id: str
    timestamp: datetime
    intended_price_cents: int
    filled_price_cents: int
    intended_contracts: int
    filled_contracts: int
    latency_ms: float
    slippage_cents: int  # Positive = worse than intended
    partial_fill: bool
    fill_ratio: float  # filled / intended


@dataclass
class MarketExecutionProfile:
    """Execution quality profile for a specific market."""
    market_id: str
    sample_count: int
    mean_slippage_cents: float
    std_slippage_cents: float
    mean_latency_ms: float
    p95_latency_ms: float
    partial_fill_rate: float
    mean_fill_ratio: float
    last_update: datetime

    def get_quality_score(self) -> float:
        """Calculate 0-1 quality score (higher = better execution).

        Factors:
        - Low slippage (target: <2 cents)
        - Low latency (target: <500ms)
        - High fill rate (target: >90%)
        """
        # Slippage score (0-1, higher is better)
        slippage_score = max(0.0, 1.0 - abs(self.mean_slippage_cents) / 5.0)

        # Latency score (0-1)
        latency_score = max(0.0, 1.0 - self.mean_latency_ms / 1000.0)

        # Fill rate score (0-1)
        fill_score = self.mean_fill_ratio

        # Weighted average
        quality = 0.4 * slippage_score + 0.3 * latency_score + 0.3 * fill_score
        return max(0.0, min(1.0, quality))


class FillQualityTracker:
    """Tracks fill quality per market and provides execution recommendations.

    Builds statistical profiles of execution quality (slippage, latency, fill rates)
    per market and adapts execution strategy accordingly.
    """

    def __init__(
        self,
        *,
        history_size: int = 100,
        min_samples_for_profile: int = 10,
    ):
        """Initialize fill quality tracker.

        Args:
            history_size: Number of recent fills to track per market
            min_samples_for_profile: Minimum fills before trusting profile
        """
        self.history_size = history_size
        self.min_samples_for_profile = min_samples_for_profile

        # Per-market fill history
        self._fill_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )

        # Cached profiles
        self._profiles: Dict[str, MarketExecutionProfile] = {}

        # Stats
        self.total_fills_recorded = 0

    def record_fill(
        self,
        market_id: str,
        *,
        intended_price_cents: int,
        filled_price_cents: int,
        intended_contracts: int,
        filled_contracts: int,
        latency_ms: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record a fill for quality tracking.

        Args:
            market_id: Market identifier
            intended_price_cents: Price we intended to pay/receive
            filled_price_cents: Price we actually paid/received
            intended_contracts: Contracts we intended to fill
            filled_contracts: Contracts actually filled
            latency_ms: Execution latency in milliseconds
            timestamp: Fill timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        slippage_cents = filled_price_cents - intended_price_cents
        partial_fill = filled_contracts < intended_contracts
        fill_ratio = filled_contracts / intended_contracts if intended_contracts > 0 else 0.0

        metrics = FillQualityMetrics(
            market_id=market_id,
            timestamp=timestamp,
            intended_price_cents=intended_price_cents,
            filled_price_cents=filled_price_cents,
            intended_contracts=intended_contracts,
            filled_contracts=filled_contracts,
            latency_ms=latency_ms,
            slippage_cents=slippage_cents,
            partial_fill=partial_fill,
            fill_ratio=fill_ratio,
        )

        self._fill_history[market_id].append(metrics)
        self.total_fills_recorded += 1

        # Invalidate cached profile
        if market_id in self._profiles:
            del self._profiles[market_id]

    def get_market_profile(self, market_id: str) -> Optional[MarketExecutionProfile]:
        """Get execution quality profile for a market.

        Args:
            market_id: Market identifier

        Returns:
            MarketExecutionProfile or None if insufficient data
        """
        # Check cache
        if market_id in self._profiles:
            return self._profiles[market_id]

        history = self._fill_history.get(market_id, [])
        if len(history) < self.min_samples_for_profile:
            return None

        # Calculate statistics
        slippages = [m.slippage_cents for m in history]
        latencies = [m.latency_ms for m in history]
        fill_ratios = [m.fill_ratio for m in history]

        profile = MarketExecutionProfile(
            market_id=market_id,
            sample_count=len(history),
            mean_slippage_cents=statistics.mean(slippages),
            std_slippage_cents=statistics.stdev(slippages) if len(slippages) > 1 else 0.0,
            mean_latency_ms=statistics.mean(latencies),
            p95_latency_ms=statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
            partial_fill_rate=sum(1 for m in history if m.partial_fill) / len(history),
            mean_fill_ratio=statistics.mean(fill_ratios),
            last_update=datetime.now(timezone.utc),
        )

        # Cache it
        self._profiles[market_id] = profile
        return profile

    def get_execution_recommendation(
        self,
        market_id: str,
        intended_contracts: int,
    ) -> Dict[str, Any]:
        """Get execution strategy recommendation based on quality profile.

        Args:
            market_id: Market identifier
            intended_contracts: Number of contracts to trade

        Returns:
            Dict with execution recommendations:
            - strategy: "aggressive" (cross spread) vs "passive" (join queue) vs "iceberg"
            - price_offset_cents: How far from touch to place passive order
            - iceberg_slice_size: If using iceberg, contracts per slice
            - expected_slippage_cents: Expected slippage based on profile
        """
        profile = self.get_market_profile(market_id)

        # No profile - use conservative defaults
        if profile is None:
            return {
                "strategy": "passive",
                "price_offset_cents": 1,
                "iceberg_slice_size": None,
                "expected_slippage_cents": 2,
                "confidence": "low",
            }

        quality_score = profile.get_quality_score()

        # E-002: Iceberg order support for large sizes
        if intended_contracts > 50 and quality_score < 0.6:
            # Poor quality + large size → slice into iceberg
            return {
                "strategy": "iceberg",
                "price_offset_cents": 1,
                "iceberg_slice_size": min(25, intended_contracts // 4),
                "expected_slippage_cents": int(profile.mean_slippage_cents),
                "confidence": "medium",
            }

        # Good quality → can be aggressive
        if quality_score >= 0.7 and profile.mean_fill_ratio >= 0.9:
            return {
                "strategy": "aggressive",
                "price_offset_cents": 0,  # Cross spread
                "iceberg_slice_size": None,
                "expected_slippage_cents": int(profile.mean_slippage_cents),
                "confidence": "high",
            }

        # Default: passive with 1-cent offset
        return {
            "strategy": "passive",
            "price_offset_cents": 1,
            "iceberg_slice_size": None,
            "expected_slippage_cents": int(profile.mean_slippage_cents),
            "confidence": "medium",
        }


# ── Singleton ────────────────────────────────────────────────────────────────


_fill_quality_tracker: Optional[FillQualityTracker] = None


def get_fill_quality_tracker() -> FillQualityTracker:
    """Get singleton FillQualityTracker."""
    global _fill_quality_tracker
    if _fill_quality_tracker is None:
        _fill_quality_tracker = FillQualityTracker()
    return _fill_quality_tracker
