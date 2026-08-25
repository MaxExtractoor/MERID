"""
Capital-insufficient / order-minimum-infeasible contract tests.

When a tiny bankroll drives the per-asset max notional below the cost of one
contract, sizing must reject with an explicit reason rather than letting the
candidate reach the router and fail with an opaque sizing/position error.
"""

from decimal import Decimal

import pytest

from merid.prediction.unified_sizing import compute_order_size


def test_max_notional_below_contract_cost_rejects():
    """A $0.037 max notional cannot afford one contract at 10c -> reject."""
    count, notional, metadata = compute_order_size(
        bankroll_usd=Decimal("1.85"),
        price_cents=10,
        asset="BTC",
        max_notional_usd=Decimal("0.037"),
    )
    assert count == 0
    assert notional == Decimal("0")
    assert metadata["reason"] == "capital_insufficient_max_notional"
    assert metadata["contract_cost_usd"] == 0.10
    assert metadata["max_notional_usd"] == 0.037


def test_max_notional_equal_to_contract_cost_allows_one_contract():
    """A $0.10 max notional exactly matches one 10c contract -> allow 1."""
    count, notional, metadata = compute_order_size(
        bankroll_usd=Decimal("1.85"),
        price_cents=10,
        asset="BTC",
        max_notional_usd=Decimal("0.10"),
    )
    assert count == 1
    assert notional == Decimal("0.10")
    assert "capital_insufficient" not in metadata.get("reason", "")
