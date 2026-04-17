"""
Data quality scoring and alerting utilities.

Tracks freshness, completeness, and anomaly counts per feed. Provides a basic
scorecard and emits alerts via logger for now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class FeedQualityMetrics:
    feed_name: str
    last_update: datetime = field(default_factory=datetime.utcnow)
    missing_ticks: int = 0
    anomaly_count: int = 0
    latency_ms: float = 0.0

    def score(self) -> float:
        penalty = self.missing_ticks * 0.1 + self.anomaly_count * 0.2 + (self.latency_ms / 1000) * 0.05
        return max(0.0, 1.0 - penalty)


class DataQualityScorer:
    def __init__(self) -> None:
        self._feeds: Dict[str, FeedQualityMetrics] = {}

    def record_update(self, feed: str, latency_ms: float, missing_ticks: int = 0, anomalies: int = 0) -> FeedQualityMetrics:
        metrics = self._feeds.setdefault(feed, FeedQualityMetrics(feed_name=feed))
        metrics.last_update = datetime.utcnow()
        metrics.latency_ms = latency_ms
        metrics.missing_ticks = missing_ticks
        metrics.anomaly_count = anomalies
        if metrics.score() < 0.5:
            logger.warning("Data quality alert for %s score %.2f", feed, metrics.score())
        return metrics

    def get_scores(self) -> Dict[str, float]:
        return {feed: metrics.score() for feed, metrics in self._feeds.items()}
