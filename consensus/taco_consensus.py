"""
TACo-Style Consensus Engine for MERID.

Implements weighted voting/auction over agent opinions to produce
unified trade plans per asset. Agents debate via opinions, then
the consensus coordinator turns that into actionable trade plans.

Based on TradingAgents research and multi-agent consensus patterns.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("consensus.taco")


# ============================================
# ENUMS & TYPES
# ============================================

class AgentRole(str, Enum):
    """Specialized agent roles for trading desk."""
    BULL_ANALYST = "bull_analyst"        # Searches for long opportunities
    BEAR_ANALYST = "bear_analyst"        # Focuses on downside/shorts
    ARBITRAGE_ANALYST = "arbitrage"      # Market inefficiencies
    SENTIMENT_ANALYST = "sentiment"      # Social/news sentiment
    TECHNICAL_ANALYST = "technical"      # Chart patterns, indicators
    FUNDAMENTAL_ANALYST = "fundamental"  # On-chain, fundamentals
    RISK_MANAGER = "risk_manager"        # Enforces limits, can veto
    TRADER = "trader"                    # Executes approved plans
    COORDINATOR = "coordinator"          # Produces consensus


class Stance(str, Enum):
    """Agent stance on an asset."""
    STRONG_BULL = "strong_bull"    # Score > 0.7
    BULL = "bull"                  # Score 0.3 to 0.7
    NEUTRAL = "neutral"           # Score -0.3 to 0.3
    BEAR = "bear"                 # Score -0.7 to -0.3
    STRONG_BEAR = "strong_bear"   # Score < -0.7


class TradeDirection(str, Enum):
    """Consensus trade direction."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    REDUCE = "reduce"


class PlanStatus(str, Enum):
    """Trade plan status."""
    PENDING = "pending"
    APPROVED = "approved"
    VETOED = "vetoed"
    EXECUTING = "executing"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


# ============================================
# DATA SCHEMAS
# ============================================

@dataclass
class AgentOpinion:
    """
    Opinion from an agent on an asset.
    Published to agent.opinions topic.
    """
    opinion_id: str
    agent_id: str
    role: str
    symbol: str
    venue: str
    
    # Core opinion
    stance: str              # Stance enum value
    score: float            # -1.0 to 1.0
    confidence: float       # 0.0 to 1.0
    
    # Context
    rationale: str          # Brief explanation
    horizon: str = "short"  # short (< 1hr), medium (1hr-1d), long (> 1d)
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    data_sources: List[str] = field(default_factory=list)
    supporting_data: Dict[str, Any] = field(default_factory=dict)
    
    # Signal layer: decay metadata (§7 integration)
    signal_snapshot_id: str = ""           # ID of the SignalSnapshot that drove this opinion
    signal_freshness: float = 1.0          # avg decay weight of driving signals (0-1)
    signal_stale_count: int = 0            # number of stale signals in snapshot
    decay_metadata: Dict[str, Any] = field(default_factory=dict)  # domain→decay_weight
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentOpinion":
        # Handle optional new fields for backward compat
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class TradePlan:
    """
    Consensus trade plan for an asset.
    Published to agent.trade_plans topic.
    """
    plan_id: str
    symbol: str
    venue: str
    
    # Direction and sizing
    direction: str          # TradeDirection value
    target_size_usd: float
    confidence: float       # 0.0 to 1.0
    
    # Consensus details
    consensus_score: float  # Aggregated weighted score
    supporting_agents: List[str]
    opposing_agents: List[str]
    
    # Execution preferences
    entry_preference: str = "market"  # market, limit, twap
    urgency: str = "normal"           # low, normal, high, urgent
    max_slippage_bps: float = 50.0
    
    # Risk adjustments
    approved_size_usd: Optional[float] = None  # After risk review
    risk_adjustment_reason: Optional[str] = None
    
    # Status
    status: str = PlanStatus.PENDING.value
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    horizon: str = "short"
    ttl_seconds: float = 300.0  # Plan expires after 5 minutes
    
    # Signal layer: decay metadata (§7 integration)
    signal_snapshot_id: str = ""           # ID of the driving SignalSnapshot
    avg_signal_freshness: float = 1.0      # avg decay weight across all opinions' signals
    decay_adjusted_confidence: float = 0.0 # confidence * avg_signal_freshness
    signal_summary: Dict[str, Any] = field(default_factory=dict)  # aggregated signal info
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradePlan":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
    
    def is_expired(self) -> bool:
        return time.time() > (self.timestamp + self.ttl_seconds)


