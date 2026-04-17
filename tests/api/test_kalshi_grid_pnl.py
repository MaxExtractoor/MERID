"""Test that /api/v1/kalshi/grid/pnl uses fills_ledger as canonical PnL source (HIGH-2 fix)."""
import asyncio
from unittest.mock import MagicMock, patch


def _make_grid(agents=None):
    grid = MagicMock()
    grid.agents = agents or []
    return grid


def _make_ledger(daily=7.5, realized=50.0, unrealized=3.0):
    ledger = MagicMock()
    ledger.summary.return_value = {
        "daily_realized_pnl_usd": daily,
        "total_realized_pnl_usd": realized,
        "total_unrealized_pnl_usd": unrealized,
        "reconciliation": {"status": "ok"},
    }
    return ledger


def test_grid_pnl_source_is_fills_ledger():
    """grid/pnl must include source=fills_ledger and correct canonical PnL values."""
    with patch("web.api.kalshi_grid_api._get_grid", return_value=_make_grid()):
        with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
                   return_value=_make_ledger(daily=7.5, realized=50.0)):
            from web.api.kalshi_grid_api import aggregated_pnl
            result = asyncio.run(aggregated_pnl())
    assert result["source"] == "fills_ledger"
    assert result["daily_pnl_usd"] == 7.5
    assert result["realized_pnl_usd"] == 50.0
    assert result["reconciliation_status"] == "ok"


def test_grid_pnl_fallback_when_ledger_unavailable():
    """When fills_ledger raises, source='unavailable' and canonical PnL fields are 0."""
    with patch("web.api.kalshi_grid_api._get_grid", return_value=_make_grid()):
        with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
                   side_effect=RuntimeError("db gone")):
            from web.api.kalshi_grid_api import aggregated_pnl
            result = asyncio.run(aggregated_pnl())
    assert result["source"] == "unavailable"
    assert result["daily_pnl_usd"] == 0.0
