"""
Automated moat erosion detection.

Compares advantage metrics to benchmarks over time to detect erosion trends so
leaders can reinvest in weakening areas before the moat collapses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List


@dataclass
class AdvantageSample:
    metric: str
    our_value: float
    benchmark: float
    timestamp: datetime


@dataclass
class ErosionAlert:
    metric: str
    erosion_rate: float
    message: str
    detected_at: datetime


class MoatErosionDetector:
    def __init__(self, window_days: int = 14, erosion_threshold: float = 0.05) -> None:
        self.window_days = window_days
        self.erosion_threshold = erosion_threshold
        self._history: Dict[str, List[AdvantageSample]] = {}

    def record(self, sample: AdvantageSample) -> None:
        history = self._history.setdefault(sample.metric, [])
        history.append(sample)
        cutoff = sample.timestamp - timedelta(days=self.window_days)
        self._history[sample.metric] = [point for point in history if point.timestamp >= cutoff]

    def detect(self, metric: str) -> ErosionAlert | None:
        history = self._history.get(metric, [])
        if len(history) < 2:
            return None
        start = history[0]
        end = history[-1]
        start_advantage = start.our_value / max(start.benchmark, 1e-6)
        end_advantage = end.our_value / max(end.benchmark, 1e-6)
        erosion = (start_advantage - end_advantage) / max(start_advantage, 1e-6)
        if erosion <= self.erosion_threshold:
            return None
        return ErosionAlert(
            metric=metric,
            erosion_rate=erosion,
            message=f"{metric} advantage eroded by {erosion*100:.1f}% over {self.window_days} days",
            detected_at=end.timestamp,
        )
