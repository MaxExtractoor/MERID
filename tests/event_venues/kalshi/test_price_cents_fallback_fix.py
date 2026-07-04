"""Regression test for price_cents=1 fallback bug fix.

BUG-PROD-001: price_cents=1 fallback in strategy.py was causing Kelly sizing to return 0 contracts,
blocking all trades. The fallback used probability-derived pricing which could return 1 cent when
market_prob was very low, causing the position sizer to return 0 contracts.

Fix: Changed fallback from probability-derived (max(1, min(99, int(round(market_prob * 100)))))
to safe default of 50 cents, which is the midpoint for binary options.

2026 UPDATE: Price clamping now uses [15, 70] range instead of [1, 99] to prevent $0.99 purchases.
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestPriceCentsFallbackFix:
    """Test that price_cents fallback uses 50c instead of probability-derived 1c."""

    def test_dynamic_sizing_get_actual_contract_price_cents_default(self):
        """Verify dynamic_sizing.get_actual_contract_price_cents returns 50 as safe default."""
        from merid.prediction.dynamic_sizing import get_actual_contract_price_cents
        
        # Test with non-existent ticker (should return safe default)
        price = get_actual_contract_price_cents("FAKE-TICKER-123", "yes")
        assert price == 50, f"Expected safe default of 50c, got {price}c"
        
        # Test with market_prob=0.01 (old code would return 1)
        price = get_actual_contract_price_cents("FAKE-TICKER-123", "yes", market_prob=0.01)
        assert price == 50, f"Expected safe default of 50c even with low market_prob, got {price}c"
