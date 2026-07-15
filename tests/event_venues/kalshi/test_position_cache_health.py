"""
Position Cache Health Guard Tests

Tests the is_healthy() method for position cache health checking.
This ensures the cache is only used for trading when it's fresh and synced.
Also tests expired ticker filtering and cache cleanup functionality.
"""

import pytest
import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from merid.event_venues.kalshi.position_cache import KalshiPositionCache, _is_expired_ticker


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear cache before each test to prevent state leakage."""
    cache = KalshiPositionCache()
    await cache.clear()
    cache._last_sync = None  # Reset sync timestamp for clean state
    yield
    await cache.clear()
    cache._last_sync = None  # Reset sync timestamp for clean state


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
        
        # Simulate a sync just under the threshold (59 seconds)
        cache._last_sync = datetime.now(timezone.utc) - timedelta(seconds=59)
        
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


class TestExpiredTickerFiltering:
    """Test _is_expired_ticker function for filtering expired markets."""

    def test_is_expired_ticker_valid_future(self):
        """Ticker in the future should not be expired."""
        # Create a ticker for 30 minutes in the future
        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        ticker = f"KXBTC15M-{future_time.strftime('%d%b%H%M%S')}-50"
        assert not _is_expired_ticker(ticker)

    def test_is_expired_ticker_expired_past(self):
        """Ticker in the past should be expired."""
        # Create a ticker for 30 minutes ago
        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        assert _is_expired_ticker(ticker)

    def test_is_expired_ticker_buffer_window(self):
        """Ticker within 15-minute buffer should not be expired."""
        # Create a ticker for 10 minutes ago (within buffer)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        assert not _is_expired_ticker(ticker)

    def test_is_expired_ticker_exactly_buffer_boundary(self):
        """Ticker exactly at 15-minute buffer boundary should be expired."""
        # Create a ticker for exactly 15 minutes ago
        past_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        assert _is_expired_ticker(ticker)

    def test_is_expired_ticker_invalid_format(self):
        """Invalid ticker format should return False (don't filter out)."""
        assert not _is_expired_ticker("INVALID_TICKER")
        assert not _is_expired_ticker("")
        assert not _is_expired_ticker(None)

    def test_is_expired_ticker_invalid_date(self):
        """Invalid date (e.g., Feb 30) should be treated as expired."""
        ticker = "KXBTC15M-30FEB12300000-50"  # February 30 doesn't exist
        assert _is_expired_ticker(ticker)

    def test_is_expired_ticker_current_window(self):
        """Ticker for current 15-minute window should not be expired."""
        now = datetime.now(timezone.utc)
        # Floor to 15-minute boundary
        window_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        ticker = f"KXBTC15M-{window_start.strftime('%d%b%H%M%S')}-50"
        assert not _is_expired_ticker(ticker)


class TestClearExpiredPositions:
    """Test clear_expired_positions method for cache cleanup."""

    @pytest.mark.asyncio
    async def test_clear_expired_positions_removes_expired(self):
        """Expired positions should be removed from cache."""
        cache = KalshiPositionCache()
        
        # Add some positions
        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        expired_ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        
        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        valid_ticker = f"KXETH15M-{future_time.strftime('%d%b%H%M%S')}-50"
        
        cache._positions[expired_ticker] = type('CachedPosition', (), {
            'contracts': 10,
            'avg_price_cents': 5000,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0
        })()
        
        cache._positions[valid_ticker] = type('CachedPosition', (), {
            'contracts': 5,
            'avg_price_cents': 6000,
            'side': 'no',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0
        })()
        
        # Clear expired positions
        removed = await cache.clear_expired_positions()
        
        # Should have removed 1 expired position
        assert removed == 1
        assert expired_ticker not in cache._positions
        assert valid_ticker in cache._positions

    @pytest.mark.asyncio
    async def test_clear_expired_positions_no_expired(self):
        """If no expired positions, should return 0 and not modify cache."""
        cache = KalshiPositionCache()
        
        # Add only valid positions
        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        valid_ticker = f"KXETH15M-{future_time.strftime('%d%b%H%M%S')}-50"
        
        cache._positions[valid_ticker] = type('CachedPosition', (), {
            'contracts': 5,
            'avg_price_cents': 6000,
            'side': 'no',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0
        })()
        
        # Clear expired positions
        removed = await cache.clear_expired_positions()
        
        # Should have removed 0 positions
        assert removed == 0
        assert valid_ticker in cache._positions

    @pytest.mark.asyncio
    async def test_clear_expired_positions_all_expired(self):
        """If all positions are expired, cache should be empty."""
        cache = KalshiPositionCache()
        
        # Add only expired positions
        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        expired_ticker1 = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        expired_ticker2 = f"KXETH15M-{past_time.strftime('%d%b%H%M%S')}-50"
        
        cache._positions[expired_ticker1] = type('CachedPosition', (), {
            'contracts': 10,
            'avg_price_cents': 5000,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0
        })()
        
        cache._positions[expired_ticker2] = type('CachedPosition', (), {
            'contracts': 5,
            'avg_price_cents': 6000,
            'side': 'no',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0
        })()
        
        # Clear expired positions
        removed = await cache.clear_expired_positions()
        
        # Should have removed 2 positions
        assert removed == 2
        assert len(cache._positions) == 0

    @pytest.mark.asyncio
    async def test_clear_expired_positions_empty_cache(self):
        """Clearing expired positions on empty cache should return 0."""
        cache = KalshiPositionCache()
        
        # Clear expired positions
        removed = await cache.clear_expired_positions()
        
        # Should have removed 0 positions
        assert removed == 0
        assert len(cache._positions) == 0
