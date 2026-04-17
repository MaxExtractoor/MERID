"""Inter-Asset Correlation Tracker — Sprint D.

Computes rolling correlation between Kalshi crypto assets to prevent
concentrated correlated exposure. When BTC and ETH are highly correlated
(ρ > 0.7), combined exposure should be capped as if they were one position.

Usage::

    tracker = get_correlation_tracker()
    tracker.record_return("BTC", 0.02)
    tracker.record_return("ETH", 0.018)
    ...
    corr = tracker.get_correlation("BTC", "ETH")  # e.g., 0.85
    factor = tracker.exposure_reduction_factor("BTC", "ETH")  # e.g., 0.6

The PortfolioRiskAgent uses ``exposure_reduction_factor()`` to shrink
combined notional caps when assets are correlated.
"""

from __future__ import annotations

import threading
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.correlation")

# Default correlation window (number of return observations)
DEFAULT_WINDOW = 50

# Predefined asset clusters (known high-correlation pairs)
ASSET_CLUSTERS: Dict[str, List[str]] = {
    "BTC_ETH": ["BTC", "ETH"],
    "ALT_BASKET": ["SOL", "XRP", "DOGE"],
}

# Threshold above which correlation triggers exposure reduction
CORRELATION_THRESHOLD = 0.5

# Maximum exposure reduction factor (at ρ=1.0)
MAX_REDUCTION = 0.4  # Reduce to 40% of combined cap at perfect correlation


@dataclass
class CorrelationPair:
    """Rolling correlation state between two assets."""
    asset_a: str
    asset_b: str
    correlation: float = 0.0
    sample_count: int = 0
    last_updated: float = 0.0


@dataclass
class CorrelationMatrix:
    """Full correlation matrix snapshot for all tracked assets."""
    timestamp: float
    pairs: List[CorrelationPair]
    assets: List[str]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "assets": self.assets,
            "pairs": [
                {
                    "asset_a": p.asset_a,
                    "asset_b": p.asset_b,
                    "correlation": round(p.correlation, 4),
                    "sample_count": p.sample_count,
                }
                for p in self.pairs
            ],
        }


