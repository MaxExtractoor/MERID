"""Test that order router enforces 50c minimum entry price.

This test verifies the fix for the bug where orders were being placed
at lottery-ticket prices (e.g., 5c) that have statistically poor win rates
(10.4% for prices < $0.30 based on 2026-07-03 analysis).

The order router now enforces the same 50c minimum as the agent grid to prevent
orders at prices that are too low to be viable.
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock


class TestOrderRouter50cMinimum(unittest.TestCase):
    """Test order router enforces 50c minimum entry price."""

    def test_order_router_rejects_below_50c(self):
        """Test that route_order_async rejects orders below 50c."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        async def run_test():
            # Create an order intent with 5c price (below minimum)
            intent = OrderIntent(
                ticker="KXETH15M-26JUN151530-1756",
                side="no",
                action="buy",
                price_cents=5,  # 5 cents - should be rejected
                count=1,
                source="agent_grid",
            )

            # Route the order
            result = await route_order_async(intent)

            # Should be rejected due to minimum price violation
            self.assertEqual(result.status, "rejected")
            self.assertIn("min_price_violation", result.reason)
            self.assertIn("5<50", result.reason)

        # Run the async test
        asyncio.run(run_test())

    def test_order_router_rejects_49c(self):
        """Test that route_order_async rejects orders at 49c (just below minimum)."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        async def run_test():
            # Create an order intent with 49c price (just below minimum)
            intent = OrderIntent(
                ticker="KXETH15M-26JUN151530-1756",
                side="no",
                action="buy",
                price_cents=49,  # 49 cents - should be rejected
                count=1,
                source="agent_grid",
            )

            # Route the order
            result = await route_order_async(intent)

            # Should be rejected due to minimum price violation
            self.assertEqual(result.status, "rejected")
            self.assertIn("min_price_violation", result.reason)
            self.assertIn("49<50", result.reason)

        # Run the async test
        asyncio.run(run_test())

    def test_order_router_hedge_engine_bypass(self):
        """Test that hedge_engine source bypasses 50c minimum (hedge engine has its own checks)."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        async def run_test():
            # Create an order intent with 5c price but source=hedge_engine
            intent = OrderIntent(
                ticker="KXETH15M-26JUN151530-1756",
                side="no",
                action="buy",
                price_cents=5,  # 5 cents - normally rejected
                count=1,
                source="hedge_engine",  # Exception: hedge_engine bypasses this check
            )

            # Mock the venue gate to return a mode
            with patch('merid.event_venues.kalshi.order_router.get_venue_gate') as mock_gate:
                mock_mode = Mock()
                mock_mode.value = "mock"
                mock_gate.return_value.mode = mock_mode

                # Mock the order deduplication cache
                with patch('merid.event_venues.kalshi.order_router._dedup_cache') as mock_cache:
                    mock_cache.return_value.check = Mock(return_value=False)
                    mock_cache.return_value.add = Mock()

                    # Mock the rate limiter
                    with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_rl:
                        mock_rl.return_value.acquire = AsyncMock(return_value=True)

                    # Route the order
                    result = await route_order_async(intent)

                    # Should NOT be rejected due to minimum price violation
                    # (hedge_engine source bypasses this check)
                    # It may be rejected for other reasons (scope, etc.), but not min_price_violation
                    if result.status == "rejected":
                        self.assertNotIn("min_price_violation", result.reason)

        # Run the async test
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
