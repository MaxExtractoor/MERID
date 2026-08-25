"""Boundary tests for fractional exit invariants.

The 15m stack must handle centi-contract (0.01 contract) quantities exactly
throughout the exit path.  Whole-contract rounding is a production blocker if
partial fills or partial exits occur.
"""

from decimal import Decimal
import pytest


@pytest.mark.parametrize(
    "pre_cc, requested_cc, expected_post_cc",
    [
        (100, 25, 75),    # 1.00 -> 0.75 requested
        (100, 50, 50),    # 1.00 -> 0.50 requested
        (75, 25, 50),     # 0.75 -> 0.50 requested
        (50, 50, 0),      # 0.50 -> flat requested
        (1, 1, 0),        # 0.01 -> flat requested
        (100, 100, 0),    # 1.00 -> flat requested (full exit)
    ],
)
def test_assert_exit_delta_boundary_table(pre_cc, requested_cc, expected_post_cc):
    """assert_exit_delta must accept all canonical fractional requested exits."""
    from merid.loop_15m import assert_exit_delta

    result = assert_exit_delta(pre_cc, requested_cc, market_id="KXBTC15M", position_id="pos-1")
    assert result == expected_post_cc, f"expected post {expected_post_cc}, got {result}"


@pytest.mark.parametrize(
    "pre_cc, requested_cc",
    [
        (100, 0),      # zero exit count
        (0, 50),       # no position to exit
        (100, 150),    # over-close
        (100, -10),    # negative exit
    ],
)
def test_assert_exit_delta_rejects_invalid_transitions(pre_cc, requested_cc):
    """assert_exit_delta must raise on any invalid close-only transition."""
    from merid.loop_15m import assert_exit_delta

    with pytest.raises(RuntimeError):
        assert_exit_delta(pre_cc, requested_cc, market_id="KXBTC15M", position_id="pos-1")


def test_order_intent_position_fp_is_exact():
    """OrderIntent pre/post position FP fields must be used in centi-contracts."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    from merid.event_venues.kalshi.order_intent_contract import normalize_order

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="sell",
        price_cents=50,
        count=0,  # display-only floor for 0.75
        count_fp=Decimal("0.75"),
        entry_or_exit="exit",
        exit_reason="exit_tp",
        pre_position_size=1,            # whole-contract floor
        expected_post_position_size=0,  # whole-contract floor
        pre_position_fp=100,            # exact 1.00 contract
        expected_post_position_fp=25,   # exact 0.25 contract residual
        reduce_only=True,
    )

    canonical = normalize_order(intent, position_side="yes")

    # Canonical before/after use the exact FP fields, not the rounded display values.
    assert canonical.expected_position_before == 100
    assert canonical.expected_position_after == 25
    assert canonical.qty_cc == 75


def test_order_router_exit_delta_uses_position_fp():
    """_check_exit_delta_invariant must prefer the intent's exact pre_position_fp."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _check_exit_delta_invariant, TradingMode

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="sell",
        price_cents=50,
        count=0,
        count_fp=Decimal("0.25"),
        entry_or_exit="exit",
        exit_reason="exit_tp",
        pre_position_fp=100,
        expected_post_position_fp=75,
        reduce_only=True,
    )

    result = _check_exit_delta_invariant(intent, TradingMode.PAPER)
    assert result is None, f"valid 1.00 -> 0.75 exit was rejected: {result}"


def test_order_router_exit_delta_rejects_over_close():
    """_check_exit_delta_invariant must reject a requested exit larger than position."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _check_exit_delta_invariant, TradingMode

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="sell",
        price_cents=50,
        count=0,
        count_fp=Decimal("1.25"),
        entry_or_exit="exit",
        exit_reason="exit_tp",
        pre_position_fp=100,
        expected_post_position_fp=-25,
        reduce_only=True,
    )

    result = _check_exit_delta_invariant(intent, TradingMode.PAPER)
    assert result is not None and result.status == "rejected"


@pytest.mark.parametrize(
    "pre_cc, requested_cc, expected_post_from_intent",
    [
        (100, 25, 75),
        (100, 100, 0),
    ],
)
def test_order_router_exit_delta_matches_intent_post(pre_cc, requested_cc, expected_post_from_intent):
    """_check_exit_delta_invariant must cross-check expected_post_position_fp."""
    from merid.event_venues.kalshi.order_router import OrderIntent, _check_exit_delta_invariant, TradingMode

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="sell",
        price_cents=50,
        count=requested_cc // 100,
        count_fp=Decimal(requested_cc) / Decimal("100"),
        entry_or_exit="exit",
        exit_reason="exit_tp",
        pre_position_fp=pre_cc,
        expected_post_position_fp=expected_post_from_intent,
        reduce_only=True,
    )

    result = _check_exit_delta_invariant(intent, TradingMode.PAPER)
    assert result is None, f"valid exit was rejected: {result}"
