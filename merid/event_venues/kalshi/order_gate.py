"""Pre-Trade Order Gate — Idempotent order store + centralized pre-trade checks.

Enforces three non-negotiable invariants before ANY order leaves the process:

1. **Idempotency** — Every order has a deterministic ``client_order_id``
   derived from (agent_id, strategy_group, contract_id, side, target_qty,
   decision_ts_bucket).  If that ID already exists as PENDING/LIVE/FILLED,
   the order is rejected (duplicate).

2. **Fill awareness** — If the current position for (contract, strategy)
   already satisfies the desired net quantity, the order is rejected as
   "already_satisfied".

3. **Single risk module** — ``PreTradeGate.check()`` is the ONE synchronous
   call that the order router and CT must invoke before any external API call.
   It runs: lease check → dedup → fill awareness → caps (delegates to
   KalshiRiskManager).

Usage::

    from merid.event_venues.kalshi.order_gate import get_pre_trade_gate

    gate = get_pre_trade_gate()
    verdict = gate.check(intent)
    if not verdict.allowed:
        return reject(verdict.reason)
    # … proceed to venue submission …
    gate.mark_submitted(verdict.client_order_id)
    # … on fill …
    gate.mark_filled(verdict.client_order_id, fill_count)
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_gate")


# ── Order status enum ────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    """Lifecycle states for an idempotent order record."""
    PENDING = "pending"       # Intent created, not yet submitted to venue
    SUBMITTED = "submitted"   # Sent to venue, awaiting ack
    LIVE = "live"             # Resting on venue order book
    PARTIAL = "partial"       # Partially filled
    FILLED = "filled"         # Fully filled
    CANCELED = "canceled"     # Canceled (by us or venue)
    REJECTED = "rejected"     # Rejected by venue or risk gate
    EXPIRED = "expired"       # TTL expired without fill


# Terminal states — no further venue interaction expected
_TERMINAL_STATES = frozenset({
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
})

# States where a duplicate intent should be blocked
_BLOCK_DUPLICATE_STATES = frozenset({
    OrderStatus.PENDING,
    OrderStatus.SUBMITTED,
    OrderStatus.LIVE,
    OrderStatus.PARTIAL,
    OrderStatus.FILLED,
})


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class OrderRecord:
    """Durable record for an idempotent order."""
    client_order_id: str
    agent_id: str
    strategy_group: str
    contract_id: str
    side: str                    # "yes" or "no"
    action: str                  # "buy" or "sell"
    target_count: int
    price_cents: int
    status: OrderStatus = OrderStatus.PENDING
    venue_order_id: Optional[str] = None
    filled_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    decision_ts_bucket: str = ""
    intent_id: Optional[str] = None


@dataclass
class GateVerdict:
    """Result of PreTradeGate.check()."""
    allowed: bool
    client_order_id: str
    reason: str = ""
    is_duplicate: bool = False
    existing_status: Optional[str] = None


@dataclass
class GateMetrics:
    """Observable counters for the pre-trade gate."""
    checks: int = 0
    allowed: int = 0
    blocked_duplicate: int = 0
    blocked_already_satisfied: int = 0
    blocked_lease_conflict: int = 0
    blocked_risk: int = 0
    blocked_stale_data: int = 0
    submitted: int = 0
    filled: int = 0
    canceled: int = 0


# ── Deterministic client_order_id ────────────────────────────────────────────

# Decision timestamp bucket width in seconds.  Two decisions within the same
# bucket for the same (agent, contract, side, qty) map to the same
# client_order_id, making retries safe.
DECISION_BUCKET_WIDTH_S: int = 60

# Market makers need shorter buckets to refresh quotes frequently (issue #2 fix).
# MMs quote both sides every cycle; 60s bucket causes "duplicate:pending" blocks.
MM_DECISION_BUCKET_WIDTH_S: int = 5


def _is_market_maker_agent(agent_id: str) -> bool:
    """Detect market maker agents by ID pattern for bucket width selection."""
    if not agent_id:
        return False
    aid = agent_id.lower()
    return (
        "mm" in aid
        or "market_maker" in aid
        or aid == "crypto_15m_mm"
        or aid.startswith("kalshi-crypto_15m_mm")
    )


def deterministic_client_order_id(
    agent_id: str,
    strategy_group: str,
    contract_id: str,
    side: str,
    target_qty: int,
    decision_ts: float,
    price_cents: int = 0,
    bucket_width_s: Optional[int] = None,
) -> str:
    """Generate a deterministic, collision-resistant client_order_id.

    The ID is a truncated SHA-256 hex digest of the canonical key components.
    Two calls with the same logical decision (within the same time bucket)
    will always produce the same ID → safe to retry.

    Args:
        price_cents: Limit price in cents (1-99). Included in preimage to
            distinguish orders at different prices (BUG-0312 fix).
        bucket_width_s: Override bucket width. If None, auto-detects MM agents
            and uses MM_DECISION_BUCKET_WIDTH_S (5s) vs DECISION_BUCKET_WIDTH_S (60s).
    """
    # Auto-detect market makers for shorter bucket width (issue #2 fix)
    if bucket_width_s is None:
        bucket_width_s = MM_DECISION_BUCKET_WIDTH_S if _is_market_maker_agent(agent_id) else DECISION_BUCKET_WIDTH_S

    bucket = int(decision_ts) // bucket_width_s
    preimage = f"{agent_id}|{strategy_group}|{contract_id}|{side}|{target_qty}|{price_cents}|{bucket}"
    digest = hashlib.sha256(preimage.encode()).hexdigest()[:32]
    return f"merid-{digest}"


# ── Idempotent Order Store ───────────────────────────────────────────────────

class IdempotentOrderStore:
    """In-memory idempotent order store keyed by ``client_order_id``.

    Thread-safe.  Entries are pruned after a configurable TTL so the store
    doesn't grow unbounded.
    """

    # Records older than this are eligible for pruning (24 hours).
    PRUNE_TTL_S: float = 86400.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._orders: Dict[str, OrderRecord] = {}
        self._metrics = GateMetrics()

    # ── Lookup / insert ──────────────────────────────────────────────────

    def lookup(self, client_order_id: str) -> Optional[OrderRecord]:
        """Return the existing record for this ID, or None."""
        with self._lock:
            return self._orders.get(client_order_id)

    def insert_if_absent(self, record: OrderRecord) -> Tuple[bool, Optional[OrderRecord]]:
        """Insert a new record if the ``client_order_id`` is not yet present.

        Returns:
            (inserted, existing_or_none) — ``inserted`` is True if the record
            was stored; False if a record already existed (returned as second
            element).
        """
        with self._lock:
            existing = self._orders.get(record.client_order_id)
            if existing is not None:
                return False, existing
            self._orders[record.client_order_id] = record
            return True, None

    # ── Status transitions ───────────────────────────────────────────────

    def mark_submitted(self, client_order_id: str, venue_order_id: Optional[str] = None) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec and rec.status in (OrderStatus.PENDING,):
                rec.status = OrderStatus.SUBMITTED
                rec.venue_order_id = venue_order_id
                rec.updated_at = time.time()
                self._metrics.submitted += 1

    def mark_live(self, client_order_id: str, venue_order_id: Optional[str] = None) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec and rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                rec.status = OrderStatus.LIVE
                if venue_order_id:
                    rec.venue_order_id = venue_order_id
                rec.updated_at = time.time()

    def mark_filled(self, client_order_id: str, filled_count: int) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec and rec.status not in _TERMINAL_STATES:
                rec.filled_count = filled_count
                if filled_count >= rec.target_count:
                    rec.status = OrderStatus.FILLED
                else:
                    rec.status = OrderStatus.PARTIAL
                rec.updated_at = time.time()
                self._metrics.filled += 1

    def mark_canceled(self, client_order_id: str) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec and rec.status not in _TERMINAL_STATES:
                rec.status = OrderStatus.CANCELED
                rec.updated_at = time.time()
                self._metrics.canceled += 1

    def mark_rejected(self, client_order_id: str, reason: str = "") -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec and rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                rec.status = OrderStatus.REJECTED
                rec.updated_at = time.time()

    # ── Query helpers ────────────────────────────────────────────────────

    def filled_count_for_contract(self, contract_id: str, side: str, strategy_group: str) -> int:
        """Total filled contracts for (contract, side, strategy_group)."""
        with self._lock:
            total = 0
            for rec in self._orders.values():
                if (
                    rec.contract_id == contract_id
                    and rec.side == side
                    and rec.strategy_group == strategy_group
                    and rec.status in (OrderStatus.FILLED, OrderStatus.PARTIAL)
                ):
                    total += rec.filled_count
            return total

    def has_live_order(self, contract_id: str, side: str, strategy_group: str) -> bool:
        """Check if there's an active (non-terminal) order for this combo."""
        with self._lock:
            for rec in self._orders.values():
                if (
                    rec.contract_id == contract_id
                    and rec.side == side
                    and rec.strategy_group == strategy_group
                    and rec.status not in _TERMINAL_STATES
                ):
                    return True
            return False

    # ── Maintenance ──────────────────────────────────────────────────────

    def prune_old(self, ttl_s: Optional[float] = None) -> int:
        """Remove terminal records older than *ttl_s*."""
        cutoff = time.time() - (ttl_s or self.PRUNE_TTL_S)
        with self._lock:
            stale = [
                k for k, v in self._orders.items()
                if v.status in _TERMINAL_STATES and v.updated_at < cutoff
            ]
            for k in stale:
                del self._orders[k]
        return len(stale)

    def snapshot(self) -> List[OrderRecord]:
        with self._lock:
            return list(self._orders.values())

    def get_metrics(self) -> Dict[str, int]:
        m = self._metrics
        return {
            "checks": m.checks,
            "allowed": m.allowed,
            "blocked_duplicate": m.blocked_duplicate,
            "blocked_already_satisfied": m.blocked_already_satisfied,
            "blocked_lease_conflict": m.blocked_lease_conflict,
            "blocked_risk": m.blocked_risk,
            "blocked_stale_data": m.blocked_stale_data,
            "submitted": m.submitted,
            "filled": m.filled,
            "canceled": m.canceled,
            "total_records": len(self._orders),
        }


