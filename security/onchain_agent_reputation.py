"""
On-chain agent reputation system scaffolding.

Maintains reputation events and computes scores that can later be mirrored to
smart contracts. Integrates with decentralized signing/coordination layers to
ensure agents with poor behavior can be demoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class ReputationEvent:
    agent_id: str
    delta: float
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentReputationState:
    agent_id: str
    score: float = 0.5
    history: List[ReputationEvent] = field(default_factory=list)


class OnChainAgentReputation:
    def __init__(self) -> None:
        self._states: Dict[str, AgentReputationState] = {}

    def record_event(self, agent_id: str, delta: float, reason: str) -> AgentReputationState:
        state = self._states.setdefault(agent_id, AgentReputationState(agent_id=agent_id))
        event = ReputationEvent(agent_id=agent_id, delta=delta, reason=reason)
        state.history.append(event)
        state.score = max(0.0, min(1.0, state.score + delta))
        return state

    def get_state(self, agent_id: str) -> AgentReputationState:
        return self._states.setdefault(agent_id, AgentReputationState(agent_id=agent_id))
