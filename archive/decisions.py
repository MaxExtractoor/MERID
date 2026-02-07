"""
MERID Archive - Decision Logs

Records intent-to-outcome mappings for forensic analysis.
Tracks the full lifecycle of trading decisions.

Part of MERID-ARCHIVE (Layer 7 - Memory & Forensics)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("archive.decisions")


class DecisionStatus(Enum):
    """Status of a decision."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class DecisionOutcome(Enum):
    """Outcome classification."""
    PROFIT = "profit"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    UNKNOWN = "unknown"


@dataclass
class DecisionEvent:
    """An event in the decision lifecycle."""
    event_id: str
    timestamp: float
    status: DecisionStatus
    actor: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "actor": self.actor,
            "details": self.details,
        }


@dataclass
class DecisionRecord:
    """Complete record of a trading decision."""
    decision_id: str
    intent_id: str
    created_at: float
    
    # Context
    strategy_id: str
    regime: str
    confidence: float
    
    # Request
    asset: str
    side: str
    requested_notional: float
    
    # Lifecycle
    events: List[DecisionEvent] = field(default_factory=list)
    current_status: DecisionStatus = DecisionStatus.PROPOSED
    
    # Execution
    executed_notional: Optional[float] = None
    avg_price: Optional[float] = None
    slippage_bps: Optional[int] = None
    fees_usd: Optional[float] = None
    
    # Outcome
    pnl: Optional[float] = None
    outcome: DecisionOutcome = DecisionOutcome.UNKNOWN
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    
    def add_event(
        self,
        status: DecisionStatus,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> DecisionEvent:
        """Add an event to the decision lifecycle."""
        import uuid
        
        event = DecisionEvent(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            status=status,
            actor=actor,
            details=details or {},
        )
        
        self.events.append(event)
        self.current_status = status
        
        return event
    
    def set_execution(
        self,
        notional: float,
        avg_price: float,
        slippage_bps: int,
        fees_usd: float,
    ) -> None:
        """Set execution details."""
        self.executed_notional = notional
        self.avg_price = avg_price
        self.slippage_bps = slippage_bps
        self.fees_usd = fees_usd
    
    def set_outcome(self, pnl: float) -> None:
        """Set outcome based on PnL."""
        self.pnl = pnl
        
        if pnl > 0:
            self.outcome = DecisionOutcome.PROFIT
        elif pnl < 0:
            self.outcome = DecisionOutcome.LOSS
        else:
            self.outcome = DecisionOutcome.BREAKEVEN
    
    def get_duration_seconds(self) -> Optional[float]:
        """Get decision duration from proposal to completion."""
        if len(self.events) < 2:
            return None
        return self.events[-1].timestamp - self.events[0].timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "created_at": self.created_at,
            "strategy_id": self.strategy_id,
            "regime": self.regime,
            "confidence": self.confidence,
            "asset": self.asset,
            "side": self.side,
            "requested_notional": self.requested_notional,
            "events": [e.to_dict() for e in self.events],
            "current_status": self.current_status.value,
            "executed_notional": self.executed_notional,
            "avg_price": self.avg_price,
            "slippage_bps": self.slippage_bps,
            "fees_usd": self.fees_usd,
            "pnl": self.pnl,
            "outcome": self.outcome.value,
            "tags": self.tags,
            "notes": self.notes,
        }