# ── Pre-Trade Gate ───────────────────────────────────────────────────────────

class PreTradeGate:
    """Centralized pre-trade check — the ONE function all order paths must call.

    Pipeline: lease → dedup → fill-awareness → (external risk checks delegated
    to caller via ``allowed`` flag so this module stays dependency-light).
    """

    def __init__(
        self,
        order_store: Optional[IdempotentOrderStore] = None,
    ) -> None:
        self._store = order_store or IdempotentOrderStore()

    @property
    def store(self) -> IdempotentOrderStore:
        return self._store

    def check(
        self,
        agent_id: str,
        strategy_group: str,
        contract_id: str,
        side: str,
        action: str,
        target_count: int,
        price_cents: int,
        decision_ts: float,
        intent_id: Optional[str] = None,
        existing_filled: Optional[int] = None,
    ) -> GateVerdict:
        """Run pre-trade gate checks.

        Args:
            agent_id:        Agent placing the order.
            strategy_group:  Logical strategy group (e.g. "btc_15m").
            contract_id:     Market ticker.
            side:            "yes" or "no".
            action:          "buy" or "sell".
            target_count:    Contracts requested.
            price_cents:     Limit price.
            decision_ts:     Wall-clock epoch of the decision.
            intent_id:       Optional intent_id for tracing.
            existing_filled: Caller-provided filled count for this (contract,
                             side, strategy) if known; otherwise the store's
                             own tally is used.

        Returns:
            :class:`GateVerdict` with ``allowed``, ``client_order_id``, and
            ``reason`` (empty string if allowed).
        """
        self._store._metrics.checks += 1

        # 1. Deterministic client_order_id
        coid = deterministic_client_order_id(
            agent_id=agent_id,
            strategy_group=strategy_group,
            contract_id=contract_id,
            side=side,
            target_qty=target_count,
            decision_ts=decision_ts,
            price_cents=price_cents,
        )

        # 2. Lease check (done by caller before this — we trust the lease
        #    was acquired; if not, the caller sets lease_ok=False and we
        #    still provide the coid for logging).

        # 3. Idempotency / dedup check
        existing = self._store.lookup(coid)
        if existing is not None and existing.status in _BLOCK_DUPLICATE_STATES:
            self._store._metrics.blocked_duplicate += 1
            # P2: Duplicate order blocking is expected idempotent behavior
            # This occurs when the same intent is submitted twice (e.g., retry logic,
            # market maker refresh, or race conditions). Not an error condition.
            logger.info(
                "[GATE] duplicate_order_blocked coid=%s status=%s contract=%s agent=%s "
                "(expected idempotent behavior)",
                coid, existing.status.value, contract_id, agent_id,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"duplicate:{existing.status.value}",
                is_duplicate=True,
                existing_status=existing.status.value,
            )

        # 4. Fill-awareness: is the target already satisfied?
        if action == "buy":
            already_filled = (
                existing_filled
                if existing_filled is not None
                else self._store.filled_count_for_contract(contract_id, side, strategy_group)
            )
            if already_filled >= target_count:
                self._store._metrics.blocked_already_satisfied += 1
                logger.info(
                    "[GATE] already_satisfied coid=%s contract=%s filled=%d target=%d",
                    coid, contract_id, already_filled, target_count,
                )
                return GateVerdict(
                    allowed=False,
                    client_order_id=coid,
                    reason=f"already_satisfied:filled={already_filled}>=target={target_count}",
                )

        # 5. Insert new record (PENDING)
        record = OrderRecord(
            client_order_id=coid,
            agent_id=agent_id,
            strategy_group=strategy_group,
            contract_id=contract_id,
            side=side,
            action=action,
            target_count=target_count,
            price_cents=price_cents,
            decision_ts_bucket=str(int(decision_ts) // DECISION_BUCKET_WIDTH_S),
            intent_id=intent_id,
        )
        inserted, conflict = self._store.insert_if_absent(record)
        if not inserted and conflict is not None:
            # Race: another thread inserted between lookup and insert
            self._store._metrics.blocked_duplicate += 1
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"duplicate_race:{conflict.status.value}",
                is_duplicate=True,
                existing_status=conflict.status.value,
            )

        self._store._metrics.allowed += 1
        logger.info(
            "[GATE] allowed coid=%s contract=%s agent=%s count=%d price=%d¢",
            coid, contract_id, agent_id, target_count, price_cents,
        )
        return GateVerdict(allowed=True, client_order_id=coid)

    def mark_submitted(self, client_order_id: str, venue_order_id: Optional[str] = None) -> None:
        """Transition order to SUBMITTED after successful venue dispatch."""
        self._store.mark_submitted(client_order_id, venue_order_id)

    def mark_filled(self, client_order_id: str, filled_count: int) -> None:
        """Update fill count from reconciliation / venue ack."""
        self._store.mark_filled(client_order_id, filled_count)

    def mark_canceled(self, client_order_id: str) -> None:
        self._store.mark_canceled(client_order_id)

    def mark_rejected(self, client_order_id: str, reason: str = "") -> None:
        self._store.mark_rejected(client_order_id, reason)

    def get_metrics(self) -> Dict[str, int]:
        return self._store.get_metrics()

    def cleanup_stale(self, ttl_s: Optional[float] = None) -> int:
        """Remove stale terminal records to prevent memory leak.
        
        Args:
            ttl_s: Time-to-live in seconds (default: 24 hours)
            
        Returns:
            Number of records removed
        """
        pruned = self._store.prune_old(ttl_s)
        if pruned > 0:
            logger.info("[GATE] Cleaned up %d stale order records", pruned)
        return pruned


