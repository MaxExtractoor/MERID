"""Cross-Timeframe Signal Aggregator.

Combines sentiment and technical signals across multiple timeframes
(1m, 5m, 15m, 1h, 4h, 1d) into a single multi-resolution view.

Design
------
- Each timeframe is a "lane" with its own rolling signal buffer.
- Signals are weighted by timeframe recency and reliability.
- Higher timeframes carry more weight (trend context).
- Lower timeframes carry more weight for timing precision.
- Outputs a ``CrossTimeframeSignal`` with alignment score, dominant
  direction, and per-lane breakdown.
- Integrates with ``SentimentBusV2`` and ``SwarmConsensusAggregator``.

Usage::

    agg = get_cross_timeframe_aggregator()
    agg.push_signal("BTC", "15m", score=0.6, source="sentiment")
    agg.push_signal("BTC", "1h",  score=0.7, source="consensus")
    result = agg.aggregate("BTC")
    print(result.alignment_score, result.dominant_direction)
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.sentiment.cross_timeframe_aggregator")


# ── Timeframe registry ────────────────────────────────────────────────────

# Ordered lowest → highest.  Weight increases with timeframe (trend context).
# stale_after: seconds before a signal is evicted from the buffer.
TIMEFRAME_CONFIG: Dict[str, Dict[str, Any]] = {
    "1m":  {"weight": 0.5,  "stale_after": 120,   "order": 0},
    "5m":  {"weight": 0.7,  "stale_after": 600,   "order": 1},
    "15m": {"weight": 1.0,  "stale_after": 1800,  "order": 2},
    "1h":  {"weight": 1.4,  "stale_after": 7200,  "order": 3},
    "4h":  {"weight": 1.8,  "stale_after": 28800, "order": 4},
    "1d":  {"weight": 2.0,  "stale_after": 172800,"order": 5},
}

KNOWN_TIMEFRAMES = list(TIMEFRAME_CONFIG.keys())


# ── Data models ───────────────────────────────────────────────────────────

@dataclass
class TimeframeSignal:
    """A single signal observation for one asset/timeframe."""
    asset: str
    timeframe: str
    score: float          # -1.0 (bearish) to +1.0 (bullish)
    source: str           # "sentiment", "consensus", "technical", "news"
    confidence: float     # 0.0 to 1.0
    timestamp: float      # unix epoch


@dataclass
class LaneSnapshot:
    """Aggregated view of one timeframe lane."""
    timeframe: str
    weight: float
    avg_score: float
    avg_confidence: float
    signal_count: int
    direction: str        # "bullish", "bearish", "neutral"
    stale: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "weight": round(self.weight, 2),
            "avg_score": round(self.avg_score, 4),
            "avg_confidence": round(self.avg_confidence, 4),
            "signal_count": self.signal_count,
            "direction": self.direction,
            "stale": self.stale,
        }


@dataclass
class CrossTimeframeSignal:
    """Aggregated multi-resolution signal for one asset."""
    asset: str
    timestamp: datetime

    # Overall composite
    composite_score: float        # Weighted average across timeframes
    dominant_direction: str       # "bullish", "bearish", "neutral"
    alignment_score: float        # 0.0 (all disagree) to 1.0 (all agree)
    overall_confidence: float     # Weighted confidence

    # Per-lane breakdown
    lanes: List[LaneSnapshot]

    # Metadata
    active_timeframes: int        # Lanes with fresh signals
    total_timeframes: int
    sources: List[str]            # Unique signal sources contributing

    # Flags
    is_aligned: bool              # alignment_score >= threshold
    has_trend_confirmation: bool  # Higher TFs agree with lower TFs
    conflict_flags: List[str]     # Descriptions of disagreements

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timestamp": self.timestamp.isoformat(),
            "composite_score": round(self.composite_score, 4),
            "dominant_direction": self.dominant_direction,
            "alignment_score": round(self.alignment_score, 4),
            "overall_confidence": round(self.overall_confidence, 4),
            "active_timeframes": self.active_timeframes,
            "total_timeframes": self.total_timeframes,
            "sources": self.sources,
            "is_aligned": self.is_aligned,
            "has_trend_confirmation": self.has_trend_confirmation,
            "conflict_flags": self.conflict_flags,
            "lanes": [lane.to_dict() for lane in self.lanes],
        }


# ── Aggregator ────────────────────────────────────────────────────────────

class CrossTimeframeAggregator:
    """Aggregates signals across timeframes into a unified multi-resolution view.

    Thread-safety: uses simple in-process deques; designed for single-threaded
    async event loops.  For multi-threaded use, wrap push/aggregate in a lock.
    """

    def __init__(
        self,
        max_signals_per_lane: int = 50,
        alignment_threshold: float = 0.65,
    ) -> None:
        self._max_per_lane = max_signals_per_lane
        self._alignment_threshold = alignment_threshold

        # {asset: {timeframe: deque[TimeframeSignal]}}
        self._buffers: Dict[str, Dict[str, Deque[TimeframeSignal]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=max_signals_per_lane))
        )

        # Cache of last aggregation result per asset
        self._cache: Dict[str, CrossTimeframeSignal] = {}

    # ── Ingestion ─────────────────────────────────────────────────────

    def push_signal(
        self,
        asset: str,
        timeframe: str,
        score: float,
        source: str = "unknown",
        confidence: float = 0.5,
    ) -> None:
        """Push a new signal observation into the appropriate lane buffer.

        Args:
            asset: Asset symbol, e.g. "BTC".
            timeframe: One of KNOWN_TIMEFRAMES ("1m", "5m", "15m", "1h", "4h", "1d").
            score: Signal score in [-1.0, 1.0].  Positive = bullish.
            source: Signal origin ("sentiment", "consensus", "technical", "news").
            confidence: Confidence in [0.0, 1.0].
        """
        if timeframe not in TIMEFRAME_CONFIG:
            logger.debug("[xtf] unknown timeframe %s — ignored", timeframe)
            return

        score = max(-1.0, min(1.0, score))
        confidence = max(0.0, min(1.0, confidence))

        sig = TimeframeSignal(
            asset=asset,
            timeframe=timeframe,
            score=score,
            source=source,
            confidence=confidence,
            timestamp=time.time(),
        )
        self._buffers[asset][timeframe].append(sig)
        logger.debug("[xtf] %s/%s score=%.3f src=%s", asset, timeframe, score, source)

    def push_from_sentiment_bus(self, asset: str, ctx: Any) -> None:
        """Convenience: push from an AssetSentimentContext object.

        Reads ``combined_score`` and ``confidence`` from the context and
        pushes into the 15m lane (default sentiment resolution).
        """
        try:
            score = float(getattr(ctx, "combined_score", 0.0))
            confidence = float(getattr(ctx, "confidence", 0.5))
            self.push_signal(asset, "15m", score=score, source="sentiment", confidence=confidence)
        except Exception as exc:
            logger.debug("[xtf] push_from_sentiment_bus error: %s", exc)

    def push_from_consensus(self, asset: str, timeframe: str, view: Any) -> None:
        """Convenience: push from a ConsensusView object.

        Maps consensus_direction → score: yes=+1, no=-1, neutral=0.
        """
        try:
            direction = getattr(view, "consensus_direction", "neutral")
            prob = float(getattr(view, "consensus_probability", 0.5))
            confidence = float(getattr(view, "consensus_confidence", 0.5))
            # Map direction + probability to a [-1, 1] score
            if direction == "yes":
                score = prob
            elif direction == "no":
                score = -prob
            else:
                score = 0.0
            self.push_signal(asset, timeframe, score=score, source="consensus", confidence=confidence)
        except Exception as exc:
            logger.debug("[xtf] push_from_consensus error: %s", exc)

    # ── Aggregation ───────────────────────────────────────────────────

    def aggregate(self, asset: str) -> CrossTimeframeSignal:
        """Compute the cross-timeframe signal for an asset.

        Returns the cached result if called multiple times without new signals.
        """
        now = time.time()
        lanes: List[LaneSnapshot] = []
        all_sources: set = set()

        weighted_score_sum = 0.0
        weighted_conf_sum = 0.0
        total_weight = 0.0
        direction_weights: Dict[str, float] = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}

        for tf, cfg in sorted(TIMEFRAME_CONFIG.items(), key=lambda x: x[1]["order"]):
            tf_weight = cfg["weight"]
            stale_after = cfg["stale_after"]
            buf = self._buffers[asset].get(tf, deque())

            # Filter stale signals
            fresh = [s for s in buf if now - s.timestamp <= stale_after]
            is_stale = len(fresh) == 0

            if fresh:
                avg_score = sum(s.score * s.confidence for s in fresh) / sum(s.confidence for s in fresh)
                avg_conf = sum(s.confidence for s in fresh) / len(fresh)
                for s in fresh:
                    all_sources.add(s.source)
            else:
                avg_score = 0.0
                avg_conf = 0.0

            direction = self._score_to_direction(avg_score)

            lane = LaneSnapshot(
                timeframe=tf,
                weight=tf_weight,
                avg_score=avg_score,
                avg_confidence=avg_conf,
                signal_count=len(fresh),
                direction=direction,
                stale=is_stale,
            )
            lanes.append(lane)

            if not is_stale:
                effective_weight = tf_weight * avg_conf
                weighted_score_sum += avg_score * effective_weight
                weighted_conf_sum += avg_conf * effective_weight
                total_weight += effective_weight
                direction_weights[direction] += effective_weight

        # Composite score
        composite = weighted_score_sum / total_weight if total_weight > 0 else 0.0
        overall_conf = weighted_conf_sum / total_weight if total_weight > 0 else 0.0

        # Dominant direction
        dominant = max(direction_weights, key=lambda d: direction_weights[d])
        if direction_weights[dominant] == 0.0:
            dominant = "neutral"

        # Alignment score: fraction of total weight on the dominant direction
        total_dir_weight = sum(direction_weights.values())
        alignment = direction_weights[dominant] / total_dir_weight if total_dir_weight > 0 else 0.0

        # Trend confirmation: higher TFs agree with lower TFs
        has_trend_conf, conflict_flags = self._check_trend_confirmation(lanes)

        active_tfs = sum(1 for lane in lanes if not lane.stale)

        result = CrossTimeframeSignal(
            asset=asset,
            timestamp=datetime.now(timezone.utc),
            composite_score=composite,
            dominant_direction=dominant,
            alignment_score=alignment,
            overall_confidence=overall_conf,
            lanes=lanes,
            active_timeframes=active_tfs,
            total_timeframes=len(TIMEFRAME_CONFIG),
            sources=sorted(all_sources),
            is_aligned=alignment >= self._alignment_threshold,
            has_trend_confirmation=has_trend_conf,
            conflict_flags=conflict_flags,
        )

        self._cache[asset] = result
        return result

    def aggregate_all(self) -> Dict[str, CrossTimeframeSignal]:
        """Aggregate all assets that have at least one signal."""
        return {asset: self.aggregate(asset) for asset in self._buffers}

    def get_cached(self, asset: str) -> Optional[CrossTimeframeSignal]:
        """Return the last computed result without recomputing."""
        return self._cache.get(asset)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _score_to_direction(score: float) -> str:
        if score > 0.1:
            return "bullish"
        if score < -0.1:
            return "bearish"
        return "neutral"

    def _check_trend_confirmation(
        self, lanes: List[LaneSnapshot]
    ) -> Tuple[bool, List[str]]:
        """Check whether higher timeframes confirm lower timeframe direction.

        Returns (has_confirmation, conflict_flags).
        """
        active = [lane for lane in lanes if not lane.stale]
        if len(active) < 2:
            return False, []

        conflicts: List[str] = []

        # Sort by timeframe order
        ordered = sorted(active, key=lambda l: TIMEFRAME_CONFIG[l.timeframe]["order"])

        # Compare each adjacent pair (lower → higher)
        for i in range(len(ordered) - 1):
            lower = ordered[i]
            higher = ordered[i + 1]
            if lower.direction != "neutral" and higher.direction != "neutral":
                if lower.direction != higher.direction:
                    conflicts.append(
                        f"{lower.timeframe} {lower.direction} vs {higher.timeframe} {higher.direction}"
                    )

        # Trend confirmed if lowest and highest active TF agree
        lowest = ordered[0]
        highest = ordered[-1]
        has_confirmation = (
            lowest.direction == highest.direction
            and lowest.direction != "neutral"
        )

        return has_confirmation, conflicts

    # ── Sync from live data sources ───────────────────────────────────

    def sync_from_sentiment_bus(self) -> int:
        """Pull current asset contexts from SentimentBusV2 and push into 15m lane.

        Returns number of assets synced.
        """
        count = 0
        try:
            from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus
            bus = get_sentiment_bus()
            contexts = bus.get_all_asset_contexts() if hasattr(bus, "get_all_asset_contexts") else {}
            for asset, ctx in contexts.items():
                self.push_from_sentiment_bus(asset, ctx)
                count += 1
        except Exception as exc:
            logger.debug("[xtf] sync_from_sentiment_bus error: %s", exc)
        return count

    def sync_from_consensus(self) -> int:
        """Pull current consensus views from SwarmConsensusAggregator.

        Returns number of views synced.
        """
        count = 0
        try:
            from merid.swarm.consensus_aggregator import get_consensus_aggregator
            agg = get_consensus_aggregator()
            all_views = agg.get_all_consensus()
            for key, view in all_views.items():
                asset, timeframe = key.split(":", 1)
                self.push_from_consensus(asset, timeframe, view)
                count += 1
        except Exception as exc:
            logger.debug("[xtf] sync_from_consensus error: %s", exc)
        return count

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Status dict for the API."""
        assets = list(self._buffers.keys())
        return {
            "tracked_assets": assets,
            "asset_count": len(assets),
            "alignment_threshold": self._alignment_threshold,
            "timeframes": KNOWN_TIMEFRAMES,
            "cached_results": list(self._cache.keys()),
        }

    def clear(self, asset: Optional[str] = None) -> None:
        """Clear signal buffers (all assets or a specific one)."""
        if asset:
            self._buffers.pop(asset, None)
            self._cache.pop(asset, None)
        else:
            self._buffers.clear()
            self._cache.clear()


# ── Singleton ─────────────────────────────────────────────────────────────

_aggregator: Optional[CrossTimeframeAggregator] = None


def get_cross_timeframe_aggregator() -> CrossTimeframeAggregator:
    """Return the module-level CrossTimeframeAggregator singleton."""
    global _aggregator
    if _aggregator is None:
        _aggregator = CrossTimeframeAggregator()
    return _aggregator
