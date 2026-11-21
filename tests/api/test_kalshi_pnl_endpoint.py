"""Test that /api/v1/kalshi/pnl uses fills_ledger as canonical source (CRIT-4 fix)."""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


def _make_ledger(daily=12.5, realized=100.0, unrealized=5.0):
    ledger = MagicMock()
    ledger.summary.return_value = {
        "daily_realized_pnl_usd": daily,
        "total_realized_pnl_usd": realized,
        "total_unrealized_pnl_usd": unrealized,
        "reconciliation": {"status": "ok"},
    }
    return ledger


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    """KalshiClientV2 stand-in: routes path -> payload (or exception)."""

    def __init__(self, routes):
        self._routes = routes

    async def _request(self, method, path, **kwargs):
        route = self._routes.get(path)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return _FakeResp({}, status_code=404)
        if isinstance(route, int):
            return _FakeResp({}, status_code=route)
        return _FakeResp(route)


class _FakeBankrollService:
    def __init__(self, equity_usd, client):
        self._equity = equity_usd
        self._client = client

    async def get_summary(self, caller_module=None):
        s = MagicMock()
        s.equity_usd = Decimal(str(self._equity))
        from merid.event_venues.kalshi.types import BalanceState
        s.state = BalanceState.FRESH
        return s


def _flow_item(amount_cents, fee_cents, status="applied", ts=1_800_000_000):
    return {
        "id": "x",
        "status": status,
        "type": "debit",
        "amount_cents": amount_cents,
        "fee_cents": fee_cents,
        "created_ts": ts,
        "finalized_ts": ts,
    }


def _run_pnl_with_equity(equity, anchor, anchor_ts, client):
    """Run get_pnl() with a stubbed bankroll service + equity anchor."""
    import web.api.kalshi_api as ka
    ka._EXTERNAL_FLOWS_CACHE.clear()
    svc = _FakeBankrollService(equity, client)
    with patch.object(ka, "get_bankroll_service", new=AsyncMock(return_value=svc)), \
         patch.object(ka, "_daily_equity_anchor", return_value=(anchor, anchor_ts, True)), \
         patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
               return_value=_make_ledger()):
        return asyncio.run(ka.get_pnl())


_ANCHOR_TS = "2026-11-21T00:00:03+00:00"
_FLOW_TS = 1_800_000_000  # well after the anchor


def test_daily_pnl_nets_out_deposit():
    """A $25 deposit (net $24.50 after fee) must not read as +$24.50 P&L."""
    client = _FakeClient({
        "/portfolio/deposits": {"deposits": [_flow_item(2500, 50, ts=_FLOW_TS)]},
        "/portfolio/withdrawals": {"withdrawals": []},
    })
    result = _run_pnl_with_equity(27.86, 3.36, _ANCHOR_TS, client)
    # equity delta = 24.50; net flows = +24.50 -> trading P&L = 0.00
    assert result["daily_pnl_usd"] == 0.0
    assert result["daily_pnl_cash_flows_usd"] == 24.5
    assert result["daily_pnl_deposits_usd"] == 24.5
    assert result["daily_pnl_withdrawals_usd"] == 0.0
    assert result["daily_pnl_source"] == "equity_delta_net_flows"


def test_daily_pnl_nets_out_withdrawal():
    """A $15 withdrawal must not read as -$15 P&L."""
    client = _FakeClient({
        "/portfolio/deposits": {"deposits": []},
        "/portfolio/withdrawals": {"withdrawals": [_flow_item(1500, 0, ts=_FLOW_TS)]},
    })
    result = _run_pnl_with_equity(15.0, 30.0, _ANCHOR_TS, client)
    # equity delta = -15.00; net flows = -15.00 -> trading P&L = 0.00
    assert result["daily_pnl_usd"] == 0.0
    assert result["daily_pnl_cash_flows_usd"] == -15.0
    assert result["daily_pnl_source"] == "equity_delta_net_flows"


def test_daily_pnl_flows_before_anchor_ignored():
    """Flows finalized before the anchor are already inside anchor equity."""
    old_ts = 1_000_000_000  # long before _ANCHOR_TS
    client = _FakeClient({
        "/portfolio/deposits": {"deposits": [_flow_item(2500, 50, ts=old_ts)]},
        "/portfolio/withdrawals": {"withdrawals": []},
    })
    result = _run_pnl_with_equity(27.86, 3.36, _ANCHOR_TS, client)
    assert result["daily_pnl_usd"] == 24.5
    assert result["daily_pnl_cash_flows_usd"] == 0.0


def test_daily_pnl_pending_and_failed_flows_ignored():
    """Only 'applied' flows moved balance; pending/failed must not subtract."""
    client = _FakeClient({
        "/portfolio/deposits": {"deposits": [
            _flow_item(2500, 50, status="pending", ts=_FLOW_TS),
            _flow_item(1000, 20, status="failed", ts=_FLOW_TS),
        ]},
        "/portfolio/withdrawals": {"withdrawals": []},
    })
    result = _run_pnl_with_equity(27.86, 3.36, _ANCHOR_TS, client)
    assert result["daily_pnl_usd"] == 24.5
    assert result["daily_pnl_cash_flows_usd"] == 0.0


def test_daily_pnl_unverified_flows_keeps_delta_and_flags():
    """When the flows endpoints fail, keep the raw delta but mark it unverified."""
    client = _FakeClient({
        "/portfolio/deposits": RuntimeError("boom"),
        "/portfolio/withdrawals": {"withdrawals": []},
    })
    result = _run_pnl_with_equity(27.86, 3.36, _ANCHOR_TS, client)
    assert result["daily_pnl_usd"] == 24.5
    assert result["daily_pnl_cash_flows_usd"] is None
    assert result["daily_pnl_source"] == "equity_delta"


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
