"""
Advanced anomaly detection (ML-based) for network and agent telemetry.

Uses rolling feature windows and placeholder ML scoring (e.g., Isolation Forest)
to detect anomalous latency, error spikes, or behavior shifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from collections import deque
import statistics


@dataclass
class TelemetryPoint:
    key: str
    value: float


class MLAnomalyDetector:
    def __init__(self, window_size: int = 50, threshold: float = 3.0) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self._history: Dict[str, deque[float]] = {}

    def record(self, metric: str, value: float) -> bool:
        history = self._history.setdefault(metric, deque(maxlen=self.window_size))
        history.append(value)
        return self._is_anomalous(history, value)

    def _is_anomalous(self, history: deque[float], value: float) -> bool:
        if len(history) < 10:
            return False
        mean = statistics.mean(history)
        stdev = statistics.pstdev(history) or 1.0
        z_score = abs(value - mean) / stdev
        return z_score > self.threshold
