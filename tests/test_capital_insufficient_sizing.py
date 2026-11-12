"""
Capital-insufficient / order-minimum-infeasible contract tests.

Sizing works on the centi-contract grid (0.01-contract quantum), so the
rejection boundary is "max_notional cannot afford one centi-contract", not
"cannot afford one whole contract".  A max notional that fits a fractional
size must size down, not reject.
"""

from decimal import Decimal

import pytest

from merid.prediction.unified_sizing import compute_order_size


def test_max_notional_fits_fractional_size():
    """$0.037 max notional at 10c affords 0.37 contracts -> size down, not reject."""
    count, notional, metadata = compute_order_size(
        bankroll_usd=Decimal("1.85"),
        price_cents=10,
        asset="BTC",
        max_notional_usd=Decimal("0.037"),
    )
    assert count > 0
    assert count <= Decimal("0.37")
    assert notional <= Decimal("0.037")
    assert "capital_insufficient" not in metadata.get("reason", "")


def test_max_notional_below_centi_contract_rejects():
    """max_notional below one centi-contract cost -> explicit reject.

    One centi-contract at 10c costs $0.001; $0.0009 cannot afford it."""
    count, notional, metadata = compute_order_size(
        bankroll_usd=Decimal("1.85"),
        price_cents=10,
        asset="BTC",
        max_notional_usd=Decimal("0.0009"),
    )
    assert count == 0
    assert notional == Decimal("0")
    assert metadata["reason"] == "capital_insufficient_max_notional"
    assert metadata["contract_cost_usd"] == 0.10
    assert metadata["max_notional_usd"] == 0.0009


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
