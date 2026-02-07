"""CanonicalAgent ABC — Typed base for all MERID canonical agents.

Every canonical agent has:
- A category, unique ID, and status lifecycle.
- A typed `run()` method that produces `AgentOutput`.
- Integration hooks for the pipeline (proposals, risk checks, explanations).
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.agents.base")


class AgentCategory(str, Enum):
    RESEARCH = "research"
    STRATEGY = "strategy"
    RISK = "risk"
    COORDINATION = "coordination"
    OPS = "ops"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    RETIRED = "retired"


@dataclass
class AgentOutput:
    """Typed output from any canonical agent run."""
    agent_id: str
    category: str
    output_type: str          # "thesis", "proposal", "risk_check", "explanation", etc.
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "category": self.category,
            "output_type": self.output_type,
            "payload": self.payload,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "run_id": self.run_id,
            "latency_ms": round(self.latency_ms, 2),
            "errors": self.errors,
        }


class CanonicalAgent(ABC):
    """Abstract base for all canonical MERID agents."""

    def __init__(self, agent_id: str, category: AgentCategory):
        self.agent_id = agent_id
        self.category = category
        self.status = AgentStatus.IDLE
        self._run_count: int = 0
        self._error_count: int = 0
        self._last_run: Optional[datetime] = None
        self._last_output: Optional[AgentOutput] = None
        self.logger = get_logger(f"merid.agents.{agent_id}")

    # ── Lifecycle ────────────────────────────────────────────────────

    def pause(self) -> None:
        self.status = AgentStatus.PAUSED

    def resume(self) -> None:
        self.status = AgentStatus.IDLE

    def retire(self) -> None:
        self.status = AgentStatus.RETIRED

    @property
    def is_active(self) -> bool:
        return self.status in (AgentStatus.IDLE, AgentStatus.RUNNING)

    # ── Core run ─────────────────────────────────────────────────────

    async def run(self, context: Dict[str, Any] = None) -> AgentOutput:
        """Execute the agent's main logic. Wraps _execute with lifecycle."""
        if self.status == AgentStatus.PAUSED:
            return AgentOutput(
                agent_id=self.agent_id, category=self.category.value,
                output_type="skipped", payload={"reason": "Agent is paused."},
            )
        if self.status == AgentStatus.RETIRED:
            return AgentOutput(
                agent_id=self.agent_id, category=self.category.value,
                output_type="skipped", payload={"reason": "Agent is retired."},
            )

        self.status = AgentStatus.RUNNING
        start = time.perf_counter()
        try:
            output = await self._execute(context or {})
            output.latency_ms = (time.perf_counter() - start) * 1000
            self._run_count += 1
            self._last_run = datetime.now(timezone.utc)
            self._last_output = output
            self.status = AgentStatus.IDLE
            return output
        except Exception as exc:
            self._error_count += 1
            self.status = AgentStatus.ERROR
            self.logger.error(f"Agent {self.agent_id} failed: {exc}")
            return AgentOutput(
                agent_id=self.agent_id, category=self.category.value,
                output_type="error",
                payload={"error": str(exc)},
                latency_ms=(time.perf_counter() - start) * 1000,
                errors=[str(exc)],
            )

    @abstractmethod
    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Implement agent-specific logic. Must return AgentOutput."""

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "category": self.category.value,
            "status": self.status.value,
            "run_count": self._run_count,
            "error_count": self._error_count,
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }


# ── Registry ─────────────────────────────────────────────────────────

class CanonicalAgentRegistry:
    """Central registry for all canonical agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, CanonicalAgent] = {}

    def register(self, agent: CanonicalAgent) -> None:
        self._agents[agent.agent_id] = agent
        logger.info(f"Registered canonical agent: {agent.agent_id} ({agent.category.value})")

    def get(self, agent_id: str) -> Optional[CanonicalAgent]:
        return self._agents.get(agent_id)

    def by_category(self, category: AgentCategory) -> List[CanonicalAgent]:
        return [a for a in self._agents.values() if a.category == category]

    def all(self) -> Dict[str, CanonicalAgent]:
        return dict(self._agents)

    def active(self) -> List[CanonicalAgent]:
        return [a for a in self._agents.values() if a.is_active]

    def summary(self) -> List[dict]:
        return [a.summary() for a in self._agents.values()]

    async def run_all(self, context: Dict[str, Any] = None) -> List[AgentOutput]:
        """Run all active agents and collect outputs."""
        outputs = []
        for agent in self.active():
            output = await agent.run(context)
            outputs.append(output)
        return outputs

    async def run_category(self, category: AgentCategory, context: Dict[str, Any] = None) -> List[AgentOutput]:
        """Run all active agents in a category."""
        outputs = []
        for agent in self.by_category(category):
            if agent.is_active:
                output = await agent.run(context)
                outputs.append(output)
        return outputs


_registry: Optional[CanonicalAgentRegistry] = None


def get_canonical_registry() -> CanonicalAgentRegistry:
    global _registry
    if _registry is None:
        _registry = CanonicalAgentRegistry()
    return _registry
