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

import asyncio
import hashlib
import os
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_gate")

# SEV-1 FIX: Track envelope failure count for alerting
_envelope_failure_count = 0
_envelope_failure_window_start = _time.time()
_envelope_failure_lock = threading.Lock()


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
    created_at: float = field(default_factory=_time.time)
    updated_at: float = field(default_factory=_time.time)
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
    blocked_invalid_transition: int = 0  # PHASE1-DUP-5: Invalid state transitions
    blocked_price_guard: int = 0  # Price guard rejections (deep OTM or high price)
    blocked_price_repeat: int = 0  # CRITICAL: Block repeat price execution (same ticker+side+price)
    blocked_window_limit: int = 0  # CRITICAL: Block slot-based risk limit violations (fixed $1 exposure cap)
    blocked_window_limit_entry: int = 0  # Track entry order slot limit blocks
    blocked_window_limit_exit: int = 0  # Track exit order slot limit blocks
    blocked_exit_policy: int = 0  # CRITICAL: Block orders without exit policy metadata (2026-07-06)
    blocked_exit_policy_invalid: int = 0  # CRITICAL: Block orders with invalid exit policy values (2026-07-08)
    blocked_sequential_trading: int = 0  # CRITICAL: Block new entries when positions exist (2026-07-08)
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


def _is_15m_crypto_agent(agent_id: str) -> bool:
    """Detect 15m crypto agents for shorter bucket width (5s cadence)."""
    if not agent_id:
        return False
    aid = agent_id.lower()
    return aid.endswith("_15m") or aid in ("btc_15m", "eth_15m", "sol_15m", "xrp_15m", "doge_15m")


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
    # Auto-detect market makers and 15m crypto agents for shorter bucket width
    # 15m crypto agents run at 5s cadence, need 5s bucket to avoid duplicate rejection
    if bucket_width_s is None:
        if _is_market_maker_agent(agent_id):
            bucket_width_s = MM_DECISION_BUCKET_WIDTH_S  # 5s for MMs
        elif _is_15m_crypto_agent(agent_id):
            bucket_width_s = 5  # 5s for 15m crypto agents (matches cadence)
        else:
            bucket_width_s = DECISION_BUCKET_WIDTH_S  # 60s default

    bucket = int(decision_ts) // bucket_width_s
    preimage = f"{agent_id}|{strategy_group}|{contract_id}|{side}|{target_qty}|{price_cents}|{bucket}"
    digest = hashlib.sha256(preimage.encode()).hexdigest()[:32]
    return f"merid-{digest}"


# ── Idempotent Order Store ───────────────────────────────────────────────────

