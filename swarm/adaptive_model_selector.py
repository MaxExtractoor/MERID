"""
Adaptive model selection based on task performance.

Maintains per-task metrics for each model provider and suggests the best option
given latency/cost/reliability targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class ModelPerformance:
    latency_ms: float
    cost_usd: float
    success_rate: float
    last_updated: datetime


class AdaptiveModelSelector:
    def __init__(self) -> None:
        self._metrics: Dict[str, Dict[str, ModelPerformance]] = {}

    def record_metrics(self, task_type: str, model_id: str, latency_ms: float, cost_usd: float, success_rate: float) -> None:
        self._metrics.setdefault(task_type, {})[model_id] = ModelPerformance(latency_ms=latency_ms, cost_usd=cost_usd, success_rate=success_rate, last_updated=datetime.utcnow())

    def best_model(self, task_type: str, max_latency_ms: float, max_cost_usd: float) -> str:
        options = self._metrics.get(task_type, {})
        scored: List[tuple[float, str]] = []
        for model_id, perf in options.items():
            if perf.latency_ms <= max_latency_ms and perf.cost_usd <= max_cost_usd:
                score = perf.success_rate - (perf.latency_ms / max_latency_ms) * 0.1 - (perf.cost_usd / max_cost_usd) * 0.1
                scored.append((score, model_id))
        scored.sort(reverse=True)
        return scored[0][1] if scored else next(iter(options), "")
