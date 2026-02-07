"""
Advanced capability matching algorithms for collaborative swarm.

Combines vector similarity, rule-based filters, and trust-aware reranking to
match tasks with ideal agent cohorts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import math


@dataclass
class CapabilityProfile:
    agent_id: str
    embedding: List[float]
    tags: List[str]
    trust_score: float


@dataclass
class MatchResult:
    agent_id: str
    score: float
    rationale: str


class CapabilityMatcher:
    def __init__(self) -> None:
        self._profiles: Dict[str, CapabilityProfile] = {}

    def add_profile(self, profile: CapabilityProfile) -> None:
        self._profiles[profile.agent_id] = profile

    def match(self, query_embedding: List[float], required_tags: List[str], min_trust: float = 0.4, limit: int = 5) -> List[MatchResult]:
        results: List[MatchResult] = []
        for profile in self._profiles.values():
            if profile.trust_score < min_trust:
                continue
            if not set(required_tags).issubset(set(profile.tags)):
                continue
            sim = self._cosine_similarity(query_embedding, profile.embedding)
            score = sim * 0.7 + profile.trust_score * 0.3
            results.append(MatchResult(agent_id=profile.agent_id, score=score, rationale=f"similarity={sim:.2f}, trust={profile.trust_score:.2f}"))
        return sorted(results, key=lambda r: r.score, reverse=True)[:limit]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (norm_a * norm_b)
