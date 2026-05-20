"""
SynthesizerAgent - Cross-signal synthesis per MASTER_SPEC v1.0

Agent ID: synthesizer-agent-01
Role: Cross-signal synthesis and integration
Expertise: 0.87
Risk Factor: 0.4

This agent:
- Integrates signals from all other agents
- Identifies convergence and divergence patterns
- Synthesizes holistic market view
- Votes based on multi-signal consensus

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import threading
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

logger = get_logger("agents.synthesizer")


@dataclass
class AgentSignal:
    """Signal from another agent."""
    agent_id: str
    signal_type: str
    direction: str
    strength: float
    confidence: float
    timestamp: float


@dataclass
class SynthesisResult:
    """Result of signal synthesis."""
    timestamp: float
    signal_count: int
    convergence_score: float
    dominant_direction: str
    confidence: float
    divergent_agents: List[str]


class SynthesizerAgent(AgentInterface):
    """
    Synthesizer Agent - Integrates signals from all agents.
    
    Capabilities:
    - Aggregates signals from market, news, risk agents
    - Detects signal convergence and divergence
    - Weights signals by agent expertise and confidence
    - Identifies conflicting viewpoints
    - Generates holistic synthesis for voting
    
    This agent acts as the integration layer,
    combining diverse perspectives into unified assessment.
    """
    
    AGENT_ID = "synthesizer-agent-01"
    EXPERTISE_SCORE = 0.87
    RISK_FACTOR = 0.4
    
    SIGNAL_HISTORY_LIMIT = 200
    CONVERGENCE_THRESHOLD = 0.7
    
    AGENT_WEIGHTS = {
        "market-analyst-01": 0.25,
        "news-analyst-01": 0.20,
        "risk-agent-01": 0.25,
        "skeptic-agent-01": 0.15,
        "strategy-agent-01": 0.15,
    }
    
    def __init__(self) -> None:
        """Initialize synthesizer agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._signal_buffer: Dict[str, AgentSignal] = {}
        self._synthesis_history: List[SynthesisResult] = []
        self._last_synthesis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state.
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self.set_working_memory("market_state", {
            "timestamp": market_state.timestamp,
            "volatility": market_state.volatility_index,
            "sentiment": market_state.news_sentiment,
        })
    
    def receive_signal(self, signal: AgentSignal) -> None:
        """
        Receive signal from another agent.
        
        Args:
            signal: Signal from agent
        """
        self._signal_buffer[signal.agent_id] = signal
        self._logger.debug(
            "Received signal from %s: direction=%s, strength=%.2f",
            signal.agent_id, signal.direction, signal.strength
        )
    
    async def analyze(self) -> Dict[str, object]:
        """
        Synthesize all received signals.
        
        Returns:
            Synthesis results
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        if not self._signal_buffer:
            self._last_synthesis = {
                "timestamp": time.time(),
                "signal_count": 0,
                "convergence_score": 0.0,
                "dominant_direction": "neutral",
                "confidence": 0.3,
                "assessment": "insufficient_signals",
            }
            return self._last_synthesis
        
        signals = list(self._signal_buffer.values())
        
        weighted_direction = self._calculate_weighted_direction(signals)
        convergence = self._calculate_convergence(signals)
        divergent = self._identify_divergent_agents(signals, weighted_direction)
        
        if weighted_direction > 0.3:
            dominant = "bullish"
        elif weighted_direction < -0.3:
            dominant = "bearish"
        else:
            dominant = "neutral"
        
        confidence = self._calculate_synthesis_confidence(
            signals, convergence, len(divergent)
        )
        
        result = SynthesisResult(
            timestamp=time.time(),
            signal_count=len(signals),
            convergence_score=convergence,
            dominant_direction=dominant,
            confidence=confidence,
            divergent_agents=divergent,
        )
        self._synthesis_history.append(result)
        if len(self._synthesis_history) > 100:
            self._synthesis_history = self._synthesis_history[-100:]
        
        self._last_synthesis = {
            "timestamp": time.time(),
            "signal_count": len(signals),
            "weighted_direction": weighted_direction,
            "convergence_score": convergence,
            "dominant_direction": dominant,
            "confidence": confidence,
            "divergent_agents": divergent,
            "signals_by_agent": {
                s.agent_id: {
                    "direction": s.direction,
                    "strength": s.strength,
                    "confidence": s.confidence,
                }
                for s in signals
            },
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Synthesis: %d signals, direction=%s (%.2f), convergence=%.2f",
            len(signals), dominant, weighted_direction, convergence
        )
        
        return self._last_synthesis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote based on synthesized signals.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with synthesis reasoning
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
        
        if self._last_synthesis is None or self._last_synthesis.get("signal_count", 0) == 0:
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.3,
                reasoning="Insufficient signals for synthesis",
            )
        
        decision, confidence, reasoning = self._evaluate_proposal(
            proposal.proposal_type, proposal.payload
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "synthesis": self._last_synthesis.get("dominant_direction"),
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
        self._state = AgentState.READY
    
    def _calculate_weighted_direction(self, signals: List[AgentSignal]) -> float:
        """
        Calculate weighted direction from all signals.
        
        Args:
            signals: List of agent signals
            
        Returns:
            Weighted direction [-1.0, 1.0]
        """
        total_weight = 0.0
        weighted_sum = 0.0
        
        for signal in signals:
            agent_weight = self.AGENT_WEIGHTS.get(signal.agent_id, 0.1)
            signal_weight = agent_weight * signal.confidence
            
            if signal.direction == "bullish":
                direction_value = signal.strength
            elif signal.direction == "bearish":
                direction_value = -signal.strength
            else:
                direction_value = 0.0
            
            weighted_sum += direction_value * signal_weight
            total_weight += signal_weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
    
    def _calculate_convergence(self, signals: List[AgentSignal]) -> float:
        """
        Calculate convergence score (how aligned are signals).
        
        Args:
            signals: List of agent signals
            
        Returns:
            Convergence score [0.0, 1.0]
        """
        if len(signals) < 2:
            return 0.5
        
        directions = []
        for signal in signals:
            if signal.direction == "bullish":
                directions.append(1)
            elif signal.direction == "bearish":
                directions.append(-1)
            else:
                directions.append(0)
        
        avg_direction = sum(directions) / len(directions)
        
        variance = sum((d - avg_direction) ** 2 for d in directions) / len(directions)
        
        convergence = 1.0 - min(variance / 2.0, 1.0)
        
        return convergence
    
    def _identify_divergent_agents(
        self,
        signals: List[AgentSignal],
        weighted_direction: float,
    ) -> List[str]:
        """
        Identify agents whose signals diverge from consensus.
        
        Args:
            signals: List of agent signals
            weighted_direction: Overall weighted direction
            
        Returns:
            List of divergent agent IDs
        """
        divergent = []
        
        consensus_direction = "bullish" if weighted_direction > 0.2 else (
            "bearish" if weighted_direction < -0.2 else "neutral"
        )
        
        for signal in signals:
            if consensus_direction == "bullish" and signal.direction == "bearish":
                divergent.append(signal.agent_id)
            elif consensus_direction == "bearish" and signal.direction == "bullish":
                divergent.append(signal.agent_id)
        
        return divergent
    
    def _calculate_synthesis_confidence(
        self,
        signals: List[AgentSignal],
        convergence: float,
        divergent_count: int,
    ) -> float:
        """
        Calculate confidence in synthesis.
        
        Args:
            signals: List of signals
            convergence: Convergence score
            divergent_count: Number of divergent agents
            
        Returns:
            Confidence score [0.0, 1.0]
        """
        signal_confidence = min(len(signals) / 5, 1.0)
        
        avg_agent_confidence = (
            sum(s.confidence for s in signals) / len(signals)
            if signals else 0.5
        )
        
        divergence_penalty = divergent_count * 0.1
        
        base_confidence = (
            signal_confidence * 0.3 +
            convergence * 0.4 +
            avg_agent_confidence * 0.3
        )
        
        return max(0.2, min(base_confidence - divergence_penalty, 0.95)) * self._expertise_score
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal based on synthesis."""
        if self._last_synthesis is None:
            return (VoteDecision.ABSTAIN, 0.3, "No synthesis available")
        
        direction = self._last_synthesis.get("dominant_direction", "neutral")
        weighted = self._last_synthesis.get("weighted_direction", 0)
        convergence = self._last_synthesis.get("convergence_score", 0)
        confidence = self._last_synthesis.get("confidence", 0.5)
        divergent = self._last_synthesis.get("divergent_agents", [])
        
        if proposal_type in ("buy", "long", "bullish_bet"):
            if direction == "bullish" and convergence > self.CONVERGENCE_THRESHOLD:
                return (
                    VoteDecision.APPROVE,
                    confidence,
                    f"Synthesis shows {direction} consensus (convergence={convergence:.2f}). "
                    f"Weighted direction: {weighted:.2f}. "
                    f"{len(divergent)} divergent agent(s).",
                )
            elif direction == "bearish":
                return (
                    VoteDecision.REJECT,
                    confidence,
                    f"Synthesis shows {direction} consensus contradicting bullish proposal. "
                    f"Weighted direction: {weighted:.2f}.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"Synthesis inconclusive (direction={direction}, convergence={convergence:.2f}). "
                    f"Insufficient consensus for strong position.",
                )
        
        elif proposal_type in ("sell", "short", "bearish_bet"):
            if direction == "bearish" and convergence > self.CONVERGENCE_THRESHOLD:
                return (
                    VoteDecision.APPROVE,
                    confidence,
                    f"Synthesis shows {direction} consensus (convergence={convergence:.2f}). "
                    f"Weighted direction: {weighted:.2f}.",
                )
            elif direction == "bullish":
                return (
                    VoteDecision.REJECT,
                    confidence,
                    f"Synthesis shows {direction} consensus contradicting bearish proposal. "
                    f"Weighted direction: {weighted:.2f}.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"Synthesis inconclusive (direction={direction}, convergence={convergence:.2f}).",
                )
        
        return (
            VoteDecision.ABSTAIN,
            0.3,
            f"Proposal type '{proposal_type}' - deferring to domain experts.",
        )


_synthesizer_agent: Optional[SynthesizerAgent] = None
_synthesizer_agent_lock = threading.Lock()


def get_synthesizer_agent() -> SynthesizerAgent:
    """Get or create synthesizer agent singleton."""
    global _synthesizer_agent
    if _synthesizer_agent is None:
        with _synthesizer_agent_lock:
            if _synthesizer_agent is None:
                _synthesizer_agent = SynthesizerAgent()
    return _synthesizer_agent
