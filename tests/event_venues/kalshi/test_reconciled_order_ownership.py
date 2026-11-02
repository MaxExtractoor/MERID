"""A partial fill must not release an exchange-working order."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi import order_router as router
from merid.event_venues.kalshi.order_router import OrderIntent, TradingMode
from merid.position_management.exit_pipeline import post_route_update


def _order(status, filled, remaining, tif="GTC"):
    return SimpleNamespace(
        order_id="order-1", client_order_id="coid-1", status=status,
        size=Decimal("1.00"), filled_size=Decimal(filled),
        remaining_size=Decimal(remaining), time_in_force=tif,
        price_cents=50, outcome="no", side="sell",
    )


def _intent():
    return OrderIntent(
        ticker="KXBTC15M-TEST", side="no", action="sell", price_cents=50,
        count=1, client_order_id="coid-1", client_tag="coid-1",
        reduce_only=True, entry_or_exit="exit",
    )


@pytest.mark.parametrize("tif", ["GTC", "IOC"])
def test_partial_working_order_keeps_remaining_quantity(tif):
    result = router._order_snapshot_to_reconciled_result(
        _order("resting", "0.25", "0.75", tif), _intent(), TradingMode.LIVE, 1
    )
    assert result.is_resting and not result.is_terminal
    assert result.executed_quantity_cc == 25
    assert result.remaining_quantity_cc == 75

    arbiter = MagicMock()
    arbiter.attempt_store.get_active.return_value = SimpleNamespace(filled_cc=25, qty_cc=100)
    post_route_update("position-1", result, fill_cc=25, arbiter=arbiter)
    arbiter.mark_acked.assert_called_once_with("position-1")
    arbiter.record_fill.assert_called_once()
    arbiter.resolve_reconcile.assert_not_called()


@pytest.mark.parametrize("status", ["canceled", "expired"])
def test_partial_terminal_order_releases_only_dead_remainder(status):
    result = router._order_snapshot_to_reconciled_result(
        _order(status, "0.25", "0.75", "IOC"), _intent(), TradingMode.LIVE, 1
    )
    assert result.status == "partial_live"
    assert result.is_terminal and not result.is_resting
    assert result.executed_quantity_cc == 25
    assert result.remaining_quantity_cc == 75


@pytest.mark.parametrize("status", ["pending", "partially_filled", "unfilled", "unknown"])
def test_nonterminal_ioc_snapshot_does_not_imply_zero_fill_terminal(status):
    result = router._order_snapshot_to_reconciled_result(
        _order(status, "0", "1.00", "IOC"), _intent(), TradingMode.LIVE, 1
    )
    assert not result.is_terminal


def test_working_partial_reconciliation_keeps_attempt_and_fractional_gate(monkeypatch):
    import merid.event_venues.kalshi.fills_ledger as fills_ledger
    import merid.event_venues.kalshi.order_gate as order_gate
    import merid.event_venues.kalshi.position_cache as position_cache

    mark_status = MagicMock()
    gate = MagicMock()
    monkeypatch.setattr(router, "_mark_attempt_status", mark_status)
    monkeypatch.setattr(fills_ledger, "get_fills_ledger", lambda: MagicMock())
    monkeypatch.setattr(position_cache, "get_position_cache", lambda: MagicMock())
    monkeypatch.setattr(order_gate, "get_pre_trade_gate", lambda: gate)
    result = router._apply_reconciled_order(
        _order("resting", "0.25", "0.75"), _intent(), TradingMode.LIVE, 1
    )
    assert result.is_resting
    assert mark_status.call_args.args[1] == "ACKNOWLEDGED"
    gate.mark_filled.assert_called_once_with(
        "coid-1", 0, fill_id=None, filled_qty_cc=25
    )
    gate.mark_canceled.assert_not_called()


def test_working_partial_does_not_terminalize_durable_attempt(tmp_path, monkeypatch):
    from merid.event_venues.kalshi import order_attempt_store as attempts

    store = attempts.OrderAttemptStore(tmp_path / "attempts.db")
    record = attempts.OrderAttemptRecord(
        order_attempt_id="attempt-1", intent_id="intent-1", client_order_id="coid-1",
        decision_id=None, replaces_order_attempt_id=None, client_tag="coid-1",
        run_id=None, process_id=None, fingerprint="test", status="SUBMISSION_UNKNOWN",
        created_at=1.0, updated_at=1.0, payload_json="{}",
    )
    store.persist_attempt(record)
    monkeypatch.setattr(attempts, "OrderAttemptStore", lambda: store)
    intent = _intent()
    intent.order_attempt_id = record.order_attempt_id
    result = router._order_snapshot_to_reconciled_result(
        _order("resting", "0.25", "0.75"), intent, TradingMode.LIVE, 1
    )
    router._finalize_attempt_store_for_result(intent, result)
    assert store.get_by_order_attempt_id("attempt-1").status == "ACKNOWLEDGED"
