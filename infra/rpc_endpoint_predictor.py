"""
ML-based RPC endpoint prediction service.

Maintains rolling latency/failure metrics per provider and uses a lightweight
scoring function to recommend the next endpoint that should be promoted to
primary for a given chain/region.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class EndpointMetrics:
    provider: str
    chain: str
    region: str
    latency_ms: float
    success_rate: float
    cost_per_million: float
    last_updated: datetime = field(default_factory=datetime.utcnow)


class RpcEndpointPredictor:
    def __init__(self) -> None:
        self._metrics: Dict[str, EndpointMetrics] = {}

    def record_metrics(self, metrics: EndpointMetrics) -> None:
        key = self._key(metrics.provider, metrics.chain, metrics.region)
        self._metrics[key] = metrics

    def predict_best(self, chain: str, region: str) -> EndpointMetrics | None:
        candidates = [metrics for metrics in self._metrics.values() if metrics.chain == chain and metrics.region == region]
        if not candidates:
            return None
        scored = sorted(candidates, key=self._score, reverse=True)
        return scored[0]

    def _score(self, metrics: EndpointMetrics) -> float:
        latency_score = max(0.0, 1.0 - metrics.latency_ms / 500)
        reliability_score = metrics.success_rate
        cost_score = max(0.0, 1.0 - metrics.cost_per_million / 500)
        return latency_score * 0.4 + reliability_score * 0.4 + cost_score * 0.2

    def _key(self, provider: str, chain: str, region: str) -> str:
        return f"{provider}:{chain}:{region}"
