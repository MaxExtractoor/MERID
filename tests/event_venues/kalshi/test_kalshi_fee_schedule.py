"""Kalshi fee schedule audit tests.

These tests pin the parabolic fee formula against the official Kalshi fee
schedule examples and document the difference between the canonical
parabolic fee (merid.event_venues.kalshi.parabolic_fees) and the legacy
fee wrapper (merid.event_venues.kalshi.fees) that applies a 2c minimum.

The 2c floor is intentionally left un-touched in live trading until we
validate actual exchange-reported fees and any crypto 15m series-specific
multiplier.  These tests are the shadow truth source for that validation.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.fees import (
    calculate_kalshi_fee_cents,
    calculate_kalshi_fee_per_contract_cents,
)
from merid.event_venues.kalshi.parabolic_fees import (
    kalshi_taker_fee_cents_parabolic,
)


class TestKalshiOfficialFeeExamples:
    """Parabolic fee formula against Kalshi-published examples.

    Source: Kalshi Fee Schedule, effective July 7, 2026.
    Formula: fee ($) = round up(M * 0.07 * C * P * (1 - P))
    With the default multiplier M = 1 for standard event contracts.
    """

    @pytest.mark.parametrize(
        "price_dollars,contracts,expected_cents",
        [
            # Official examples from the fee schedule.
            (0.01, 1, 1),      # 1 contract at 1c -> $0.01 fee
            (0.50, 1, 2),      # 1 contract at 50c -> $0.02 fee
            (0.10, 100, 63),   # 100 contracts at 10c -> $0.63 fee
            (0.40, 100, 168),  # 100 contracts at 40c -> $1.68 fee
            (0.50, 100, 175),  # 100 contracts at 50c -> $1.75 fee
            (0.90, 100, 63),   # 100 contracts at 90c -> $0.63 fee
            # Symmetry sanity checks.
            (0.05, 10, 4),     # ceil(0.07 * 10 * 0.05 * 0.95 * 100) = 4
            (0.95, 10, 4),     # Same by symmetry
            (0.99, 1, 1),      # Same as P=0.01 by symmetry
        ],
    )
    def test_official_examples(self, price_dollars, contracts, expected_cents):
        """Canonical parabolic fee must match the official schedule examples."""
        fee = kalshi_taker_fee_cents_parabolic(price_dollars, contracts)
        assert fee == expected_cents, (
            f"P={price_dollars}, C={contracts}: expected {expected_cents}c, got {fee}c"
        )


class TestLegacyFeesVsParabolicFees:
    """Shadow comparison: fees.py (tiered rates) vs canonical parabolic formula.

    For 1-contract, low/high-priced orders the per-contract 2c floor has been
    removed; both calculators now agree at 1c.  The only remaining discrepancy
    is tiered rates (5% for 100-999 contracts, 3% for 1000+) in fees.py versus
    the flat 7% taker rate in parabolic_fees.py.  These tests document that
    divergence for large-size fills.
    """

    @pytest.mark.parametrize(
        "price_cents",
        [10, 14, 16, 91],
    )
    def test_one_contract_matches_canonical_at_extremes(self, price_cents):
        """For 1 contract at OTM/ITM prices the Kalshi fee rounds to 1c."""
        legacy_fee = calculate_kalshi_fee_per_contract_cents(1, price_cents)
        canonical_fee = kalshi_taker_fee_cents_parabolic(price_cents / 100.0, 1)

        assert canonical_fee == 1
        assert legacy_fee == float(canonical_fee)

    @pytest.mark.parametrize(
        "price_cents",
        [23, 50, 55],
    )
    def test_legacy_fee_matches_canonical_at_higher_raw_fees(self, price_cents):
        """When the raw fee is already >= 2c the legacy floor is not active."""
        legacy_fee = calculate_kalshi_fee_per_contract_cents(1, price_cents)
        canonical_fee = kalshi_taker_fee_cents_parabolic(price_cents / 100.0, 1)
        assert legacy_fee == float(canonical_fee)

    def test_canonical_total_fee_for_100_contracts(self):
        """Both calculators now use the flat 7% taker rate and agree.

        fees.py retired the mistaken 5%/3% volume tiers (Kalshi has no volume
        tiers — the only multiplier is per-market M).  The historical
        45c-vs-63c shadow discrepancy is resolved: both return 63c.
        """
        price_cents = 10
        total_legacy = calculate_kalshi_fee_cents(100, price_cents)
        total_canonical = kalshi_taker_fee_cents_parabolic(price_cents / 100.0, 100)

        # Flat 7%: ceil(0.07 * 100 * 0.10 * 0.90 * 100) = 63c
        assert total_canonical == 63
        assert total_legacy == 63
