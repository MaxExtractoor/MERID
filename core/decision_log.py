"""
Decision and Event Log System for MERID
Comprehensive logging of trades, decisions, outcomes, and context.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.persistence_manager import get_persistence_manager
from utils.logger import get_logger

logger = get_logger("core.decision_log")


class EventType(Enum):
    """Types of events to log."""
    TRADE_EXECUTION = "trade_execution"
    QUOTE_SNAPSHOT = "quote_snapshot"
    POSITION_CHANGE = "position_change"
    AGENT_DECISION = "agent_decision"
    OUTCOME_VALIDATION = "outcome_validation"
    MARKET_CONTEXT = "market_context"
    RISK_EVENT = "risk_event"
    SYSTEM_EVENT = "system_event"


class DecisionOutcome(Enum):
    """Outcome of a decision."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    PENDING = "pending"
    CANCELLED = "cancelled"


@dataclass
class TradeExecution:
    """Trade execution event."""
    trade_id: str
    timestamp: float
    symbol: str
    side: str  # buy/sell
    quantity: float
    price: float
    venue: str
    order_type: str
    fill_time_ms: float
    slippage_bps: float
    fees: float
    agent_id: Optional[str] = None
    strategy_id: Optional[str] = None
    metadata: Dict[str, Any] = None


@dataclass
class QuoteSnapshot:
    """Market quote snapshot."""
    timestamp: float
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    spread_bps: float
    venue: str
    metadata: Dict[str, Any] = None


@dataclass
class PositionChange:
    """Position change event."""
    timestamp: float
    symbol: str
    previous_quantity: float
    new_quantity: float
    average_entry_price: float
    unrealized_pnl: float
    realized_pnl: float
    agent_id: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = None


@dataclass
class AgentDecision:
    """Agent decision event."""
    decision_id: str
    timestamp: float
    agent_id: str
    agent_type: str
    decision_type: str  # trade, hedge, rebalance, etc.
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    confidence: float
    reasoning: str
    context: Dict[str, Any]
    outcome: DecisionOutcome = DecisionOutcome.PENDING
    outcome_timestamp: Optional[float] = None
    outcome_metrics: Dict[str, Any] = None


@dataclass
class OutcomeValidation:
    """Validation of decision outcome."""
    decision_id: str
    timestamp: float
    outcome: DecisionOutcome
    actual_result: Any
    expected_result: Any
    error_magnitude: float
    attribution: Dict[str, float]  # Factor contributions
    lessons_learned: List[str]
    metadata: Dict[str, Any] = None


@dataclass
class MarketContext:
    """Market environment context."""
    timestamp: float
    volatility: Dict[str, float]  # Per symbol
    liquidity: Dict[str, float]  # Per symbol
    spreads: Dict[str, float]  # Per symbol
    regime: str  # bull/bear/sideways/volatile
    correlations: Dict[str, float]  # Pairwise
    sentiment: Dict[str, float]  # Per symbol
    metadata: Dict[str, Any] = None


