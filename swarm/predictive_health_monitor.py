"""
Predictive health monitoring service.

Extends protocol health tracking with forecasting over metric history to flag
deviations before they breach thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime, timedelta
import statistics


@dataclass
class ForecastedMetric:
    metric_name: str
    current_value: float
    forecast_value: float
    breach_time: datetime | None
    confidence: float


class PredictiveHealthMonitor:
    def __init__(self, horizon_minutes: int = 60) -> None:
        self.horizon = timedelta(minutes=horizon_minutes)
        self._history: Dict[str, List[tuple[datetime, float]]] = {}

    def record_metric(self, metric_name: str, value: float) -> None:
        series = self._history.setdefault(metric_name, [])
        series.append((datetime.utcnow(), value))
        series[:] = series[-200:]

    def forecast(self, metric_name: str, threshold: float) -> ForecastedMetric | None:
        series = self._history.get(metric_name, [])
        if len(series) < 5:
            return None
        values = [value for _, value in series]
        slope = self._estimate_slope(series)
        forecast_value = values[-1] + slope * (self.horizon.total_seconds() / 60)
        breach_time = None
        if slope != 0:
            minutes_to_breach = (threshold - values[-1]) / slope
            if 0 < minutes_to_breach < self.horizon.total_seconds() / 60:
                breach_time = datetime.utcnow() + timedelta(minutes=minutes_to_breach)
        confidence = min(1.0, max(0.1, statistics.pvariance(values) or 0.1))
        return ForecastedMetric(metric_name=metric_name, current_value=values[-1], forecast_value=forecast_value, breach_time=breach_time, confidence=1 - confidence)

    def _estimate_slope(self, series: List[tuple[datetime, float]]) -> float:
        if len(series) < 2:
            return 0.0
        times = [(ts - series[0][0]).total_seconds() / 60 for ts, _ in series]
        values = [value for _, value in series]
        mean_t = statistics.mean(times)
        mean_v = statistics.mean(values)
        numerator = sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values))
        denominator = sum((t - mean_t) ** 2 for t in times) or 1.0
        return numerator / denominator
