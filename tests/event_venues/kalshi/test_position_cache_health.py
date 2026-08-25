"""
Position Cache Health Guard Tests

Tests the is_healthy() method for position cache health checking.
This ensures the cache is only used for trading when it's fresh and synced.
Also tests expired ticker filtering and cache cleanup functionality.
"""

import pytest
import asyncio
import time
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from merid.event_venues.kalshi.position_cache import KalshiPositionCache, _is_expired_ticker


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear cache before each test to prevent state leakage."""
    cache = KalshiPositionCache()
    # Some legacy tests replace _ensure_mutex with a mock; restore the real lock.
    if not isinstance(cache._ensure_mutex, types.MethodType):
        try:
            del cache._ensure_mutex
        except AttributeError:
            pass
    await cache.clear()
    cache._last_sync = None  # Reset sync timestamp for clean state
    yield
    # Re-check in case a test replaced it during the test body.
    if not isinstance(cache._ensure_mutex, types.MethodType):
        try:
            del cache._ensure_mutex
        except AttributeError:
            pass
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
        
        # After sync with actual position data, log health again
        positions_list = [
            {
                "ticker": "KXBTC15M-TEST",
                "side": "yes",
                "contracts": 1,
                "avg_price_cents": 50
            }
        ]
        await cache.sync_from_rest(positions_list, rest_timestamp=time.time())
        cache.log_health()
        
        # Should be healthy after sync with actual data
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
        """Ticker within 15-minute settlement buffer should not be expired."""
        # Create a ticker for 10 minutes ago (within 15-minute buffer)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        assert not _is_expired_ticker(ticker)

    def test_is_expired_ticker_exactly_buffer_boundary(self):
        """Ticker beyond the 15-minute settlement buffer should be expired."""
        # Create a ticker for 20 minutes ago (past the 15-minute buffer)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=20)
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
        """Ticker for window that just opened should not be expired."""
        # Create a ticker 10 minutes ago (within the 15-minute settlement buffer)
        window_start = datetime.now(timezone.utc) - timedelta(minutes=10)
        ticker = f"KXBTC15M-{window_start.strftime('%d%b%H%M%S')}-50"
        assert not _is_expired_ticker(ticker)


class TestClearExpiredPositions:
    """Test clear_expired_positions method for cache cleanup."""

    @pytest.mark.asyncio
    async def test_clear_expired_positions_removes_settled(self):
        """Positions only removed once explicitly settled or zero."""
        cache = KalshiPositionCache()

        # Add a closed-but-unsettled position and a settled position.
        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        closed_ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"
        past_time2 = datetime.now(timezone.utc) - timedelta(minutes=35)
        settled_ticker = f"KXETH15M-{past_time2.strftime('%d%b%H%M%S')}-50"

        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        valid_ticker = f"KXSOL15M-{future_time.strftime('%d%b%H%M%S')}-50"

        cache._positions[closed_ticker] = type('CachedPosition', (), {
            'contracts': 10,
            'quantity_cc': 1000,
            'avg_price_cents': 5000,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'open',
        })()

        cache._positions[settled_ticker] = type('CachedPosition', (), {
            'contracts': 5,
            'quantity_cc': 500,
            'avg_price_cents': 6000,
            'side': 'no',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'settled',
        })()

        cache._positions[valid_ticker] = type('CachedPosition', (), {
            'contracts': 2,
            'quantity_cc': 200,
            'avg_price_cents': 5500,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'open',
        })()

        # Clear expired positions
        removed = await cache.clear_expired_positions()

        # Only the explicitly settled position should be removed.
        assert removed == 1
        assert settled_ticker not in cache._positions
        assert closed_ticker in cache._positions
        assert closed_ticker in [t for t, p in cache._positions.items() if p.settlement_status == 'pending']
        assert valid_ticker in cache._positions

    @pytest.mark.asyncio
    async def test_clear_expired_positions_no_expired(self):
        """If no positions are expired/closed, should return 0 and not modify cache."""
        cache = KalshiPositionCache()

        # Add only valid positions
        future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
        valid_ticker = f"KXETH15M-{future_time.strftime('%d%b%H%M%S')}-50"

        cache._positions[valid_ticker] = type('CachedPosition', (), {
            'contracts': 5,
            'quantity_cc': 500,
            'avg_price_cents': 6000,
            'side': 'no',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'open',
        })()

        # Clear expired positions
        removed = await cache.clear_expired_positions()

        # Should have removed 0 positions
        assert removed == 0
        assert valid_ticker in cache._positions

    @pytest.mark.asyncio
    async def test_clear_expired_positions_removes_zero_positions(self):
        """Authoritative zero positions are removed even before settlement."""
        cache = KalshiPositionCache()

        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        zero_ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"

        cache._positions[zero_ticker] = type('CachedPosition', (), {
            'contracts': 0,
            'quantity_cc': 0,
            'avg_price_cents': 5000,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'open',
        })()

        removed = await cache.clear_expired_positions()

        assert removed == 1
        assert zero_ticker not in cache._positions

    @pytest.mark.asyncio
    async def test_clear_expired_positions_mark_settled_removes(self):
        """mark_settled removes the cached position."""
        cache = KalshiPositionCache()

        past_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        settled_ticker = f"KXBTC15M-{past_time.strftime('%d%b%H%M%S')}-50"

        cache._positions[settled_ticker] = type('CachedPosition', (), {
            'contracts': 1,
            'quantity_cc': 100,
            'avg_price_cents': 5000,
            'side': 'yes',
            'realized_pnl_usd': 0,
            'notional_usd': 0,
            'unrealized_pnl_usd': 0,
            'settlement_status': 'open',
        })()

        # mark_settled does not need a monitor patch; it removes from _positions.
        await cache.mark_settled(settled_ticker)

        assert settled_ticker not in cache._positions
        assert cache.is_settled(settled_ticker)

    @pytest.mark.asyncio
    async def test_clear_expired_positions_empty_cache(self):
        """Clearing expired positions on empty cache should return 0."""
        cache = KalshiPositionCache()

        # Clear expired positions
        removed = await cache.clear_expired_positions()

        # Should have removed 0 positions
        assert removed == 0
        assert len(cache._positions) == 0


class TestRestPriceNormalization:
    """Test that sync_from_rest keeps REST-reported avg price in the position's
    own outcome space and derives the side from the canonical outcome_id / side
    or the signed position_fp (2026-08-13 side/price fix)."""

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_no_position_from_position_fp(self, _mock_expired):
        """A raw MarketPosition with negative position_fp and positive market_exposure
        becomes a NO position with the NO price unchanged."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                # No outcome_id/side: side must be inferred from signed position_fp.
                "position_fp": -1.0,
                # market_exposure_dollars is the cost paid for the NO position.
                "market_exposure_dollars": 0.47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is not None, "Position should be in cache"
        assert pos.thesis_side == "no", f"Expected NO thesis, got {pos.thesis_side}"
        assert pos.avg_price_cents == 47, f"NO position avg price should be 47, got {pos.avg_price_cents}"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_no_position_keeps_avg_price(self, _mock_expired):
        """A canonical long NO position with avg_price_cents=47 stays entry=47."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                "side": "no",
                "avg_price_cents": 47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is not None, "Position should be in cache"
        assert pos.thesis_side == "no", f"Expected NO thesis, got {pos.thesis_side}"
        assert pos.avg_price_cents == 47, f"NO position avg price should be 47, got {pos.avg_price_cents}"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_yes_position_uses_avg_price(self, _mock_expired):
        """A long YES position with REST avg_price_cents=47 stays entry=47."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                "side": "yes",
                "avg_price_cents": 47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is not None, "Position should be in cache"
        assert pos.thesis_side == "yes", f"Expected YES thesis, got {pos.thesis_side}"
        assert pos.avg_price_cents == 47, f"YES position avg price should be 47, got {pos.avg_price_cents}"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_no_position_outcome_id(self, _mock_expired):
        """A canonical NO position with outcome_id has its own-side price preserved."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                "outcome_id": "no",
                "avg_price_cents": 47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is not None, "Position should be in cache"
        assert pos.thesis_side == "no", f"Expected NO thesis, got {pos.thesis_side}"
        assert pos.avg_price_cents == 47, f"NO position avg price should be 47, got {pos.avg_price_cents}"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_yes_position_outcome_id(self, _mock_expired):
        """A long YES position with outcome_id="yes" is preserved."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                "outcome_id": "YES",
                "avg_price_cents": 47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is not None, "Position should be in cache"
        assert pos.thesis_side == "yes", f"Expected YES thesis, got {pos.thesis_side}"
        assert pos.avg_price_cents == 47, f"YES position avg price should be 47, got {pos.avg_price_cents}"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.position_cache._is_expired_ticker", return_value=False)
    async def test_rest_sync_outcome_id_outcome_side_conflict_is_quarantined(self, _mock_expired):
        """Conflicting outcome_id and outcome_side must not create a position."""
        cache = KalshiPositionCache()

        rest_positions = [
            {
                "market_id": "KXBTC15M-26AUG121500-00",
                "contracts": 1,
                "outcome_id": "no",
                "outcome_side": "yes",
                "avg_price_cents": 47,
                "realized_pnl": 0,
                "unrealized_pnl": 0,
            }
        ]

        await cache.sync_from_rest(rest_positions, rest_timestamp=time.time(), force=True)

        pos = cache._positions.get("KXBTC15M-26AUG121500-00")
        assert pos is None, "Conflicting side fields must not produce a cached position"
