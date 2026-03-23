"""Market Consensus Schema for Kalshi Trading.

This module defines the core MarketConsensusSnapshot data structure that becomes
the object of consensus in MERID's trading system.

Philosophy:
- Consensus is about **Kalshi market state and trade decisions**, not news items
- News becomes one input feature among many (sentiment, on-chain, technicals)
- Market data (prices, liquidity, volume) are the primary signals
- Agent votes determine trading action: LONG, SHORT, FLAT (not news approval)

Flow:
  News/OnChain/Technicals → Features → MarketConsensusSnapshot → AgentVotes → TradingAction
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


class TradingAction(str, Enum):
    """Trading action determined by consensus."""
    LONG = "long"          # Buy YES or sell NO
    SHORT = "short"        # Buy NO or sell YES
    FLAT = "flat"          # No position / close position
    NO_EDGE = "no_edge"    # Market is fairly priced, no trade


class ConfidenceBucket(str, Enum):
    """Confidence classification for sizing."""
    LOW = "low"            # 0-40%
    MEDIUM = "medium"      # 40-70%
    HIGH = "high"          # 70-90%
    VERY_HIGH = "very_high"  # 90%+


@dataclass
class MarketData:
    """Kalshi market data snapshot."""
    ticker: str                          # e.g., "KXBTCD-26MAR2300-T"
    question: str                        # Market question

    # Pricing
    best_bid: Decimal = Decimal("0")     # Best YES bid in cents (0-99)
    best_ask: Decimal = Decimal("0")     # Best YES ask in cents (0-99)
    mid_price: Decimal = Decimal("0")    # (bid + ask) / 2
    last_price: Decimal = Decimal("0")   # Last trade price

    # Derived probabilities
    implied_prob: float = 0.0            # Mid price / 100 (0-1)

    # Liquidity
    spread_cents: Decimal = Decimal("0") # Ask - bid
    spread_pct: float = 0.0              # Spread / mid * 100
    bid_depth: int = 0                   # Contracts at best bid
    ask_depth: int = 0                   # Contracts at best ask
    total_depth: int = 0                 # Total book depth

    # Volume and activity
    volume_24h: int = 0                  # 24h volume in contracts
    trade_count_24h: int = 0             # Number of trades
    open_interest: int = 0               # Total open contracts

    # Metadata
    expiry_time: Optional[datetime] = None
    time_to_expiry_hours: float = 0.0
    active: bool = True

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "question": self.question,
            "best_bid": str(self.best_bid),
            "best_ask": str(self.best_ask),
            "mid_price": str(self.mid_price),
            "last_price": str(self.last_price),
            "implied_prob": round(self.implied_prob, 4),
            "spread_cents": str(self.spread_cents),
            "spread_pct": round(self.spread_pct, 2),
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "total_depth": self.total_depth,
            "volume_24h": self.volume_24h,
            "trade_count_24h": self.trade_count_24h,
            "open_interest": self.open_interest,
            "expiry_time": self.expiry_time.isoformat() if self.expiry_time else None,
            "time_to_expiry_hours": round(self.time_to_expiry_hours, 2),
            "active": self.active,
            "timestamp": self.timestamp,
        }


@dataclass
class MarketFeatures:
    """Feature inputs for market consensus.

    News and other signals become features, not the primary decision object.
    """
    # News sentiment features
    news_bullish_score: float = 0.0      # 0-1, recent bullish news impact
    news_bearish_score: float = 0.0      # 0-1, recent bearish news impact
    news_regime: str = "neutral"         # neutral, risk_on, risk_off, vol_spike
    recent_headlines: List[str] = field(default_factory=list)

    # On-chain / fundamentals (if applicable to asset)
    onchain_signal: float = 0.0          # -1 to +1, whale activity, flows
    funding_rate: Optional[float] = None # Perp funding if available

    # Technical indicators
    rsi_14: Optional[float] = None       # RSI(14)
    ema_cross: Optional[str] = None      # bullish, bearish, neutral
    volume_z_score: float = 0.0          # Volume anomaly z-score

    # Market regime
    volatility_regime: str = "normal"    # low, normal, high, extreme
    correlation_regime: str = "normal"   # normal, breakdown, flight_to_quality

    # Kalshi-specific
    kalshi_liquidity_score: float = 0.5  # 0-1, market quality score
    kalshi_volume_rank: int = 0          # Percentile rank vs other markets

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "news_bullish_score": round(self.news_bullish_score, 3),
            "news_bearish_score": round(self.news_bearish_score, 3),
            "news_regime": self.news_regime,
            "recent_headlines": self.recent_headlines[:3],  # Limit to 3
            "onchain_signal": round(self.onchain_signal, 3),
            "funding_rate": round(self.funding_rate, 4) if self.funding_rate else None,
            "rsi_14": round(self.rsi_14, 2) if self.rsi_14 else None,
            "ema_cross": self.ema_cross,
            "volume_z_score": round(self.volume_z_score, 2),
            "volatility_regime": self.volatility_regime,
            "correlation_regime": self.correlation_regime,
            "kalshi_liquidity_score": round(self.kalshi_liquidity_score, 3),
            "kalshi_volume_rank": self.kalshi_volume_rank,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentOpinion:
    """Single agent's opinion on a market."""
    agent_id: str
    agent_role: str                      # e.g., "price_feed", "news_monitor", "risk"

    # Opinion
    action: TradingAction                # LONG, SHORT, FLAT, NO_EDGE
    confidence: float                    # 0-1
    edge_estimate_pct: float = 0.0       # Agent's estimated edge vs market price

    # Reasoning
    reasoning: List[str] = field(default_factory=list)
    primary_factors: List[str] = field(default_factory=list)  # Which features drove decision

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_role": self.agent_role,
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "edge_estimate_pct": round(self.edge_estimate_pct, 2),
            "reasoning": self.reasoning[:2],  # Limit reasoning
            "primary_factors": self.primary_factors,
            "timestamp": self.timestamp,
        }