@dataclass 
class TradeExecution:
    """
    Executed trade record.
    Published to trades.executed topic.
    """
    execution_id: str
    plan_id: str
    order_id: str
    
    symbol: str
    venue: str
    side: str
    size_usd: float
    fill_price: float
    
    # Traceability
    triggered_by_opinions: List[str]  # Opinion IDs
    consensus_score: float
    
    # Execution details
    slippage_bps: float
    fees_usd: float
    
    # Mode
    is_simulated: bool = True
    execution_mode: str = "paper"
    
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================
# AGENT RELIABILITY WEIGHTS
# ============================================

@dataclass
class AgentReliability:
    """Track agent reliability for weighted consensus."""
    agent_id: str
    role: str
    
    # Performance metrics
    total_opinions: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.5
    
    # Risk-adjusted metrics
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    
    # Derived weight
    weight: float = 1.0
    
    def update_weight(self):
        """Recalculate weight based on metrics."""
        # Base weight from accuracy
        accuracy_factor = max(0.1, self.accuracy)
        
        # Sharpe bonus (capped)
        sharpe_factor = 1.0 + min(0.5, max(0, self.sharpe_ratio) * 0.1)
        
        # Drawdown penalty
        dd_factor = 1.0 - min(0.5, self.max_drawdown)
        
        self.weight = accuracy_factor * sharpe_factor * dd_factor


# ============================================
# CONSENSUS COORDINATOR
# ============================================

