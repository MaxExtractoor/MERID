"""Canonical portfolio reconciler.

Builds one immutable `CanonicalPortfolioSnapshot` per cycle by reconciling:
1. Exchange REST positions (`/portfolio/positions`) - authoritative.
2. Private WebSocket position, fill, and order events - low-latency updates.
3. Local fills ledger - derived from applied fills.
4. Position cache - local cached view.
5. Working orders from REST / order gate - reserved but not filled exposure.

The reconciler publishes each snapshot to `CanonicalPortfolioStore`.  Consumers
must not independently recompute; they read the current snapshot via the store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import replace
from enum import Enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger
from merid.event_venues.base import PlacedOrder, VenuePosition
from merid.event_venues.kalshi.canonical_portfolio import (
    CanonicalFill,
    CanonicalOrder,
    CanonicalPortfolioSnapshot,
    CanonicalPortfolioStore,
    CanonicalPosition,
    FillProvenance,
    OrderProvenance,
    PaginationIncomplete,
    PositionProvenance,
    ReconciliationReason,
    ReconciliationStatus,
    SourceCompleteness,
    collect_all_pages,
    get_canonical_portfolio_store,
)
from merid.event_venues.kalshi.position_cache import get_position_cache

logger = get_logger("merid.event_venues.kalshi.canonical_portfolio_reconciler")


# Tolerance for centi-contract comparisons.
_RECONCILIATION_TOLERANCE_CC = 1


def _reason_str(reason: Any) -> str:
    """Return the string value of a ReconciliationReason (or any Enum/str)."""
    if reason is None:
        return ""
    if isinstance(reason, str):
        return reason
    if isinstance(reason, Enum):
        return str(reason.value) if reason.value is not None else str(reason)
    return str(reason)


def _ticker_to_agent(ticker: str) -> str:
    """Derive a default agent_id from a Kalshi 15m crypto ticker."""
    match = re.match(r"^KX([A-Z]+)(?:-?)(\d+[mM])", (ticker or "").upper())
    if match:
        underlying = match.group(1)
        timeframe = match.group(2).upper()
        return f"{underlying.upper()}_{timeframe.upper()}"
    return "unknown_agent"


def _first_pagination_error(
    *completeness: Optional[SourceCompleteness]
) -> Optional[str]:
    """Return the first non-success pagination error code, if any."""
    for c in completeness:
        if c is not None and not c.complete:
            return c.error_code
    return None


def _extract_position_outcome(pos: Any) -> str:
    """Return the canonical outcome (yes/no) for a position-like object.

    Handles CachedPosition, REST dicts, and other position records uniformly
    without relying on a possibly-missing ``outcome`` attribute.
    """
    if pos is None:
        return "yes"
    outcome = (
        getattr(pos, "outcome", None)
        or getattr(pos, "thesis_side", None)
        or getattr(pos, "outcome_side", None)
        or getattr(pos, "side", None)
    )
    if outcome:
        return str(outcome)
    if isinstance(pos, dict):
        return pos.get("outcome") or pos.get("side") or "yes"
    return "yes"


def _yes_exposure_cc(side: str, quantity_fp: Decimal) -> int:
    """Convert whole-contract position into signed-YES centi-contracts.

    Positive = long YES, negative = long NO.
    """
    qcc = int(quantity_fp * Decimal("100"))
    if side == "no":
        return -qcc
    return qcc


def _yes_exposure_from_qcc(side: str, qcc: int) -> int:
    """Return signed-YES centi-contracts from a raw qcc value."""
    qcc = int(qcc)
    if side == "no":
        return -qcc
    return qcc


class CanonicalPortfolioReconciler:
    """Build and publish canonical portfolio snapshots."""

    _instance: Optional["CanonicalPortfolioReconciler"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CanonicalPortfolioReconciler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._local_lock = threading.Lock()
        self._version = 0
        self._store = get_canonical_portfolio_store()

        # Kalshi client and fills ledger are fetched lazily to avoid import cycles.
        self._kalshi_client: Optional[Any] = None
        self._fills_ledger: Optional[Any] = None
        # Optional override for tests; if set, _fetch_cache_positions uses it.
        self._position_cache: Optional[Any] = None

        # Private-WS events buffered for the next snapshot.
        self._ws_positions: Dict[str, Any] = {}
        self._ws_orders: Dict[str, Any] = {}
        self._ws_fills: Dict[str, Any] = {}
        self._ws_healthy: bool = False

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 2026-08-24: Authority-transition instrumentation.  Track the previous
        # published snapshot and mismatch timing so we can emit a structured diff
        # every time authority changes.
        self._last_snapshot: Optional[CanonicalPortfolioSnapshot] = None
        self._last_authoritative_at_mono: float = 0.0
        self._first_mismatch_at_mono: Optional[float] = None
        self._last_mismatch_reason: Optional[str] = None
        self._reconcile_attempt = 0
        self._mismatch_reconcile_attempt = 0
        self._last_recovery_at_mono: Optional[float] = None
        self._last_mismatch_heartbeat_at_mono: float = 0.0
        self._recovery_state = "IDLE"

        self._initialized = True
        logger.info("[CANONICAL-PORTFOLIO-RECONCILER] initialized interval=60.0s")

    async def start(self, interval: float = 60.0) -> None:
        """Start the background reconciliation loop."""
        if self._running:
            return
        self._running = True

        async def _loop() -> None:
            while self._running:
                loop_start = time.monotonic()
                try:
                    snap = await self.build_snapshot()
                    # 2026-08-24: Bounded self-healing.  If the snapshot is non-authoritative
                    # but has complete pagination, attempt a bounded recovery before publishing.
                    if (
                        snap is not None
                        and not snap.is_authoritative
                        and snap.pagination_complete
                    ):
                        snap = await self._recover_authority(snap)
                    if snap is not None:
                        self._store.publish(snap)
                except Exception as e:
                    logger.error("[CANONICAL-RECONCILER] snapshot build failed: %s", e)
                # P0 FIX: Adaptive sleep so the next cycle starts on the requested
                # cadence, even if build_snapshot (REST calls) took a long time.
                elapsed = time.monotonic() - loop_start
                await asyncio.sleep(max(0.0, interval - elapsed))

        try:
            self._task = asyncio.create_task(_loop())
        except Exception as e:
            self._running = False
            logger.error("[CANONICAL-RECONCILER] failed to start loop: %s", e)

    async def stop(self) -> None:
        """Stop the background reconciliation loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest_position_event(self, ticker: str, event: Dict[str, Any]) -> None:
        """Ingest a private-WS position event."""
        with self._local_lock:
            self._ws_positions[ticker] = event

    def ingest_order_event(self, order_id: str, event: Dict[str, Any]) -> None:
        """Ingest a private-WS order event."""
        with self._local_lock:
            self._ws_orders[order_id] = event

    def ingest_fill_event(self, fill_id: str, event: Dict[str, Any]) -> None:
        """Ingest a private-WS fill event.

        Duplicate fill IDs are idempotent.
        """
        with self._local_lock:
            if fill_id in self._ws_fills:
                return
            self._ws_fills[fill_id] = event

    # ── Snapshot builder ───────────────────────────────────────────────────────

    async def build_snapshot(self) -> CanonicalPortfolioSnapshot:
        """Build a new canonical portfolio snapshot."""
        t0 = time.monotonic()

        # 1. Exchange positions (REST, authoritative).
        positions_result = await self._fetch_exchange_positions()
        exchange_positions = positions_result[0]
        rest_failed = exchange_positions is None
        exchange_positions = exchange_positions or {}

        # 2. Local ledger positions.
        ledger_positions = self._fetch_ledger_positions()

        # 3. Local cache positions.
        cache_positions = self._fetch_cache_positions()

        # 4. Working orders (REST + WS + order gate).
        working_orders, orders_complete = await self._fetch_working_orders()

        # 5. Pending fills from WS / HTTP.
        pending_fills, fills_complete = await self._fetch_fills()

        # Build canonical positions.  Start from exchange and merge provenance.
        positions_by_ticker: Dict[str, CanonicalPosition] = {}
        for market_id, pos in exchange_positions.items():
            ticker = market_id
            qty = Decimal(str(pos.get("quantity_fp", pos.get("contracts", 0))))
            positions_by_ticker[ticker] = CanonicalPosition(
                ticker=ticker,
                market_id=market_id,
                outcome=pos.get("outcome", "yes"),
                quantity_fp=qty,
                avg_entry_price_cents=int(pos.get("avg_price_cents", 0) or 0),
                entry_order_id=pos.get("entry_order_id"),
                entry_fill_id=pos.get("entry_fill_id"),
                provenance=PositionProvenance.EXCHANGE_REST,
                timestamp=time.monotonic(),
                yes_exposure_cc=_yes_exposure_cc(
                    pos.get("outcome", "yes"),
                    qty,
                ),
            )

        # Merge cache/ledger positions for tickers not on exchange.
        for market_id, pos in cache_positions.items():
            if market_id in positions_by_ticker:
                continue
            cache_qcc = getattr(pos, "quantity_cc", (pos.contracts or 0) * 100)
            cache_qty = Decimal(cache_qcc) / Decimal("100")
            ticker = market_id
            positions_by_ticker[ticker] = CanonicalPosition(
                ticker=ticker,
                market_id=market_id,
                outcome=_extract_position_outcome(pos),
                quantity_fp=cache_qty,
                avg_entry_price_cents=int(pos.avg_price_cents or 0),
                entry_order_id=pos.entry_order_id,
                entry_fill_id=pos.entry_fill_id,
                provenance=PositionProvenance.CACHE,
                timestamp=time.monotonic(),
                yes_exposure_cc=_yes_exposure_from_qcc(
                    _extract_position_outcome(pos),
                    cache_qcc,
                ),
            )

        for market_id, pos in ledger_positions.items():
            if market_id in positions_by_ticker:
                continue
            qty = Decimal(str(pos.get("contracts", 0)))
            ticker = market_id
            positions_by_ticker[ticker] = CanonicalPosition(
                ticker=ticker,
                market_id=market_id,
                outcome=pos.get("side", "yes"),
                quantity_fp=qty,
                avg_entry_price_cents=int(pos.get("avg_price_cents", 0) or 0),
                entry_order_id=pos.get("entry_order_id"),
                entry_fill_id=pos.get("entry_fill_id"),
                provenance=PositionProvenance.LOCAL_LEDGER,
                timestamp=time.monotonic(),
                yes_exposure_cc=_yes_exposure_cc(
                    pos.get("side", "yes"),
                    qty,
                ),
            )

        # Build canonical working orders.
        orders_by_id: Dict[str, CanonicalOrder] = {}
        for order in working_orders:
            oid = order.get("order_id") or order.get("client_order_id", "unknown")
            orders_by_id[oid] = CanonicalOrder(
                order_id=oid,
                client_order_id=order.get("client_order_id"),
                ticker=order.get("ticker", ""),
                side=order.get("side", ""),
                action=order.get("action", order.get("side", "")),
                quantity_fp=Decimal(str(order.get("quantity", 0))),
                filled_quantity_fp=Decimal(str(order.get("filled_quantity", 0))),
                remaining_quantity_fp=Decimal(str(order.get("remaining_quantity", order.get("quantity", 0)))),
                price_cents=int(order.get("price_cents", 0) or 0),
                status=order.get("status", "pending"),
                source=order.get("source", OrderProvenance.EXCHANGE_REST),
                timestamp=time.monotonic(),
            )

        # Build canonical fills.
        fills_by_id: Dict[str, CanonicalFill] = {}
        for fill in pending_fills:
            fid = fill.get("fill_id") or f"ws:{time.monotonic()}"
            fills_by_id[fid] = CanonicalFill(
                fill_id=fid,
                order_id=fill.get("order_id", ""),
                ticker=fill.get("ticker", ""),
                side=fill.get("side", ""),
                action=fill.get("action", ""),
                quantity_fp=Decimal(str(fill.get("quantity", 0))),
                price_cents=int(fill.get("price_cents", 0) or 0),
                fee_cents=int(fill.get("fee_cents", 0) or 0),
                timestamp=fill.get("timestamp", time.monotonic()),
                source=fill.get("source", FillProvenance.WS_FILL),
            )

        # Aggregate exposure.
        exchange_exposure_cc = sum(
            _yes_exposure_cc(
                pos.get("outcome", "yes"),
                Decimal(str(pos.get("quantity_fp", pos.get("contracts", 0)))),
            )
            for pos in exchange_positions.values()
        )
        ledger_exposure_cc = sum(
            _yes_exposure_cc(
                pos.get("side", "yes"),
                Decimal(str(pos.get("contracts", 0))),
            )
            for pos in ledger_positions.values()
        )
        cache_exposure_cc = sum(
            _yes_exposure_from_qcc(
                _extract_position_outcome(pos),
                getattr(pos, "quantity_cc", (pos.contracts or 0) * 100),
            )
            for pos in cache_positions.values()
        )

        reserved_exposure_cc = sum(
            _yes_exposure_cc(
                order.get("side", "yes"),
                Decimal(str(order.get("remaining_quantity", order.get("quantity", 0)))),
            )
            for order in working_orders
        )
        reserved_gross_cc = sum(
            abs(
                _yes_exposure_cc(
                    order.get("side", "yes"),
                    Decimal(str(order.get("remaining_quantity", order.get("quantity", 0)))),
                )
            )
            for order in working_orders
        )

        signed_exposure_cc = sum(
            pos.yes_exposure_cc for pos in positions_by_ticker.values()
        )
        gross_exposure_cc = sum(
            abs(pos.yes_exposure_cc) for pos in positions_by_ticker.values()
        )
        gross_notional_cents = sum(
            abs(pos.yes_exposure_cc) * max(pos.avg_entry_price_cents, 0)
            for pos in positions_by_ticker.values()
        )

        # Reconcile positions.  Missing sources are treated as zero exposure so
        # that a confirmed exchange position with an empty ledger or cache is
        # reported as a mismatch.
        mismatches: List[str] = []
        all_tickers = (
            set(positions_by_ticker.keys())
            | set(ledger_positions.keys())
            | set(cache_positions.keys())
        )
        for ticker in all_tickers:
            exp = exchange_positions.get(ticker, {})
            led = ledger_positions.get(ticker, {})
            cac = cache_positions.get(ticker)

            exp_cc = _yes_exposure_cc(
                exp.get("outcome", "yes"),
                Decimal(str(exp.get("quantity_fp", exp.get("contracts", 0)))),
            )
            led_cc = _yes_exposure_cc(
                led.get("side", "yes"),
                Decimal(str(led.get("contracts", 0))),
            )
            cac_cc = (
                _yes_exposure_from_qcc(
                    _extract_position_outcome(cac),
                    getattr(cac, "quantity_cc", (cac.contracts or 0) * 100),
                )
                if cac is not None
                else 0
            )

            if abs(exp_cc - led_cc) > _RECONCILIATION_TOLERANCE_CC:
                mismatches.append(f"{ticker}:exchange={exp_cc}:ledger={led_cc}")
            if abs(exp_cc - cac_cc) > _RECONCILIATION_TOLERANCE_CC:
                mismatches.append(f"{ticker}:exchange={exp_cc}:cache={cac_cc}")

        # Determine status and detailed reason code.
        reason = ReconciliationReason.MATCHED
        positions_complete = positions_result[1]

        pagination_error = _first_pagination_error(
            positions_complete, orders_complete, fills_complete
        )

        if rest_failed:
            status = ReconciliationStatus.UNKNOWN
            source = "no_exchange_data"
            if self._get_client() is None:
                reason = ReconciliationReason.UNKNOWN_SOURCE
            elif pagination_error == "UNKNOWN_NETWORK":
                reason = ReconciliationReason.UNKNOWN_NETWORK
            elif pagination_error:
                reason = ReconciliationReason.UNKNOWN_PAGINATION
            else:
                reason = ReconciliationReason.UNKNOWN_NETWORK
        elif mismatches:
            status = ReconciliationStatus.MISMATCH
            source = "exchange_ledger_cache_mismatch"
            if any(":ledger=" in m for m in mismatches):
                reason = ReconciliationReason.MISMATCH_LEDGER
            elif any(":cache=" in m for m in mismatches):
                reason = ReconciliationReason.MISMATCH_POSITION
            else:
                reason = ReconciliationReason.MISMATCH_POSITION
        else:
            status = ReconciliationStatus.MATCHED
            source = "exchange_rest_confirmed"

        source_age_ms = int((time.monotonic() - t0) * 1000)
        if source_age_ms > 5 * 60 * 1000:
            status = ReconciliationStatus.STALE
            reason = ReconciliationReason.STALE_REST
        # P0 FIX: Do NOT override a MATCHED/UNKNOWN status just because the private
        # WebSocket has not yet delivered events. With an empty portfolio and no
        # working orders, the REST snapshot is authoritative. Private-WS health is
        # still captured in private_ws_healthy for downstream diagnostics, but it
        # must not block new entries when paginated REST data is complete and consistent.

        pagination_complete = all([
            positions_complete is None or positions_complete.complete,
            orders_complete is None or orders_complete.complete,
            fills_complete is None or fills_complete.complete,
        ])

        # A complete exchange match with an incomplete paginated source is still
        # not authoritative for new entries.
        if not pagination_complete and status == ReconciliationStatus.MATCHED:
            status = ReconciliationStatus.UNKNOWN
            reason = ReconciliationReason.UNKNOWN_PAGINATION
            source = "incomplete_paginated_source"

        self._reconcile_attempt += 1
        self._version += 1
        # P0 FIX: Capture timestamp at the end of building so age_ms reflects the
        # time since the snapshot was actually published, not the start of a long
        # REST/build cycle.
        captured_at_wall_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        captured_at_mono_ns = int(time.monotonic() * 1e9)
        snapshot = CanonicalPortfolioSnapshot(
            version=self._version,
            captured_at_wall_ns=captured_at_wall_ns,
            captured_at_mono_ns=captured_at_mono_ns,
            positions_by_ticker=positions_by_ticker,
            working_orders_by_id=orders_by_id,
            pending_fills_by_id=fills_by_id,
            exchange_exposure_cc=exchange_exposure_cc,
            local_ledger_exposure_cc=ledger_exposure_cc,
            reserved_exposure_cc=reserved_exposure_cc,
            signed_exposure_cc=signed_exposure_cc,
            gross_exposure_cc=gross_exposure_cc,
            signed_reserved_exposure_cc=reserved_exposure_cc,
            gross_reserved_exposure_cc=reserved_gross_cc,
            gross_notional_cents=gross_notional_cents,
            reconciliation_status=status,
            reconciliation_reason=reason,
            pagination_complete=pagination_complete,
            positions_source_complete=positions_result[1],
            fills_source_complete=fills_complete,
            orders_source_complete=orders_complete,
            source=source,
            source_age_ms=source_age_ms,
            private_ws_healthy=self._is_private_ws_healthy(),
            mismatches=tuple(mismatches),
        )

        # 2026-08-24: Emit a structured authority transition log with a full diff
        # so MISMATCH_LEDGER is explainable.  We intentionally log before publish
        # so the transition event references the previous published snapshot.
        self._log_authority_transition(
            self._last_snapshot,
            snapshot,
            exchange_positions=exchange_positions or {},
            ledger_positions=ledger_positions,
            cache_positions=cache_positions,
            working_orders=working_orders,
            pending_fills=pending_fills,
        )

        self._last_snapshot = snapshot
        return snapshot

    # ── Authority transition instrumentation ───────────────────────────────────

    def _serialize_position_map(
        self,
        positions: Dict[str, Any],
        source: str,
    ) -> List[Dict[str, Any]]:
        """Convert a raw position map into a JSON-friendly list for telemetry."""
        out: List[Dict[str, Any]] = []
        for market_id, pos in positions.items():
            if pos is None:
                continue
            if isinstance(pos, dict):
                qty = pos.get("quantity_fp") or pos.get("contracts") or 0
                qty_fp = Decimal(str(qty)) if qty is not None else Decimal("0")
                out.append({
                    "ticker": market_id,
                    "outcome": pos.get("outcome", pos.get("side", "yes")),
                    "quantity_fp": str(qty_fp),
                    "quantity_cc": int(qty_fp * Decimal("100")),
                    "avg_price_cents": int(pos.get("avg_price_cents", 0) or 0),
                    "source": str(pos.get("source", source)),
                    "entry_order_id": pos.get("entry_order_id"),
                    "entry_fill_id": pos.get("entry_fill_id"),
                })
            else:
                try:
                    qty = getattr(pos, "quantity_fp", None) or getattr(pos, "contracts", 0)
                    qty_fp = Decimal(str(qty)) if qty is not None else Decimal("0")
                    out.append({
                        "ticker": market_id,
                        "outcome": getattr(pos, "outcome", getattr(pos, "side", "yes")) or "yes",
                        "quantity_fp": str(qty_fp),
                        "quantity_cc": int(qty_fp * Decimal("100")),
                        "avg_price_cents": int(getattr(pos, "avg_price_cents", 0) or 0),
                        "source": str(source),
                        "entry_order_id": getattr(pos, "entry_order_id", None),
                        "entry_fill_id": getattr(pos, "entry_fill_id", None),
                    })
                except Exception:
                    out.append({"ticker": market_id, "source": source, "raw": repr(pos)})
        return out

    def _notional_cents(self, positions: List[Dict[str, Any]]) -> int:
        """Return gross notional cents for a serialized position list."""
        return sum(abs(p.get("quantity_cc", 0)) * p.get("avg_price_cents", 0) for p in positions)

    def _unmatched_items(
        self,
        positions: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
        fills: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Return unmatched orders/fills relative to the provided position map.

        An order or fill is unmatched when no position in the supplied map has the
        same ticker.  This is a lightweight diagnostic, not a full reconciliation;
        it helps identify rejected/cancelled orders or fills not yet reflected in
        positions.
        """
        position_tickers = {p.get("ticker") for p in positions if p.get("ticker")}
        unmatched_orders: List[Dict[str, Any]] = []
        unmatched_fills: List[Dict[str, Any]] = []
        for order in orders:
            ticker = order.get("ticker")
            if not ticker or ticker not in position_tickers:
                unmatched_orders.append({
                    "order_id": order.get("order_id"),
                    "client_order_id": order.get("client_order_id"),
                    "ticker": ticker,
                    "side": order.get("side"),
                    "remaining_quantity_fp": str(order.get("remaining_quantity")),
                    "source": order.get("source", "unknown"),
                })
        for fill in fills:
            ticker = fill.get("ticker")
            if not ticker or ticker not in position_tickers:
                unmatched_fills.append({
                    "fill_id": fill.get("fill_id"),
                    "order_id": fill.get("order_id"),
                    "ticker": ticker,
                    "side": fill.get("side"),
                    "quantity_fp": str(fill.get("quantity")),
                    "source": fill.get("source", "unknown"),
                })
        return unmatched_orders, unmatched_fills

    def _diff_hash(self, payload: Dict[str, Any]) -> str:
        """Return a stable hash of the authority diff payload."""

        def _serialize(obj: Any) -> Any:
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, (set, frozenset, tuple)):
                return sorted(_serialize(x) for x in obj)
            if isinstance(obj, list):
                return [_serialize(x) for x in obj]
            if isinstance(obj, dict):
                return {str(k): _serialize(v) for k, v in obj.items()}
            if isinstance(obj, Enum):
                return str(obj.value) if obj.value is not None else str(obj)
            return obj

        try:
            serialized = _serialize(payload)
            return hashlib.sha256(
                json.dumps(serialized, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
        except Exception:
            return "unhashable"

    def _terminalize_impossible_local_intents(
        self,
        mismatch_tickers: List[str],
        open_order_ids: List[str],
        open_client_order_ids: List[str],
    ) -> int:
        """Release PENDING canonical records that cannot have live exchange orders.

        A record is considered impossible when:
        - its ticker is in the mismatch set;
        - it is still PENDING (not submitted or submitted but with no execution);
        - it has no matching open order by client_order_id or order_id;
        - it has been PENDING for longer than the submission grace period.

        This is intentionally conservative: it does NOT release records for tickers
        that agree with the exchange, and it does NOT release records that may just
        be in-flight.
        """
        try:
            from merid.event_venues.kalshi.order_intent_contract import (
                _accepted_entry_intents,
                _entry_idempotency_lock,
                release_entry_idempotency_by_key,
            )
        except Exception:
            return 0

        now = time.time()
        grace_s = float(os.getenv("MERID_RECONCILE_INTENT_GRACE_S", "5.0"))
        released = 0
        mismatch_set = set(mismatch_tickers)
        open_client_ids = set(open_client_order_ids)
        open_ids = set(open_order_ids)

        with _entry_idempotency_lock:
            for (ticker, contract), rec in list(_accepted_entry_intents.items()):
                if ticker not in mismatch_set:
                    continue
                status = rec.get("status")
                submitted = rec.get("submitted", False)
                has_execution = rec.get("has_execution", False)
                coid = rec.get("client_order_id")
                oid = rec.get("order_id")
                age_s = now - rec.get("ts", now)

                if status == "rejected":
                    release_entry_idempotency_by_key(ticker, contract)
                    released += 1
                    continue

                if submitted or has_execution:
                    # Could be in-flight; leave it for the next attempt.
                    continue

                if age_s < grace_s:
                    # In-flight pre-submit; be patient.
                    continue

                if coid in open_client_ids or oid in open_ids:
                    # Exchange still knows about it; do not release.
                    continue

                release_entry_idempotency_by_key(ticker, contract)
                released += 1

        return released

    async def _rebuild_affected_cache_and_reservations(
        self,
        mismatch_tickers: List[str],
        open_orders: List[Dict[str, Any]],
    ) -> None:
        """Attempt to rebuild cache for mismatching tickers from the fills ledger.

        This is a conservative, first-principles recovery: the fills ledger is the
        canonical source of truth for executed exposure.  For each affected ticker:

        1. Recompute the position from the ledger deterministically.
        2. If the recomputed position differs materially from the cache, force-sync
           the cache to the ledger-derived view.
        3. Release any stale order-group / slot reservations for tickers that have
           no working exchange order and no unapplied fill in the ledger.

        The method is gated by ``MERID_RECONCILER_ALLOW_CACHE_REBUILD`` (default
        ``true``) so it can be disabled if it ever makes a bad problem worse.
        """
        if os.getenv("MERID_RECONCILER_ALLOW_CACHE_REBUILD", "true").lower() in ("0", "false", "no"):
            logger.warning(
                "[CANONICAL-RECONCILER] Cache rebuild disabled by MERID_RECONCILER_ALLOW_CACHE_REBUILD"
            )
            return

        try:
            cache = get_position_cache()
        except Exception as e:
            logger.warning("[CANONICAL-RECONCILER] Position cache unavailable: %s", e)
            return

        open_order_tickers = {o.get("market_id") or o.get("ticker") for o in open_orders}
        open_order_tickers.discard(None)

        for ticker in mismatch_tickers:
            try:
                agent_id = _ticker_to_agent(ticker)

                recomputed = await cache.recompute_position_from_ledger(ticker, agent_id)
                if recomputed is None:
                    # No fills for this ticker.  If the cache still has a position and
                    # the exchange shows none and there are no open orders, the cache
                    # entry is a phantom and we can remove it under cleanup_stale.
                    if (
                        cache.get_position(ticker) is not None
                        and ticker not in open_order_tickers
                    ):
                        logger.warning(
                            "[PORTFOLIO-AUTHORITY-REBUILD] ticker=%s no ledger fills, no open orders, "
                            "removing phantom cache entry",
                            ticker,
                        )
                        await cache.sync_from_rest(
                            [],
                            rest_timestamp=time.time(),
                            force=True,
                            open_orders=open_orders,
                            cleanup_stale=True,
                        )
                    continue

                # Convert the recomputed CachedPosition into a REST-style dict that
                # ``sync_from_rest`` can consume.  We only include fields that survive
                # the sync path and keep any existing TP/SL targets.
                existing = cache.get_position(ticker)
                existing_tp = getattr(existing, "take_profit_price_cents", None)
                existing_sl = getattr(existing, "stop_loss_price_cents", None)

                pos_dict = {
                    "market_id": recomputed.market_id,
                    "contracts": int(recomputed.contracts),
                    "quantity_cc": int(recomputed.quantity_cc or (recomputed.contracts * 100)),
                    "side": recomputed.thesis_side or "yes",
                    "thesis_side": recomputed.thesis_side or "yes",
                    "outcome_side": recomputed.outcome_side or recomputed.thesis_side or "yes",
                    "avg_price_cents": recomputed.avg_price_cents,
                    "entry_price_state": getattr(recomputed, "entry_price_state", "unknown"),
                    "take_profit_price_cents": getattr(recomputed, "take_profit_price_cents", None) or existing_tp,
                    "stop_loss_price_cents": getattr(recomputed, "stop_loss_price_cents", None) or existing_sl,
                }

                logger.warning(
                    "[PORTFOLIO-AUTHORITY-REBUILD] ticker=%s agent=%s "
                    "recomputed_contracts=%d side=%s avg_price=%s tp=%s sl=%s",
                    ticker,
                    agent_id,
                    pos_dict["contracts"],
                    pos_dict["side"],
                    pos_dict["avg_price_cents"],
                    pos_dict["take_profit_price_cents"],
                    pos_dict["stop_loss_price_cents"],
                )

                await cache.sync_from_rest(
                    [pos_dict],
                    rest_timestamp=time.time(),
                    force=True,
                    open_orders=open_orders,
                    cleanup_stale=False,
                )

            except Exception as e:
                logger.error(
                    "[PORTFOLIO-AUTHORITY-REBUILD] Failed to rebuild ticker=%s: %s",
                    ticker,
                    e,
                    exc_info=True,
        )

    async def _recover_authority(
        self,
        initial: CanonicalPortfolioSnapshot,
    ) -> CanonicalPortfolioSnapshot:
        """Bounded recovery from a non-authoritative snapshot.

        Implements a simple state machine:
            MISMATCH_DETECTED -> RECONCILING -> RECOVERED | QUARANTINED

        On each retry we refetch the authoritative exchange snapshot, terminalize
        any local PENDING intents that cannot possibly have a live exchange order,
        and rebuild the snapshot.  If the snapshot is still non-authoritative after
        all retries, the recovery state is set to QUARANTINED and the final snapshot
        is returned.
        """
        self._recovery_state = "MISMATCH_DETECTED"
        delays = [0.25, 1.0, 3.0]
        self._last_mismatch_reason = _reason_str(initial.reconciliation_reason)
        recovery_started_at = time.monotonic()

        exchange_oids = list(initial.working_orders_by_id.keys())
        client_oids = [
            o.client_order_id
            for o in initial.working_orders_by_id.values()
            if o.client_order_id
        ]

        # Extract the mismatching tickers from the initial snapshot.
        mismatch_tickers = [
            m.split(":", 1)[0]
            for m in (initial.mismatches or ())
            if ":" in m
        ]

        for attempt, delay in enumerate(delays, start=1):
            self._mismatch_reconcile_attempt += 1
            self._recovery_state = "RECONCILING"
            try:
                await asyncio.sleep(delay)

                # Attempt to clean up impossible local state and rebuild affected
                # cache before refetching exchange data.
                self._terminalize_impossible_local_intents(
                    mismatch_tickers,
                    exchange_oids,
                    client_oids,
                )
                working_order_dicts = [
                    {
                        "order_id": o.order_id,
                        "client_order_id": o.client_order_id,
                        "market_id": o.ticker,
                        "ticker": o.ticker,
                        "side": o.side,
                        "action": o.action,
                        "contracts": int(o.remaining_quantity_fp),
                        "quantity_fp": o.remaining_quantity_fp,
                        "price_cents": o.price_cents,
                        "status": o.status,
                    }
                    for o in (initial.working_orders_by_id or {}).values()
                ]
                await self._rebuild_affected_cache_and_reservations(
                    mismatch_tickers,
                    working_order_dicts,
                )

                snapshot = await self.build_snapshot()
                if snapshot.is_authoritative:
                    self._last_recovery_at_mono = time.monotonic()
                    self._last_mismatch_reason = None
                    self._first_mismatch_at_mono = None
                    self._recovery_state = "RECOVERED"
                    recovery_latency_ms = int(
                        (self._last_recovery_at_mono - recovery_started_at) * 1000
                    )
                    logger.warning(
                        "PORTFOLIO-AUTHORITY-RECOVERY "
                        "state=RECOVERED previous_reason=%s recovery_attempt=%d "
                        "recovery_latency_ms=%d version=%d",
                        _reason_str(initial.reconciliation_reason),
                        attempt,
                        recovery_latency_ms,
                        snapshot.version,
                        extra={
                            "event": "PORTFOLIO-AUTHORITY-RECOVERY",
                            "state": "RECOVERED",
                            "previous_reason": _reason_str(initial.reconciliation_reason),
                            "recovery_attempt": attempt,
                            "recovery_latency_ms": recovery_latency_ms,
                            "version": snapshot.version,
                        },
                    )
                    return snapshot
            except Exception as e:
                logger.error(
                    "[CANONICAL-RECONCILER] Authority recovery attempt %d failed: %s",
                    attempt,
                    e,
                )

        self._recovery_state = "QUARANTINED"
        logger.error(
            "PORTFOLIO-AUTHORITY-RECOVERY "
            "state=QUARANTINED previous_reason=%s recovery_attempts=%d "
            "version=%d",
            _reason_str(initial.reconciliation_reason),
            len(delays),
            initial.version,
            extra={
                "event": "PORTFOLIO-AUTHORITY-RECOVERY",
                "state": "QUARANTINED",
                "previous_reason": _reason_str(initial.reconciliation_reason),
                "recovery_attempts": len(delays),
                "version": initial.version,
            },
        )
        return initial

    def _log_authority_transition(
        self,
        old: Optional[CanonicalPortfolioSnapshot],
        new: CanonicalPortfolioSnapshot,
        exchange_positions: Dict[str, Dict[str, Any]],
        ledger_positions: Dict[str, Dict[str, Any]],
        cache_positions: Dict[str, Any],
        working_orders: List[Dict[str, Any]],
        pending_fills: List[Dict[str, Any]],
    ) -> None:
        """Emit a structured authority-transition event with a full diff.

        This is the priority-one observability fix for MISMATCH_LEDGER: the log
        must explain *why* the portfolio became non-authoritative so an operator
        can determine whether the discrepancy is a stale order, a missing fill,
        an expired window, or a representation mismatch.

        State tracking is updated on every call so ``_last_authoritative_at_mono``
        always reflects the most recent matched snapshot and
        ``_first_mismatch_at_mono`` is reset when authority is restored.  Paired
        ``state=MISMATCH`` / ``state=RECOVERED`` events are emitted so the
        recovery latency and the diff that preceded it can be correlated.
        """
        old_authoritative = bool(old.is_authoritative) if old is not None else True
        new_authoritative = bool(new.is_authoritative)
        reason = _reason_str(new.reconciliation_reason)

        exchange_pos_list = self._serialize_position_map(exchange_positions, "exchange_rest")
        ledger_pos_list = self._serialize_position_map(ledger_positions, "local_ledger")
        cache_pos_list = self._serialize_position_map(cache_positions, "cache")

        exchange_orders = [
            o for o in working_orders if o.get("source") == OrderProvenance.EXCHANGE_REST
        ]
        ledger_orders = [
            o for o in working_orders if o.get("source") == OrderProvenance.LOCAL_GATE
        ]
        cache_orders: List[Dict[str, Any]] = []  # Cache does not track open orders.

        unmatched_orders, unmatched_fills = self._unmatched_items(
            exchange_pos_list, working_orders, pending_fills
        )

        diff_payload = {
            "exchange_positions": exchange_pos_list,
            "ledger_positions": ledger_pos_list,
            "cache_positions": cache_pos_list,
            "exchange_open_orders": exchange_orders,
            "ledger_open_orders": ledger_orders,
            "unmatched_fills": unmatched_fills,
            "unmatched_orders": unmatched_orders,
            "mismatches": list(new.mismatches),
        }
        diff_hash = self._diff_hash(diff_payload)

        if new_authoritative:
            self._last_authoritative_at_mono = time.monotonic()
            if old is not None and not old.is_authoritative:
                # Transition back to authority: clear mismatch tracking.
                first_mismatch_at = self._first_mismatch_at_mono
                previous_reason = self._last_mismatch_reason or _reason_str(old.reconciliation_reason)
                self._first_mismatch_at_mono = None
                self._last_mismatch_reason = None
                self._last_recovery_at_mono = time.monotonic()
                recovery_latency_ms = (
                    int((self._last_recovery_at_mono - first_mismatch_at) * 1000)
                    if first_mismatch_at is not None
                    else -1
                )
                logger.warning(
                    "PORTFOLIO-AUTHORITY-TRANSITION "
                    "state=RECOVERED old_authoritative=false new_authoritative=true "
                    "reason=%s previous_reason=%s reconcile_attempt=%d "
                    "recovery_latency_ms=%d diff_hash=%s version=%d",
                    reason,
                    previous_reason,
                    self._reconcile_attempt,
                    recovery_latency_ms,
                    diff_hash,
                    new.version,
                    extra={
                        "event": "PORTFOLIO-AUTHORITY-TRANSITION",
                        "state": "RECOVERED",
                        "old_authoritative": False,
                        "new_authoritative": True,
                        "reason": reason,
                        "previous_reason": previous_reason,
                        "version": new.version,
                        "reconcile_attempt": self._reconcile_attempt,
                        "recovery_latency_ms": recovery_latency_ms,
                        "diff_hash": diff_hash,
                        "diff_payload": diff_payload,
                        "last_successful_reconcile_at": self._last_authoritative_at_mono,
                        "first_mismatch_at": first_mismatch_at,
                    },
                )
            else:
                # Already authoritative; no transition, but emit a quiet heartbeat
                # with the current attempt and diff hash for correlation.
                logger.debug(
                    "PORTFOLIO-AUTHORITY-TRANSITION "
                    "state=AUTHORITATIVE reason=%s reconcile_attempt=%d diff_hash=%s version=%d",
                    reason,
                    self._reconcile_attempt,
                    diff_hash,
                    new.version,
                    extra={
                        "event": "PORTFOLIO-AUTHORITY-TRANSITION",
                        "state": "AUTHORITATIVE",
                        "old_authoritative": True,
                        "new_authoritative": True,
                        "reason": reason,
                        "version": new.version,
                        "reconcile_attempt": self._reconcile_attempt,
                        "diff_hash": diff_hash,
                    },
                )
            return

        # Transition into non-authority (or continued non-authority).
        if self._first_mismatch_at_mono is None:
            self._first_mismatch_at_mono = time.monotonic()
        self._last_mismatch_reason = reason

        # Emit the full structured diff on a state transition into mismatch.
        # For continued mismatch, emit a throttled summary so operators can see
        # how many reconciliation attempts have passed without recovery.
        if old_authoritative == new_authoritative:
            now = time.monotonic()
            mismatch_age_ms = int((now - (self._first_mismatch_at_mono or 0)) * 1000)
            if now - self._last_mismatch_heartbeat_at_mono < 30.0:
                return
            self._last_mismatch_heartbeat_at_mono = now
            logger.warning(
                "PORTFOLIO-AUTHORITY-TRANSITION "
                "state=MISMATCH_PERSISTENT old_authoritative=false new_authoritative=false "
                "reason=%s reconcile_attempt=%d mismatch_age_ms=%d diff_hash=%s version=%d",
                reason,
                self._reconcile_attempt,
                mismatch_age_ms,
                diff_hash,
                new.version,
                extra={
                    "event": "PORTFOLIO-AUTHORITY-TRANSITION",
                    "state": "MISMATCH_PERSISTENT",
                    "old_authoritative": False,
                    "new_authoritative": False,
                    "reason": reason,
                    "version": new.version,
                    "reconcile_attempt": self._reconcile_attempt,
                    "mismatch_age_ms": mismatch_age_ms,
                    "diff_hash": diff_hash,
                    "diff_payload": diff_payload,
                },
            )
            return

        logger.warning(
            "PORTFOLIO-AUTHORITY-TRANSITION "
            "state=MISMATCH old_authoritative=%s new_authoritative=false "
            "reason=%s reconcile_attempt=%d diff_hash=%s version=%d "
            "exchange_positions=%s ledger_positions=%s cache_positions=%s "
            "exchange_open_orders=%s ledger_open_orders=%s cache_open_orders=%s "
            "unmatched_fills=%s unmatched_orders=%s "
            "notional_exchange_cents=%d notional_ledger_cents=%d notional_cache_cents=%d "
            "first_mismatch_at=%.3f last_successful_reconcile_at=%.3f",
            old_authoritative,
            reason,
            self._reconcile_attempt,
            diff_hash,
            new.version,
            exchange_pos_list,
            ledger_pos_list,
            cache_pos_list,
            exchange_orders,
            ledger_orders,
            cache_orders,
            unmatched_fills,
            unmatched_orders,
            self._notional_cents(exchange_pos_list),
            self._notional_cents(ledger_pos_list),
            self._notional_cents(cache_pos_list),
            self._first_mismatch_at_mono,
            self._last_authoritative_at_mono,
            extra={
                "event": "PORTFOLIO-AUTHORITY-TRANSITION",
                "state": "MISMATCH",
                "old_authoritative": old_authoritative,
                "new_authoritative": False,
                "reason": reason,
                "version": new.version,
                "reconcile_attempt": self._reconcile_attempt,
                "diff_hash": diff_hash,
                "diff_payload": diff_payload,
                "exchange_positions": exchange_pos_list,
                "ledger_positions": ledger_pos_list,
                "cache_positions": cache_pos_list,
                "exchange_open_orders": exchange_orders,
                "ledger_open_orders": ledger_orders,
                "cache_open_orders": cache_orders,
                "unmatched_fills": unmatched_fills,
                "unmatched_orders": unmatched_orders,
                "notional_exchange_cents": self._notional_cents(exchange_pos_list),
                "notional_ledger_cents": self._notional_cents(ledger_pos_list),
                "notional_cache_cents": self._notional_cents(cache_pos_list),
                "first_mismatch_at": self._first_mismatch_at_mono,
                "last_successful_reconcile_at": self._last_authoritative_at_mono,
            },
        )

    # ── Data fetchers ──────────────────────────────────────────────────────────

    async def _fetch_exchange_positions(
        self,
    ) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[SourceCompleteness]]:
        """Fetch positions from Kalshi authenticated REST API.

        Returns ``({}, None)`` when the client is unavailable, and ``(None,
        SourceCompleteness)`` when the fetch itself fails.  A non-empty dict is the
        authoritative position set; an empty dict with ``complete=True`` means the
        exchange confirmed zero open positions.
        """
        client = self._get_client()
        if client is None:
            return {}, None
        try:
            started = time.time_ns()
            if hasattr(client, "get_positions_result"):
                result = await client.get_positions_result()
                complete = SourceCompleteness(
                    source="exchange_rest",
                    complete=result.success and not result.metadata.get("truncated"),
                    pages_fetched=result.metadata.get("pages_fetched", 1),
                    records_fetched=len(result.data or []),
                    request_started_ns=started,
                    request_completed_ns=time.time_ns(),
                    error_code=None if result.success else str(result.error),
                )
                if not result.success and not result.data:
                    return None, complete
                positions = result.data or []
            else:
                positions = await client.get_positions()
                complete = SourceCompleteness(
                    source="exchange_rest",
                    complete=True,
                    pages_fetched=1,
                    records_fetched=len(positions),
                    request_started_ns=started,
                    request_completed_ns=time.time_ns(),
                )

            return {
                pos.market_id: {
                    "market_id": pos.market_id,
                    "outcome": pos.outcome_id or "yes",
                    "contracts": float(pos.size) if pos.size else 0.0,
                    "quantity_fp": Decimal(str(pos.size)) if pos.size else Decimal("0"),
                    "avg_price_cents": int(
                        (pos.average_entry_price * Decimal("100")).to_integral_value()
                    )
                    if pos.average_entry_price
                    else 0,
                    "source": PositionProvenance.EXCHANGE_REST,
                }
                for pos in positions
                if pos.size and Decimal(str(pos.size)) != Decimal("0")
            }, complete
        except Exception as e:
            logger.error("[CANONICAL-RECONCILER] exchange positions fetch failed: %s", e)
            return None, SourceCompleteness(
                source="exchange_rest",
                complete=False,
                request_started_ns=started,
                request_completed_ns=time.time_ns(),
                error_code="UNKNOWN_NETWORK",
            )

    def _fetch_ledger_positions(self) -> Dict[str, Dict[str, Any]]:
        """Fetch positions from local fills ledger."""
        ledger = self._get_fills_ledger()
        if ledger is None:
            return {}
        try:
            return ledger.compute_net_positions(since_hours=24)
        except Exception as e:
            logger.error("[CANONICAL-RECONCILER] ledger positions fetch failed: %s", e)
            return {}

    def _fetch_cache_positions(self) -> Dict[str, Any]:
        """Fetch positions from local cache (or test override)."""
        if self._position_cache is not None:
            try:
                return self._position_cache.get_all_positions(validate_freshness=False)
            except Exception:
                return {}
        try:
            cache = get_position_cache()
            return cache.get_all_positions(validate_freshness=False)
        except Exception as e:
            logger.error("[CANONICAL-RECONCILER] cache positions fetch failed: %s", e)
            return {}

    async def _fetch_working_orders(
        self,
    ) -> Tuple[List[Dict[str, Any]], Optional[SourceCompleteness]]:
        """Fetch working orders from exchange REST, order gate, and WS."""
        client = self._get_client()
        rest_orders: List[Dict[str, Any]] = []
        complete: Optional[SourceCompleteness] = None
        started = time.time_ns()

        if client is not None:
            try:
                if hasattr(client, "get_open_orders_result"):
                    result = await client.get_open_orders_result()
                    complete = SourceCompleteness(
                        source="exchange_rest_orders",
                        complete=result.success and not result.metadata.get("truncated"),
                        pages_fetched=result.metadata.get("pages_fetched", 1),
                        records_fetched=len(result.data or []),
                        request_started_ns=started,
                        request_completed_ns=time.time_ns(),
                        error_code=None if result.success else str(result.error),
                    )
                    if not result.success and not result.data:
                        return [], complete
                    placed_orders = result.data or []
                else:
                    placed_orders = await client.get_open_orders()
                    complete = SourceCompleteness(
                        source="exchange_rest_orders",
                        complete=True,
                        pages_fetched=1,
                        records_fetched=len(placed_orders),
                        request_started_ns=started,
                        request_completed_ns=time.time_ns(),
                    )

                for o in placed_orders:
                    if not isinstance(o, PlacedOrder):
                        continue
                    if o.status not in ("pending", "partially_filled", "resting"):
                        continue
                    remaining = (
                        o.remaining_size
                        if o.remaining_size is not None
                        else o.size - o.filled_size
                    )
                    rest_orders.append({
                        "order_id": o.order_id,
                        "client_order_id": None,
                        "ticker": o.market_id,
                        "side": o.side,
                        "action": o.side,
                        "quantity": o.size,
                        "filled_quantity": o.filled_size,
                        "remaining_quantity": remaining,
                        "price_cents": int((o.price * Decimal("100")).to_integral_value())
                        if o.price
                        else 0,
                        "status": o.status,
                        "source": OrderProvenance.EXCHANGE_REST,
                    })
            except Exception as e:
                logger.error("[CANONICAL-RECONCILER] working orders fetch failed: %s", e)
                complete = SourceCompleteness(
                    source="exchange_rest_orders",
                    complete=False,
                    request_started_ns=started,
                    request_completed_ns=time.time_ns(),
                    error_code="PAGE_FETCH_FAILED",
                )

        # Merge with locally-tracked orders from the order gate or WS.
        with self._local_lock:
            ws_orders = list(self._ws_orders.values())

        merged = {o["order_id"]: o for o in rest_orders}
        for o in ws_orders:
            oid = o.get("order_id")
            if oid and oid not in merged:
                merged[oid] = o

        return list(merged.values()), complete

    async def _fetch_fills(
        self,
    ) -> Tuple[List[Dict[str, Any]], Optional[SourceCompleteness]]:
        """Return pending fills (WS events and, when available, REST fills)."""
        with self._local_lock:
            ws_fills = list(self._ws_fills.values())

        client = self._get_client()
        complete = SourceCompleteness(
            source="ws_fills",
            complete=True,
            records_fetched=len(ws_fills),
            request_started_ns=time.time_ns(),
            request_completed_ns=time.time_ns(),
        )

        if client is not None and hasattr(client, "get_fills"):
            try:
                started = time.time_ns()
                result = await client.get_fills()
                if result.success:
                    complete = SourceCompleteness(
                        source="exchange_rest_fills",
                        complete=not result.metadata.get("truncated"),
                        pages_fetched=result.metadata.get("pages_fetched", 1),
                        records_fetched=len(result.data or []),
                        request_started_ns=started,
                        request_completed_ns=time.time_ns(),
                    )
                else:
                    err = result.error
                    code = err.error_code if isinstance(err, PaginationIncomplete) else "PAGE_FETCH_FAILED"
                    complete = SourceCompleteness(
                        source="exchange_rest_fills",
                        complete=False,
                        request_started_ns=started,
                        request_completed_ns=time.time_ns(),
                        error_code=code,
                    )
            except Exception as e:
                logger.error("[CANONICAL-RECONCILER] REST fills fetch failed: %s", e)
                complete = SourceCompleteness(
                    source="exchange_rest_fills",
                    complete=False,
                    request_started_ns=started,
                    request_completed_ns=time.time_ns(),
                    error_code="PAGE_FETCH_FAILED",
                )

        return ws_fills, complete

    def _is_private_ws_healthy(self) -> bool:
        with self._local_lock:
            return self._ws_healthy

    # ── Lazy accessors to avoid import cycles ──────────────────────────────────

    def _get_client(self) -> Optional[Any]:
        if self._kalshi_client is None:
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                self._kalshi_client = get_kalshi_client()
            except Exception:
                pass
        return self._kalshi_client

    def _get_fills_ledger(self) -> Optional[Any]:
        if self._fills_ledger is None:
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                self._fills_ledger = get_fills_ledger()
            except Exception:
                pass
        return self._fills_ledger


def get_canonical_portfolio_reconciler() -> CanonicalPortfolioReconciler:
    """Return the global canonical portfolio reconciler singleton."""
    return CanonicalPortfolioReconciler()
