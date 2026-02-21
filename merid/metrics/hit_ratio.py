"""Hit Ratio Tracker — Sprint O.

Tracks whether our p_model predictions actually beat the Kalshi implied
probability. This is distinct from Brier scores (which measure calibration)
— hit ratio measures *directional accuracy*: did we correctly predict
which side would win more often than the market implied?

Metrics tracked:
1. **Hit ratio** — % of trades where outcome matched our predicted direction
2. **Edge capture** — average (p_model - p_implied) for winning trades
3. **Surprise ratio** — % of trades where outcome was opposite to market consensus
4. **Per-forecaster hit rate** — breakdown by forecaster_id

Usage::

    tracker = get_hit_ratio_tracker()
    tracker.record(
        market_id="KXBTC-24FEB21",
        forecaster_id="momentum_v1",
        p_model=0.65,
        p_implied=0.52,
        outcome=1,  # 1=YES won, 0=NO won
    )
    stats = tracker.stats
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.metrics.hit_ratio")


@dataclass
class HitRecord:
    """Single prediction→outcome record."""
    market_id: str
    forecaster_id: str
    p_model: float
    p_implied: float
    outcome: int          # 1 = YES won, 0 = NO won
    predicted_yes: bool   # Did model predict YES side?
    hit: bool             # Did prediction match outcome?
    edge_at_entry: float  # p_model - p_implied (signed)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "forecaster_id": self.forecaster_id,
            "p_model": round(self.p_model, 4),
            "p_implied": round(self.p_implied, 4),
            "outcome": self.outcome,
            "predicted_yes": self.predicted_yes,
            "hit": self.hit,
            "edge_at_entry": round(self.edge_at_entry, 4),
            "timestamp": self.timestamp,
        }


class HitRatioTracker:
    """Tracks directional accuracy of model predictions vs market implied.

    A "hit" means our model correctly predicted the winning side more
    confidently than the market. E.g. if p_model=0.65 and p_implied=0.52,
    and YES wins → that's a hit (we were right to be more bullish than market).
    """

    def __init__(self, max_history: int = 2000):
        self._records: List[HitRecord] = []
        self._max_history = max_history
        self._per_forecaster: Dict[str, List[HitRecord]] = defaultdict(list)

    def record(
        self,
        market_id: str,
        forecaster_id: str,
        p_model: float,
        p_implied: float,
        outcome: int,
    ) -> HitRecord:
        """Record a prediction outcome.

        Args:
            market_id: Kalshi market ID
            forecaster_id: Which forecaster made the prediction
            p_model: Our model's predicted YES probability
            p_implied: Market implied YES probability at entry
            outcome: 1 if YES won, 0 if NO won

        Returns:
            The HitRecord created
        """
        predicted_yes = p_model > 0.5
        actual_yes = outcome == 1

        # A "hit" is when we predicted the correct side AND had edge
        hit = (predicted_yes == actual_yes)

        edge_at_entry = p_model - p_implied

        rec = HitRecord(
            market_id=market_id,
            forecaster_id=forecaster_id,
            p_model=p_model,
            p_implied=p_implied,
            outcome=outcome,
            predicted_yes=predicted_yes,
            hit=hit,
            edge_at_entry=edge_at_entry,
        )

        self._records.append(rec)
        self._per_forecaster[forecaster_id].append(rec)

        if len(self._records) > self._max_history:
            self._records = self._records[-self._max_history:]

        logger.debug(
            f"Hit record: {market_id} forecaster={forecaster_id} "
            f"p_model={p_model:.3f} p_implied={p_implied:.3f} "
            f"outcome={'YES' if actual_yes else 'NO'} hit={hit}"
        )

        return rec

    @property
    def stats(self) -> Dict[str, Any]:
        """Aggregate hit ratio statistics."""
        if not self._records:
            return {
                "total_records": 0,
                "hit_ratio": 0.0,
                "avg_edge_at_entry": 0.0,
                "avg_edge_on_hits": 0.0,
                "surprise_ratio": 0.0,
                "per_forecaster": {},
            }

        total = len(self._records)
        hits = sum(1 for r in self._records if r.hit)
        hit_ratio = hits / total

        avg_edge = sum(r.edge_at_entry for r in self._records) / total
        hit_records = [r for r in self._records if r.hit]
        avg_edge_on_hits = (
            sum(r.edge_at_entry for r in hit_records) / len(hit_records)
            if hit_records else 0.0
        )

        # Surprise ratio: outcomes that went against market consensus
        surprises = sum(
            1 for r in self._records
            if (r.p_implied > 0.5 and r.outcome == 0) or
               (r.p_implied < 0.5 and r.outcome == 1)
        )
        surprise_ratio = surprises / total

        per_forecaster = {}
        for fid, records in self._per_forecaster.items():
            if records:
                f_hits = sum(1 for r in records if r.hit)
                per_forecaster[fid] = {
                    "total": len(records),
                    "hits": f_hits,
                    "hit_ratio": round(f_hits / len(records), 4),
                    "avg_edge": round(
                        sum(r.edge_at_entry for r in records) / len(records), 4
                    ),
                }

        return {
            "total_records": total,
            "hit_ratio": round(hit_ratio, 4),
            "avg_edge_at_entry": round(avg_edge, 4),
            "avg_edge_on_hits": round(avg_edge_on_hits, 4),
            "surprise_ratio": round(surprise_ratio, 4),
            "per_forecaster": per_forecaster,
        }

    @property
    def history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._records[-100:]]


# ── Singleton ────────────────────────────────────────────────────────────

_tracker: Optional[HitRatioTracker] = None


def get_hit_ratio_tracker() -> HitRatioTracker:
    """Get or create the singleton HitRatioTracker."""
    global _tracker
    if _tracker is None:
        _tracker = HitRatioTracker()
    return _tracker
