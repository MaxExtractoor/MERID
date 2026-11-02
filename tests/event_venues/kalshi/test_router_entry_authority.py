"""Live order planning fails closed on missing ticker subscription or portfolio."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi import order_router
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.prediction.trading_mode import TradingMode


TICKER = "KXBTC15M-TEST"


def intent():
    return OrderIntent(
        ticker=TICKER, side="BUY_YES", action="buy", price_cents=50, count=1,
        mode=TradingMode.LIVE, order_type="limit", time_in_force="gtc",
        snapshot_ts=time.time(), source="agent_grid_15m",
    )


def test_live_entry_requires_its_own_confirmed_subscription(monkeypatch):
    monkeypatch.setattr(order_router, "_is_exit_order", lambda intent: False)
    monkeypatch.setattr(order_router, "_live_orderbook_subscription_confirmed", lambda ticker: False)
    result, state = order_router._prepare_order_for_gate(intent(), TradingMode.LIVE, time.monotonic())
    assert state is None
    assert result.status == "rejected"
    assert result.reason == f"ws_subscription_unconfirmed:{TICKER}"


@pytest.mark.parametrize("unavailable", ["missing", "error"])
def test_live_entry_requires_portfolio_even_with_ready_book(monkeypatch, unavailable):
    monkeypatch.setattr(order_router, "_is_exit_order", lambda intent: False)
    monkeypatch.setattr(order_router, "_live_orderbook_subscription_confirmed", lambda ticker: True)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: SimpleNamespace(get=lambda ticker: object(), is_market_entry_ready=lambda ticker: (True, None)),
    )
    current = MagicMock(return_value=None)
    if unavailable == "error":
        current.side_effect = OSError("portfolio unavailable")
    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio.get_canonical_portfolio_store",
        lambda: SimpleNamespace(current=current),
    )
    result, state = order_router._prepare_order_for_gate(intent(), TradingMode.LIVE, time.monotonic())
    assert state is None
    assert result.status == "rejected"
    assert result.reason == f"portfolio_unavailable:{TICKER}"


def test_exit_does_not_consult_subscription_entry_gate(monkeypatch):
    monkeypatch.setattr(order_router, "_is_exit_order", lambda intent: True)
    monkeypatch.setattr(
        order_router, "_live_orderbook_subscription_confirmed",
        MagicMock(side_effect=AssertionError("exit must not use entry subscription gate")),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: SimpleNamespace(get=MagicMock(side_effect=RuntimeError("past subscription gate"))),
    )
    with pytest.raises(RuntimeError, match="past subscription gate"):
        order_router._prepare_order_for_gate(intent(), TradingMode.LIVE, time.monotonic())
