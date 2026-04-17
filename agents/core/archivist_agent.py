"""
ArchivistAgent - Memory and history per MASTER_SPEC v1.0

Agent ID: archivist-agent-01
Role: Memory management and historical analysis
Expertise: 0.82
Risk Factor: 0.2

This agent:
- Maintains system memory and historical records
- Provides historical context for decisions
- Identifies patterns from past outcomes
- Manages memory lineage across agent resurrections

Reference: MASTER_SPEC.md Section 4.1
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 4 (Memory Semantics)
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agents.interface import (
    AgentInterface,
    AgentVote,
    VoteDecision,
    MarketState,
    Proposal,
    Outcome,
    AgentState,
)
from utils.logger import get_logger

logger = get_logger("agents.archivist")


@dataclass
class HistoricalRecord:
    """A historical record entry."""
    record_id: str
    record_type: str
    timestamp: float
    data: Dict[str, object]
    tags: List[str] = field(default_factory=list)


@dataclass
class PatternMatch:
    """A detected historical pattern."""
    pattern_id: str
    pattern_type: str
    similarity_score: float
    historical_outcome: str
    context: Dict[str, object]


class ArchivistAgent(AgentInterface):
    """
    Archivist Agent - Memory and historical analysis.
    
    Capabilities:
    - Maintains append-only historical ledger
    - Provides context from similar past situations
    - Identifies recurring patterns
    - Tracks decision outcomes for learning
    - Manages memory inheritance for resurrected agents
    
    Memory Layers (per MASTER_SPEC_AMENDMENTS):
    - Core Ledger: Append-only, system-wide, permanent
    - Agent History: Append-only, per-agent, permanent
    - Working Memory: Mutable, per-agent, session
    """
    
    AGENT_ID = "archivist-agent-01"
    EXPERTISE_SCORE = 0.82
    RISK_FACTOR = 0.2
    
    LEDGER_LIMIT = 10000
    PATTERN_HISTORY_LIMIT = 500
    
    def __init__(self) -> None:
        """Initialize archivist agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._core_ledger: List[HistoricalRecord] = []
        self._outcome_history: Dict[str, Dict[str, object]] = {}
        self._pattern_cache: List[PatternMatch] = []
        self._tag_index: Dict[str, List[str]] = defaultdict(list)
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Record market state observation.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        record = HistoricalRecord(
            record_id=f"market_{int(market_state.timestamp)}",
            record_type="market_state",
            timestamp=market_state.timestamp,
            data={
                "volatility": market_state.volatility_index,
                "sentiment": market_state.news_sentiment,
                "price_count": len(market_state.prices),
            },
            tags=["market", "observation"],
        )
        
        self._append_to_ledger(record)
        self.set_working_memory("last_observation", market_state.timestamp)
    
    def record_decision(
        self,
        proposal_id: str,
        decision: str,
        confidence: float,
        context: Dict[str, object],
    ) -> None:
        """
        Record a decision for historical tracking.
        
        Args:
            proposal_id: Proposal identifier
            decision: Decision made
            confidence: Confidence level
            context: Decision context
        """
        record = HistoricalRecord(
            record_id=f"decision_{proposal_id}",
            record_type="decision",
            timestamp=time.time(),
            data={
                "proposal_id": proposal_id,
                "decision": decision,
                "confidence": confidence,
                "context": context,
            },
            tags=["decision", decision],
        )
        
        self._append_to_ledger(record)
    
    def record_outcome(
        self,
        proposal_id: str,
        outcome: str,
        actual_value: Optional[float],
        predicted_value: Optional[float],
    ) -> None:
        """
        Record outcome for a proposal.
        
        Args:
            proposal_id: Proposal identifier
            outcome: Outcome result
            actual_value: Actual value achieved
            predicted_value: Predicted value
        """
        self._outcome_history[proposal_id] = {
            "outcome": outcome,
            "actual_value": actual_value,
            "predicted_value": predicted_value,
            "timestamp": time.time(),
        }
        
        record = HistoricalRecord(
            record_id=f"outcome_{proposal_id}",
            record_type="outcome",
            timestamp=time.time(),
            data={
                "proposal_id": proposal_id,
                "outcome": outcome,
                "actual_value": actual_value,
                "predicted_value": predicted_value,
            },
            tags=["outcome", outcome],
        )
        
        self._append_to_ledger(record)
    
    async def analyze(self) -> Dict[str, object]:
        """
        Analyze historical patterns.
        
        Returns:
            Analysis with historical context
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        recent_decisions = self._get_recent_records("decision", limit=50)
        recent_outcomes = self._get_recent_records("outcome", limit=50)
        
        success_rate = self._calculate_success_rate(recent_outcomes)
        
        patterns = self._detect_patterns()
        
        decision_distribution = self._get_decision_distribution(recent_decisions)
        
        self._last_analysis = {
            "timestamp": time.time(),
            "ledger_size": len(self._core_ledger),
            "recent_decisions": len(recent_decisions),
            "recent_outcomes": len(recent_outcomes),
            "success_rate": success_rate,
            "patterns_detected": len(patterns),
            "decision_distribution": decision_distribution,
            "top_patterns": [self._pattern_to_dict(p) for p in patterns[:3]],
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Analysis: ledger=%d records, success_rate=%.2f, patterns=%d",
            len(self._core_ledger), success_rate, len(patterns)
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote based on historical analysis.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with historical reasoning
        """
        self._state = AgentState.VOTING
        self.heartbeat()
        
        if proposal.is_expired():
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning="Proposal expired before vote could be cast",
            )
        
        similar_proposals = self._find_similar_proposals(proposal)
        historical_success_rate = self._calculate_similar_success_rate(similar_proposals)
        
        decision, confidence, reasoning = self._evaluate_with_history(
            proposal, similar_proposals, historical_success_rate
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "similar_count": len(similar_proposals),
        })
        
        if len(self._prediction_history) > 100:
            self._prediction_history = self._prediction_history[-100:]
        
        self._state = AgentState.READY
        
        return AgentVote(
            agent_id=self._agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update historical records based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        
        self.record_outcome(
            proposal_id=outcome.proposal_id,
            outcome=outcome.result,
            actual_value=outcome.actual_value,
            predicted_value=outcome.predicted_value,
        )
        
        self._state = AgentState.READY
    
    def get_context_for_resurrection(self, agent_id: str) -> Dict[str, object]:
        """
        Get historical context for agent resurrection.
        
        Args:
            agent_id: ID of agent being resurrected
            
        Returns:
            Context for resurrection
        """
        agent_records = [
            r for r in self._core_ledger
            if r.data.get("agent_id") == agent_id
        ]
        
        recent_patterns = self._pattern_cache[-10:]
        
        return {
            "agent_history_count": len(agent_records),
            "recent_patterns": [self._pattern_to_dict(p) for p in recent_patterns],
            "overall_success_rate": self._calculate_success_rate(
                self._get_recent_records("outcome", limit=100)
            ),
        }
    
    def _append_to_ledger(self, record: HistoricalRecord) -> None:
        """Append record to core ledger (append-only)."""
        self._core_ledger.append(record)
        
        for tag in record.tags:
            self._tag_index[tag].append(record.record_id)
        
        if len(self._core_ledger) > self.LEDGER_LIMIT:
            self._core_ledger = self._core_ledger[-self.LEDGER_LIMIT:]
    
    def _get_recent_records(
        self,
        record_type: str,
        limit: int = 50,
    ) -> List[HistoricalRecord]:
        """Get recent records of a specific type."""
        matching = [r for r in self._core_ledger if r.record_type == record_type]
        return matching[-limit:]
    
    def _calculate_success_rate(
        self,
        outcome_records: List[HistoricalRecord],
    ) -> float:
        """Calculate success rate from outcome records."""
        if not outcome_records:
            return 0.5
        
        successes = sum(
            1 for r in outcome_records
            if r.data.get("outcome") in ("success", "profit", "correct")
        )
        
        return successes / len(outcome_records)
    
    def _detect_patterns(self) -> List[PatternMatch]:
        """Detect patterns in historical data."""
        patterns = []
        
        outcomes = self._get_recent_records("outcome", limit=100)
        
        consecutive_successes = 0
        consecutive_failures = 0
        
        for record in outcomes:
            outcome = record.data.get("outcome", "")
            if outcome in ("success", "profit"):
                consecutive_successes += 1
                consecutive_failures = 0
            elif outcome in ("failure", "loss"):
                consecutive_failures += 1
                consecutive_successes = 0
        
        if consecutive_successes >= 3:
            patterns.append(PatternMatch(
                pattern_id="winning_streak",
                pattern_type="streak",
                similarity_score=0.8,
                historical_outcome="positive",
                context={"streak_length": consecutive_successes},
            ))
        
        if consecutive_failures >= 3:
            patterns.append(PatternMatch(
                pattern_id="losing_streak",
                pattern_type="streak",
                similarity_score=0.8,
                historical_outcome="negative",
                context={"streak_length": consecutive_failures},
            ))
        
        self._pattern_cache = patterns
        
        return patterns
    
    def _get_decision_distribution(
        self,
        decision_records: List[HistoricalRecord],
    ) -> Dict[str, int]:
        """Get distribution of decisions."""
        distribution: Dict[str, int] = defaultdict(int)
        
        for record in decision_records:
            decision = record.data.get("decision", "unknown")
            distribution[decision] += 1
        
        return dict(distribution)
    
    def _find_similar_proposals(
        self,
        proposal: Proposal,
    ) -> List[HistoricalRecord]:
        """Find historically similar proposals."""
        similar = []
        
        for record in self._core_ledger:
            if record.record_type != "decision":
                continue
            
            context = record.data.get("context", {})
            if context.get("proposal_type") == proposal.proposal_type:
                similar.append(record)
        
        return similar[-20:]
    
    def _calculate_similar_success_rate(
        self,
        similar_proposals: List[HistoricalRecord],
    ) -> float:
        """Calculate success rate for similar proposals."""
        if not similar_proposals:
            return 0.5
        
        successes = 0
        total = 0
        
        for record in similar_proposals:
            proposal_id = record.data.get("proposal_id")
            if proposal_id in self._outcome_history:
                total += 1
                outcome = self._outcome_history[proposal_id].get("outcome", "")
                if outcome in ("success", "profit", "correct"):
                    successes += 1
        
        if total == 0:
            return 0.5
        
        return successes / total
    
    def _evaluate_with_history(
        self,
        proposal: Proposal,
        similar_proposals: List[HistoricalRecord],
        historical_success_rate: float,
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal using historical context."""
        if not similar_proposals:
            return (
                VoteDecision.ABSTAIN,
                0.4,
                "No similar historical proposals found. Insufficient historical context.",
            )
        
        if historical_success_rate > 0.7:
            return (
                VoteDecision.APPROVE,
                min(0.5 + historical_success_rate * 0.3, 0.85),
                f"Historical success rate for similar proposals: {historical_success_rate:.1%}. "
                f"Based on {len(similar_proposals)} similar cases.",
            )
        elif historical_success_rate < 0.3:
            return (
                VoteDecision.REJECT,
                min(0.5 + (1 - historical_success_rate) * 0.3, 0.85),
                f"Historical success rate for similar proposals: {historical_success_rate:.1%}. "
                f"Poor track record suggests caution.",
            )
        else:
            return (
                VoteDecision.ABSTAIN,
                0.5,
                f"Historical success rate: {historical_success_rate:.1%}. "
                f"Mixed results - deferring to domain experts.",
            )
    
    def _pattern_to_dict(self, pattern: PatternMatch) -> Dict[str, object]:
        """Convert pattern to dictionary."""
        return {
            "pattern_id": pattern.pattern_id,
            "pattern_type": pattern.pattern_type,
            "similarity_score": pattern.similarity_score,
            "historical_outcome": pattern.historical_outcome,
            "context": pattern.context,
        }


_archivist_agent: Optional[ArchivistAgent] = None
_archivist_agent_lock = threading.Lock()


def get_archivist_agent() -> ArchivistAgent:
    """Get or create archivist agent singleton."""
    global _archivist_agent
    if _archivist_agent is None:
        with _archivist_agent_lock:
            if _archivist_agent is None:
                _archivist_agent = ArchivistAgent()
    return _archivist_agent
