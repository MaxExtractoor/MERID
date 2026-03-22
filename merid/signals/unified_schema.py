"""Unified Signal Schema — ApprovedSignal for single-path crypto execution.

This schema represents a signal that has passed all pre-execution checks:
- TradingAgent edge model + confidence
- SwarmConsensusAggregator direction/consensus gate
- ExecutionGuard 6-layer checks
- BTC15m risk layer evaluation

Every Kalshi crypto order flows through this schema before reaching
KalshiContinuousTrader for sizing and execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class ApprovedSignal:
    """
    Approved trading signal ready for execution.

    Published by TradingAgent to event_bus channel: signals.crypto.{asset}.{tenor}
    Consumed by KalshiContinuousTrader for sizing and execution.
    """
    # Identity
    signal_id: str                          # Unique signal ID
    timestamp: datetime                     # When signal was generated
    agent_id: str                           # Originating TradingAgent ID

    # Market identifiers
    asset: str                              # BTC, ETH, SOL, XRP, DOGE
    tenor: str                              # 15m, 1h, daily, weekly
    ticker: str                             # Kalshi market ticker (KXBTC15M-...)
    market_id: str                          # Event market ID
    question: str                           # Market question text

    # Signal direction and probability
    direction: str                          # "yes" or "no"
    model_prob: float                       # Model's probability estimate (0-1)
    market_prob: float                      # Current market price (0-1)
    edge: float                             # model_prob - market_prob
    confidence: float                       # Signal confidence (0-1)

    # Sizing recommendation from swarm
    swarm_size_band: str = "base"           # small, reduced, base, large
    swarm_consensus_prob: Optional[float] = None  # Consensus probability
    swarm_confidence: Optional[float] = None      # Consensus confidence
    agents_voting: int = 0                  # Number of agents in consensus

    # Execution parameters
    limit_price_cents: int = 50             # Suggested limit price (1-99)
    contracts_upper_bound: int = 1          # Max contracts (from swarm)

    # Market context snapshot
    spread_bps: float = 0.0                 # Current spread in basis points
    volume_24h: float = 0.0                 # 24h volume
    open_interest: float = 0.0              # Current open interest
    minutes_to_expiry: Optional[int] = None # Minutes until contract expiry

    # Risk context
    fear_greed: Optional[int] = None        # Fear/greed index (0-100)
    volatility_regime: str = "normal"       # calm, normal, hot
    risk_regime: str = "normal"             # normal, tight, halt

    # Settlement specification
    settlement_spec_id: Optional[str] = None  # Settlement index reference (e.g., "cf_btc_rr")
    settlement_source: Optional[str] = None   # "cf_benchmarks", "coinbase", etc.

    # Execution guard status
    guard_layers_passed: List[str] = field(default_factory=list)  # Which guards passed
    guard_adjustments: Dict[str, Any] = field(default_factory=dict)  # Size/price adjustments

    # Trade tracking
    trade_mode: str = "paper"               # paper, live, blocked
    executed: bool = False                  # Has this signal been executed?
    order_id: Optional[str] = None          # Filled order ID (if executed)
    fill_price_cents: Optional[int] = None  # Actual fill price
    fill_contracts: Optional[int] = None    # Actual filled contracts
    fill_timestamp: Optional[datetime] = None  # When order filled

    # Post-trade
    settlement_price: Optional[float] = None  # Final settlement (0 or 1)
    settlement_timestamp: Optional[datetime] = None  # When market settled
    realized_pnl_usd: Optional[float] = None  # Realized P&L

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for event bus publishing."""
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "asset": self.asset,
            "tenor": self.tenor,
            "ticker": self.ticker,
            "market_id": self.market_id,
            "question": self.question,
            "direction": self.direction,
            "model_prob": float(self.model_prob),
            "market_prob": float(self.market_prob),
            "edge": float(self.edge),
            "confidence": float(self.confidence),
            "swarm_size_band": self.swarm_size_band,
            "swarm_consensus_prob": float(self.swarm_consensus_prob) if self.swarm_consensus_prob else None,
            "swarm_confidence": float(self.swarm_confidence) if self.swarm_confidence else None,
            "agents_voting": self.agents_voting,
            "limit_price_cents": self.limit_price_cents,
            "contracts_upper_bound": self.contracts_upper_bound,
            "spread_bps": float(self.spread_bps),
            "volume_24h": float(self.volume_24h),
            "open_interest": float(self.open_interest),
            "minutes_to_expiry": self.minutes_to_expiry,
            "fear_greed": self.fear_greed,
            "volatility_regime": self.volatility_regime,
            "risk_regime": self.risk_regime,
            "settlement_spec_id": self.settlement_spec_id,
            "settlement_source": self.settlement_source,
            "guard_layers_passed": self.guard_layers_passed,
            "guard_adjustments": self.guard_adjustments,
            "trade_mode": self.trade_mode,
            "executed": self.executed,
            "order_id": self.order_id,
            "fill_price_cents": self.fill_price_cents,
            "fill_contracts": self.fill_contracts,
            "fill_timestamp": self.fill_timestamp.isoformat() if self.fill_timestamp else None,
            "settlement_price": float(self.settlement_price) if self.settlement_price else None,
            "settlement_timestamp": self.settlement_timestamp.isoformat() if self.settlement_timestamp else None,
            "realized_pnl_usd": float(self.realized_pnl_usd) if self.realized_pnl_usd else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ApprovedSignal:
        """Reconstruct from dictionary (for event bus consumption)."""
        return cls(
            signal_id=data["signal_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            agent_id=data["agent_id"],
            asset=data["asset"],
            tenor=data["tenor"],
            ticker=data["ticker"],
            market_id=data["market_id"],
            question=data["question"],
            direction=data["direction"],
            model_prob=data["model_prob"],
            market_prob=data["market_prob"],
            edge=data["edge"],
            confidence=data["confidence"],
            swarm_size_band=data.get("swarm_size_band", "base"),
            swarm_consensus_prob=data.get("swarm_consensus_prob"),
            swarm_confidence=data.get("swarm_confidence"),
            agents_voting=data.get("agents_voting", 0),
            limit_price_cents=data.get("limit_price_cents", 50),
            contracts_upper_bound=data.get("contracts_upper_bound", 1),
            spread_bps=data.get("spread_bps", 0.0),
            volume_24h=data.get("volume_24h", 0.0),
            open_interest=data.get("open_interest", 0.0),
            minutes_to_expiry=data.get("minutes_to_expiry"),
            fear_greed=data.get("fear_greed"),
            volatility_regime=data.get("volatility_regime", "normal"),
            risk_regime=data.get("risk_regime", "normal"),
            settlement_spec_id=data.get("settlement_spec_id"),
            settlement_source=data.get("settlement_source"),
            guard_layers_passed=data.get("guard_layers_passed", []),
            guard_adjustments=data.get("guard_adjustments", {}),
            trade_mode=data.get("trade_mode", "paper"),
            executed=data.get("executed", False),
            order_id=data.get("order_id"),
            fill_price_cents=data.get("fill_price_cents"),
            fill_contracts=data.get("fill_contracts"),
            fill_timestamp=datetime.fromisoformat(data["fill_timestamp"]) if data.get("fill_timestamp") else None,
            settlement_price=data.get("settlement_price"),
            settlement_timestamp=datetime.fromisoformat(data["settlement_timestamp"]) if data.get("settlement_timestamp") else None,
            realized_pnl_usd=data.get("realized_pnl_usd"),
        )

    def get_event_channel(self) -> str:
        """Get the event bus channel name for this signal."""
        return f"signals.crypto.{self.asset}.{self.tenor}"

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"{self.asset} {self.tenor} {self.direction.upper()} @ {self.model_prob:.1%} "
            f"(edge={self.edge:+.2%}, conf={self.confidence:.1%}, "
            f"size={self.swarm_size_band}, mode={self.trade_mode})"
        )
