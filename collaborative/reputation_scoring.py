"""
Automated agent reputation scoring with ML-inspired signals.

Aggregates reliability metrics, collaboration outcomes, governance flags, and
peer attestations into a composite score used by the collaborative swarm layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class ReputationSignal:
    agent_id: str
    reliability: float
    task_success_rate: float
    governance_flags: int
    peer_attestations: int
    recency_days: int


@dataclass
class ReputationScore:
    agent_id: str
    score: float
    tier: str
    updated_at: datetime


class ReputationScoringEngine:
    def __init__(self) -> None:
        self._scores: Dict[str, ReputationScore] = {}

    def score(self, signal: ReputationSignal) -> ReputationScore:
        reliability_component = signal.reliability * 0.35
        success_component = signal.task_success_rate * 0.3
        governance_penalty = max(0.0, 1 - signal.governance_flags * 0.1)
        attestation_bonus = min(0.15, signal.peer_attestations * 0.02)
        recency_factor = max(0.7, 1 - signal.recency_days * 0.01)
        base_score = (reliability_component + success_component) * governance_penalty * recency_factor + attestation_bonus
        score = max(0.0, min(1.0, base_score))
        tier = self._tier(score)
        result = ReputationScore(agent_id=signal.agent_id, score=score, tier=tier, updated_at=datetime.utcnow())
        self._scores[signal.agent_id] = result
        return result

    def _tier(self, score: float) -> str:
        if score >= 0.8:
            return "platinum"
        if score >= 0.6:
            return "gold"
        if score >= 0.4:
            return "silver"
        return "bronze"

    def get_score(self, agent_id: str) -> ReputationScore | None:
        return self._scores.get(agent_id)
