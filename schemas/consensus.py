"""
ConsensusBlock Schema - Hashable, replayable consensus records.

A ConsensusBlock represents a single consensus decision made by the agent mesh.
Blocks are immutable, hashable, and form a chain for audit replay.

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class ConsensusOutcome(Enum):
    """Possible outcomes of a consensus round."""
    APPROVED = "approved"
    REJECTED = "rejected"
    VETOED = "vetoed"
    TIMEOUT = "timeout"
    INSUFFICIENT_VOTES = "insufficient_votes"
    FORCE_REROUND = "force_reround"


class VoteType(Enum):
    """Types of votes agents can cast."""
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"
    VETO = "veto"           # Risk agent only
    FORCE_REROUND = "force_reround"  # Skeptic agent only


@dataclass
class ConsensusVote:
    """A single vote from an agent."""
    agent_id: str
    vote: VoteType
    confidence: float  # 0.0 to 1.0
    trust_weight: float  # Agent's current trust score
    reasoning: str
    timestamp: float = field(default_factory=time.time)
    
    # Optional analysis data
    signal: Optional[str] = None  # bullish, bearish, neutral
    risk_score: Optional[float] = None
    
    def weighted_score(self) -> float:
        """Calculate trust-weighted vote score."""
        if self.vote == VoteType.APPROVE:
            return self.confidence * self.trust_weight
        elif self.vote == VoteType.REJECT:
            return -self.confidence * self.trust_weight
        elif self.vote == VoteType.VETO:
            return -2.0  # Veto has special weight
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "vote": self.vote.value,
            "confidence": self.confidence,
            "trust_weight": self.trust_weight,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp,
            "signal": self.signal,
            "risk_score": self.risk_score,
            "weighted_score": self.weighted_score(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsensusVote":
        return cls(
            agent_id=data["agent_id"],
            vote=VoteType(data["vote"]),
            confidence=data["confidence"],
            trust_weight=data["trust_weight"],
            reasoning=data["reasoning"],
            timestamp=data.get("timestamp", time.time()),
            signal=data.get("signal"),
            risk_score=data.get("risk_score"),
        )


@dataclass
class ConsensusBlock:
    """
    An immutable, hashable consensus decision block.
    
    Forms a chain with previous blocks for full audit replay.
    Each block contains:
    - The intent being voted on
    - All agent votes
    - The final outcome
    - Cryptographic hash linking to previous block
    """
    
    # Identity
    block_id: str = field(default_factory=lambda: f"cb_{uuid.uuid4().hex[:12]}")
    block_number: int = 0
    
    # Chain linkage
    previous_hash: str = "genesis"
    
    # Subject
    intent_id: str = ""
    intent_hash: str = ""
    intent_summary: str = ""
    
    # Votes
    votes: List[ConsensusVote] = field(default_factory=list)
    
    # Outcome
    outcome: ConsensusOutcome = ConsensusOutcome.INSUFFICIENT_VOTES
    consensus_score: float = 0.0  # Weighted sum of votes
    consensus_threshold: float = 0.65
    
    # Timing
    round_started_at: float = field(default_factory=time.time)
    round_ended_at: float = field(default_factory=time.time)
    round_duration_ms: float = 0.0
    
    # Metadata
    participating_agents: int = 0
    required_agents: int = 3
    veto_cast: bool = False
    veto_agent: Optional[str] = None
    force_reround_requested: bool = False
    reround_count: int = 0
    
    # Block hash (computed)
    block_hash: str = ""
    
    def __post_init__(self):
        """Compute block hash after initialization."""
        if not self.block_hash:
            self.block_hash = self.compute_hash()
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the block."""
        hash_data = {
            "block_id": self.block_id,
            "block_number": self.block_number,
            "previous_hash": self.previous_hash,
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "votes": [v.to_dict() for v in self.votes],
            "outcome": self.outcome.value,
            "consensus_score": self.consensus_score,
            "round_started_at": self.round_started_at,
            "round_ended_at": self.round_ended_at,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def add_vote(self, vote: ConsensusVote) -> None:
        """Add a vote to the block (before finalization)."""
        self.votes.append(vote)
        self.participating_agents = len(self.votes)
        
        # Check for veto
        if vote.vote == VoteType.VETO:
            self.veto_cast = True
            self.veto_agent = vote.agent_id
        
        # Check for force reround
        if vote.vote == VoteType.FORCE_REROUND:
            self.force_reround_requested = True
    
    def finalize(self) -> ConsensusOutcome:
        """Finalize the consensus round and determine outcome."""
        self.round_ended_at = time.time()
        self.round_duration_ms = (self.round_ended_at - self.round_started_at) * 1000
        
        # Check for veto first
        if self.veto_cast:
            self.outcome = ConsensusOutcome.VETOED
            self.block_hash = self.compute_hash()
            return self.outcome
        
        # Check for force reround
        if self.force_reround_requested:
            self.outcome = ConsensusOutcome.FORCE_REROUND
            self.block_hash = self.compute_hash()
            return self.outcome
        
        # Check for sufficient votes
        if self.participating_agents < self.required_agents:
            self.outcome = ConsensusOutcome.INSUFFICIENT_VOTES
            self.block_hash = self.compute_hash()
            return self.outcome
        
        # Calculate consensus score
        total_weight = sum(v.trust_weight for v in self.votes if v.vote != VoteType.ABSTAIN)
        if total_weight > 0:
            weighted_sum = sum(v.weighted_score() for v in self.votes)
            self.consensus_score = weighted_sum / total_weight
        
        # Determine outcome
        if self.consensus_score >= self.consensus_threshold:
            self.outcome = ConsensusOutcome.APPROVED
        else:
            self.outcome = ConsensusOutcome.REJECTED
        
        self.block_hash = self.compute_hash()
        return self.outcome
    
    def verify_chain(self, previous_block: Optional["ConsensusBlock"]) -> bool:
        """Verify this block links correctly to the previous block."""
        if previous_block is None:
            return self.previous_hash == "genesis"
        return self.previous_hash == previous_block.block_hash
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "block_id": self.block_id,
            "block_number": self.block_number,
            "previous_hash": self.previous_hash,
            "block_hash": self.block_hash,
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "intent_summary": self.intent_summary,
            "votes": [v.to_dict() for v in self.votes],
            "outcome": self.outcome.value,
            "consensus_score": self.consensus_score,
            "consensus_threshold": self.consensus_threshold,
            "round_started_at": self.round_started_at,
            "round_ended_at": self.round_ended_at,
            "round_duration_ms": self.round_duration_ms,
            "participating_agents": self.participating_agents,
            "required_agents": self.required_agents,
            "veto_cast": self.veto_cast,
            "veto_agent": self.veto_agent,
            "force_reround_requested": self.force_reround_requested,
            "reround_count": self.reround_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConsensusBlock":
        """Create from dictionary."""
        votes = [ConsensusVote.from_dict(v) for v in data.get("votes", [])]
        
        block = cls(
            block_id=data.get("block_id", f"cb_{uuid.uuid4().hex[:12]}"),
            block_number=data.get("block_number", 0),
            previous_hash=data.get("previous_hash", "genesis"),
            intent_id=data.get("intent_id", ""),
            intent_hash=data.get("intent_hash", ""),
            intent_summary=data.get("intent_summary", ""),
            votes=votes,
            outcome=ConsensusOutcome(data.get("outcome", "insufficient_votes")),
            consensus_score=data.get("consensus_score", 0.0),
            consensus_threshold=data.get("consensus_threshold", 0.65),
            round_started_at=data.get("round_started_at", time.time()),
            round_ended_at=data.get("round_ended_at", time.time()),
            round_duration_ms=data.get("round_duration_ms", 0.0),
            participating_agents=data.get("participating_agents", 0),
            required_agents=data.get("required_agents", 3),
            veto_cast=data.get("veto_cast", False),
            veto_agent=data.get("veto_agent"),
            force_reround_requested=data.get("force_reround_requested", False),
            reround_count=data.get("reround_count", 0),
        )
        block.block_hash = data.get("block_hash", block.compute_hash())
        return block
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ConsensusBlock":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
