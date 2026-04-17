"""Tracks MERID-submitted live Kalshi orders for reconciliation internal book.

When ``MERID_REC_INTERNAL_SOURCE=fills_ledger``, position truth comes from the
fills ledger but open-order truth must reflect orders this process placed on
the venue. The venue adapter's matching engine is empty in that mode; this
registry is populated by ``order_router`` after successful live placement and
pruned against the venue's open-order snapshot during reconciliation.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Set

from merid.event_venues.base import PlacedOrder
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.live_open_order_registry")


class LiveOpenOrderRegistry:
    """Thread-safe map of Kalshi order_id -> last known PlacedOrder snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: Dict[str, PlacedOrder] = {}

    def record_placed(self, placed: PlacedOrder) -> None:
        if not placed or not placed.order_id:
            return
        with self._lock:
            self._by_id[placed.order_id] = placed
        logger.debug(
            "live_open_order_registry recorded order_id=%s market=%s status=%s",
            placed.order_id,
            placed.market_id,
            placed.status,
        )

    def remove_order(self, order_id: str) -> None:
        if not order_id:
            return
        with self._lock:
            self._by_id.pop(order_id, None)

    def prune_to_open_order_ids(self, open_ids: Set[str]) -> None:
        """Drop registry entries that are no longer open on the venue."""
        with self._lock:
            stale = [oid for oid in self._by_id if oid not in open_ids]
            for oid in stale:
                del self._by_id[oid]
            if stale:
                logger.debug(
                    "live_open_order_registry pruned %d stale order(s) not on venue open set",
                    len(stale),
                )

    def prune_expired(self, cutoff_ts: Optional[float] = None, ttl_seconds: float = 86400.0) -> int:
        """Remove orders whose placement age exceeds *ttl_seconds* (default 24 h).

        Uses ``PlacedOrder.created_at`` when available; falls back to a TTL
        measured from the time the order was first recorded (not available here,
        so orders with no ``created_at`` are **not** pruned — they must be
        removed via :meth:`prune_to_open_order_ids`).

        Args:
            cutoff_ts: Unix timestamp (seconds).  Orders placed *before* this
                value are pruned.  Defaults to ``time.time() - ttl_seconds``.
            ttl_seconds: Age threshold in seconds.  Ignored when *cutoff_ts* is
                supplied explicitly.

        Returns:
            Number of orders removed.
        """
        if cutoff_ts is None:
            cutoff_ts = time.time() - ttl_seconds

        pruned: List[str] = []
        with self._lock:
            for oid, placed in list(self._by_id.items()):
                created_at = placed.created_at
                if created_at is None:
                    continue  # cannot determine age; skip
                if created_at.timestamp() < cutoff_ts:
                    pruned.append(oid)
            for oid in pruned:
                del self._by_id[oid]

        if pruned:
            logger.debug(
                "live_open_order_registry.prune_expired removed %d order(s) older than cutoff %s",
                len(pruned),
                cutoff_ts,
            )
        return len(pruned)

    def has_open_for_market(self, market_id: str) -> bool:
        """Return True if any non-terminal order for this market is in the registry.

        Prevents placing a new order on a ticker that already has a resting order
        from a prior cycle (cross-cycle duplicate guard).
        """
        _TERMINAL = {"filled", "cancelled", "canceled", "expired", "closed"}
        with self._lock:
            return any(
                p.market_id == market_id and p.status not in _TERMINAL
                for p in self._by_id.values()
            )

    def snapshot(self) -> List[PlacedOrder]:
        with self._lock:
            return list(self._by_id.values())


_registry: Optional[LiveOpenOrderRegistry] = None
_reg_lock = threading.Lock()


def get_live_open_order_registry() -> LiveOpenOrderRegistry:
    global _registry
    with _reg_lock:
        if _registry is None:
            _registry = LiveOpenOrderRegistry()
        return _registry


def reset_live_open_order_registry_for_testing() -> None:
    global _registry
    with _reg_lock:
        _registry = None
