"""
Agent performance benchmarking utilities.

Collects latency, success, and resource metrics per agent role to generate
leaderboards and identify underperforming configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class AgentMetric:
    agent_id: str
    task_type: str
    latency_ms: float
    success: bool
    cost_usd: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentBenchmark:
    agent_id: str
    avg_latency_ms: float
    success_rate: float
    avg_cost_usd: float
    sample_count: int


class AgentBenchmarkingService:
    def __init__(self) -> None:
        self._metrics: Dict[str, List[AgentMetric]] = {}

    def record_metric(self, metric: AgentMetric) -> None:
        self._metrics.setdefault(metric.agent_id, []).append(metric)

    def benchmark(self, agent_id: str) -> AgentBenchmark:
        metrics = self._metrics.get(agent_id, [])
        if not metrics:
            return AgentBenchmark(agent_id, 0.0, 0.0, 0.0, 0)
        avg_latency = sum(m.latency_ms for m in metrics) / len(metrics)
        success_rate = sum(1 for m in metrics if m.success) / len(metrics)
        avg_cost = sum(m.cost_usd for m in metrics) / len(metrics)
        return AgentBenchmark(agent_id=agent_id, avg_latency_ms=avg_latency, success_rate=success_rate, avg_cost_usd=avg_cost, sample_count=len(metrics))

    def leaderboard(self, limit: int = 10) -> List[AgentBenchmark]:
        scores = [self.benchmark(agent_id) for agent_id in self._metrics.keys()]
        return sorted(scores, key=lambda score: (score.success_rate, -score.avg_latency_ms), reverse=True)[:limit]
