"""Cross-Layer Traceability

Adds trace_id that flows through:
- order creation
- fill ingestion
- ledger write
- position update
- PnL impact

This enables end-to-end tracing from strategy decision to PnL impact.
"""

from __future__ import annotations

import uuid
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    """Record of a trace event in the execution path."""
    trace_id: str
    event_type: str  # "order_created", "fill_ingested", "ledger_write", "position_update", "pnl_impact"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)


class ExecutionTrace:
    """
    Cross-layer traceability for execution path.
    
    Flows trace_id through:
    - order creation (strategy decision)
    - fill ingestion (WebSocket/HTTP)
    - ledger write (fills_ledger)
    - position update (position_cache)
    - PnL impact (pnl_tracker)
    """
    
    _instance: Optional["ExecutionTrace"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "ExecutionTrace":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "ExecutionTrace":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Trace history
        self._trace_history: List[TraceEvent] = []
        self._max_history = 10000
        
        # Active traces by order_id and fill_id
        self._active_traces: Dict[str, str] = {}  # order_id -> trace_id
        self._fill_traces: Dict[str, str] = {}  # fill_id -> trace_id
        
        # Metrics
        self._traces_created: int = 0
        self._events_recorded: int = 0
        
        logger.info("[EXECUTION-TRACE] Initialized")
    
    def create_trace(self, order_id: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a new trace for an order.
        
        Args:
            order_id: Order identifier
            context: Additional context for the trace
            
        Returns:
            trace_id for this execution path
        """
        trace_id = str(uuid.uuid4())
        self._active_traces[order_id] = trace_id
        self._traces_created += 1
        
        # Record order creation event
        event = TraceEvent(
            trace_id=trace_id,
            event_type="order_created",
            context={"order_id": order_id, **(context or {})}
        )
        self._record_event(event)
        
        logger.debug(
            "[EXECUTION-TRACE] Created trace_id=%s for order_id=%s",
            trace_id, order_id
        )
        
        return trace_id
    
    def get_trace(self, order_id: str) -> Optional[str]:
        """Get trace_id for an order."""
        return self._active_traces.get(order_id)
    
    def get_trace_by_fill(self, fill_id: str) -> Optional[str]:
        """Get trace_id for a fill."""
        return self._fill_traces.get(fill_id)
    
    def record_fill_ingestion(
        self,
        fill_id: str,
        order_id: Optional[str],
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record fill ingestion event.
        
        Args:
            fill_id: Fill identifier
            order_id: Order identifier (if known)
            context: Additional context
        """
        trace_id = None
        
        # Try to get trace from order_id
        if order_id and order_id in self._active_traces:
            trace_id = self._active_traces[order_id]
        
        # If no trace, create one for this fill
        if not trace_id:
            trace_id = str(uuid.uuid4())
            self._traces_created += 1
        
        # Link fill to trace
        self._fill_traces[fill_id] = trace_id
        
        # Record event
        event = TraceEvent(
            trace_id=trace_id,
            event_type="fill_ingested",
            context={
                "fill_id": fill_id,
                "order_id": order_id,
                **(context or {})
            }
        )
        self._record_event(event)
        
        logger.debug(
            "[EXECUTION-TRACE] Recorded fill_ingestion for fill_id=%s trace_id=%s",
            fill_id, trace_id
        )
    
    def record_ledger_write(
        self,
        fill_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record ledger write event.
        
        Args:
            fill_id: Fill identifier
            context: Additional context
        """
        trace_id = self._fill_traces.get(fill_id)
        if not trace_id:
            logger.debug("[EXECUTION-TRACE] No trace found for fill_id=%s during ledger write", fill_id)
            return
        
        event = TraceEvent(
            trace_id=trace_id,
            event_type="ledger_write",
            context={"fill_id": fill_id, **(context or {})}
        )
        self._record_event(event)
    
    def record_position_update(
        self,
        market_id: str,
        trace_id: Optional[str],
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record position update event.
        
        Args:
            market_id: Market identifier
            trace_id: Trace identifier (if known)
            context: Additional context
        """
        if not trace_id:
            logger.debug("[EXECUTION-TRACE] No trace_id provided for position update on %s", market_id)
            return
        
        event = TraceEvent(
            trace_id=trace_id,
            event_type="position_update",
            context={"market_id": market_id, **(context or {})}
        )
        self._record_event(event)
    
    def record_pnl_impact(
        self,
        market_id: str,
        trace_id: Optional[str],
        pnl_usd: float,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record PnL impact event.
        
        Args:
            market_id: Market identifier
            trace_id: Trace identifier (if known)
            pnl_usd: PnL impact in USD
            context: Additional context
        """
        if not trace_id:
            logger.debug("[EXECUTION-TRACE] No trace_id provided for PnL impact on %s", market_id)
            return
        
        event = TraceEvent(
            trace_id=trace_id,
            event_type="pnl_impact",
            context={
                "market_id": market_id,
                "pnl_usd": pnl_usd,
                **(context or {})
            }
        )
        self._record_event(event)
    
    def _record_event(self, event: TraceEvent) -> None:
        """Record a trace event."""
        self._trace_history.append(event)
        self._events_recorded += 1
        
        if len(self._trace_history) > self._max_history:
            self._trace_history.pop(0)
    
    def get_trace_events(self, trace_id: str) -> List[TraceEvent]:
        """Get all events for a specific trace."""
        return [e for e in self._trace_history if e.trace_id == trace_id]
    
    def get_trace_summary(self, trace_id: str) -> Dict[str, Any]:
        """Get summary of a trace."""
        events = self.get_trace_events(trace_id)
        if not events:
            return {}
        
        return {
            "trace_id": trace_id,
            "event_count": len(events),
            "event_types": [e.event_type for e in events],
            "first_event": events[0].timestamp.isoformat(),
            "last_event": events[-1].timestamp.isoformat(),
            "duration_ms": (events[-1].timestamp - events[0].timestamp).total_seconds() * 1000
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get trace metrics."""
        return {
            "traces_created": self._traces_created,
            "events_recorded": self._events_recorded,
            "active_traces": len(self._active_traces),
            "fill_traces": len(self._fill_traces),
            "history_size": len(self._trace_history)
        }
    
    def clear_trace(self, order_id: str) -> None:
        """Clear a trace (for testing or cleanup)."""
        if order_id in self._active_traces:
            trace_id = self._active_traces[order_id]
            del self._active_traces[order_id]
            logger.debug("[EXECUTION-TRACE] Cleared trace for order_id=%s", order_id)


def get_execution_trace() -> ExecutionTrace:
    """Get singleton instance of ExecutionTrace."""
    return ExecutionTrace.get_instance()
