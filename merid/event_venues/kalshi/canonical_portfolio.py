"""Canonical portfolio snapshot and reconciliation.

This module provides the single authoritative portfolio view that all trading
components consume.  It reconciles exchange positions, private WebSocket
position/fill/order events, the local fills ledger, the position cache, and
risk-manager reservations into one immutable snapshot per cycle.

Design principles
-----------------
- One snapshot per reconciliation cycle, published atomically.
- Exchange REST is the authority for bootstrap and recovery.
- Private WS events update the snapshot for low-latency decisions.
- Local ledger / cache are derived state; they never override a confirmed
  exchange position without explicit reconciliation.
- Allocator reservations are tracked as *pending* exposure, never as
  exchange-confirmed positions.
- New entries are blocked when reconciliation_status is not MATCHED.
- Safety exits remain available when the position quantity is individually
  confirmed, even if unrelated telemetry is mismatched.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.canonical_portfolio")


class ReconciliationStatus(str, Enum):
    """Authoritative reconciliation status for a portfolio snapshot."""

    MATCHED = "MATCHED"
    MISMATCH = "MISMATCH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class PaginationIncomplete(Exception):
    """Raised when a paginated source cannot be fully collected."""

    def __init__(self, error_code: str, pages_fetched: int = 0, records_fetched: int = 0):
        self.error_code = error_code
        self.pages_fetched = pages_fetched
        self.records_fetched = records_fetched
        super().__init__(f"Pagination incomplete: {error_code}")


@dataclass(frozen=True)
class SourceCompleteness:
    """Metadata describing whether a paginated source was fully collected."""

    source: str
    complete: bool
    pages_fetched: int = 0
    records_fetched: int = 0
    cursor_seen: Optional[str] = None
    cursor_next: Optional[str] = None
    request_started_ns: int = 0
    request_completed_ns: int = 0
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "complete": self.complete,
            "pages_fetched": self.pages_fetched,
            "records_fetched": self.records_fetched,
            "cursor_seen": self.cursor_seen,
            "cursor_next": self.cursor_next,
            "request_started_ns": self.request_started_ns,
            "request_completed_ns": self.request_completed_ns,
            "error_code": self.error_code,
        }


MAX_PAGES = 10


class ReconciliationReason(str, Enum):
    """Detailed reason for the reconciliation status.

    The router uses this to distinguish a recoverable delay from a dangerous
    disagreement.  A missing or incomplete authoritative source is never treated
    the same as a network failure.
    """

    MATCHED = "MATCHED"
    MISMATCH_POSITION = "MISMATCH_POSITION"
    MISMATCH_LEDGER = "MISMATCH_LEDGER"
    MISMATCH_WORKING_ORDER = "MISMATCH_WORKING_ORDER"
    MISMATCH_DUPLICATE_EVENT = "MISMATCH_DUPLICATE_EVENT"
    STALE_REST = "STALE_REST"
    STALE_PRIVATE_WS = "STALE_PRIVATE_WS"
    UNKNOWN_NETWORK = "UNKNOWN_NETWORK"
    UNKNOWN_PAGINATION = "UNKNOWN_PAGINATION"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"


class PositionProvenance(str, Enum):
    """Source of truth for a canonical position."""

    EXCHANGE_REST = "exchange_rest"
    WS_POSITION = "ws_position"
    LOCAL_LEDGER = "local_ledger"
    CACHE = "cache"
    RECONCILED = "reconciled"


class OrderProvenance(str, Enum):
    """Source of truth for a canonical working order."""

    EXCHANGE_REST = "exchange_rest"
    WS_ORDER = "ws_order"
    LOCAL_GATE = "local_gate"


class FillProvenance(str, Enum):
    """Source of truth for a canonical fill."""

    EXCHANGE_REST = "exchange_rest"
    WS_FILL = "ws_fill"
    HTTP_FILL = "http_fill"


@dataclass(frozen=True)
class CanonicalPosition:
    """Immutable per-market position used in the canonical snapshot.

    All quantity fields use ``Decimal`` whole contracts for human-readable
    provenance, while the snapshot aggregates canonical centi-contract
    ``yes_exposure_cc`` for risk arithmetic.
    """

    ticker: str
    market_id: str
    outcome: str  # "yes" or "no"
    quantity_fp: Decimal  # signed whole contracts, positive long this outcome
    avg_entry_price_cents: int
    entry_order_id: Optional[str]
    entry_fill_id: Optional[str]
    provenance: str
    timestamp: float
    # Canonical signed-YES centi-contract exposure derived from outcome/quantity.
    # Positive = long YES, negative = long NO.
    yes_exposure_cc: int = 0


@dataclass(frozen=True)
class CanonicalOrder:
    """Immutable working order in the canonical snapshot."""

    order_id: str
    client_order_id: Optional[str]
    ticker: str
    side: str
    action: str
    quantity_fp: Decimal
    filled_quantity_fp: Decimal
    remaining_quantity_fp: Decimal
    price_cents: int
    status: str
    source: str
    timestamp: float


@dataclass(frozen=True)
class CanonicalFill:
    """Immutable fill in the canonical snapshot."""

    fill_id: str
    order_id: str
    ticker: str
    side: str
    action: str
    quantity_fp: Decimal
    price_cents: int
    fee_cents: int
    timestamp: float
    source: str


@dataclass(frozen=True)
class CanonicalPortfolioSnapshot:
    """Single, immutable portfolio snapshot published per reconciliation cycle."""

    version: int
    captured_at_wall_ns: int
    captured_at_mono_ns: int

    positions_by_ticker: Dict[str, CanonicalPosition]
    working_orders_by_id: Dict[str, CanonicalOrder]
    pending_fills_by_id: Dict[str, CanonicalFill]

    # Aggregate exposure in signed-YES centi-contracts.
    # These are retained for backward compatibility and are aliases for the
    # signed aggregate below.
    exchange_exposure_cc: int
    local_ledger_exposure_cc: int
    reserved_exposure_cc: int

    reconciliation_status: str
    source: str
    source_age_ms: int
    private_ws_healthy: bool

    # Signed-vs-gross exposure breakdown.
    # Signed exposure = directional net position / net pending quantity.
    # Gross exposure  = capital-at-risk view (sum of absolute quantities).
    # Risk, slot, and concentration limits must use gross values.
    signed_exposure_cc: int = 0
    gross_exposure_cc: int = 0
    signed_reserved_exposure_cc: int = 0
    gross_reserved_exposure_cc: int = 0
    gross_notional_cents: int = 0

    # Detailed reason code for the reconciliation status.
    # This lets the router distinguish recoverable stale data from dangerous
    # disagreement between authoritative sources.
    reconciliation_reason: str = ReconciliationReason.MATCHED

    # Pagination / source completeness metadata.
    # A complete empty result is authoritative zero; an incomplete result is
    # unknown and must block new entries.
    pagination_complete: bool = False
    positions_source_complete: Optional[SourceCompleteness] = None
    fills_source_complete: Optional[SourceCompleteness] = None
    orders_source_complete: Optional[SourceCompleteness] = None

    # Diagnostic detail for mismatched tickers.
    mismatches: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def positions_count(self) -> int:
        return len(self.positions_by_ticker)

    @property
    def age_ms(self) -> int:
        """Return time since capture in milliseconds."""
        return int((time.monotonic() - (self.captured_at_mono_ns / 1e9)) * 1000)

    @property
    def is_matched(self) -> bool:
        return self.reconciliation_status == ReconciliationStatus.MATCHED

    @property
    def is_authoritative(self) -> bool:
        """Return True only when the snapshot is matched *and* all paginated
        sources that were queried are complete.

        New entries must use this; exits remain available when ``is_matched`` is
        false for the individual position.
        """
        if not self.is_matched:
            return False
        if not self.pagination_complete:
            return False
        return all(
            src is None or src.complete
            for src in (
                self.positions_source_complete,
                self.orders_source_complete,
                self.fills_source_complete,
            )
        )

    def exchange_position_fp(self, position_key: str) -> Decimal:
        """Return the signed whole-contract position for a market, or zero."""
        pos = self.positions_by_ticker.get(position_key)
        if pos is None:
            return Decimal("0")
        return pos.quantity_fp

    def working_exit_count_fp(self, position_key: str) -> Decimal:
        """Return the total remaining whole-contract quantity of working orders
        for a market.  Any non-zero value means a working order for that market
        remains.
        """
        return sum(
            (
                order.remaining_quantity_fp
                for order in self.working_orders_by_id.values()
                if order.ticker == position_key
            ),
            Decimal("0"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for logs and telemetry."""
        return {
            "version": self.version,
            "captured_at_wall_ns": self.captured_at_wall_ns,
            "captured_at_mono_ns": self.captured_at_mono_ns,
            "positions_count": self.positions_count,
            "working_orders_count": len(self.working_orders_by_id),
            "pending_fills_count": len(self.pending_fills_by_id),
            "exchange_exposure_cc": self.exchange_exposure_cc,
            "local_ledger_exposure_cc": self.local_ledger_exposure_cc,
            "reserved_exposure_cc": self.reserved_exposure_cc,
            "signed_exposure_cc": self.signed_exposure_cc,
            "gross_exposure_cc": self.gross_exposure_cc,
            "signed_reserved_exposure_cc": self.signed_reserved_exposure_cc,
            "gross_reserved_exposure_cc": self.gross_reserved_exposure_cc,
            "gross_notional_cents": self.gross_notional_cents,
            "reconciliation_status": self.reconciliation_status,
            "reconciliation_reason": self.reconciliation_reason,
            "pagination_complete": self.pagination_complete,
            "positions_source_complete": self.positions_source_complete.to_dict() if self.positions_source_complete else None,
            "fills_source_complete": self.fills_source_complete.to_dict() if self.fills_source_complete else None,
            "orders_source_complete": self.orders_source_complete.to_dict() if self.orders_source_complete else None,
            "source": self.source,
            "source_age_ms": self.source_age_ms,
            "private_ws_healthy": self.private_ws_healthy,
            "mismatches": list(self.mismatches),
            "age_ms": self.age_ms,
        }


