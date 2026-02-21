"""
Explicit Event Schemas for Swarm Communication

Defines the contract for opinion → consensus → trade flow.
All events are serializable, versionable, and include state tracking.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class OpinionDirection(Enum):
    """Direction of a strategy opinion."""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    REDUCE = "reduce"
    CLOSE = "close"


class TradingMode(Enum):
    """Trading execution mode."""
    SIMULATION = "simulation"  # Local sim engine, no external calls
    PAPER = "paper"            # Broker paper API
    LIVE = "live"              # Real money (requires special authorization)


@dataclass
class StrategyOpinion:
    """
    A strategy agent's opinion about a symbol.
    
    Published by: Strategy agents
    Consumed by: ConsensusCoordinator
    """
    # Identity
    opinion_id: str = field(default_factory=lambda: f"op_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_role: str = "strategy"  # strategy, momentum, mean_reversion, ml, etc.
    
    # Subject
    symbol: str = ""
    venue: str = ""
    horizon: str = "1h"  # 1m, 5m, 15m, 1h, 4h, 1d
    
    # Opinion
    direction: OpinionDirection = OpinionDirection.FLAT
    confidence: float = 0.0  # 0.0 to 1.0
    target_size_pct: float = 0.0  # % of portfolio
    
    # Reasoning
    rationale_ref: str = ""  # Reference to detailed analysis in storage
    rationale_summary: str = ""
    signal_strength: float = 0.0  # Raw signal magnitude
    
    # State tracking
    state_version: str = ""  # Hash/version of market state used
    price_at_opinion: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    # Risk metadata
    max_drawdown_pct: float = 0.0
    stop_loss_pct: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "opinion_id": self.opinion_id,
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "symbol": self.symbol,
            "venue": self.venue,
            "horizon": self.horizon,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "target_size_pct": self.target_size_pct,
            "rationale_ref": self.rationale_ref,
            "rationale_summary": self.rationale_summary,
            "signal_strength": self.signal_strength,
            "state_version": self.state_version,
            "price_at_opinion": self.price_at_opinion,
            "timestamp": self.timestamp,
            "max_drawdown_pct": self.max_drawdown_pct,
            "stop_loss_pct": self.stop_loss_pct,
        }


@dataclass
class ConsensusDecision:
    """
    Aggregated consensus decision from multiple agent opinions.
    
    Published by: ConsensusCoordinator
    Consumed by: Execution agents, Risk agents
    """
    # Identity
    decision_id: str = field(default_factory=lambda: f"cd_{uuid.uuid4().hex[:12]}")
    consensus_round_id: str = ""
    
    # Subject
    symbol: str = ""
    venue: str = ""
    
    # Decision
    decision: OpinionDirection = OpinionDirection.FLAT
    size_usd: float = 0.0
    confidence: float = 0.0
    
    # Participating agents
    participating_agents: List[str] = field(default_factory=list)
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    abstaining_agents: List[str] = field(default_factory=list)
    
    # Dissent tracking
    dissenters: List[str] = field(default_factory=list)
    dissent_ratio: float = 0.0  # Fraction of agents disagreeing
    consensus_score: float = 0.0  # Weighted vote score
    
    # Opinion metadata
    opinion_ids: List[str] = field(default_factory=list)
    opinion_window_ms: float = 0.0
    avg_confidence: float = 0.0
    confidence_spread: float = 0.0  # Std dev of confidences
    
    # State tracking
    state_version: str = ""
    price_at_decision: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    # Aggregation method
    aggregation_method: str = "weighted_vote"  # weighted_vote, majority, unanimous
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "consensus_round_id": self.consensus_round_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "decision": self.decision.value,
            "size_usd": self.size_usd,
            "confidence": self.confidence,
            "participating_agents": self.participating_agents,
            "supporting_agents": self.supporting_agents,
            "opposing_agents": self.opposing_agents,
            "abstaining_agents": self.abstaining_agents,
            "dissenters": self.dissenters,
            "dissent_ratio": self.dissent_ratio,
            "consensus_score": self.consensus_score,
            "opinion_ids": self.opinion_ids,
            "opinion_window_ms": self.opinion_window_ms,
            "avg_confidence": self.avg_confidence,
            "confidence_spread": self.confidence_spread,
            "state_version": self.state_version,
            "price_at_decision": self.price_at_decision,
            "timestamp": self.timestamp,
            "aggregation_method": self.aggregation_method,
        }


@dataclass
class TradeIntent:
    """
    Intent to execute a trade, after risk approval.
    
    Published by: Execution agents (after risk check)
    Consumed by: OrderRouter
    """
    # Identity
    intent_id: str = field(default_factory=lambda: f"ti_{uuid.uuid4().hex[:12]}")
    consensus_id: str = ""
    
    # Order details
    symbol: str = ""
    venue: str = ""
    side: str = "buy"  # buy, sell
    quantity: float = 0.0
    order_type: str = "market"  # market, limit, stop
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    
    # Risk approval
    risk_checked: bool = False
    risk_agent_id: str = ""
    risk_score: float = 0.0
    position_size_approved: float = 0.0
    
    # Mode enforcement
    mode: TradingMode = TradingMode.SIMULATION
    
    # State tracking
    state_version: str = ""
    price_at_intent: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    # Ancestry
    consensus_decision_ref: str = ""
    opinion_refs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "consensus_id": self.consensus_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "risk_checked": self.risk_checked,
            "risk_agent_id": self.risk_agent_id,
            "risk_score": self.risk_score,
            "position_size_approved": self.position_size_approved,
            "mode": self.mode.value,
            "state_version": self.state_version,
            "price_at_intent": self.price_at_intent,
            "timestamp": self.timestamp,
            "consensus_decision_ref": self.consensus_decision_ref,
            "opinion_refs": self.opinion_refs,
        }


@dataclass
class OrderEvent:
    """
    Actual order execution event.
    
    Published by: OrderRouter
    Consumed by: Portfolio manager, agents, UI
    """
    # Identity
    event_id: str = field(default_factory=lambda: f"oe_{uuid.uuid4().hex[:12]}")
    order_id: str = ""
    trade_intent_id: str = ""
    
    # Order details
    symbol: str = ""
    venue: str = ""
    side: str = "buy"
    quantity: float = 0.0
    order_type: str = "market"
    
    # Execution
    status: str = "pending"  # pending, filled, partial, rejected, cancelled
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fill_timestamp: Optional[float] = None
    
    # Mode tracking
    mode: TradingMode = TradingMode.SIMULATION
    simulated: bool = True
    
    # Fees and slippage
    commission_usd: float = 0.0
    slippage_bps: float = 0.0
    
    # Ancestry (full lineage)
    consensus_id: str = ""
    opinion_ids: List[str] = field(default_factory=list)
    
    # Timestamps
    submitted_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # Rejection reason
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "order_id": self.order_id,
            "trade_intent_id": self.trade_intent_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "status": self.status,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "fill_timestamp": self.fill_timestamp,
            "mode": self.mode.value,
            "simulated": self.simulated,
            "commission_usd": self.commission_usd,
            "slippage_bps": self.slippage_bps,
            "consensus_id": self.consensus_id,
            "opinion_ids": self.opinion_ids,
            "submitted_at": self.submitted_at,
            "acknowledged_at": self.acknowledged_at,
            "completed_at": self.completed_at,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class AgentHeartbeat:
    """
    Agent liveness signal.
    
    Published by: All agents
    Consumed by: Watchdog agents, monitoring
    """
    agent_id: str = ""
    agent_type: str = ""  # strategy, risk, execution, consensus, governance
    status: str = "healthy"  # healthy, degraded, error, offline
    
    # Activity metrics
    last_input_offset: int = 0  # Kafka offset or sequence number
    last_output_timestamp: float = 0.0
    messages_processed_count: int = 0
    error_count: int = 0
    
    # Lag metrics
    input_lag_ms: float = 0.0
    processing_latency_p50_ms: float = 0.0
    processing_latency_p99_ms: float = 0.0
    
    # Mode
    current_mode: TradingMode = TradingMode.SIMULATION
    
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "last_input_offset": self.last_input_offset,
            "last_output_timestamp": self.last_output_timestamp,
            "messages_processed_count": self.messages_processed_count,
            "error_count": self.error_count,
            "input_lag_ms": self.input_lag_ms,
            "processing_latency_p50_ms": self.processing_latency_p50_ms,
            "processing_latency_p99_ms": self.processing_latency_p99_ms,
            "current_mode": self.current_mode.value,
            "timestamp": self.timestamp,
        }
