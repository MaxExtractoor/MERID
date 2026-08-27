"""Precision and settlement boundary tests for the 15m crypto signal path.

These tests enforce the three-layer precision model:

1. Raw source precision is preserved end-to-end (Decimal).
2. Settlement precision is driven by ``custom_strike.round_digits`` / asset table.
3. Display precision never bleeds into computation.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from merid.data.price_precision import (
    assert_market_precision,
    format_price,
    get_asset_settlement_digits,
    get_asset_settlement_quantum,
    parse_price,
    settlement_round,
)


@pytest.mark.parametrize(
    "asset,raw,expected_digits",
    [
        ("BTC", "65000.123", 2),
        ("ETH", "3500.456", 2),
        ("SOL", "96.78901", 4),
        ("XRP", "1.23456", 4),
        ("DOGE", "0.0848348", 7),
    ],
)
def test_settlement_round_quantizes_to_market_digits(asset, raw, expected_digits):
    """Each asset is quantized to its expected settlement quantum once."""
    price = parse_price(raw)
    rounded = settlement_round(price, expected_digits)
    assert rounded == Decimal(raw).quantize(Decimal(1).scaleb(-expected_digits))


@pytest.mark.parametrize(
    "asset,raw,expected_str",
    [
        ("BTC", "65000.123", "65000.12"),
        ("ETH", "3500.456", "3500.46"),
        ("SOL", "96.78901", "96.7890"),
        ("XRP", "1.23456", "1.2346"),
        ("DOGE", "0.0848348", "0.0848348"),
    ],
)
def test_format_price_uses_settlement_digits(asset, raw, expected_str):
    """Display formatting reflects the asset's settlement precision."""
    assert format_price(asset, raw) == expected_str


def test_parse_price_from_float_uses_full_string():
    """Converting a float to Decimal via str must not add binary artifacts."""
    price = parse_price(0.0848348)
    assert price == Decimal("0.0848348")


def test_parse_price_rejects_strings_and_missing():
    assert parse_price("") is None
    assert parse_price(None) is None
    assert parse_price("abc") is None


def test_assert_market_precision_accepts_full_doget_precision():
    assert_market_precision("DOGE", Decimal("0.0848348"), 7)


def test_assert_market_precision_rejects_truncated_doget():
    with pytest.raises(ValueError) as exc:
        assert_market_precision("DOGE", Decimal("0.0848"), 7)
    assert "retains only 4 decimals" in str(exc.value)


def test_assert_market_precision_rejects_mismatched_digits():
    with pytest.raises(ValueError) as exc:
        assert_market_precision("DOGE", Decimal("0.0848348"), 4)
    assert "does not match expected settlement precision" in str(exc.value)


@pytest.mark.parametrize(
    "asset,strike,raw_price",
    [
        ("BTC", Decimal("65000.00"), Decimal("65000.01")),   # 1 cent above
        ("BTC", Decimal("65000.00"), Decimal("64999.99")),   # 1 cent below
        ("ETH", Decimal("3500.00"), Decimal("3500.01")),
        ("ETH", Decimal("3500.00"), Decimal("3499.99")),
        ("SOL", Decimal("96.7800"), Decimal("96.7801")),     # 1 tick (0.0001)
        ("SOL", Decimal("96.7800"), Decimal("96.7799")),
        ("XRP", Decimal("1.2345"), Decimal("1.2346")),
        ("XRP", Decimal("1.2345"), Decimal("1.2344")),
        ("DOGE", Decimal("0.0848348"), Decimal("0.0848349")), # 1 tick (0.0000001)
        ("DOGE", Decimal("0.0848348"), Decimal("0.0848347")),
    ],
)
def test_boundary_above_below_one_settlement_tick(asset, strike, raw_price):
    """Strike comparison must be exact at the boundary plus/minus one tick.

    This is the core failure mode: truncating DOGE to 4 decimals turns
    0.0848349 into 0.0848 and flips the YES/NO outcome at the boundary.
    """
    digits = get_asset_settlement_digits(asset)
    quantum = get_asset_settlement_quantum(asset)

    quantized_strike = settlement_round(strike, digits)
    quantized_price = settlement_round(raw_price, digits)

    # Exactly one settlement tick above or below, quantized.
    if raw_price > strike:
        assert quantized_price == quantized_strike + quantum
    else:
        assert quantized_price == quantized_strike - quantum

    # Outcome comparison must not be ambiguous.
    assert quantized_price != quantized_strike


def test_no_early_rounding_doget_average():
    """Averaging DOGE raw ticks must not collapse precision before settlement.

    Simulates 61 one-second DOGE observations symmetric around 0.0848348 and
    verifies the mean and final quantized settlement keep 7 decimals.
    """
    base = Decimal("0.0848348")
    quantum = Decimal("0.0000001")
    samples = [base + (i - 30) * quantum for i in range(61)]  # -30q .. +30q
    raw_avg = sum(samples, Decimal("0")) / Decimal(len(samples))
    assert raw_avg == base
    quantized = settlement_round(raw_avg, 7)
    assert quantized == base
    assert format_price("DOGE", quantized) == "0.0848348"
