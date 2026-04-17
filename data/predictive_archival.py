"""
Predictive data archival planner.

Forecasts storage growth per dataset and schedules archival/migration tasks
before storage tiers hit capacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List
import statistics


@dataclass
class DatasetUsage:
    dataset_id: str
    storage_gb: float
    timestamp: datetime


@dataclass
class ArchivalPlan:
    dataset_id: str
    target_tier: str
    execute_at: datetime
    reason: str


class PredictiveArchivalPlanner:
    def __init__(self, capacity_gb: float = 10_000.0) -> None:
        self.capacity_gb = capacity_gb
        self._history: Dict[str, List[DatasetUsage]] = {}

    def record_usage(self, usage: DatasetUsage) -> None:
        series = self._history.setdefault(usage.dataset_id, [])
        series.append(usage)
        series[:] = series[-200:]

    def forecast(self, dataset_id: str) -> ArchivalPlan | None:
        series = self._history.get(dataset_id, [])
        if len(series) < 3:
            return None
        usage_sorted = sorted(series, key=lambda entry: entry.timestamp)
        growth = self._estimate_growth(usage_sorted)
        current = usage_sorted[-1]
        if growth <= 0:
            return None
        minutes_until_full = (self.capacity_gb - current.storage_gb) / growth
        if minutes_until_full < 0:
            minutes_until_full = 0
        execute_at = current.timestamp + timedelta(minutes=minutes_until_full * 0.5)
        return ArchivalPlan(
            dataset_id=dataset_id,
            target_tier="archive",
            execute_at=execute_at,
            reason=f"Predicting capacity hit in {minutes_until_full:.1f} minutes",
        )

    def _estimate_growth(self, series: List[DatasetUsage]) -> float:
        if len(series) < 2:
            return 0.0
        values = [entry.storage_gb for entry in series]
        times = [(entry.timestamp - series[0].timestamp).total_seconds() / 60 for entry in series]
        mean_t = statistics.mean(times)
        mean_v = statistics.mean(values)
        numerator = sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values))
        denominator = sum((t - mean_t) ** 2 for t in times) or 1.0
        return numerator / denominator
