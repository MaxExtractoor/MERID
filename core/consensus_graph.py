"""
ConsensusGraph - Canonical consensus mechanism per MASTER_SPEC v1.0

This module implements the core consensus engine for MERID including:
- Vote aggregation with weighted trust scores
- Quorum logic with dynamic fallback (Amendment 3.2)
- Skeptic veto handling with cooldown (Amendment 3.1)
- Partial quorum fallback for latency compliance (Amendment 1.1)
- Full audit trail for all consensus decisions

Reference: MASTER_SPEC.md Section 6.1
Reference: MASTER_SPEC_AMENDMENTS.md Amendments 1, 3
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable

from utils.logger import get_logger
from agents.interface import AgentVote, VoteDecision

logger = get_logger("core.consensus")


class ConsensusState(Enum):
    """Consensus round lifecycle states."""
    
    PENDING = "pending"
    COLLECTING = "collecting"
    QUORUM_REACHED = "quorum_reached"
    PARTIAL_QUORUM = "partial_quorum"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    VETOED = "vetoed"
    DEADLOCKED = "deadlocked"


@dataclass
class ConsensusConfig:
    """
    Configuration for consensus behavior.
    
    Reference: MASTER_SPEC.md Section 6.1
    Reference: MASTER_SPEC_AMENDMENTS.md Amendment 1.1, 3.2
    """
    
    quorum_threshold: int = 5
    approval_threshold: float = 0.60
    
    partial_quorum_threshold: int = 4
    partial_approval_threshold: float = 0.75
    
    timeout_seconds: float = 30.0
    timeout_warning_ms: int = 80
    
    skeptic_agent_id: str = "skeptic-agent-01"
    skeptic_veto_confidence_threshold: float = 0.80
    max_skeptic_vetoes_per_hour: int = 3
    
    min_dynamic_quorum: int = 3
    
    def get_dynamic_thresholds(self, alive_agents: int) -> tuple[int, float]:
        """
        Get dynamic quorum and approval thresholds based on alive agent count.
        
        Reference: MASTER_SPEC_AMENDMENTS.md Amendment 3.2
        
        Args:
            alive_agents: Number of currently alive agents
            
        Returns:
            Tuple of (min_quorum, approval_threshold)
        """
        thresholds = {
            8: (5, 0.60),
            7: (5, 0.60),
            6: (4, 0.65),
            5: (4, 0.70),
            4: (3, 0.75),
            3: (3, 0.80),
        }
        if alive_agents < 3:
            raise InsufficientAgentsError(
                f"Cannot form consensus with {alive_agents} agents (minimum 3 required)"
            )
        return thresholds.get(alive_agents, (5, 0.60))


class ConsensusError(Exception):
    """Base exception for consensus errors."""
    pass


class InsufficientAgentsError(ConsensusError):
    """Raised when not enough agents are alive for consensus."""
    pass


class VetoError(ConsensusError):
    """Raised when skeptic agent vetoes a proposal."""
    pass


class QuorumNotReachedError(ConsensusError):
    """Raised when quorum is not reached before timeout."""
    pass


@dataclass
class SkepticVetoTracker:
    """
    Track skeptic veto usage to prevent system paralysis.
    
    Reference: MASTER_SPEC_AMENDMENTS.md Amendment 3.1
    """
    
    max_vetoes_per_hour: int = 3
    cooldown_seconds: int = 3600
    _veto_timestamps: List[float] = field(default_factory=list)
    
    def can_veto(self) -> bool:
        """Check if skeptic can issue another veto."""
        self._cleanup_expired()
        return len(self._veto_timestamps) < self.max_vetoes_per_hour
    
    def record_veto(self) -> None:
        """Record a veto usage."""
        self._veto_timestamps.append(time.time())
        logger.info(
            "Skeptic veto recorded. Vetoes in last hour: %d/%d",
            len(self._veto_timestamps), self.max_vetoes_per_hour
        )
    
    def vetoes_remaining(self) -> int:
        """Get number of vetoes remaining in current window."""
        self._cleanup_expired()
        return max(0, self.max_vetoes_per_hour - len(self._veto_timestamps))
    
    def _cleanup_expired(self) -> None:
        """Remove expired veto records."""
        cutoff = time.time() - self.cooldown_seconds
        self._veto_timestamps = [t for t in self._veto_timestamps if t > cutoff]


@dataclass
class ConsensusRound:
    """
    Represents a single consensus voting round.
    
    Reference: MASTER_SPEC.md Section 6.1
    """
    
    round_id: str
    proposal_id: str
    proposal_type: str
    proposal_payload: Dict[str, object]
    
    created_at: float = field(default_factory=time.time)
    config: ConsensusConfig = field(default_factory=ConsensusConfig)
    
    votes: Dict[str, AgentVote] = field(default_factory=dict)
    state: ConsensusState = ConsensusState.PENDING
    
    final_result: Optional[str] = None
    final_approval_ratio: Optional[float] = None
    resolution_reason: Optional[str] = None
    resolved_at: Optional[float] = None
    
    audit_log: List[Dict[str, object]] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Initialize round and log creation."""
        self._log_event("round_created", {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
        })
        self.state = ConsensusState.COLLECTING
    
    @property
    def expires_at(self) -> float:
        """Calculate expiration timestamp."""
        return self.created_at + self.config.timeout_seconds
    
    @property
    def is_expired(self) -> bool:
        """Check if round has expired."""
        return time.time() > self.expires_at
    
    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (time.time() - self.created_at) * 1000
    
    @property
    def vote_count(self) -> int:
        """Get current vote count."""
        return len(self.votes)
    
    def add_vote(
        self,
        vote: AgentVote,
        veto_tracker: Optional[SkepticVetoTracker] = None,
    ) -> ConsensusState:
        """
        Add a vote to this round and evaluate state.
        
        Args:
            vote: Agent's vote
            veto_tracker: Optional tracker for skeptic vetoes
            
        Returns:
            Updated consensus state
        """
        if self.state in (
            ConsensusState.APPROVED,
            ConsensusState.REJECTED,
            ConsensusState.EXPIRED,
            ConsensusState.VETOED,
        ):
            logger.warning(
                "Attempted to add vote to resolved round %s (state=%s)",
                self.round_id, self.state.value
            )
            return self.state
        
        if self.is_expired:
            self._resolve(ConsensusState.EXPIRED, "timeout")
            return self.state
        
        if vote.agent_id in self.votes:
            logger.warning(
                "Duplicate vote from %s in round %s, ignoring",
                vote.agent_id, self.round_id
            )
            return self.state
        
        self.votes[vote.agent_id] = vote
        self._log_event("vote_received", {
            "agent_id": vote.agent_id,
            "decision": vote.decision.value,
            "confidence": vote.confidence,
        })
        
        if self._check_skeptic_veto(vote, veto_tracker):
            return self.state
        
        self._evaluate_state()
        return self.state
    
    def force_evaluate(self, alive_agents: int = 8) -> ConsensusState:
        """
        Force evaluation of current state (used for timeout handling).
        
        Args:
            alive_agents: Number of currently alive agents
            
        Returns:
            Updated consensus state
        """
        if self.is_expired:
            if self.vote_count >= self.config.partial_quorum_threshold:
                self._evaluate_partial_quorum(alive_agents)
            else:
                self._resolve(ConsensusState.EXPIRED, "timeout_no_quorum")
        else:
            self._evaluate_state(alive_agents)
        return self.state
    
    def _check_skeptic_veto(
        self,
        vote: AgentVote,
        veto_tracker: Optional[SkepticVetoTracker],
    ) -> bool:
        """
        Check if skeptic agent is vetoing.
        
        Returns:
            True if veto was applied
        """
        if vote.agent_id != self.config.skeptic_agent_id:
            return False
        
        if vote.decision != VoteDecision.REJECT:
            return False
        
        if vote.confidence < self.config.skeptic_veto_confidence_threshold:
            return False
        
        if veto_tracker and not veto_tracker.can_veto():
            logger.warning(
                "Skeptic veto blocked: cooldown active (vetoes remaining: %d)",
                veto_tracker.vetoes_remaining()
            )
            self._log_event("veto_blocked", {
                "reason": "cooldown_active",
                "confidence": vote.confidence,
            })
            return False
        
        if veto_tracker:
            veto_tracker.record_veto()
        
        self._resolve(ConsensusState.VETOED, f"skeptic_veto_confidence_{vote.confidence:.2f}")
        return True
    
    def _evaluate_state(self, alive_agents: int = 8) -> None:
        """Evaluate consensus state based on current votes."""
        if self.state not in (ConsensusState.COLLECTING, ConsensusState.PENDING):
            return
        
        min_quorum, approval_threshold = self.config.get_dynamic_thresholds(alive_agents)
        
        if self.elapsed_ms > self.config.timeout_warning_ms:
            if self.vote_count >= self.config.partial_quorum_threshold:
                self._evaluate_partial_quorum(alive_agents)
                return
        
        if self.vote_count < min_quorum:
            return
        
        self.state = ConsensusState.QUORUM_REACHED
        self._log_event("quorum_reached", {"vote_count": self.vote_count})
        
        approval_ratio = self._calculate_approval_ratio()
        self.final_approval_ratio = approval_ratio
        
        if self._check_unanimous_abstain():
            self._resolve(ConsensusState.REJECTED, "insufficient_confidence")
            return
        
        if approval_ratio >= approval_threshold:
            self._resolve(ConsensusState.APPROVED, f"approval_ratio_{approval_ratio:.2f}")
        else:
            self._resolve(ConsensusState.REJECTED, f"approval_ratio_{approval_ratio:.2f}")
    
    def _evaluate_partial_quorum(self, alive_agents: int = 8) -> None:
        """
        Evaluate with partial quorum rules.
        
        Reference: MASTER_SPEC_AMENDMENTS.md Amendment 1.1
        """
        if self.vote_count < self.config.partial_quorum_threshold:
            return
        
        self.state = ConsensusState.PARTIAL_QUORUM
        self._log_event("partial_quorum", {"vote_count": self.vote_count})
        
        approval_ratio = self._calculate_approval_ratio()
        self.final_approval_ratio = approval_ratio
        
        if approval_ratio >= self.config.partial_approval_threshold:
            self._resolve(
                ConsensusState.APPROVED,
                f"partial_quorum_approval_{approval_ratio:.2f}"
            )
        else:
            self._resolve(
                ConsensusState.REJECTED,
                f"partial_quorum_rejection_{approval_ratio:.2f}"
            )
    
    def _calculate_approval_ratio(self) -> float:
        """Calculate weighted approval ratio."""
        if not self.votes:
            return 0.0
        
        total_weight = 0.0
        approval_weight = 0.0
        
        for vote in self.votes.values():
            weight = vote.confidence
            total_weight += weight
            if vote.decision == VoteDecision.APPROVE:
                approval_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return approval_weight / total_weight
    
    def _check_unanimous_abstain(self) -> bool:
        """
        Check if all votes are abstentions.
        
        Reference: MASTER_SPEC_AMENDMENTS.md Amendment 3.3
        """
        if not self.votes:
            return False
        
        for vote in self.votes.values():
            if vote.decision != VoteDecision.ABSTAIN:
                return False
        
        self._log_event("unanimous_abstain", {"vote_count": self.vote_count})
        return True
    
    def _resolve(self, state: ConsensusState, reason: str) -> None:
        """Resolve the round with final state."""
        self.state = state
        self.resolution_reason = reason
        self.resolved_at = time.time()
        
        if state == ConsensusState.APPROVED:
            self.final_result = "approved"
        elif state in (ConsensusState.REJECTED, ConsensusState.VETOED, ConsensusState.EXPIRED):
            self.final_result = "rejected"
        else:
            self.final_result = "unresolved"
        
        self._log_event("round_resolved", {
            "state": state.value,
            "reason": reason,
            "approval_ratio": self.final_approval_ratio,
            "vote_count": self.vote_count,
            "duration_ms": self.elapsed_ms,
        })
        
        logger.info(
            "Consensus round %s resolved: %s (reason=%s, votes=%d, ratio=%.2f)",
            self.round_id, state.value, reason, self.vote_count,
            self.final_approval_ratio or 0.0
        )
    
    def _log_event(self, event_type: str, details: Dict[str, object]) -> None:
        """Add event to audit log."""
        self.audit_log.append({
            "timestamp": time.time(),
            "event_type": event_type,
            "round_id": self.round_id,
            **details,
        })
    
    def get_vote_summary(self) -> Dict[str, object]:
        """Get summary of votes for reporting."""
        approve_count = sum(
            1 for v in self.votes.values() if v.decision == VoteDecision.APPROVE
        )
        reject_count = sum(
            1 for v in self.votes.values() if v.decision == VoteDecision.REJECT
        )
        abstain_count = sum(
            1 for v in self.votes.values() if v.decision == VoteDecision.ABSTAIN
        )
        
        return {
            "total": self.vote_count,
            "approve": approve_count,
            "reject": reject_count,
            "abstain": abstain_count,
            "approval_ratio": self.final_approval_ratio,
        }
    
    def to_dict(self) -> Dict[str, object]:
        """Serialize round to dictionary."""
        return {
            "round_id": self.round_id,
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "state": self.state.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "vote_summary": self.get_vote_summary(),
            "final_result": self.final_result,
            "resolution_reason": self.resolution_reason,
            "audit_log_count": len(self.audit_log),
        }


