from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SourceMetrics:
    source: str
    last_batch_at: float = 0.0
    last_count: int = 0
    total_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    stale_threshold_sec: float = 300.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def register_batch(self, count: int, latency_ms: float, metadata: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        self.last_batch_at = now
        self.last_count = count
        self.total_count += count
        if metadata:
            self.metadata.update(metadata)

        if self.avg_latency_ms == 0.0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = (self.avg_latency_ms * 0.8) + (latency_ms * 0.2)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)

    def register_error(self) -> None:
        self.error_count += 1

    def as_dict(self) -> Dict[str, Any]:
        last_age = time.time() - self.last_batch_at if self.last_batch_at else None
        return {
            "source": self.source,
            "last_batch_ts": self.last_batch_at,
            "last_batch_age_sec": last_age,
            "last_batch_count": self.last_count,
            "total_count": self.total_count,
            "error_count": self.error_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "max_latency_ms": round(self.max_latency_ms, 2),
            "stale": bool(last_age and last_age > self.stale_threshold_sec),
            "metadata": self.metadata,
        }


class SocialDataQualityMonitor:
    """Tracks freshness and quality of social ingestion feeds."""

    def __init__(self) -> None:
        self._sources: Dict[str, SourceMetrics] = {}

    def _get_source(self, source: str) -> SourceMetrics:
        if source not in self._sources:
            self._sources[source] = SourceMetrics(source=source)
        return self._sources[source]

    def record_batch(
        self,
        source: str,
        count: int,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        metrics = self._get_source(source)
        metrics.register_batch(count, latency_ms, metadata)

    def record_error(self, source: str) -> None:
        metrics = self._get_source(source)
        metrics.register_error()

    def get_status(self) -> Dict[str, Any]:
        total_errors = sum(src.error_count for src in self._sources.values())
        total_events = sum(src.total_count for src in self._sources.values())
        sources = {name: metrics.as_dict() for name, metrics in self._sources.items()}
        return {
            "sources": sources,
            "aggregate": {
                "total_events": total_events,
                "total_errors": total_errors,
                "source_count": len(self._sources),
            },
        }


_data_quality_monitor: Optional[SocialDataQualityMonitor] = None
_data_quality_monitor_lock = threading.Lock()


def get_social_data_quality_monitor() -> SocialDataQualityMonitor:
    global _data_quality_monitor
    if _data_quality_monitor is None:
        with _data_quality_monitor_lock:
            if _data_quality_monitor is None:
                _data_quality_monitor = SocialDataQualityMonitor()
    return _data_quality_monitor
