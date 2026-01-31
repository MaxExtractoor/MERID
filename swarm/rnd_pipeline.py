"""
Swarm R&D pipeline orchestrator for discovering and maturing new strategies.

Encodes the standardized flow: idea intake → research → build → eval → rollout,
with gating hooks so safety teams can observe each stage. Supports multiple
parallel experiments with status tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import logging
import uuid


logger = logging.getLogger(__name__)


class ExperimentStage(str, Enum):
    IDEA = "idea"
    RESEARCH = "research"
    BUILD = "build"
    EVAL = "eval"
    ROLLOUT = "rollout"
    ARCHIVED = "archived"


@dataclass
class RDExperiment:
    experiment_id: str
    title: str
    owner: str
    hypothesis: str
    stage: ExperimentStage = ExperimentStage.IDEA
    metrics: Dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    approvals: List[str] = field(default_factory=list)

    def advance(self, next_stage: ExperimentStage) -> None:
        self.stage = next_stage
        self.updated_at = datetime.utcnow()


class SwarmRDPipeline:
    """Manages lifecycle of research & development experiments."""

    def __init__(self) -> None:
        self._experiments: Dict[str, RDExperiment] = {}

    def submit_experiment(self, title: str, owner: str, hypothesis: str) -> RDExperiment:
        exp = RDExperiment(
            experiment_id=uuid.uuid4().hex[:12],
            title=title,
            owner=owner,
            hypothesis=hypothesis,
        )
        self._experiments[exp.experiment_id] = exp
        logger.info("R&D experiment %s submitted by %s", exp.experiment_id, owner)
        return exp

    def record_metric(self, experiment_id: str, name: str, value: float) -> None:
        exp = self._experiments[experiment_id]
        exp.metrics[name] = value
        exp.updated_at = datetime.utcnow()

    def advance_stage(self, experiment_id: str, next_stage: ExperimentStage, approval: Optional[str] = None) -> RDExperiment:
        exp = self._experiments[experiment_id]
        if approval:
            exp.approvals.append(approval)
        exp.advance(next_stage)
        logger.info("Experiment %s advanced to %s", experiment_id, next_stage)
        return exp

    def list_experiments(self, stage: Optional[ExperimentStage] = None) -> List[RDExperiment]:
        experiments = list(self._experiments.values())
        if stage:
            experiments = [exp for exp in experiments if exp.stage == stage]
        return experiments


_swarm_rd_pipeline: Optional[SwarmRDPipeline] = None


def get_swarm_rd_pipeline() -> SwarmRDPipeline:
    global _swarm_rd_pipeline
    if _swarm_rd_pipeline is None:
        _swarm_rd_pipeline = SwarmRDPipeline()
    return _swarm_rd_pipeline
