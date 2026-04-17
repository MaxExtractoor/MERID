"""Test that /api/v1/kalshi/pnl uses fills_ledger as canonical source (CRIT-4 fix)."""
import asyncio
from unittest.mock import MagicMock, patch


def _make_ledger(daily=12.5, realized=100.0, unrealized=5.0):
    ledger = MagicMock()
    ledger.summary.return_value = {
        "daily_realized_pnl_usd": daily,
        "total_realized_pnl_usd": realized,
        "total_unrealized_pnl_usd": unrealized,
        "reconciliation": {"status": "ok"},
    }
    return ledger


def test_pnl_source_is_fills_ledger():
    """source field must be 'fills_ledger' and PnL values must match ledger."""
    with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
               return_value=_make_ledger(daily=12.5, realized=100.0, unrealized=5.0)):
        from web.api.kalshi_api import get_pnl
        result = asyncio.run(get_pnl())
    assert result["source"] == "fills_ledger"
    assert result["daily_pnl_usd"] == 12.5
    assert result["realized_pnl_usd"] == 100.0
    assert result["unrealized_pnl_usd"] == 5.0
    assert result["reconciliation_status"] == "ok"


def test_pnl_fallback_when_ledger_unavailable():
    """When fills_ledger raises, source='unavailable' and PnL fields are 0."""
    with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
               side_effect=RuntimeError("db gone")):
        from web.api.kalshi_api import get_pnl
        result = asyncio.run(get_pnl())
    assert result["source"] == "unavailable"
    assert result["daily_pnl_usd"] == 0.0
    assert result["realized_pnl_usd"] == 0.0


def test_pnl_always_has_required_keys():
    """Response must always contain all expected keys regardless of source availability."""
    with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
               side_effect=Exception("unavailable")):
        from web.api.kalshi_api import get_pnl
        result = asyncio.run(get_pnl())
    required = {
        "daily_pnl_usd", "realized_pnl_usd", "unrealized_pnl_usd",
        "total_notional_usd", "peak_equity_usd", "current_equity_usd",
        "drawdown_pct", "category_pnl", "category_notional",
        "source", "reconciliation_status",
    }
    missing = required - set(result.keys())
    assert not missing, f"Missing keys: {missing}"
