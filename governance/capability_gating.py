"""
Capability gating service based on reliability scores and governance approvals.

Used by the exponential growth layer to ensure that new agents or features only
unlock additional powers after proving reliability and passing review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


class CapabilityLevel(Enum):
    OBSERVE = "observe"
    SUGGEST = "suggest"
    EXECUTE = "execute"
    GOVERN = "govern"


@dataclass
class CapabilityGate:
    capability: CapabilityLevel
    min_reliability: float
    approvals_required: int
    grace_period_hours: int = 0


@dataclass
class AgentCapabilityState:
    agent_id: str
    reliability_score: float
    granted_capabilities: List[CapabilityLevel] = field(default_factory=list)
    pending_capabilities: Dict[CapabilityLevel, datetime] = field(default_factory=dict)


class CapabilityGatingService:
    def __init__(self) -> None:
        self._gates: Dict[CapabilityLevel, CapabilityGate] = {}
        self._agents: Dict[str, AgentCapabilityState] = {}

    def register_gate(
        self,
        capability: CapabilityLevel,
        min_reliability: float,
        approvals_required: int,
        grace_period_hours: int = 0,
    ) -> None:
        self._gates[capability] = CapabilityGate(
            capability=capability,
            min_reliability=min_reliability,
            approvals_required=approvals_required,
            grace_period_hours=grace_period_hours,
        )
        logger.info("Registered gate %s min_reliability=%.2f approvals=%d",
                    capability.value, min_reliability, approvals_required)

    def update_agent_reliability(self, agent_id: str, score: float) -> None:
        state = self._agents.setdefault(
            agent_id,
            AgentCapabilityState(agent_id=agent_id, reliability_score=score),
        )
        state.reliability_score = score

    def request_capability(self, agent_id: str, capability: CapabilityLevel) -> bool:
        gate = self._gates.get(capability)
        if not gate:
            raise KeyError(f"Capability gate '{capability.value}' not configured")

        state = self._agents.setdefault(
            agent_id,
            AgentCapabilityState(agent_id=agent_id, reliability_score=0.0),
        )
        if state.reliability_score < gate.min_reliability:
            logger.warning(
                "Agent %s reliability %.2f below requirement %.2f for %s",
                agent_id,
                state.reliability_score,
                gate.min_reliability,
                capability.value,
            )
            return False

        if capability in state.granted_capabilities:
            return True

        state.pending_capabilities[capability] = datetime.utcnow()
        logger.info("Capability %s pending for agent %s", capability.value, agent_id)
        return True

    def grant_capability(self, agent_id: str, capability: CapabilityLevel) -> None:
        state = self._agents.get(agent_id)
        if not state:
            raise KeyError(f"Agent '{agent_id}' not registered")
        state.granted_capabilities.append(capability)
        state.pending_capabilities.pop(capability, None)
        logger.info("Capability %s granted to agent %s", capability.value, agent_id)

    def get_agent_state(self, agent_id: str) -> Optional[AgentCapabilityState]:
        return self._agents.get(agent_id)

    def get_gate_summary(self) -> Dict[str, Dict[str, float]]:
        return {
            gate.capability.value: {
                "min_reliability": gate.min_reliability,
                "approvals_required": gate.approvals_required,
                "grace_period_hours": gate.grace_period_hours,
            }
            for gate in self._gates.values()
        }


_capability_gating_service: Optional[CapabilityGatingService] = None


def get_capability_gating_service() -> CapabilityGatingService:
    global _capability_gating_service
    if _capability_gating_service is None:
        _capability_gating_service = CapabilityGatingService()
    return _capability_gating_service
