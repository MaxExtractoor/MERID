"""Guardrails: empty fills ledger + venue OI must not auto-arm domain kill."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.base import VenuePosition
from merid.reconciliation.kalshi_reconciler import KalshiReconciler, reset_kalshi_reconciler


@pytest.mark.asyncio
async def test_critical_phantom_suppressed_when_ledger_empty(monkeypatch):
    monkeypatch.setenv("MERID_REC_INTERNAL_SOURCE", "fills_ledger")
    reset_kalshi_reconciler()

    empty_led = MagicMock()
    empty_led._fills = {}
    empty_led.build_venue_positions_from_ledger.return_value = []

    with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger", return_value=empty_led):
        with patch("merid.reconciliation.kalshi_reconciler.get_kalshi_venue_adapter") as m_ada:
            adapter = MagicMock()
            adapter.get_positions = AsyncMock(
                return_value=[
                    VenuePosition(
                        market_id="KXBTC-TEST",
                        outcome_id=None,
                        size=Decimal("5"),
                        average_entry_price=Decimal("0.5"),
                        venue="kalshi",
                    )
                ]
            )
            adapter.get_orders = AsyncMock(return_value=[])
            m_ada.return_value = adapter

            with patch("merid.execution_guard.get_execution_guard") as m_guard:
                m_guard.return_value = MagicMock()
                r = KalshiReconciler()
                report = await r.reconcile(apply_domain_kill_switch=True)

                assert report.severity == "CRITICAL"
                assert report.book_health_ok is False
                assert report.auto_kill_suppressed_reason == "empty_fills_ledger_with_venue_positions"
                m_guard.return_value.activate_domain_kill_switch.assert_not_called()
