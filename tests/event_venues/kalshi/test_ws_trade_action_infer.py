"""Kalshi WS trade action inference."""

from decimal import Decimal

from merid.event_venues.kalshi.ws import _infer_kalshi_trade_action


def test_infer_from_explicit_action():
    d = {"action": "sell", "price": 50}
    assert _infer_kalshi_trade_action(d, Decimal("0.5")) == "sell"


def test_heuristic_high_price_is_buy():
    assert _infer_kalshi_trade_action({}, Decimal("0.60")) == "buy"


def test_heuristic_low_price_is_sell():
    assert _infer_kalshi_trade_action({}, Decimal("0.40")) == "sell"
