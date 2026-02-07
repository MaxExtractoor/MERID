"""
SkepticAgent - Adversarial challenge per MASTER_SPEC v1.0

Agent ID: skeptic-agent-01
Role: Adversarial challenge and devil's advocate
Expertise: 0.90
Risk Factor: 0.6

This agent:
- Challenges all proposals with adversarial reasoning
- Identifies potential failure modes and edge cases
- Has VETO power on high-risk proposals (with cooldown)
- Acts as the system's immune system against bad decisions

Reference: MASTER_SPEC.md Section 4.1
Reference: MASTER_SPEC_AMENDMENTS.md Amendment 3.1 (Veto Cooldown)
"""

from __future__ import annotations

import time
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

logger = get_logger("agents.skeptic")


@dataclass
class ChallengeRecord:
    """Record of a challenge issued by skeptic."""
    proposal_id: str
    challenge_type: str
    severity: str
    reasoning: str
    timestamp: float
    was_veto: bool = False


class SkepticAgent(AgentInterface):
    """
    Skeptic Agent - Adversarial challenger and devil's advocate.
    
    Capabilities:
    - Identifies logical flaws in proposals
    - Challenges assumptions and biases
    - Detects groupthink and confirmation bias
    - Issues high-confidence vetoes on dangerous proposals
    - Tracks veto usage to prevent system paralysis
    
    This agent has special VETO power per MASTER_SPEC:
    - Veto requires confidence > 0.80
    - Maximum 3 vetoes per hour (Amendment 3.1)
    - Veto blocks proposal regardless of other votes
    """
    
    AGENT_ID = "skeptic-agent-01"
    EXPERTISE_SCORE = 0.90
    RISK_FACTOR = 0.6
    
    VETO_CONFIDENCE_THRESHOLD = 0.80
    MAX_VETOES_PER_HOUR = 3
    VETO_COOLDOWN_SECONDS = 3600
    
    CHALLENGE_PATTERNS = [
        "confirmation_bias",
        "recency_bias",
        "survivorship_bias",
        "anchoring",
        "overconfidence",
        "groupthink",
        "sunk_cost",
        "availability_heuristic",
    ]
    
    def __init__(self) -> None:
        """Initialize skeptic agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._challenge_history: List[ChallengeRecord] = []
        self._veto_timestamps: List[float] = []
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
        self._market_context: Dict[str, object] = {}
        
        self._contrarian_mode: bool = True
        self._challenge_threshold: float = 0.3
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state for context.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self._market_context = {
            "timestamp": market_state.timestamp,
            "volatility": market_state.volatility_index,
            "sentiment": market_state.news_sentiment,
            "price_count": len(market_state.prices),
        }
        
        self.set_working_memory("market_context", self._market_context)
        
        self._logger.debug(
            "Observed: volatility=%.4f, sentiment=%.2f",
            market_state.volatility_index, market_state.news_sentiment
        )
    
    async def analyze(self) -> Dict[str, object]:
        """
        Analyze current state for potential challenges.
        
        Returns:
            Analysis with identified biases and concerns
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        vetoes_remaining = self._get_vetoes_remaining()
        can_veto = vetoes_remaining > 0
        
        recent_challenges = [
            c for c in self._challenge_history
            if time.time() - c.timestamp < 3600
        ]
        
        challenge_rate = len(recent_challenges) / max(len(self._challenge_history), 1)
        
        volatility = self._market_context.get("volatility", 0)
        sentiment = self._market_context.get("sentiment", 0)
        
        if volatility > 0.05:
            market_concern = "high_volatility"
            concern_level = "elevated"
        elif abs(sentiment) > 0.7:
            market_concern = "extreme_sentiment"
            concern_level = "elevated"
        else:
            market_concern = "none"
            concern_level = "normal"
        
        self._last_analysis = {
            "timestamp": time.time(),
            "vetoes_remaining": vetoes_remaining,
            "can_veto": can_veto,
            "recent_challenge_count": len(recent_challenges),
            "challenge_rate": challenge_rate,
            "market_concern": market_concern,
            "concern_level": concern_level,
            "contrarian_mode": self._contrarian_mode,
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Analysis: vetoes_remaining=%d, concern=%s, contrarian=%s",
            vetoes_remaining, market_concern, self._contrarian_mode
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on proposal with adversarial perspective.
        
        The skeptic agent:
        1. Always looks for reasons to reject
        2. Challenges assumptions in the proposal
        3. Issues veto if confidence > 0.80 and vetoes available
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with adversarial reasoning
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
        
        if self._last_analysis is None:
            await self.analyze()
        
        challenges = self._identify_challenges(proposal)
        
        decision, confidence, reasoning, is_veto = self._evaluate_with_challenges(
            proposal, challenges
        )
        
        if is_veto and decision == VoteDecision.REJECT:
            if self._can_issue_veto():
                self._record_veto()
                reasoning = f"[VETO] {reasoning}"
                self._logger.warning(
                    "VETO issued for proposal %s: %s",
                    proposal.proposal_id, reasoning
                )
            else:
                confidence = min(confidence, self.VETO_CONFIDENCE_THRESHOLD - 0.01)
                reasoning = f"[VETO BLOCKED - cooldown] {reasoning}"
                self._logger.info(
                    "Veto blocked by cooldown for proposal %s",
                    proposal.proposal_id
                )
        
        challenge_record = ChallengeRecord(
            proposal_id=proposal.proposal_id,
            challenge_type=challenges[0]["type"] if challenges else "none",
            severity="high" if is_veto else "normal",
            reasoning=reasoning,
            timestamp=time.time(),
            was_veto=is_veto and decision == VoteDecision.REJECT,
        )
        self._challenge_history.append(challenge_record)
        if len(self._challenge_history) > 200:
            self._challenge_history = self._challenge_history[-200:]
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "was_veto": is_veto,
            "challenges": [c["type"] for c in challenges],
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
        Update internal state based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        
        matching_prediction = None
        for pred in self._prediction_history:
            if pred.get("proposal_id") == outcome.proposal_id:
                matching_prediction = pred
                break
        
        if matching_prediction is None:
            return
        
        was_correct = self._evaluate_prediction_accuracy(matching_prediction, outcome)
        
        if matching_prediction.get("was_veto"):
            if was_correct:
                self._logger.info(
                    "Veto was justified for %s - outcome confirmed concerns",
                    outcome.proposal_id
                )
            else:
                self._logger.warning(
                    "Veto may have been excessive for %s - outcome was positive",
                    outcome.proposal_id
                )
                self._challenge_threshold = min(self._challenge_threshold + 0.05, 0.6)
        
        self._state = AgentState.READY
    
    def _identify_challenges(self, proposal: Proposal) -> List[Dict[str, object]]:
        """
        Identify potential challenges to the proposal.
        
        Args:
            proposal: Proposal to challenge
            
        Returns:
            List of identified challenges
        """
        challenges = []
        payload = proposal.payload
        
        if payload.get("confidence", 0) > 0.9:
            challenges.append({
                "type": "overconfidence",
                "severity": 0.7,
                "description": "Proposal shows signs of overconfidence bias",
            })
        
        if payload.get("based_on_recent", False) or "recent" in str(payload).lower():
            challenges.append({
                "type": "recency_bias",
                "severity": 0.5,
                "description": "Proposal may be overly influenced by recent events",
            })
        
        supporting_agents = payload.get("supporting_agents", [])
        if len(supporting_agents) > 5:
            challenges.append({
                "type": "groupthink",
                "severity": 0.6,
                "description": "High agent agreement may indicate groupthink",
            })
        
        if self._market_context.get("volatility", 0) > 0.05:
            challenges.append({
                "type": "high_volatility_risk",
                "severity": 0.8,
                "description": "Market volatility increases execution risk",
            })
        
        sentiment = self._market_context.get("sentiment", 0)
        proposal_direction = payload.get("direction", "")
        if (sentiment > 0.5 and proposal_direction == "long") or \
           (sentiment < -0.5 and proposal_direction == "short"):
            challenges.append({
                "type": "confirmation_bias",
                "severity": 0.6,
                "description": "Proposal aligns too closely with current sentiment",
            })
        
        leverage = payload.get("leverage", 1.0)
        if leverage > 2.0:
            challenges.append({
                "type": "excessive_leverage",
                "severity": 0.9,
                "description": f"Leverage of {leverage}x increases liquidation risk",
            })
        
        return challenges
    
    def _evaluate_with_challenges(
        self,
        proposal: Proposal,
        challenges: List[Dict[str, object]],
    ) -> tuple[VoteDecision, float, str, bool]:
        """
        Evaluate proposal considering identified challenges.
        
        Args:
            proposal: Proposal being evaluated
            challenges: Identified challenges
            
        Returns:
            Tuple of (decision, confidence, reasoning, is_veto_worthy)
        """
        if not challenges:
            return (
                VoteDecision.ABSTAIN,
                0.4,
                "No significant challenges identified. Deferring to domain experts.",
                False,
            )
        
        max_severity = max(c["severity"] for c in challenges)
        avg_severity = sum(c["severity"] for c in challenges) / len(challenges)
        
        challenge_descriptions = [c["description"] for c in challenges]
        reasoning_parts = [
            f"Identified {len(challenges)} challenge(s):",
            *[f"- {desc}" for desc in challenge_descriptions[:3]],
        ]
        
        is_veto_worthy = False
        
        if max_severity > 0.85 or (len(challenges) >= 3 and avg_severity > 0.6):
            decision = VoteDecision.REJECT
            confidence = min(0.5 + avg_severity * 0.4, 0.95)
            
            if confidence >= self.VETO_CONFIDENCE_THRESHOLD:
                is_veto_worthy = True
                reasoning_parts.append(
                    f"CRITICAL: Severity ({max_severity:.2f}) warrants veto consideration."
                )
            
        elif avg_severity > 0.5:
            decision = VoteDecision.REJECT
            confidence = 0.5 + avg_severity * 0.3
            reasoning_parts.append(
                f"Elevated concerns (avg severity: {avg_severity:.2f}) warrant rejection."
            )
            
        elif avg_severity > 0.3:
            decision = VoteDecision.ABSTAIN
            confidence = 0.5
            reasoning_parts.append(
                f"Moderate concerns (avg severity: {avg_severity:.2f}). "
                f"Recommend caution but not blocking."
            )
            
        else:
            decision = VoteDecision.ABSTAIN
            confidence = 0.4
            reasoning_parts.append(
                "Minor concerns only. Deferring to domain experts."
            )
        
        reasoning = " ".join(reasoning_parts)
        
        return (decision, confidence, reasoning, is_veto_worthy)
    
    def _can_issue_veto(self) -> bool:
        """Check if veto can be issued (cooldown check)."""
        return self._get_vetoes_remaining() > 0
    
    def _get_vetoes_remaining(self) -> int:
        """Get number of vetoes remaining in current window."""
        self._cleanup_veto_timestamps()
        return max(0, self.MAX_VETOES_PER_HOUR - len(self._veto_timestamps))
    
    def _record_veto(self) -> None:
        """Record a veto usage."""
        self._veto_timestamps.append(time.time())
        self._logger.info(
            "Veto recorded. Vetoes remaining: %d/%d",
            self._get_vetoes_remaining(), self.MAX_VETOES_PER_HOUR
        )
    
    def _cleanup_veto_timestamps(self) -> None:
        """Remove expired veto records."""
        cutoff = time.time() - self.VETO_COOLDOWN_SECONDS
        self._veto_timestamps = [t for t in self._veto_timestamps if t > cutoff]
    
    def _evaluate_prediction_accuracy(
        self,
        prediction: Dict[str, object],
        outcome: Outcome,
    ) -> bool:
        """Evaluate if skeptic's challenge was justified."""
        pred_decision = prediction.get("decision", "abstain")
        actual_result = outcome.result
        
        if pred_decision == "reject" and actual_result in ("failure", "loss", "incorrect"):
            return True
        if pred_decision == "approve" and actual_result in ("success", "profit", "correct"):
            return True
        
        return False


_skeptic_agent: Optional[SkepticAgent] = None


def get_skeptic_agent() -> SkepticAgent:
    """Get or create skeptic agent singleton."""
    global _skeptic_agent
    if _skeptic_agent is None:
        _skeptic_agent = SkepticAgent()
    return _skeptic_agent
