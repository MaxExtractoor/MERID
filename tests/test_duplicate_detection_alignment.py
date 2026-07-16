"""Test duplicate detection alignment (2026-07-16).

This test verifies that duplicate detection TTL windows are aligned across
order_router.py and order_deduplication.py to match the 5s cadence.
"""

import pytest
import time
from datetime import datetime, timezone, timedelta


class TestDuplicateDetectionAlignment:
    """Test that duplicate detection TTL windows are aligned."""

    def test_order_router_duplicate_window_is_5s(self):
        """Verify order_router.py uses 5s duplicate window."""
        from merid.event_venues.kalshi.order_router import _DUPLICATE_ORDER_WINDOW_SECONDS
        
        assert _DUPLICATE_ORDER_WINDOW_SECONDS == 5, (
            f"Order router duplicate window should be 5s, got {_DUPLICATE_ORDER_WINDOW_SECONDS}s"
        )

    def test_order_deduplication_ttl_is_5s(self):
        """Verify order_deduplication.py uses 5s TTL."""
        from merid.event_venues.kalshi.order_deduplication import _TTL_SECONDS
        
        assert _TTL_SECONDS == 5, (
            f"Order deduplication TTL should be 5s, got {_TTL_SECONDS}s"
        )

    def test_duplicate_windows_aligned(self):
        """Verify both systems use the same TTL."""
        from merid.event_venues.kalshi.order_router import _DUPLICATE_ORDER_WINDOW_SECONDS
        from merid.event_venues.kalshi.order_deduplication import _TTL_SECONDS
        
        assert _DUPLICATE_ORDER_WINDOW_SECONDS == _TTL_SECONDS, (
            f"Duplicate windows must be aligned: "
            f"order_router={_DUPLICATE_ORDER_WINDOW_SECONDS}s, "
            f"order_deduplication={_TTL_SECONDS}s"
        )

    def test_order_deduplication_cache_functionality(self):
        """Verify OrderDeduplicationCache works correctly with 5s TTL."""
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        cache = OrderDeduplicationCache()
        
        # Create an order intent
        intent_params = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "outcome": "yes",
            "price_cents": 50,
            "count": 1,
        }
        
        # First call should create new client_order_id (returns tuple)
        client_order_id_1, is_dup_1 = cache.get_or_create(**intent_params)
        assert client_order_id_1 is not None
        assert is_dup_1 is False  # First call should not be duplicate
        
        # Mark as submitted to exchange
        cache.mark_submitted(client_order_id_1)
        
        # Immediate second call should return same client_order_id (within TTL)
        client_order_id_2, is_dup_2 = cache.get_or_create(**intent_params)
        assert client_order_id_1 == client_order_id_2
        assert is_dup_2 is True  # Should be duplicate since submitted
        
        # Wait for TTL to expire (5s + small buffer)
        time.sleep(6)
        
        # After TTL, should create new client_order_id (old entry pruned)
        client_order_id_3, is_dup_3 = cache.get_or_create(**intent_params)
        # Should be a new ID since old entry expired
        assert is_dup_3 is False

    def test_order_deduplication_tracks_submission(self):
        """Verify OrderDeduplicationCache tracks whether order was submitted."""
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        cache = OrderDeduplicationCache()
        
        intent_params = {
            "ticker": "KXETH15M-TEST",
            "side": "yes",
            "outcome": "yes",
            "price_cents": 50,
            "count": 1,
        }
        
        client_order_id, _ = cache.get_or_create(**intent_params)
        
        # Mark as submitted
        cache.mark_submitted(client_order_id)
        
        # Verify it's marked as submitted by checking duplicate detection
        client_order_id_2, is_dup = cache.get_or_create(**intent_params)
        assert is_dup is True  # Should be duplicate since submitted
        assert client_order_id == client_order_id_2

    def test_order_deduplication_cleanup_expired(self):
        """Verify OrderDeduplicationCache cleans up expired entries automatically."""
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        cache = OrderDeduplicationCache()
        
        # Create an order
        intent_params = {
            "ticker": "KXSOL15M-TEST",
            "side": "yes",
            "outcome": "yes",
            "price_cents": 50,
            "count": 1,
        }
        
        client_order_id, _ = cache.get_or_create(**intent_params)
        
        # Wait for TTL to expire
        time.sleep(6)
        
        # get_or_create automatically calls _prune_expired
        # After TTL, should create new order since old one was pruned
        client_order_id_2, is_dup = cache.get_or_create(**intent_params)
        assert is_dup is False  # Should not be duplicate after TTL

    def test_duplicate_detection_prevents_false_positives(self):
        """Verify duplicate detection doesn't cause false positives for unsubmitted orders."""
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        cache = OrderDeduplicationCache()
        
        intent_params = {
            "ticker": "KXXRP15M-TEST",
            "side": "yes",
            "outcome": "yes",
            "price_cents": 50,
            "count": 1,
        }
        
        # First order (not marked as submitted)
        client_order_id_1, is_dup_1 = cache.get_or_create(**intent_params)
        assert is_dup_1 is False
        
        # Second call without marking as submitted should NOT be duplicate
        # (because it was never submitted to exchange)
        client_order_id_2, is_dup_2 = cache.get_or_create(**intent_params)
        assert is_dup_2 is False  # Should not be duplicate since not submitted
        
        # Now mark as submitted
        cache.mark_submitted(client_order_id_2)
        
        # Third call should now be duplicate
        client_order_id_3, is_dup_3 = cache.get_or_create(**intent_params)
        assert is_dup_3 is True  # Should be duplicate since submitted

    def test_order_router_duplicate_check_deprecated(self):
        """Verify _check_duplicate_order in order_router.py is deprecated."""
        from merid.event_venues.kalshi.order_router import _check_duplicate_order, OrderIntent
        import warnings
        
        # Create a test intent
        intent = OrderIntent(
            ticker="KXDOGE15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _check_duplicate_order(intent)
            
            # Should have issued a DeprecationWarning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "OrderDeduplicationCache" in str(w[0].message)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
