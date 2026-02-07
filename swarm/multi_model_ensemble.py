"""
Multi-model ensemble voting and adaptive selection utilities.

Combines outputs from heterogeneous models, applies weighted voting, and keeps
rolling performance stats so the orchestrator can automatically prefer models
that perform best for each task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime


@dataclass
class ModelOutput:
    model_id: str
    task_type: str
    content: str
    confidence: float
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ModelStats:
    successes: int = 0
    failures: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total else 0.0


@dataclass
class EnsembleVote:
    winning_content: str
    support_ratio: float
    participating_models: List[str]


class MultiModelEnsemble:
    def __init__(self) -> None:
        self._stats: Dict[str, ModelStats] = {}

    def aggregate_votes(self, outputs: List[ModelOutput]) -> EnsembleVote:
        if not outputs:
            raise ValueError("No model outputs provided")
        weight_sum: Dict[str, float] = {}
        for output in outputs:
            weight = output.confidence * (1.0 + self._stats.get(output.model_id, ModelStats()).success_rate)
            weight_sum[output.content] = weight_sum.get(output.content, 0.0) + weight
        winning_content = max(weight_sum.items(), key=lambda item: item[1])[0]
        support_ratio = weight_sum[winning_content] / sum(weight_sum.values())
        return EnsembleVote(winning_content=winning_content, support_ratio=support_ratio, participating_models=[o.model_id for o in outputs])

    def update_performance(self, model_id: str, success: bool) -> None:
        stats = self._stats.setdefault(model_id, ModelStats())
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
        stats.last_updated = datetime.utcnow()

    def best_model_for_task(self, task_type: str, candidates: List[str]) -> str:
        scored = []
        for candidate in candidates:
            stats = self._stats.get(candidate, ModelStats())
            scored.append((stats.success_rate, candidate))
        scored.sort(reverse=True)
        return scored[0][1] if scored else candidates[0]
