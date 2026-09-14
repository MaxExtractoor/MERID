"""Exact Kalshi fee pinned to real V2 fill records (2026-09-14, live account)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from merid.event_venues.kalshi.parabolic_fees import (
    kalshi_fee_cents_exact,
    kalshi_taker_fee_cents_parabolic,
)


@pytest.mark.parametrize(
    "price_cents, fee_dollars_from_kalshi",
    [
        (47, "0.0175"),  # KXBTC15M-26SEP031315-15 sell no 1.00 taker
        (56, "0.0173"),  # KXXRP15M-26SEP031300-00 buy yes 1.00 taker
        (55, "0.0174"),  # KXXRP15M-26SEP022315-15
        (41, "0.0170"),  # KXXRP15M-26SEP022100-00
        (42, "0.0171"),  # KXXRP15M-26SEP022015-15
        (40, "0.0168"),  # KXXRP15M-26SEP022015-15
        (1.1, "0.0008"),  # KXXRP15M-26SEP021730-30 buy yes @1.1c
    ],
)
def test_exact_taker_fee_matches_kalshi_fill_records(price_cents, fee_dollars_from_kalshi):
    fee_cents = kalshi_fee_cents_exact(price_cents / 100.0, 1, "taker")
    assert fee_cents == Decimal(fee_dollars_from_kalshi) * 100


def test_exact_fee_scales_with_fractional_count():
    # 0.11 contracts at 69c: 0.07*0.11*0.69*0.31 = 0.0016466 -> ceil to $0.0017 = 0.17c
    fee = kalshi_fee_cents_exact(0.69, Decimal("0.11"), "taker")
    assert fee == Decimal("0.17")
    # The whole-cent helper over-charges the same order by ~6x.
    assert kalshi_taker_fee_cents_parabolic(0.69, Decimal("0.11")) == 1


def test_exact_fee_zero_for_non_positive_count():
    assert kalshi_fee_cents_exact(0.5, 0, "taker") == 0
    assert kalshi_fee_cents_exact(0.5, Decimal("-1"), "taker") == 0
