"""
Dynamic feature prioritization based on moat impact.

Scores roadmap features using impact, urgency, cost, and moat contribution so
leadership can focus on upgrades that strengthen defensive layers first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class FeatureCandidate:
    feature_id: str
    description: str
    moat_domain: str
    impact_score: float
    urgency_score: float
    cost_score: float
    moat_contribution: float
    created_at: datetime


@dataclass
class FeaturePriority:
    feature_id: str
    priority: float
    rationale: str


class FeaturePrioritizationEngine:
    def rank(self, candidates: List[FeatureCandidate], limit: int = 10) -> List[FeaturePriority]:
        priorities: List[FeaturePriority] = []
        for candidate in candidates:
            benefit = (
                candidate.impact_score * 0.35
                + candidate.urgency_score * 0.25
                + candidate.moat_contribution * 0.3
            )
            penalty = candidate.cost_score * 0.2
            score = benefit - penalty
            rationale = (
                f"impact={candidate.impact_score:.2f}, urgency={candidate.urgency_score:.2f}, "
                f"moat={candidate.moat_contribution:.2f}, cost={candidate.cost_score:.2f}"
            )
            priorities.append(FeaturePriority(feature_id=candidate.feature_id, priority=score, rationale=rationale))
        return sorted(priorities, key=lambda item: item.priority, reverse=True)[:limit]
