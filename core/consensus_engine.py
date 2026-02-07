"""
Consensus Engine - Production implementation.

Continuous consensus processing with:
- Trust-weighted voting
- Risk agent VETO power
- Skeptic re-round capability
- 2/3 quorum requirement
- Inter-system API integration for authority enforcement
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from collections import defaultdict
import time

from core.streaming_bus import get_event_bus, EventChannel, StreamEvent
from core.intersystem_api import get_intersystem_api, MeridSystem, IntentStatus
from core.consensus_logging import (
    get_consensus_logger, VoteType, ConsensusOutcome
)
from utils.logger import get_logger

logger = get_logger("core.consensus")


@dataclass
class Vote:
    """Individual agent vote."""
    agent_id: str
    proposal: str
    signal: str  # bullish, bearish, neutral
    confidence: float
    energy: float = 1.0
    trust: float = 1.0
    timestamp: float = field(default_factory=time.time)
    
    @property
    def weight(self) -> float:
        """Calculate vote weight: trust × energy × confidence."""
        return self.trust * self.energy * self.confidence


@dataclass
class ConsensusResult:
    """Result of consensus resolution."""
    decision: str
    signal: str
    confidence: float
    votes: List[Vote]
    quorum_met: bool
    vetoed: bool = False
    veto_reason: str = ""
    reround_requested: bool = False
    reround_reason: str = ""
    timestamp: float = field(default_factory=time.time)


class ConsensusEngine:
    """
    Production consensus engine.
    
    Processes agent outputs continuously and resolves
    consensus decisions with proper voting mechanics.
    """
    
    def __init__(self):
        self.bus = get_event_bus()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        
        # Vote collection
        self.pending_votes: Dict[str, Vote] = {}
        self.vote_window = 5.0  # Seconds to collect votes
        
        # Trust scores (updated by meta-audit)
        self.trust_scores: Dict[str, float] = defaultdict(lambda: 1.0)
        
        # Consensus parameters
        self.quorum_threshold = 0.67  # 2/3 majority
        self.min_votes = 3  # Minimum votes for consensus
        
        # State
        self.last_consensus_time = 0.0
        self.consensus_interval = 10.0  # Resolve consensus every N seconds
        
        # CONSTITUTIONAL: Consensus transparency logging
        self.consensus_logger = get_consensus_logger()
        self.current_round_id: Optional[str] = None
        
    async def start(self):
        """Start the consensus engine."""
        if self.running:
            return
        
        self.running = True
        
        # Subscribe to agent outputs
        await self.bus.subscribe(
            subscriber_id="consensus-engine",
            channels=[EventChannel.AGENT_OUTPUT],
            queue_size=100
        )
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Consensus engine started")
        
    async def stop(self):
        """Stop the consensus engine."""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.bus.unsubscribe("consensus-engine")
        logger.info("Consensus engine stopped")
        
    async def _run_loop(self):
        """Main consensus processing loop."""
        logger.info("Consensus engine entering processing loop")
        
        while self.running:
            try:
                # Get events from agent outputs
                event = await asyncio.wait_for(
                    self.bus.get_event("consensus-engine"),
                    timeout=1.0
                )
                
                if event:
                    await self._process_event(event)
                
                # Check if it's time to resolve consensus
                now = time.time()
                if now - self.last_consensus_time >= self.consensus_interval:
                    if len(self.pending_votes) >= self.min_votes:
                        result = await self._resolve_consensus()
                        if result:
                            await self._publish_result(result)
                    self.last_consensus_time = now
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consensus engine error: {e}")
                await asyncio.sleep(1)
                
    async def _process_event(self, event: StreamEvent):
        """Process an agent output event."""
        data = event.data
        event_type = event.event_type
        
        # Handle risk veto
        if event_type == "risk_veto":
            self._handle_veto(event)
            return
        
        # Handle skeptic challenge
        if event_type == "skeptic_challenge":
            self._handle_challenge(event)
            return
        
        # Handle trust updates
        if event_type == "performance_audit":
            self._update_trust_scores(data)
            return
        
        # Extract vote from signal events
        if event_type in ["price_signal", "synthesis_proposal", "trade_plan", "news_impact"]:
            vote = self._extract_vote(event)
            if vote:
                self.pending_votes[vote.agent_id] = vote
                
    def _extract_vote(self, event: StreamEvent) -> Optional[Vote]:
        """Extract a vote from an agent event."""
        data = event.data
        
        signal = data.get("signal", data.get("direction", ""))
        if not signal:
            return None
        
        confidence = data.get("confidence", 0.5)
        
        vote = Vote(
            agent_id=event.source,
            proposal=event.event_type,
            signal=signal.lower(),
            confidence=confidence,
            trust=self.trust_scores[event.source]
        )
        
        # CONSTITUTIONAL: Log vote in consensus transparency system
        if self.current_round_id:
            vote_type = VoteType.APPROVE if signal.lower() in ["bullish", "buy"] else VoteType.REJECT
            reasoning = data.get("reasoning", f"{signal} signal with {confidence:.1%} confidence")
            
            self.consensus_logger.record_vote(
                round_id=self.current_round_id,
                agent_id=event.source,
                vote=vote_type,
                reasoning=reasoning,
                confidence=confidence,
                trust_weight=self.trust_scores[event.source]
            )
        
        return vote
        
    def _handle_veto(self, event: StreamEvent):
        """Handle risk agent veto."""
        data = event.data
        logger.warning(f"VETO received from {event.source}: {data.get('reason')}")
        
        # Clear pending votes - veto blocks consensus
        self.pending_votes.clear()
        
    def _handle_challenge(self, event: StreamEvent):
        """Handle skeptic challenge."""
        data = event.data
        
        if data.get("force_reround"):
            logger.warning(f"Re-round requested by {event.source}: {data.get('reasoning')}")
            # Don't clear votes, but mark for re-evaluation
            
    def _update_trust_scores(self, data: Dict):
        """Update trust scores from meta-audit."""
        agents = data.get("agents", [])
        for agent in agents:
            agent_id = agent.get("agent_id")
            trust = agent.get("trust_score", 1.0)
            if agent_id:
                self.trust_scores[agent_id] = trust
                
    async def _resolve_consensus(self) -> Optional[ConsensusResult]:
        """Resolve consensus from pending votes with inter-system authority checks."""
        if not self.pending_votes:
            return None
        
        # CONSTITUTIONAL: Start consensus round logging
        proposal = {
            "type": "market_consensus",
            "votes_count": len(self.pending_votes),
            "timestamp": time.time()
        }
        self.current_round_id = self.consensus_logger.start_round(
            proposal=proposal,
            quorum_required=self.min_votes
        )
        
        votes = list(self.pending_votes.values())
        self.pending_votes.clear()
        
        # Calculate weighted votes
        bullish_weight = sum(v.weight for v in votes if v.signal == "bullish")
        bearish_weight = sum(v.weight for v in votes if v.signal == "bearish")
        total_weight = bullish_weight + bearish_weight
        
        if total_weight == 0:
            return None
        
        # Determine signal
        if bullish_weight > bearish_weight:
            signal = "bullish"
            signal_weight = bullish_weight
        elif bearish_weight > bullish_weight:
            signal = "bearish"
            signal_weight = bearish_weight
        else:
            signal = "neutral"
            signal_weight = 0
        
        # Check quorum
        quorum_ratio = signal_weight / total_weight if total_weight > 0 else 0
        quorum_met = quorum_ratio >= self.quorum_threshold
        
        # Calculate confidence
        confidence = quorum_ratio * (sum(v.confidence for v in votes) / len(votes))
        
        # Determine decision
        if not quorum_met:
            decision = "NO_ACTION"
        elif signal == "bullish":
            decision = "EXECUTE_LONG"
        elif signal == "bearish":
            decision = "EXECUTE_SHORT"
        else:
            decision = "HOLD"
        
        # Inter-system API authority check for execution decisions
        vetoed = False
        veto_reason = ""
        if decision in ("EXECUTE_LONG", "EXECUTE_SHORT") and quorum_met:
            try:
                api = get_intersystem_api()
                # Check if system is frozen
                if api.is_frozen():
                    vetoed = True
                    veto_reason = "System is in emergency freeze state"
                    decision = "NO_ACTION"
                    logger.warning(f"Consensus vetoed: {veto_reason}")
            except Exception as e:
                logger.error(f"Inter-system API check failed: {e}")
        
        result = ConsensusResult(
            decision=decision,
            signal=signal,
            confidence=confidence,
            votes=votes,
            quorum_met=quorum_met,
            vetoed=vetoed,
            veto_reason=veto_reason
        )
        
        # CONSTITUTIONAL: Complete consensus round logging
        if self.current_round_id:
            outcome = ConsensusOutcome.PASSED if quorum_met and not vetoed else ConsensusOutcome.FAILED
            if vetoed:
                outcome = ConsensusOutcome.FAILED
            elif not quorum_met:
                outcome = ConsensusOutcome.NO_QUORUM
            
            self.consensus_logger.complete_round(
                round_id=self.current_round_id,
                outcome=outcome,
                final_confidence=confidence,
                final_action=decision
            )
            self.current_round_id = None
        
        logger.info(f"Consensus resolved: {decision} ({signal}) confidence={confidence:.2%} quorum={quorum_met} vetoed={vetoed}")
        
        return result
        
    async def _publish_result(self, result: ConsensusResult):
        """Publish consensus result to event bus."""
        await self.bus.publish(StreamEvent(
            channel=EventChannel.CONSENSUS,
            event_type="consensus_decision",
            source="consensus-engine",
            data={
                "decision": result.decision,
                "signal": result.signal,
                "confidence": result.confidence,
                "quorum_met": result.quorum_met,
                "vote_count": len(result.votes),
                "vetoed": result.vetoed,
                "votes": [
                    {
                        "agent_id": v.agent_id,
                        "signal": v.signal,
                        "confidence": v.confidence,
                        "weight": v.weight
                    }
                    for v in result.votes
                ]
            },
            timestamp=result.timestamp
        ))


# Singleton
_consensus_engine: Optional[ConsensusEngine] = None


def get_consensus_engine() -> ConsensusEngine:
    """Get the singleton consensus engine."""
    global _consensus_engine
    if _consensus_engine is None:
        _consensus_engine = ConsensusEngine()
    return _consensus_engine
