"""Pre-trade idempotency gate for Kalshi order submission.

Purpose
-------
Prevent duplicate live orders from reaching Kalshi while allowing:
  1. Idempotent retries of the same logical order.
  2. Genuine new orders, even when parameters match a previous order that has
     already reached a terminal state (filled / rejected / canceled).
  3. Market-maker agents to place fresh bid/ask pairs every cycle, even when
     the price/qty parameters are unchanged within a 60-second window.

Design overview
---------------
The gate assigns every logical order a deterministic *internal* key called a
``coid`` (client-order identifier).  This is distinct from the Kalshi REST/FIX
``client_order_id``, which continues to use a UUID4-based trace_id
(see ``order_router.py: FIX-DEDUP``).

The coid preimage is:

    ``{agent_id}|{strategy_group}|{contract_id}|{side}|{qty}|{price_cents}|{bucket}[|{cycle_id}]``

where:

* ``bucket`` is ``floor(unix_epoch / DECISION_BUCKET_WIDTH_S)``.  Orders with
  the same parameters within the same time bucket share a coid → the gate
  treats them as the same logical order.
* ``cycle_id`` (optional) is a caller-supplied nonce that forces a new coid
  for a new logical cycle, even if all other parameters are identical.

Bucket-width configuration
--------------------------
* Default (directional agents): ``DECISION_BUCKET_WIDTH_S = 60`` seconds.
* Market-maker agents (``archetype == "market_maker"`` or ``is_mm=True``):
  ``MM_DECISION_BUCKET_WIDTH_S = 5`` seconds (env: ``MERID_MM_GATE_BUCKET_S``).

  Rationale: a 15-minute-expiry MM quotes every ~15 s.  With a 60-second
  bucket, cycles 1–4 inside the same minute share a coid and the gate blocks
  cycles 2–4 as duplicates.  A 5-second bucket gives every cycle its own
  fresh key while retries within ~5 s still share the same key.

Gate status machine
-------------------
``pending``  → order has been reserved by the gate but not yet confirmed
``open``     → Kalshi ACK'd the order; it is resting on the book
``filled``   → order fully (or partially) executed
``rejected`` → Kalshi rejected the order
``canceled`` → order was explicitly canceled

Terminal statuses (``filled``, ``rejected``, ``canceled``) allow the same
parameter set to be used for a new logical order in a subsequent call to
``check_and_reserve``.

Gate decisions returned by ``check_and_reserve``
-------------------------------------------------
``"proceed"``             – New unique order; gate records it as ``pending``.
``"idempotent"``          – Same coid, already ``pending``/``open``; caller
                            should treat the existing order as the response
                            (do not re-submit to Kalshi).
``"duplicate_blocked"``   – Same coid, still ``pending``/``open``; a new
                            submission was attempted.  Log and reject the
                            caller's order.

Usage in the router
-------------------
::

    gate = get_pre_trade_gate()
    coid, decision, entry = gate.check_and_reserve(
        agent_id=intent.agent_id,
        strategy_group=intent.strategy_group or intent.source,
        contract_id=intent.ticker,
        side=intent.side,
        qty=intent.count,
        price_cents=intent.price_cents,
        is_mm=intent.is_market_maker,
        cycle_id=intent.cycle_id,
    )
    if decision == "duplicate_blocked":
        return OrderResult(status="rejected", reason=f"gate:duplicate:{entry.status}")

    # ... submit to Kalshi ...

    gate.update_status(coid, "filled")

Rollback
--------
Set env ``MERID_ORDER_GATE_ENABLED=false`` to disable all gate checks.
All orders will proceed as if the gate returned ``"proceed"``.  This reverts
to the pre-gate behaviour (UUID4-only dedup at the Kalshi layer).
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_gate")

# ── Configuration ─────────────────────────────────────────────────────────────

# Default time bucket for directional / slow agents: 60 seconds.
# Within a single bucket, two orders with identical (agent, strategy_group,
# contract, side, qty, price) share a coid and are treated as the same order.
DECISION_BUCKET_WIDTH_S: int = int(os.getenv("MERID_GATE_BUCKET_S", "60"))

# Shorter bucket for market-maker (high-frequency) agents: 5 seconds.
# Ensures each MM cycle (~15 s period) gets a fresh coid even for repeated
# parameters, so the gate does not permanently block MM order flow.
MM_DECISION_BUCKET_WIDTH_S: int = int(os.getenv("MERID_MM_GATE_BUCKET_S", "5"))

# Gate-wide kill switch.  Set to "false" to bypass all gate checks.
_GATE_ENABLED: bool = os.getenv("MERID_ORDER_GATE_ENABLED", "true").lower() != "false"

# TTL for terminal entries.  After this many seconds a filled/rejected/canceled
# coid is pruned from in-memory state so the dict stays bounded.
_TERMINAL_ENTRY_TTL_S: int = int(os.getenv("MERID_GATE_ENTRY_TTL_S", "300"))


# ── Status enum ───────────────────────────────────────────────────────────────

class OrderGateStatus(str, Enum):
    """Lifecycle states of an order as seen by the gate."""
    PENDING  = "pending"    # reserved but not yet ACK'd by Kalshi
    OPEN     = "open"       # resting on the Kalshi book
    FILLED   = "filled"     # fully (or partially) executed
    REJECTED = "rejected"   # rejected by Kalshi (or our risk layer post-reserve)
    CANCELED = "canceled"   # explicitly canceled


_TERMINAL_STATUSES = frozenset({
    OrderGateStatus.FILLED,
    OrderGateStatus.REJECTED,
    OrderGateStatus.CANCELED,
})

_BLOCKING_STATUSES = frozenset({
    OrderGateStatus.PENDING,
    OrderGateStatus.OPEN,
})


# ── Gate entry ────────────────────────────────────────────────────────────────

@dataclass
class GateEntry:
    """Record for a single logical order held in the gate's state dict."""
    coid:           str
    status:         OrderGateStatus
    agent_id:       str
    strategy_group: str
    contract_id:    str
    side:           str
    qty:            int
    price_cents:    int
    bucket:         int
    cycle_id:       Optional[str]
    is_mm:          bool
    created_at:     float = field(default_factory=time.time)
    updated_at:     float = field(default_factory=time.time)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def is_blocking(self) -> bool:
        return self.status in _BLOCKING_STATUSES


