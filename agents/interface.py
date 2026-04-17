"""
AgentInterface - Canonical agent contract per MASTER_SPEC v1.0

This module defines the foundational interface that ALL MERID agents must implement.
It enforces lifecycle hooks, input/output contracts, memory access rules, voting
interface, and health/heartbeat reporting.

Reference: MASTER_SPEC.md Section 4.2
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union

from utils.logger import get_logger


class AgentState(Enum):
    """Agent lifecycle states."""
    INITIALIZING = "initializing"
    READY = "ready"
    PROCESSING = "processing"
    VOTING = "voting"
    REFLECTING = "reflecting"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class VoteDecision(Enum):
    """Canonical vote decisions."""
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class AgentVote:
    """
    Immutable vote record from an agent.
    
    Reference: MASTER_SPEC.md Section 4.2
    """
    agent_id: str
    decision: VoteDecision
    confidence: float
    reasoning: str
    timestamp: float = field(default_factory=time.time)
    vote_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def __post_init__(self) -> None:
        """Validate vote constraints."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0.0, 1.0], got {self.confidence}")
        if not self.agent_id:
            raise ValueError("agent_id cannot be empty")
        if not self.reasoning:
            raise ValueError("reasoning cannot be empty")


@dataclass
class AgentHealth:
    """Agent health status for monitoring."""
    agent_id: str
    state: AgentState
    last_heartbeat: float
    uptime_seconds: float
    processed_count: int
    error_count: int
    avg_latency_ms: float
    memory_usage_bytes: int
    
    def is_healthy(self, max_heartbeat_age_seconds: float = 30.0) -> bool:
        """Check if agent is considered healthy."""
        if self.state in (AgentState.TERMINATED, AgentState.SUSPENDED):
            return False
        heartbeat_age = time.time() - self.last_heartbeat
        if heartbeat_age > max_heartbeat_age_seconds:
            return False
        return True


@dataclass
class ResurrectionContext:
    """
    Context passed to resurrected agent.
    
    Reference: MASTER_SPEC_AMENDMENTS.md Amendment 4.2
    """
    predecessor_id: str
    death_reason: str
    death_timestamp: float
    lineage_id: str
    generation: int
    
    trust_score: float
    expertise_score: float
    
    core_memories: List[Dict[str, object]] = field(default_factory=list)
    learned_patterns: Dict[str, float] = field(default_factory=dict)
    predecessor_chain: List[str] = field(default_factory=list)


@dataclass
class MarketState:
    """Canonical market state snapshot for agent observation."""
    timestamp: float
    prices: Dict[str, float]
    volumes: Dict[str, float]
    funding_rates: Dict[str, float]
    news_sentiment: float
    volatility_index: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class Proposal:
    """Proposal submitted for agent voting."""
    proposal_id: str
    proposal_type: str
    payload: Dict[str, object]
    created_at: float
    expires_at: float
    source_agent: str
    priority: int = 0
    metadata: Dict[str, object] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if proposal has expired."""
        return time.time() > self.expires_at


@dataclass
class Outcome:
    """Outcome record for agent reflection."""
    outcome_id: str
    proposal_id: str
    result: str
    actual_value: Optional[float]
    predicted_value: Optional[float]
    timestamp: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class NormalizedProposal:
    """
    Standardized proposal that all agents must conform to.
    
    This ensures consistent proposal format across all agents and
    enables proper validation at the consensus entrypoint.
    """
    # Identity
    proposal_id: str
    agent_id: str
    agent_role: str
    
    # Market Context (REQUIRED)
    asset: str                      # Must be in ACTIVE_CRYPTO_ASSETS
    timeframe: str                  # Must be in ACTIVE_CRYPTO_TIMEFRAMES
    kalshi_ticker: str              # Validated Kalshi series ticker
    
    # Decision (REQUIRED)
    recommendation: str             # "buy", "sell", "hold", "abstain"
    direction: str                  # "bullish", "bearish", "neutral"
    confidence: float               # 0.0 to 1.0, clamped
    edge: Optional[float] = None   # Expected edge in bps
    
    # Risk (REQUIRED for execution)
    size_hint: Optional[int] = None        # Contract count
    max_position: Optional[int] = None     # Risk limit
    risk_pct: Optional[float] = None       # % of allocation
    
    # Provenance
    timestamp: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    source_data: Dict[str, object] = field(default_factory=dict)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    evidence: Dict[str, object] = field(default_factory=dict)
    
    def __post_init__(self):
        """Auto-validate on creation."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Invalid NormalizedProposal: {', '.join(errors)}")
    
    def validate(self) -> List[str]:
        """Return list of validation errors, empty if valid."""
        errors = []
        
        # Lazy import to avoid circular dependency
        from config.crypto_universe import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_TIMEFRAMES
        
        # Validate asset
        if self.asset.upper() not in ACTIVE_CRYPTO_ASSETS:
            errors.append(f"Invalid asset: {self.asset}. Must be one of {ACTIVE_CRYPTO_ASSETS}")
        
        # Validate timeframe
        if self.timeframe not in ACTIVE_CRYPTO_TIMEFRAMES:
            errors.append(f"Invalid timeframe: {self.timeframe}. Must be one of {ACTIVE_CRYPTO_TIMEFRAMES}")
        
        # Validate confidence
        if not 0.0 <= self.confidence <= 1.0:
            errors.append(f"Confidence out of range: {self.confidence}. Must be in [0.0, 1.0]")
        
        # Validate recommendation
        valid_recommendations = ["buy", "sell", "hold", "abstain"]
        if self.recommendation not in valid_recommendations:
            errors.append(f"Invalid recommendation: {self.recommendation}. Must be one of {valid_recommendations}")
        
        # Validate direction
        valid_directions = ["bullish", "bearish", "neutral"]
        if self.direction not in valid_directions:
            errors.append(f"Invalid direction: {self.direction}. Must be one of {valid_directions}")
        
        # Validate risk fields if present
        if self.size_hint is not None and self.size_hint <= 0:
            errors.append(f"size_hint must be positive, got {self.size_hint}")
        
        if self.max_position is not None and self.max_position <= 0:
            errors.append(f"max_position must be positive, got {self.max_position}")
        
        if self.risk_pct is not None and not 0.0 <= self.risk_pct <= 1.0:
            errors.append(f"risk_pct must be in [0.0, 1.0], got {self.risk_pct}")
        
        return errors
    
    def to_dict(self) -> Dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "proposal_id": self.proposal_id,
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "kalshi_ticker": self.kalshi_ticker,
            "recommendation": self.recommendation,
            "direction": self.direction,
            "confidence": self.confidence,
            "edge": self.edge,
            "size_hint": self.size_hint,
            "max_position": self.max_position,
            "risk_pct": self.risk_pct,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "tags": self.tags,
            "evidence": self.evidence,
        }


