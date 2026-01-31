"""
Self-evolving system loop that coordinates reflection + optimization cycles.

This module ties together growth metrics, curriculum learning, agent pattern
reuse, and the A/B testing framework to ensure that MERID can continuously
improve while keeping guardrails in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging
import uuid

from learning.curriculum_learning import get_curriculum_planner
from learning.ab_testing_framework import get_ab_testing_framework
from swarm.agent_pattern_library import get_agent_pattern_library
from swarm.growth_metrics_tracker import get_growth_metrics_tracker


logger = logging.getLogger(__name__)


@dataclass
class EvolutionIteration:
    """Single reflection/optimization pass."""

    iteration_id: str
    created_at: datetime
    objective: str
    reflection_notes: List[str] = field(default_factory=list)
    optimization_actions: List[str] = field(default_factory=list)
    deployment_candidate: Optional[str] = None
    associated_experiment: Optional[str] = None
    outcome: Optional[str] = None


class SelfEvolutionLoop:
    """Coordinates reflection, optimization, and deployment for new agent ideas."""

    def __init__(self) -> None:
        self._iterations: List[EvolutionIteration] = []
        self._curriculum = get_curriculum_planner()
        self._ab_testing = get_ab_testing_framework()
        self._patterns = get_agent_pattern_library()
        self._metrics = get_growth_metrics_tracker()

    def start_iteration(self, objective: str) -> EvolutionIteration:
        iteration = EvolutionIteration(
            iteration_id=uuid.uuid4().hex[:12],
            created_at=datetime.utcnow(),
            objective=objective,
        )
        self._iterations.append(iteration)
        logger.info("Started self-evolution iteration %s", iteration.iteration_id)
        return iteration

    def record_reflection(self, iteration_id: str, note: str) -> None:
        iteration = self._get_iteration(iteration_id)
        iteration.reflection_notes.append(note)

    def plan_optimization(self, iteration_id: str, action: str) -> None:
        iteration = self._get_iteration(iteration_id)
        iteration.optimization_actions.append(action)

    def schedule_experiment(
        self,
        iteration_id: str,
        experiment_name: str,
        hypothesis: str,
        variants: List[tuple],
        metric: str = "sharpe_ratio",
    ) -> str:
        experiment = self._ab_testing.start_experiment(
            name=experiment_name,
            hypothesis=hypothesis,
            success_metric=metric,
            variants=variants,
            metadata={"iteration_id": iteration_id},
        )
        iteration = self._get_iteration(iteration_id)
        iteration.associated_experiment = experiment.experiment_id
        logger.info("Linked experiment %s to iteration %s", experiment.experiment_id, iteration_id)
        return experiment.experiment_id

    def recommend_patterns(self, capability: str, min_sharpe: float = 1.0) -> List[Dict[str, object]]:
        patterns = self._patterns.suggest_patterns(capability, min_sharpe=min_sharpe)
        return [
            {
                "pattern_id": p.pattern_id,
                "name": p.name,
                "strengths": p.strengths,
                "sharpe_ratio": p.success_metrics.get("sharpe_ratio"),
            }
            for p in patterns
        ]

    def assign_curriculum(self, agent_id: str, track_id: str) -> None:
        self._curriculum.assign_track(agent_id, track_id)

    def complete_iteration(self, iteration_id: str, outcome: str) -> EvolutionIteration:
        iteration = self._get_iteration(iteration_id)
        iteration.outcome = outcome
        self._metrics.record_innovation(
            innovation_type="self_evolution",
            name=iteration.objective,
            proposed_by="self_evolution_loop",
        )
        logger.info("Iteration %s completed outcome=%s", iteration_id, outcome)
        return iteration

    def get_iterations(self, limit: int = 20) -> List[EvolutionIteration]:
        return self._iterations[-limit:]

    def _get_iteration(self, iteration_id: str) -> EvolutionIteration:
        for iteration in self._iterations:
            if iteration.iteration_id == iteration_id:
                return iteration
        raise KeyError(f"Iteration '{iteration_id}' not found")


_self_evolution_loop: Optional[SelfEvolutionLoop] = None


def get_self_evolution_loop() -> SelfEvolutionLoop:
    global _self_evolution_loop
    if _self_evolution_loop is None:
        _self_evolution_loop = SelfEvolutionLoop()
    return _self_evolution_loop