# ── Deterministic coid generator ─────────────────────────────────────────────

def make_coid(
    agent_id:       str,
    strategy_group: str,
    contract_id:    str,
    side:           str,
    qty:            int,
    price_cents:    int,
    *,
    is_mm:   bool = False,
    cycle_id: Optional[str] = None,
    now:     Optional[float] = None,
) -> Tuple[str, int]:
    """Compute a deterministic gate key (coid) from order parameters.

    The coid encodes the logical identity of an order.  Two calls with the
    same parameters within the same time bucket return the same coid.

    Preimage fields:
        agent_id       – agent name/ID (e.g. "kalshi-crypto_15m_mm_sol")
        strategy_group – strategy group label (e.g. "CRYPTO_15M_MM", "BTC_15M")
        contract_id    – Kalshi ticker (e.g. "KXSOL15M-26APR121400-00")
        side           – "yes" or "no"
        qty            – contract count (int)
        price_cents    – limit price in cents (int, 1-99)
        bucket         – floor(epoch_seconds / bucket_width)
        cycle_id       – optional caller nonce that forces a new coid for a new
                         MM trade cycle (appended when not None)

    Returns:
        (coid, bucket) – coid is a 16-hex-char prefix of SHA-256 of the
        preimage.  Bucket is included for logging / diagnostics.
    """
    ts = now if now is not None else time.time()
    bucket_width = MM_DECISION_BUCKET_WIDTH_S if is_mm else DECISION_BUCKET_WIDTH_S
    bucket = math.floor(ts / bucket_width)

    parts = [
        agent_id,
        strategy_group,
        contract_id,
        side,
        str(qty),
        str(price_cents),
        str(bucket),
    ]
    if cycle_id is not None:
        parts.append(cycle_id)

    preimage = "|".join(parts)
    digest = hashlib.sha256(preimage.encode()).hexdigest()[:16]
    return f"mg_{digest}", bucket


# ── Gate class ────────────────────────────────────────────────────────────────

