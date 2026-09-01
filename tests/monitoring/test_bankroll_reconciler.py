"""Focused tests for the event-driven bankroll reconciler."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from merid.monitoring.bankroll_reconciler import (
    BankrollReconciler,
    get_bankroll_reconciler,
)


@dataclass
class _FakeBankrollSummary:
    state: Any
    equity_usd: float
    available_cash_usd: float
    as_of: datetime


class _FakeState:
    name = "FRESH"


class _FakeBankrollService:
    def __init__(self, consistent: bool = True, equity: float = 1000.0, cash: float = 500.0):
        self.consistent = consistent
        self.equity = equity
        self.cash = cash

    async def get_summary(self, caller_module: Optional[str] = None):
        return _FakeBankrollSummary(
            state=_FakeState(),
            equity_usd=self.equity,
            available_cash_usd=self.cash,
            as_of=datetime.now(timezone.utc),
        )

    async def check_consistency(self):
        return {
            "consistent": self.consistent,
            "severity": "ok" if self.consistent else "critical",
            "fresh_equity": self.equity,
            "cached_equity": self.equity,
            "equity_diff": 0.0,
            "equity_diff_pct": 0.0,
        }

    async def get_portfolio_value_cents(self):
        return int((self.equity - self.cash) * 100)


@pytest.fixture
def reconciler(tmp_path: Path, monkeypatch: Any):
    log_path = tmp_path / "bankroll_reconciliation.jsonl"
    BankrollReconciler.reset_instance()
    rec = BankrollReconciler.get_instance(str(log_path))
    # Speed up tests: tiny delay and no throttle by default.
    rec._delay = 0.05
    rec._min_interval = 0.0
    rec._enabled = True

    # Patch the bankroll service getter in the source module.  The reconciler
    # imports this lazily inside _build_record, so the source namespace is the
    # correct target.
    fake_service = _FakeBankrollService()

    async def fake_get_bankroll_service():
        return fake_service

    monkeypatch.setattr(
        "merid.event_venues.kalshi.bankroll_service_v2.get_bankroll_service",
        fake_get_bankroll_service,
        raising=False,
    )

    yield rec

    BankrollReconciler.reset_instance()


def _read_records(log_path: Path) -> List[Dict[str, Any]]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def test_record_order_produces_reconcile_record(reconciler: BankrollReconciler):
    log_path = Path(reconciler._log_path)

    async def _run():
        reconciler.record_order(
            client_order_id="coid-1",
            order_id="order-1",
            ticker="KXBTC15M-TEST-000000-00",
            side="yes",
            action="buy",
            quantity_cc=100,
            price_cents=55,
            status="filled",
        )
        await asyncio.sleep(0.2)

    asyncio.run(_run())

    records = _read_records(log_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["trigger"] == "order"
    assert rec["trigger_context"]["client_order_id"] == "coid-1"
    assert rec["consistent"] is True
    assert rec["internal_equity_usd"] == 1000.0
    assert rec["internal_cash_usd"] == 500.0
    assert rec["internal_portfolio_value_cents"] == 50000
    assert rec["expected_change_cents"] is None


def test_record_fill_computes_expected_change(reconciler: BankrollReconciler):
    log_path = Path(reconciler._log_path)

    async def _run():
        reconciler.record_fill(
            client_order_id="coid-1",
            fill_id="fill-1",
            ticker="KXBTC15M-TEST-000000-00",
            side="yes",
            action="buy",
            quantity_cc=100,
            price_cents=55,
            fee_cents=2,
        )
        await asyncio.sleep(0.2)

    asyncio.run(_run())

    records = _read_records(log_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["trigger"] == "fill"
    # 100 cc = 1 contract * 55c + 2c fee = 57c debit.
    assert rec["expected_change_cents"] == -57


def test_record_settlement_uses_realized_pnl_as_expected_change(reconciler: BankrollReconciler):
    log_path = Path(reconciler._log_path)

    async def _run():
        reconciler.record_settlement(
            ticker="KXBTC15M-TEST-000000-00",
            outcome="yes",
            settlement_price_cents=100,
            realized_pnl_cents=45,
        )
        await asyncio.sleep(0.2)

    asyncio.run(_run())

    records = _read_records(log_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["trigger"] == "settlement"
    assert rec["expected_change_cents"] == 45


def test_reconcile_merges_rapid_events(reconciler: BankrollReconciler):
    log_path = Path(reconciler._log_path)

    async def _run():
        reconciler.record_order(
            client_order_id="coid-1",
            ticker="KXBTC15M-TEST-000000-00",
            quantity_cc=100,
            price_cents=55,
            status="filled",
        )
        reconciler.record_fill(
            fill_id="fill-1",
            ticker="KXBTC15M-TEST-000000-00",
            quantity_cc=100,
            price_cents=55,
            fee_cents=2,
        )
        await asyncio.sleep(0.2)

    asyncio.run(_run())

    records = _read_records(log_path)
    assert len(records) == 1
    rec = records[0]
    # The more significant trigger wins (fill over order).
    assert rec["trigger"] == "fill"
    assert rec["trigger_context"]["client_order_id"] == "coid-1"
    assert rec["trigger_context"]["fill_id"] == "fill-1"


def test_reconcile_nets_expected_change_across_merged_events(reconciler: BankrollReconciler):
    log_path = Path(reconciler._log_path)

    async def _run():
        # Two fills in quick succession:
        #  - buy 1 contract @ 55c with 2c fee  -> -57c
        #  - sell 1 contract @ 60c with 2c fee -> +58c
        # Net expected change = +1c.
        reconciler.record_fill(
            fill_id="fill-1",
            ticker="KXBTC15M-TEST-000000-00",
            side="yes",
            action="buy",
            quantity_cc=100,
            price_cents=55,
            fee_cents=2,
        )
        reconciler.record_fill(
            fill_id="fill-2",
            ticker="KXBTC15M-TEST-000000-00",
            side="yes",
            action="sell",
            quantity_cc=100,
            price_cents=60,
            fee_cents=2,
        )
        await asyncio.sleep(0.2)

    asyncio.run(_run())

    records = _read_records(log_path)
    assert len(records) == 1
    rec = records[0]
    assert rec["trigger"] == "fill"
    assert rec["trigger_context"]["merged_event_count"] == 2
    assert rec["trigger_context"]["merged_fill_ids"] == ["fill-1", "fill-2"]
    # Net: -57 + 58 = +1c.
    assert rec["expected_change_cents"] == 1
    assert rec["trigger_context"]["fee_cents"] == 4
    assert rec["trigger_context"]["quantity_cc"] == 200


def test_record_methods_are_non_blocking_and_deferred(reconciler: BankrollReconciler):
    """record_* must return immediately and not await the live reconcile."""
    reconciler._delay = 5.0  # Long delay so the reconcile cannot complete.

    async def _run():
        start = time.time()
        reconciler.record_order(client_order_id="coid-1", ticker="KXBTC15M-TEST-000000-00")
        elapsed = time.time() - start
        # The synchronous record call must not wait for the reconcile task.
        assert elapsed < 0.1
        # A pending task should have been scheduled.
        assert reconciler._pending_task is not None
        reconciler._pending_task.cancel()
        try:
            await reconciler._pending_task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())


def test_get_bankroll_reconciler_honors_disabled():
    """When disabled, the convenience getter returns None so live call sites skip."""
    import os
    original = os.environ.get("MERID_BANKROLL_RECONCILER_ENABLED")
    os.environ["MERID_BANKROLL_RECONCILER_ENABLED"] = "0"
    try:
        # Force module reload to pick up env change? The module-level _ENABLED is set at import.
        # Instead, call the helper directly after resetting the singleton.
        BankrollReconciler.reset_instance()
        rec = get_bankroll_reconciler()
        assert rec is None
    finally:
        if original is None:
            os.environ.pop("MERID_BANKROLL_RECONCILER_ENABLED", None)
        else:
            os.environ["MERID_BANKROLL_RECONCILER_ENABLED"] = original
        BankrollReconciler.reset_instance()
