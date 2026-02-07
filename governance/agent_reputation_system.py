"""
Agent reputation and trust scoring for capital allocation.

This module aggregates performance, reliability, compliance, and human feedback
signals to determine trust tiers for each agent. Capital allocations and
capability gating can reference these scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


@dataclass
class ReputationSignal:
    signal_type: str
    value: float
    weight: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class AgentReputation:
    agent_id: str
    signals: List[ReputationSignal] = field(default_factory=list)
    score: float = 0.0
    last_updated: Optional[datetime] = None
    tier: str = "baseline"

    def recalc(self) -> None:
        if not self.signals:
            self.score = 0.0
            self.tier = "baseline"
            return
        total_weight = sum(signal.weight for signal in self.signals)
        weighted_sum = sum(signal.value * signal.weight for signal in self.signals)
        self.score = weighted_sum / total_weight if total_weight else 0.0
        self.last_updated = datetime.utcnow()
        self.tier = self._tier_from_score(self.score)

    @staticmethod
    def _tier_from_score(score: float) -> str:
        if score >= 0.75:
            return "trusted"
        if score >= 0.5:
            return "preferred"
        if score <= -0.25:
            return "restricted"
        return "baseline"


class AgentReputationSystem:
    """Maintains reputational data for agents."""

    def __init__(self) -> None:
        self._records: Dict[str, AgentReputation] = {}

    def add_signal(
        self,
        agent_id: str,
        signal_type: str,
        value: float,
        weight: float = 1.0,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ReputationSignal:
        record = self._records.setdefault(agent_id, AgentReputation(agent_id=agent_id))
        signal = ReputationSignal(
            signal_type=signal_type,
            value=value,
            weight=weight,
            metadata=metadata or {},
        )
        record.signals.append(signal)
        record.recalc()
        logger.debug("Reputation updated for %s score=%.2f tier=%s", agent_id, record.score, record.tier)
        return signal

    def get_reputation(self, agent_id: str) -> Optional[AgentReputation]:
        return self._records.get(agent_id)

    def rank_agents(self) -> List[AgentReputation]:
        return sorted(self._records.values(), key=lambda r: r.score, reverse=True)


_agent_reputation_system: Optional[AgentReputationSystem] = None


def get_agent_reputation_system() -> AgentReputationSystem:
    global _agent_reputation_system
    if _agent_reputation_system is None:
        _agent_reputation_system = AgentReputationSystem()
    return _agent_reputation_system