class PreTradeGate:
    """In-process pre-trade idempotency gate.

    Thread-safety note: this class uses a plain dict and is designed for a
    single-threaded async event loop.  If concurrent access from multiple
    threads is ever required, wrap state mutations with a threading.Lock.
    """

    def __init__(self) -> None:
        self._state: Dict[str, GateEntry] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def check_and_reserve(
        self,
        agent_id:       str,
        strategy_group: str,
        contract_id:    str,
        side:           str,
        qty:            int,
        price_cents:    int,
        *,
        is_mm:    bool = False,
        cycle_id: Optional[str] = None,
        now:      Optional[float] = None,
    ) -> Tuple[str, str, Optional[GateEntry]]:
        """Check whether an order may proceed and reserve a gate slot.

        Returns:
            (coid, decision, entry)

            decision:
                "proceed"           – new unique order; gate marks it pending.
                "idempotent"        – same coid already pending/open; treat
                                      existing order as the response.
                "duplicate_blocked" – same coid, blocking status; reject.

        Side-effects:
            On "proceed": inserts a new GateEntry with status=PENDING.
            On "idempotent"/"duplicate_blocked": no state change.
        """
        if not _GATE_ENABLED:
            coid, bucket = make_coid(
                agent_id, strategy_group, contract_id, side, qty, price_cents,
                is_mm=is_mm, cycle_id=cycle_id, now=now,
            )
            logger.debug(
                "[GATE] gate_disabled proceed coid=%s agent=%s contract=%s side=%s",
                coid, agent_id, contract_id, side,
            )
            return coid, "proceed", None

        coid, bucket = make_coid(
            agent_id, strategy_group, contract_id, side, qty, price_cents,
            is_mm=is_mm, cycle_id=cycle_id, now=now,
        )

        existing = self._state.get(coid)

        if existing is None or existing.is_terminal():
            # New order or previous order reached a terminal state → allow.
            entry = GateEntry(
                coid=coid,
                status=OrderGateStatus.PENDING,
                agent_id=agent_id,
                strategy_group=strategy_group,
                contract_id=contract_id,
                side=side,
                qty=qty,
                price_cents=price_cents,
                bucket=bucket,
                cycle_id=cycle_id,
                is_mm=is_mm,
            )
            self._state[coid] = entry
            logger.info(
                "[GATE] new_order_proceed coid=%s status=pending contract=%s "
                "agent=%s strategy_group=%s side=%s qty=%d price_cents=%d "
                "bucket=%d is_mm=%s cycle_id=%s",
                coid, contract_id, agent_id, strategy_group,
                side, qty, price_cents, bucket, is_mm, cycle_id,
            )
            return coid, "proceed", None

        if existing.is_blocking():
            # Same logical order, still pending or open.
            logger.warning(
                "[GATE] duplicate blocked coid=%s status=%s contract=%s "
                "agent=%s strategy_group=%s side=%s qty=%d price_cents=%d "
                "bucket=%d is_mm=%s cycle_id=%s",
                coid, existing.status.value, contract_id,
                agent_id, strategy_group, side, qty, price_cents,
                bucket, is_mm, cycle_id,
            )
            return coid, "duplicate_blocked", existing

        # Should not reach here (all statuses covered above), but be safe.
        logger.error(
            "[GATE] unexpected_status coid=%s status=%s — treating as proceed",
            coid, existing.status,
        )
        return coid, "proceed", existing

    def update_status(
        self,
        coid: str,
        status: str | OrderGateStatus,
        *,
        log_context: Optional[str] = None,
    ) -> bool:
        """Transition a gate entry to a new status.

        Returns True if the entry was found and updated, False otherwise.
        """
        if isinstance(status, str):
            try:
                status = OrderGateStatus(status)
            except ValueError:
                logger.error(
                    "[GATE] update_status unknown status=%r for coid=%s", status, coid
                )
                return False

        entry = self._state.get(coid)
        if entry is None:
            logger.warning(
                "[GATE] update_status coid=%s not found (status=%s ctx=%s)",
                coid, status.value, log_context,
            )
            return False

        old = entry.status
        entry.status = status
        entry.updated_at = time.time()

        level = logger.info if status in _TERMINAL_STATUSES else logger.debug
        level(
            "[GATE] status_transition coid=%s %s→%s contract=%s agent=%s ctx=%s",
            coid, old.value, status.value, entry.contract_id,
            entry.agent_id, log_context,
        )
        return True

    def release(self, coid: str, status: str | OrderGateStatus = OrderGateStatus.CANCELED) -> bool:
        """Force-release a gate entry to a terminal status.

        Useful for cancel-and-replace flows: after canceling an order at
        Kalshi, call ``release(coid, "canceled")`` so the gate no longer
        blocks fresh orders with the same parameters.
        """
        return self.update_status(coid, status, log_context="explicit_release")

    def cleanup_stale(self, ttl_seconds: Optional[int] = None) -> int:
        """Remove terminal entries older than *ttl_seconds*.

        Returns the number of entries removed.
        """
        ttl = ttl_seconds if ttl_seconds is not None else _TERMINAL_ENTRY_TTL_S
        cutoff = time.time() - ttl
        stale = [
            coid for coid, entry in self._state.items()
            if entry.is_terminal() and entry.updated_at < cutoff
        ]
        for coid in stale:
            del self._state[coid]
        if stale:
            logger.debug("[GATE] cleanup removed %d stale entries", len(stale))
        return len(stale)

    def snapshot(self) -> Dict[str, dict]:
        """Return a read-only snapshot of the current gate state (for diagnostics)."""
        return {
            coid: {
                "status":         e.status.value,
                "agent_id":       e.agent_id,
                "strategy_group": e.strategy_group,
                "contract_id":    e.contract_id,
                "side":           e.side,
                "qty":            e.qty,
                "price_cents":    e.price_cents,
                "bucket":         e.bucket,
                "is_mm":          e.is_mm,
                "cycle_id":       e.cycle_id,
                "created_at":     e.created_at,
                "updated_at":     e.updated_at,
            }
            for coid, e in self._state.items()
        }

    def active_count(self) -> int:
        """Number of non-terminal (pending/open) entries."""
        return sum(1 for e in self._state.values() if e.is_blocking())


# ── Singleton ─────────────────────────────────────────────────────────────────

_gate: Optional[PreTradeGate] = None


def get_pre_trade_gate() -> PreTradeGate:
    """Return the process-wide PreTradeGate singleton."""
    global _gate
    if _gate is None:
        _gate = PreTradeGate()
    return _gate
