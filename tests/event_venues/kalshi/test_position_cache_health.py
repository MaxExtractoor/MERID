"""
Position Cache Health Guard Tests

Tests the is_healthy() method for position cache health checking.
This ensures the cache is only used for trading when it's fresh and synced.
"""

import pytest
import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from merid.event_venues.kalshi.position_cache import KalshiPositionCache


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear cache before each test to prevent state leakage."""
    cache = KalshiPositionCache()
    await cache.clear()
    yield
    await cache.clear()


class TestPositionCacheHealth:
    """Test position cache health guard functionality."""

    @pytest.mark.asyncio
    async def test_is_healthy_never_synced(self):
        """Cache that has never synced should be unhealthy."""
        cache = KalshiPositionCache()
        
        # Cache has never been synced
        assert cache._last_sync is None
        
        # Should be unhealthy
        assert not cache.is_healthy(max_staleness_seconds=60.0)

    @pytest.mark.asyncio
    async def test_is_healthy_fresh_sync(self):
        """Cache with recent sync should be healthy."""
        cache = KalshiPositionCache()
        
        # Simulate a recent sync
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=10)
        
        # Should be healthy
        assert cache.is_healthy(max_staleness_seconds=60.0)

    @pytest.mark.asyncio
    async def test_is_healthy_stale_sync(self):
        """Cache with stale sync should be unhealthy."""
        cache = KalshiPositionCache()
        
        # Simulate a stale sync (older than threshold)
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=120)
        
        # Should be unhealthy with 60s threshold
        assert not cache.is_healthy(max_staleness_seconds=60.0)

    @pytest.mark.asyncio
    async def test_is_healthy_custom_threshold(self):
        """Cache health check respects custom staleness threshold."""
        cache = KalshiPositionCache()
        
        # Simulate a sync 30 seconds ago
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=30)
        
        # Should be healthy with 60s threshold
        assert cache.is_healthy(max_staleness_seconds=60.0)
        
        # Should be unhealthy with 20s threshold
        assert not cache.is_healthy(max_staleness_seconds=20.0)

    @pytest.mark.asyncio
    async def test_is_healthy_boundary_condition(self):
        """Cache health check at exact boundary."""
        cache = KalshiPositionCache()
        
        # Simulate a sync exactly at the threshold
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=60)
        
        # Should be healthy (not greater than threshold)
        assert cache.is_healthy(max_staleness_seconds=60.0)
        
        # One second over threshold should be unhealthy
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=61)
        assert not cache.is_healthy(max_staleness_seconds=60.0)

    @pytest.mark.asyncio
    async def test_is_healthy_after_sync_from_rest(self):
        """Cache becomes healthy after successful sync_from_rest."""
        cache = KalshiPositionCache()
        
        # Initially unhealthy (never synced)
        assert not cache.is_healthy(max_staleness_seconds=60.0)
        
        # Simulate sync_from_rest
        positions_list = [
            {
                "market_id": "KXBTC15M-24APR15-10000",
                "contracts": 5,
                "avg_price_cents": 5000,
                "side": "yes"
            }
        ]
        await cache.sync_from_rest(positions_list, rest_timestamp=time.time())
        
        # Should now be healthy
        assert cache.is_healthy(max_staleness_seconds=60.0)

    @pytest.mark.asyncio
    async def test_log_health_integration(self):
        """log_health() method works correctly with is_healthy()."""
        cache = KalshiPositionCache()
        
        # Log health when never synced
        cache.log_health()
        
        # After sync, log health again
        positions_list = []
        await cache.sync_from_rest(positions_list, rest_timestamp=time.time())
        cache.log_health()
        
        # Should be healthy after sync
        assert cache.is_healthy(max_staleness_seconds=60.0)
