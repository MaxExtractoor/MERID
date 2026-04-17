"""Source reliability tracking for Stage 6 consensus."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("core.source_health")


@dataclass
class SourceHealth:
    """Rolling health metrics for an external API source."""

    source: str
    srw: float = 1.0  # Source Reliability Weight [0.25, 1.0]
    success_rate: float = 1.0
    fallback_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_calls: int = 0
    successful_calls: int = 0
    fallback_used: int = 0
    latency_sum_ms: float = 0.0
    status: str = "active"  # active, degraded, quarantined
    updated_at: float = field(default_factory=lambda: time.time())

    def record_call(
        self,
        success: bool,
        fallback: bool,
        latency_ms: float,
    ) -> None:
        """Record a single API call outcome and recompute SRW."""
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        if fallback:
            self.fallback_used += 1
        self.latency_sum_ms += latency_ms

        # Recompute rolling averages
        self.success_rate = self.successful_calls / self.total_calls if self.total_calls > 0 else 1.0
        self.fallback_rate = self.fallback_used / self.total_calls if self.total_calls > 0 else 0.0
        self.avg_latency_ms = self.latency_sum_ms / self.total_calls if self.total_calls > 0 else 0.0

        # Recompute SRW
        self._recompute_srw()
        self.updated_at = time.time()

    def _recompute_srw(self) -> None:
        """
        Compute Source Reliability Weight using the canonical formula:
        
        SRW = clamp(
            (0.6 * success_rate)
            + (0.3 * (1 - fallback_rate))
            + (0.1 * (1 - latency_penalty)),
            0.25,
            1.0
        )
        
        where latency_penalty = clamp(avg_latency_ms / 5000, 0, 1)
        """
        latency_penalty = min(max(self.avg_latency_ms / 5000.0, 0.0), 1.0)
        raw_srw = (
            (0.6 * self.success_rate)
            + (0.3 * (1.0 - self.fallback_rate))
            + (0.1 * (1.0 - latency_penalty))
        )
        self.srw = min(max(raw_srw, 0.25), 1.0)

    def to_dict(self) -> Dict[str, float]:
        """Serialize for API exposure."""
        return {
            "source": self.source,
            "srw": round(self.srw, 4),
            "success_rate": round(self.success_rate, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_calls": self.total_calls,
            "updated_at": self.updated_at,
        }


class SourceHealthRegistry:
    """Global registry tracking health for all external sources."""

    def __init__(self) -> None:
        self._sources: Dict[str, SourceHealth] = {}

    def record(
        self,
        source: str,
        success: bool,
        fallback: bool,
        latency_ms: float,
    ) -> None:
        """Record a call outcome and update source health."""
        if source not in self._sources:
            self._sources[source] = SourceHealth(source=source)
        self._sources[source].record_call(success, fallback, latency_ms)
        logger.debug(
            "Source %s health updated: SRW=%.3f, success=%.2f, fallback=%.2f",
            source,
            self._sources[source].srw,
            self._sources[source].success_rate,
            self._sources[source].fallback_rate,
        )

    def get_srw(self, source: str) -> float:
        """Get current SRW for a source (defaults to 1.0 if unknown)."""
        return self._sources.get(source, SourceHealth(source=source)).srw

    def get_health(self, source: str) -> Optional[SourceHealth]:
        """Get full health object for a source."""
        return self._sources.get(source)

    def all_sources(self) -> Dict[str, SourceHealth]:
        """Return all tracked sources."""
        return self._sources.copy()

    def snapshot(self) -> Dict[str, Dict]:
        """Serialize all source health for API exposure."""
        return {name: health.to_dict() for name, health in self._sources.items()}


# Global singleton
_registry = SourceHealthRegistry()


def get_source_registry() -> SourceHealthRegistry:
    """Access the global source health registry."""
    return _registry
