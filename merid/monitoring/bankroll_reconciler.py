"""Event-driven bankroll/equity reconciliation.

The reconciler records a structured ``logs/bankroll_reconciliation.jsonl`` line
every time an order, fill, or settlement occurs.  It forces a fresh Kalshi
portfolio/balance check (via ``BankrollServiceV2``) and compares the live
exchange view against MERID's internal bankroll, cash, and position-cache
portfolio value.  The goal is to catch the Polymarket-class silent-loss bug:
a position or balance can drift without the strategy noticing.

Design constraints:
- Non-blocking: record_* returns immediately and schedules a deferred reconcile.
- Throttled: a minimum interval between live API calls avoids exchange rate limits.
- Fail-safe: any reconcile failure is logged; it never halts trading.
- Read-only: it does not submit orders or mutate positions.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.jsonl_writer import JsonlWriter
from utils.logger import get_logger

logger = get_logger("merid.monitoring.bankroll_reconciler")

_ENABLED = os.environ.get("MERID_BANKROLL_RECONCILER_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_MIN_INTERVAL_SECONDS = float(os.environ.get("MERID_BANKROLL_RECONCILER_MIN_INTERVAL_S", "5.0"))
_DELAY_BEFORE_RECONCILE_SECONDS = float(
    os.environ.get("MERID_BANKROLL_RECONCILER_DELAY_S", "1.0")
)
_DEFAULT_LOG_PATH = os.environ.get(
    "MERID_BANKROLL_RECONCILIATION_LOG", "logs/bankroll_reconciliation.jsonl"
)

# Equity-drift alert thresholds.  A drift is flagged if either the absolute
# USD difference or the percentage exceeds the configured level.
_EQUITY_DRIFT_WARNING_PCT = float(
    os.environ.get("MERID_BANKROLL_DRIFT_WARNING_PCT", "0.5")
)
_EQUITY_DRIFT_CRITICAL_PCT = float(
    os.environ.get("MERID_BANKROLL_DRIFT_CRITICAL_PCT", "1.0")
)
_EQUITY_DRIFT_WARNING_USD = float(
    os.environ.get("MERID_BANKROLL_DRIFT_WARNING_USD", "1.0")
)
_EQUITY_DRIFT_CRITICAL_USD = float(
    os.environ.get("MERID_BANKROLL_DRIFT_CRITICAL_USD", "5.0")
)

SCHEMA_VERSION = 1


@dataclass
class ReconciliationRecord:
    """One bankroll reconciliation event."""

    record_id: str
    schema_version: int
    event_ts: str
    trigger: str  # "order" | "fill" | "settlement" | "periodic"
    trigger_context: Dict[str, Any] = field(default_factory=dict)

    # Internal MERID state
    internal_state: Optional[str] = None
    internal_equity_usd: Optional[float] = None
    internal_cash_usd: Optional[float] = None
    internal_portfolio_value_cents: Optional[int] = None
    internal_as_of: Optional[str] = None

    # Exchange (Kalshi) live state
    fresh_equity_usd: Optional[float] = None
    fresh_cash_usd: Optional[float] = None
    exchange_available: Optional[bool] = None

    # Comparison
    consistent: Optional[bool] = None
    severity: Optional[str] = None  # ok | warning | critical | error
    equity_diff_usd: Optional[float] = None
    equity_diff_pct: Optional[float] = None

    # Expected change from the triggering event (for diagnosis)
    expected_change_cents: Optional[int] = None
    notes: List[str] = field(default_factory=list)


class BankrollReconciler:
    """Singleton bankroll reconciler."""

    _instance: Optional[BankrollReconciler] = None
    _lock = threading.Lock()

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = Path(log_path or _DEFAULT_LOG_PATH)
        self._writer = JsonlWriter(self._log_path, max_bytes=50_000_000, backup_count=3)
        self._enabled = _ENABLED
        self._min_interval = _MIN_INTERVAL_SECONDS
        self._delay = _DELAY_BEFORE_RECONCILE_SECONDS

        self._last_reconcile_at: float = 0.0
        self._pending_task: Optional[asyncio.Task] = None
        self._in_progress: bool = False
        self._event_queue: List[Dict[str, Any]] = []
        self._queue_lock = threading.Lock()
        self._reconcile_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls, log_path: Optional[str] = None) -> BankrollReconciler:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(log_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (test isolation only)."""
        with cls._lock:
            cls._instance = None

    async def start(self) -> None:
        logger.info(
            "[BANKROLL-RECONCILER] started enabled=%s min_interval=%.2fs log=%s",
            self._enabled,
            self._min_interval,
            self._log_path,
        )

    async def stop(self) -> None:
        if self._pending_task:
            try:
                self._pending_task.cancel()
                await self._pending_task
            except asyncio.CancelledError:
                pass
            self._pending_task = None
        logger.info("[BANKROLL-RECONCILER] stopped")

    def record_order(
        self,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        ticker: Optional[str] = None,
        side: Optional[str] = None,
        action: Optional[str] = None,
        quantity_cc: Optional[int] = None,
        price_cents: Optional[int] = None,
        status: Optional[str] = None,
        error: Optional[str] = None,
        expected_change_cents: Optional[int] = None,
    ) -> None:
        """Queue a reconcile triggered by an order placement/ack/reject."""
        self._schedule(
            "order",
            {
                "client_order_id": client_order_id,
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "action": action,
                "quantity_cc": quantity_cc,
                "price_cents": price_cents,
                "status": status,
                "error": error,
                "expected_change_cents": expected_change_cents,
            },
        )

    def record_fill(
        self,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
        ticker: Optional[str] = None,
        side: Optional[str] = None,
        action: Optional[str] = None,
        quantity_cc: Optional[int] = None,
        price_cents: Optional[int] = None,
        fee_cents: Optional[int] = None,
    ) -> None:
        """Queue a reconcile triggered by a fill."""
        self._schedule(
            "fill",
            {
                "client_order_id": client_order_id,
                "order_id": order_id,
                "fill_id": fill_id,
                "ticker": ticker,
                "side": side,
                "action": action,
                "quantity_cc": quantity_cc,
                "price_cents": price_cents,
                "fee_cents": fee_cents,
                "expected_change_cents": self._expected_fill_change_cents(
                    quantity_cc, price_cents, fee_cents, action
                ),
            },
        )

    def record_settlement(
        self,
        ticker: Optional[str] = None,
        outcome: Optional[str] = None,
        settlement_price_cents: Optional[int] = None,
        realized_pnl_cents: Optional[int] = None,
    ) -> None:
        """Queue a reconcile triggered by a market settlement."""
        self._schedule(
            "settlement",
            {
                "ticker": ticker,
                "outcome": outcome,
                "settlement_price_cents": settlement_price_cents,
                "realized_pnl_cents": realized_pnl_cents,
                "expected_change_cents": realized_pnl_cents,
            },
        )

    def record_periodic(self, reason: str = "periodic") -> None:
        """Queue a periodic reconcile (can be wired to a timer)."""
        self._schedule("periodic", {"reason": reason})

    # -----------------------------------------------------------------------
    # Scheduling
    # -----------------------------------------------------------------------

    def _schedule(self, trigger: str, context: Dict[str, Any]) -> None:
        if not self._enabled:
            return

        event = {
            "trigger": trigger,
            "context": context,
            "queued_at": time.time(),
        }
        with self._queue_lock:
            self._event_queue.append(event)

        try:
            loop = asyncio.get_running_loop()
            if self._pending_task is None or self._pending_task.done():
                self._pending_task = loop.create_task(self._deferred_reconcile())
        except RuntimeError:
            # No event loop available; the next async caller will drain the queue.
            logger.debug("[BANKROLL-RECONCILER] no running loop; event queued")

    async def _deferred_reconcile(self) -> None:
        """Wait briefly for event bursts, then reconcile if throttle allows."""
        try:
            await asyncio.sleep(self._delay)
            await self._reconcile_if_due()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[BANKROLL-RECONCILER] deferred reconcile failed: %s", e)

    async def _reconcile_if_due(self) -> None:
        now = time.time()
        if self._in_progress:
            return
        if now - self._last_reconcile_at < self._min_interval:
            # Too soon; re-schedule at the next interval boundary.
            wait = self._min_interval - (now - self._last_reconcile_at)
            try:
                loop = asyncio.get_running_loop()
                if self._pending_task is None or self._pending_task.done():
                    self._pending_task = loop.create_task(self._delayed_reconcile_after(wait))
            except RuntimeError:
                pass
            return

        with self._queue_lock:
            events = list(self._event_queue)
            self._event_queue.clear()

        if not events:
            return

        # Use the most significant trigger and merge contexts.
        trigger, merged_context = self._merge_events(events)
        await self._run_reconcile(trigger, merged_context)

    async def _delayed_reconcile_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._reconcile_if_due()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[BANKROLL-RECONCILER] delayed reconcile failed: %s", e)

    # -----------------------------------------------------------------------
    # Reconcile core
    # -----------------------------------------------------------------------

    async def _run_reconcile(self, trigger: str, context: Dict[str, Any]) -> None:
        if self._in_progress:
            return
        async with self._reconcile_lock:
            self._in_progress = True
            try:
                self._last_reconcile_at = time.time()
                record = await self._build_record(trigger, context)
                await self._write_record(record)
            except Exception as e:
                logger.error("[BANKROLL-RECONCILER] reconcile error: %s", e)
            finally:
                self._in_progress = False

    async def _build_record(
        self, trigger: str, context: Dict[str, Any]
    ) -> ReconciliationRecord:
        record = ReconciliationRecord(
            record_id=uuid.uuid4().hex[:12],
            schema_version=SCHEMA_VERSION,
            event_ts=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            trigger_context=context,
            expected_change_cents=context.get("expected_change_cents"),
        )

        # Bankroll service is the single source of truth for both internal and
        # (via its Kalshi client) the live exchange view.
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service

            service = await get_bankroll_service()
            if service is None:
                record.notes.append("bankroll_service_not_initialized")
                return record

            # Internal snapshot.
            summary = await service.get_summary(caller_module=__name__)
            record.internal_state = summary.state.name if summary.state else None
            record.internal_equity_usd = (
                float(summary.equity_usd) if summary.equity_usd is not None else None
            )
            record.internal_cash_usd = (
                float(summary.available_cash_usd)
                if summary.available_cash_usd is not None
                else None
            )
            record.internal_as_of = summary.as_of.isoformat() if summary.as_of else None

            try:
                portfolio_cents = await service.get_portfolio_value_cents()
                record.internal_portfolio_value_cents = portfolio_cents
            except Exception as pe:
                record.notes.append(f"portfolio_value_error:{pe}")

            # Live exchange comparison (forces a fresh /portfolio/balance call).
            consistency = await service.check_consistency()
            record.consistent = consistency.get("consistent")
            record.severity = consistency.get("severity")
            record.fresh_equity_usd = consistency.get("fresh_equity")
            record.equity_diff_usd = consistency.get("equity_diff")
            record.equity_diff_pct = consistency.get("equity_diff_pct")
            record.exchange_available = record.fresh_equity_usd is not None

            # Cash consistency: available cash should equal exchange balance.
            if record.fresh_equity_usd is not None and record.internal_cash_usd is not None:
                record.fresh_cash_usd = record.fresh_equity_usd - (
                    record.internal_portfolio_value_cents or 0
                ) / 100.0

            # Override/augment the service-reported severity with our own
            # percentage/USD thresholds so drift is actionable regardless of
            # what the bankroll service labels it.
            computed = self._severity(record.equity_diff_pct, record.equity_diff_usd)
            record.severity = self._worse_severity(record.severity, computed)
            if computed == "critical":
                record.notes.append("equity_divergence_above_critical")
                logger.critical(
                    "[BANKROLL-RECONCILER] equity divergence critical: diff_usd=%s diff_pct=%s",
                    record.equity_diff_usd,
                    record.equity_diff_pct,
                )
            elif computed == "warning":
                record.notes.append("equity_divergence_above_warning")
                logger.warning(
                    "[BANKROLL-RECONCILER] equity divergence warning: diff_usd=%s diff_pct=%s",
                    record.equity_diff_usd,
                    record.equity_diff_pct,
                )

        except Exception as e:
            record.notes.append(f"bankroll_check_error:{e}")
            logger.warning("[BANKROLL-RECONCILER] bankroll check failed: %s", e)

        return record

    async def _write_record(self, record: ReconciliationRecord) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._writer.append, asdict(record))

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _severity(
        self,
        equity_diff_pct: Optional[float],
        equity_diff_usd: Optional[float],
    ) -> Optional[str]:
        """Return warning/critical/ok based on configured drift thresholds."""
        if equity_diff_pct is None and equity_diff_usd is None:
            return None
        # Use absolute drift; both directions are equally dangerous.
        pct = abs(equity_diff_pct) if equity_diff_pct is not None else 0.0
        usd = abs(equity_diff_usd) if equity_diff_usd is not None else 0.0
        if pct >= _EQUITY_DRIFT_CRITICAL_PCT or usd >= _EQUITY_DRIFT_CRITICAL_USD:
            return "critical"
        if pct >= _EQUITY_DRIFT_WARNING_PCT or usd >= _EQUITY_DRIFT_WARNING_USD:
            return "warning"
        return "ok"

    @staticmethod
    def _worse_severity(a: Optional[str], b: Optional[str]) -> Optional[str]:
        """Return the more severe of two severity strings."""
        order = {"ok": 0, "warning": 1, "critical": 2, "error": 3}
        if a is None:
            return b
        if b is None:
            return a
        return a if order.get(a, 0) >= order.get(b, 0) else b

    def _merge_events(self, events: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Pick the most significant trigger and merge contexts.

        Numerical expected-change fields are summed across the burst so a
        throttled reconcile still accounts for every order/fill/settlement.
        """
        priority = {"settlement": 3, "fill": 2, "order": 1, "periodic": 0}
        events.sort(key=lambda e: priority.get(e["trigger"], 0), reverse=True)
        context: Dict[str, Any] = {}
        # Counters that should be netted rather than overwritten.
        summed: Dict[str, int] = {
            "expected_change_cents": 0,
            "realized_pnl_cents": 0,
            "fee_cents": 0,
            "quantity_cc": 0,
        }
        merged_keys: Dict[str, List[Any]] = {}

        for e in events:
            for k, v in e["context"].items():
                if v is None:
                    continue
                if k in summed and isinstance(v, (int, float)):
                    summed[k] += int(v)
                elif k not in context:
                    context[k] = v
                # Collect all values for diagnostic keys (e.g. fill_ids).
                if k in ("fill_id", "order_id"):
                    merged_keys.setdefault(k, []).append(v)

        for k, v in summed.items():
            if v != 0 or context.get(k) is not None:
                context[k] = v

        context["merged_event_count"] = len(events)
        context["merged_triggers"] = [e["trigger"] for e in events]
        for k, vals in merged_keys.items():
            context[f"merged_{k}s"] = vals

        return events[0]["trigger"], context

    def _expected_fill_change_cents(
        self,
        quantity_cc: Optional[int],
        price_cents: Optional[int],
        fee_cents: Optional[int],
        action: Optional[str],
    ) -> Optional[int]:
        """Compute the expected cash change for a fill in cents.

        For a buy, cash decreases by (qty * price + fee).
        For a sell, cash increases by (qty * price - fee).
        This is a coarse heuristic; the real P&L depends on the held side.
        """
        if quantity_cc is None or price_cents is None:
            return None
        # quantity_cc is centi-contracts; convert to contract-level cents using
        # the same ROUND_HALF_UP policy as the rest of the ledger.
        gross_cents = (
            Decimal(quantity_cc) * Decimal(price_cents) / Decimal(100)
        ).quantize(Decimal("1."), rounding=ROUND_HALF_UP)
        fee = fee_cents or 0
        if str(action).lower() == "buy":
            return int(-(gross_cents + fee))
        else:
            return int(gross_cents - fee)


# Convenience helpers used by live call sites.

def get_bankroll_reconciler() -> Optional[BankrollReconciler]:
    """Return the singleton reconciler, or None if not enabled.

    Environment variable ``MERID_BANKROLL_RECONCILER_ENABLED`` is re-checked at
    call time so startup flags can disable it without restarting the process.
    """
    env = os.environ.get("MERID_BANKROLL_RECONCILER_ENABLED", "1").strip().lower()
    if env in ("0", "false", "no", "off"):
        return None
    return BankrollReconciler.get_instance()
