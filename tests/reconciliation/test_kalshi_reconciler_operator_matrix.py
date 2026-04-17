"""Operator-visible reconciliation outcomes (kill arm vs suppress vs disabled)."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.base import VenuePosition
from merid.matching_engine import Order, OrderSide, OrderStatus
from merid.reconciliation.kalshi_reconciler import KalshiReconciler, reset_kalshi_reconciler


@pytest.mark.parametrize(
    "internal_source,ledger_fills,venue_n,expect_suppress_kill,expect_kill_called",
    [
        ("fills_ledger", 0, 1, True, False),
        ("fills_ledger", 0, 0, False, False),
        ("matching_engine", 0, 1, False, True),
    ],
)
@pytest.mark.asyncio
async def test_critical_kill_matrix(
    monkeypatch,
    internal_source,
    ledger_fills,
    venue_n,
    expect_suppress_kill,
    expect_kill_called,
):
    monkeypatch.setenv("MERID_REC_INTERNAL_SOURCE", internal_source)
    monkeypatch.setenv("MERID_REC_AUTO_KILL_ON_CRITICAL", "1")
    reset_kalshi_reconciler()

    empty_led = MagicMock()
    empty_led._fills = {f"f{i}": object() for i in range(ledger_fills)}
    empty_led.build_venue_positions_from_ledger.return_value = []

    venue_positions = []
    if venue_n:
        venue_positions = [
            VenuePosition(
                market_id="KX-TEST",
                outcome_id=None,
                size=Decimal("1"),
                average_entry_price=Decimal("0.5"),
                venue="kalshi",
            )
        ]

    with patch("merid.reconciliation.kalshi_reconciler.get_matching_engine") as m_me:
        _eng = MagicMock()
        _eng._orders = {}
        m_me.return_value = _eng
        with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger", return_value=empty_led):
            with patch("merid.reconciliation.kalshi_reconciler.get_kalshi_venue_adapter") as m_ada:
                adapter = MagicMock()
                adapter.get_positions = AsyncMock(return_value=venue_positions)
                adapter.get_orders = AsyncMock(return_value=[])
                m_ada.return_value = adapter

                with patch("merid.execution_guard.get_execution_guard") as m_guard:
                    m_guard.return_value = MagicMock()
                    r = KalshiReconciler()
                    await r.reconcile(apply_domain_kill_switch=True)

                    if expect_kill_called:
                        m_guard.return_value.activate_domain_kill_switch.assert_called()
                    else:
                        m_guard.return_value.activate_domain_kill_switch.assert_not_called()

                    rep = r.get_last_report()
                    assert rep is not None
                    if expect_suppress_kill:
                        assert rep.auto_kill_suppressed_reason == "empty_fills_ledger_with_venue_positions"
                        assert rep.book_health_ok is False


@pytest.mark.asyncio
async def test_me_residual_position_venue_flat_critical_suppresses_kill(monkeypatch):
    """Internal-only size (ME) vs flat venue: CRITICAL missing_position, kill suppressed."""
    monkeypatch.setenv("MERID_REC_INTERNAL_SOURCE", "matching_engine")
    monkeypatch.setenv("MERID_REC_AUTO_KILL_ON_CRITICAL", "1")
    reset_kalshi_reconciler()

    internal_order = Order(
        instrument_id="KX-INTERNAL-ONLY",
        side=OrderSide.BUY,
        price=0.5,
        quantity=15.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 15.0
    internal_order.filled_price = 0.5

    empty_led = MagicMock()
    empty_led._fills = {}
    empty_led.build_venue_positions_from_ledger.return_value = []

    with patch("merid.reconciliation.kalshi_reconciler.get_matching_engine") as m_me:
        eng = MagicMock()
        eng._orders = {internal_order.order_id: internal_order}
        m_me.return_value = eng
        with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger", return_value=empty_led):
            with patch("merid.reconciliation.kalshi_reconciler.get_kalshi_venue_adapter") as m_ada:
                adapter = MagicMock()
                adapter.get_positions = AsyncMock(return_value=[])
                adapter.get_orders = AsyncMock(return_value=[])
                m_ada.return_value = adapter

                with patch("merid.execution_guard.get_execution_guard") as m_guard:
                    m_guard.return_value = MagicMock()
                    r = KalshiReconciler()
                    await r.reconcile(apply_domain_kill_switch=True)

                    m_guard.return_value.activate_domain_kill_switch.assert_not_called()

                    rep = r.get_last_report()
                    assert rep is not None
                    assert rep.severity == "CRITICAL"
                    assert rep.auto_kill_suppressed_reason == "internal_position_not_on_venue"
                    assert any(i.issue_type.value == "missing_position" for i in rep.issues)