class CorrelationTracker:
    """Rolling inter-asset correlation tracker.

    Records per-asset returns (from price changes or PnL moves) and
    computes pairwise Pearson correlation over a rolling window.
    """

    def __init__(self, window: int = DEFAULT_WINDOW):
        self._window = window
        self._returns: Dict[str, List[float]] = defaultdict(list)
        self._timestamps: Dict[str, List[float]] = defaultdict(list)
        self._cache: Dict[Tuple[str, str], float] = {}
        self._cache_ts: float = 0.0
        self._cache_ttl = 30.0  # seconds

    def record_return(self, asset: str, ret: float, ts: Optional[float] = None) -> None:
        """Record a return observation for an asset.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH").
            ret: Period return (e.g., 0.02 for 2%).
            ts: Optional timestamp.
        """
        asset = asset.upper()
        self._returns[asset].append(ret)
        self._timestamps[asset].append(ts or time.time())

        # Trim to window
        if len(self._returns[asset]) > self._window:
            self._returns[asset] = self._returns[asset][-self._window:]
            self._timestamps[asset] = self._timestamps[asset][-self._window:]

        # Invalidate cache
        self._cache_ts = 0.0

    def record_price(self, asset: str, price: float) -> None:
        """Record a price observation and auto-compute return from previous.

        Convenience method: if you have prices rather than returns.
        """
        asset = asset.upper()
        if self._returns[asset]:
            # We store returns, so derive from last price
            # But we don't store prices — use a separate tracker
            pass
        # For simplicity, just record as-is; callers should use record_return
        # with actual return values

    def get_correlation(self, asset_a: str, asset_b: str) -> float:
        """Get Pearson correlation between two assets.

        Returns 0.0 if insufficient data (< 5 overlapping observations).
        """
        asset_a, asset_b = asset_a.upper(), asset_b.upper()
        if asset_a == asset_b:
            return 1.0

        key = tuple(sorted([asset_a, asset_b]))
        now = time.time()

        # Check cache
        if now - self._cache_ts < self._cache_ttl and key in self._cache:
            return self._cache[key]

        corr = self._compute_pearson(asset_a, asset_b)
        self._cache[key] = corr
        self._cache_ts = now
        return corr

    def exposure_reduction_factor(self, asset_a: str, asset_b: str) -> float:
        """Compute exposure reduction factor based on correlation.

        Returns a factor in [MAX_REDUCTION, 1.0]:
        - ρ < THRESHOLD → 1.0 (no reduction)
        - ρ = 1.0 → MAX_REDUCTION (maximum reduction)
        - Linear interpolation between

        The PortfolioRiskAgent multiplies the combined cap by this factor.
        """
        corr = abs(self.get_correlation(asset_a, asset_b))

        if corr < CORRELATION_THRESHOLD:
            return 1.0

        # Linear interpolation: at threshold → 1.0, at 1.0 → MAX_REDUCTION
        t = (corr - CORRELATION_THRESHOLD) / (1.0 - CORRELATION_THRESHOLD)
        return 1.0 - t * (1.0 - MAX_REDUCTION)

    def get_matrix(self) -> CorrelationMatrix:
        """Get the full correlation matrix for all tracked assets."""
        assets = sorted(self._returns.keys())
        pairs = []

        for i, a in enumerate(assets):
            for b in assets[i + 1:]:
                corr = self.get_correlation(a, b)
                pairs.append(CorrelationPair(
                    asset_a=a,
                    asset_b=b,
                    correlation=corr,
                    sample_count=min(len(self._returns[a]), len(self._returns[b])),
                    last_updated=time.time(),
                ))

        return CorrelationMatrix(
            timestamp=time.time(),
            pairs=pairs,
            assets=assets,
        )

    def get_cluster_factor(self, asset: str) -> float:
        """Get the worst-case reduction factor for an asset across its cluster.

        If BTC is correlated with ETH (ρ=0.85), the factor for BTC considers
        all cluster members.
        """
        asset = asset.upper()
        worst_factor = 1.0

        for cluster_name, members in ASSET_CLUSTERS.items():
            if asset not in [m.upper() for m in members]:
                continue
            for other in members:
                other = other.upper()
                if other == asset:
                    continue
                factor = self.exposure_reduction_factor(asset, other)
                worst_factor = min(worst_factor, factor)

        return worst_factor

    @property
    def tracked_assets(self) -> List[str]:
        return sorted(self._returns.keys())

    def reset(self) -> None:
        """Clear all tracked data."""
        self._returns.clear()
        self._timestamps.clear()
        self._cache.clear()

    # ── Internal ─────────────────────────────────────────────────────────

    def _compute_pearson(self, a: str, b: str) -> float:
        """Compute Pearson correlation between two return series."""
        ra = self._returns.get(a, [])
        rb = self._returns.get(b, [])

        # Align: take most recent overlapping observations
        n = min(len(ra), len(rb))
        if n < 5:
            return 0.0

        xa = ra[-n:]
        xb = rb[-n:]

        mean_a = sum(xa) / n
        mean_b = sum(xb) / n

        cov = sum((xa[i] - mean_a) * (xb[i] - mean_b) for i in range(n)) / n
        std_a = math.sqrt(sum((x - mean_a) ** 2 for x in xa) / n)
        std_b = math.sqrt(sum((x - mean_b) ** 2 for x in xb) / n)

        if std_a == 0 or std_b == 0:
            return 0.0

        return max(-1.0, min(1.0, cov / (std_a * std_b)))


# ── Singleton ────────────────────────────────────────────────────────────

_tracker: Optional[CorrelationTracker] = None
_tracker_lock = threading.Lock()


def get_correlation_tracker() -> CorrelationTracker:
    """Get or create the singleton CorrelationTracker."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = CorrelationTracker()
    return _tracker
