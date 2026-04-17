"""CanonicalAgent ABC — Typed base for all MERID canonical agents.

Every canonical agent has:
- A category, unique ID, and status lifecycle.
- A typed `run()` method that produces `AgentOutput`.
- Integration hooks for the pipeline (proposals, risk checks, explanations).
"""

from __future__ import annotations

import threading
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

    @is_active.setter
    def is_active(self, value: bool) -> None:
        """Enable/disable agent via lifecycle methods (True → resume, False → pause)."""
        if value:
            self.resume()
        else:
            self.pause()

    # ── Core run ─────────────────────────────────────────────────────

    # Medium-risk: consecutive error limit before auto-retiring agent
    _MAX_CANONICAL_CONSECUTIVE_ERRORS: int = 5

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
        # Medium-risk: ERROR state blocks retries until explicitly reset.
        # Allow retrying from ERROR but count consecutive failures; auto-retire
        # after _MAX_CANONICAL_CONSECUTIVE_ERRORS to prevent infinite API spam.
        if self.status == AgentStatus.ERROR:
            if self._error_count >= self._MAX_CANONICAL_CONSECUTIVE_ERRORS:
                self.logger.error(
                    "Agent %s has %d consecutive errors — auto-retiring to prevent API spam",
                    self.agent_id, self._error_count,
                )
                self.status = AgentStatus.RETIRED
                return AgentOutput(
                    agent_id=self.agent_id, category=self.category.value,
                    output_type="skipped",
                    payload={"reason": f"Auto-retired after {self._error_count} consecutive errors."},
                )
            # Allow retry from ERROR state
            self.logger.warning(
                "Agent %s retrying from ERROR state (attempt %d/%d)",
                self.agent_id, self._error_count + 1, self._MAX_CANONICAL_CONSECUTIVE_ERRORS,
            )

        self.status = AgentStatus.RUNNING
        start = time.perf_counter()
        try:
            output = await self._execute(context or {})
            output.latency_ms = (time.perf_counter() - start) * 1000
            self._run_count += 1
            self._last_run = datetime.now(timezone.utc)
            self._last_output = output
            self._error_count = 0  # reset on success
            self.status = AgentStatus.IDLE
            return output
        except Exception as exc:
            self._error_count += 1
            self.status = AgentStatus.ERROR
            self.logger.error(f"Agent {self.agent_id} failed ({self._error_count}/{self._MAX_CANONICAL_CONSECUTIVE_ERRORS}): {exc}")
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

    # ── AgentInterface contract (observe/analyze/vote/reflect) ────────
    # Default implementations satisfy the interface contract without
    # requiring all 47 concrete subclasses to override them.  Subclasses
    # that participate in the structured debate loop should override these.

    async def observe(self, market_state: Any) -> None:
        """Ingest market state. Override in subclasses that use structured observe-analyze-vote."""
        self.logger.debug("observe: default no-op for %s", self.agent_id)

    async def analyze(self) -> Dict[str, Any]:
        """Generate analysis. Override in subclasses that use structured observe-analyze-vote."""
        self.logger.debug("analyze: default no-op for %s", self.agent_id)
        return {}

    async def vote(self, proposal: Any) -> Any:
        """Cast vote on proposal. Override in subclasses that participate in voting."""
        self.logger.debug("vote: default abstain for %s", self.agent_id)
        from agents.interface import AgentVote, VoteDecision
        return AgentVote(
            agent_id=self.agent_id,
            decision=VoteDecision.ABSTAIN,
            confidence=0.0,
            reasoning=f"{self.agent_id} has no vote implementation — abstaining",
        )

    async def reflect(self, outcome: Any) -> None:
        """Update internal state from outcome. Override in subclasses that learn from outcomes."""
        self.logger.debug("reflect: default no-op for %s", self.agent_id)

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