class DecisionLog:
    """Manages decision and event logging."""
    
    def __init__(self, log_dir: str = "logs/decisions"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self._trade_executions: List[TradeExecution] = []
        self._quote_snapshots: List[QuoteSnapshot] = []
        self._position_changes: List[PositionChange] = []
        self._agent_decisions: List[AgentDecision] = []
        self._outcome_validations: List[OutcomeValidation] = []
        self._market_contexts: List[MarketContext] = []
        
        self._persistence = get_persistence_manager()
    
    def log_trade_execution(self, trade: TradeExecution) -> None:
        """Log a trade execution."""
        self._trade_executions.append(trade)
        
        logger.info(
            f"Trade executed: {trade.symbol} {trade.side} {trade.quantity} @ {trade.price} "
            f"on {trade.venue} (slippage: {trade.slippage_bps:.2f}bps)"
        )
        
        self._persist_event(EventType.TRADE_EXECUTION, asdict(trade))
    
    def log_quote_snapshot(self, quote: QuoteSnapshot) -> None:
        """Log a market quote snapshot."""
        self._quote_snapshots.append(quote)
        self._persist_event(EventType.QUOTE_SNAPSHOT, asdict(quote))
    
    def log_position_change(self, position: PositionChange) -> None:
        """Log a position change."""
        self._position_changes.append(position)
        
        logger.info(
            f"Position changed: {position.symbol} {position.previous_quantity} -> {position.new_quantity} "
            f"(realized PnL: {position.realized_pnl:.2f})"
        )
        
        self._persist_event(EventType.POSITION_CHANGE, asdict(position))
    
    def log_agent_decision(self, decision: AgentDecision) -> None:
        """Log an agent decision."""
        self._agent_decisions.append(decision)
        
        logger.info(
            f"Agent decision: {decision.agent_id} ({decision.agent_type}) "
            f"{decision.decision_type} with confidence {decision.confidence:.2f}"
        )
        
        self._persist_event(EventType.AGENT_DECISION, asdict(decision))
    
    def log_outcome_validation(self, validation: OutcomeValidation) -> None:
        """Log outcome validation."""
        self._outcome_validations.append(validation)
        
        # Update corresponding decision
        for decision in self._agent_decisions:
            if decision.decision_id == validation.decision_id:
                decision.outcome = validation.outcome
                decision.outcome_timestamp = validation.timestamp
                decision.outcome_metrics = {
                    "error_magnitude": validation.error_magnitude,
                    "attribution": validation.attribution
                }
                break
        
        logger.info(
            f"Outcome validated: {validation.decision_id} -> {validation.outcome.value} "
            f"(error: {validation.error_magnitude:.4f})"
        )
        
        self._persist_event(EventType.OUTCOME_VALIDATION, asdict(validation))
    
    def log_market_context(self, context: MarketContext) -> None:
        """Log market context."""
        self._market_contexts.append(context)
        self._persist_event(EventType.MARKET_CONTEXT, asdict(context))
    
    def _persist_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """Persist event to disk."""
        event = {
            "event_type": event_type.value,
            "timestamp": time.time(),
            "data": data
        }
        
        # Use date-based file naming
        date_str = time.strftime("%Y-%m-%d")
        file_path = self.log_dir / f"events_{date_str}.jsonl"
        
        # Append to JSONL file
        try:
            with open(file_path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as exc:
            logger.error(f"Failed to persist event: {exc}")
    
    def get_trades(
        self,
        symbol: Optional[str] = None,
        agent_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> List[TradeExecution]:
        """Query trade executions."""
        trades = self._trade_executions
        
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        if agent_id:
            trades = [t for t in trades if t.agent_id == agent_id]
        if start_time:
            trades = [t for t in trades if t.timestamp >= start_time]
        if end_time:
            trades = [t for t in trades if t.timestamp <= end_time]
        
        return trades[-limit:]
    
    def get_agent_decisions(
        self,
        agent_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        outcome: Optional[DecisionOutcome] = None,
        start_time: Optional[float] = None,
        limit: int = 100
    ) -> List[AgentDecision]:
        """Query agent decisions."""
        decisions = self._agent_decisions
        
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        if decision_type:
            decisions = [d for d in decisions if d.decision_type == decision_type]
        if outcome:
            decisions = [d for d in decisions if d.outcome == outcome]
        if start_time:
            decisions = [d for d in decisions if d.timestamp >= start_time]
        
        return decisions[-limit:]
    
    def get_position_history(
        self,
        symbol: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[PositionChange]:
        """Get position history for a symbol."""
        positions = [p for p in self._position_changes if p.symbol == symbol]
        
        if start_time:
            positions = [p for p in positions if p.timestamp >= start_time]
        if end_time:
            positions = [p for p in positions if p.timestamp <= end_time]
        
        return positions
    
    def get_market_context_history(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100
    ) -> List[MarketContext]:
        """Get market context history."""
        contexts = self._market_contexts
        
        if start_time:
            contexts = [c for c in contexts if c.timestamp >= start_time]
        if end_time:
            contexts = [c for c in contexts if c.timestamp <= end_time]
        
        return contexts[-limit:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get logging statistics."""
        return {
            "total_trades": len(self._trade_executions),
            "total_decisions": len(self._agent_decisions),
            "total_position_changes": len(self._position_changes),
            "total_validations": len(self._outcome_validations),
            "total_contexts": len(self._market_contexts),
            "decision_outcomes": {
                outcome.value: sum(1 for d in self._agent_decisions if d.outcome == outcome)
                for outcome in DecisionOutcome
            },
            "agents_active": len(set(d.agent_id for d in self._agent_decisions)),
            "symbols_traded": len(set(t.symbol for t in self._trade_executions))
        }
    
    def flush(self) -> None:
        """Flush all pending logs to disk."""
        logger.info("Flushing decision logs")
        
        # Persist all in-memory data
        data = {
            "trade_executions": [asdict(t) for t in self._trade_executions],
            "quote_snapshots": [asdict(q) for q in self._quote_snapshots],
            "position_changes": [asdict(p) for p in self._position_changes],
            "agent_decisions": [asdict(d) for d in self._agent_decisions],
            "outcome_validations": [asdict(v) for v in self._outcome_validations],
            "market_contexts": [asdict(c) for c in self._market_contexts]
        }
        
        date_str = time.strftime("%Y-%m-%d")
        file_path = self.log_dir / f"snapshot_{date_str}.json"
        
        self._persistence.write_json(str(file_path), data, immediate=True)


# Global decision log
_decision_log: Optional[DecisionLog] = None


def get_decision_log() -> DecisionLog:
    """Get the global decision log."""
    global _decision_log
    if _decision_log is None:
        _decision_log = DecisionLog()
    return _decision_log
