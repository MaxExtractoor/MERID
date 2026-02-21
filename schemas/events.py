"""
MERID Canonical Event Schemas - Section 2: Legacy Data Pipeline

Defines standardized event schemas for all Kafka topics.
LLM agents see only these normalized schemas, never raw vendor data.

Topic families:
- prices.*        - Market price data
- orderbook.*     - Order book snapshots/deltas
- trades.*        - Executed trades
- agent.opinions.*- Agent opinions
- consensus.*     - Consensus decisions
- risk.*          - Risk alerts and metrics
- alerts.*        - System alerts
- social.*        - Social/sentiment data
- news.*          - News headlines
- onchain.*       - On-chain data
"""

from __future__ import annotations

import time
import uuid
import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "1.0.0"


# ============================================
# BASE EVENT
# ============================================

@dataclass
class BaseEvent:
    """Base class for all MERID events."""
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: str = ""
    timestamp: float = field(default_factory=time.time)
    schema_version: str = SCHEMA_VERSION
    source: str = "merid"
    idempotency_key: str = ""
    
    def __post_init__(self):
        if not self.idempotency_key:
            self.idempotency_key = self.event_id
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def compute_hash(self) -> str:
        """Compute content hash for deduplication."""
        data = self.to_dict()
        # Remove non-deterministic fields
        data.pop("event_id", None)
        data.pop("timestamp", None)
        data.pop("idempotency_key", None)
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]


# ============================================
# PRICE EVENTS (prices.*)
# ============================================

@dataclass
class PriceEvent(BaseEvent):
    """
    Normalized price tick event.
    Topic: prices.spot.{symbol}, prices.perps.{symbol}, prices.fx.{pair}
    """
    event_type: str = "price.tick"
    symbol: str = ""
    venue: str = ""
    asset_type: str = "spot"  # spot, perps, options, fx
    
    # Price data
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    mid: float = 0.0
    
    # Volume
    bid_size: float = 0.0
    ask_size: float = 0.0
    volume_24h: float = 0.0
    
    # OHLC (if aggregated)
    open_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    
    def __post_init__(self):
        super().__post_init__()
        if self.bid and self.ask:
            self.mid = (self.bid + self.ask) / 2


@dataclass
class OHLCVEvent(BaseEvent):
    """
    OHLCV candle event.
    Topic: prices.ohlcv.{symbol}.{timeframe}
    """
    event_type: str = "price.ohlcv"
    symbol: str = ""
    venue: str = ""
    timeframe: str = "1m"  # 1m, 5m, 15m, 1h, 4h, 1d
    
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    
    candle_start: float = 0.0
    candle_end: float = 0.0
    trade_count: int = 0


# ============================================
# ORDERBOOK EVENTS (orderbook.*)
# ============================================

@dataclass
class OrderBookLevel:
    """Single orderbook level."""
    price: float
    size: float
    order_count: int = 0


@dataclass
class OrderBookEvent(BaseEvent):
    """
    Order book snapshot/update.
    Topic: orderbook.l2.{symbol}, orderbook.l3.{symbol}
    """
    event_type: str = "orderbook.snapshot"
    symbol: str = ""
    venue: str = ""
    depth_level: str = "l2"  # l1, l2, l3
    
    bids: List[Dict[str, float]] = field(default_factory=list)  # [{price, size}]
    asks: List[Dict[str, float]] = field(default_factory=list)
    
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    
    def __post_init__(self):
        super().__post_init__()
        if self.bids:
            self.best_bid = self.bids[0].get("price", 0)
        if self.asks:
            self.best_ask = self.asks[0].get("price", 0)
        if self.best_bid and self.best_ask:
            self.spread = self.best_ask - self.best_bid
            mid = (self.best_bid + self.best_ask) / 2
            self.spread_bps = (self.spread / mid) * 10000 if mid else 0


# ============================================
# TRADE EVENTS (trades.*)
# ============================================

@dataclass
class TradeEvent(BaseEvent):
    """
    Executed trade event.
    Topic: trades.executed.{symbol}
    """
    event_type: str = "trade.executed"
    
    # Identity
    trade_id: str = ""
    order_id: str = ""
    plan_id: str = ""  # Consensus plan that triggered this
    
    # Trade details
    symbol: str = ""
    venue: str = ""
    side: str = ""      # buy, sell
    quantity: float = 0.0
    price: float = 0.0
    notional_usd: float = 0.0
    
    # Execution quality
    slippage_bps: float = 0.0
    fees_usd: float = 0.0
    fees_asset: str = ""
    
    # Attribution
    agent_id: str = ""
    strategy: str = ""
    
    # Mode
    is_paper: bool = True
    execution_mode: str = "paper"  # paper, live