class DecisionLogger:
    """
    Logs and tracks trading decisions.
    
    Features:
    - Full lifecycle tracking
    - Intent-to-outcome mapping
    - Query by various filters
    - Performance analytics
    """
    
    def __init__(self):
        self._decisions: Dict[str, DecisionRecord] = {}
        self._by_intent: Dict[str, str] = {}  # intent_id -> decision_id
        
        logger.info("Decision logger initialized")
    
    def create_decision(
        self,
        intent_id: str,
        strategy_id: str,
        regime: str,
        confidence: float,
        asset: str,
        side: str,
        requested_notional: float,
    ) -> DecisionRecord:
        """Create a new decision record."""
        import uuid
        
        decision_id = str(uuid.uuid4())
        
        record = DecisionRecord(
            decision_id=decision_id,
            intent_id=intent_id,
            created_at=time.time(),
            strategy_id=strategy_id,
            regime=regime,
            confidence=confidence,
            asset=asset,
            side=side,
            requested_notional=requested_notional,
        )
        
        # Add initial event
        record.add_event(DecisionStatus.PROPOSED, "OPS", {
            "strategy_id": strategy_id,
            "confidence": confidence,
        })
        
        self._decisions[decision_id] = record
        self._by_intent[intent_id] = decision_id
        
        logger.info(
            "Created decision %s for intent %s",
            decision_id[:8], intent_id[:8]
        )
        
        return record
    
    def get_decision(self, decision_id: str) -> Optional[DecisionRecord]:
        """Get decision by ID."""
        return self._decisions.get(decision_id)
    
    def get_by_intent(self, intent_id: str) -> Optional[DecisionRecord]:
        """Get decision by intent ID."""
        decision_id = self._by_intent.get(intent_id)
        if decision_id:
            return self._decisions.get(decision_id)
        return None
    
    def update_status(
        self,
        decision_id: str,
        status: DecisionStatus,
        actor: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[DecisionEvent]:
        """Update decision status."""
        record = self._decisions.get(decision_id)
        if not record:
            logger.warning("Decision not found: %s", decision_id)
            return None
        
        event = record.add_event(status, actor, details)
        
        logger.info(
            "Updated decision %s: %s by %s",
            decision_id[:8], status.value, actor
        )
        
        return event
    
    def record_execution(
        self,
        decision_id: str,
        notional: float,
        avg_price: float,
        slippage_bps: int,
        fees_usd: float,
    ) -> None:
        """Record execution details."""
        record = self._decisions.get(decision_id)
        if not record:
            logger.warning("Decision not found: %s", decision_id)
            return
        
        record.set_execution(notional, avg_price, slippage_bps, fees_usd)
        record.add_event(DecisionStatus.EXECUTING, "FIN", {
            "notional": notional,
            "avg_price": avg_price,
            "slippage_bps": slippage_bps,
        })
    
    def record_outcome(
        self,
        decision_id: str,
        pnl: float,
        notes: str = "",
    ) -> None:
        """Record decision outcome."""
        record = self._decisions.get(decision_id)
        if not record:
            logger.warning("Decision not found: %s", decision_id)
            return
        
        record.set_outcome(pnl)
        record.notes = notes
        record.add_event(DecisionStatus.COMPLETED, "ARCHIVE", {
            "pnl": pnl,
            "outcome": record.outcome.value,
        })
        
        logger.info(
            "Recorded outcome for %s: pnl=%.2f, outcome=%s",
            decision_id[:8], pnl, record.outcome.value
        )
    
    def query(
        self,
        status: Optional[DecisionStatus] = None,
        outcome: Optional[DecisionOutcome] = None,
        strategy_id: Optional[str] = None,
        regime: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 100,
    ) -> List[DecisionRecord]:
        """Query decisions with filters."""
        results = []
        
        for record in self._decisions.values():
            if status and record.current_status != status:
                continue
            if outcome and record.outcome != outcome:
                continue
            if strategy_id and record.strategy_id != strategy_id:
                continue
            if regime and record.regime != regime:
                continue
            if start_ts and record.created_at < start_ts:
                continue
            if end_ts and record.created_at > end_ts:
                continue
            
            results.append(record)
        
        # Sort by creation time descending
        results.sort(key=lambda r: r.created_at, reverse=True)
        
        return results[:limit]
    
    def get_performance_summary(
        self,
        strategy_id: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get performance summary."""
        decisions = self.query(
            status=DecisionStatus.COMPLETED,
            strategy_id=strategy_id,
            regime=regime,
            limit=10000,
        )
        
        if not decisions:
            return {"total_decisions": 0}
        
        total_pnl = sum(d.pnl or 0 for d in decisions)
        wins = sum(1 for d in decisions if d.outcome == DecisionOutcome.PROFIT)
        losses = sum(1 for d in decisions if d.outcome == DecisionOutcome.LOSS)
        
        return {
            "total_decisions": len(decisions),
            "total_pnl": round(total_pnl, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(decisions), 4) if decisions else 0,
            "avg_pnl": round(total_pnl / len(decisions), 2) if decisions else 0,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get logger statistics."""
        status_counts = {}
        outcome_counts = {}
        
        for record in self._decisions.values():
            status = record.current_status.value
            status_counts[status] = status_counts.get(status, 0) + 1
            
            outcome = record.outcome.value
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        
        return {
            "total_decisions": len(self._decisions),
            "status_counts": status_counts,
            "outcome_counts": outcome_counts,
        }


# Singleton instance
_decision_logger: Optional[DecisionLogger] = None


def get_decision_logger() -> DecisionLogger:
    """Get the singleton decision logger."""
    global _decision_logger
    if _decision_logger is None:
        _decision_logger = DecisionLogger()
    return _decision_logger
