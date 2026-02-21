"""
SwarmConsensusAggregator — Consolidates agent proposals into unified consensus.

Aggregates signals from multiple agents into a single consensus view:
- Consensus probability and direction
- Confidence scoring
- Size band recommendations
- Risk layer integration

Output: Consensus decisions feed into MarketMoodBus as InsightObjects.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class ConsensusStatus(Enum):
    """Status of consensus formation."""
    FORMING = "forming"      # Gathering votes
    READY = "ready"          # Consensus achieved
    CONFLICTED = "conflicted"  # High disagreement
    STALE = "stale"          # Data too old


@dataclass
class AgentProposal:
    """Individual agent proposal for consensus."""
    agent_id: str
    asset: str
    timeframe: str
    direction: str  # "yes", "no", "neutral"
    probability: float  # 0-1
    confidence: float  # 0-1
    size_preference: str  # "small", "base", "large"
    rationale: str
    edge_estimate: float  # Expected edge in cents
    timestamp: datetime
    
    # Agent metadata
    agent_archetype: str  # "trend", "mean_reversion", "momentum", etc.
    agent_track_record: Optional[Dict[str, float]] = None  # win_rate, sharpe, etc.


@dataclass
class ConsensusView:
    """Aggregated consensus from multiple agents."""
    asset: str
    timeframe: str
    timestamp: datetime
    
    # Consensus metrics
    status: ConsensusStatus
    consensus_direction: str  # "yes", "no", "neutral"
    consensus_probability: float  # 0-1 weighted average
    consensus_confidence: float  # 0-1
    
    # Agent participation
    total_agents: int
    voting_agents: int
    direction_breakdown: Dict[str, int]  # {"yes": 3, "no": 1, "neutral": 2}
    
    # Size recommendation
    size_band: str  # "small", "base", "reduced", "halted"
    size_rationale: str
    
    # Confidence factors
    confidence_factors: List[str]  # Why we are/aren't confident
    disagreement_flags: List[str]  # Sources of disagreement
    
    # Raw data for audit
    raw_proposals: List[AgentProposal]
    
    def to_sentiment_context_update(self) -> Dict[str, Any]:
        """Convert to update for SentimentContext."""
        return {
            "swarm_consensus_prob": self.consensus_probability,
            "swarm_consensus_direction": self.consensus_direction,
            "swarm_confidence": self.consensus_confidence,
            "swarm_agents_voting": self.voting_agents,
        }
    
    def to_insight_object(
        self,
        context: "SentimentContext",  # type: ignore
        insight_id: str,
    ) -> "InsightObject":  # type: ignore
        """Convert to InsightObject for UI/socials."""
        from merid.swarm.market_mood_bus import InsightObject
        
        # Build headline
        dir_emoji = "📈" if self.consensus_direction == "yes" else "📉" if self.consensus_direction == "no" else "➡️"
        headline = f"{dir_emoji} Swarm consensus: {self.consensus_direction.upper()} @ {self.consensus_probability:.0%} confidence"
        
        # Build rationale
        rationale_parts = [
            f"{self.voting_agents} agents voted with {self.consensus_confidence:.0%} alignment.",
            f"Direction breakdown: {self.direction_breakdown}.",
            f"Size recommendation: {self.size_band} ({self.size_rationale}).",
        ]
        
        # Build key factors
        factors = list(self.confidence_factors)
        if self.disagreement_flags:
            factors.append(f"Caution: {', '.join(self.disagreement_flags)}")
        
        return InsightObject(
            insight_id=insight_id,
            timestamp=datetime.now(timezone.utc),
            asset=self.asset,
            timeframe=self.timeframe,
            swarm_direction=self.consensus_direction,
            swarm_probability=self.consensus_probability,
            swarm_confidence=self.consensus_confidence,
            swarm_size_band=self.size_band,
            context=context,
            signal_type="consensus",
            edge_source="swarm_aggregation",
            headline=headline,
            rationale=" ".join(rationale_parts),
            key_factors=factors,
            risk_checks_passed=[],
            risk_adjustments={},
            final_mode="pending",  # Set by risk layer
        )


class SwarmConsensusAggregator:
    """
    Aggregates agent proposals into unified consensus decisions.
    
    Handles:
    - Weighted voting by agent track record
    - Confidence calculation
    - Disagreement detection
    - Size band recommendation
    - Integration with MarketMoodBus
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        min_agents_for_consensus: int = 2,
        max_proposal_age_seconds: float = 300.0,
        consensus_threshold: float = 0.6,  # 60% agreement
    ):
        if self._initialized:
            return
        
        self.min_agents = min_agents_for_consensus
        self.max_age = timedelta(seconds=max_proposal_age_seconds)
        self.consensus_threshold = consensus_threshold
        
        # Storage
        self._proposals: Dict[str, List[AgentProposal]] = defaultdict(list)
        # "BTC:15m" -> [proposals]
        
        self._consensus_cache: Dict[str, ConsensusView] = {}
        # "BTC:15m" -> current consensus
        
        self._subscribers: List[Callable[[ConsensusView], None]] = []
        
        self._initialized = True
        logger.info(f"SwarmConsensusAggregator initialized (min={min_agents_for_consensus})")
    
    def submit_proposal(self, proposal: AgentProposal) -> None:
        """Submit an agent proposal for consensus."""
        key = f"{proposal.asset}:{proposal.timeframe}"
        
        # Clean old proposals
        now = datetime.now(timezone.utc)
        self._proposals[key] = [
            p for p in self._proposals[key]
            if now - p.timestamp < self.max_age
        ]
        
        # Add new proposal
        self._proposals[key].append(proposal)
        
        # Recompute consensus
        self._recompute_consensus(key)
    
    def _recompute_consensus(self, key: str) -> None:
        """Recompute consensus for an asset/timeframe."""
        proposals = self._proposals[key]
        if len(proposals) < self.min_agents:
            return
        
        asset, timeframe = key.split(":")
        consensus = self._aggregate_proposals(asset, timeframe, proposals)
        
        # Update cache
        old_consensus = self._consensus_cache.get(key)
        self._consensus_cache[key] = consensus
        
        # Notify if significant change
        if self._is_significant_change(old_consensus, consensus):
            for callback in self._subscribers:
                try:
                    callback(consensus)
                except Exception as exc:
                    logger.debug(f"Subscriber error: {exc}")
        
        # Publish to MarketMoodBus
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            context = bus.get_context(asset, timeframe)
            if context:
                insight = consensus.to_insight_object(
                    context,
                    insight_id=f"consensus-{key}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                )
                bus.publish_insight(insight)
        except Exception as exc:
            logger.debug(f"MarketMoodBus publish error: {exc}")

        # Sprint H: Publish typed Decision message when consensus is READY
        try:
            from merid.swarm.messages import Decision, publish_decision
            from merid.swarm.consensus_aggregator import ConsensusStatus as _CS
            if consensus.status == _CS.READY:
                import asyncio as _aio
                decision = Decision(
                    decision_id=f"dec-{key}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                    market_id=consensus.asset,
                    action=consensus.consensus_direction,
                    side="yes" if "yes" in consensus.consensus_direction else "no",
                    size_contracts=0,  # Sizing determined downstream
                    limit_price_cents=0,
                    p_consensus=consensus.consensus_probability,
                    consensus_confidence=consensus.consensus_confidence,
                    size_band=consensus.size_band,
                    contributing_forecasters=[p.agent_id for p in proposals],
                    risk_approved=False,  # Risk agent approves separately
                    rationale="; ".join(consensus.confidence_factors),
                )
                try:
                    loop = _aio.get_running_loop()
                    loop.create_task(publish_decision(decision))
                except RuntimeError:
                    pass  # No running event loop
        except Exception as exc:
            logger.debug(f"Decision publish error: {exc}")
    
    def _aggregate_proposals(
        self,
        asset: str,
        timeframe: str,
        proposals: List[AgentProposal],
    ) -> ConsensusView:
        """Aggregate proposals into consensus view."""
        now = datetime.now(timezone.utc)
        
        # Direction counts
        direction_counts = defaultdict(int)
        direction_weights = defaultdict(float)
        
        # Weighted probability calculation
        total_weight = 0.0
        weighted_prob = 0.0
        
        # Track confidence and disagreement
        confidences = []
        edges = []
        archetypes = set()
        
        for p in proposals:
            # Calculate weight based on track record
            weight = self._calculate_agent_weight(p)
            
            direction_counts[p.direction] += 1
            direction_weights[p.direction] += weight
            
            weighted_prob += p.probability * weight * p.confidence
            total_weight += weight * p.confidence
            
            confidences.append(p.confidence)
            edges.append(p.edge_estimate)
            archetypes.add(p.agent_archetype)
        
        # Determine consensus direction
        winning_dir = max(direction_weights.keys(), key=lambda d: direction_weights[d])
        winning_weight = direction_weights[winning_dir]
        total_dir_weight = sum(direction_weights.values())
        
        agreement_ratio = winning_weight / total_dir_weight if total_dir_weight > 0 else 0
        
        # Calculate consensus probability
        consensus_prob = weighted_prob / total_weight if total_weight > 0 else 0.5
        
        # Calculate overall confidence
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        confidence_factors = []
        disagreement_flags = []
        
        # Confidence based on agreement
        if agreement_ratio >= 0.8:
            consensus_confidence = avg_confidence * 1.0
            confidence_factors.append(f"Strong agreement ({agreement_ratio:.0%})")
        elif agreement_ratio >= 0.6:
            consensus_confidence = avg_confidence * 0.8
            confidence_factors.append(f"Moderate agreement ({agreement_ratio:.0%})")
        else:
            consensus_confidence = avg_confidence * 0.5
            disagreement_flags.append(f"Weak agreement ({agreement_ratio:.0%})")
        
        # Adjust for archetype diversity
        if len(archetypes) >= 3:
            confidence_factors.append("Diverse agent perspectives")
        elif len(archetypes) == 1:
            disagreement_flags.append("Single archetype bias")
        
        # Sprint D: Minimum diversity requirement
        min_archetypes = 2
        if len(archetypes) < min_archetypes and len(proposals) >= self.min_agents:
            disagreement_flags.append(
                f"Insufficient diversity: {len(archetypes)} archetype(s), need {min_archetypes}+"
            )
            consensus_confidence *= 0.6  # Penalize low-diversity consensus

        # Determine status
        if len(proposals) < self.min_agents:
            status = ConsensusStatus.FORMING
        elif len(archetypes) < min_archetypes:
            status = ConsensusStatus.FORMING  # Block consensus without diversity
        elif agreement_ratio < self.consensus_threshold:
            status = ConsensusStatus.CONFLICTED
        else:
            status = ConsensusStatus.READY
        
        # Size band recommendation
        size_band = self._calculate_size_band(
            consensus_confidence,
            agreement_ratio,
            edges,
        )
        
        return ConsensusView(
            asset=asset,
            timeframe=timeframe,
            timestamp=now,
            status=status,
            consensus_direction=winning_dir,
            consensus_probability=consensus_prob,
            consensus_confidence=consensus_confidence,
            total_agents=len(set(p.agent_id for p in proposals)),
            voting_agents=len(proposals),
            direction_breakdown=dict(direction_counts),
            size_band=size_band,
            size_rationale=self._size_rationale(size_band, consensus_confidence, edges),
            confidence_factors=confidence_factors,
            disagreement_flags=disagreement_flags,
            raw_proposals=proposals.copy(),
        )
    
    def _calculate_agent_weight(self, proposal: AgentProposal) -> float:
        """Calculate voting weight based on agent track record + Brier calibration.

        Priority order:
        1. Brier calibration weight from CalibrationStore (Sprint C — primary).
        2. Inline ``agent_track_record`` on the proposal (fast path).
        3. Live metrics from ``AgentPerformanceTracker`` (authoritative).
        4. Neutral base weight of 1.0 (no data yet).

        Factors used:
        - brier_weight      → from CalibrationStore (inversely proportional to Brier score)
        - win_rate           → scaled 0.5–1.0
        - sharpe_ratio       → capped at 2.0, scaled 0–1.0
        - avg_realized_edge  → bonus when positive
        """
        # ── Sprint C: Brier calibration weight (primary signal) ──────────
        brier_weight = 1.0
        try:
            from merid.metrics.calibration import get_calibration_store
            cal = get_calibration_store()
            bucket = (proposal.asset or "unknown").lower()
            brier_weight = cal.get_weight(proposal.agent_id, bucket)
        except Exception:
            pass

        track = proposal.agent_track_record or {}

        # Pull live metrics from the performance tracker if available
        if not track:
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                live = tracker.get_agent_metrics(proposal.agent_id)
                if live.total_closes >= 5:  # Require minimum sample
                    track = {
                        "win_rate": live.win_rate,
                        "sharpe_ratio": live.sharpe_ratio,
                        "avg_realized_edge": live.avg_realized_edge,
                        "total_closes": live.total_closes,
                    }
            except Exception:
                pass

        if not track:
            # No performance data — use Brier weight only
            return brier_weight * proposal.confidence

        win_rate = float(track.get("win_rate", 0.5))
        sharpe = float(track.get("sharpe_ratio", 1.0))
        avg_realized_edge = float(track.get("avg_realized_edge", 0.0))

        # Win rate: scale 0.5–1.0 (below 0.5 is below chance)
        win_weight = 0.5 + (max(0.0, min(1.0, win_rate)) * 0.5)

        # Sharpe: cap at 2.0, scale 0–1.0
        sharpe_weight = min(max(sharpe, 0.0), 2.0) / 2.0

        # Edge bonus: positive realized edge adds up to 10% boost
        edge_bonus = min(avg_realized_edge / 10.0, 0.1)

        # Combine: Brier calibration weight modulates the performance-based weight
        performance_weight = ((win_weight + sharpe_weight) / 2) + edge_bonus
        base_weight = performance_weight * brier_weight

        # Boost for high confidence proposals
        return base_weight * proposal.confidence
    
    def _calculate_size_band(
        self,
        confidence: float,
        agreement: float,
        edges: List[float],
    ) -> str:
        """Calculate recommended size band.

        Mapping (tightest → loosest):
          small   — low confidence or weak agreement (high uncertainty)
          reduced — borderline confidence/agreement (proceed cautiously)
          base    — moderate confidence, normal sizing
          large   — high confidence + strong agreement + positive edge
        """
        avg_edge = sum(edges) / len(edges) if edges else 0.0

        if confidence < 0.3 or agreement < 0.5:
            return "small"
        elif confidence < 0.5 or agreement < 0.6:
            return "reduced"
        elif confidence >= 0.8 and agreement >= 0.8 and avg_edge >= 3.0:
            return "large"
        else:
            return "base"
    
    def _size_rationale(
        self,
        size_band: str,
        confidence: float,
        edges: List[float],
    ) -> str:
        """Generate rationale for size band."""
        parts = []
        
        if size_band == "small":
            parts.append("Low confidence or disagreement suggests minimal exposure")
        elif size_band == "base":
            parts.append("Standard sizing appropriate for conditions")
        elif size_band == "reduced":
            parts.append("Higher confidence but need to manage risk")
        
        avg_edge = sum(edges) / len(edges) if edges else 0
        parts.append(f"Avg edge {avg_edge:.1f}¢")
        
        return ", ".join(parts)
    
    def _is_significant_change(
        self,
        old: Optional[ConsensusView],
        new: ConsensusView,
    ) -> bool:
        """Check if consensus change is significant enough to notify."""
        if old is None:
            return True
        
        # Direction flip
        if old.consensus_direction != new.consensus_direction:
            return True
        
        # Probability shift > 10%
        if abs(old.consensus_probability - new.consensus_probability) > 0.1:
            return True
        
        # Confidence shift > 20%
        if abs(old.consensus_confidence - new.consensus_confidence) > 0.2:
            return True
        
        return False
    
    # === Public API ===
    
    def get_consensus(
        self,
        asset: str,
        timeframe: str,
    ) -> Optional[ConsensusView]:
        """Get current consensus for asset/timeframe."""
        return self._consensus_cache.get(f"{asset}:{timeframe}")
    
    def get_all_consensus(self) -> Dict[str, ConsensusView]:
        """Get all current consensus views."""
        return dict(self._consensus_cache)
    
    def subscribe(self, callback: Callable[[ConsensusView], None]):
        """Subscribe to consensus updates."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[ConsensusView], None]):
        """Unsubscribe from consensus updates."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def clear_proposals(self, asset: Optional[str] = None):
        """Clear old proposals."""
        if asset:
            for key in list(self._proposals.keys()):
                if key.startswith(f"{asset}:"):
                    self._proposals[key].clear()
        else:
            self._proposals.clear()


# Singleton accessor
def get_consensus_aggregator() -> SwarmConsensusAggregator:
    """Get the singleton SwarmConsensusAggregator instance."""
    return SwarmConsensusAggregator()
