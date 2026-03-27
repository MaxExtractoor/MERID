"""Tests for E1 – check_order receives real orderbook params.

Verifies that spread_cents and depth_at_price actually change check_order's
decision, and that tests serve as regression guards against silent acceptance
of dummy values.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, KalshiRiskManager


@pytest.fixture
def risk():
    cfg = KalshiRiskConfig(
        max_spread_cents=10,
        min_depth_contracts=5,
    )
    return KalshiRiskManager(config=cfg)


def test_check_order_allowed_without_orderbook_params(risk):
    """Without spread/depth, check_order passes (no orderbook checks applied)."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
    )
    assert ok, f"Expected allowed but got: {reason}"


def test_check_order_blocked_when_spread_exceeds_max(risk):
    """Spread above max_spread_cents causes rejection."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        spread_cents=15,   # > max_spread_cents=10
    )
    assert not ok
    assert "Spread" in reason
    assert "orderbook check" in reason


def test_check_order_allowed_when_spread_at_max(risk):
    """Spread exactly at max_spread_cents is allowed."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        spread_cents=10,   # == max_spread_cents
    )
    assert ok, reason


def test_check_order_blocked_when_depth_below_min(risk):
    """Depth below min_depth_contracts causes rejection."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        depth_at_price=3,   # < min_depth_contracts=5
    )
    assert not ok
    assert "Depth" in reason
    assert "orderbook check" in reason


def test_check_order_allowed_when_depth_meets_min(risk):
    """Depth exactly at min_depth_contracts is allowed."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        depth_at_price=5,   # == min_depth_contracts
    )
    assert ok, reason


def test_changing_spread_changes_decision(risk):
    """Varying spread around the threshold flips the decision."""
    ok_tight, _ = risk.check_order("KXBTC", "crypto", 5, 50, spread_cents=5)
    ok_wide, _  = risk.check_order("KXBTC", "crypto", 5, 50, spread_cents=20)

    assert ok_tight, "tight spread should be allowed"
    assert not ok_wide, "wide spread should be blocked"


def test_changing_depth_changes_decision(risk):
    """Varying depth around the threshold flips the decision."""
    ok_deep, _    = risk.check_order("KXBTC", "crypto", 5, 50, depth_at_price=10)
    ok_shallow, _ = risk.check_order("KXBTC", "crypto", 5, 50, depth_at_price=2)

    assert ok_deep,    "deep orderbook should be allowed"
    assert not ok_shallow, "shallow orderbook should be blocked"


def test_order_intent_carries_orderbook_params():
    """OrderIntent now has spread_cents and depth_at_price fields (E1)."""
    from merid.event_venues.kalshi.order_router import OrderIntent, TradingMode
    intent = OrderIntent(
        ticker="KXBTC",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        spread_cents=8,
        depth_at_price=20,
    )
    assert intent.spread_cents == 8
    assert intent.depth_at_price == 20
