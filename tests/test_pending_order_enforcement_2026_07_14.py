"""Test for pending order enforcement fix (2026-07-14).

Tests that the GlobalAllocator has_pending_order() method correctly
prevents duplicate submissions for the same asset, which would otherwise
bypass the MAX_POSITIONS_PER_ASSET=1 limit enforced at fill time.

This fix addresses the race condition where multiple orders for the same asset
could pass pre-submission checks and fill before the per-asset limit was enforced.
"""

import pytest
import time
from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate, create_global_allocator_from_envelope


class TestHasPendingOrder:
    """Test the has_pending_order() method."""
    
    def test_has_pending_order_returns_false_when_no_pending(self):
        """Test that has_pending_order returns False when no pending order exists."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        assert allocator.has_pending_order("BTC") is False
        assert allocator.has_pending_order("ETH") is False
        print("✓ has_pending_order returns False when no pending order")
    
    def test_has_pending_order_returns_true_when_pending(self):
        """Test that has_pending_order returns True when pending order exists."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record a pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        
        assert allocator.has_pending_order("BTC") is True
        assert allocator.has_pending_order("ETH") is False
        print("✓ has_pending_order returns True when pending order exists")
    
    def test_has_pending_order_clears_stale_orders(self):
        """Test that has_pending_order clears stale pending orders."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record a pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        
        # Manually set timestamp to make it stale (timeout is 60s)
        allocator._pending_order_timestamps["BTC"] = time.time() - 70
        
        # has_pending_order should clear the stale order and return False
        assert allocator.has_pending_order("BTC") is False
        assert "BTC" not in allocator._pending_orders
        print("✓ has_pending_order clears stale pending orders")
    
    def test_has_pending_order_non_stale_within_timeout(self):
        """Test that has_pending_order returns True for non-stale orders within timeout."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record a pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        
        # Set timestamp to 15 seconds ago (within 30s timeout)
        allocator._pending_order_timestamps["BTC"] = time.time() - 15
        
        # has_pending_order should return True
        assert allocator.has_pending_order("BTC") is True
        print("✓ has_pending_order returns True for non-stale orders within timeout")


class TestPendingOrderLifecycle:
    """Test the complete pending order lifecycle."""
    
    def test_pending_order_cleared_on_fill(self):
        """Test that pending orders are cleared when order fills."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        assert allocator.has_pending_order("BTC") is True
        
        # Record fill
        allocator.record_order_filled("BTC", "order_123", 0.50)
        
        # Pending order should be cleared
        assert allocator.has_pending_order("BTC") is False
        assert allocator.get_asset_positions().get("BTC") == 0.50
        print("✓ Pending order cleared on fill")
    
    def test_pending_order_cleared_on_reject(self):
        """Test that pending orders are cleared when order is rejected."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        assert allocator.has_pending_order("BTC") is True
        
        # Record rejection
        allocator.record_order_rejected("BTC", "order_123")
        
        # Pending order should be cleared
        assert allocator.has_pending_order("BTC") is False
        print("✓ Pending order cleared on reject")
    
    def test_pending_order_prevents_duplicate_submissions(self):
        """Test that pending orders prevent duplicate submissions in allocation."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Create candidates
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-1",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=3.0,
                confidence=0.6,
                model_prob=0.55,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-2",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=2.5,
                confidence=0.55,
                model_prob=0.50,
                agent_name="BTC_15M"
            )
        ]
        
        # Record pending order for BTC
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        
        # Run allocation - should filter out BTC due to pending order
        current_positions = {}
        chosen = allocator.allocate(candidates, current_positions)
        
        # No orders should be chosen (both are for BTC which has pending order)
        assert len(chosen) == 0
        print("✓ Pending order prevents duplicate submissions in allocation")


class TestMultiAssetPendingOrders:
    """Test pending order tracking across multiple assets."""
    
    def test_pending_orders_per_asset(self):
        """Test that pending orders are tracked per asset."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record pending orders for different assets
        allocator.record_order_submitted("BTC", "order_btc", 0.50)
        allocator.record_order_submitted("ETH", "order_eth", 0.30)
        
        assert allocator.has_pending_order("BTC") is True
        assert allocator.has_pending_order("ETH") is True
        assert allocator.has_pending_order("SOL") is False
        
        # Clear BTC pending order
        allocator.record_order_filled("BTC", "order_btc", 0.50)
        
        assert allocator.has_pending_order("BTC") is False
        assert allocator.has_pending_order("ETH") is True
        print("✓ Pending orders tracked per asset")
    
    def test_pending_order_allows_different_assets(self):
        """Test that pending orders for one asset don't block other assets."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Create candidates for different assets
        candidates = [
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-1",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=3.0,
                confidence=0.6,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL",
                ticker="KXSOL15M-1",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=2.5,
                confidence=0.55,
                model_prob=0.50,
                agent_name="SOL_15M"
            )
        ]
        
        # Record pending order for BTC only
        allocator.record_order_submitted("BTC", "order_btc", 0.50)
        
        # Run allocation - ETH and SOL should still be allowed
        current_positions = {}
        chosen = allocator.allocate(candidates, current_positions)
        
        # Both ETH and SOL should be chosen (BTC not in candidates)
        assert len(chosen) == 2
        print("✓ Pending order for one asset doesn't block other assets")


class TestPendingOrderIntegration:
    """Integration tests for pending order enforcement."""
    
    def test_pending_order_timeout_prevents_hang(self):
        """Test that pending order timeout prevents indefinite blocking."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        # Record pending order
        allocator.record_order_submitted("BTC", "order_123", 0.50)
        
        # Manually expire the pending order
        allocator._pending_order_timestamps["BTC"] = time.time() - 70
        
        # has_pending_order should clear and return False
        assert allocator.has_pending_order("BTC") is False
        
        # New order should be allowed
        allocator.record_order_submitted("BTC", "order_456", 0.50)
        assert allocator.has_pending_order("BTC") is True
        print("✓ Pending order timeout prevents indefinite blocking")
    
    def test_concurrent_pending_order_checks(self):
        """Test that concurrent has_pending_order checks are thread-safe."""
        import threading
        
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        results = []
        
        def check_pending():
            for _ in range(100):
                results.append(allocator.has_pending_order("BTC"))
        
        # Start multiple threads checking pending orders
        threads = [threading.Thread(target=check_pending) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should return False (no pending order)
        assert all(r is False for r in results)
        print("✓ Concurrent pending order checks are thread-safe")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
