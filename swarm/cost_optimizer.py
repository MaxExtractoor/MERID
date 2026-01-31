"""
Cost optimization across providers.

Aggregates spend per model/provider, compares against utilization, and suggests
cheaper alternatives when performance deltas are acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ProviderCost:
    provider_id: str
    avg_latency_ms: float
    success_rate: float
    cost_per_token_usd: float
    monthly_volume_tokens: int

    @property
    def monthly_spend(self) -> float:
        return self.cost_per_token_usd * self.monthly_volume_tokens


class ProviderCostOptimizer:
    def __init__(self) -> None:
        self._costs: Dict[str, ProviderCost] = {}

    def record_cost(self, cost: ProviderCost) -> None:
        self._costs[cost.provider_id] = cost

    def optimization_candidates(self, max_latency_increase_ms: float = 50.0, min_success_rate: float = 0.9) -> List[tuple[str, str]]:
        providers = list(self._costs.values())
        candidates: List[tuple[str, str]] = []
        for expensive in providers:
            for cheaper in providers:
                if cheaper.cost_per_token_usd < expensive.cost_per_token_usd and cheaper.success_rate >= min_success_rate:
                    if cheaper.avg_latency_ms - expensive.avg_latency_ms <= max_latency_increase_ms:
                        candidates.append((expensive.provider_id, cheaper.provider_id))
        return candidates