class AgentInterface(ABC):
    """
    Abstract base interface that ALL MERID agents must implement.
    
    This defines the canonical contract for agent behavior including:
    - Lifecycle management (initialize, start, stop, resurrect)
    - Core loop (observe, analyze, vote, reflect)
    - Health monitoring (heartbeat, health status)
    - Memory access (working memory, append to ledger)
    
    Reference: MASTER_SPEC.md Section 4.2
    
    Implementation Rules:
    - All abstract methods MUST be implemented (no pass statements)
    - All methods MUST have complete type annotations
    - All exceptions MUST be typed and logged
    - No bare except clauses allowed
    """
    
    def __init__(self, agent_id: str, expertise_score: float, risk_factor: float) -> None:
        """
        Initialize agent with core identity.
        
        Args:
            agent_id: Unique identifier for this agent instance
            expertise_score: Agent's expertise level [0.0, 1.0]
            risk_factor: Agent's risk tolerance [0.0, 1.0]
        """
        if not agent_id:
            raise ValueError("agent_id cannot be empty")
        if not 0.0 <= expertise_score <= 1.0:
            raise ValueError(f"expertise_score must be in [0.0, 1.0], got {expertise_score}")
        if not 0.0 <= risk_factor <= 1.0:
            raise ValueError(f"risk_factor must be in [0.0, 1.0], got {risk_factor}")
        
        self._agent_id = agent_id
        self._expertise_score = expertise_score
        self._risk_factor = risk_factor
        self._trust_score: float = 1.0
        self._state: AgentState = AgentState.INITIALIZING
        self._start_time: float = time.time()
        self._last_heartbeat: float = time.time()
        self._processed_count: int = 0
        self._error_count: int = 0
        self._total_latency_ms: float = 0.0
        self._lineage_id: str = str(uuid.uuid4())
        self._generation: int = 0
        self._working_memory: Dict[str, object] = {}
        self._logger = get_logger(f"agents.{agent_id}")
    
    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent."""
        return self._agent_id
    
    @property
    def expertise_score(self) -> float:
        """Agent's expertise level [0.0, 1.0]."""
        return self._expertise_score
    
    @property
    def risk_factor(self) -> float:
        """Agent's risk tolerance [0.0, 1.0]."""
        return self._risk_factor
    
    @property
    def trust_score(self) -> float:
        """Current trust score based on prediction accuracy."""
        return self._trust_score
    
    @property
    def state(self) -> AgentState:
        """Current agent lifecycle state."""
        return self._state
    
    @property
    def lineage_id(self) -> str:
        """UUID of original agent (preserved across resurrections)."""
        return self._lineage_id
    
    @property
    def generation(self) -> int:
        """Resurrection generation count."""
        return self._generation
    
    def update_trust(self, new_trust: float) -> None:
        """
        Update agent's trust score.
        
        Args:
            new_trust: New trust score [0.0, 1.0]
        """
        if not 0.0 <= new_trust <= 1.0:
            raise ValueError(f"trust must be in [0.0, 1.0], got {new_trust}")
        old_trust = self._trust_score
        self._trust_score = new_trust
        self._logger.info(
            "Trust updated: %.3f -> %.3f (delta: %+.3f)",
            old_trust, new_trust, new_trust - old_trust
        )
    
    def heartbeat(self) -> None:
        """Record heartbeat for health monitoring."""
        self._last_heartbeat = time.time()
    
    def get_health(self) -> AgentHealth:
        """Get current health status."""
        avg_latency = (
            self._total_latency_ms / self._processed_count
            if self._processed_count > 0 else 0.0
        )
        return AgentHealth(
            agent_id=self._agent_id,
            state=self._state,
            last_heartbeat=self._last_heartbeat,
            uptime_seconds=time.time() - self._start_time,
            processed_count=self._processed_count,
            error_count=self._error_count,
            avg_latency_ms=avg_latency,
            memory_usage_bytes=0
        )
    
    def get_working_memory(self, key: str) -> Optional[object]:
        """
        Get value from mutable working memory.
        
        Args:
            key: Memory key
            
        Returns:
            Value if exists, None otherwise
        """
        return self._working_memory.get(key)
    
    def set_working_memory(self, key: str, value: object) -> None:
        """
        Set value in mutable working memory.
        
        Args:
            key: Memory key
            value: Value to store
        """
        self._working_memory[key] = value
    
    def clear_working_memory(self) -> None:
        """Clear all working memory (used on resurrection)."""
        self._working_memory.clear()
    
    async def start(self) -> None:
        """
        Start the agent and transition to READY state.
        
        Called once after initialization to prepare agent for processing.
        """
        self._state = AgentState.READY
        self._logger.info("Agent started: %s", self._agent_id)
    
    async def stop(self) -> None:
        """
        Stop the agent gracefully.
        
        Called to cleanly shut down the agent.
        """
        self._state = AgentState.TERMINATED
        self._logger.info("Agent stopped: %s", self._agent_id)
    
    async def resurrect(self, context: ResurrectionContext) -> None:
        """
        Resurrect agent with inherited context from predecessor.
        
        Reference: MASTER_SPEC_AMENDMENTS.md Amendment 4.2
        
        Args:
            context: Resurrection context with inherited state
        """
        self._lineage_id = context.lineage_id
        self._generation = context.generation + 1
        self._trust_score = context.trust_score * 0.9
        self._expertise_score = context.expertise_score
        self.clear_working_memory()
        
        for pattern_key, pattern_value in context.learned_patterns.items():
            self.set_working_memory(f"pattern:{pattern_key}", pattern_value)
        
        self._state = AgentState.READY
        self._logger.info(
            "Agent resurrected: %s (gen %d, lineage %s, predecessor %s)",
            self._agent_id, self._generation, self._lineage_id, context.predecessor_id
        )
    
    @abstractmethod
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest current market state for analysis.
        
        This is the first step in the observe-analyze-vote loop.
        Agents should store relevant observations in working memory.
        
        Args:
            market_state: Current market snapshot
        """
        raise NotImplementedError
    
    @abstractmethod
    async def analyze(self) -> Dict[str, object]:
        """
        Generate analysis from observations.
        
        This is the second step in the observe-analyze-vote loop.
        Agents should process observations and generate insights.
        
        Returns:
            Analysis results dictionary
        """
        raise NotImplementedError
    
    @abstractmethod
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on a proposal.
        
        This is the third step in the observe-analyze-vote loop.
        Agents must return a valid AgentVote with reasoning.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with confidence and reasoning
        """
        raise NotImplementedError
    
    @abstractmethod
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Called after consensus is reached and outcome is known.
        Agents should update learned patterns and adjust behavior.
        
        Args:
            outcome: Outcome of the proposal
        """
        raise NotImplementedError
    
    def _record_processing(self, latency_ms: float, success: bool) -> None:
        """
        Record processing metrics.
        
        Args:
            latency_ms: Processing latency in milliseconds
            success: Whether processing succeeded
        """
        self._processed_count += 1
        self._total_latency_ms += latency_ms
        if not success:
            self._error_count += 1
        self.heartbeat()
