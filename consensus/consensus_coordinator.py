"""
MERID Enhanced Consensus Coordinator - Section 6: Swarm Coordination & Failure Modes

Extends TACo-style consensus with:
- Configurable quorum and timeouts
- Tie-breaker rules (RiskAgent veto overrides)
- Safe defaults when consensus not reached
- Fallback handling for disagreements
- Agent heartbeat monitoring
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from schemas.swarm_events import ConsensusDecision, OpinionDirection, StrategyOpinion
from observability.event_stream import publish_event, get_event_stream
from observability.swarm_telemetry import get_swarm_telemetry
from utils.logger import get_logger

logger = get_logger("consensus.coordinator")


class ConsensusState(str, Enum):
    """State of a consensus round."""
    COLLECTING = "collecting"    # Gathering opinions
    VOTING = "voting"            # Voting phase
    DECIDED = "decided"          # Consensus reached
    TIMEOUT = "timeout"          # Timed out
    VETOED = "vetoed"            # Vetoed by risk agent
    FAILED = "failed"            # Failed to reach consensus


class SafeDefaultAction(str, Enum):
    """Safe default actions when consensus fails."""
    NO_ACTION = "no_action"           # Do nothing
    REDUCE_EXPOSURE = "reduce_exposure"  # Reduce existing positions
    CLOSE_POSITIONS = "close_positions"  # Close all positions for symbol
    ESCALATE = "escalate"             # Escalate to governance


@dataclass
class ConsensusConfig:
    """Configuration for consensus rounds."""
    # Quorum settings
    min_agents_for_quorum: int = 3
    quorum_percentage: float = 0.6     # 60% of registered agents
    
    # Thresholds
    approval_threshold: float = 0.65   # Score needed for approval
    strong_approval_threshold: float = 0.8
    veto_threshold: float = -0.5       # Score below this triggers safe mode
    
    # Timeouts
    opinion_window_seconds: float = 60.0
    voting_timeout_seconds: float = 30.0
    round_timeout_seconds: float = 120.0
    
    # Retry settings
    max_retries: int = 2
    retry_delay_seconds: float = 10.0
    
    # Safe defaults
    safe_default_on_timeout: SafeDefaultAction = SafeDefaultAction.NO_ACTION
    safe_default_on_tie: SafeDefaultAction = SafeDefaultAction.NO_ACTION
    
    # Weights
    risk_agent_weight_multiplier: float = 1.5
    low_confidence_weight_penalty: float = 0.5
    confidence_threshold_for_full_weight: float = 0.7


@dataclass
class AgentVote:
    """Individual agent vote in consensus."""
    agent_id: str
    agent_role: str
    vote: str           # approve, reject, abstain, veto
    score: float        # -1.0 to 1.0
    confidence: float   # 0.0 to 1.0
    weight: float       # Computed weight
    reasoning: str
    timestamp: float = field(default_factory=time.time)
    
    def weighted_score(self) -> float:
        """Calculate trust-weighted vote score."""
        if self.vote == "veto":
            return -2.0  # Veto has special negative weight
        elif self.vote == "abstain":
            return 0.0
        return self.score * self.confidence * self.weight


@dataclass
class ConsensusRound:
    """A single consensus round for a symbol."""
    round_id: str = field(default_factory=lambda: f"cr_{uuid.uuid4().hex[:12]}")
    symbol: str = ""
    venue: str = ""
    
    # State
    state: ConsensusState = ConsensusState.COLLECTING
    
    # Votes
    votes: List[AgentVote] = field(default_factory=list)
    
    # Result
    final_score: float = 0.0
    direction: str = "flat"  # long, short, flat, reduce
    confidence: float = 0.0
    target_size_usd: float = 0.0
    
    # Participants
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    abstaining_agents: List[str] = field(default_factory=list)
    veto_agent: Optional[str] = None
    
    # Timing
    started_at: float = field(default_factory=time.time)
    decided_at: float = 0.0
    duration_ms: float = 0.0
    
    # Retry tracking
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_id": self.round_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "state": self.state.value,
            "final_score": self.final_score,
            "direction": self.direction,
            "confidence": self.confidence,
            "target_size_usd": self.target_size_usd,
            "supporting_agents": self.supporting_agents,
            "opposing_agents": self.opposing_agents,
            "abstaining_agents": self.abstaining_agents,
            "veto_agent": self.veto_agent,
            "vote_count": len(self.votes),
            "started_at": self.started_at,
            "decided_at": self.decided_at,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
        }


@dataclass
class AgentHeartbeat:
    """Agent heartbeat tracking."""
    agent_id: str
    agent_role: str
    last_heartbeat: float = field(default_factory=time.time)
    is_healthy: bool = True
    consecutive_misses: int = 0
    reliability_score: float = 1.0


class EnhancedConsensusCoordinator:
    """
    Enhanced consensus coordinator with failure handling.
    
    Key improvements over basic TACo:
    - Configurable quorum with timeout handling
    - Risk agent veto power with override rules
    - Safe defaults when consensus fails
    - Agent health monitoring
    - Disagreement escalation
    """
    
    _instance: Optional["EnhancedConsensusCoordinator"] = None
    
    def __init__(self, config: ConsensusConfig = None):
        self.config = config or ConsensusConfig()
        
        # Active rounds
        self._rounds: Dict[str, ConsensusRound] = {}  # symbol -> round
        self._round_history: List[ConsensusRound] = []
        
        # Agent tracking
        self._registered_agents: Dict[str, str] = {}  # agent_id -> role
        self._agent_heartbeats: Dict[str, AgentHeartbeat] = {}
        self._agent_reliability: Dict[str, float] = {}  # agent_id -> reliability score
        
        # Opinion tracking (NEW: for swarm integration)
        self._pending_opinions: Dict[str, List[StrategyOpinion]] = {}  # symbol -> opinions
        self._opinion_timestamps: Dict[str, float] = {}  # symbol -> last opinion time
        
        # Subscribers
        self._event_handlers: List[Callable] = []
        
        # Event stream subscription
        self._opinion_subscriber_task: Optional[asyncio.Task] = None
        
        # Locks
        self._lock = asyncio.Lock()
        
        # Metrics
        self._total_rounds = 0
        self._successful_rounds = 0
        self._timeout_rounds = 0
        self._vetoed_rounds = 0
        
        logger.info("EnhancedConsensusCoordinator initialized")
    
    @classmethod
    def get_instance(cls, config: ConsensusConfig = None) -> "EnhancedConsensusCoordinator":
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance
    
    async def start_opinion_subscriber(self) -> None:
        """Start subscribing to strategy opinion events."""
        if self._opinion_subscriber_task is not None:
            logger.warning("Opinion subscriber already running")
            return
        
        self._opinion_subscriber_task = asyncio.create_task(self._opinion_subscription_loop())
        logger.info("Opinion subscriber started")
    
    async def stop_opinion_subscriber(self) -> None:
        """Stop opinion subscriber."""
        if self._opinion_subscriber_task:
            self._opinion_subscriber_task.cancel()
            try:
                await self._opinion_subscriber_task
            except asyncio.CancelledError:
                pass
            self._opinion_subscriber_task = None
            logger.info("Opinion subscriber stopped")
    
    async def _opinion_subscription_loop(self) -> None:
        """Background loop to consume strategy opinion events."""
        event_stream = get_event_stream()
        queue = await event_stream.subscribe()
        
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    
                    # Only process strategy_opinion events
                    if event.event_type == "strategy_opinion":
                        await self._handle_opinion_event(event.payload)
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Opinion subscription error: {e}")
                    await asyncio.sleep(1.0)
        
        finally:
            await event_stream.unsubscribe(queue)
    
    async def _handle_opinion_event(self, payload: Dict[str, Any]) -> None:
        """Handle incoming strategy opinion event."""
        try:
            # Parse opinion from payload
            opinion = StrategyOpinion(**payload)
            
            async with self._lock:
                # Add to pending opinions for symbol
                if opinion.symbol not in self._pending_opinions:
                    self._pending_opinions[opinion.symbol] = []
                
                self._pending_opinions[opinion.symbol].append(opinion)
                self._opinion_timestamps[opinion.symbol] = time.time()
                
                # Check if we should trigger consensus
                opinion_count = len(self._pending_opinions[opinion.symbol])
                
                # Trigger consensus if we have enough opinions
                if opinion_count >= self.config.min_agents_for_quorum:
                    await self._try_form_consensus(opinion.symbol)
        
        except Exception as e:
            logger.error(f"Failed to handle opinion event: {e}")
    
    async def _try_form_consensus(self, symbol: str) -> None:
        """Try to form consensus from pending opinions."""
        opinions = self._pending_opinions.get(symbol, [])
        
        if len(opinions) < self.config.min_agents_for_quorum:
            return
        
        # Start consensus round if not already active
        if symbol not in self._rounds:
            await self.start_round(symbol)
        
        round = self._rounds[symbol]
        
        # Track opinion IDs for ancestry
        opinion_ids = [opinion.opinion_id for opinion in opinions]
        
        # Store opinion IDs in round metadata
        if not hasattr(round, 'opinion_ids'):
            round.opinion_ids = []
        round.opinion_ids.extend(opinion_ids)
        
        # Convert opinions to votes
        for opinion in opinions:
            # Map opinion direction to vote
            vote_map = {
                OpinionDirection.LONG: "approve",
                OpinionDirection.SHORT: "reject",
                OpinionDirection.FLAT: "abstain",
                OpinionDirection.REDUCE: "reject",
                OpinionDirection.CLOSE: "reject",
            }
            
            vote = vote_map.get(opinion.direction, "abstain")
            score = 1.0 if opinion.direction == OpinionDirection.LONG else -1.0 if opinion.direction == OpinionDirection.SHORT else 0.0
            
            # Submit vote
            await self.submit_vote(
                symbol=symbol,
                agent_id=opinion.agent_id,
                vote=vote,
                score=score,
                confidence=opinion.confidence,
                reasoning=opinion.rationale_summary,
            )
        
        # Clear pending opinions for this symbol
        self._pending_opinions[symbol] = []
        
        logger.info(f"Formed consensus for {symbol} from {len(opinions)} opinions (IDs: {opinion_ids})")
    
    def subscribe(self, handler: Callable) -> Callable[[], None]:
        """Subscribe to consensus events."""
        self._event_handlers.append(handler)
        return lambda: self._event_handlers.remove(handler)
    
    async def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit consensus event."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                logger.error(f"Consensus event handler error: {e}")
    
    async def _emit_consensus_decision(self, round: ConsensusRound) -> None:
        """Emit swarm-compliant ConsensusDecision event."""
        # Map direction string to OpinionDirection enum
        direction_map = {
            "long": OpinionDirection.LONG,
            "short": OpinionDirection.SHORT,
            "flat": OpinionDirection.FLAT,
            "reduce": OpinionDirection.REDUCE,
        }
        decision_direction = direction_map.get(round.direction, OpinionDirection.FLAT)
        
        # Separate supporting/opposing agents
        supporting = []
        opposing = []
        abstaining = []
        
        for vote in round.votes:
            if vote.vote == "approve":
                supporting.append(vote.agent_id)
            elif vote.vote == "reject":
                opposing.append(vote.agent_id)
            elif vote.vote == "abstain":
                abstaining.append(vote.agent_id)
        
        # Calculate dissent ratio
        total_non_abstain = len(supporting) + len(opposing)
        dissent_ratio = len(opposing) / total_non_abstain if total_non_abstain > 0 else 0.0
        
        # Get opinion IDs from round (if available)
        opinion_ids = getattr(round, 'opinion_ids', [])
        
        # Create ConsensusDecision event
        decision = ConsensusDecision(
            consensus_round_id=round.round_id,
            symbol=round.symbol,
            venue=round.venue,
            decision=decision_direction,
            size_usd=round.target_size_usd,
            confidence=round.confidence,
            participating_agents=[v.agent_id for v in round.votes],
            supporting_agents=supporting,
            opposing_agents=opposing,
            abstaining_agents=abstaining,
            dissenters=opposing,
            dissent_ratio=dissent_ratio,
            consensus_score=round.final_score,
            opinion_ids=opinion_ids,  # NOW POPULATED from stored opinions
            opinion_window_ms=round.duration_ms,
            avg_confidence=round.confidence,
            aggregation_method="weighted_vote",
        )
        
        # Publish to event stream
        await publish_event("consensus_decision", decision.to_dict())
        
        # Record in telemetry
        telemetry = get_swarm_telemetry()
        telemetry.record_consensus(decision, opinion_window_had_opinions=len(round.votes) > 0)
    
    # ============================================
    # AGENT MANAGEMENT
    # ============================================
    
    def register_agent(self, agent_id: str, role: str) -> None:
        """Register an agent for consensus participation."""
        self._registered_agents[agent_id] = role
        self._agent_heartbeats[agent_id] = AgentHeartbeat(
            agent_id=agent_id,
            agent_role=role,
        )
        self._agent_reliability[agent_id] = 1.0
        logger.info(f"Agent registered for consensus: {agent_id} ({role})")
    
    def unregister_agent(self, agent_id: str) -> None:
        """Unregister an agent."""
        self._registered_agents.pop(agent_id, None)
        self._agent_heartbeats.pop(agent_id, None)
        logger.info(f"Agent unregistered from consensus: {agent_id}")
    
    def record_heartbeat(self, agent_id: str) -> None:
        """Record agent heartbeat."""
        if agent_id in self._agent_heartbeats:
            hb = self._agent_heartbeats[agent_id]
            hb.last_heartbeat = time.time()
            hb.is_healthy = True
            hb.consecutive_misses = 0
    
    def check_agent_health(self, timeout_seconds: float = 60.0) -> List[str]:
        """Check for unhealthy agents."""
        unhealthy = []
        cutoff = time.time() - timeout_seconds
        
        for agent_id, hb in self._agent_heartbeats.items():
            if hb.last_heartbeat < cutoff:
                hb.is_healthy = False
                hb.consecutive_misses += 1
                
                # Reduce reliability score
                hb.reliability_score = max(0.1, hb.reliability_score * 0.9)
                self._agent_reliability[agent_id] = hb.reliability_score
                
                unhealthy.append(agent_id)
                
                if hb.consecutive_misses == 1:
                    logger.warning(f"Agent {agent_id} missed heartbeat")
        
        return unhealthy
    
    def get_healthy_agent_count(self) -> int:
        """Get count of healthy agents."""
        return sum(1 for hb in self._agent_heartbeats.values() if hb.is_healthy)
    
    def _get_agent_weight(self, agent_id: str, role: str, confidence: float) -> float:
        """Calculate agent weight for voting."""
        base_weight = self._agent_reliability.get(agent_id, 1.0)
        
        # Risk manager gets higher weight
        if "risk" in role.lower():
            base_weight *= self.config.risk_agent_weight_multiplier
        
        # Penalty for low confidence
        if confidence < self.config.confidence_threshold_for_full_weight:
            confidence_ratio = confidence / self.config.confidence_threshold_for_full_weight
            base_weight *= (self.config.low_confidence_weight_penalty + 
                          (1 - self.config.low_confidence_weight_penalty) * confidence_ratio)
        
        return base_weight
    
    # ============================================
    # CONSENSUS ROUNDS
    # ============================================
    
    async def start_round(self, symbol: str, venue: str = "paper") -> ConsensusRound:
        """Start a new consensus round for a symbol."""
        async with self._lock:
            # Check for existing round
            if symbol in self._rounds:
                existing = self._rounds[symbol]
                if existing.state == ConsensusState.COLLECTING:
                    return existing  # Return existing active round
            
            # Create new round
            round = ConsensusRound(
                symbol=symbol,
                venue=venue,
            )
            self._rounds[symbol] = round
            self._total_rounds += 1
            
            logger.info(f"Consensus round started: {round.round_id} for {symbol}")
            
            await self._emit_event("consensus.round_started", round.to_dict())
            
            # Schedule timeout
            asyncio.create_task(self._handle_round_timeout(round.round_id, symbol))
            
            return round
    
    async def submit_vote(
        self,
        symbol: str,
        agent_id: str,
        vote: str,
        score: float,
        confidence: float,
        reasoning: str,
    ) -> bool:
        """Submit a vote for a consensus round."""
        async with self._lock:
            round = self._rounds.get(symbol)
            if not round or round.state != ConsensusState.COLLECTING:
                logger.warning(f"No active round for {symbol}, vote from {agent_id} rejected")
                return False
            
            # Get agent role
            role = self._registered_agents.get(agent_id, "unknown")
            
            # Calculate weight
            weight = self._get_agent_weight(agent_id, role, confidence)
            
            # Create vote
            agent_vote = AgentVote(
                agent_id=agent_id,
                agent_role=role,
                vote=vote,
                score=score,
                confidence=confidence,
                weight=weight,
                reasoning=reasoning,
            )
            
            # Check for veto
            if vote == "veto":
                round.veto_agent = agent_id
                round.state = ConsensusState.VETOED
                await self._finalize_round(symbol, vetoed=True)
                return True
            
            # Add vote
            round.votes.append(agent_vote)
            
            # Track supporters/opposers
            if score > 0:
                round.supporting_agents.append(agent_id)
            elif score < 0:
                round.opposing_agents.append(agent_id)
            else:
                round.abstaining_agents.append(agent_id)
            
            logger.debug(f"Vote recorded: {agent_id} -> {symbol} ({vote}, score={score:.2f})")
            
            # Check if we have quorum
            if self._has_quorum(round):
                round.state = ConsensusState.VOTING
                await self._finalize_round(symbol)
            
            return True
    
    def _has_quorum(self, round: ConsensusRound) -> bool:
        """Check if round has reached quorum."""
        vote_count = len(round.votes)
        
        # Check minimum
        if vote_count < self.config.min_agents_for_quorum:
            return False
        
        # Check percentage
        healthy_count = self.get_healthy_agent_count()
        if healthy_count > 0:
            percentage = vote_count / healthy_count
            if percentage >= self.config.quorum_percentage:
                return True
        
        return vote_count >= self.config.min_agents_for_quorum
    
    async def _finalize_round(self, symbol: str, vetoed: bool = False) -> None:
        """Finalize a consensus round and determine outcome."""
        round = self._rounds.get(symbol)
        if not round:
            return
        
        round.decided_at = time.time()
        round.duration_ms = (round.decided_at - round.started_at) * 1000
        
        if vetoed:
            round.state = ConsensusState.VETOED
            round.direction = "flat"
            round.final_score = -1.0
            round.confidence = 1.0
            self._vetoed_rounds += 1
            
            logger.warning(f"Consensus vetoed by {round.veto_agent}: {symbol}")
            
            await self._emit_event("consensus.vetoed", {
                **round.to_dict(),
                "safe_action": self._get_safe_action_for_veto(),
            })
        else:
            # Calculate consensus score
            if round.votes:
                total_weight = sum(v.weight for v in round.votes if v.vote != "abstain")
                weighted_sum = sum(v.weighted_score() for v in round.votes)
                
                if total_weight > 0:
                    round.final_score = weighted_sum / total_weight
                else:
                    round.final_score = 0.0
                
                # Calculate confidence as weighted average
                round.confidence = sum(v.confidence * v.weight for v in round.votes) / max(1, total_weight)
            
            # Determine direction
            if round.final_score >= self.config.approval_threshold:
                round.direction = "long"
                round.state = ConsensusState.DECIDED
                self._successful_rounds += 1
            elif round.final_score <= -self.config.approval_threshold:
                round.direction = "short"
                round.state = ConsensusState.DECIDED
                self._successful_rounds += 1
            elif round.final_score <= self.config.veto_threshold:
                round.direction = "reduce"
                round.state = ConsensusState.DECIDED
            else:
                round.direction = "flat"
                round.state = ConsensusState.DECIDED
            
            # Calculate target size based on confidence
            base_size = 1000.0
            round.target_size_usd = base_size * round.confidence * abs(round.final_score)
            
            logger.info(
                f"Consensus reached: {symbol} -> {round.direction} "
                f"(score={round.final_score:.2f}, confidence={round.confidence:.2f})"
            )
            
            # Emit swarm-compliant ConsensusDecision event
            await self._emit_consensus_decision(round)
            
            await self._emit_event("consensus.decided", round.to_dict())
        
        # Archive round
        self._round_history.append(round)
        
        # Clean up
        if symbol in self._rounds:
            del self._rounds[symbol]
    
    async def _handle_round_timeout(self, round_id: str, symbol: str) -> None:
        """Handle round timeout."""
        await asyncio.sleep(self.config.round_timeout_seconds)
        
        async with self._lock:
            round = self._rounds.get(symbol)
            if round and round.round_id == round_id and round.state == ConsensusState.COLLECTING:
                # Check if we can retry
                if round.retry_count < self.config.max_retries:
                    round.retry_count += 1
                    logger.warning(f"Consensus round timeout, retrying ({round.retry_count}/{self.config.max_retries}): {symbol}")
                    
                    # Schedule another timeout
                    asyncio.create_task(self._handle_round_timeout(round_id, symbol))
                    return
                
                # Final timeout
                round.state = ConsensusState.TIMEOUT
                round.decided_at = time.time()
                round.duration_ms = (round.decided_at - round.started_at) * 1000
                self._timeout_rounds += 1
                
                logger.warning(f"Consensus round timed out: {symbol}")
                
                # Apply safe default
                safe_action = self.config.safe_default_on_timeout
                
                await self._emit_event("consensus.timeout", {
                    **round.to_dict(),
                    "safe_action": safe_action.value,
                })
                
                self._round_history.append(round)
                del self._rounds[symbol]
    
    def _get_safe_action_for_veto(self) -> str:
        """Get safe action when consensus is vetoed."""
        return SafeDefaultAction.NO_ACTION.value
    
    # ============================================
    # QUERY METHODS
    # ============================================
    
    def get_active_rounds(self) -> List[Dict[str, Any]]:
        """Get all active consensus rounds."""
        return [r.to_dict() for r in self._rounds.values()]
    
    def get_round_status(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific round."""
        round = self._rounds.get(symbol)
        return round.to_dict() if round else None
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get consensus metrics."""
        return {
            "total_rounds": self._total_rounds,
            "successful_rounds": self._successful_rounds,
            "timeout_rounds": self._timeout_rounds,
            "vetoed_rounds": self._vetoed_rounds,
            "success_rate": self._successful_rounds / max(1, self._total_rounds),
            "active_rounds": len(self._rounds),
            "registered_agents": len(self._registered_agents),
            "healthy_agents": self.get_healthy_agent_count(),
        }
    
    def get_recent_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent consensus decisions."""
        return [r.to_dict() for r in self._round_history[-limit:]]