@dataclass
class AgentOpinion:
    """Typed opinion output from a Kalshi regime agent."""
    agent_id: str
    market_id: str
    side: str  # "yes" or "no", or "buy_yes"/"buy_no"
    confidence: float  # 0.0 to 1.0
    edge_estimate: float  # Expected edge in cents
    horizon: str  # e.g., "15m", "1h"
    symbol: Optional[str] = None  # e.g., "BTC", "ETH"
    timeframe: Optional[str] = None  # e.g., "15m", "1h", "daily"
    size_pct: Optional[float] = None  # Position size percentage
    trace_id: Optional[str] = None  # Tracing identifier
    correlation_id: Optional[str] = None  # Business correlation ID
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def for_series(
        cls,
        agent_id: str,
        symbol: str,
        timeframe: str,
        market_id: str,
        side: str,
        confidence: float,
        edge_estimate: float,
        horizon: str,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **kwargs,
    ) -> "AgentOpinion":
        """Helper constructor to ensure symbol/timeframe are always set.
        
        Args:
            agent_id: Unique agent identifier
            symbol: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            timeframe: Timeframe (15m, 1h, daily, weekly)
            market_id: Kalshi market ticker
            side: "buy_yes" or "buy_no"
            confidence: 0.0 to 1.0
            edge_estimate: Expected edge in cents
            horizon: "short", "medium", "long"
            trace_id: Optional tracing ID
            correlation_id: Optional correlation ID
            **kwargs: Additional fields (size_pct, metadata, etc.)
        
        Returns:
            AgentOpinion with symbol/timeframe explicitly set
        """
        return cls(
            agent_id=agent_id,
            symbol=symbol,
            timeframe=timeframe,
            market_id=market_id,
            side=side,
            confidence=confidence,
            edge_estimate=edge_estimate,
            horizon=horizon,
            trace_id=trace_id,
            correlation_id=correlation_id,
            **kwargs,
        )


class BaseKalshiAgent(CanonicalAgent):
    """Abstract base for Kalshi-specific regime agents.
    
    These agents produce opinions on Kalshi prediction markets
    based on regime analysis (RTI, volatility, trend).
    """
    
    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id, AgentCategory.STRATEGY)
        
    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Default implementation - subclasses should override get_opinion()."""
        opinion = await self.get_opinion()
        if opinion is None:
            return AgentOutput(
                agent_id=self.agent_id,
                category=self.category.value,
                output_type="no_opinion",
                payload={},
                confidence=0.0,
            )
        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="opinion",
            payload={
                "market_id": opinion.market_id,
                "side": opinion.side,
                "confidence": opinion.confidence,
                "edge_estimate": opinion.edge_estimate,
                "horizon": opinion.horizon,
                "size_pct": opinion.size_pct,
            },
            confidence=opinion.confidence,
        )
    
    @abstractmethod
    async def get_opinion(
        self,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[AgentOpinion]:
        """Generate an opinion on the current market regime.
        
        Args:
            trace_id: Unique identifier for tracing this opinion through the swarm
            correlation_id: Business correlation ID linking to upstream decision
            
        Returns None if no clear signal, otherwise returns AgentOpinion
        with side (yes/no), confidence, and edge estimate.
        """
        pass


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

    def count(self) -> int:
        """Return total number of registered agents."""
        return len(self._agents)

    def summary(self) -> List[dict]:
        return [a.summary() for a in self._agents.values()]

    async def run_all(self, context: Dict[str, Any] = None) -> List[AgentOutput]:
        """Run all active agents concurrently and collect outputs."""
        import asyncio
        agents = list(self.active())
        if not agents:
            return []
        results = await asyncio.gather(
            *(a.run(context) for a in agents),
            return_exceptions=True,
        )
        outputs = []
        for agent, result in zip(agents, results):
            if isinstance(result, Exception):
                logger.warning(f"Agent {agent.agent_id} failed: {result}")
            else:
                outputs.append(result)
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
_registry_lock = threading.Lock()


def get_canonical_registry() -> CanonicalAgentRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = CanonicalAgentRegistry()
    return _registry
