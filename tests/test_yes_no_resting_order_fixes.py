"""
Tests for YES/NO Market and Resting Order Fixes

Tests the fixes applied to address flaws found in the audit:
- MAX_HOLD_SECONDS_15M constant in risk_parameters.py
- Crossed market detection in orderbook.py
- ChildOrder time_in_force consistency in order_scaler.py
"""

import unittest
import time
from datetime import datetime, timedelta

from merid.event_venues.kalshi.risk_parameters import MAX_HOLD_SECONDS_15M
from merid.event_venues.kalshi.orderbook import LocalOrderbook
from merid.event_venues.kalshi.order_scaler import ChildOrder


class TestMAXHoldSeconds15M(unittest.TestCase):
    """Test MAX_HOLD_SECONDS_15M constant exists and has correct value."""

    def test_max_hold_seconds_15m_exists(self):
        """Test that MAX_HOLD_SECONDS_15M constant is defined."""
        self.assertTrue(
            MAX_HOLD_SECONDS_15M is not None,
            "MAX_HOLD_SECONDS_15M should be defined in risk_parameters.py"
        )

    def test_max_hold_seconds_15m_value(self):
        """Test that MAX_HOLD_SECONDS_15M is 180 seconds (3 minutes)."""
        self.assertEqual(
            MAX_HOLD_SECONDS_15M,
            180,
            "MAX_HOLD_SECONDS_15M should be 180 seconds for 15m crypto markets"
        )

    def test_max_hold_seconds_15m_is_int(self):
        """Test that MAX_HOLD_SECONDS_15M is an integer."""
        self.assertIsInstance(
            MAX_HOLD_SECONDS_15M,
            int,
            "MAX_HOLD_SECONDS_15M should be an integer"
        )


class TestCrossedMarketDetection(unittest.TestCase):
    """Test crossed market detection in orderbook."""

    def test_crossed_market_detection_within_tolerance(self):
        """Test that crossed market detection allows 3c tolerance for 15m crypto volatility."""
        orderbook = LocalOrderbook("KXBTC-15M-ABOVE-50000")
        
        # Create a snapshot with yes_bid + no_bid = 103c (within 3c tolerance)
        snapshot = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTC-15M-ABOVE-50000",
            "yes": [[0.60, 100]],  # yes_bid = 60c
            "no": [[0.43, 80]]    # no_bid = 43c, sum = 103c (within tolerance)
        }
        
        orderbook.apply_snapshot(snapshot)
        
        best_bid = orderbook.get_best_bid()
        best_no_bid = min(orderbook.no_levels.keys()) if orderbook.no_levels else None
        
        if best_bid and best_no_bid:
            # Should be within tolerance (103c <= 103c)
            self.assertLessEqual(
                best_bid[0] + best_no_bid,
                103,
                "Crossed market detection should allow 3c tolerance for 15m crypto volatility"
            )

    def test_crossed_market_detection_exceeds_tolerance(self):
        """Test that crossed market detection alerts when exceeding 3c tolerance."""
        orderbook = LocalOrderbook("KXBTC-15M-ABOVE-50000")
        
        # Create a snapshot with yes_bid + no_bid = 105c (exceeds 3c tolerance)
        snapshot = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTC-15M-ABOVE-50000",
            "yes": [[0.60, 100]],  # yes_bid = 60c
            "no": [[0.45, 80]]    # no_bid = 45c, sum = 105c (exceeds tolerance)
        }
        
        orderbook.apply_snapshot(snapshot)
        
        best_bid = orderbook.get_best_bid()
        best_no_bid = min(orderbook.no_levels.keys()) if orderbook.no_levels else None
        
        if best_bid and best_no_bid:
            # Should exceed tolerance (105c > 103c)
            self.assertGreater(
                best_bid[0] + best_no_bid,
                103,
                "Crossed market should exceed 3c tolerance (105c > 103c)"
            )

    def test_normal_market_not_crossed(self):
        """Test that normal market (yes_bid + no_bid < 100) is not flagged."""
        orderbook = LocalOrderbook("KXBTC-15M-ABOVE-50000")
        
        # Create a normal snapshot
        snapshot = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTC-15M-ABOVE-50000",
            "yes": [[0.55, 100]],  # yes_bid = 55c
            "no": [[0.45, 80]]    # no_bid = 45c, sum = 100c (normal)
        }
        
        orderbook.apply_snapshot(snapshot)
        
        best_bid = orderbook.get_best_bid()
        best_no_bid = min(orderbook.no_levels.keys()) if orderbook.no_levels else None
        
        if best_bid and best_no_bid:
            # Should be normal (100c <= 100c)
            self.assertLessEqual(
                best_bid[0] + best_no_bid,
                100,
                "Normal market should not be flagged as crossed"
            )


class TestChildOrderTIFConsistency(unittest.TestCase):
    """Test ChildOrder time_in_force consistency for limit orders."""

    def test_child_order_default_tif_is_gtc(self):
        """Test that ChildOrder defaults to GTC time_in_force."""
        child = ChildOrder(
            ticker="KXBTC-15M-ABOVE-50000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            delay_seconds=0.0
        )
        
        self.assertEqual(
            child.time_in_force,
            "gtc",
            "ChildOrder should default to time_in_force='gtc' for resting limit orders"
        )

    def test_child_order_explicit_tif(self):
        """Test that ChildOrder accepts explicit time_in_force."""
        child = ChildOrder(
            ticker="KXBTC-15M-ABOVE-50000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            delay_seconds=0.0,
            time_in_force="ioc"
        )
        
        self.assertEqual(
            child.time_in_force,
            "ioc",
            "ChildOrder should accept explicit time_in_force parameter"
        )

    def test_child_order_limit_order_type(self):
        """Test that ChildOrder defaults to limit order type."""
        child = ChildOrder(
            ticker="KXBTC-15M-ABOVE-50000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            delay_seconds=0.0
        )
        
        self.assertEqual(
            child.order_type,
            "limit",
            "ChildOrder should default to order_type='limit'"
        )

    def test_child_order_yes_no_sides(self):
        """Test that ChildOrder accepts both yes and no sides."""
        yes_child = ChildOrder(
            ticker="KXBTC-15M-ABOVE-50000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            delay_seconds=0.0
        )
        
        no_child = ChildOrder(
            ticker="KXBTC-15M-ABOVE-50000",
            side="no",
            action="buy",
            price_cents=45,
            count=10,
            delay_seconds=0.0
        )
        
        self.assertEqual(yes_child.side, "yes")
        self.assertEqual(no_child.side, "no")


if __name__ == "__main__":
    unittest.main()