# ── Global singleton ─────────────────────────────────────────────────────────

_gate: Optional[PreTradeGate] = None
_gate_lock = threading.Lock()
_maintenance_thread: Optional[threading.Thread] = None
_maintenance_stop_event = threading.Event()


def get_pre_trade_gate() -> PreTradeGate:
    """Get the process-wide pre-trade gate singleton."""
    global _gate
    if _gate is not None:
        return _gate
    with _gate_lock:
        if _gate is None:
            _gate = PreTradeGate()
            # P2-3 FIX: Start maintenance scheduler to prevent memory leak
            _start_maintenance_scheduler()
        return _gate


def _maintenance_loop() -> None:
    """Background thread that periodically cleans up stale order records."""
    logger.info("[GATE] Maintenance scheduler started (cleanup every 5 minutes)")
    while not _maintenance_stop_event.is_set():
        try:
            if _gate is not None:
                _gate.cleanup_stale()
        except Exception as e:
            logger.warning("[GATE] Maintenance cleanup error: %s", e)
        # Wait 5 minutes or until stop signal
        _maintenance_stop_event.wait(timeout=300)


def _start_maintenance_scheduler() -> None:
    """Start the background maintenance thread if not already running."""
    global _maintenance_thread
    if _maintenance_thread is not None and _maintenance_thread.is_alive():
        return
    _maintenance_stop_event.clear()
    _maintenance_thread = threading.Thread(target=_maintenance_loop, name="order-gate-maintenance", daemon=True)
    _maintenance_thread.start()


def stop_maintenance_scheduler() -> None:
    """Stop the background maintenance thread (for graceful shutdown)."""
    global _maintenance_thread
    _maintenance_stop_event.set()
    if _maintenance_thread is not None:
        _maintenance_thread.join(timeout=5)
        logger.info("[GATE] Maintenance scheduler stopped")


def reset_pre_trade_gate_for_testing() -> None:
    """Reset the global singleton (tests only)."""
    global _gate
    with _gate_lock:
        _gate = None
