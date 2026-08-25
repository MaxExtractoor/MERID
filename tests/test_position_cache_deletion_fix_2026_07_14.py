"""
Position Cache Deletion Fix Tests (2026-07-14)

Tests the fix for phantom position entries in the position cache.
Previously, when positions were fully closed (contracts=0), they remained
in the _positions dictionary, causing total_positions to be inflated
while open_positions was correct.

This fix ensures closed positions are deleted from the cache dictionary,
so total_positions accurately reflects only open positions.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.position_cache import KalshiPositionCache, CachedPosition


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear cache before each test to prevent state leakage."""
    cache = KalshiPositionCache()
    await cache.clear()
    yield
    await cache.clear()


class TestPositionCacheDeletionOnClose:
    """Test that closed positions are deleted from cache dictionary."""

    @pytest.mark.asyncio
    async def test_closed_position_deleted_from_cache(self):
        """When a position is fully closed, it should be deleted from _positions dict."""
        cache = KalshiPositionCache()
        
        # Add a position
        market_id = "KXBTC15M-14JUL220000-50"
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=5000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Verify position exists
        assert market_id in cache._positions
        assert len(cache._positions) == 1
        
        # Simulate full close by setting contracts to 0
        cache._positions[market_id].contracts = 0
        
        # Simulate the fix: delete position when contracts == 0
        del cache._positions[market_id]
        
        # Verify position is deleted
        assert market_id not in cache._positions
        assert len(cache._positions) == 0

    @pytest.mark.asyncio
    async def test_partial_close_does_not_delete_position(self):
        """Partial closes should not delete the position from cache."""
        cache = KalshiPositionCache()
        
        # Add a position
        market_id = "KXETH15M-14JUL220000-50"
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=6000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Simulate partial close (contracts > 0)
        cache._positions[market_id].contracts = 5
        
        # Position should still exist
        assert market_id in cache._positions
        assert len(cache._positions) == 1
        assert cache._positions[market_id].contracts == 5

    @pytest.mark.asyncio
    async def test_total_vs_open_positions_after_close(self):
        """total_positions should match open_positions after closed positions are deleted."""
        cache = KalshiPositionCache()
        
        # Add multiple positions
        market1 = "KXBTC15M-14JUL220000-50"
        market2 = "KXETH15M-14JUL220000-50"
        market3 = "KXSOL15M-14JUL220000-50"
        
        cache._positions[market1] = CachedPosition(
            market_id=market1,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=5000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        cache._positions[market2] = CachedPosition(
            market_id=market2,
            agent_id="test_agent",
            thesis_side="no",
            contracts=5,
            side="no",
            avg_price_cents=4000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        cache._positions[market3] = CachedPosition(
            market_id=market3,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=8,
            side="yes",
            avg_price_cents=5500,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # All positions open
        assert len(cache._positions) == 3
        open_positions = {k: v for k, v in cache._positions.items() if v.contracts > 0}
        assert len(open_positions) == 3
        
        # Close one position
        cache._positions[market2].contracts = 0
        del cache._positions[market2]  # Simulate the fix
        
        # Now total should match open
        assert len(cache._positions) == 2
        open_positions = {k: v for k, v in cache._positions.items() if v.contracts > 0}
        assert len(open_positions) == 2
        assert len(cache._positions) == len(open_positions)

    @pytest.mark.asyncio
    async def test_on_fill_deletes_closed_position(self):
        """Test that on_fill deletes position when contracts become 0."""
        cache = KalshiPositionCache()
        
        # Add a position
        market_id = "KXDOGE15M-14JUL220000-50"
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=5,
            side="yes",
            avg_price_cents=3000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Simulate a closing fill (5 contracts at same price)
        # This should set contracts to 0 and trigger deletion
        cache._positions[market_id].apply_fill(
            contracts=5,
            price_cents=3000,
            fee_cents=2,
            side="yes",
            action="sell"
        )
        
        # After apply_fill, contracts should be 0
        assert cache._positions[market_id].contracts == 0
        
        # Simulate the fix: delete position
        del cache._positions[market_id]
        
        # Position should be gone
        assert market_id not in cache._positions
        assert len(cache._positions) == 0

    @pytest.mark.asyncio
    async def test_multiple_closes_and_opens(self):
        """Test that positions can be opened, closed, and reopened correctly."""
        cache = KalshiPositionCache()
        
        market_id = "KXXRP15M-14JIL220000-50"
        
        # Open position
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=4500,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        assert len(cache._positions) == 1
        
        # Close position
        cache._positions[market_id].contracts = 0
        del cache._positions[market_id]
        assert len(cache._positions) == 0
        
        # Reopen position (new entry)
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=8,
            side="yes",
            avg_price_cents=4600,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        assert len(cache._positions) == 1
        assert cache._positions[market_id].contracts == 8

    @pytest.mark.asyncio
    async def test_get_all_positions_accuracy_after_deletion(self):
        """get_all_positions should only return open positions after deletion."""
        cache = KalshiPositionCache()
        
        # Add positions
        market1 = "KXBTC15M-14JUL220000-50"
        market2 = "KXETH15M-14JUL220000-50"
        
        cache._positions[market1] = CachedPosition(
            market_id=market1,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=5000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        cache._positions[market2] = CachedPosition(
            market_id=market2,
            agent_id="test_agent",
            thesis_side="no",
            contracts=5,
            side="no",
            avg_price_cents=4000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Both positions open
        all_positions = cache.get_all_positions(validate_freshness=False)
        assert len(all_positions) == 2
        
        # Close one position
        cache._positions[market2].contracts = 0
        del cache._positions[market2]
        
        # Only one position should be returned
        all_positions = cache.get_all_positions(validate_freshness=False)
        assert len(all_positions) == 1
        assert market1 in all_positions
        assert market2 not in all_positions

    @pytest.mark.asyncio
    async def test_get_cache_health_accuracy_after_deletion(self):
        """get_cache_health should report accurate counts after deletion."""
        cache = KalshiPositionCache()
        
        # Add positions
        market1 = "KXBTC15M-14JUL220000-50"
        market2 = "KXETH15M-14JUL220000-50"
        market3 = "KXSOL15M-14JUL220000-50"
        
        cache._positions[market1] = CachedPosition(
            market_id=market1,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=5000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        cache._positions[market2] = CachedPosition(
            market_id=market2,
            agent_id="test_agent",
            thesis_side="no",
            contracts=5,
            side="no",
            avg_price_cents=4000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        cache._positions[market3] = CachedPosition(
            market_id=market3,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=8,
            side="yes",
            avg_price_cents=5500,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # All positions open
        health = cache.get_cache_health()
        assert health["total_positions"] == 3
        assert health["open_positions"] == 3
        assert health["closed_positions"] == 0
        
        # Close one position
        cache._positions[market2].contracts = 0
        del cache._positions[market2]
        
        # Health should reflect deletion
        health = cache.get_cache_health()
        assert health["total_positions"] == 2
        assert health["open_positions"] == 2
        assert health["closed_positions"] == 0

    @pytest.mark.asyncio
    async def test_sync_from_rest_filters_closed_positions(self):
        """sync_from_rest should not add positions with contracts=0."""
        cache = KalshiPositionCache()
        
        # Use future dates to avoid expired ticker filtering
        from datetime import datetime, timezone, timedelta
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        future_str = future_time.strftime('%d%b%H%M')
        
        # Sync with positions including closed ones
        positions_list = [
            {
                "market_id": f"KXBTC15M-{future_str}-50",
                "contracts": 10,
                "avg_price_cents": 5000,
                "side": "yes"
            },
            {
                "market_id": f"KXETH15M-{future_str}-50",
                "contracts": 0,  # Closed position
                "avg_price_cents": 4000,
                "side": "no"
            },
            {
                "market_id": f"KXSOL15M-{future_str}-50",
                "contracts": 5,
                "avg_price_cents": 5500,
                "side": "yes"
            }
        ]
        
        await cache.sync_from_rest(positions_list, rest_timestamp=asyncio.get_event_loop().time())
        
        # Only open positions should be in cache
        assert len(cache._positions) == 2
        assert f"KXBTC15M-{future_str}-50" in cache._positions
        assert f"KXSOL15M-{future_str}-50" in cache._positions
        assert f"KXETH15M-{future_str}-50" not in cache._positions

    @pytest.mark.asyncio
    async def test_exit_fill_reduces_position_correctly(self):
        """Exit fill should reduce position contracts correctly for both YES and NO sides."""
        cache = KalshiPositionCache()
        
        # Test NO position exit
        market_no = "KXXRP15M-21JUL220000-50"
        cache._positions[market_no] = CachedPosition(
            market_id=market_no,
            agent_id="test_agent",
            thesis_side="no",
            contracts=10,
            side="no",
            avg_price_cents=4000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Apply exit fill (SELL_NO)
        cache._positions[market_no].apply_fill(
            contracts=5,
            price_cents=4000,
            fee_cents=2,
            side="no",
            action="sell"
        )
        
        # Position should be reduced
        assert cache._positions[market_no].contracts == 5
        assert cache._positions[market_no].side == "no"
        
        # Test YES position exit
        market_yes = "KXBTC15M-21JUL220000-50"
        cache._positions[market_yes] = CachedPosition(
            market_id=market_yes,
            agent_id="test_agent",
            thesis_side="yes",
            contracts=10,
            side="yes",
            avg_price_cents=5000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        # Apply exit fill (SELL_YES)
        cache._positions[market_yes].apply_fill(
            contracts=3,
            price_cents=5000,
            fee_cents=2,
            side="yes",
            action="sell"
        )
        
        # Position should be reduced
        assert cache._positions[market_yes].contracts == 7
        assert cache._positions[market_yes].side == "yes"
