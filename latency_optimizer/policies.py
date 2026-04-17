"""Latency-aware optimization policies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from latency_optimizer.config import FallbackStrategy, SLODefinition, get_slo
import threading


@dataclass(frozen=True)
class OptimizationDecision:
    domain: str
    workflow: str
    observed_ms: float
    status: str
    fallback: Optional[FallbackStrategy]
    slo: Optional[SLODefinition]


class LatencyOptimizerPolicy:
    def evaluate(self, domain: str, workflow: str, observed_ms: float) -> Optional[OptimizationDecision]:
        slo = get_slo(domain, workflow)
        if slo is None:
            return None

        if observed_ms <= slo.budget.p50_ms:
            status = "within_budget"
            fallback = None
        elif observed_ms <= slo.budget.p95_ms:
            status = "approaching_budget"
            fallback = slo.fallback_chain[0] if slo.fallback_chain else None
        elif observed_ms <= slo.budget.hard_deadline_ms:
            status = "breached_slo"
            fallback = slo.fallback_chain[-1] if slo.fallback_chain else None
        else:
            status = "deadline_violation"
            fallback = slo.fallback_chain[-1] if slo.fallback_chain else None

        return OptimizationDecision(
            domain=domain,
            workflow=workflow,
            observed_ms=observed_ms,
            status=status,
            fallback=fallback,
            slo=slo,
        )


_policy: Optional[LatencyOptimizerPolicy] = None
_policy_lock = threading.Lock()


def get_latency_policy() -> LatencyOptimizerPolicy:
    global _policy
    if _policy is None:
        with _policy_lock:
            if _policy is None:
                _policy = LatencyOptimizerPolicy()
    return _policy
