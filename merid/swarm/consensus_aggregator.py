"""
SwarmConsensusAggregator — Consolidates agent proposals into unified consensus.

Aggregates signals from multiple agents into a single consensus view:
- Consensus probability and direction
- Confidence scoring
- Size band recommendations
- Risk layer integration

Output: Consensus decisions feed into MarketMoodBus as InsightObjects.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Deque, List, Optional, Any, Callable
from enum import Enum
import asyncio
from utils.logger import get_logger
from config.trading_constants import DOWNWEIGHT_VOTE_PENALTY

logger = get_logger(__name__)


def _size_band_from_size_preference(size_preference: str) -> str:
    """Map AgentProposal.size_preference to consensus size_band vocabulary."""
    sp = (size_preference or "base").strip().lower()
    if sp in ("small", "base", "reduced", "large", "halted"):
        return sp
    return "base"


def _consensus_from_single_proposal(
    asset: str,
    timeframe: str,
    proposal: AgentProposal,
) -> ConsensusView:
    """READY consensus for one live proposal (AgentGrid: one agent per asset×timeframe).

    Without this, ``len(proposals) < min_agents`` prevents any cache update, so
    ``get_consensus`` returns None and KalshiTradingAgent stalls in the solo
    hold / degraded path even when the cell's strategy has a valid edge.
    """
    now = datetime.now(timezone.utc)
    direction = proposal.direction if proposal.direction in ("yes", "no", "neutral") else "neutral"
    direction_breakdown = {"yes": 0, "no": 0, "neutral": 0}
    direction_breakdown[direction] = direction_breakdown.get(direction, 0) + 1
    size_band = _size_band_from_size_preference(proposal.size_preference)
    return ConsensusView(
        asset=asset,
        timeframe=timeframe,
        timestamp=now,
        status=ConsensusStatus.READY,
        consensus_direction=direction,
        consensus_probability=float(proposal.probability),
        consensus_confidence=float(proposal.confidence),
        total_agents=1,
        voting_agents=1,
        direction_breakdown=dict(direction_breakdown),
        size_band=size_band,
        size_rationale=f"AgentGrid single-operator cell — {proposal.rationale[:160]}",
        confidence_factors=["single_agent_grid_cell"],
        disagreement_flags=[],
        raw_proposals=[proposal],
        usable=True,
    )


def neutral_consensus_view(
    asset: str,
    timeframe: str,
    *,
    reason: str = "no_live_proposals",
) -> ConsensusView:
    """Explicit no-op consensus: zero confidence, not usable for sizing."""
    now = datetime.now(timezone.utc)
    return ConsensusView(
        asset=asset,
        timeframe=timeframe,
        timestamp=now,
        status=ConsensusStatus.STALE,
        consensus_direction="neutral",
        consensus_probability=0.5,
        consensus_confidence=0.0,
        total_agents=0,
        voting_agents=0,
        direction_breakdown={"yes": 0, "no": 0, "neutral": 0},
        size_band="halted",
        size_rationale=f"No trade — {reason}",
        confidence_factors=[],
        disagreement_flags=[reason] if reason else [],
        raw_proposals=[],
        usable=False,
    )


def _get_venue_mode() -> str:
    """Return the current VenueGate trading mode (live/paper/shadow/dry_run).

    Falls back to 'paper' if the gate is unavailable so the payload is always
    a valid string rather than a hardcoded constant.
    """
    try:
        from core.venue_gate import get_venue_gate
        gate = get_venue_gate()
        return str(getattr(gate, "mode", "paper"))
    except Exception:
        return "paper"


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
    market_data: Optional[Dict[str, Any]] = None  # live Kalshi market signals (spread, depth, OI, expiry)
    # BUG-Y fix: carry the matrix downweight flag so the aggregator
    # can apply the intended 50% vote reduction for poor performers.
    downweight: bool = False
    # True when upstream marks social/hashtag input as likely spam — excluded from tally
    suspect: bool = False


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

    # Trace chain correlation ID for end-to-end observability
    correlation_id: Optional[str] = None

    # False when there is no actionable swarm conviction (size allocation should be zero).
    usable: bool = True

    def to_sentiment_context_update(self) -> Dict[str, Any]:
        """Convert to update for SentimentContext."""
        return {
            "swarm_consensus_prob": self.consensus_probability,
            "swarm_consensus_direction": self.consensus_direction,
            "swarm_confidence": self.consensus_confidence,
            "swarm_agents_voting": self.voting_agents,
            "swarm_usable": self.usable,
            "correlation_id": self.correlation_id,
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
    _instance_lock = __import__('threading').Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        min_agents_for_consensus: int = 2,
        max_proposal_age_seconds: float = 300.0,
        consensus_threshold: float = 0.65,  # 65% weighted-vote agreement — raised from 0.60
        # to require stronger directional conviction before firing.
        # Override at runtime via MERID_CONSENSUS_THRESHOLD env var.
    ):
        if self._initialized:
            return

        import os as _os
        _env_thr = _os.getenv("MERID_CONSENSUS_THRESHOLD")
        if _env_thr:
            try:
                consensus_threshold = float(_env_thr)
            except ValueError:
                pass

        self.min_agents = min_agents_for_consensus
        self.max_age = timedelta(seconds=max_proposal_age_seconds)
        self.consensus_threshold = consensus_threshold
        
        # Storage
        self._proposals: Dict[str, List[AgentProposal]] = defaultdict(list)
        # "BTC:15m" -> [proposals]
        self._proposals_lock = threading.Lock()  # guards _proposals mutations

        self._consensus_cache: Dict[str, ConsensusView] = {}
        # "BTC:15m" -> current consensus

        # Rolling log of every READY consensus that was published.  Capped at 200
        # entries so the feed never grows unbounded.  Protected by _proposals_lock
        # (same lock as proposals to avoid a second acquisition in _recompute_consensus).
        self._verdict_log: Deque[ConsensusView] = deque(maxlen=200)

        # Track full Kalshi ticker mapping for better logging
        # asset:timeframe -> full ticker (e.g., "BTC:15m" -> "KXBTC-15M")
        self._ticker_mapping: Dict[str, str] = {}

        self._subscribers: List[Callable[[ConsensusView], None]] = []

        self._initialized = True
        logger.info(f"SwarmConsensusAggregator initialized (min={min_agents_for_consensus})")
    
    def submit_proposal(self, proposal: AgentProposal) -> bool:
        """
        Submit an agent proposal for consensus.
        
        Args:
            proposal: AgentProposal to submit
            
        Returns:
            True if proposal was accepted, False if rejected due to validation errors
        """
        # ── Validate proposal against NormalizedProposal schema ─────────
        try:
            from agents.interface import NormalizedProposal
            
            # Convert AgentProposal to NormalizedProposal for validation
            # Map direction: "yes"/"no"/"neutral" -> recommendation mapping
            direction_to_rec = {
                "yes": "buy",
                "no": "sell", 
                "neutral": "hold"
            }
            direction_to_dir = {
                "yes": "bullish",
                "no": "bearish",
                "neutral": "neutral"
            }
            
            normalized = NormalizedProposal(
                proposal_id=f"{proposal.agent_id}:{proposal.asset}:{proposal.timeframe}:{int(proposal.timestamp.timestamp())}",
                agent_id=proposal.agent_id,
                agent_role=proposal.agent_archetype,
                asset=proposal.asset,
                timeframe=proposal.timeframe,
                kalshi_ticker=f"KX{proposal.asset.upper()}",  # Basic mapping, can be enhanced
                recommendation=direction_to_rec.get(proposal.direction, "abstain"),
                direction=direction_to_dir.get(proposal.direction, "neutral"),
                confidence=proposal.confidence,
                edge=proposal.edge_estimate if proposal.edge_estimate else None,
                timestamp=proposal.timestamp.timestamp(),
                tags=["consensus"],
                evidence={
                    "probability": proposal.probability,
                    "size_preference": proposal.size_preference,
                    "rationale": proposal.rationale
                }
            )
            
            # Validation passed - proceed with processing
        except ValueError as ve:
            # Validation failed - log and reject
            logger.error(
                f"Proposal rejected from {proposal.agent_id}: validation failed: {ve}"
            )
            return False
        except Exception as exc:
            logger.error(
                f"Proposal rejected from {proposal.agent_id}: unexpected validation error: {exc}"
            )
            return False
        
        # ── Process validated proposal ─────────────────────────────────
        key = f"{proposal.asset}:{proposal.timeframe}"

        # Lock the full read-modify-write so concurrent agents for the same cell
        # can't race and inflate vote weight via double-append.
        with self._proposals_lock:
            # Clean old proposals
            now = datetime.now(timezone.utc)
            self._proposals[key] = [
                p for p in self._proposals[key]
                if now - p.timestamp < self.max_age
            ]

            # Deduplicate by agent_id: replace any existing proposal from the same
            # agent rather than appending.  This prevents fast-cycling agents from
            # accumulating N× vote weight within the max_age window.
            self._proposals[key] = [
                p for p in self._proposals[key]
                if p.agent_id != proposal.agent_id
            ]
            self._proposals[key].append(proposal)
        try:
            from merid.prediction.crypto_edge_production import record_proposal_activity

            _tid = self._ticker_mapping.get(key, "")
            _md = proposal.market_data or {}
            record_proposal_activity(key, _md.get("ticker") or _tid)
        except Exception:
            pass

        # Recompute consensus
        self._recompute_consensus(key)
        return True
    
    def _recompute_consensus(self, key: str) -> None:
        """Recompute consensus for an asset/timeframe."""
        raw = self._proposals[key]
        # Strict True only — ``MagicMock.suspect`` is truthy and would drop all votes.
        proposals = [p for p in raw if getattr(p, "suspect", None) is not True]
        n_suspect = len(raw) - len(proposals)
        if n_suspect:
            logger.warning(
                "[consensus] quarantine: dropped %d suspect proposal(s) before recompute for %s",
                n_suspect,
                key,
            )
        if not proposals:
            return

        asset, timeframe = key.split(":", 1)
        single_operator = len(proposals) < self.min_agents
        if single_operator:
            consensus = _consensus_from_single_proposal(asset, timeframe, proposals[-1])
            publish_proposals: List[AgentProposal] = [proposals[-1]]
        else:
            consensus = self._aggregate_proposals(asset, timeframe, proposals)
            publish_proposals = proposals

        # Store pre-publish snapshot for change detection
        old_consensus = self._consensus_cache.get(key)

        # H6 fix: run auction BEFORE updating the cache and publishing so that
        # all downstream consumers (Decision message, event_bus, MarketMoodBus,
        # subscribers) always receive the final post-auction state.
        if (not single_operator) and consensus.status == ConsensusStatus.CONFLICTED:
            try:
                from merid.swarm.auction_consensus import get_auction_resolver
                resolver = get_auction_resolver()
                auction_result = resolver.resolve_conflict(
                    proposals=publish_proposals,
                    asset=asset,
                    timeframe=timeframe,
                )
                if auction_result.resolved:
                    consensus.status = ConsensusStatus.READY
                    consensus.consensus_direction = auction_result.winning_direction
                    consensus.consensus_probability = auction_result.winning_probability
                    consensus.consensus_confidence = auction_result.winning_confidence
                    consensus.confidence_factors.append(
                        f"Auction resolved: {auction_result.reason}"
                    )
                    logger.info(
                        f"Auction resolved conflict for {key}: "
                        f"{auction_result.winning_direction} @ "
                        f"{auction_result.winning_probability:.2f}"
                    )
                else:
                    # No consensus after auction is normal operational state when agents disagree
                    # Log at WARNING not ERROR since this is expected behavior, not a system failure
                    logger.warning(
                        f"Consensus for {key} remains CONFLICTED after auction — "
                        f"no Decision will be published this cycle. "
                        f"Reason: {getattr(auction_result, 'reason', 'unresolved')}"
                    )
            except Exception as exc:
                logger.error(
                    f"Auction resolution failed for {key} (consensus stays CONFLICTED): {exc}"
                )

        # Update cache with the fully-resolved consensus object
        self._consensus_cache[key] = consensus

        # Append every usable READY verdict to the rolling log so
        # /swarm/verdicts can show a historical timeline rather than only
        # the current live snapshot for each (asset, timeframe) cell.
        if consensus.status == ConsensusStatus.READY and consensus.usable:
            with self._proposals_lock:
                self._verdict_log.append(consensus)

        try:
            from merid.prediction.crypto_edge_production import (
                log_consensus_default_leak,
                log_consensus_update_event,
                maybe_emit_consensus_health_warnings,
                record_consensus_refresh,
            )

            record_consensus_refresh(key)
            ticker = self._ticker_mapping.get(key, key)
            log_consensus_update_event(
                market_key=key,
                status=consensus.status.value,
                direction=consensus.consensus_direction,
                probability=float(consensus.consensus_probability),
                confidence=float(consensus.consensus_confidence),
                signal_count=len(publish_proposals),
                ticker=ticker,
            )
            if (
                len(publish_proposals) >= 1
                and consensus.status.value == "ready"
                and consensus.consensus_direction == "neutral"
                and abs(float(consensus.consensus_probability) - 0.5) < 1e-3
            ):
                log_consensus_default_leak(
                    market_key=key,
                    status=consensus.status.value,
                    direction=consensus.consensus_direction,
                    probability=float(consensus.consensus_probability),
                    signal_count=len(publish_proposals),
                )
            maybe_emit_consensus_health_warnings()
        except Exception as _ce:
            logger.debug("consensus production hooks skipped: %s", _ce)

        # NEW: Log with explicit market ID if we have a ticker mapping
        ticker = self._ticker_mapping.get(key, key)
        if consensus.status == ConsensusStatus.READY:
            logger.info(
                f"Consensus READY for {ticker}: "
                f"{consensus.consensus_direction.upper()} @ "
                f"{consensus.consensus_probability:.0%} prob, "
                f"{consensus.consensus_confidence:.0%} conf, "
                f"size={consensus.size_band}"
            )
        elif consensus.status == ConsensusStatus.CONFLICTED:
            _n_vote = getattr(consensus, "voting_agents", None)
            logger.info(
                f"Consensus CONFLICTED for {ticker}: "
                f"disagreement among {_n_vote if _n_vote is not None else '?'} agents, "
                f"will attempt auction resolution"
            )

        # Notify subscribers with the final state
        if self._is_significant_change(old_consensus, consensus):
            for callback in self._subscribers:
                try:
                    result = callback(consensus)
                    if asyncio.iscoroutine(result):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(result)
                        except RuntimeError:
                            result.close()  # No running loop — discard coroutine cleanly
                except Exception as exc:
                    logger.debug(f"Subscriber error: {exc}")

        # Publish to MarketMoodBus (final state)
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

        # Publish typed Decision message when consensus is READY (final state)
        try:
            from merid.swarm.messages import Decision, publish_decision
            if consensus.status == ConsensusStatus.READY:
                import asyncio as _aio
                decision = Decision(
                    decision_id=f"dec-{key}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                    market_id=consensus.asset,
                    action=consensus.consensus_direction,
                    side="yes" if "yes" in consensus.consensus_direction else ("no" if "no" in consensus.consensus_direction else ""),
                    size_contracts=0,  # Sizing determined downstream
                    limit_price_cents=0,
                    p_consensus=consensus.consensus_probability,
                    consensus_confidence=consensus.consensus_confidence,
                    size_band=consensus.size_band,
                    contributing_forecasters=[p.agent_id for p in publish_proposals],
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

        # Fire kalshi:consensus_decision to core.event_bus (final post-auction state)
        if consensus.status in (ConsensusStatus.READY, ConsensusStatus.CONFLICTED):
            try:
                import asyncio as _aio
                from core.event_bus import event_stream as _es
                direction_counts = consensus.direction_breakdown
                _ev = 0.0
                if consensus.raw_proposals:
                    _edge_sum = 0.0
                    _w_sum = 0.0
                    for _rp in consensus.raw_proposals:
                        _e = _rp.edge_estimate if _rp.edge_estimate else 0.0
                        _w = _rp.confidence if _rp.confidence else 0.5
                        _edge_sum += float(_e) * float(_w)
                        _w_sum += float(_w)
                    if _w_sum > 0:
                        _ev = _edge_sum / _w_sum
                payload = {
                    "ticker":              consensus.asset,
                    "asset":               consensus.asset,
                    "timeframe":           consensus.timeframe,
                    "direction":           consensus.consensus_direction.upper(),
                    "consensus_prob":      consensus.consensus_probability,
                    "confidence":          consensus.consensus_confidence,
                    "ev":                  round(_ev, 4),
                    "n_agents":            consensus.voting_agents,
                    "n_yes":               direction_counts.get("yes", 0),
                    "n_no":                direction_counts.get("no", 0),
                    "n_neutral":           direction_counts.get("neutral", 0),
                    "size_band":           consensus.size_band,
                    "size_rationale":      consensus.size_rationale,
                    "confidence_factors":  consensus.confidence_factors,
                    "disagreement_flags":  consensus.disagreement_flags,
                    "auction_resolved":    consensus.status == ConsensusStatus.READY
                                          and any("Auction" in f for f in consensus.confidence_factors),
                    "mode":                _get_venue_mode(),
                }
                try:
                    loop = _aio.get_running_loop()
                    loop.create_task(
                        _es.publish("kalshi:consensus_decision", payload)
                    )
                except RuntimeError:
                    pass  # Not in async context — skip gracefully
            except Exception as exc:
                logger.debug(f"event_bus consensus_decision publish error: {exc}")
    
    def _aggregate_proposals(
        self,
        asset: str,
        timeframe: str,
        proposals: List[AgentProposal],
    ) -> ConsensusView:
        """Aggregate proposals into consensus view."""
        now = datetime.now(timezone.utc)

        n_suspect = sum(1 for p in proposals if getattr(p, "suspect", False))
        proposals = [p for p in proposals if not getattr(p, "suspect", False)]
        if n_suspect:
            logger.warning(
                "[consensus] quarantine: dropped %d suspect proposal(s) for %s:%s",
                n_suspect,
                asset,
                timeframe,
            )

        if not proposals:
            return neutral_consensus_view(
                asset, timeframe, reason="no_proposals_after_quarantine"
            )
        
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
            # _calculate_agent_weight already multiplies by proposal.confidence so
            # the returned weight is track_record_weight × confidence.  Do NOT
            # multiply by p.confidence again here — that would square-weight
            # high-confidence agents and under-represent cautious-but-accurate ones.
            weight = self._calculate_agent_weight(p)

            direction_counts[p.direction] += 1
            direction_weights[p.direction] += weight

            weighted_prob += p.probability * weight
            total_weight += weight

            confidences.append(p.confidence)
            edges.append(p.edge_estimate)
            archetypes.add(p.agent_archetype)
        
        # Determine consensus direction (ties → neutral to avoid ambiguous trades)
        _max_w = max(direction_weights.values()) if direction_weights else 0.0
        _tied = [d for d, w in direction_weights.items() if w == _max_w]
        if len(_tied) > 1:
            winning_dir = "neutral"
            winning_weight = _max_w
        else:
            winning_dir = _tied[0] if _tied else "neutral"
            winning_weight = direction_weights.get(winning_dir, 0.0)
        total_dir_weight = sum(direction_weights.values())
        
        _raw_ratio = winning_weight / total_dir_weight if total_dir_weight > 0 else 0
        # Guard against NaN propagating from upstream weight calculations — NaN comparisons
        # always return False, which would silently mis-classify consensus as "weak agreement".
        agreement_ratio = _raw_ratio if not math.isnan(_raw_ratio) else 0.5
        
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
        # Note: len(proposals) < self.min_agents check is handled by the caller
        # (_recompute_consensus routes to _consensus_from_single_proposal for that case).
        if len(archetypes) < min_archetypes:
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
            usable=True,
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
        except Exception as _brier_exc:
            logger.debug("Brier calibration lookup failed for %s: %s", proposal.agent_id, _brier_exc)

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
            except Exception as _perf_exc:
                logger.debug("Performance tracker lookup failed for %s: %s", proposal.agent_id, _perf_exc)

        if not track:
            # No performance data — use Brier weight only.
            # Still apply downweight so Sharpe-penalised new agents don't
            # escape the penalty just because they lack a track record yet.
            base = brier_weight * proposal.confidence
            if proposal.downweight:
                base *= DOWNWEIGHT_VOTE_PENALTY
            return base

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

        # BUG-Y fix: apply matrix downweight penalty (DOWNWEIGHT_VOTE_PENALTY vote reduction).
        # Agents with sharpe_medium < SHARPE_DOWNWEIGHT_THRESHOLD have
        # downweight=True on their proposal — reduce their voting weight.
        if proposal.downweight:
            base_weight *= DOWNWEIGHT_VOTE_PENALTY

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
        """Get current consensus for asset/timeframe.

        Returns None if all underlying proposals have expired so callers
        never receive a stale consensus built from no-longer-valid data.
        """
        key = f"{asset}:{timeframe}"
        now = datetime.now(timezone.utc)
        live_proposals = [
            p for p in self._proposals.get(key, [])
            if now - p.timestamp < self.max_age
        ]
        if not live_proposals:
            # All proposals expired — return None to signal no current consensus,
            # but keep the cached ConsensusView intact so it remains available
            # as a last-known-good reference until new proposals replace it.
            return None
        cached = self._consensus_cache.get(key)
        if cached is None:
            # e.g. first proposal after process start — submit_proposal already
            # calls _recompute, but this heals any cache miss with live votes.
            self._recompute_consensus(key)
            cached = self._consensus_cache.get(key)
        return cached

    def get_consensus_or_neutral(
        self,
        asset: str,
        timeframe: str,
        *,
        reason: str = "no_live_proposals",
    ) -> ConsensusView:
        """Return live consensus or an explicit neutral, non-usable view for sizing."""
        live = self.get_consensus(asset, timeframe)
        if live is None:
            return neutral_consensus_view(asset, timeframe, reason=reason)
        return live
    
    def get_consensus_by_ticker(self, ticker: str) -> Optional[ConsensusView]:
        """Get current consensus by full Kalshi ticker.
        
        Args:
            ticker: Full Kalshi ticker (e.g., "KXBTC-15M", "KXETH-D1")
            
        Returns:
            ConsensusView if found, None otherwise
        """
        # Look up the asset:timeframe key for this ticker
        for key, mapped_ticker in self._ticker_mapping.items():
            if mapped_ticker.upper() == ticker.upper():
                return self._consensus_cache.get(key)
        
        # Fallback: try to parse from ticker format
        from merid.prediction.market_opinion import parse_kalshi_ticker
        asset, timeframe = parse_kalshi_ticker(ticker)
        return self.get_consensus(asset, timeframe)
    
    def register_ticker_mapping(self, asset: str, timeframe: str, ticker: str) -> None:
        """Register the full Kalshi ticker for an asset:timeframe.
        
        This enables logging with explicit market IDs (e.g., KXBTC-15M)
        instead of internal keys (BTC:15m).
        
        Args:
            asset: Asset code (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, daily, weekly)
            ticker: Full Kalshi ticker (KXBTC-15M, etc.)
        """
        key = f"{asset}:{timeframe}"
        self._ticker_mapping[key] = ticker.upper()
        logger.debug(f"Registered ticker mapping: {key} -> {ticker.upper()}")
    
    def get_all_consensus(self) -> Dict[str, ConsensusView]:
        """Get all current consensus views (one per live asset×timeframe cell)."""
        return dict(self._consensus_cache)

    def get_recent_verdicts(self, limit: int = 20) -> List[ConsensusView]:
        """Return the *limit* most-recent READY verdicts from the rolling log.

        Unlike ``get_all_consensus`` (which returns the *current* state of each
        cell), this returns a historical timeline — one entry each time a READY
        verdict was published.  Newest first.
        """
        with self._proposals_lock:
            items = list(self._verdict_log)
        items.sort(key=lambda cv: cv.timestamp, reverse=True)
        return items[:limit]

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


# ── Singleton ──────────────────────────────────────────────────────────
import threading as _threading

_aggregator: "Optional[SwarmConsensusAggregator]" = None
_aggregator_lock = _threading.Lock()


def get_consensus_aggregator() -> SwarmConsensusAggregator:
    """Return the module-level SwarmConsensusAggregator singleton."""
    global _aggregator
    if _aggregator is None:
        with _aggregator_lock:
            if _aggregator is None:
                _aggregator = SwarmConsensusAggregator()
    return _aggregator
