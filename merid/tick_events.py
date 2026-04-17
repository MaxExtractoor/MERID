"""§OBS1 Tick Events — canonical structured event schema for MERID tick observability.

Every tick in the Kalshi trading loop emits a sequence of structured events:

  tick_started          → loop begins, tick_id assigned
  data_snapshot_taken   → market data fetched, counts recorded
  agent_cycle_completed → per-agent decision cycle finished
  risk_checked          → pre-trade risk verdict recorded
  order_submitted       → order sent to venue
  order_rejected        → order blocked by risk or venue
  fill_received         → fill confirmed
  tick_summary          → full tick rolled up, latency recorded
  tick_error            → unhandled error during tick

All events share a common envelope (event, tick_id, agent_id, ts, venue, mode).

The TickEventBus:
- Holds the last N tick summaries in memory (default 200).
- Broadcasts to registered async subscriber queues (for WS streaming).
- Is the single authoritative source for /api/v1/operator/ticks.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.tick_events")


# ── Event name constants ───────────────────────────────────────────────

TICK_STARTED = "tick_started"
DATA_SNAPSHOT_TAKEN = "data_snapshot_taken"
AGENT_CYCLE_COMPLETED = "agent_cycle_completed"
RISK_CHECKED = "risk_checked"
ORDER_SUBMITTED = "order_submitted"
ORDER_REJECTED = "order_rejected"
FILL_RECEIVED = "fill_received"
TICK_SUMMARY = "tick_summary"
TICK_ERROR = "tick_error"
STOP_LOSS_TRIGGERED = "stop_loss_triggered"
SESSION_GATED = "session_gated"


# ── Canonical event schema ────────────────────────────────────────────

@dataclass
class TickEvent:
    """Base envelope shared by every tick event."""
    event: str
    tick_id: str
    agent_id: str
    ts: float = field(default_factory=time.time)
    venue: str = "kalshi"
    mode: str = "paper"
    # Event-specific payload (kept flat for easy JSON serialisation)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "event": self.event,
            "tick_id": self.tick_id,
            "agent_id": self.agent_id,
            "ts": self.ts,
            "venue": self.venue,
            "mode": self.mode,
        }
        d.update(self.payload)
        return d


@dataclass
class TickSummary:
    """Rolled-up summary emitted at the end of each agent tick."""
    tick_id: str
    agent_id: str
    ts_started: float
    ts_ended: float
    duration_ms: float
    venue: str = "kalshi"
    mode: str = "paper"
    cycle_number: int = 0

    # Data phase
    markets_resolved: int = 0
    markets_in_window: int = 0
    session_allowed: bool = True

    # Signal phase
    signals_evaluated: int = 0
    signals_actionable: int = 0
    signals_consensus_blocked: int = 0

    # Risk phase
    risk_allowed: int = 0
    risk_blocked: int = 0

    # Execution phase
    orders_submitted: int = 0
    orders_rejected: int = 0
    fills_confirmed: int = 0

    # Stop-loss
    stop_losses_triggered: int = 0

    # Error
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": TICK_SUMMARY,
            "tick_id": self.tick_id,
            "agent_id": self.agent_id,
            "ts": self.ts_ended,
            "ts_started": self.ts_started,
            "ts_ended": self.ts_ended,
            "duration_ms": round(self.duration_ms, 1),
            "venue": self.venue,
            "mode": self.mode,
            "cycle_number": self.cycle_number,
            "markets_resolved": self.markets_resolved,
            "markets_in_window": self.markets_in_window,
            "session_allowed": self.session_allowed,
            "signals_evaluated": self.signals_evaluated,
            "signals_actionable": self.signals_actionable,
            "signals_consensus_blocked": self.signals_consensus_blocked,
            "risk_allowed": self.risk_allowed,
            "risk_blocked": self.risk_blocked,
            "orders_submitted": self.orders_submitted,
            "orders_rejected": self.orders_rejected,
            "fills_confirmed": self.fills_confirmed,
            "stop_losses_triggered": self.stop_losses_triggered,
            "error": self.error,
        }


# ── Tick context (per-cycle accumulator) ─────────────────────────────

class TickContext:
    """Mutable accumulator for a single agent tick.

    Created at tick_started, mutated as phases complete,
    finalised into a TickSummary at tick_summary.
    """

    def __init__(self, agent_id: str, cycle_number: int, venue: str = "kalshi", mode: str = "paper"):
        self.tick_id: str = uuid.uuid4().hex[:12]
        self.agent_id = agent_id
        self.cycle_number = cycle_number
        self.venue = venue
        self.mode = mode
        self.ts_started = time.time()

        self.markets_resolved: int = 0
        self.markets_in_window: int = 0
        self.session_allowed: bool = True
        self.signals_evaluated: int = 0
        self.signals_actionable: int = 0
        self.signals_consensus_blocked: int = 0
        self.risk_allowed: int = 0
        self.risk_blocked: int = 0
        self.orders_submitted: int = 0
        self.orders_rejected: int = 0
        self.fills_confirmed: int = 0
        self.stop_losses_triggered: int = 0
        self.error: str = ""

    def _base_event(self, event_name: str, **payload) -> TickEvent:
        return TickEvent(
            event=event_name,
            tick_id=self.tick_id,
            agent_id=self.agent_id,
            venue=self.venue,
            mode=self.mode,
            payload=payload,
        )

    def emit_started(self) -> TickEvent:
        return self._base_event(
            TICK_STARTED,
            cycle_number=self.cycle_number,
        )

    def emit_snapshot(self, markets_resolved: int, markets_in_window: int, session_allowed: bool) -> TickEvent:
        self.markets_resolved = markets_resolved
        self.markets_in_window = markets_in_window
        self.session_allowed = session_allowed
        return self._base_event(
            DATA_SNAPSHOT_TAKEN,
            markets_resolved=markets_resolved,
            markets_in_window=markets_in_window,
            session_allowed=session_allowed,
        )

    def emit_agent_cycle(self, signals_evaluated: int, signals_actionable: int, signals_consensus_blocked: int = 0) -> TickEvent:
        self.signals_evaluated += signals_evaluated
        self.signals_actionable += signals_actionable
        self.signals_consensus_blocked += signals_consensus_blocked
        return self._base_event(
            AGENT_CYCLE_COMPLETED,
            signals_evaluated=signals_evaluated,
            signals_actionable=signals_actionable,
            signals_consensus_blocked=signals_consensus_blocked,
        )

    def emit_risk_check(self, market_id: str, allowed: bool, reason: str = "") -> TickEvent:
        if allowed:
            self.risk_allowed += 1
        else:
            self.risk_blocked += 1
        return self._base_event(
            RISK_CHECKED,
            market_id=market_id,
            allowed=allowed,
            reason=reason,
        )

    def emit_order_submitted(self, market_id: str, side: str, contracts: int, price_cents: int, order_id: str = "") -> TickEvent:
        self.orders_submitted += 1
        return self._base_event(
            ORDER_SUBMITTED,
            market_id=market_id,
            side=side,
            contracts=contracts,
            price_cents=price_cents,
            order_id=order_id,
        )

    def emit_order_rejected(self, market_id: str, reason: str) -> TickEvent:
        self.orders_rejected += 1
        return self._base_event(
            ORDER_REJECTED,
            market_id=market_id,
            reason=reason,
        )

    def emit_fill(self, market_id: str, side: str, contracts: int, fill_price_cents: int) -> TickEvent:
        self.fills_confirmed += 1
        return self._base_event(
            FILL_RECEIVED,
            market_id=market_id,
            side=side,
            contracts=contracts,
            fill_price_cents=fill_price_cents,
        )

    def emit_stop_loss(self, ticker: str, rule: str, reason: str) -> TickEvent:
        self.stop_losses_triggered += 1
        return self._base_event(
            STOP_LOSS_TRIGGERED,
            ticker=ticker,
            rule=rule,
            reason=reason,
        )

    def emit_session_gated(self, reason: str) -> TickEvent:
        self.session_allowed = False
        return self._base_event(SESSION_GATED, reason=reason)

    def emit_error(self, error: str) -> TickEvent:
        self.error = error
        return self._base_event(TICK_ERROR, error=error)

    def finalise(self) -> TickSummary:
        ts_ended = time.time()
        return TickSummary(
            tick_id=self.tick_id,
            agent_id=self.agent_id,
            ts_started=self.ts_started,
            ts_ended=ts_ended,
            duration_ms=(ts_ended - self.ts_started) * 1000.0,
            venue=self.venue,
            mode=self.mode,
            cycle_number=self.cycle_number,
            markets_resolved=self.markets_resolved,
            markets_in_window=self.markets_in_window,
            session_allowed=self.session_allowed,
            signals_evaluated=self.signals_evaluated,
            signals_actionable=self.signals_actionable,
            signals_consensus_blocked=self.signals_consensus_blocked,
            risk_allowed=self.risk_allowed,
            risk_blocked=self.risk_blocked,
            orders_submitted=self.orders_submitted,
            orders_rejected=self.orders_rejected,
            fills_confirmed=self.fills_confirmed,
            stop_losses_triggered=self.stop_losses_triggered,
            error=self.error,
        )


# ── Tick Event Bus ────────────────────────────────────────────────────

class TickEventBus:
    """Central pub/sub bus for tick events.

    - emit(event): publish a TickEvent or TickSummary to all subscribers.
    - subscribe(): returns an asyncio.Queue that receives dicts.
    - recent_summaries(n): last N TickSummary dicts (for REST API).
    - recent_events(n): last N TickEvent dicts (granular stream).
    """

    def __init__(self, max_summaries: int = 200, max_events: int = 500):
        self._summaries: List[Dict[str, Any]] = []
        self._events: List[Dict[str, Any]] = []
        self._max_summaries = max_summaries
        self._max_events = max_events
        self._subscribers: List[asyncio.Queue] = []
        self._lock = threading.Lock()

    def emit(self, event: "TickEvent | TickSummary") -> None:
        """Publish an event. Thread-safe; notifies all WS subscribers."""
        d = event.to_dict()
        with self._lock:
            if d.get("event") == TICK_SUMMARY:
                self._summaries.append(d)
                if len(self._summaries) > self._max_summaries:
                    self._summaries = self._summaries[-self._max_summaries:]
            self._events.append(d)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(d)
            except asyncio.QueueFull:
                pass

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        """Register a new subscriber queue. Returns the queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def recent_summaries(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._summaries[-limit:])

    def recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events[-limit:])

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            summaries = self._summaries
            n = len(summaries)
            if not n:
                return {"total_ticks": 0, "subscribers": len(self._subscribers)}
            errors = sum(1 for s in summaries if s.get("error"))
            avg_ms = sum(s.get("duration_ms", 0) for s in summaries) / n
            total_orders = sum(s.get("orders_submitted", 0) for s in summaries)
            total_fills = sum(s.get("fills_confirmed", 0) for s in summaries)
            return {
                "total_ticks": n,
                "error_rate": round(errors / n, 4),
                "avg_duration_ms": round(avg_ms, 1),
                "total_orders_submitted": total_orders,
                "total_fills_confirmed": total_fills,
                "subscribers": len(self._subscribers),
            }


# ── Singleton ─────────────────────────────────────────────────────────

_bus: Optional[TickEventBus] = None
_bus_lock = threading.Lock()


def get_tick_bus() -> TickEventBus:
    """Return the global TickEventBus singleton."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = TickEventBus()
    return _bus
