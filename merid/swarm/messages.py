"""Typed Swarm Message Schemas — Sprint E.

Defines the canonical message types that flow between swarm agents:

- **Forecast** — A forecaster's probability estimate for a market
- **Critique** — A critic's evaluation of forecasts or market conditions
- **RiskView** — A risk agent's per-market or portfolio-level risk assessment
- **Decision** — The supervisor's final trading decision

All messages are published to ``core/streaming_bus.py`` channels and
consumed by the supervisor/consensus layer instead of sequential calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageType(str, Enum):
    """Swarm message types."""
    FORECAST = "forecast"
    CRITIQUE = "critique"
    RISK_VIEW = "risk_view"
    DECISION = "decision"


class CritiqueType(str, Enum):
    """Types of critic evaluations."""
    STALE_DATA = "stale_data"
    ILLIQUID = "illiquid"
    ARB_MISMATCH = "arb_mismatch"
    IMPOSSIBLE_PROB = "impossible_prob"
    MODEL_DIVERGENCE = "model_divergence"
    SPREAD_WARNING = "spread_warning"


class RiskLevel(str, Enum):
    """Risk assessment levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionAction(str, Enum):
    """Trading decision actions."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    SKIP = "skip"
    CLOSE = "close"


# ═══════════════════════════════════════════════════════════════════════
# Message dataclasses
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class Forecast:
    """A forecaster's probability estimate for a Kalshi market.

    Published by each forecaster agent after evaluating a market.
    Consumed by the supervisor/consensus layer.
    """
    message_type: str = field(default=MessageType.FORECAST, init=False)
    forecaster_id: str = ""
    model_type: str = ""          # "momentum", "mean_reversion", "edge_model", etc.
    market_id: str = ""
    asset: str = ""
    category: str = ""
    timeframe: str = ""
    p_model: float = 0.5          # YES probability (0–1)
    confidence: float = 0.0       # Signal confidence (0–1)
    edge_estimate: float = 0.0    # p_model - implied_yes (cents)
    components: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_type": self.message_type,
            "forecaster_id": self.forecaster_id,
            "model_type": self.model_type,
            "market_id": self.market_id,
            "asset": self.asset,
            "category": self.category,
            "timeframe": self.timeframe,
            "p_model": round(self.p_model, 6),
            "confidence": round(self.confidence, 4),
            "edge_estimate": round(self.edge_estimate, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "timestamp": self.timestamp,
        }


@dataclass
class Critique:
    """A critic's evaluation of market conditions or forecast quality.

    Published by critic/sanity agents. Can down-weight or veto forecasts.
    """
    message_type: str = field(default=MessageType.CRITIQUE, init=False)
    critic_id: str = ""
    critique_type: str = ""       # CritiqueType value
    market_id: str = ""
    severity: float = 0.0         # 0–1 (1 = critical)
    target_forecaster_id: Optional[str] = None  # If targeting a specific forecaster
    reason: str = ""
    recommended_action: str = ""  # "ignore", "down_weight", "veto"
    weight_adjustment: float = 1.0  # Multiplier for target forecaster (0.0 = full veto)
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_type": self.message_type,
            "critic_id": self.critic_id,
            "critique_type": self.critique_type,
            "market_id": self.market_id,
            "severity": round(self.severity, 3),
            "target_forecaster_id": self.target_forecaster_id,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "weight_adjustment": round(self.weight_adjustment, 3),
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class RiskView:
    """A risk agent's assessment for a market or portfolio.

    Published by risk agents. Consumed by the supervisor before deciding.
    """
    message_type: str = field(default=MessageType.RISK_VIEW, init=False)
    risk_agent_id: str = ""
    market_id: str = ""           # Empty string = portfolio-level
    asset: str = ""
    risk_level: str = RiskLevel.LOW
    max_size_contracts: int = 0   # 0 = do not trade
    kelly_fraction: float = 0.0
    edge_threshold_met: bool = False
    correlation_factor: float = 1.0  # From Sprint D
    exposure_pct: float = 0.0     # Current exposure as % of cap
    flags: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_type": self.message_type,
            "risk_agent_id": self.risk_agent_id,
            "market_id": self.market_id,
            "asset": self.asset,
            "risk_level": self.risk_level,
            "max_size_contracts": self.max_size_contracts,
            "kelly_fraction": round(self.kelly_fraction, 4),
            "edge_threshold_met": self.edge_threshold_met,
            "correlation_factor": round(self.correlation_factor, 3),
            "exposure_pct": round(self.exposure_pct, 2),
            "flags": self.flags,
            "timestamp": self.timestamp,
        }


@dataclass
class Decision:
    """The supervisor's final trading decision for a market.

    Published after consensus resolution. Consumed by the execution agent.
    """
    message_type: str = field(default=MessageType.DECISION, init=False)
    decision_id: str = ""
    market_id: str = ""
    asset: str = ""
    action: str = DecisionAction.SKIP
    side: str = ""                # "yes" or "no"
    size_contracts: int = 0
    limit_price: float = 0.0     # 0 = market order
    p_consensus: float = 0.5     # Consensus probability
    consensus_confidence: float = 0.0
    edge_estimate: float = 0.0
    contributing_forecasters: List[str] = field(default_factory=list)
    risk_approved: bool = False
    risk_flags: List[str] = field(default_factory=list)
    rationale: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_type": self.message_type,
            "decision_id": self.decision_id,
            "market_id": self.market_id,
            "asset": self.asset,
            "action": self.action,
            "side": self.side,
            "size_contracts": self.size_contracts,
            "limit_price": round(self.limit_price, 4),
            "p_consensus": round(self.p_consensus, 6),
            "consensus_confidence": round(self.consensus_confidence, 4),
            "edge_estimate": round(self.edge_estimate, 4),
            "contributing_forecasters": self.contributing_forecasters,
            "risk_approved": self.risk_approved,
            "risk_flags": self.risk_flags,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════
# Bus integration helpers
# ═══════════════════════════════════════════════════════════════════════


async def publish_forecast(forecast: Forecast) -> None:
    """Publish a Forecast message to the streaming bus."""
    try:
        from core.streaming_bus import get_event_bus, StreamEvent, EventChannel
        bus = get_event_bus()
        await bus.publish(StreamEvent(
            channel=EventChannel.AGENT_OUTPUT,
            event_type="forecast",
            source=forecast.forecaster_id,
            data=forecast.to_dict(),
            timestamp=forecast.timestamp,
        ))
    except Exception:
        pass  # Bus unavailable — non-fatal


async def publish_critique(critique: Critique) -> None:
    """Publish a Critique message to the streaming bus."""
    try:
        from core.streaming_bus import get_event_bus, StreamEvent, EventChannel
        bus = get_event_bus()
        await bus.publish(StreamEvent(
            channel=EventChannel.AGENT_OUTPUT,
            event_type="critique",
            source=critique.critic_id,
            data=critique.to_dict(),
            timestamp=critique.timestamp,
        ))
    except Exception:
        pass  # Bus unavailable — non-fatal


async def publish_risk_view(risk_view: RiskView) -> None:
    """Publish a RiskView message to the streaming bus."""
    try:
        from core.streaming_bus import get_event_bus, StreamEvent, EventChannel
        bus = get_event_bus()
        await bus.publish(StreamEvent(
            channel=EventChannel.AGENT_OUTPUT,
            event_type="risk_view",
            source=risk_view.risk_agent_id,
            data=risk_view.to_dict(),
            timestamp=risk_view.timestamp,
        ))
    except Exception:
        pass  # Bus unavailable — non-fatal


async def publish_decision(decision: Decision) -> None:
    """Publish a Decision message to the streaming bus."""
    try:
        from core.streaming_bus import get_event_bus, StreamEvent, EventChannel
        bus = get_event_bus()
        await bus.publish(StreamEvent(
            channel=EventChannel.CONSENSUS,
            event_type="decision",
            source="supervisor",
            data=decision.to_dict(),
            timestamp=decision.timestamp,
        ))
    except Exception:
        pass  # Bus unavailable — non-fatal