class IdempotentOrderStore:
    """In-memory idempotent order store keyed by ``client_order_id``.

    Thread-safe and async-safe.  Entries are pruned after a configurable TTL so the store
    doesn't grow unbounded.
    
    PHASE1-DUP-4: Added asyncio.Lock for async dedup to prevent concurrent duplicate
    submissions in async contexts (e.g., route_order_async).
    """

    # Records older than this are eligible for pruning (24 hours).
    PRUNE_TTL_S: float = 86400.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._async_lock: Optional[asyncio.Lock] = None  # PHASE1-DUP-4: Async lock for concurrent async submissions
        self._orders: Dict[str, OrderRecord] = {}
        self._metrics = GateMetrics()
        # CRITICAL: Track price execution history to prevent repeat price execution
        # Key: (contract_id, side, price_cents), Value: timestamp of last execution
        self._price_execution_history: Dict[Tuple[str, str, int], float] = {}
        # Time window for price repeat check
        # CRITICAL FIX (2026-07-12): Reduced from 900s (15 min) to 60s (1 min)
        # The 15-minute window was blocking legitimate re-executions at the same price
        # after market moves and returns. 60s allows for short-term duplicate prevention
        # while enabling legitimate trading activity in 15m cycles
        self._price_repeat_window_s: float = 60.0

    def _ensure_async_lock(self) -> asyncio.Lock:
        """Lazy-initialize the async lock in the current event loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

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

    async def async_insert_if_absent(self, record: OrderRecord) -> Tuple[bool, Optional[OrderRecord]]:
        """Async version of insert_if_absent using asyncio.Lock.

        PHASE1-DUP-4: Prevents concurrent duplicate submissions in async contexts
        (e.g., route_order_async) by using an async lock instead of the threading lock.

        Returns:
            (inserted, existing_or_none) — ``inserted`` is True if the record
            was stored; False if a record already existed (returned as second
            element).
        """
        async with self._ensure_async_lock():
            existing = self._orders.get(record.client_order_id)
            if existing is not None:
                return False, existing
            self._orders[record.client_order_id] = record
            return True, None

    # ── Status transitions ───────────────────────────────────────────────

    def _check_transition_allowed(
        self,
        rec: OrderRecord,
        new_status: OrderStatus,
        method_name: str
    ) -> bool:
        """PHASE1-DUP-5: Validate order state transition invariants.
        
        Enforces:
        1. No status regressions (e.g., FILLED → SUBMITTED blocked)
        2. Terminal state immutability (no transitions from FILLED/CANCELED/REJECTED/EXPIRED)
        
        Returns True if transition is allowed, False otherwise.
        Logs violations for monitoring.
        """
        # Terminal state immutability: cannot transition from terminal states
        if rec.status in _TERMINAL_STATES:
            logger.error(
                "[ORDER-STATE-INVARIANT] Terminal state transition blocked | "
                "coid=%s current=%s attempted=%s method=%s | "
                "Terminal states are immutable",
                rec.client_order_id, rec.status.value, new_status.value, method_name
            )
            self._metrics.blocked_invalid_transition += 1
            return False
        
        # No status regressions: block backward transitions
        # Define valid forward transitions
        valid_transitions = {
            OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.LIVE, OrderStatus.REJECTED, OrderStatus.CANCELED},
            OrderStatus.SUBMITTED: {OrderStatus.LIVE, OrderStatus.REJECTED, OrderStatus.CANCELED},
            OrderStatus.LIVE: {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELED},
            OrderStatus.PARTIAL: {OrderStatus.FILLED, OrderStatus.CANCELED},
        }
        
        if rec.status in valid_transitions and new_status not in valid_transitions[rec.status]:
            logger.error(
                "[ORDER-STATE-INVARIANT] Invalid status transition blocked | "
                "coid=%s current=%s attempted=%s method=%s | "
                "Valid transitions from %s: %s",
                rec.client_order_id, rec.status.value, new_status.value, method_name,
                rec.status.value, [s.value for s in valid_transitions[rec.status]]
            )
            self._metrics.blocked_invalid_transition += 1
            return False
        
        return True

    def mark_submitted(self, client_order_id: str, venue_order_id: Optional[str] = None) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec:
                # PHASE1-DUP-5: Check transition invariants
                if not self._check_transition_allowed(rec, OrderStatus.SUBMITTED, "mark_submitted"):
                    return
                if rec.status in (OrderStatus.PENDING,):
                    rec.status = OrderStatus.SUBMITTED
                    rec.venue_order_id = venue_order_id
                    rec.updated_at = _time.time()
                    self._metrics.submitted += 1

    def mark_live(self, client_order_id: str, venue_order_id: Optional[str] = None) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec:
                # PHASE1-DUP-5: Check transition invariants
                if not self._check_transition_allowed(rec, OrderStatus.LIVE, "mark_live"):
                    return
                if rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                    rec.status = OrderStatus.LIVE
                    if venue_order_id:
                        rec.venue_order_id = venue_order_id
                    rec.updated_at = _time.time()

    def mark_filled(self, client_order_id: str, filled_count: int) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec:
                # PHASE1-DUP-5: Check transition invariants (allow PARTIAL → FILLED)
                target_status = OrderStatus.FILLED if filled_count >= rec.target_count else OrderStatus.PARTIAL
                if not self._check_transition_allowed(rec, target_status, "mark_filled"):
                    return
                if rec.status not in _TERMINAL_STATES:
                    rec.filled_count = filled_count
                    if filled_count >= rec.target_count:
                        rec.status = OrderStatus.FILLED
                    else:
                        rec.status = OrderStatus.PARTIAL
                    rec.updated_at = _time.time()
                    self._metrics.filled += 1

                    # FIX 2: Window exposure recording centralized in position_cache.on_fill()
                    # Removed from here to prevent duplicate recording and ensure consistency
                    # across all fill paths (WebSocket and HTTP). All fills now go through
                    # position_cache.on_fill() which records window exposure once.

    def mark_canceled(self, client_order_id: str) -> None:
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec:
                # PHASE1-DUP-5: Check transition invariants
                if not self._check_transition_allowed(rec, OrderStatus.CANCELED, "mark_canceled"):
                    return
                if rec.status not in _TERMINAL_STATES:
                    rec.status = OrderStatus.CANCELED
                    rec.updated_at = _time.time()
                    self._metrics.canceled += 1
                    
                    # CRITICAL FIX (2026-07-08): Release resting order exposure on cancel
                    # Resting exposure was recorded at placement time in check()
                    # When order is canceled, we must release the resting exposure
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        if envelope:
                            order_notional_usd = (rec.target_count * rec.price_cents) / 100.0
                            envelope.release_resting_order_exposure(
                                agent_id=rec.agent_id,
                                order_notional_usd=order_notional_usd
                            )
                            logger.info(
                                "[order-gate-WINDOW-RELEASE] Released resting exposure on cancel: coid=%s agent=%s notional=$%.2f",
                                client_order_id[:16], rec.agent_id, order_notional_usd
                            )
                    except Exception as e:
                        logger.warning("[order-gate-WINDOW-RELEASE] Failed to release resting exposure on cancel: %s", e)

    def mark_rejected(self, client_order_id: str, reason: str = "") -> None:
        # CRITICAL FIX (2026-07-07): Window exposure no longer recorded optimistically
        # No refund needed since exposure is only recorded on fills
        # CRITICAL FIX (2026-07-08): Release resting order exposure on reject
        # Resting exposure was recorded at placement time in check()
        # When order is rejected, we must release the resting exposure
        with self._lock:
            rec = self._orders.get(client_order_id)
            if rec:
                # PHASE1-DUP-5: Check transition invariants
                if not self._check_transition_allowed(rec, OrderStatus.REJECTED, "mark_rejected"):
                    return
                if rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
                    rec.status = OrderStatus.REJECTED
                    rec.updated_at = _time.time()
                    
                    # Release resting exposure on reject
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        if envelope:
                            order_notional_usd = (rec.target_count * rec.price_cents) / 100.0
                            envelope.release_resting_order_exposure(
                                agent_id=rec.agent_id,
                                order_notional_usd=order_notional_usd
                            )
                            logger.info(
                                "[order-gate-WINDOW-RELEASE] Released resting exposure on reject: coid=%s agent=%s notional=$%.2f reason=%s",
                                client_order_id[:16], rec.agent_id, order_notional_usd, reason
                            )
                    except Exception as e:
                        logger.warning("[order-gate-WINDOW-RELEASE] Failed to release resting exposure on reject: %s", e)

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

    def find_resting_duplicate(
        self,
        contract_id: str,
        side: str,
        action: str,
        price_cents: int,
        target_count: int,
        exclude_coid: Optional[str] = None,
    ) -> Optional[OrderRecord]:
        """Find an identical resting order (same contract, side, action, price, count).
        
        This prevents duplicate resting orders even when they have different
        client_order_ids due to different 5-second time buckets.
        
        CRITICAL FIX: Exclude stale PENDING orders from duplicate check to prevent
        blocking new orders when old orders failed to transition properly.
        PENDING orders older than 30 seconds are considered stale and ignored.
        
        CRITICAL FIX 2026-07-09: Added target_count to duplicate detection to prevent
        multiple orders with different quantities from bypassing duplicate checks.
        
        Args:
            contract_id: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            price_cents: Limit price in cents
            target_count: Number of contracts requested
            exclude_coid: Optional client_order_id to exclude (current order)
            
        Returns:
            OrderRecord if duplicate found, None otherwise
        """
        with self._lock:
            now = _time.time()
            for rec in self._orders.values():
                # Skip if this is the current order we're checking
                if exclude_coid and rec.client_order_id == exclude_coid:
                    continue
                # Check for identical resting order (including count)
                if (
                    rec.contract_id == contract_id
                    and rec.side == side
                    and rec.action == action
                    and rec.price_cents == price_cents
                    and rec.target_count == target_count  # CRITICAL: Check count to prevent multi-contract bypass
                    and rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)
                ):
                    # CRITICAL FIX: Skip stale PENDING orders (older than 5 seconds)
                    # These are likely failed orders that never transitioned properly
                    # CRITICAL FIX 2026-07-10: Reduced threshold from 30s to 5s to match time bucket width
                    # This prevents stale PENDING orders from blocking new orders when the 5s bucket changes
                    if rec.status == OrderStatus.PENDING:
                        age_seconds = now - rec.updated_at
                        if age_seconds > 5:
                            logger.debug(
                                "[find_resting_duplicate] Skipping stale PENDING order coid=%s age=%.1fs (threshold=5s)",
                                rec.client_order_id, age_seconds
                            )
                            continue
                    return rec
            return None

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

    def check_price_repeat(
        self,
        contract_id: str,
        side: str,
        price_cents: int,
        allow_lower_price: bool = True,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """Check if this (contract, side, price) was executed recently.
        
        CRITICAL FIX: Prevent agents from executing the same price multiple times.
        Forces scaling in at lower prices - if same price was executed before,
        reject unless new price is strictly lower (cheaper entry).
        
        Args:
            contract_id: Market ticker
            side: "yes" or "no"
            price_cents: Limit price in cents
            allow_lower_price: If True, allow execution at lower price (scaling in)
            
        Returns:
            Tuple of (allowed, reason, last_price_cents)
            - allowed: True if price is allowed, False if blocked
            - reason: Reason string if blocked, None otherwise
            - last_price_cents: Last executed price for this (contract, side), None if none
        """
        with self._lock:
            now = _time.time()
            price_key = (contract_id, side, price_cents)
            
            # Check if this exact price was executed recently
            if price_key in self._price_execution_history:
                last_execution_ts = self._price_execution_history[price_key]
                age_seconds = now - last_execution_ts
                
                # If within the 15-minute window, block repeat execution
                if age_seconds < self._price_repeat_window_s:
                    self._metrics.blocked_price_repeat += 1
                    logger.warning(
                        "[PRICE-REPEAT-BLOCK] contract=%s side=%s price=%dc executed %.1fs ago (window=%.1fs) - BLOCKED",
                        contract_id, side, price_cents, age_seconds, self._price_repeat_window_s
                    )
                    return False, f"price_repeat:executed_{age_seconds:.0f}s_ago", price_cents
            
            # Check if any price for this (contract, side) was executed recently
            # to enforce scaling in at lower prices (cheaper entry)
            if allow_lower_price:
                for (hist_contract, hist_side, hist_price), hist_ts in self._price_execution_history.items():
                    if hist_contract == contract_id and hist_side == side:
                        age_seconds = now - hist_ts
                        if age_seconds < self._price_repeat_window_s:
                            # Only allow strictly lower prices (scale in at cheaper price)
                            # This forces agents to get better entry prices
                            if price_cents >= hist_price:
                                self._metrics.blocked_price_repeat += 1
                                logger.warning(
                                    "[PRICE-SCALE-IN-BLOCK] contract=%s side=%s price=%dc >= last_price=%dc (window=%.1fs) - BLOCKED (must scale in at lower price)",
                                    contract_id, side, price_cents, hist_price, self._price_repeat_window_s
                                )
                                return False, f"price_scale_in:price_{price_cents}c >= last_{hist_price}c", hist_price
            
            return True, None, None

    def record_price_execution(
        self,
        contract_id: str,
        side: str,
        price_cents: int,
    ) -> None:
        """Record that this (contract, side, price) was executed.
        
        This is called after successful order execution to update the
        price execution history for future repeat checks.
        
        Args:
            contract_id: Market ticker
            side: "yes" or "no"
            price_cents: Executed price in cents
        """
        with self._lock:
            price_key = (contract_id, side, price_cents)
            self._price_execution_history[price_key] = _time.time()
            logger.debug(
                "[PRICE-EXECUTION-RECORDED] contract=%s side=%s price=%dc",
                contract_id, side, price_cents
            )

    # ── Duplicate Race Detection ─────────────────────────────────────────
    # NOTE: This method is UNUSED LEGACY CODE. It has zero call sites in the codebase.
    # Actual duplicate protection is handled via client_order_id in PreTradeGate.check()
    # which uses IdempotentOrderStore.lookup() to block replays of the exact same intent.
    # This method is kept for reference but should not be used.

    def check_duplicate_race(
        self,
        contract_id: str,
        side: str,
        strategy_group: str,
        race_window_seconds: float = 2.0,
    ) -> tuple[bool, str]:
        """Prevent same-asset duplicate orders within time window.
        
        DEPRECATED: This method is unused. Duplicate protection is handled via
        client_order_id in PreTradeGate.check() using IdempotentOrderStore.
        
        MICRO-SCALPING FIX: Allow multiple orders IF they're on different sides
        (YES vs NO) or different assets. Block only true duplicates within
        the race window.
        
        Args:
            contract_id: Market ticker
            side: "yes" or "no"
            strategy_group: Logical strategy group
            race_window_seconds: Time window for duplicate detection (default 2s)
            
        Returns:
            Tuple of (allowed, reason). allowed=True if no duplicate race detected.
        """
        with self._lock:
            now = _time.time()
            
            for rec in self._orders.values():
                # Check for pending/submitted orders on same contract+side+strategy
                if (
                    rec.contract_id == contract_id
                    and rec.side == side
                    and rec.strategy_group == strategy_group
                    and rec.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)
                ):
                    time_since = now - rec.created_at
                    if time_since < race_window_seconds:
                        return False, (
                            f"duplicate_race:rejected — {contract_id}:{side} "
                            f"already has {rec.status.value} order within {time_since:.1f}s "
                            f"(window: {race_window_seconds}s)"
                        )
            
            return True, "approved"

    # ── Maintenance ──────────────────────────────────────────────────────

    def prune_old(self, ttl_s: Optional[float] = None) -> int:
        """Remove terminal records older than *ttl_s*."""
        cutoff = _time.time() - (ttl_s or self.PRUNE_TTL_S)
        with self._lock:
            stale = [
                k for k, v in self._orders.items()
                if v.status in _TERMINAL_STATES and v.updated_at < cutoff
            ]
            for k in stale:
                del self._orders[k]
        return len(stale)

    # Non-terminal TTLs for the orphan sweep.  A PENDING record that never
    # transitions to SUBMITTED is almost always the result of an upstream
    # crash between ``PreTradeGate.check`` and ``route_order_async`` (or an
    # unhandled exception inside the router *before* ``mark_submitted``).
    # SUBMITTED without an ack past the longer TTL is a zombie that will
    # later be resolved by the reconciler — we only mark it so operators can
    # see it in the gate metrics.
    # 2026 FIX: Reduced ORPHAN_PENDING_TTL_S from 300s to 15s for 15m crypto trading
    # 15m markets move fast - 5 minutes is too long for orphan cleanup
    ORPHAN_PENDING_TTL_S: float = 15.0        # 15 seconds (was 5 minutes - too slow for 15m crypto)
    ORPHAN_SUBMITTED_TTL_S: float = 60.0      # 1 minute (was 1 hour - too slow for 15m crypto)

    def prune_stale_pending(
        self,
        pending_ttl_s: Optional[float] = None,
        submitted_ttl_s: Optional[float] = None,
    ) -> Dict[str, int]:
        """Mark orphaned non-terminal records as REJECTED so they can be pruned.

        This is the GC complement to :meth:`prune_old`.  Without it, a PENDING
        record produced by an upstream caller that crashes *before* calling
        ``route_order_async`` leaks forever — ``prune_old`` never touches it
        (by design: in-flight orders must not be swept) but neither does
        anything else in the system.

        The transition is lossy-but-safe: the record is marked REJECTED with
        reason ``"orphaned_pending"`` / ``"orphaned_submitted"``, its
        ``updated_at`` is bumped, and the next ``prune_old`` pass will
        eventually delete it once the terminal TTL elapses.  This keeps the
        PENDING slot free for a legitimate retry of the same logical order.

        Returns a small dict of counts for observability:
        ``{"orphaned_pending": N, "orphaned_submitted": M}``.
        """
        pending_cutoff = _time.time() - (
            pending_ttl_s if pending_ttl_s is not None else self.ORPHAN_PENDING_TTL_S
        )
        submitted_cutoff = _time.time() - (
            submitted_ttl_s if submitted_ttl_s is not None else self.ORPHAN_SUBMITTED_TTL_S
        )
        result = {"orphaned_pending": 0, "orphaned_submitted": 0}
        now = _time.time()
        with self._lock:
            for rec in self._orders.values():
                if rec.status == OrderStatus.PENDING and rec.updated_at < pending_cutoff:
                    rec.status = OrderStatus.REJECTED
                    rec.updated_at = now
                    result["orphaned_pending"] += 1
                elif rec.status == OrderStatus.SUBMITTED and rec.updated_at < submitted_cutoff:
                    rec.status = OrderStatus.REJECTED
                    rec.updated_at = now
                    result["orphaned_submitted"] += 1
        return result

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
        # CRITICAL FIX: Exit policy metadata parameters (2026-07-06)
        exit_policy_id: Optional[str] = None,
        window_resolution_id: Optional[str] = None,
        risk_tier: Optional[str] = None,
        max_hold_seconds: Optional[int] = None,
        # CRITICAL FIX: Entry/exit direction classification (2026-07-20)
        entry_or_exit: Optional[str] = None,
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
            exit_policy_id:  Optional exit policy ID for crypto 15m markets.
            window_resolution_id: Optional window resolution ID for crypto 15m markets.
            risk_tier:       Optional risk tier for crypto 15m markets.
            max_hold_seconds: Optional max hold seconds for crypto 15m markets.
            entry_or_exit:   Optional "entry" or "exit" direction classification.

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
            # PHASE1-DUP-9: Alert for duplicate order attempts (warning level + metric)
            logger.warning(
                "[GATE-ALERT] duplicate_order_attempt_blocked coid=%s status=%s contract=%s agent=%s "
                "(metric: blocked_duplicate=%d)",
                coid, existing.status.value, contract_id, agent_id,
                self._store._metrics.blocked_duplicate,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"duplicate:{existing.status.value}",
                is_duplicate=True,
                existing_status=existing.status.value,
            )

        # 3b. Resting order deduplication (across time buckets)
        # Prevent identical resting orders even with different client_order_ids
        # This catches duplicates when the 5s time bucket changes between submissions
        resting_duplicate = self._store.find_resting_duplicate(
            contract_id=contract_id,
            side=side,
            action=action,
            price_cents=price_cents,
            target_count=target_count,  # CRITICAL: Include count to prevent multi-contract bypass
            exclude_coid=coid,  # Exclude the current order we just checked
        )
        if resting_duplicate is not None:
            self._store._metrics.blocked_duplicate += 1
            logger.warning(
                "[GATE-ALERT] resting_order_duplicate_blocked contract=%s side=%s action=%s price=%dc "
                "existing_coid=%s new_coid=%s agent=%s (metric: blocked_duplicate=%d)",
                contract_id, side, action, price_cents, resting_duplicate.client_order_id, coid, agent_id,
                self._store._metrics.blocked_duplicate,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"resting_duplicate:{resting_duplicate.client_order_id}",
                is_duplicate=True,
                existing_status=resting_duplicate.status.value,
            )

        # 3c. CRITICAL: Price repeat check - prevent executing same price multiple times
        # Forces scaling in at lower prices - if same price was executed before, reject
        # unless new price is lower (for buy) or higher (for sell)
        price_allowed, price_reason, last_price = self._store.check_price_repeat(
            contract_id=contract_id,
            side=side,
            price_cents=price_cents,
            allow_lower_price=True,  # Allow scaling in at lower prices
        )
        if not price_allowed:
            self._store._metrics.blocked_price_repeat += 1
            logger.warning(
                "[GATE-ALERT] price_repeat_blocked contract=%s side=%s price=%dc reason=%s last_price=%s agent=%s "
                "(metric: blocked_price_repeat=%d)",
                contract_id, side, price_cents, price_reason, last_price, agent_id,
                self._store._metrics.blocked_price_repeat,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"price_repeat:{price_reason}",
            )

        # 3c.5. CRITICAL FIX: Position existence validation for exit orders (2026-07-08)
        # Prevents exit orders from executing as new entry trades when no position exists
        # This is the root cause of agents placing multiple orders at different prices
        # Exit orders (SELL) must have an existing position to close
        # MOVED BEFORE window limit check for logical ordering and testability
        # CRITICAL FIX (2026-07-13): DISABLED position check in gate.check()
        # The gate.check() function doesn't have access to the source field, which is required
        # to properly detect exit orders using _is_exit_order. Without source info, we can't
        # distinguish between true exit orders (take_profit, stop_loss) and entry orders.
        # Position validation is now handled in order_router where source is available.
        # This prevents false rejections of entry orders that have exit_policy_id set.

        # 3d. CRITICAL FIX: 2026-07-09 - Updated sequential trading to use slot allocator
        # OLD: No new entries until ALL positions exit (too restrictive)
        # NEW: Allow new entries when slot allocator has available exposure
        # This enables sequential trading with early exits: close profitable positions, free up slots, enter new positions
        # Only applies to entry orders, not exit orders
        # CRITICAL FIX (2026-07-13): DISABLED sequential trading check in gate.check()
        # The gate.check() function doesn't have access to the source field, which is required
        # to properly detect exit orders using _is_exit_order. Without source info, we can't
        # distinguish between true exit orders and entry orders. Sequential trading enforcement
        # is now handled in order_router where source is available.
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile()
            if profile and hasattr(profile, 'risk_policy_sequential_trading') and profile.risk_policy_sequential_trading:
                # DISABLED: Cannot detect exit orders without source field
                # Sequential trading check moved to order_router
                pass
        except Exception as e:
            logger.warning("[GATE] Sequential trading check failed: %s", e)
            # Continue with other checks if validation fails (non-critical)

        # 3e. 2026-07-08 UPDATE: Window-based risk limit check DISABLED in favor of fixed $1 exposure model
        # Percentage-based window limits (3% per agent, 5% total venue) DISABLED
        # Risk is now enforced via:
        # - Sequential trading (blocks new entries until positions exit)
        # - Slot-based position management (sum of contract prices ≤ $1)
        # - Fixed $1 exposure cap (risk_policy.fixed_exposure_cap_usd: 1.00)
        # Window-based limits were redundant with sequential trading and slot-based model

        # 3.7. CRITICAL FIX: Exit policy validation for crypto 15m markets (2026-07-06)
        # Enforces "no trade without exit" invariant by requiring exit policy metadata
        # This ensures all trades have attached, valid, and enforceable exit policies
        try:
            from merid.event_venues.kalshi.order_router import _is_crypto_15m_market
            
            if _is_crypto_15m_market(contract_id):
                if action == "buy":  # Entry order requires full risk contract linkage
                    missing_fields = []
                    invalid_fields = []
                    
                    if not exit_policy_id:
                        missing_fields.append("exit_policy_id")
                    if not window_resolution_id:
                        missing_fields.append("window_resolution_id")
                    if not risk_tier:
                        missing_fields.append("risk_tier")
                    if not max_hold_seconds:
                        missing_fields.append("max_hold_seconds")
                    
                    # CRITICAL FIX (2026-07-08): Validate exit policy metadata values
                    # Extract TP/SL from metadata if available (stored in intent metadata)
                    tp_price_cents = None
                    sl_price_cents = None
                    entry_price_cents = price_cents
                    
                    # Check if metadata dict is provided and contains TP/SL
                    # Note: exit_policy_metadata is not currently passed to check(), but we can
                    # add it as a parameter in the future. For now, we validate what we can.
                    # If metadata is added later, uncomment the following:
                    # if isinstance(exit_policy_metadata, dict):
                    #     tp_price_cents = exit_policy_metadata.get("tp_price_cents")
                    #     sl_price_cents = exit_policy_metadata.get("sl_price_cents")
                    
                    # Validate max_hold_seconds is reasonable
                    if max_hold_seconds and max_hold_seconds < 60:
                        invalid_fields.append(f"max_hold_seconds_invalid:{max_hold_seconds}s < 60s minimum")
                    if max_hold_seconds and max_hold_seconds > 3600:
                        invalid_fields.append(f"max_hold_seconds_invalid:{max_hold_seconds}s > 3600s maximum")
                    
                    # Validate TP price if provided (future enhancement when metadata is passed)
                    if tp_price_cents is not None:
                        if tp_price_cents <= entry_price_cents:
                            invalid_fields.append(f"tp_price_cents_invalid:{tp_price_cents}c <= entry_{entry_price_cents}c")
                        if tp_price_cents > 99:
                            invalid_fields.append(f"tp_price_cents_invalid:{tp_price_cents}c > 99c")
                    
                    # Validate SL price if provided (future enhancement when metadata is passed)
                    if sl_price_cents is not None:
                        if sl_price_cents >= entry_price_cents:
                            invalid_fields.append(f"sl_price_cents_invalid:{sl_price_cents}c >= entry_{entry_price_cents}c")
                        if sl_price_cents < 1:
                            invalid_fields.append(f"sl_price_cents_invalid:{sl_price_cents}c < 1c")
                    
                    if missing_fields:
                        self._store._metrics.blocked_exit_policy += 1
                        logger.error(
                            "[GATE-ALERT] exit_policy_metadata_missing contract=%s side=%s agent=%s missing_fields=%s (metric: blocked_exit_policy=%d)",
                            contract_id, side, agent_id, ", ".join(missing_fields),
                            self._store._metrics.blocked_exit_policy,
                        )
                        return GateVerdict(
                            allowed=False,
                            client_order_id=coid,
                            reason=f"exit_policy_metadata_missing:{', '.join(missing_fields)}",
                        )
                    
                    if invalid_fields:
                        self._store._metrics.blocked_exit_policy_invalid += 1
                        logger.error(
                            "[GATE-ALERT] exit_policy_metadata_invalid contract=%s side=%s agent=%s invalid_fields=%s (metric: blocked_exit_policy_invalid=%d)",
                            contract_id, side, agent_id, ", ".join(invalid_fields),
                            self._store._metrics.blocked_exit_policy_invalid,
                        )
                        return GateVerdict(
                            allowed=False,
                            client_order_id=coid,
                            reason=f"exit_policy_metadata_invalid:{', '.join(invalid_fields)}",
                        )
                else:  # Exit order requires exit_policy_id for tracking
                    if not exit_policy_id:
                        self._store._metrics.blocked_exit_policy += 1
                        logger.error(
                            "[GATE-ALERT] exit_policy_id_missing contract=%s side=%s agent=%s (metric: blocked_exit_policy=%d)",
                            contract_id, side, agent_id,
                            self._store._metrics.blocked_exit_policy,
                        )
                        return GateVerdict(
                            allowed=False,
                            client_order_id=coid,
                            reason="exit_policy_id_missing",
                        )
        except Exception as e:
            logger.warning("[GATE] Exit policy validation check failed: %s", e)
            # Continue with other checks if validation fails (non-critical)

        # 3.5. Price guard: prevent deep OTM longshots and high-price low-profit trades (critical guardrail)
        # Load min_contract_price_cents from profile with fallback to 10 cents
        min_price_cents = 10  # CRITICAL FIX: Default fallback 10c to match profile (was 15c)
        max_price_cents = 75  # CRITICAL FIX: Default fallback 75c to match profile (was 55c)
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_contract_price_cents'):
                max_price_cents = profile_adapter.profile.guardrails_max_contract_price_cents
        except Exception as e:
            logger.debug("[GATE] Failed to load contract price limits from profile: %s, using defaults", e)
        
        # For both YES and NO contracts, check the price directly
        # - Low YES price (e.g., 5¢) = deep OTM longshot (betting on low-probability event)
        # - Low NO price (e.g., 5¢) = deep OTM longshot (betting against high-probability event)
        if price_cents < min_price_cents:
            self._store._metrics.blocked_price_guard += 1
            logger.warning(
                "[GATE-ALERT] deep_otm_longshot_blocked coid=%s contract=%s side=%s price=%dc < %dc threshold (deep OTM longshot rejected)",
                coid, contract_id, side, price_cents, min_price_cents,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"deep_otm_longshot:price={price_cents}c < {min_price_cents}c threshold",
            )
        
        # - High YES price (e.g., 85¢) = low-profit trade (risk more than profit potential)
        # - High NO price (e.g., 85¢) = low-profit trade (risk more than profit potential)
        # CRITICAL FIX: Skip this check for exit orders (2026-07-20)
        # Exit orders need to close positions even at high prices to realize PnL
        if entry_or_exit != "exit" and price_cents > max_price_cents:
            self._store._metrics.blocked_price_guard += 1
            logger.warning(
                "[GATE-ALERT] high_price_low_profit_blocked coid=%s contract=%s side=%s price=%dc > %dc threshold "
                "(poor risk/reward rejected) entry_or_exit=%s",
                coid, contract_id, side, price_cents, max_price_cents, entry_or_exit or "entry",
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"high_price_low_profit:price={price_cents}c > {max_price_cents}c threshold",
            )

        # 4. Fill-awareness: is the target already satisfied?
        # CRITICAL FIX (2026-07-20): Apply to both buy and sell actions
        # Exit orders (sell) should also check if already satisfied to prevent duplicate exits
        already_filled = (
            existing_filled
            if existing_filled is not None
            else self._store.filled_count_for_contract(contract_id, side, strategy_group)
        )
        if already_filled >= target_count:
            self._store._metrics.blocked_already_satisfied += 1
            logger.info(
                "[GATE] already_satisfied coid=%s contract=%s filled=%d target=%d action=%s",
                coid, contract_id, already_filled, target_count, action,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"already_satisfied:filled={already_filled}>=target={target_count}",
            )

        # 4b. CRYPTO15M Timeframe Budget + Expiry Cap Check (hard gate)
        # NOTE: This gate is DISABLED for lean 15m mode because the allocator (crypto15mallocator.py)
        # is archived. The priority queue + budget/cooldown + edge thresholds provide the
        # risk envelope instead. Set MERID_DISABLE_CRYPTO15M_GATE=1 to disable.
        # Skip check if env disables it (emergency override for lean stack)
        if os.getenv("MERID_DISABLE_CRYPTO15M_GATE", "").lower() in ("1", "true", "yes"):
            logger.debug("[CRYPTO15M-GATE] Skipped (disabled by MERID_DISABLE_CRYPTO15M_GATE) for %s", contract_id)
        else:
            try:
                from merid.prediction.crypto15mallocator import (
                    is_15m_crypto_ticker,
                    check_timeframe_budget,
                    check_expiry_open_cap,
                    is_increasing_exposure_check,
                    get_crypto15m_allocator,
                )
                
                if is_15m_crypto_ticker(contract_id):
                    # Determine if this increases exposure
                    is_increasing = is_increasing_exposure_check(
                        ticker=contract_id,
                        side=side,
                        requested_contracts=target_count,
                        existing_position_contracts=existing_filled or 0,
                    )
                    
                    # Only check caps for increasing exposure (reductions always allowed)
                    if is_increasing:
                        allocator = get_crypto15m_allocator()
                        phase = allocator.config.rollout_phase
                        
                        # Check timeframe budget
                        tf_allowed, tf_approved, tf_reason = check_timeframe_budget(
                            ticker=contract_id,
                            requested_contracts=target_count,
                            bankroll_equity_usd=0.0,  # Will use default budget
                        )
                        
                        # Check expiry cap
                        expiry_allowed, expiry_approved, expiry_reason = check_expiry_open_cap(
                            ticker=contract_id,
                            requested_contracts=target_count,
                            is_increasing_exposure=True,
                        )
                        
                        # In hard_gate phase, enforce strictly
                        if phase == "hard_gate":
                            if not tf_allowed:
                                self._store._metrics.blocked_risk += 1
                                logger.warning(
                                    "[GATE] [TFBUDGET] BLOCKED hard_gate coid=%s contract=%s "
                                    "reason=timeframe_budget_exhausted agent=%s",
                                    coid, contract_id, agent_id
                                )
                                return GateVerdict(
                                    allowed=False,
                                    client_order_id=coid,
                                    reason="timeframe_budget_exhausted",
                                )
                            
                            if not expiry_allowed:
                                self._store._metrics.blocked_risk += 1
                                logger.warning(
                                    "[GATE] [EXPIRYLIMIT] BLOCKED hard_gate coid=%s contract=%s "
                                    "reason=expiry_limit_exhausted agent=%s",
                                    coid, contract_id, agent_id
                                )
                                return GateVerdict(
                                    allowed=False,
                                    client_order_id=coid,
                                    reason="expiry_limit_exhausted",
                                )
                            
                            # Check if slicing is needed
                            min_approved = min(tf_approved, expiry_approved)
                            if min_approved < target_count:
                                logger.info(
                                    "[GATE] [CRYPTO15M] CAPPED coid=%s contract=%s "
                                    "requested=%d approved=%d (tf=%d, expiry=%d) agent=%s",
                                    coid, contract_id, target_count, min_approved,
                                    tf_approved, expiry_approved, agent_id
                                )
                                # Note: We don't return here; the slicing happens at caller
                        
                        # In soft_gate/dry_run, log but allow
                        elif phase in ("soft_gate", "dry_run"):
                            if not tf_allowed:
                                logger.debug(
                                    "[GATE] [TFBUDGET] would_block phase=%s coid=%s contract=%s agent=%s",
                                    phase, coid, contract_id, agent_id
                                )
                            if not expiry_allowed:
                                logger.debug(
                                    "[GATE] [EXPIRYLIMIT] would_block phase=%s coid=%s contract=%s agent=%s",
                                    phase, coid, contract_id, agent_id
                                )
            except Exception as exc:
                # Fail-closed: block trade if CRYPTO15M check fails
                logger.warning("[GATE] CRYPTO15M check failed (fail-closed): %s - blocking trade", exc)
                return GateVerdict(
                    allowed=False,
                    client_order_id=coid,
                    reason=f"crypto15m_check_failed:{type(exc).__name__}",
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
            # 2026 IDEMPOTENCY STANDARD (Stripe model): a duplicate deterministic
            # client_order_id means this exact logical order is already known. Do NOT
            # reject as an error and do NOT blindly resubmit — return an idempotent
            # verdict carrying the existing order's status so the router can skip the
            # redundant venue call (avoids duplicate API calls / 409 storms).
            self._store._metrics.blocked_duplicate += 1
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"idempotent_duplicate:{conflict.status.value}",
                is_duplicate=True,
                existing_status=conflict.status.value,
            )

        self._store._metrics.allowed += 1
        logger.info(
            "[GATE] allowed coid=%s contract=%s agent=%s count=%d price=%d¢",
            coid, contract_id, agent_id, target_count, price_cents,
        )
        return GateVerdict(allowed=True, client_order_id=coid)

    async def async_check(
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
        """Async version of pre-trade gate check using asyncio.Lock.

        PHASE1-DUP-4: Prevents concurrent duplicate submissions in async contexts
        (e.g., route_order_async) by using async_insert_if_absent with asyncio.Lock.

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
            # PHASE1-DUP-9: Alert for duplicate order attempts (warning level + metric)
            logger.warning(
                "[GATE-ALERT] duplicate_order_attempt_blocked coid=%s status=%s contract=%s agent=%s "
                "(metric: blocked_duplicate=%d)",
                coid, existing.status.value, contract_id, agent_id,
                self._store._metrics.blocked_duplicate,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"duplicate:{existing.status.value}",
                is_duplicate=True,
                existing_status=existing.status.value,
            )

        # 3b. Resting order deduplication (across time buckets)
        # Prevent identical resting orders even with different client_order_ids
        # This catches duplicates when the 5s time bucket changes between submissions
        resting_duplicate = self._store.find_resting_duplicate(
            contract_id=contract_id,
            side=side,
            action=action,
            price_cents=price_cents,
            target_count=target_count,  # CRITICAL: Include count to prevent multi-contract bypass
            exclude_coid=coid,  # Exclude the current order we just checked
        )
        if resting_duplicate is not None:
            self._store._metrics.blocked_duplicate += 1
            logger.warning(
                "[GATE-ALERT] resting_order_duplicate_blocked contract=%s side=%s action=%s price=%dc "
                "existing_coid=%s new_coid=%s agent=%s (metric: blocked_duplicate=%d)",
                contract_id, side, action, price_cents, resting_duplicate.client_order_id, coid, agent_id,
                self._store._metrics.blocked_duplicate,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"resting_duplicate:{resting_duplicate.client_order_id}",
                is_duplicate=True,
                existing_status=resting_duplicate.status.value,
            )

        # 3c. CRITICAL: Price repeat check - prevent executing same price multiple times
        # Forces scaling in at lower prices - if same price was executed before, reject
        # unless new price is lower (for buy) or higher (for sell)
        price_allowed, price_reason, last_price = self._store.check_price_repeat(
            contract_id=contract_id,
            side=side,
            price_cents=price_cents,
            allow_lower_price=True,  # Allow scaling in at lower prices
        )
        if not price_allowed:
            self._store._metrics.blocked_price_repeat += 1
            logger.warning(
                "[GATE-ALERT] price_repeat_blocked contract=%s side=%s price=%dc reason=%s last_price=%s agent=%s "
                "(metric: blocked_price_repeat=%d)",
                contract_id, side, price_cents, price_reason, last_price, agent_id,
                self._store._metrics.blocked_price_repeat,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"price_repeat:{price_reason}",
            )

        # 3.5. Price guard: prevent deep OTM longshots and high-price low-profit trades (critical guardrail)
        # Load min_contract_price_cents from profile with fallback to 10 cents
        min_price_cents = 10  # CRITICAL FIX: Default fallback 10c to match profile (was 15c)
        max_price_cents = 75  # CRITICAL FIX: Default fallback 75c to match profile (was 55c)
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_contract_price_cents'):
                max_price_cents = profile_adapter.profile.guardrails_max_contract_price_cents
        except Exception as e:
            logger.debug("[GATE] Failed to load contract price limits from profile: %s, using defaults", e)
        
        # For both YES and NO contracts, check the price directly
        # - Low YES price (e.g., 5¢) = deep OTM longshot (betting on low-probability event)
        # - Low NO price (e.g., 5¢) = deep OTM longshot (betting against high-probability event)
        if price_cents < min_price_cents:
            self._store._metrics.blocked_price_guard += 1
            logger.warning(
                "[GATE-ALERT] deep_otm_longshot_blocked coid=%s contract=%s side=%s price=%dc < %dc threshold (deep OTM longshot rejected)",
                coid, contract_id, side, price_cents, min_price_cents,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"deep_otm_longshot:price={price_cents}c < {min_price_cents}c threshold",
            )
        
        # - High YES price (e.g., 85¢) = low-profit trade (risk more than profit potential)
        # - High NO price (e.g., 85¢) = low-profit trade (risk more than profit potential)
        # CRITICAL FIX: Skip this check for exit orders (2026-07-20)
        # Exit orders need to close positions even at high prices to realize PnL
        if entry_or_exit != "exit" and price_cents > max_price_cents:
            self._store._metrics.blocked_price_guard += 1
            logger.warning(
                "[GATE-ALERT] high_price_low_profit_blocked coid=%s contract=%s side=%s price=%dc > %dc threshold "
                "(poor risk/reward rejected) entry_or_exit=%s",
                coid, contract_id, side, price_cents, max_price_cents, entry_or_exit or "entry",
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"high_price_low_profit:price={price_cents}c > {max_price_cents}c threshold",
            )

        # 4. Fill-awareness: is the target already satisfied?
        # CRITICAL FIX (2026-07-20): Apply to both buy and sell actions
        # Exit orders (sell) should also check if already satisfied to prevent duplicate exits
        already_filled = (
            existing_filled
            if existing_filled is not None
            else self._store.filled_count_for_contract(contract_id, side, strategy_group)
        )
        if already_filled >= target_count:
            self._store._metrics.blocked_already_satisfied += 1
            logger.info(
                "[GATE] already_satisfied coid=%s contract=%s filled=%d target=%d action=%s",
                coid, contract_id, already_filled, target_count, action,
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"already_satisfied:filled={already_filled}>=target={target_count}",
            )

        # 5. Insert new record (PENDING) using async lock
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
        inserted, conflict = await self._store.async_insert_if_absent(record)
        if not inserted and conflict is not None:
            # 2026 IDEMPOTENCY STANDARD (Stripe model): duplicate deterministic
            # client_order_id → return idempotent verdict with the existing order's
            # status instead of erroring. The router treats is_duplicate as a graceful
            # no-op (the order is already working), avoiding duplicate venue calls.
            self._store._metrics.blocked_duplicate += 1
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason=f"idempotent_duplicate:{conflict.status.value}",
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

    def cleanup_stale(
        self,
        ttl_s: Optional[float] = None,
        pending_ttl_s: Optional[float] = None,
        submitted_ttl_s: Optional[float] = None,
    ) -> Dict[str, int]:
        """Run both the terminal prune and the orphan sweep.

        Two distinct cleanups live under one operator-facing entry point so
        the maintenance scheduler only has to call one method:

        * :meth:`IdempotentOrderStore.prune_old` — deletes terminal records
          (FILLED / REJECTED / CANCELED) older than ``ttl_s`` (default
          24h).  This is the long-TTL GC that keeps the dict bounded.
        * :meth:`IdempotentOrderStore.prune_stale_pending` — marks orphaned
          PENDING / SUBMITTED records as REJECTED so the terminal prune
          can eventually sweep them.  Without this step, a PENDING record
          produced by a crashed upstream caller would leak forever.

        Returns a dict with ``pruned_terminal``, ``orphaned_pending``, and
        ``orphaned_submitted`` counts for observability.
        """
        # Mark orphans BEFORE running the terminal prune so the records
        # marked in this tick don't have to wait until the next one to be
        # candidates (they still have to age past ``ttl_s`` of course, but
        # operators get a single consistent snapshot of "what happened").
        orphans = self._store.prune_stale_pending(pending_ttl_s, submitted_ttl_s)
        pruned = self._store.prune_old(ttl_s)

        if pruned > 0 or any(orphans.values()):
            logger.info(
                "[GATE] cleanup_stale: pruned_terminal=%d orphaned_pending=%d orphaned_submitted=%d",
                pruned, orphans["orphaned_pending"], orphans["orphaned_submitted"],
            )

        return {
            "pruned_terminal": pruned,
            **orphans,
        }


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