def get_consensus_coordinator(config: ConsensusConfig = None) -> EnhancedConsensusCoordinator:
    """Get the global consensus coordinator instance."""
    return EnhancedConsensusCoordinator.get_instance(config)


# ============================================
# MINIMUM VIABLE SWARM
# ============================================

MINIMUM_VIABLE_AGENTS = ["risk_manager", "execution_agent"]

def check_minimum_viable_swarm(coordinator: EnhancedConsensusCoordinator) -> bool:
    """
    Check if minimum viable swarm is available.
    System can function conservatively with only RiskManager and ExecutionAgent.
    """
    available_roles = set(coordinator._registered_agents.values())
    
    for required_role in MINIMUM_VIABLE_AGENTS:
        if required_role not in available_roles:
            # Check for healthy agent with this role
            for agent_id, role in coordinator._registered_agents.items():
                if role == required_role:
                    hb = coordinator._agent_heartbeats.get(agent_id)
                    if hb and hb.is_healthy:
                        break
            else:
                return False
    
    return True


def get_limp_mode_policy() -> Dict[str, Any]:
    """
    Get policy for limp mode operation.
    In limp mode (< quorum agents), only allow position reduction.
    """
    return {
        "allowed_actions": ["reduce", "close", "flat"],
        "blocked_actions": ["long", "short"],
        "max_new_position_usd": 0,
        "require_risk_approval": True,
        "escalate_to_governance": True,
    }
