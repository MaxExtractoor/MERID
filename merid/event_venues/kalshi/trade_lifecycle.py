"""Trade lifecycle tracing for Kalshi markets.

This module provides structured tracing of trade lifecycle from signal
to settlement, enabling analysis of why trades win or lose.

Key features:
- Unique trade_id threading through all lifecycle stages
- Structured logging at each stage
- Reconciliation of expected vs actual outcomes
- Side-specific performance tracking

Usage::

    from merid.event_venues.kalshi.trade_lifecycle import (
        TradeLifecycle,
        LifecycleStage,
        record_lifecycle_event,
    )
    
    # Create a new trade trace
    trace = TradeLifecycle(
        trade_id="trade_abc123",
        ticker="KXBTC15M-26MAY111330-30",
        side="yes",
        agent_id="BTC15M",
    )
    
    # Record lifecycle events
    record_lifecycle_event(trace, LifecycleStage.SIGNAL_GENERATED, {...})
    record_lifecycle_event(trace, LifecycleStage.STRATEGY_GATED, {...})
    record_lifecycle_event(trace, LifecycleStage.ORDER_PLACED, {...})
    record_lifecycle_event(trace, LifecycleStage.FILL_RECEIVED, {...})
    record_lifecycle_event(trace, LifecycleStage.SETTLED, {...})
"""

from __future__ import annotations

import json
import time as _time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trade_lifecycle")


class LifecycleStage(str, Enum):
    """Lifecycle stages for a trade."""
    SIGNAL_GENERATED = "signal_generated"
    STRATEGY_GATED = "strategy_gated"
    RISK_APPROVED = "risk_approved"
    ORDER_PLACED = "order_placed"
    FILL_RECEIVED = "fill_received"
    POSITION_MANAGED = "position_managed"
    EXPIRED = "expired"
    SETTLED = "settled"
    KILL_SWITCHED = "kill_switched"


@dataclass
class LifecycleEvent:
    """Single event in trade lifecycle."""
    stage: LifecycleStage
    timestamp: float
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "stage": self.stage.value,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "data": self.data,
        }


@dataclass
class TradeLifecycle:
    """Complete trace of a trade from signal to settlement.
    
    Attributes:
        trade_id: Unique identifier for this trade (should match intent_id)
        ticker: Kalshi market ticker
        side: YES or NO
        agent_id: Originating agent
        created_at: Creation timestamp
        events: List of lifecycle events
        metadata: Additional metadata
    """
    trade_id: str
    ticker: str
    side: str
    agent_id: str
    created_at: float = field(default_factory=_time.time)
    events: List[LifecycleEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_event(self, stage: LifecycleStage, data: Dict[str, Any]) -> None:
        """Add a lifecycle event."""
        event = LifecycleEvent(
            stage=stage,
            timestamp=_time.time(),
            data=data,
        )
        self.events.append(event)
        logger.info(
            "[TRADE-LIFECYCLE] trade_id=%s stage=%s ticker=%s side=%s agent_id=%s data=%s",
            self.trade_id,
            stage.value,
            self.ticker,
            self.side,
            self.agent_id,
            json.dumps(data, default=str),
        )
    
    def get_stage_data(self, stage: LifecycleStage) -> Optional[Dict[str, Any]]:
        """Get data for a specific stage."""
        for event in self.events:
            if event.stage == stage:
                return event.data
        return None
    
    def get_duration_between(self, stage1: LifecycleStage, stage2: LifecycleStage) -> Optional[float]:
        """Get duration in seconds between two stages."""
        t1 = None
        t2 = None
        
        for event in self.events:
            if event.stage == stage1:
                t1 = event.timestamp
            elif event.stage == stage2:
                t2 = event.timestamp
        
        if t1 is not None and t2 is not None:
            return t2 - t1
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "trade_id": self.trade_id,
            "ticker": self.ticker,
            "side": self.side,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "events": [e.to_dict() for e in self.events],
            "metadata": self.metadata,
        }


# Global registry of active trades
_active_trades: Dict[str, TradeLifecycle] = {}


def record_lifecycle_event(
    trade_id: str,
    stage: LifecycleStage,
    data: Dict[str, Any],
    ticker: Optional[str] = None,
    side: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> TradeLifecycle:
    """Record a lifecycle event for a trade.
    
    Args:
        trade_id: Unique trade identifier
        stage: Lifecycle stage
        data: Event-specific data
        ticker: Market ticker (required for new trades)
        side: Side (required for new trades)
        agent_id: Agent ID (required for new trades)
        
    Returns:
        TradeLifecycle object
    """
    if trade_id not in _active_trades:
        # Create new trade trace
        if ticker is None or side is None or agent_id is None:
            raise ValueError(
                "ticker, side, and agent_id required for new trade traces"
            )
        
        trace = TradeLifecycle(
            trade_id=trade_id,
            ticker=ticker,
            side=side,
            agent_id=agent_id,
        )
        _active_trades[trade_id] = trace
    
    trace = _active_trades[trade_id]
    trace.add_event(stage, data)
    return trace


def get_trade_lifecycle(trade_id: str) -> Optional[TradeLifecycle]:
    """Get lifecycle trace for a trade."""
    return _active_trades.get(trade_id)


def complete_trade_lifecycle(trade_id: str) -> Optional[TradeLifecycle]:
    """Mark trade as complete and remove from active registry.
    
    Returns the completed lifecycle trace.
    """
    trace = _active_trades.pop(trade_id, None)
    if trace:
        logger.info(
            "[TRADE-LIFECYCLE] Completed trade_id=%s with %d events",
            trade_id,
            len(trace.events),
        )
    return trace


def get_all_active_trades() -> List[TradeLifecycle]:
    """Get all active trade traces."""
    return list(_active_trades.values())


def analyze_trade_outcomes(
    trades: List[TradeLifecycle],
) -> Dict[str, Any]:
    """Analyze trade outcomes by side and stage.
    
    Args:
        trades: List of trade lifecycle traces
        
    Returns:
        Analysis results
    """
    total = len(trades)
    if total == 0:
        return {"total": 0}
    
    by_side: Dict[str, List[TradeLifecycle]] = {"yes": [], "no": []}
    by_stage: Dict[str, int] = {}
    
    for trade in trades:
        by_side[trade.side].append(trade)
        for event in trade.events:
            by_stage[event.stage.value] = by_stage.get(event.stage.value, 0) + 1
    
    # Calculate win rates by side (if settlement data available)
    yes_wins = 0
    no_wins = 0
    
    for trade in trades:
        settled_data = trade.get_stage_data(LifecycleStage.SETTLED)
        if settled_data:
            outcome = settled_data.get("outcome")  # "yes_won" or "no_won"
            if outcome == "yes_won":
                if trade.side == "yes":
                    yes_wins += 1
                else:
                    no_wins += 1
            elif outcome == "no_won":
                if trade.side == "no":
                    no_wins += 1
                else:
                    yes_wins += 1
    
    yes_total = len(by_side["yes"])
    no_total = len(by_side["no"])
    
    return {
        "total": total,
        "by_side": {
            "yes": {
                "total": yes_total,
                "wins": yes_wins,
                "win_rate": yes_wins / yes_total if yes_total > 0 else 0.0,
            },
            "no": {
                "total": no_total,
                "wins": no_wins,
                "win_rate": no_wins / no_total if no_total > 0 else 0.0,
            },
        },
        "by_stage": by_stage,
    }