class CanonicalPortfolioStore:
    """Atomic store for the current canonical portfolio snapshot.

    Consumers read ``current()``; the reconciler publishes a new snapshot via
    ``publish()``.  The store is thread-safe and versioned.
    """

    _instance: Optional["CanonicalPortfolioStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CanonicalPortfolioStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._local_lock = threading.Lock()
        self._current: Optional[CanonicalPortfolioSnapshot] = None
        self._version = 0
        self._publish_count = 0
        self._last_publish_mono = 0.0
        self._initialized = True
        logger.info("[CANONICAL-PORTFOLIO-STORE] initialized")

    def publish(self, snapshot: CanonicalPortfolioSnapshot) -> bool:
        """Publish a new canonical snapshot atomically.

        Reject stale versions so an older builder finishing later cannot
        overwrite a newer published snapshot.
        """
        with self._local_lock:
            if self._current is not None and snapshot.version <= self._current.version:
                logger.warning(
                    "[PORTFOLIO-SNAPSHOT-STALE-REJECTED] version=%d current=%d - "
                    "stale snapshot rejected by store",
                    snapshot.version,
                    self._current.version,
                )
                return False
            self._current = snapshot
            self._version = snapshot.version
            self._publish_count += 1
            self._last_publish_mono = time.monotonic()
        logger.info(
            "[PORTFOLIO-SNAPSHOT-PUBLISHED] version=%d positions=%d "
            "reconciliation_status=%s source=%s age_ms=%d",
            snapshot.version,
            snapshot.positions_count,
            snapshot.reconciliation_status,
            snapshot.source,
            snapshot.source_age_ms,
        )
        return True

    def current(self) -> Optional[CanonicalPortfolioSnapshot]:
        """Return the current canonical snapshot, or None if none published."""
        with self._local_lock:
            return self._current

    def get_status(self) -> Dict[str, Any]:
        with self._local_lock:
            snap = self._current
            return {
                "version": self._version,
                "publish_count": self._publish_count,
                "last_publish_ago_ms": (
                    int((time.monotonic() - self._last_publish_mono) * 1000)
                    if self._last_publish_mono > 0
                    else None
                ),
                "snapshot": snap.to_dict() if snap else None,
            }


async def collect_all_pages(
    source_name: str,
    fetch_page: Any,
    request: Optional[Dict[str, Any]] = None,
    *,
    max_pages: int = MAX_PAGES,
    started_ns: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], SourceCompleteness]:
    """Collect a complete paginated list from a Kalshi-style cursor API.

    ``fetch_page`` must accept ``cursor`` and return a mapping with at least an
    ``items`` list and an optional ``cursor`` key.  It may be a coroutine.

    Raises ``PaginationIncomplete`` when a page is malformed, a cursor loops,
    a page fetch fails, or the maximum page count is reached with more data
    still available.
    """
    records: List[Dict[str, Any]] = []
    seen_cursors: set = set()
    cursor: Optional[str] = None
    pages = 0
    started = started_ns or time.time_ns()
    completed = started

    request = request or {}

    while True:
        try:
            if asyncio.iscoroutinefunction(fetch_page):
                response = await fetch_page(cursor=cursor, **request)
            else:
                response = fetch_page(cursor=cursor, **request)
        except Exception:
            completed = time.time_ns()
            raise PaginationIncomplete(
                "PAGE_FETCH_FAILED",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        pages += 1

        if not isinstance(response, dict):
            completed = time.time_ns()
            raise PaginationIncomplete(
                "MALFORMED_RESPONSE",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        items = response.get("items")
        if not isinstance(items, list):
            completed = time.time_ns()
            raise PaginationIncomplete(
                "MISSING_ITEMS",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        next_cursor = response.get("cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            completed = time.time_ns()
            raise PaginationIncomplete(
                "INVALID_CURSOR",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        records.extend(items)
        completed = time.time_ns()

        if not next_cursor:
            return records, SourceCompleteness(
                source=source_name,
                complete=True,
                pages_fetched=pages,
                records_fetched=len(records),
                cursor_seen=cursor,
                request_completed_ns=completed,
                request_started_ns=started,
            )

        if next_cursor in seen_cursors:
            raise PaginationIncomplete(
                "CURSOR_LOOP",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        if pages >= max_pages:
            raise PaginationIncomplete(
                "MAX_PAGES",
                pages_fetched=pages,
                records_fetched=len(records),
            )

        seen_cursors.add(next_cursor)
        cursor = next_cursor


def get_canonical_portfolio_store() -> CanonicalPortfolioStore:
    """Return the global canonical portfolio snapshot singleton."""
    return CanonicalPortfolioStore()