class TaCoConsensusCoordinator:
    """
    TACo-style consensus coordinator.
    
    Collects opinions from agents, applies weighted voting,
    and produces unified trade plans per asset.
    """
    
    _instance: Optional["TaCoConsensusCoordinator"] = None
    
    def __init__(
        self,
        opinion_window_seconds: float = 60.0,
        min_opinions_for_consensus: int = 2,
        bull_threshold: float = 0.3,
        bear_threshold: float = -0.3,
        strong_threshold: float = 0.6,
    ):
        self.opinion_window_seconds = opinion_window_seconds
        self.min_opinions = min_opinions_for_consensus
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold
        self.strong_threshold = strong_threshold
        
        # State
        self._opinions: Dict[str, List[AgentOpinion]] = defaultdict(list)  # symbol -> opinions
        self._active_plans: Dict[str, TradePlan] = {}  # plan_id -> plan
        self._agent_weights: Dict[str, AgentReliability] = {}
        self._subscribers: Set[Callable] = set()
        self._lock = asyncio.Lock()
        
        # Metrics
        self._total_opinions = 0
        self._total_plans = 0
        self._consensus_cycles = 0
        
        logger.info("TaCoConsensusCoordinator initialized")
    
    @classmethod
    def get_instance(cls) -> "TaCoConsensusCoordinator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ============================================
    # OPINION HANDLING
    # ============================================
    
    async def submit_opinion(self, opinion: AgentOpinion) -> None:
        """Submit an agent opinion for consensus consideration."""
        async with self._lock:
            # Store opinion
            self._opinions[opinion.symbol].append(opinion)
            self._total_opinions += 1
            
            # Prune old opinions
            cutoff = time.time() - self.opinion_window_seconds
            self._opinions[opinion.symbol] = [
                o for o in self._opinions[opinion.symbol]
                if o.timestamp >= cutoff
            ]
            
            logger.info(
                f"Opinion received: {opinion.agent_id} -> {opinion.symbol} "
                f"({opinion.stance}, score={opinion.score:.2f})"
            )
            
            # Notify subscribers
            await self._notify_opinion(opinion)
            
            # Check if we should run consensus
            if len(self._opinions[opinion.symbol]) >= self.min_opinions:
                await self._run_consensus_cycle(opinion.symbol)
    
    async def _notify_opinion(self, opinion: AgentOpinion) -> None:
        """Notify subscribers of new opinion."""
        for callback in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("opinion", opinion.to_dict())
                else:
                    callback("opinion", opinion.to_dict())
            except Exception as e:
                logger.error(f"Opinion notification failed: {e}")
    
    # ============================================
    # CONSENSUS LOGIC
    # ============================================
    
    async def _run_consensus_cycle(self, symbol: str) -> Optional[TradePlan]:
        """
        Run TACo-style consensus for a symbol.
        Weighted voting over recent opinions.
        """
        opinions = self._opinions.get(symbol, [])
        if len(opinions) < self.min_opinions:
            return None
        
        self._consensus_cycles += 1
        
        # Get agent weights
        weighted_scores = []
        supporting = []
        opposing = []
        
        freshness_vals = []
        for opinion in opinions:
            weight = self._get_agent_weight(opinion.agent_id)
            # §7: decay-aware consensus — scale by signal freshness
            freshness = getattr(opinion, "signal_freshness", 1.0)
            freshness_vals.append(freshness)
            weighted_score = opinion.score * weight * opinion.confidence * freshness
            weighted_scores.append(weighted_score)
            
            if opinion.score > 0:
                supporting.append(opinion.agent_id)
            elif opinion.score < 0:
                opposing.append(opinion.agent_id)
        
        # Calculate consensus score
        if not weighted_scores:
            return None
        
        avg_signal_freshness = sum(freshness_vals) / max(len(freshness_vals), 1)
        total_weight = sum(abs(w) for w in weighted_scores)
        consensus_score = sum(weighted_scores) / max(1, len(weighted_scores))
        
        # Determine direction
        if consensus_score >= self.strong_threshold:
            direction = TradeDirection.LONG
            confidence = min(1.0, abs(consensus_score))
        elif consensus_score >= self.bull_threshold:
            direction = TradeDirection.LONG
            confidence = 0.5 + (consensus_score - self.bull_threshold) / (self.strong_threshold - self.bull_threshold) * 0.3
        elif consensus_score <= -self.strong_threshold:
            direction = TradeDirection.SHORT
            confidence = min(1.0, abs(consensus_score))
        elif consensus_score <= self.bear_threshold:
            direction = TradeDirection.SHORT
            confidence = 0.5 + (abs(consensus_score) - abs(self.bear_threshold)) / (self.strong_threshold - abs(self.bear_threshold)) * 0.3
        else:
            direction = TradeDirection.FLAT
            confidence = 0.3
        
        # Calculate target size based on confidence
        base_size = 1000.0  # Base position size USD
        target_size = base_size * confidence
        
        # §7: decay-adjusted confidence = confidence * avg freshness
        decay_adjusted_conf = confidence * avg_signal_freshness
        
        # Create trade plan
        plan = TradePlan(
            plan_id=f"plan_{uuid.uuid4().hex[:12]}",
            symbol=symbol,
            venue=opinions[0].venue if opinions else "paper",
            direction=direction.value,
            target_size_usd=target_size,
            confidence=confidence,
            consensus_score=consensus_score,
            supporting_agents=supporting,
            opposing_agents=opposing,
            horizon=opinions[0].horizon if opinions else "short",
            avg_signal_freshness=avg_signal_freshness,
            decay_adjusted_confidence=decay_adjusted_conf,
        )
        
        self._active_plans[plan.plan_id] = plan
        self._total_plans += 1
        
        logger.info(
            f"Consensus reached: {symbol} -> {direction.value} "
            f"(score={consensus_score:.2f}, confidence={confidence:.2f}, "
            f"supporters={len(supporting)}, opposers={len(opposing)})"
        )
        
        # Notify subscribers
        await self._notify_plan(plan)
        
        return plan
    
    async def _notify_plan(self, plan: TradePlan) -> None:
        """Notify subscribers of new trade plan."""
        for callback in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("trade_plan", plan.to_dict())
                else:
                    callback("trade_plan", plan.to_dict())
            except Exception as e:
                logger.error(f"Plan notification failed: {e}")
    
    def _get_agent_weight(self, agent_id: str) -> float:
        """Get reliability weight for an agent based on performance metrics."""
        # First check local reliability weights
        if agent_id in self._agent_weights:
            return self._agent_weights[agent_id].weight
        
        # Try to get weight from risk metrics tracker
        try:
            from risk import get_agent_metrics_tracker
            tracker = get_agent_metrics_tracker()
            agent = tracker.get_agent(agent_id)
            if agent:
                return agent.consensus_weight
        except Exception:
            pass
        
        # Default weight based on role inference
        if "risk" in agent_id.lower():
            return 1.5  # Risk manager gets higher weight
        if "bull" in agent_id.lower() or "bear" in agent_id.lower():
            return 1.0
        return 1.0
    
    # ============================================
    # RISK REVIEW
    # ============================================
    
    async def risk_review_plan(
        self,
        plan_id: str,
        approved: bool,
        approved_size: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> Optional[TradePlan]:
        """Risk manager reviews and potentially adjusts a plan."""
        async with self._lock:
            plan = self._active_plans.get(plan_id)
            if not plan:
                return None
            
            if approved:
                plan.status = PlanStatus.APPROVED.value
                plan.approved_size_usd = approved_size or plan.target_size_usd
                plan.risk_adjustment_reason = reason
                logger.info(f"Plan {plan_id} approved (size={plan.approved_size_usd})")
            else:
                plan.status = PlanStatus.VETOED.value
                plan.risk_adjustment_reason = reason
                logger.info(f"Plan {plan_id} vetoed: {reason}")
            
            await self._notify_plan(plan)
            return plan
    
    # ============================================
    # SUBSCRIPTIONS
    # ============================================
    
    def subscribe(self, callback: Callable) -> Callable[[], None]:
        """Subscribe to consensus events (opinions, plans)."""
        self._subscribers.add(callback)
        return lambda: self._subscribers.discard(callback)
    
    # ============================================
    # STATE & METRICS
    # ============================================
    
    def get_recent_opinions(self, symbol: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Get recent opinions."""
        if symbol:
            opinions = self._opinions.get(symbol, [])
        else:
            opinions = []
            for sym_opinions in self._opinions.values():
                opinions.extend(sym_opinions)
        
        opinions.sort(key=lambda o: o.timestamp, reverse=True)
        return [o.to_dict() for o in opinions[:limit]]
    
    def get_active_plans(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get active trade plans."""
        plans = list(self._active_plans.values())
        
        # Filter expired
        plans = [p for p in plans if not p.is_expired()]
        
        if symbol:
            plans = [p for p in plans if p.symbol == symbol]
        
        return [p.to_dict() for p in plans]
    
    def get_consensus_status(self, symbol: str) -> Dict[str, Any]:
        """Get current consensus status for a symbol."""
        opinions = self._opinions.get(symbol, [])
        
        if not opinions:
            return {
                "symbol": symbol,
                "has_consensus": False,
                "opinion_count": 0,
                "consensus_score": 0,
                "direction": "flat",
                "confidence": 0,
            }
        
        # Calculate current consensus
        scores = [o.score * o.confidence for o in opinions]
        consensus_score = sum(scores) / len(scores) if scores else 0
        
        if consensus_score >= self.bull_threshold:
            direction = "long"
        elif consensus_score <= self.bear_threshold:
            direction = "short"
        else:
            direction = "flat"
        
        return {
            "symbol": symbol,
            "has_consensus": len(opinions) >= self.min_opinions,
            "opinion_count": len(opinions),
            "consensus_score": consensus_score,
            "direction": direction,
            "confidence": abs(consensus_score),
            "supporting_agents": [o.agent_id for o in opinions if o.score > 0],
            "opposing_agents": [o.agent_id for o in opinions if o.score < 0],
            "last_update": max(o.timestamp for o in opinions) if opinions else 0,
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get coordinator metrics."""
        return {
            "total_opinions": self._total_opinions,
            "total_plans": self._total_plans,
            "consensus_cycles": self._consensus_cycles,
            "active_plans": len(self._active_plans),
            "tracked_symbols": list(self._opinions.keys()),
            "agent_count": len(self._agent_weights),
        }


def get_consensus_coordinator() -> TaCoConsensusCoordinator:
    """Get the singleton consensus coordinator."""
    return TaCoConsensusCoordinator.get_instance()


# ============================================
# HELPER: Create opinion from agent result
# ============================================

def create_opinion_from_vote(
    agent_id: str,
    role: str,
    symbol: str,
    vote: str,
    confidence: float,
    reasoning: str,
    venue: str = "paper",
) -> AgentOpinion:
    """Convert agent vote to structured opinion."""
    # Map vote to stance and score
    vote_lower = vote.lower()
    
    if "strong" in vote_lower and "bull" in vote_lower:
        stance = Stance.STRONG_BULL.value
        score = 0.9
    elif "bull" in vote_lower or "long" in vote_lower or "buy" in vote_lower:
        stance = Stance.BULL.value
        score = 0.6
    elif "strong" in vote_lower and "bear" in vote_lower:
        stance = Stance.STRONG_BEAR.value
        score = -0.9
    elif "bear" in vote_lower or "short" in vote_lower or "sell" in vote_lower:
        stance = Stance.BEAR.value
        score = -0.6
    else:
        stance = Stance.NEUTRAL.value
        score = 0.0
    
    # Adjust score by confidence
    score = score * confidence
    
    return AgentOpinion(
        opinion_id=f"op_{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        role=role,
        symbol=symbol,
        venue=venue,
        stance=stance,
        score=score,
        confidence=confidence,
        rationale=reasoning[:500] if reasoning else "",
    )
