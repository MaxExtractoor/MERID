"""
Tests for position cache health monitoring and REST reconciliation.

This test suite validates the 2026 best practice implementation of
position cache health monitoring and periodic REST synchronization.

Run with: pytest tests/test_position_cache_health.py -v
"""

import pytest
import time
from datetime import datetime, timezone
from merid.event_venues.kalshi.position_cache import get_position_cache, KalshiPositionCache


class TestPositionCacheHealth:
    """Test suite for position cache health monitoring."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        # Clear any existing positions for clean test
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    def test_get_cache_health_no_sync(self, position_cache):
        """Test cache health when no sync has occurred."""
        health = position_cache.get_cache_health()
        
        assert health["last_sync_timestamp"] is None
        assert health["staleness_seconds"] == 0.0
        assert health["is_stale"] is False
        assert health["total_positions"] == 0
        assert health["open_positions"] == 0
        assert health["closed_positions"] == 0
    
    def test_get_cache_health_fresh_sync(self, position_cache):
        """Test cache health with fresh sync."""
        position_cache._last_sync = datetime.now(timezone.utc)
        
        health = position_cache.get_cache_health()
        
        assert health["last_sync_timestamp"] is not None
        assert health["staleness_seconds"] < 10.0  # Should be very fresh
        assert health["is_stale"] is False
    
    def test_get_cache_health_stale_sync(self, position_cache):
        """Test cache health with stale sync (> 5 minutes)."""
        # Set sync time to 6 minutes ago
        position_cache._last_sync = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        position_cache._last_sync = position_cache._last_sync.replace(
            minute=position_cache._last_sync.minute - 6
        )
        
        health = position_cache.get_cache_health()
        
        assert health["staleness_seconds"] > 300.0  # > 5 minutes
        assert health["is_stale"] is True
    
    def test_get_cache_health_with_positions(self, position_cache):
        """Test cache health with open and closed positions."""
        # Add mock positions
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from decimal import Decimal
        
        # Open position
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            contracts=10,
            side="yes",
            avg_price_cents=50,
            unrealized_pnl_usd=Decimal("0.50")
        )
        
        # Closed position
        position_cache._positions["KXETH15M-26JUL012015-45"] = CachedPosition(
            market_id="KXETH15M-26JUL012015-45",
            contracts=0,  # Closed
            side="no",
            avg_price_cents=30,
            unrealized_pnl_usd=Decimal("0.00")
        )
        
        position_cache._last_sync = datetime.now(timezone.utc)
        
        health = position_cache.get_cache_health()
        
        assert health["total_positions"] == 2
        assert health["open_positions"] == 1
        assert health["closed_positions"] == 1
    
    def test_get_all_positions_without_validation(self, position_cache):
        """Test get_all_positions with validate_freshness=False."""
        # Set stale sync
        position_cache._last_sync = datetime.now(timezone.utc).replace(
            minute=datetime.now(timezone.utc).minute - 10
        )
        
        # Should not log warning when validate_freshness=False
        positions = position_cache.get_all_positions(validate_freshness=False)
        assert isinstance(positions, dict)
    
    def test_get_all_positions_with_validation(self, position_cache):
        """Test get_all_positions with validate_freshness=True."""
        # Set stale sync
        position_cache._last_sync = datetime.now(timezone.utc).replace(
            minute=datetime.now(timezone.utc).minute - 10
        )
        
        # Should log warning when validate_freshness=True (but still return positions)
        positions = position_cache.get_all_positions(validate_freshness=True)
        assert isinstance(positions, dict)


class TestPositionCacheReconciliation:
    """Test suite for position cache REST reconciliation."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        # Clear any existing positions for clean test
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_basic(self, position_cache):
        """Test basic sync_from_rest functionality."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        assert len(position_cache._positions) == 1
        assert "KXBTC15M-26JUL012015-30" in position_cache._positions
        assert position_cache._positions["KXBTC15M-26JUL012015-30"].contracts == 10
        assert position_cache._last_sync is not None
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_filters_test_positions(self, position_cache):
        """Test that sync_from_rest filters out test positions."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-TEST-30",  # Test ticker
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            },
            {
                "market_id": "KXBTC15M-26JUL012015-30",  # Real ticker
                "contracts": 5,
                "side": "no",
                "avg_price_cents": 30,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.2
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        # Should only have the real position
        assert len(position_cache._positions) == 1
        assert "KXBTC15M-26JUL012015-30" in position_cache._positions
        assert "KXBTC15M-TEST-30" not in position_cache._positions
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_filters_closed_positions(self, position_cache):
        """Test that sync_from_rest filters out closed positions (contracts=0)."""
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 0,  # Closed position
                "side": "yes",
                "avg_price_cents": 50,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0
            },
            {
                "market_id": "KXETH15M-26JUL012015-45",
                "contracts": 5,  # Open position
                "side": "no",
                "avg_price_cents": 30,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.2
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions)
        
        # Should only have the open position
        assert len(position_cache._positions) == 1
        assert "KXETH15M-26JUL012015-45" in position_cache._positions
        assert "KXBTC15M-26JUL012015-30" not in position_cache._positions
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_staleness_guard(self, position_cache):
        """Test that sync_from_rest rejects stale REST snapshots."""
        # Set recent sync
        position_cache._last_sync = datetime.now(timezone.utc)
        
        # Try to sync with older timestamp (should be rejected)
        old_timestamp = time.time() - 60.0  # 60 seconds ago
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions, rest_timestamp=old_timestamp)
        
        # Should not have updated (stale guard)
        assert len(position_cache._positions) == 0
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_with_timestamp(self, position_cache):
        """Test sync_from_rest with explicit timestamp."""
        current_timestamp = time.time()
        rest_positions = [
            {
                "market_id": "KXBTC15M-26JUL012015-30",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]
        
        await position_cache.sync_from_rest(rest_positions, rest_timestamp=current_timestamp)
        
        assert position_cache._last_sync is not None
        # Check that sync time is close to provided timestamp
        sync_diff = abs(position_cache._last_sync.timestamp() - current_timestamp)
        assert sync_diff < 1.0  # Within 1 second
