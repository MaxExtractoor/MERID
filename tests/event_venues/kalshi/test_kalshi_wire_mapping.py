"""Canonical intent-to-wire and exposure matrix tests.

These tests lock in the four Kalshi V2 order forms, the legacy-to-V2 price
conversion, and the order_router._build_create_order_request side/outcome
normalization.  They are the regression suite for the side-flip fixes.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.binary_price_space import (
    held_outcome_from_legacy,
    legacy_to_v2,
    parse_kalshi_side,
    traded_side_from_held,
)
from merid.event_venues.kalshi.order_router import OrderIntent, _build_create_order_request


@pytest.mark.parametrize(
    "traded_side,action,expected_held",
    [
        ("yes", "buy", "yes"),
        ("no", "sell", "yes"),
        ("no", "buy", "no"),
        ("yes", "sell", "no"),
    ],
)
def test_held_outcome_from_legacy(traded_side, action, expected_held):
    assert held_outcome_from_legacy(traded_side, action) == expected_held


@pytest.mark.parametrize(
    "held,action,expected_traded",
    [
        ("yes", "buy", "yes"),
        ("yes", "sell", "no"),
        ("no", "buy", "no"),
        ("no", "sell", "yes"),
    ],
)
def test_traded_side_from_held(held, action, expected_traded):
    assert traded_side_from_held(held, action) == expected_traded


@pytest.mark.parametrize(
    "action,traded_side,price,expected_book,expected_yes_price",
    [
        ("buy", "yes", 55, "bid", 55),
        ("sell", "yes", 55, "ask", 55),
        ("buy", "no", 32, "ask", 68),
        ("sell", "no", 32, "bid", 68),
    ],
)
def test_legacy_to_v2_direction_matrix(
    action, traded_side, price, expected_book, expected_yes_price
):
    book, yes_price = legacy_to_v2(action, traded_side, price)
    assert book == expected_book
    assert yes_price == expected_yes_price


@pytest.mark.parametrize(
    "kalshi_side,expected_traded,expected_action",
    [
        ("BUY_YES", "yes", "buy"),
        ("SELL_YES", "yes", "sell"),
        ("BUY_NO", "no", "buy"),
        ("SELL_NO", "no", "sell"),
    ],
)
def test_parse_kalshi_side(kalshi_side, expected_traded, expected_action):
    side, action = parse_kalshi_side(kalshi_side)
    assert side == expected_traded
    assert action == expected_action


def _make_intent(
    side: str,
    action: str,
    price: int = 55,
    count: int = 1,
    entry_or_exit: str = "entry",
    exchange_index: int = 2,
) -> OrderIntent:
    return OrderIntent(
        ticker="KXBTC15M-TEST-50000",
        price_cents=price,
        count=count,
        side=side,
        action=action,
        client_order_id=f"test_{side}_{action}",
        idempotency_key=f"idemp_{side}_{action}",
        order_attempt_id=f"attempt_{side}_{action}",
        decision_id="decision",
        run_id="run",
        process_id="pid",
        reason="test",
        entry_or_exit=entry_or_exit,
        exchange_index=exchange_index,
    )


@pytest.mark.parametrize(
    "side,action,expected_outcome",
    [
        ("yes", "buy", "yes"),
        ("no", "buy", "no"),
        ("yes", "sell", "yes"),
        ("no", "sell", "no"),
        ("BUY_YES", "buy", "yes"),
        ("SELL_NO", "sell", "no"),
    ],
)
def test_build_create_order_request_traded_outcome(side, action, expected_outcome):
    intent = _make_intent(side, action)
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=intent.exchange_index,
        final_price_cents=55,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=False,
    )
    assert req.side == action
    assert req.outcome == expected_outcome
    assert req.exchange_index == 2


def test_build_create_order_request_reduce_only_defaults_for_exit():
    intent = _make_intent("yes", "sell", entry_or_exit="exit")
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=1,
        final_price_cents=5,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=False,
    )
    assert req.reduce_only is True


def test_build_create_order_request_reduce_only_false_is_respected():
    intent = _make_intent("yes", "sell", entry_or_exit="exit")
    intent.reduce_only = False
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=1,
        final_price_cents=5,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=False,
    )
    assert req.reduce_only is False


def test_build_create_order_request_resolves_stp_from_liquidity_role():
    intent = _make_intent("yes", "buy", entry_or_exit="entry")
    intent.liquidity_role = "maker"
    intent.self_trade_prevention_type = None
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=2,
        final_price_cents=55,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=True,
    )
    assert req.self_trade_prevention_type == "maker"


def test_build_create_order_request_resolves_stp_from_explicit_intent():
    intent = _make_intent("yes", "buy", entry_or_exit="entry")
    intent.self_trade_prevention_type = "taker_at_cross"
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=2,
        final_price_cents=55,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=False,
    )
    assert req.self_trade_prevention_type == "taker_at_cross"


def test_build_create_order_request_computes_max_execution_cost_from_ev():
    intent = _make_intent("yes", "buy", entry_or_exit="entry", count=2)
    intent.all_in_cost_cents = 22.0  # 20c price + 2c fee
    intent.ev_net_cents = 33.0       # p=0.55 -> break-even at 55c/contract
    intent.fee_cents = 2.0
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=2,
        final_price_cents=20,
        effective_order_type="limit",
        effective_tif="IOC",
        expiration_ts=None,
        post_only=False,
    )
    # max = count * (all_in + ev_net) = 2 * (22 + 33) = 110 cents
    assert req.max_execution_cost_cents == 110


def test_build_create_order_request_computes_max_execution_cost_from_p_selected():
    intent = _make_intent("no", "buy", entry_or_exit="entry", count=1)
    intent.p_selected = 0.55
    intent.fee_cents = 0.0
    req = _build_create_order_request(
        intent,
        ticker=intent.ticker,
        exchange_index=2,
        final_price_cents=20,
        effective_order_type="limit",
        effective_tif="GTC",
        expiration_ts=1700000000,
        post_only=False,
    )
    # max = count * p_selected * 100 = 55 cents; bounded below by all_in (20+0) + 1
    assert req.max_execution_cost_cents == 55
