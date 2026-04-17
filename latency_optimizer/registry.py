"""Lightweight registry for correlating latency decisions with other systems."""
from __future__ import annotations

from typing import Dict, Optional

from latency_optimizer.policies import OptimizationDecision


class LatencyDecisionRegistry:
    def __init__(self) -> None:
        self._store: Dict[str, OptimizationDecision] = {}

    def record(self, key: str, decision: OptimizationDecision) -> None:
        self._store[key] = decision

    def consume(self, key: str) -> Optional[OptimizationDecision]:
        return self._store.pop(key, None)


_registry = LatencyDecisionRegistry()


def record_latency_decision(key: str, decision: OptimizationDecision) -> None:
    if key:
        _registry.record(key, decision)


def consume_latency_decision(key: str) -> Optional[OptimizationDecision]:
    if not key:
        return None
    return _registry.consume(key)
