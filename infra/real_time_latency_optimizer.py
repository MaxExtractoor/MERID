"""
Real-time latency optimization service.

Streams latency probes from agents, reranks network paths, and emits routing
suggestions that keep the swarm under tight SLA budgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class LatencyProbe:
    path_id: str
    latency_ms: float
    jitter_ms: float
    timestamp: datetime


@dataclass
class LatencyRecommendation:
    preferred_path: str
    average_latency_ms: float
    rationale: str


class RealTimeLatencyOptimizer:
    def __init__(self, window: int = 20) -> None:
        self.window = window
        self._probes: Dict[str, List[LatencyProbe]] = {}

    def record_probe(self, probe: LatencyProbe) -> None:
        series = self._probes.setdefault(probe.path_id, [])
        series.append(probe)
        series[:] = series[-self.window :]

    def recommend(self) -> LatencyRecommendation | None:
        if not self._probes:
            return None
        stats = [
            (
                path_id,
                sum(probe.latency_ms for probe in probes) / len(probes),
                sum(probe.jitter_ms for probe in probes) / len(probes),
            )
            for path_id, probes in self._probes.items()
            if probes
        ]
        path, latency, jitter = min(stats, key=lambda item: (item[1], item[2]))
        rationale = f"Latency {latency:.2f} ms, jitter {jitter:.2f} ms over last {self.window} probes"
        return LatencyRecommendation(preferred_path=path, average_latency_ms=latency, rationale=rationale)
