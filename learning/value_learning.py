"""
Value learning engine that extracts reward signals from human interventions.

Phase 9 requires that human collaboration feedback directly shapes agent reward
models. This module consumes mentorship notes / operator actions and computes
policy adjustments or rule weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


@dataclass
class InterventionRecord:
    intervention_id: str
    agent_id: str
    operator: str
    signal: float
    context: Dict[str, object]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ValueProfile:
    agent_id: str
    cumulative_signal: float = 0.0
    interventions: List[InterventionRecord] = field(default_factory=list)
    last_updated: Optional[datetime] = None

    def apply_signal(self, record: InterventionRecord) -> None:
        self.interventions.append(record)
        self.cumulative_signal += record.signal
        self.last_updated = record.timestamp

    @property
    def average_signal(self) -> float:
        if not self.interventions:
            return 0.0
        return self.cumulative_signal / len(self.interventions)


class ValueLearningEngine:
    """Transforms interventions into reward adjustments."""

    def __init__(self) -> None:
        self._profiles: Dict[str, ValueProfile] = {}

    def record_intervention(
        self,
        intervention_id: str,
        agent_id: str,
        operator: str,
        signal: float,
        context: Optional[Dict[str, object]] = None,
    ) -> InterventionRecord:
        record = InterventionRecord(
            intervention_id=intervention_id,
            agent_id=agent_id,
            operator=operator,
            signal=signal,
            context=context or {},
        )
        profile = self._profiles.setdefault(agent_id, ValueProfile(agent_id=agent_id))
        profile.apply_signal(record)
        logger.info("Applied intervention %.2f to agent %s", signal, agent_id)
        return record

    def get_reward_adjustment(self, agent_id: str) -> float:
        profile = self._profiles.get(agent_id)
        if not profile:
            return 0.0
        # Use tanh-like clipping to keep adjustments bounded
        avg = profile.average_signal
        return max(min(avg, 1.0), -1.0)

    def get_profile(self, agent_id: str) -> Optional[ValueProfile]:
        return self._profiles.get(agent_id)

    def get_rankings(self) -> List[ValueProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.average_signal, reverse=True)


_value_learning_engine: Optional[ValueLearningEngine] = None


def get_value_learning_engine() -> ValueLearningEngine:
    global _value_learning_engine
    if _value_learning_engine is None:
        _value_learning_engine = ValueLearningEngine()
    return _value_learning_engine
