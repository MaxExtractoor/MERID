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
import threading
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
    # H4: domain this result is authoritative for.
    # ConsensusEngine is authoritative for 'crypto' venues only.
    # Kalshi decisions are authoritative from SwarmConsensusAggregator.
    authoritative_for: str = "crypto"
    abstention_count: int = 0


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
        # BUG-6 fix: default 0.3 instead of 1.0 so new/unknown agents start
        # with reduced influence rather than full voting weight.
        self.trust_scores: Dict[str, float] = defaultdict(lambda: 0.3)

        # BUG-6 fix: explicit allowlist of authorised voter source IDs.
        # Empty set means allowlist is disabled (permissive mode for bootstrap).
        # Populate via register_voter() or load_voter_allowlist().
        self._voter_allowlist: set = set()
        
        # Consensus parameters
        self.quorum_threshold = 0.67  # 2/3 majority
        self.min_votes = 3  # Minimum votes for consensus
        
        # State
        self.last_consensus_time = 0.0
        self.consensus_interval = 10.0  # Resolve consensus every N seconds
        
        # CONSTITUTIONAL: Consensus transparency logging
        self.consensus_logger = get_consensus_logger()
        self.current_round_id: Optional[str] = None

        # Lane intent storage — keyed by lane_id, holds KalshiContext + RiskDecision dicts
        self._lane_intents: Dict[str, Any] = {}
        
    def register_voter(self, source_id: str, initial_trust: float = 0.5) -> None:
        """Add a source ID to the authorised voter allowlist.

        BUG-6 fix: only explicitly registered agents may contribute votes.
        """
        self._voter_allowlist.add(source_id)
        if source_id not in self.trust_scores:
            self.trust_scores[source_id] = initial_trust
        logger.info("ConsensusEngine: registered voter '%s' (trust=%.2f)", source_id, initial_trust)

    def unregister_voter(self, source_id: str) -> None:
        """Remove a source ID from the authorised voter allowlist."""
        self._voter_allowlist.discard(source_id)
        logger.info("ConsensusEngine: unregistered voter '%s'", source_id)

    def update_lane_intent(self, lane_id: str, intent_data: Dict[str, Any]) -> None:
        """Store Kalshi + RCK intent data for a lane (used by API endpoints)."""
        self._lane_intents[lane_id] = intent_data

    def get_lane_intent(self, lane_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored lane intent data."""
        return self._lane_intents.get(lane_id)

    async def start(self):
        """Start the consensus engine."""
        if self.running:
            return
        
        self.running = True
        
        # Subscribe to agent outputs (crypto venue signals)
        await self.bus.subscribe_named(
            subscriber_id="consensus-engine",
            channels=[EventChannel.AGENT_OUTPUT],
            queue_size=100
        )

        # H4: also subscribe to kalshi:consensus_decision for audit/monitoring
        # only — no execution actions are triggered from this path.
        try:
            from core.event_bus import event_stream as _es
            await _es.subscribe(
                "kalshi:consensus_decision",
                self._audit_kalshi_consensus,
            )
        except Exception as _sub_exc:
            logger.debug("kalshi consensus audit subscription skipped: %s", _sub_exc)
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Consensus engine started")
        
    async def _audit_kalshi_consensus(self, payload: dict) -> None:
        """H4: Read-only audit handler for Kalshi consensus decisions.

        ConsensusEngine is NOT authoritative for Kalshi — SwarmConsensusAggregator
        owns that domain.  This handler logs divergence between the two systems
        so operators can detect split-brain conditions without acting on them.
        """
        kalshi_dir = payload.get("direction", "").lower()
        kalshi_conf = payload.get("confidence", 0.0)
        asset = payload.get("asset", "?")

        # Check for divergence against the most recent crypto consensus
        for agent_id, vote in list(self.pending_votes.items()):
            if vote.signal in ("bullish", "bearish") and vote.signal != kalshi_dir:
                logger.warning(
                    "H4 divergence detected: ConsensusEngine has '%s' pending votes "
                    "while Kalshi swarm emitted '%s' for %s (kalshi_conf=%.2f). "
                    "No action taken — Kalshi is authoritative for its own domain.",
                    vote.signal, kalshi_dir, asset, kalshi_conf,
                )
                break

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
            # BUG-6 fix: reject votes from sources not on the allowlist
            if self._voter_allowlist and event.source not in self._voter_allowlist:
                logger.warning(
                    "ConsensusEngine: rejected vote from unlisted source '%s' "
                    "(event_type=%s) — add via register_voter() to allow",
                    event.source, event_type,
                )
                return
            vote = self._extract_vote(event)
            if vote:
                vote.timestamp = time.time()
                self.pending_votes[vote.agent_id] = vote
                
    def _extract_vote(self, event: StreamEvent) -> Optional[Vote]:
        """Extract a vote from an agent event."""
        data = event.data
        
        signal = data.get("signal", data.get("direction", ""))
        if not signal:
            return None
        
        confidence = data.get("confidence", 0.5)
        
        # Sprint C: Use Brier-calibrated weight as trust score when available
        trust = self.trust_scores[event.source]
        try:
            from merid.metrics.calibration import get_calibration_store
            cal = get_calibration_store()
            bucket = data.get("category", data.get("bucket", "unknown")).lower()
            brier_weight = cal.get_weight(event.source, bucket)
            # Blend: 70% Brier calibration, 30% existing trust score
            trust = 0.7 * brier_weight + 0.3 * trust
        except Exception as _cal_exc:
            logger.debug("Brier calibration lookup failed for %s: %s", event.source, _cal_exc)
        
        vote = Vote(
            agent_id=event.source,
            proposal=event.event_type,
            signal=signal.lower(),
            confidence=confidence,
            trust=trust
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
        """Handle risk agent veto — attempt negotiation before hard block.

        H7 fix: vetoes are scoped to the proposal/domain indicated in the
        event payload.  Only votes whose ``proposal`` field matches the veto
        target are cleared; unrelated-domain votes are preserved.
        """
        data = event.data
        veto_reason = data.get("reason", "unspecified")
        veto_target = data.get("proposal", data.get("domain", None))
        logger.debug(f"VETO received from {event.source} (target={veto_target}): {veto_reason}")

        # Attempt negotiation before hard-blocking
        try:
            from core.negotiation_protocol import NegotiationSession, NegotiationMediator

            session = NegotiationSession(
                session_id=f"veto-{event.source}-{int(time.time())}",
                initiator=event.source,
                responder="consensus_engine",
                topic=f"risk_veto: {veto_reason}",
                timeout_seconds=10.0,
            )
            mediator = NegotiationMediator()

            # Risk agent proposes constraints; consensus engine counter-proposes
            session.propose(event.source, {
                "action": "block",
                "reason": veto_reason,
                "constraints": data.get("constraints", {}),
            })

            # Auto-resolve via mediator (highest_confidence strategy)
            resolution = mediator.resolve(session)

            if resolution and resolution.get("outcome") == "accepted":
                constraints = resolution.get("constraints") or {}
                if constraints:
                    logger.info(
                        f"Negotiation resolved veto from {event.source} — "
                        f"applying constraints: {constraints}"
                    )
                    # Apply negotiated size constraint: downgrade trust of all
                    # pending votes so the consensus sizing is reduced.
                    size_multiplier = float(constraints.get("size_multiplier", 0.5))
                    size_multiplier = max(0.0, min(size_multiplier, 1.0))
                    for vote in self.pending_votes.values():
                        vote.energy = vote.energy * size_multiplier
                    return
                else:
                    # Negotiation "accepted" but returned no actionable constraints —
                    # treat as a hard veto to stay safe.
                    logger.warning(
                        f"Negotiation from {event.source} returned accepted but no "
                        f"constraints — falling back to hard veto"
                    )
        except (ImportError, Exception) as exc:
            logger.debug(f"Negotiation unavailable or failed: {exc}")

        # Fallback: hard veto — clear only votes for the vetoed proposal/domain
        # H7 fix: preserve votes from unrelated domains
        if veto_target:
            self.pending_votes = {
                agent_id: v
                for agent_id, v in self.pending_votes.items()
                if v.proposal != veto_target
            }
            logger.info(
                f"Hard veto from {event.source}: cleared votes for proposal='{veto_target}'; "
                f"{len(self.pending_votes)} votes from other proposals preserved"
            )
        else:
            # No target specified — fall back to clearing all (legacy behaviour)
            self.pending_votes.clear()
            logger.warning(
                f"Hard veto from {event.source} with no target — cleared all pending votes"
            )
        
    def _handle_challenge(self, event: StreamEvent):
        """Handle skeptic challenge.

        H7 fix: force_reround now extends the collection window by vote_window
        seconds so agents can revise their votes, and logs the re-round event
        in the consensus transparency system.
        """
        data = event.data

        if data.get("force_reround"):
            reasoning = data.get('reasoning', 'skeptic challenge')
            logger.info(f"Re-round requested by {event.source}: {reasoning}")
            # Extend the resolution deadline by one vote_window
            self.last_consensus_time = time.time()
            if self.current_round_id:
                try:
                    self.consensus_logger.record_vote(
                        round_id=self.current_round_id,
                        agent_id=event.source,
                        vote=VoteType.ABSTAIN,
                        reasoning=f"force_reround: {reasoning}",
                        confidence=0.0,
                        trust_weight=self.trust_scores.get(event.source, 1.0),
                    )
                except Exception as _cr_exc:
                    logger.debug("consensus_logger reround record failed: %s", _cr_exc)
            
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

        # H7 fix: drop votes older than vote_window before resolution
        now = time.time()
        self.pending_votes = {
            agent_id: v
            for agent_id, v in self.pending_votes.items()
            if now - v.timestamp <= self.vote_window
        }
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

        # H8 fix: separate abstain votes — they count toward participation
        # denominator but not toward any directional weight.
        abstain_votes = [v for v in votes if v.signal == "abstain"]
        directional_votes = [v for v in votes if v.signal != "abstain"]
        total_voters = len(votes)

        # Abstention rate guard: if > 50% abstain, force NO_ACTION
        if total_voters > 0 and len(abstain_votes) / total_voters > 0.5:
            logger.warning(
                "Abstention rate %.0f%% exceeds 50%% threshold — forcing NO_ACTION (H8)",
                100 * len(abstain_votes) / total_voters,
            )
            result = ConsensusResult(
                decision="NO_ACTION",
                signal="abstain",
                confidence=0.0,
                votes=votes,
                quorum_met=False,
                veto_reason=f"High abstention rate: {len(abstain_votes)}/{total_voters} agents abstained",
            )
            if self.current_round_id:
                self.consensus_logger.complete_round(
                    round_id=self.current_round_id,
                    outcome=ConsensusOutcome.NO_QUORUM,
                    final_confidence=0.0,
                    final_action="NO_ACTION",
                )
                self.current_round_id = None
            return result

        # Calculate weighted votes (neutral counts toward quorum denominator)
        bullish_weight = sum(v.weight for v in directional_votes if v.signal == "bullish")
        bearish_weight = sum(v.weight for v in directional_votes if v.signal == "bearish")
        neutral_weight = sum(v.weight for v in directional_votes if v.signal == "neutral")
        total_weight = bullish_weight + bearish_weight + neutral_weight

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
        
        # Check quorum (denominator includes abstaining voters for safety)
        effective_total = total_weight + sum(v.weight for v in abstain_votes)
        quorum_ratio = signal_weight / effective_total if effective_total > 0 else 0
        quorum_met = quorum_ratio >= self.quorum_threshold
        
        # Calculate confidence (only over directional voters)
        confidence = quorum_ratio * (sum(v.confidence for v in directional_votes) / len(directional_votes)) if directional_votes else 0.0
        
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
                if api.is_frozen(MeridSystem.EXECUTION):
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
            veto_reason=veto_reason,
            authoritative_for="crypto",  # H4: engine only authoritative for crypto
            abstention_count=len(abstain_votes),
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
        """Publish consensus result to event bus.

        H4: execution decisions (EXECUTE_LONG/SHORT) are only published when
        authoritative_for='crypto'.  The Kalshi domain is owned exclusively by
        SwarmConsensusAggregator; this engine must not emit parallel execution
        intents for Kalshi instruments.
        """
        # H4: suppress execution decisions for non-crypto domains
        if result.decision in ("EXECUTE_LONG", "EXECUTE_SHORT") \
                and result.authoritative_for != "crypto":
            logger.warning(
                "H4: suppressing %s decision for non-crypto domain '%s' — "
                "ConsensusEngine is not authoritative for this domain",
                result.decision, result.authoritative_for,
            )
            return

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
                "abstention_count": result.abstention_count,
                "authoritative_for": result.authoritative_for,
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
_consensus_engine_lock = threading.Lock()


def get_consensus_engine() -> ConsensusEngine:
    """Get the singleton consensus engine."""
    global _consensus_engine
    if _consensus_engine is None:
        with _consensus_engine_lock:
            if _consensus_engine is None:
                _consensus_engine = ConsensusEngine()
    return _consensus_engine
