"""Order idempotency / deduplication cache for Kalshi trading.

Prevents duplicate orders from being submitted on retry by reusing
the same client_order_id when a matching in-flight order is found.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_deduplication")

_TTL_SECONDS: int = 5  # 5 seconds — Aligned with order_router.py _DUPLICATE_ORDER_WINDOW_SECONDS to match 15m crypto agent 5s cadence


@dataclass
class PendingOrder:
    """Cached order waiting for or having received a response."""

    client_order_id: str
    ticker: str
    side: str        # "buy" or "sell"
    outcome: str     # "yes" or "no"
    price_cents: Optional[int]
    count: int
    submitted_at: datetime
    order_id: Optional[str] = None  # filled once Kalshi confirms
    submitted_to_exchange: bool = False  # CRITICAL: Track if order was actually submitted


class OrderDeduplicationCache:
    """Cache of recently submitted orders for idempotency.

    On each placement attempt the caller calls ``get_or_create`` with
    the order parameters.  If an identical in-flight order already
    exists (same ticker/side/outcome/price/count within the TTL) the
    existing ``client_order_id`` is returned so the second request
    reuses Kalshi's natural idempotency key.  Otherwise a fresh UUID is
    generated and cached.

    Usage::

        cache = get_order_cache()
        coid, is_dup = cache.get_or_create(
            ticker="KXBTC-23DEC3100-T3550",
            side="buy",
            outcome="yes",
            price_cents=55,
            count=10,
        )
        # Pass coid as ``client_order_id`` in the Kalshi payload.
        # On success call cache.mark_completed(coid, order_id).
    """

    def __init__(self, ttl_seconds: int = _TTL_SECONDS) -> None:
        self._cache: Dict[str, PendingOrder] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        ticker: str,
        side: str,
        outcome: str,
        price_cents: Optional[int],
        count: int,
    ) -> Tuple[str, bool]:
        """Return (client_order_id, is_duplicate).

        If a matching order exists in the cache the existing ID is
        returned and ``is_duplicate`` is ``True``.  Otherwise a new
        UUID ID is registered and ``is_duplicate`` is ``False``.
        """
        self._prune_expired()

        for pending in self._cache.values():
            if (
                pending.ticker == ticker
                and pending.side == side
                and pending.outcome == outcome
                and pending.price_cents == price_cents
                and pending.count == count
                and pending.order_id is None  # not yet confirmed
            ):
                # CRITICAL FIX: Only treat as duplicate if it was actually submitted to exchange
                # If the order was cached but never submitted (e.g., rejected before submission),
                # we should allow it to be submitted now
                if pending.submitted_to_exchange:
                    logger.warning(
                        "Duplicate order detected for %s %s %s %s×%d — "
                        "reusing client_order_id %s (already submitted to exchange)",
                        ticker, side, outcome, price_cents, count,
                        pending.client_order_id,
                    )
                    return pending.client_order_id, True
                else:
                    logger.info(
                        "Cached order %s %s %s %s×%d was never submitted to exchange - allowing submission",
                        ticker, side, outcome, price_cents, count
                    )
                    # Remove the stale entry and continue to create a new one
                    del self._cache[pending.client_order_id]
                    break

        coid = str(uuid.uuid4())
        self._cache[coid] = PendingOrder(
            client_order_id=coid,
            ticker=ticker,
            side=side,
            outcome=outcome,
            price_cents=price_cents,
            count=count,
            submitted_at=datetime.now(timezone.utc),
        )
        return coid, False

    def is_duplicate(
        self,
        ticker: str,
        side: str,
        outcome: str,
        price_cents: Optional[int],
        count: int,
    ) -> bool:
        """Check whether an in-flight, already-submitted matching order exists.

        Unlike ``get_or_create``, this does NOT create a cache entry and does
        NOT remove stale un-submitted entries.  It is intended for pre-flight
        validation guards.
        """
        self._prune_expired()
        for pending in self._cache.values():
            if (
                pending.ticker == ticker
                and pending.side == side
                and pending.outcome == outcome
                and pending.price_cents == price_cents
                and pending.count == count
                and pending.order_id is None
                and pending.submitted_to_exchange
            ):
                logger.warning(
                    "Duplicate order detected for %s %s %s %s×%d — "
                    "reusing client_order_id %s (already submitted to exchange)",
                    ticker, side, outcome, price_cents, count,
                    pending.client_order_id,
                )
                return True
        return False

    def mark_completed(self, client_order_id: str, order_id: str) -> None:
        """Record the Kalshi order_id once the API confirms the order."""
        if client_order_id in self._cache:
            self._cache[client_order_id].order_id = order_id
            self._cache[client_order_id].submitted_to_exchange = True
        else:
            logger.debug("mark_completed called for unknown coid %s", client_order_id)

    def mark_submitted(self, client_order_id: str) -> None:
        """Record that the order was actually submitted to the exchange."""
        if client_order_id in self._cache:
            self._cache[client_order_id].submitted_to_exchange = True
        else:
            logger.debug("mark_submitted called for unknown coid %s", client_order_id)

    def get_metrics(self) -> Dict[str, int]:
        """Return cache metrics for observability."""
        self._prune_expired()
        pending = sum(1 for p in self._cache.values() if p.order_id is None)
        confirmed = len(self._cache) - pending
        return {"cached_orders": len(self._cache), "pending": pending, "confirmed": confirmed}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired: List[str] = [
            k for k, v in self._cache.items()
            if now - v.submitted_at > self._ttl
        ]
        for k in expired:
            del self._cache[k]


# ── Global singleton ───────────────────────────────────────────────────────

_order_cache: Optional[OrderDeduplicationCache] = None


def get_order_cache() -> OrderDeduplicationCache:
    """Get the global order deduplication cache singleton."""
    global _order_cache
    if _order_cache is None:
        _order_cache = OrderDeduplicationCache()
    return _order_cache
