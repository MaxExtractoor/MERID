"""
ML-based idea prioritization engine for Swarm Lab.

Scores R&D ideas by combining impact, effort, confidence, and historical win
rates so the lab can focus on the most promising experiments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class IdeaSubmission:
    idea_id: str
    title: str
    impact_score: float
    effort_score: float
    confidence_score: float
    historical_success_rate: float
    submitted_at: datetime


@dataclass
class PrioritizedIdea:
    idea_id: str
    title: str
    priority: float
    rationale: str


class IdeaPrioritizer:
    def __init__(self) -> None:
        self._ideas: Dict[str, IdeaSubmission] = {}

    def submit(self, idea: IdeaSubmission) -> None:
        self._ideas[idea.idea_id] = idea

    def prioritize(self, limit: int = 5) -> List[PrioritizedIdea]:
        scored: List[PrioritizedIdea] = []
        for idea in self._ideas.values():
            score = (
                idea.impact_score * 0.4
                + (1 - idea.effort_score) * 0.2
                + idea.confidence_score * 0.2
                + idea.historical_success_rate * 0.2
            )
            rationale = (
                f"Impact {idea.impact_score:.2f}, effort {idea.effort_score:.2f}, "
                f"confidence {idea.confidence_score:.2f}, success {idea.historical_success_rate:.2f}"
            )
            scored.append(PrioritizedIdea(idea_id=idea.idea_id, title=idea.title, priority=score, rationale=rationale))
        scored.sort(key=lambda idea: idea.priority, reverse=True)
        return scored[:limit]
