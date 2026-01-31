"""
Moat-aware resource allocation engine.

Allocates engineering/compute budget across moat domains using impact,
defensibility, and urgency inputs to ensure capital flows to the strongest
compounders first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ResourceRequest:
    request_id: str
    domain: str
    required_budget: float
    impact_score: float
    defensibility_score: float
    urgency_score: float


@dataclass
class AllocationDecision:
    request_id: str
    allocated_budget: float
    allocation_ratio: float
    rationale: str


class MoatResourceAllocator:
    def __init__(self, domain_caps: Dict[str, float]) -> None:
        self._domain_caps = domain_caps

    def allocate(self, requests: List[ResourceRequest]) -> List[AllocationDecision]:
        decisions: List[AllocationDecision] = []
        for domain, cap in self._domain_caps.items():
            domain_requests = [req for req in requests if req.domain == domain]
            if not domain_requests:
                continue
            scores = self._score_requests(domain_requests)
            remaining = cap
            for request, score in scores:
                if remaining <= 0:
                    break
                allocated = min(request.required_budget, remaining * score)
                remaining -= allocated
                decisions.append(
                    AllocationDecision(
                        request_id=request.request_id,
                        allocated_budget=allocated,
                        allocation_ratio=allocated / max(request.required_budget, 1e-6),
                        rationale=f"impact={request.impact_score:.2f}, defensibility={request.defensibility_score:.2f}, urgency={request.urgency_score:.2f}",
                    )
                )
        return decisions

    def _score_requests(self, requests: List[ResourceRequest]) -> List[tuple[ResourceRequest, float]]:
        scored = []
        for request in requests:
            numerator = (
                request.impact_score * 0.4
                + request.defensibility_score * 0.35
                + request.urgency_score * 0.25
            )
            score = numerator / max(request.required_budget, 1e-6)
            scored.append((request, score))
        return sorted(scored, key=lambda pair: pair[1], reverse=True)
