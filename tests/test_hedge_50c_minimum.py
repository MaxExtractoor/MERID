"""Test that hedge engine enforces 50c minimum entry price.

This test verifies the fix for the bug where hedge orders were being placed
at lottery-ticket prices (e.g., 5c) that have statistically poor win rates
(10.4% for prices < $0.30 based on 2026-07-03 analysis).

The hedge engine now enforces the same 50c minimum as the agent grid to prevent
hedge orders at prices that are too low to be viable.
"""

import unittest
from unittest.mock import Mock, MagicMock


class TestHedgeEngine50cMinimum(unittest.TestCase):
    """Test hedge engine enforces 50c minimum entry price."""

    def test_resolve_mid_price_enforces_50c_minimum(self):
        """Test that _resolve_mid_price returns 0 for prices below 50c."""
        from merid.hedging.engine import CryptoHedgeEngine

        # Create mock market catalog with a market at 5c (below minimum)
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.mid_price_cents = 5  # 5 cents - should be rejected
        mock_catalog.get_current_15m_market = Mock(return_value=mock_market)

        # Call _resolve_mid_price
        mid_price = CryptoHedgeEngine._resolve_mid_price("ETH", "15m", mock_catalog)

        # Should return 0 to signal "skip this hedge"
        self.assertEqual(mid_price, 0, "Should return 0 for prices below 50c")

    def test_resolve_mid_price_accepts_50c(self):
        """Test that _resolve_mid_price accepts prices at or above 50c."""
        from merid.hedging.engine import CryptoHedgeEngine

        # Create mock market catalog with a market at 50c (minimum acceptable)
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.mid_price_cents = 50  # 50 cents - should be accepted
        mock_catalog.get_current_15m_market = Mock(return_value=mock_market)

        # Call _resolve_mid_price
        mid_price = CryptoHedgeEngine._resolve_mid_price("ETH", "15m", mock_catalog)

        # Should return 50 (the actual price)
        self.assertEqual(mid_price, 50, "Should return 50c for minimum acceptable price")

    def test_resolve_mid_price_accepts_80c(self):
        """Test that _resolve_mid_price accepts prices above 50c."""
        from merid.hedging.engine import CryptoHedgeEngine

        # Create mock market catalog with a market at 80c (typical price)
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.mid_price_cents = 80  # 80 cents - should be accepted
        mock_catalog.get_current_15m_market = Mock(return_value=mock_market)

        # Call _resolve_mid_price
        mid_price = CryptoHedgeEngine._resolve_mid_price("ETH", "15m", mock_catalog)

        # Should return 80 (the actual price)
        self.assertEqual(mid_price, 80, "Should return 80c for typical price")

    def test_compute_hedge_orders_skips_below_50c(self):
        """Test that compute_hedge_orders skips hedges when price is below 50c."""
        from merid.hedging.engine import CryptoHedgeEngine, HedgeResult
        from merid.hedging.config import HedgeConfig, TimeframeHedgeRule

        # Create mock exposure with net delta
        mock_exposure = Mock()
        mock_exposure.net_delta_cents = Mock(return_value=1000)  # $10 exposure

        # Create mock config
        mock_config = Mock(spec=HedgeConfig)
        mock_config.enabled = True
        mock_config.timeframes = {"15m": TimeframeHedgeRule()}
        mock_config.slice_value_cents = Mock(return_value=10000)
        mock_config.get_timeframe_rule = Mock(return_value=TimeframeHedgeRule())
        mock_config.max_net_exposure_cents = Mock(return_value=5000)

        # Create mock market catalog with market at 5c (below minimum)
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.mid_price_cents = 5  # 5 cents - should be rejected
        mock_market.ticker = "KXETH-15M-UP-1756"
        mock_catalog.get_current_15m_market = Mock(return_value=mock_market)

        # Compute hedge orders
        engine = CryptoHedgeEngine()
        result = engine.compute_hedge_orders(
            exposure=mock_exposure,
            config=mock_config,
            bankroll_cents=100000,
            market_catalog=mock_catalog,
        )

        # Should return empty result (no hedge orders)
        self.assertIsInstance(result, HedgeResult)
        self.assertEqual(len(result.orders), 0, "Should skip hedge when price is below 50c")

    def test_compute_hedge_orders_accepts_at_50c(self):
        """Test that compute_hedge_orders accepts hedges when price is at 50c."""
        from merid.hedging.engine import CryptoHedgeEngine, HedgeResult
        from merid.hedging.config import HedgeConfig, TimeframeHedgeRule

        # Create mock exposure with net delta
        mock_exposure = Mock()
        mock_exposure.net_delta_cents = Mock(return_value=1000)  # $10 exposure

        # Create mock config
        mock_config = Mock(spec=HedgeConfig)
        mock_config.enabled = True
        mock_config.timeframes = {"15m": TimeframeHedgeRule()}
        mock_config.slice_value_cents = Mock(return_value=10000)
        mock_config.get_timeframe_rule = Mock(return_value=TimeframeHedgeRule())
        mock_config.max_net_exposure_cents = Mock(return_value=5000)

        # Create mock market catalog with market at 50c (minimum acceptable)
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.mid_price_cents = 50  # 50 cents - should be accepted
        mock_market.ticker = "KXETH-15M-UP-1756"
        mock_catalog.get_current_15m_market = Mock(return_value=mock_market)

        # Compute hedge orders
        engine = CryptoHedgeEngine()
        result = engine.compute_hedge_orders(
            exposure=mock_exposure,
            config=mock_config,
            bankroll_cents=100000,
            market_catalog=mock_catalog,
        )

        # Should return hedge orders
        self.assertIsInstance(result, HedgeResult)
        self.assertGreater(len(result.orders), 0, "Should generate hedge orders when price is at 50c")


if __name__ == "__main__":
    unittest.main()
