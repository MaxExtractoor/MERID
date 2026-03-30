"""
Governance Event Bus — typed pub/sub with DLQ, retry, and asset/timeframe fields.

Design notes
============
* Every governance event carries ``asset`` and ``timeframe`` fields (may be
  ``None`` for system-wide events).  Both MUST come from the canonical set in
  ``config.crypto_universe`` when they are set.
* Failed deliveries are retried up to ``max_retries`` times with exponential
  back-off capped at ``max_retry_delay_s``.  After exhausting retries, the
  event is moved to the Dead-Letter Queue (DLQ).
* DLQ depth is observable via ``get_dlq_depth()`` and all DLQ entries are
  logged at WARNING level.  Operators can replay via ``replay_dlq()``.
* No subscriber for an event type is itself a warning-level log so "handled by
  nobody" events are never silent.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("agents.governance_event_bus")

# ── Event types ───────────────────────────────────────────────────────────────


class GovernanceEventType(str, Enum):
    """All supported governance event types.

    Keep this the single authoritative list; never string-match raw strings
    outside this enum.
    """

    # Agent lifecycle
    AGENT_PAUSED = "agent.paused"
    AGENT_RESUMED = "agent.resumed"
    AGENT_PROMOTED = "agent.promoted"
    AGENT_DEMOTED = "agent.demoted"
    AGENT_RETIRED = "agent.retired"

    # Quorum / consensus
    QUORUM_FAILED = "quorum.failed"
    QUORUM_RECOVERED = "quorum.recovered"
    CONSENSUS_REACHED = "consensus.reached"

    # Risk / circuit-breaker
    RISK_BREACH = "risk.breach"
    KILL_SWITCH_ACTIVATED = "kill_switch.activated"
    KILL_SWITCH_DEACTIVATED = "kill_switch.deactivated"

    # Promotion / demotion
    PROMOTION_APPROVED = "promotion.approved"
    PROMOTION_REJECTED = "promotion.rejected"
    DEMOTION_TRIGGERED = "demotion.triggered"

    # Alerts / incidents
    INCIDENT_OPENED = "incident.opened"
    INCIDENT_ESCALATED = "incident.escalated"
    INCIDENT_RESOLVED = "incident.resolved"

    # Governance decisions
    GOVERNANCE_ACTION = "governance.action"
    POLICY_UPDATED = "policy.updated"


# ── Event schema ──────────────────────────────────────────────────────────────


@dataclass
class GovernanceEvent:
    """A typed governance event with full asset/timeframe context.

    ``asset`` and ``timeframe`` MUST be values from
    ``config.crypto_universe.CRYPTO_ASSETS`` /
    ``config.crypto_universe.CRYPTO_TIMEFRAMES`` when they refer to a
    specific market series.  Use ``None`` for system-wide events.
    """

    event_type: GovernanceEventType
    payload: Dict[str, Any]

    # Crypto universe fields — set when the event concerns a specific series.
    asset: Optional[str] = None
    timeframe: Optional[str] = None

    # Housekeeping.
    event_id: str = field(default_factory=lambda: f"gev-{uuid.uuid4().hex[:12]}")
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)

    # Retry bookkeeping — managed by the bus; callers must not set these.
    _attempt: int = field(default=0, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "_attempt": self._attempt,
        }


# ── DLQ entry ─────────────────────────────────────────────────────────────────


@dataclass
class DLQEntry:
    """A governance event that exhausted all retries."""

    event: GovernanceEvent
    last_error: str
    failed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failed_at": self.failed_at,
            "last_error": self.last_error,
            "event": self.event.to_dict(),
        }


# ── Handler type ──────────────────────────────────────────────────────────────

# A handler can be either a plain sync callable or an async coroutine function.
HandlerFn = Callable[[GovernanceEvent], Any]


# ── Bus ───────────────────────────────────────────────────────────────────────


class GovernanceEventBus:
    """Typed governance event bus with DLQ, retry, and per-event metrics.

    Usage::

        bus = GovernanceEventBus()

        # Register a handler.
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, my_handler)

        # Publish an event (fire-and-forget — returns immediately).
        bus.publish(GovernanceEvent(
            event_type=GovernanceEventType.QUORUM_FAILED,
            asset="BTC",
            timeframe="15m",
            source="unified_decision_layer",
            payload={"reason": "only 1 of 3 agents responded"},
        ))
    """

    # Retry / back-off knobs — intentionally centralised here.
    DLQ_MAX_SIZE: int = 1_000

    def __init__(
        self,
        max_retries: int = 3,
        initial_retry_delay_s: float = 0.5,
        max_retry_delay_s: float = 30.0,
    ) -> None:
        self.max_retries = max_retries
        self.initial_retry_delay_s = initial_retry_delay_s
        self.max_retry_delay_s = max_retry_delay_s
        self._subscribers: Dict[GovernanceEventType, List[HandlerFn]] = defaultdict(list)
        self._dlq: Deque[DLQEntry] = deque(maxlen=self.DLQ_MAX_SIZE)
        self._event_counts: Dict[str, int] = defaultdict(int)
        self._dlq_counts: Dict[str, int] = defaultdict(int)
        self._pending_tasks: List[asyncio.Task] = []

    # ── Subscription ─────────────────────────────────────────────────────────

    def subscribe(
        self,
        event_type: GovernanceEventType,
        handler: HandlerFn,
    ) -> None:
        """Register a handler for an event type."""
        self._subscribers[event_type].append(handler)
        logger.debug(
            "governance_event_bus: subscribed %s → %s",
            event_type.value,
            getattr(handler, "__qualname__", repr(handler)),
        )

    def unsubscribe(
        self,
        event_type: GovernanceEventType,
        handler: HandlerFn,
    ) -> None:
        """Remove a previously registered handler."""
        try:
            self._subscribers[event_type].remove(handler)
        except ValueError:
            pass

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, event: GovernanceEvent) -> None:
        """Publish an event.

        Dispatches synchronously where possible; schedules async dispatch via
        ``asyncio.create_task`` when a running event loop is available.
        """
        self._validate_event(event)
        self._event_counts[event.event_type.value] += 1
        handlers = list(self._subscribers.get(event.event_type, []))

        if not handlers:
            logger.warning(
                "governance_event_bus: no subscribers for %s (event_id=%s, asset=%s, tf=%s)",
                event.event_type.value,
                event.event_id,
                event.asset,
                event.timeframe,
            )
            return

        logger.debug(
            "governance_event_bus: dispatching %s to %d handler(s) (event_id=%s)",
            event.event_type.value,
            len(handlers),
            event.event_id,
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        for handler in handlers:
            if loop is not None:
                task = loop.create_task(
                    self._dispatch_with_retry(event, handler),
                    name=f"gov_bus_{event.event_id}",
                )
                # Keep a reference so the task is not garbage-collected.
                self._pending_tasks.append(task)
                task.add_done_callback(self._pending_tasks.remove)
            else:
                # Synchronous path (unit tests, scripts).
                self._dispatch_sync(event, handler)

    # ── Internal dispatch ─────────────────────────────────────────────────────

    def _dispatch_sync(self, event: GovernanceEvent, handler: HandlerFn) -> None:
        """Synchronous dispatch with retry (non-async environments only)."""
        delay = self.initial_retry_delay_s
        last_err = ""
        for attempt in range(self.max_retries + 1):
            event._attempt = attempt
            try:
                result = handler(event)
                # If handler returned a coroutine, we can't await it here.
                if asyncio.iscoroutine(result):
                    result.close()
                    logger.warning(
                        "governance_event_bus: async handler %s called in sync context; "
                        "coroutine discarded (event_id=%s)",
                        getattr(handler, "__qualname__", repr(handler)),
                        event.event_id,
                    )
                return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                if attempt < self.max_retries:
                    logger.warning(
                        "governance_event_bus: handler %s failed (attempt %d/%d, event_id=%s): %s",
                        getattr(handler, "__qualname__", repr(handler)),
                        attempt + 1,
                        self.max_retries + 1,
                        event.event_id,
                        exc,
                    )
                    time.sleep(min(delay, self.max_retry_delay_s))
                    delay *= 2
        self._send_to_dlq(event, last_err)

    async def _dispatch_with_retry(
        self, event: GovernanceEvent, handler: HandlerFn
    ) -> None:
        """Async dispatch with exponential back-off retry."""
        delay = self.initial_retry_delay_s
        last_err = ""
        for attempt in range(self.max_retries + 1):
            event._attempt = attempt
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                if attempt < self.max_retries:
                    wait = min(delay, self.max_retry_delay_s)
                    logger.warning(
                        "governance_event_bus: handler %s failed (attempt %d/%d, "
                        "event_id=%s, retry_in=%.1fs): %s",
                        getattr(handler, "__qualname__", repr(handler)),
                        attempt + 1,
                        self.max_retries + 1,
                        event.event_id,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)
                    delay *= 2
        self._send_to_dlq(event, last_err)

    def _send_to_dlq(self, event: GovernanceEvent, error: str) -> None:
        """Move an event to the DLQ after exhausting retries."""
        entry = DLQEntry(event=event, last_error=error)
        self._dlq.append(entry)
        self._dlq_counts[event.event_type.value] += 1
        logger.warning(
            "governance_event_bus: DLQ ← event_id=%s type=%s asset=%s tf=%s "
            "after %d attempts; last_error=%r; dlq_depth=%d",
            event.event_id,
            event.event_type.value,
            event.asset,
            event.timeframe,
            event._attempt + 1,
            error,
            len(self._dlq),
        )

    # ── DLQ management ───────────────────────────────────────────────────────

    def get_dlq_depth(self) -> int:
        """Return the current number of items in the DLQ."""
        return len(self._dlq)

    def get_dlq_entries(self) -> List[DLQEntry]:
        """Return a snapshot of all DLQ entries (oldest first)."""
        return list(self._dlq)

    def replay_dlq(self) -> int:
        """Re-publish all DLQ entries and clear the queue.

        Returns the number of events replayed.  Failed re-deliveries will
        return to the DLQ again if they still fail.
        """
        entries = list(self._dlq)
        self._dlq.clear()
        for entry in entries:
            entry.event._attempt = 0
            self.publish(entry.event)
        if entries:
            logger.info(
                "governance_event_bus: replayed %d DLQ event(s)", len(entries)
            )
        return len(entries)

    def clear_dlq(self) -> int:
        """Discard all DLQ entries (use with care — data is lost).

        Returns the number of discarded entries.
        """
        count = len(self._dlq)
        self._dlq.clear()
        if count:
            logger.warning(
                "governance_event_bus: cleared %d DLQ entry(s) without replay", count
            )
        return count

    # ── Observability ─────────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """Return observable metrics for dashboards and health checks."""
        return {
            "event_counts": dict(self._event_counts),
            "dlq_counts": dict(self._dlq_counts),
            "dlq_depth": len(self._dlq),
            "subscriber_counts": {
                et.value: len(handlers)
                for et, handlers in self._subscribers.items()
            },
        }

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_event(self, event: GovernanceEvent) -> None:
        """Validate asset/timeframe fields against crypto_universe."""
        # Import lazily to avoid circular imports at module load time.
        try:
            from config.crypto_universe import is_valid_pair

            if event.asset is not None and event.timeframe is not None:
                if not is_valid_pair(event.asset, event.timeframe):
                    logger.warning(
                        "governance_event_bus: event %s has invalid (asset=%r, tf=%r) — "
                        "check against config.crypto_universe",
                        event.event_id,
                        event.asset,
                        event.timeframe,
                    )
            elif event.asset is not None:
                from config.crypto_universe import CRYPTO_ASSETS

                if event.asset not in CRYPTO_ASSETS:
                    logger.warning(
                        "governance_event_bus: event %s has unknown asset=%r",
                        event.event_id,
                        event.asset,
                    )
            elif event.timeframe is not None:
                from config.crypto_universe import CRYPTO_TIMEFRAMES

                if event.timeframe not in CRYPTO_TIMEFRAMES:
                    logger.warning(
                        "governance_event_bus: event %s has unknown timeframe=%r",
                        event.event_id,
                        event.timeframe,
                    )
        except ImportError:
            pass  # Validation is best-effort; missing dep should not block.


# ── Singleton ─────────────────────────────────────────────────────────────────

_governance_event_bus: Optional[GovernanceEventBus] = None


def get_governance_event_bus() -> GovernanceEventBus:
    """Return the process-wide governance event bus (lazy singleton)."""
    global _governance_event_bus
    if _governance_event_bus is None:
        _governance_event_bus = GovernanceEventBus()
    return _governance_event_bus
