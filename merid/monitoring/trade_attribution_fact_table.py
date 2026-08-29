"""Trade attribution fact table — unified intent→order→fill→settlement→P&L.

This is a single append-only fact table that joins the full lifecycle of a
15m trading decision.  Each lifecycle event (intent, order, fill, settlement)
is stored as one row keyed by ``intent_id`` and ``client_order_id`` so the
history is immutable and auditable.  A materialized view / query layer can
roll these up into one row per decision.

Design guarantees:
- Non-blocking to the trading loop: record_* methods append to an in-memory
  queue and return immediately.
- Exception-safe: any persistence failure is logged and swallowed; it never
  raises back into the order/fill/settlement path.
- Immutable: rows are never updated or deleted.  Settlement/fill updates are
  new rows with the same ``intent_id`` / ``client_order_id``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("merid.monitoring.trade_attribution_fact_table")


# Default to a sibling of the fills DB so backup / replication policies line up.
_DEFAULT_DB_PATH = "data/trade_attribution_fact.db"
_FLUSH_INTERVAL_SECONDS = 1.0
_QUEUE_SIZE_WARN = 1000


class TradeAttributionTable:
    """Singleton append-only fact table for the 15m trade lifecycle."""

    _instance: Optional[TradeAttributionTable] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or os.getenv(
            "MERID_TRADE_ATTRIBUTION_DB_PATH", _DEFAULT_DB_PATH
        )
        self._queue: deque[Dict[str, Any]] = deque()
        self._queue_lock = threading.Lock()
        self._writer_task: Optional[asyncio.Task] = None
        self._running = False
        self._initialized = False

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> TradeAttributionTable:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (test isolation only)."""
        with cls._lock:
            cls._instance = None

    def _append(self, event_type: str, row: Dict[str, Any]) -> None:
        """Append a row to the in-memory queue; never blocks or raises."""
        try:
            row = self._sanitize(row)
            row["event_type"] = event_type
            row["event_ts"] = datetime.now(timezone.utc).isoformat()
            with self._queue_lock:
                self._queue.append(row)
                if len(self._queue) >= _QUEUE_SIZE_WARN:
                    logger.warning(
                        "[TRADE-ATTRIBUTION] queue size=%d; writer may be behind",
                        len(self._queue),
                    )
        except Exception as e:
            logger.warning("[TRADE-ATTRIBUTION] failed to queue %s: %s", event_type, e)

    def _sanitize(self, value: Any) -> Any:
        """Make values SQLite-serializable in place."""
        if isinstance(value, dict):
            return {k: self._sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize(v) for v in value]
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if is_dataclass(value) and not isinstance(value, type):
            return self._sanitize(asdict(value))
        return value

    async def start(self) -> None:
        """Create schema and start background writer."""
        if self._running:
            return
        self._running = True
        await self._init_db()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="trade_attribution_writer"
        )
        logger.info("[TRADE-ATTRIBUTION] started writer db=%s", self._db_path)

    async def stop(self) -> None:
        """Flush remaining rows and stop writer."""
        self._running = False
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def _writer_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(_FLUSH_INTERVAL_SECONDS)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[TRADE-ATTRIBUTION] writer loop error: %s", e)

    async def _init_db(self) -> None:
        if self._initialized:
            return
        try:
            import aiosqlite

            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                await db.execute("PRAGMA synchronous=NORMAL;")
                await db.execute("PRAGMA busy_timeout=5000;")
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS trade_attribution_fact (
                        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        event_ts TEXT,
                        run_id TEXT,
                        process_id TEXT,
                        signal_id TEXT,
                        intent_id TEXT,
                        client_order_id TEXT,
                        order_id TEXT,
                        fill_id TEXT,
                        ticker TEXT,
                        asset TEXT,
                        side TEXT,
                        action TEXT,
                        price_cents INTEGER,
                        count_fp TEXT,
                        quantity_cc INTEGER,
                        order_type TEXT,
                        time_in_force TEXT,
                        post_only INTEGER,
                        reduce_only INTEGER,
                        cancel_order_on_pause INTEGER,
                        self_trade_prevention_type TEXT,
                        max_execution_cost_cents INTEGER,
                        take_profit_price_cents INTEGER,
                        stop_loss_price_cents INTEGER,
                        source TEXT,
                        order_status TEXT,
                        fill_quantity_cc INTEGER,
                        avg_fill_price_cents INTEGER,
                        fee_cost_cents INTEGER,
                        realized_pnl_cents INTEGER,
                        settlement_outcome TEXT,
                        settlement_price_cents INTEGER,
                        settlement_ts TEXT,
                        rejection_reason TEXT,
                        error TEXT,
                        metadata TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_intent
                    ON trade_attribution_fact (intent_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_client_order
                    ON trade_attribution_fact (client_order_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_order
                    ON trade_attribution_fact (order_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_fill
                    ON trade_attribution_fact (fill_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_ticker
                    ON trade_attribution_fact (ticker)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trade_attribution_run
                    ON trade_attribution_fact (run_id)
                """)
                await db.commit()
            self._initialized = True
            logger.info("[TRADE-ATTRIBUTION] schema initialized")
        except Exception as e:
            logger.error("[TRADE-ATTRIBUTION] schema init failed: %s", e)

    async def flush(self) -> None:
        """Flush queued rows to SQLite."""
        if not self._initialized:
            try:
                await self._init_db()
            except Exception:
                logger.error("[TRADE-ATTRIBUTION] init failed; rows remain queued")
                return
            if not self._initialized:
                return

        rows: List[Dict[str, Any]] = []
        with self._queue_lock:
            rows = list(self._queue)
            self._queue.clear()

        if not rows:
            return

        columns = [
            "event_type", "event_ts", "run_id", "process_id", "signal_id",
            "intent_id", "client_order_id", "order_id", "fill_id", "ticker",
            "asset", "side", "action", "price_cents", "count_fp", "quantity_cc",
            "order_type", "time_in_force", "post_only", "reduce_only",
            "cancel_order_on_pause", "self_trade_prevention_type",
            "max_execution_cost_cents", "take_profit_price_cents",
            "stop_loss_price_cents", "source", "order_status", "fill_quantity_cc",
            "avg_fill_price_cents", "fee_cost_cents", "realized_pnl_cents",
            "settlement_outcome", "settlement_price_cents", "settlement_ts",
            "rejection_reason", "error", "metadata",
        ]
        placeholders = ",".join("?" * len(columns))
        sql = f"INSERT INTO trade_attribution_fact ({','.join(columns)}) VALUES ({placeholders})"

        try:
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000;")
                for row in rows:
                    values = [row.get(c) for c in columns]
                    await db.execute(sql, values)
                await db.commit()
            logger.debug("[TRADE-ATTRIBUTION] flushed %d rows", len(rows))
        except Exception as e:
            logger.error("[TRADE-ATTRIBUTION] flush failed: %s", e)
            # Re-queue so we don't silently lose rows; bounded to avoid memory blow.
            with self._queue_lock:
                self._queue.extend(rows)
                while len(self._queue) > _QUEUE_SIZE_WARN * 2:
                    self._queue.popleft()

    # ------------------------------------------------------------------
    # Record methods (sync, non-blocking)
    # ------------------------------------------------------------------

    def record_intent(self, intent: Any, request: Any) -> None:
        """Record an OrderIntent and the resulting CreateOrderRequest."""
        try:
            row: Dict[str, Any] = {
                "run_id": getattr(intent, "run_id", None),
                "process_id": getattr(intent, "process_id", None),
                "signal_id": getattr(intent, "source_signal_id", None)
                             or getattr(intent, "signal_id", None),
                "intent_id": getattr(intent, "intent_id", None),
                "client_order_id": getattr(intent, "client_order_id", None)
                                   or getattr(request, "client_order_id", None),
                "ticker": getattr(intent, "ticker", None)
                          or getattr(request, "ticker", None),
                "asset": getattr(intent, "asset", None),
                "side": getattr(intent, "side", None)
                        or getattr(request, "outcome", None)
                        or getattr(request, "side", None),
                "action": getattr(intent, "action", None),
                "price_cents": getattr(intent, "price_cents", None)
                               or getattr(request, "price_cents", None),
                "count_fp": str(getattr(intent, "count_fp", None)
                                or getattr(intent, "count", None)
                                or getattr(request, "size", None)),
                "order_type": getattr(request, "order_type", None),
                "time_in_force": getattr(request, "time_in_force", None),
                "post_only": int(bool(getattr(request, "post_only", False))),
                "reduce_only": int(bool(getattr(request, "reduce_only", False))),
                "cancel_order_on_pause": int(bool(getattr(request, "cancel_order_on_pause", True))),
                "self_trade_prevention_type": getattr(request, "self_trade_prevention_type", None),
                "max_execution_cost_cents": getattr(request, "max_execution_cost_cents", None),
                "take_profit_price_cents": getattr(intent, "take_profit_price_cents", None),
                "stop_loss_price_cents": getattr(intent, "stop_loss_price_cents", None),
                "source": getattr(intent, "source", None)
                          or getattr(request, "source", None),
                "metadata": json.dumps(self._extract_metadata(intent, request), default=str),
            }
            self._append("intent", row)
        except Exception as e:
            logger.warning("[TRADE-ATTRIBUTION] record_intent failed: %s", e)

    def record_order(
        self,
        request: Any,
        response: Any,
        placed: Optional[Any] = None,
    ) -> None:
        """Record the venue response for a CreateOrderRequest."""
        try:
            order_id = getattr(placed, "order_id", None)
            if not order_id:
                raw = getattr(placed, "raw_data", None) or {}
                order_id = raw.get("order_id")
            status = getattr(placed, "status", None)
            if not status and response is not None:
                status = "rejected" if not getattr(response, "success", True) else None

            req_metadata = getattr(request, "metadata", {}) or {}
            intent_id = (
                req_metadata.get("intent_id")
                or getattr(placed, "intent_id", None)
                or getattr(response, "intent_id", None)
            )

            row: Dict[str, Any] = {
                "intent_id": intent_id,
                "client_order_id": getattr(request, "client_order_id", None),
                "order_id": order_id,
                "ticker": getattr(request, "ticker", None),
                "side": getattr(request, "outcome", None)
                        or getattr(request, "side", None),
                "action": getattr(request, "side", None),
                "price_cents": getattr(request, "price_cents", None),
                "count_fp": str(getattr(request, "size", None)),
                "order_type": getattr(request, "order_type", None),
                "order_status": status,
                "error": getattr(response, "error", None),
                "metadata": json.dumps(self._extract_metadata(request), default=str),
            }
            self._append("order", row)
        except Exception as e:
            logger.warning("[TRADE-ATTRIBUTION] record_order failed: %s", e)

    def record_fill(self, fill: Any) -> None:
        """Record a KalshiFill against the parent intent."""
        try:
            fill_quantity_cc = int(getattr(fill, "quantity_cc", 0) or 0)
            fee_cost = getattr(fill, "fee_cost", Decimal("0")) or Decimal("0")
            fee_cents = int(fee_cost * 100) if fee_cost else 0

            row: Dict[str, Any] = {
                "run_id": getattr(fill, "run_id", None),
                "process_id": getattr(fill, "process_id", None),
                "signal_id": getattr(fill, "decision_trace_id", None),
                "intent_id": getattr(fill, "intent_id", None),
                "client_order_id": getattr(fill, "client_order_id", None)
                                   or getattr(fill, "client_tag", None),
                "order_id": getattr(fill, "order_id", None),
                "fill_id": getattr(fill, "fill_id", None),
                "ticker": getattr(fill, "market_ticker", None),
                "asset": getattr(fill, "asset", None),
                "side": getattr(fill, "canonical_position_side", None)
                        or getattr(fill, "side", None),
                "action": getattr(fill, "canonical_position_action", None)
                         or getattr(fill, "action", None),
                "avg_fill_price_cents": getattr(fill, "canonical_leg_price_cents", None),
                "count_fp": str(getattr(fill, "count_fp", None)),
                "fill_quantity_cc": fill_quantity_cc,
                "fee_cost_cents": fee_cents,
                "source": getattr(fill, "ingestion_source", None),
                "metadata": json.dumps(self._extract_metadata(fill), default=str),
            }
            self._append("fill", row)
        except Exception as e:
            logger.warning("[TRADE-ATTRIBUTION] record_fill failed: %s", e)

    def record_settlement(
        self,
        market_ticker: str,
        outcome: str,
        position: Optional[Any] = None,
        settlement_price_cents: Optional[int] = None,
    ) -> None:
        """Record a market settlement and realized PnL for the position."""
        try:
            if settlement_price_cents is None and outcome:
                settlement_price_cents = 100 if outcome.lower() == "yes" else 0

            realized_pnl_cents: Optional[int] = None
            if position is not None:
                realized_pnl = getattr(position, "realized_pnl_usd", Decimal("0")) or Decimal("0")
                realized_pnl_cents = int(realized_pnl * 100)

            row: Dict[str, Any] = {
                "intent_id": getattr(position, "entry_intent_id", None) if position else None,
                "ticker": market_ticker,
                "side": getattr(position, "side", None),
                "count_fp": str(getattr(position, "contracts", None)) if position else None,
                "realized_pnl_cents": realized_pnl_cents,
                "settlement_outcome": outcome,
                "settlement_price_cents": settlement_price_cents,
                "settlement_ts": datetime.now(timezone.utc).isoformat(),
                "metadata": json.dumps(
                    {
                        "avg_price_cents": getattr(position, "avg_price_cents", None),
                        "entry_intent_id": getattr(position, "entry_intent_id", None),
                        "fill_source": getattr(position, "fill_source", None),
                    },
                    default=str,
                ),
            }
            self._append("settlement", row)
        except Exception as e:
            logger.warning("[TRADE-ATTRIBUTION] record_settlement failed: %s", e)

    def _extract_metadata(self, *objects: Any) -> Dict[str, Any]:
        """Build a compact metadata dict from dataclass-like objects."""
        meta: Dict[str, Any] = {}
        for obj in objects:
            if obj is None:
                continue
            if is_dataclass(obj) and not isinstance(obj, type):
                for key, value in asdict(obj).items():
                    if key not in meta and value is not None:
                        meta[key] = value
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if key not in meta and value is not None:
                        meta[key] = value
        return self._sanitize(meta)

    async def get_events_for_intent(self, intent_id: str) -> List[Dict[str, Any]]:
        """Return all events for a given intent_id."""
        try:
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM trade_attribution_fact WHERE intent_id = ? ORDER BY row_id",
                    (intent_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(r) for r in rows]
        except Exception as e:
            logger.error("[TRADE-ATTRIBUTION] get_events_for_intent failed: %s", e)
            return []


# ----------------------------------------------------------------------
# Convenience helpers for live call sites
# ----------------------------------------------------------------------

def get_trade_attribution_table() -> Optional[TradeAttributionTable]:
    """Return the singleton table if initialized, else None.

    Live call sites should call this and only record if non-None, so the
    table is fully opt-in and tests are not affected.
    """
    return TradeAttributionTable._instance
