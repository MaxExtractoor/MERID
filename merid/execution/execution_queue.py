"""Top-Edge Execution Queue — Single-file, queue-aware order pipeline.

Core rule: Only the current best idea that passes bankroll and reconciliation
gets to block the pipe. Everything else is dropped or deferred.

Per-ticker state machine:
    IDLE → PENDING → OPEN → IDLE

While PENDING or OPEN, new intents on the same ticker are rejected.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional
from queue import PriorityQueue, Empty

from utils.logger import get_logger

logger = get_logger("merid.execution.execution_queue")


class TickerState(Enum):
    """Per-ticker execution state machine."""
    IDLE = "idle"
    PENDING = "pending"
    OPEN = "open"


class QueueAction(Enum):
    """Action taken on queue submission."""
    ENQUEUED = "enqueued"
    REJECTED_RISK = "rejected_risk"
    REJECTED_RECON = "rejected_recon"
    REJECTED_STATE = "rejected_state"
    REJECTED_BANKROLL = "rejected_bankroll"
    DROPPED = "dropped"


@dataclass(order=True)
class ExecutionQueueEntry:
    """Priority queue entry for validated trade intents."""
    priority_score: float
    timestamp: float
    entry_id: str = field(compare=False)
    ticker: str = field(compare=False)
    direction: str = field(compare=False)
    size_contracts: int = field(compare=False)
    edge: float = field(compare=False)
    confidence: float = field(compare=False)
    bankroll_snapshot_usd: Decimal = field(compare=False)
    risk_ok: bool = field(compare=False)
    recon_ok: bool = field(compare=False)
    agent_id: str = field(compare=False)
    strategy_signal_id: Optional[str] = field(compare=False)
    cycle_id: Optional[str] = field(compare=False)
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_signal(
        cls,
        ticker: str,
        direction: str,
        size_contracts: int,
        edge: float,
        confidence: float,
        bankroll_snapshot_usd: Decimal,
        risk_ok: bool,
        recon_ok: bool,
        agent_id: str,
        strategy_signal_id: Optional[str] = None,
        cycle_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionQueueEntry":
        priority = -(edge * confidence * 1000.0)
        return cls(
            priority_score=priority,
            timestamp=time.time(),
            entry_id=f"eq_{int(time.time() * 1000)}_{ticker}",
            ticker=ticker,
            direction=direction,
            size_contracts=size_contracts,
            edge=edge,
            confidence=confidence,
            bankroll_snapshot_usd=bankroll_snapshot_usd,
            risk_ok=risk_ok,
            recon_ok=recon_ok,
            agent_id=agent_id,
            strategy_signal_id=strategy_signal_id,
            cycle_id=cycle_id,
            metadata=metadata or {},
        )


@dataclass
class QueueSubmissionResult:
    """Result of attempting to submit to execution queue."""
    action: QueueAction
    entry_id: Optional[str] = None
    ticker: Optional[str] = None
    reason: Optional[str] = None
    current_ticker_state: Optional[TickerState] = None
    edge: float = 0.0
    confidence: float = 0.0


@dataclass
class TickerExecutionState:
    """State tracking for a single ticker."""
    ticker: str
    state: TickerState = TickerState.IDLE
    current_entry_id: Optional[str] = None
    entry_time: Optional[float] = None
    fill_time: Optional[float] = None
    close_time: Optional[float] = None
    last_rejection_time: Optional[float] = None
    rejection_cooldown_seconds: float = 5.0
    total_enqueued: int = 0
    total_executed: int = 0
    total_rejected: int = 0

    def is_available(self) -> bool:
        if self.state != TickerState.IDLE:
            return False
        if self.last_rejection_time:
            elapsed = time.time() - self.last_rejection_time
            if elapsed < self.rejection_cooldown_seconds:
                return False
        return True


class TopEdgeExecutionQueue:
    """Priority queue for validated trades with per-ticker state machine."""

    def __init__(
        self,
        max_queue_size: int = 100,
        pending_timeout_seconds: float = 15.0,
        cooldown_after_rejection_seconds: float = 5.0,
    ):
        self._max_size = max_queue_size
        self._pending_timeout = pending_timeout_seconds
        self._cooldown_seconds = cooldown_after_rejection_seconds
        self._queue: PriorityQueue[ExecutionQueueEntry] = PriorityQueue(maxsize=max_queue_size)
        self._ticker_states: Dict[str, TickerExecutionState] = {}
        self._ticker_locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.RLock()
        self._processing_entry_id: Optional[str] = None

        # Metrics
        self._submissions_total = 0
        self._submissions_accepted = 0
        self._submissions_rejected_risk = 0
        self._submissions_rejected_recon = 0
        self._submissions_rejected_state = 0
        self._submissions_rejected_bankroll = 0
        self._submissions_dropped = 0
        self._executions_completed = 0
        self._executions_failed = 0

        logger.info(
            "[EXEC_QUEUE] Initialized max_size=%d pending_timeout=%.0fs cooldown=%.0fs",
            max_queue_size, pending_timeout_seconds, cooldown_after_rejection_seconds
        )

    def _get_ticker_state(self, ticker: str) -> TickerExecutionState:
        with self._global_lock:
            if ticker not in self._ticker_states:
                self._ticker_states[ticker] = TickerExecutionState(
                    ticker=ticker,
                    rejection_cooldown_seconds=self._cooldown_seconds,
                )
                self._ticker_locks[ticker] = threading.Lock()
            return self._ticker_states[ticker]

    def _get_ticker_lock(self, ticker: str) -> threading.Lock:
        with self._global_lock:
            if ticker not in self._ticker_locks:
                self._ticker_locks[ticker] = threading.Lock()
            return self._ticker_locks[ticker]

    def submit(
        self,
        ticker: str,
        direction: str,
        size_contracts: int,
        edge: float,
        confidence: float,
        bankroll_snapshot_usd: Decimal,
        risk_ok: bool,
        recon_ok: bool,
        agent_id: str,
        strategy_signal_id: Optional[str] = None,
        cycle_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QueueSubmissionResult:
        """Submit a validated trade intent to the execution queue."""
        self._submissions_total += 1

        if not risk_ok:
            self._submissions_rejected_risk += 1
            return QueueSubmissionResult(
                action=QueueAction.REJECTED_RISK,
                ticker=ticker,
                reason="risk_ok=False",
                edge=edge,
                confidence=confidence,
            )

        if not recon_ok:
            self._submissions_rejected_recon += 1
            return QueueSubmissionResult(
                action=QueueAction.REJECTED_RECON,
                ticker=ticker,
                reason="recon_ok=False",
                edge=edge,
                confidence=confidence,
            )

        if bankroll_snapshot_usd <= 0:
            self._submissions_rejected_bankroll += 1
            return QueueSubmissionResult(
                action=QueueAction.REJECTED_BANKROLL,
                ticker=ticker,
                reason=f"bankroll=${bankroll_snapshot_usd}",
                edge=edge,
                confidence=confidence,
            )

        ticker_state = self._get_ticker_state(ticker)
        ticker_lock = self._get_ticker_lock(ticker)

        with ticker_lock:
            if not ticker_state.is_available():
                self._submissions_rejected_state += 1
                ticker_state.total_rejected += 1
                ticker_state.last_rejection_time = time.time()
                return QueueSubmissionResult(
                    action=QueueAction.REJECTED_STATE,
                    ticker=ticker,
                    reason=f"ticker_state={ticker_state.state.value}",
                    current_ticker_state=ticker_state.state,
                    edge=edge,
                    confidence=confidence,
                )

            entry = ExecutionQueueEntry.from_signal(
                ticker=ticker,
                direction=direction,
                size_contracts=size_contracts,
                edge=edge,
                confidence=confidence,
                bankroll_snapshot_usd=bankroll_snapshot_usd,
                risk_ok=risk_ok,
                recon_ok=recon_ok,
                agent_id=agent_id,
                strategy_signal_id=strategy_signal_id,
                cycle_id=cycle_id,
                metadata=metadata or {},
            )

            ticker_state.state = TickerState.PENDING
            ticker_state.current_entry_id = entry.entry_id
            ticker_state.entry_time = time.time()
            ticker_state.total_enqueued += 1

            try:
                self._queue.put_nowait(entry)
                self._submissions_accepted += 1

                logger.info(
                    "[EXEC_QUEUE] ENQUEUED entry=%s ticker=%s edge=%.4f conf=%.2f priority=%.1f agent=%s",
                    entry.entry_id, ticker, edge, confidence, -entry.priority_score, agent_id
                )

                return QueueSubmissionResult(
                    action=QueueAction.ENQUEUED,
                    entry_id=entry.entry_id,
                    ticker=ticker,
                    reason="top_edge_accepted",
                    current_ticker_state=TickerState.PENDING,
                    edge=edge,
                    confidence=confidence,
                )

            except Exception as e:
                ticker_state.state = TickerState.IDLE
                ticker_state.current_entry_id = None
                ticker_state.entry_time = None

                logger.error(
                    "[EXEC_QUEUE] ENQUEUE_FAILED entry=%s ticker=%s error=%s",
                    entry.entry_id, ticker, e
                )

                return QueueSubmissionResult(
                    action=QueueAction.DROPPED,
                    ticker=ticker,
                    reason=f"enqueue_error: {e}",
                    edge=edge,
                    confidence=confidence,
                )

    def get_next_for_execution(self, timeout_seconds: float = 0.1) -> Optional[ExecutionQueueEntry]:
        """Get the next entry for execution."""
        try:
            entry = self._queue.get(timeout=timeout_seconds)
            self._processing_entry_id = entry.entry_id
            logger.info(
                "[EXEC_QUEUE] DEQUEUE entry=%s ticker=%s edge=%.4f for execution",
                entry.entry_id, entry.ticker, entry.edge
            )
            return entry
        except Empty:
            return None

    def mark_executed(self, entry_id: str, ticker: str, success: bool = True) -> None:
        """Mark an entry as executed (transition PENDING → OPEN or back to IDLE)."""
        ticker_state = self._get_ticker_state(ticker)
        ticker_lock = self._get_ticker_lock(ticker)

        with ticker_lock:
            if ticker_state.current_entry_id != entry_id:
                logger.warning(
                    "[EXEC_QUEUE] MISMATCH entry_id=%s current=%s ticker=%s",
                    entry_id, ticker_state.current_entry_id, ticker
                )
                return

            if success:
                ticker_state.state = TickerState.OPEN
                ticker_state.fill_time = time.time()
                ticker_state.total_executed += 1
                self._executions_completed += 1
                logger.info(
                    "[EXEC_QUEUE] EXECUTED entry=%s ticker=%s state=PENDING→OPEN",
                    entry_id, ticker
                )
            else:
                ticker_state.state = TickerState.IDLE
                ticker_state.current_entry_id = None
                ticker_state.entry_time = None
                self._executions_failed += 1
                logger.warning(
                    "[EXEC_QUEUE] REJECTED entry=%s ticker=%s state=PENDING→IDLE",
                    entry_id, ticker
                )

        self._processing_entry_id = None

    def mark_closed(self, ticker: str, entry_id: Optional[str] = None) -> None:
        """Mark a position as closed (transition OPEN → IDLE)."""
        ticker_state = self._get_ticker_state(ticker)
        ticker_lock = self._get_ticker_lock(ticker)

        with ticker_lock:
            if entry_id and ticker_state.current_entry_id != entry_id:
                logger.debug(
                    "[EXEC_QUEUE] CLOSE_SKIP entry_id=%s current=%s ticker=%s",
                    entry_id, ticker_state.current_entry_id, ticker
                )
                return

            old_state = ticker_state.state
            ticker_state.state = TickerState.IDLE
            ticker_state.close_time = time.time()

            logger.info(
                "[EXEC_QUEUE] CLOSED entry=%s ticker=%s state=%s→IDLE",
                ticker_state.current_entry_id, ticker, old_state.value
            )

            ticker_state.current_entry_id = None
            ticker_state.entry_time = None
            ticker_state.fill_time = None

    def get_ticker_state(self, ticker: str) -> Optional[TickerState]:
        """Get current state for a ticker."""
        ticker_state = self._ticker_states.get(ticker)
        if ticker_state:
            return ticker_state.state
        return TickerState.IDLE

    def is_ticker_available(self, ticker: str) -> bool:
        """Check if ticker is available for new orders."""
        ticker_state = self._get_ticker_state(ticker)
        return ticker_state.is_available()

    def get_metrics(self) -> Dict[str, Any]:
        """Get queue metrics for monitoring."""
        with self._global_lock:
            ticker_states_summary = {
                ticker: {
                    "state": ts.state.value,
                    "current_entry": ts.current_entry_id,
                    "enqueued": ts.total_enqueued,
                    "executed": ts.total_executed,
                    "rejected": ts.total_rejected,
                }
                for ticker, ts in self._ticker_states.items()
                if ts.state != TickerState.IDLE or ts.total_enqueued > 0
            }

            return {
                "submissions": {
                    "total": self._submissions_total,
                    "accepted": self._submissions_accepted,
                    "rejected_risk": self._submissions_rejected_risk,
                    "rejected_recon": self._submissions_rejected_recon,
                    "rejected_state": self._submissions_rejected_state,
                    "rejected_bankroll": self._submissions_rejected_bankroll,
                    "dropped": self._submissions_dropped,
                },
                "executions": {
                    "completed": self._executions_completed,
                    "failed": self._executions_failed,
                },
                "queue": {
                    "size": self._queue.qsize(),
                    "max_size": self._max_size,
                    "processing_entry": self._processing_entry_id,
                },
                "ticker_states": ticker_states_summary,
                "tickers_not_idle": sum(
                    1 for ts in self._ticker_states.values()
                    if ts.state != TickerState.IDLE
                ),
            }

    def reset_ticker(self, ticker: str) -> bool:
        """Force reset ticker to IDLE (emergency use)."""
        ticker_state = self._get_ticker_state(ticker)
        ticker_lock = self._get_ticker_lock(ticker)

        with ticker_lock:
            old_state = ticker_state.state
            ticker_state.state = TickerState.IDLE
            ticker_state.current_entry_id = None
            ticker_state.entry_time = None

            logger.warning(
                "[EXEC_QUEUE] RESET ticker=%s state=%s→IDLE",
                ticker, old_state.value
            )
            return True


# Global singleton
_execution_queue: Optional[TopEdgeExecutionQueue] = None
_execution_queue_lock = threading.Lock()


def get_execution_queue(
    max_queue_size: int = 100,
    pending_timeout_seconds: float = 15.0,
    cooldown_after_rejection_seconds: float = 5.0,
) -> TopEdgeExecutionQueue:
    """Get or create the global execution queue singleton."""
    global _execution_queue
    with _execution_queue_lock:
        if _execution_queue is None:
            _execution_queue = TopEdgeExecutionQueue(
                max_queue_size=max_queue_size,
                pending_timeout_seconds=pending_timeout_seconds,
                cooldown_after_rejection_seconds=cooldown_after_rejection_seconds,
            )
        return _execution_queue


def reset_execution_queue() -> None:
    """Reset the global execution queue (testing only)."""
    global _execution_queue
    with _execution_queue_lock:
        _execution_queue = None