@dataclass
class MarketConsensusSnapshot:
    """The central object of consensus for Kalshi trading.

    This snapshot contains:
    - Kalshi market identifiers and data
    - Aggregated features (news, on-chain, technicals)
    - Agent opinions on trading action
    - Consensus outcome (what to do in this market)

    Agents vote on this snapshot to determine trading action.
    """
    snapshot_id: str = ""

    # Market identification
    event_id: str = ""                   # Kalshi event ID
    contract_id: str = ""                # Kalshi contract/ticker ID
    asset: str = ""                      # BTC, ETH, SOL, etc.
    timeframe: str = ""                  # 15m, 1h, 24h, weekly

    # Market data
    market_data: Optional[MarketData] = None

    # Feature inputs
    features: Optional[MarketFeatures] = None

    # Agent opinions
    agent_opinions: List[AgentOpinion] = field(default_factory=list)

    # Consensus outcome
    consensus_action: TradingAction = TradingAction.NO_EDGE
    consensus_confidence: float = 0.0
    consensus_edge_pct: float = 0.0      # Weighted avg edge from agents

    # Vote statistics
    votes_long: int = 0
    votes_short: int = 0
    votes_flat: int = 0
    votes_no_edge: int = 0
    total_votes: int = 0
    agreement_pct: float = 0.0           # % of agents agreeing with consensus

    # Execution parameters (if consensus is LONG/SHORT)
    recommended_side: Optional[str] = None  # "yes" or "no"
    recommended_size: int = 0            # Contracts to trade
    max_price_cents: int = 0             # Price limit (if applicable)

    # Risk constraints
    liquidity_ok: bool = True            # Spread/depth acceptable?
    risk_ok: bool = True                 # Position limits OK?
    fees_acceptable: bool = True         # Edge > fees?

    # Metadata
    timestamp: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.snapshot_id:
            self.snapshot_id = f"mcs-{self.contract_id}-{int(self.timestamp)}"

    def is_tradeable(self) -> bool:
        """Check if consensus result is tradeable."""
        return (
            self.consensus_action in (TradingAction.LONG, TradingAction.SHORT) and
            self.consensus_confidence >= 0.60 and  # Min 60% agreement
            self.liquidity_ok and
            self.risk_ok and
            self.fees_acceptable
        )

    def get_dominant_features(self) -> List[str]:
        """Extract the most frequently cited primary factors across all agents."""
        factor_counts: Dict[str, int] = {}
        for opinion in self.agent_opinions:
            for factor in opinion.primary_factors:
                factor_counts[factor] = factor_counts.get(factor, 0) + 1

        # Sort by count, return top 3
        sorted_factors = sorted(factor_counts.items(), key=lambda x: x[1], reverse=True)
        return [factor for factor, _ in sorted_factors[:3]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "event_id": self.event_id,
            "contract_id": self.contract_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "market_data": self.market_data.to_dict() if self.market_data else None,
            "features": self.features.to_dict() if self.features else None,
            "agent_opinions": [op.to_dict() for op in self.agent_opinions],
            "consensus_action": self.consensus_action.value,
            "consensus_confidence": round(self.consensus_confidence, 3),
            "consensus_edge_pct": round(self.consensus_edge_pct, 2),
            "votes_long": self.votes_long,
            "votes_short": self.votes_short,
            "votes_flat": self.votes_flat,
            "votes_no_edge": self.votes_no_edge,
            "total_votes": self.total_votes,
            "agreement_pct": round(self.agreement_pct, 2),
            "recommended_side": self.recommended_side,
            "recommended_size": self.recommended_size,
            "max_price_cents": self.max_price_cents,
            "liquidity_ok": self.liquidity_ok,
            "risk_ok": self.risk_ok,
            "fees_acceptable": self.fees_acceptable,
            "is_tradeable": self.is_tradeable(),
            "dominant_features": self.get_dominant_features(),
            "timestamp": self.timestamp,
            "created_at": self.created_at,
        }


@dataclass
class MarketConsensusDecision:
    """Record of a finalized market consensus decision.

    Used for reflection, PnL tracking, and agent learning.
    """
    decision_id: str = ""
    snapshot: Optional[MarketConsensusSnapshot] = None

    # Execution
    executed: bool = False
    execution_time: Optional[float] = None
    execution_price: Optional[Decimal] = None
    execution_size: int = 0
    order_id: Optional[str] = None

    # Outcome tracking
    settled: bool = False
    settlement_time: Optional[float] = None
    settlement_price: Optional[Decimal] = None  # Final contract price (0 or 100)
    pnl_usd: Optional[float] = None

    # Performance metrics
    decision_correct: Optional[bool] = None  # Did we pick the right side?
    edge_realized_pct: Optional[float] = None  # Actual edge vs estimated

    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.decision_id and self.snapshot:
            self.decision_id = f"mcd-{self.snapshot.snapshot_id}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "executed": self.executed,
            "execution_time": self.execution_time,
            "execution_price": str(self.execution_price) if self.execution_price else None,
            "execution_size": self.execution_size,
            "order_id": self.order_id,
            "settled": self.settled,
            "settlement_time": self.settlement_time,
            "settlement_price": str(self.settlement_price) if self.settlement_price else None,
            "pnl_usd": round(self.pnl_usd, 2) if self.pnl_usd else None,
            "decision_correct": self.decision_correct,
            "edge_realized_pct": round(self.edge_realized_pct, 2) if self.edge_realized_pct else None,
            "timestamp": self.timestamp,
        }