class ConsensusEngine:
    """
    Main consensus engine managing multiple rounds.
    
    Reference: MASTER_SPEC.md Section 6.1
    """
    
    def __init__(self, config: Optional[ConsensusConfig] = None) -> None:
        """
        Initialize consensus engine.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or ConsensusConfig()
        self.veto_tracker = SkepticVetoTracker(
            max_vetoes_per_hour=self.config.max_skeptic_vetoes_per_hour
        )
        self._active_rounds: Dict[str, ConsensusRound] = {}
        self._completed_rounds: List[ConsensusRound] = []
        self._round_callbacks: List[Callable[[ConsensusRound], None]] = []
        self._logger = get_logger("core.consensus.engine")
    
    def create_round(
        self,
        proposal_id: str,
        proposal_type: str,
        proposal_payload: Dict[str, object],
    ) -> ConsensusRound:
        """
        Create a new consensus round.
        
        Args:
            proposal_id: Unique proposal identifier
            proposal_type: Type of proposal
            proposal_payload: Proposal content
            
        Returns:
            New ConsensusRound
        """
        round_id = str(uuid.uuid4())
        
        consensus_round = ConsensusRound(
            round_id=round_id,
            proposal_id=proposal_id,
            proposal_type=proposal_type,
            proposal_payload=proposal_payload,
            config=self.config,
        )
        
        self._active_rounds[round_id] = consensus_round
        self._logger.info(
            "Created consensus round %s for proposal %s",
            round_id, proposal_id
        )
        
        return consensus_round
    
    def submit_vote(
        self,
        round_id: str,
        vote: AgentVote,
    ) -> ConsensusState:
        """
        Submit a vote to a round.
        
        Args:
            round_id: Target round ID
            vote: Agent's vote
            
        Returns:
            Updated consensus state
            
        Raises:
            KeyError: If round not found
        """
        if round_id not in self._active_rounds:
            raise KeyError(f"Round {round_id} not found")
        
        consensus_round = self._active_rounds[round_id]
        new_state = consensus_round.add_vote(vote, self.veto_tracker)
        
        if new_state in (
            ConsensusState.APPROVED,
            ConsensusState.REJECTED,
            ConsensusState.EXPIRED,
            ConsensusState.VETOED,
        ):
            self._complete_round(consensus_round)
        
        return new_state
    
    def get_round(self, round_id: str) -> Optional[ConsensusRound]:
        """Get a round by ID."""
        return self._active_rounds.get(round_id)
    
    def get_active_rounds(self) -> List[ConsensusRound]:
        """Get all active rounds."""
        return list(self._active_rounds.values())
    
    def cleanup_expired(self, alive_agents: int = 8) -> List[ConsensusRound]:
        """
        Clean up expired rounds.
        
        Args:
            alive_agents: Number of currently alive agents
            
        Returns:
            List of expired rounds
        """
        expired = []
        for round_id, consensus_round in list(self._active_rounds.items()):
            if consensus_round.is_expired:
                consensus_round.force_evaluate(alive_agents)
                self._complete_round(consensus_round)
                expired.append(consensus_round)
        return expired
    
    def register_callback(
        self,
        callback: Callable[[ConsensusRound], None],
    ) -> None:
        """Register callback for round completion."""
        self._round_callbacks.append(callback)
    
    def _complete_round(self, consensus_round: ConsensusRound) -> None:
        """Move round from active to completed."""
        if consensus_round.round_id in self._active_rounds:
            del self._active_rounds[consensus_round.round_id]
        
        self._completed_rounds.append(consensus_round)
        
        if len(self._completed_rounds) > 1000:
            self._completed_rounds = self._completed_rounds[-500:]
        
        for callback in self._round_callbacks:
            try:
                callback(consensus_round)
            except Exception as e:
                self._logger.error("Callback error: %s", e)
    
    def get_stats(self) -> Dict[str, object]:
        """Get engine statistics."""
        approved = sum(
            1 for r in self._completed_rounds
            if r.state == ConsensusState.APPROVED
        )
        rejected = sum(
            1 for r in self._completed_rounds
            if r.state == ConsensusState.REJECTED
        )
        vetoed = sum(
            1 for r in self._completed_rounds
            if r.state == ConsensusState.VETOED
        )
        expired = sum(
            1 for r in self._completed_rounds
            if r.state == ConsensusState.EXPIRED
        )
        
        return {
            "active_rounds": len(self._active_rounds),
            "completed_rounds": len(self._completed_rounds),
            "approved": approved,
            "rejected": rejected,
            "vetoed": vetoed,
            "expired": expired,
            "veto_tracker_remaining": self.veto_tracker.vetoes_remaining(),
        }


_consensus_engine: Optional[ConsensusEngine] = None
_consensus_engine_lock = threading.Lock()


def get_consensus_engine() -> ConsensusEngine:
    """Get or create global consensus engine singleton."""
    global _consensus_engine
    if _consensus_engine is None:
        with _consensus_engine_lock:
            if _consensus_engine is None:
                _consensus_engine = ConsensusEngine()
    return _consensus_engine
