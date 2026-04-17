"""
MERID Consensus Process Logging
Constitutional requirement: All consensus rounds must be fully traceable
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import json

from utils.logger import get_logger

logger = get_logger("core.consensus_logging")


class VoteType(Enum):
    """Types of votes in consensus"""
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ConsensusOutcome(Enum):
    """Consensus round outcomes"""
    PASSED = "passed"
    FAILED = "failed"
    NO_QUORUM = "no_quorum"
    TIMEOUT = "timeout"


@dataclass
class AgentVote:
    """Individual agent vote in consensus round"""
    agent_id: str
    vote: VoteType
    reasoning: str
    confidence: float
    trust_weight: float
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "vote": self.vote.value,
            "reasoning": self.reasoning,
            "confidence": round(self.confidence, 4),
            "trust_weight": round(self.trust_weight, 4),
            "timestamp": self.timestamp
        }


@dataclass
class DissentRecord:
    """Record of dissenting opinion in consensus"""
    agent_id: str
    vote: VoteType
    reasoning: str
    resolution: str
    overruled_by: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "vote": self.vote.value,
            "reasoning": self.reasoning,
            "resolution": self.resolution,
            "overruled_by": self.overruled_by
        }


@dataclass
class ConsensusTimeline:
    """Complete timeline of a consensus round"""
    round_id: str
    proposal: Dict[str, Any]
    start_time: float
    end_time: Optional[float]
    
    # Voting process
    votes: List[AgentVote] = field(default_factory=list)
    dissent: List[DissentRecord] = field(default_factory=list)
    
    # Outcome
    outcome: Optional[ConsensusOutcome] = None
    final_confidence: float = 0.0
    final_action: Optional[str] = None
    
    # Metadata
    quorum_required: int = 3
    quorum_reached: bool = False
    total_trust_weight: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_id": self.round_id,
            "proposal": self.proposal,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": (self.end_time - self.start_time) if self.end_time else None,
            "votes": [v.to_dict() for v in self.votes],
            "dissent": [d.to_dict() for d in self.dissent],
            "outcome": self.outcome.value if self.outcome else None,
            "final_confidence": round(self.final_confidence, 4),
            "final_action": self.final_action,
            "quorum_required": self.quorum_required,
            "quorum_reached": self.quorum_reached,
            "total_trust_weight": round(self.total_trust_weight, 4),
            "vote_summary": self._get_vote_summary()
        }
    
    def _get_vote_summary(self) -> Dict[str, int]:
        """Get summary of votes"""
        summary = {
            "approve": 0,
            "reject": 0,
            "abstain": 0
        }
        for vote in self.votes:
            summary[vote.vote.value] += 1
        return summary
    
    def to_human_readable(self) -> str:
        """Convert to human-readable format"""
        lines = [
            f"Consensus Round: {self.round_id}",
            f"Outcome: {self.outcome.value if self.outcome else 'pending'}",
            f"Confidence: {self.final_confidence:.1%}",
            f"",
            f"Proposal:",
            f"  {json.dumps(self.proposal, indent=2)}",
            f"",
            f"Votes ({len(self.votes)} total):",
        ]
        
        for vote in self.votes:
            lines.append(
                f"  {vote.agent_id}: {vote.vote.value.upper()} "
                f"(confidence: {vote.confidence:.1%}, trust: {vote.trust_weight:.2f})"
            )
            lines.append(f"    Reasoning: {vote.reasoning}")
        
        if self.dissent:
            lines.append("")
            lines.append("Dissenting Opinions:")
            for d in self.dissent:
                lines.append(f"  {d.agent_id}: {d.vote.value.upper()}")
                lines.append(f"    Reasoning: {d.reasoning}")
                lines.append(f"    Resolution: {d.resolution}")
        
        lines.append("")
        lines.append(f"Final Action: {self.final_action or 'None'}")
        
        return "\n".join(lines)


class ConsensusLogger:
    """Logs and tracks consensus process"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.rounds: List[ConsensusTimeline] = []
        self._active_rounds: Dict[str, ConsensusTimeline] = {}
        
        logger.info("Consensus logger initialized")
    
    def start_round(
        self,
        proposal: Dict[str, Any],
        quorum_required: int = 3
    ) -> str:
        """Start a new consensus round"""
        round_id = str(uuid.uuid4())
        
        timeline = ConsensusTimeline(
            round_id=round_id,
            proposal=proposal,
            start_time=time.time(),
            end_time=None,
            quorum_required=quorum_required
        )
        
        self._active_rounds[round_id] = timeline
        
        logger.info(f"Consensus round started: {round_id}")
        return round_id
    
    def record_vote(
        self,
        round_id: str,
        agent_id: str,
        vote: VoteType,
        reasoning: str,
        confidence: float,
        trust_weight: float
    ) -> None:
        """Record an agent vote"""
        timeline = self._active_rounds.get(round_id)
        if not timeline:
            logger.warning(f"Round {round_id} not found")
            return
        
        agent_vote = AgentVote(
            agent_id=agent_id,
            vote=vote,
            reasoning=reasoning,
            confidence=confidence,
            trust_weight=trust_weight,
            timestamp=time.time()
        )
        
        timeline.votes.append(agent_vote)
        timeline.total_trust_weight += trust_weight
        
        # Check quorum
        if len(timeline.votes) >= timeline.quorum_required:
            timeline.quorum_reached = True
        
        logger.debug(
            f"Vote recorded: {agent_id} -> {vote.value} "
            f"(round: {round_id}, confidence: {confidence:.2f})"
        )
    
    def record_dissent(
        self,
        round_id: str,
        agent_id: str,
        vote: VoteType,
        reasoning: str,
        resolution: str,
        overruled_by: List[str]
    ) -> None:
        """Record dissenting opinion"""
        timeline = self._active_rounds.get(round_id)
        if not timeline:
            logger.warning(f"Round {round_id} not found")
            return
        
        dissent = DissentRecord(
            agent_id=agent_id,
            vote=vote,
            reasoning=reasoning,
            resolution=resolution,
            overruled_by=overruled_by
        )
        
        timeline.dissent.append(dissent)
        
        logger.info(
            f"Dissent recorded: {agent_id} dissented with {vote.value} "
            f"(round: {round_id})"
        )
    
    def complete_round(
        self,
        round_id: str,
        outcome: ConsensusOutcome,
        final_confidence: float,
        final_action: Optional[str] = None
    ) -> ConsensusTimeline:
        """Complete a consensus round"""
        timeline = self._active_rounds.get(round_id)
        if not timeline:
            logger.warning(f"Round {round_id} not found")
            return None
        
        timeline.end_time = time.time()
        timeline.outcome = outcome
        timeline.final_confidence = final_confidence
        timeline.final_action = final_action
        
        # Move to history
        self.rounds.append(timeline)
        del self._active_rounds[round_id]
        
        # Trim history
        if len(self.rounds) > self.max_history:
            self.rounds = self.rounds[-self.max_history:]
        
        duration = timeline.end_time - timeline.start_time
        logger.info(
            f"Consensus round completed: {round_id} -> {outcome.value} "
            f"(confidence: {final_confidence:.2f}, duration: {duration:.2f}s)"
        )
        
        return timeline
    
    def get_round(self, round_id: str) -> Optional[ConsensusTimeline]:
        """Get consensus round by ID"""
        # Check active rounds first
        if round_id in self._active_rounds:
            return self._active_rounds[round_id]
        
        # Check history
        for timeline in reversed(self.rounds):
            if timeline.round_id == round_id:
                return timeline
        
        return None
    
    def get_recent_rounds(self, limit: int = 50) -> List[ConsensusTimeline]:
        """Get recent consensus rounds"""
        return self.rounds[-limit:]
    
    def get_consensus_stats(self) -> Dict[str, Any]:
        """Get consensus statistics"""
        total = len(self.rounds)
        
        if total == 0:
            return {
                "total_rounds": 0,
                "active_rounds": len(self._active_rounds),
                "avg_confidence": 0.0,
                "pass_rate": 0.0
            }
        
        passed = sum(1 for r in self.rounds if r.outcome == ConsensusOutcome.PASSED)
        avg_confidence = sum(r.final_confidence for r in self.rounds) / total
        avg_duration = sum(
            (r.end_time - r.start_time) for r in self.rounds if r.end_time
        ) / total
        
        outcome_counts = {}
        for r in self.rounds:
            if r.outcome:
                outcome = r.outcome.value
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        
        return {
            "total_rounds": total,
            "active_rounds": len(self._active_rounds),
            "passed": passed,
            "pass_rate": round(passed / total, 4),
            "avg_confidence": round(avg_confidence, 4),
            "avg_duration_seconds": round(avg_duration, 2),
            "outcome_distribution": outcome_counts,
            "recent_rounds": [r.to_dict() for r in self.rounds[-10:]]
        }


# Global consensus logger
_consensus_logger: Optional[ConsensusLogger] = None
_consensus_logger_lock = threading.Lock()


def get_consensus_logger() -> ConsensusLogger:
    """Get global consensus logger instance"""
    global _consensus_logger
    if _consensus_logger is None:
        with _consensus_logger_lock:
            if _consensus_logger is None:
                _consensus_logger = ConsensusLogger()
    return _consensus_logger