# ============================================
# AGENT OPINION EVENTS (agent.opinions.*)
# ============================================

class AgentStance(str, Enum):
    """Agent stance on an asset."""
    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"


@dataclass
class AgentOpinionEvent(BaseEvent):
    """
    Agent opinion event for consensus.
    Topic: agent.opinions.{symbol}
    """
    event_type: str = "agent.opinion"
    
    # Identity
    opinion_id: str = field(default_factory=lambda: f"op_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_role: str = ""  # bull_analyst, bear_analyst, risk_manager, etc.
    
    # Target
    symbol: str = ""
    venue: str = ""
    
    # Opinion
    stance: str = AgentStance.NEUTRAL.value
    score: float = 0.0        # -1.0 to 1.0
    confidence: float = 0.5   # 0.0 to 1.0
    
    # Context
    rationale: str = ""
    horizon: str = "short"    # short, medium, long
    
    # Data sources
    data_sources: List[str] = field(default_factory=list)
    supporting_signals: Dict[str, Any] = field(default_factory=dict)
    
    # TTL
    ttl_seconds: float = 300.0  # Opinion valid for 5 minutes


# ============================================
# CONSENSUS EVENTS (consensus.*)
# ============================================

class ConsensusOutcome(str, Enum):
    """Consensus decision outcomes."""
    APPROVED = "approved"
    REJECTED = "rejected"
    VETOED = "vetoed"
    TIMEOUT = "timeout"
    INSUFFICIENT_VOTES = "insufficient_votes"


@dataclass
class ConsensusEvent(BaseEvent):
    """
    Consensus decision event.
    Topic: consensus.decisions.{symbol}
    """
    event_type: str = "consensus.decision"
    
    # Identity
    consensus_id: str = field(default_factory=lambda: f"cons_{uuid.uuid4().hex[:12]}")
    plan_id: str = ""
    
    # Target
    symbol: str = ""
    venue: str = ""
    
    # Decision
    outcome: str = ConsensusOutcome.INSUFFICIENT_VOTES.value
    direction: str = "flat"   # long, short, flat, reduce
    target_size_usd: float = 0.0
    
    # Scoring
    consensus_score: float = 0.0
    confidence: float = 0.0
    quorum_met: bool = False
    
    # Participants
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    abstaining_agents: List[str] = field(default_factory=list)
    veto_agent: Optional[str] = None
    
    # Timing
    round_duration_ms: float = 0.0
    opinions_considered: int = 0


# ============================================
# RISK EVENTS (risk.*)
# ============================================

class RiskAlertSeverity(str, Enum):
    """Risk alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class RiskAlertEvent(BaseEvent):
    """
    Risk alert event.
    Topic: risk.alerts.{severity}
    """
    event_type: str = "risk.alert"
    
    alert_id: str = field(default_factory=lambda: f"ra_{uuid.uuid4().hex[:12]}")
    severity: str = RiskAlertSeverity.WARNING.value
    
    # Context
    symbol: Optional[str] = None
    venue: Optional[str] = None
    agent_id: Optional[str] = None
    
    # Alert details
    alert_type: str = ""      # position_limit, drawdown, exposure, etc.
    message: str = ""
    
    # Thresholds
    current_value: float = 0.0
    threshold_value: float = 0.0
    breach_percent: float = 0.0
    
    # Action taken
    action_taken: str = ""    # none, reduced, blocked, killed
    requires_ack: bool = False


@dataclass
class RiskMetricsEvent(BaseEvent):
    """
    Periodic risk metrics snapshot.
    Topic: risk.metrics
    """
    event_type: str = "risk.metrics"
    
    # Portfolio metrics
    total_exposure_usd: float = 0.0
    net_exposure_usd: float = 0.0
    gross_leverage: float = 0.0
    
    # PnL
    daily_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    
    # Risk metrics
    portfolio_var_95: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Limits usage
    position_limit_usage: float = 0.0  # 0-1
    exposure_limit_usage: float = 0.0
    daily_loss_limit_usage: float = 0.0


# ============================================
# SOCIAL/SENTIMENT EVENTS (social.*)
# ============================================

@dataclass
class SentimentEvent(BaseEvent):
    """
    Social sentiment event.
    Topic: social.sentiment.{symbol}
    """
    event_type: str = "social.sentiment"
    
    symbol: str = ""
    source: str = ""          # twitter, reddit, telegram, stockgeist, etc.
    
    # Sentiment scores
    sentiment_score: float = 0.0   # -1.0 to 1.0
    bullish_percent: float = 0.0
    bearish_percent: float = 0.0
    neutral_percent: float = 0.0
    
    # Volume
    mention_count: int = 0
    engagement_score: float = 0.0
    
    # Trend
    sentiment_change_1h: float = 0.0
    sentiment_change_24h: float = 0.0
    volume_change_24h: float = 0.0


# ============================================
# NEWS EVENTS (news.*)
# ============================================

@dataclass
class NewsEvent(BaseEvent):
    """
    News headline event.
    Topic: news.headlines.{symbol}
    """
    event_type: str = "news.headline"
    
    news_id: str = field(default_factory=lambda: f"news_{uuid.uuid4().hex[:12]}")
    
    # Content
    headline: str = ""
    summary: str = ""
    url: str = ""
    source: str = ""
    author: str = ""
    
    # Classification
    symbols: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    
    # Sentiment
    sentiment_score: float = 0.0
    relevance_score: float = 0.0
    
    # Timing
    published_at: float = 0.0
    
    # Dedup
    content_hash: str = ""
    
    def __post_init__(self):
        super().__post_init__()
        if not self.content_hash and self.headline:
            self.content_hash = hashlib.sha256(self.headline.encode()).hexdigest()[:16]


# ============================================
# ON-CHAIN EVENTS (onchain.*)
# ============================================

@dataclass
class WhaleTransactionEvent(BaseEvent):
    """
    Large on-chain transaction event.
    Topic: onchain.whale_tx.{chain}
    """
    event_type: str = "onchain.whale_tx"
    
    tx_hash: str = ""
    chain: str = ""           # ethereum, bitcoin, solana, etc.
    
    # Transaction details
    from_address: str = ""
    to_address: str = ""
    from_label: str = ""      # exchange, whale, dex, etc.
    to_label: str = ""
    
    # Value
    amount: float = 0.0
    amount_usd: float = 0.0
    asset: str = ""
    
    # Classification
    tx_type: str = ""         # transfer, exchange_deposit, exchange_withdrawal, etc.
    significance: str = "medium"  # low, medium, high


@dataclass
class DeFiFlowEvent(BaseEvent):
    """
    DeFi protocol flow event.
    Topic: onchain.defi.{protocol}
    """
    event_type: str = "onchain.defi_flow"
    
    protocol: str = ""        # aave, compound, uniswap, etc.
    chain: str = ""
    
    # Flow data
    tvl_usd: float = 0.0
    tvl_change_24h: float = 0.0
    
    inflow_usd: float = 0.0
    outflow_usd: float = 0.0
    net_flow_usd: float = 0.0
    
    # Specific metrics
    apy: Optional[float] = None
    utilization: Optional[float] = None


# ============================================
# EVENT FACTORY
# ============================================

EVENT_TYPES = {
    "price.tick": PriceEvent,
    "price.ohlcv": OHLCVEvent,
    "orderbook.snapshot": OrderBookEvent,
    "trade.executed": TradeEvent,
    "agent.opinion": AgentOpinionEvent,
    "consensus.decision": ConsensusEvent,
    "risk.alert": RiskAlertEvent,
    "risk.metrics": RiskMetricsEvent,
    "social.sentiment": SentimentEvent,
    "news.headline": NewsEvent,
    "onchain.whale_tx": WhaleTransactionEvent,
    "onchain.defi_flow": DeFiFlowEvent,
}


def create_event(event_type: str, **kwargs) -> BaseEvent:
    """Factory function to create events by type."""
    event_class = EVENT_TYPES.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown event type: {event_type}")
    return event_class(**kwargs)


def parse_event(data: Dict[str, Any]) -> BaseEvent:
    """Parse event from dictionary."""
    event_type = data.get("event_type", "")
    event_class = EVENT_TYPES.get(event_type, BaseEvent)
    return event_class(**data)
