"""Regression test for price_band filter issue.

This test ensures that NearSpotSelector does not drop all markets when
the price_bands feature is disabled (the safe default).

Bug: Commit c4216c68 changed use_price_bands default to True and CT
explicitly passed use_price_bands=True, causing all 41 markets to be
filtered out due to price_band constraints.

Fix: Changed CT to pass use_price_bands=False.
"""

import unittest
from decimal import Decimal
from typing import List

from merid.event_venues.kalshi.market_filter import (
    MarketCandidate,
    NearSpotSelector,
    select_near_spot_best_edge,
    enrich_candidates,
)


class TestPriceBandsRegression(unittest.TestCase):
    """Test that price_bands filtering behaves correctly."""

    def _make_candidate(
        self,
        ticker: str,
        underlying: str,
        mid_price_cents: int,
        timeframe: str = "15m",
    ) -> MarketCandidate:
        """Create a test market candidate."""
        return MarketCandidate(
            ticker=ticker,
            underlying=underlying,
            timeframe=timeframe,
            mid_price_cents=mid_price_cents,
            best_bid_cents=max(1, mid_price_cents - 2),
            best_ask_cents=min(99, mid_price_cents + 2),
            volume=100,
            open_interest=50,
        )

    def test_use_price_bands_false_keeps_candidates(self):
        """With use_price_bands=False, candidates should NOT be filtered by price."""
        # Create candidates with mid-prices across the range
        candidates: List[MarketCandidate] = [
            self._make_candidate("KXBTC-TEST-B80000", "BTC", 50),   # 50¢
            self._make_candidate("KXBTC-TEST-B85000", "BTC", 55),   # 55¢
            self._make_candidate("KXETH-TEST-B2000", "ETH", 45),     # 45¢
            self._make_candidate("KXETH-TEST-B2100", "ETH", 60),    # 60¢
        ]

        def get_spot(asset: str) -> float:
            spots = {"BTC": 85000.0, "ETH": 2100.0}
            return spots.get(asset, 0.0)

        def compute_edge(c: MarketCandidate, spot: float, strike: float) -> Decimal:
            # Simple edge calculation for testing
            return Decimal("0.05")

        # Call with use_price_bands=False (the safe default)
        result = select_near_spot_best_edge(
            candidates,
            get_spot=get_spot,
            compute_edge=compute_edge,
            max_per_bucket=2,
            use_price_bands=False,  # KEY: This should NOT filter by price bands
        )

        # All candidates should be kept when price_bands is disabled
        self.assertEqual(
            len(result),
            len(candidates),
            f"Expected all {len(candidates)} candidates to be kept with use_price_bands=False, "
            f"but only {len(result)} were kept. "
            f"This indicates the price_band filter is incorrectly dropping markets.",
        )

    def test_near_spot_selector_default_is_safe(self):
        """NearSpotSelector.select_near_spot should have use_price_bands=False by default."""
        selector = NearSpotSelector(spot_source=lambda asset: 100.0)
        
        # Check the default value by inspecting the method signature
        import inspect
        sig = inspect.signature(selector.select_near_spot)
        default = sig.parameters['use_price_bands'].default
        
        self.assertIs(
            default,
            False,
            "NearSpotSelector.select_near_spot must have use_price_bands=False by default "
            "to prevent accidental filtering of all markets. "
            f"Current default: {default}",
        )

    def test_ct_does_not_force_price_bands_true(self):
        """Verify CT code doesn't hardcode use_price_bands=True."""
        import ast
        import inspect
        from merid.trading import kalshi_continuous_trader

        # Read the source file
        source_file = inspect.getfile(kalshi_continuous_trader)
        with open(source_file, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())

        # Find any calls to select_near_spot with use_price_bands=True
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for keyword arguments
                for kw in node.keywords:
                    if kw.arg == 'use_price_bands':
                        if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            # Get line number if available
                            lineno = getattr(node, 'lineno', 'unknown')
                            violations.append(lineno)

        if violations:
            self.fail(
                f"Found use_price_bands=True in kalshi_continuous_trader.py "
                f"at line(s): {violations}. "
                "This will cause all markets to be filtered out! "
                "Change to use_price_bands=False."
            )


if __name__ == '__main__':
    unittest.main()
