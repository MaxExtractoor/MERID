"""
Tests for position cache rebuild from fills ledger.

CRITICAL FIX (2026-07-23): When REST API returns empty positions but fills ledger
shows active positions, the position cache should rebuild from fills ledger (canonical source).
This ensures positions are tracked for exit policies even when REST is unreliable.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch
from collections import namedtuple

from merid.event_venues.kalshi.position_cache import KalshiPositionCache


# Mock KalshiFill for testing
KalshiFill = namedtuple('KalshiFill', [
    'fill_id', 'market_id', 'count', 'price_cents', 'side', 'action', 
    'order_id', 'raw_payload', 'agent_id'
])


class TestPositionCacheRebuildFromFillsLedger:
    """Test position cache rebuild from fills ledger functionality."""
    
    @pytest.mark.asyncio
    async def test_rebuild_from_fills_ledger_basic(self):
        """Test basic rebuild from fills ledger."""
        cache = KalshiPositionCache()
        cache._positions.clear()  # Clear any existing positions
        
        # Mock fills ledger with recent fills
        mock_ledger = Mock()
        mock_fill1 = KalshiFill(
            fill_id="fill1",
            market_id="KXBTC15M-1234",
            count=10,
            price_cents=50,
            side="yes",
            action="buy",
            order_id="order1",
            raw_payload='{"take_profit_price_cents": 60, "stop_loss_price_cents": 40}',
            agent_id="BTC_15M"
        )
        mock_ledger.get_recent_fills.return_value = [mock_fill1]
        
        with patch.object(cache, '_get_fills_ledger', return_value=mock_ledger):
            await cache._rebuild_from_fills_ledger()
        
        # Verify position was rebuilt
        assert len(cache._positions) == 1
        position = cache._positions.get("KXBTC15M-1234")
        assert position is not None
        assert position.contracts == 10
        assert position.avg_price_cents == 50
        assert position.thesis_side == "yes"
        assert position.take_profit_price_cents == 60
        assert position.stop_loss_price_cents == 40
    
    @pytest.mark.asyncio
    async def test_rebuild_computes_net_position(self):
        """Test that rebuild computes net position from multiple fills."""
        cache = KalshiPositionCache()
        cache._positions.clear()  # Clear any existing positions
        
        # Mock fills ledger with entry and exit fills
        mock_ledger = Mock()
        mock_fill1 = KalshiFill(
            fill_id="fill1",
            market_id="KXBTC15M-1234",
            count=10,
            price_cents=50,
            side="yes",
            action="buy",
            order_id="order1",
            raw_payload='{}',
            agent_id="BTC_15M"
        )
        mock_fill2 = KalshiFill(
            fill_id="fill2",
            market_id="KXBTC15M-1234",
            count=3,
            price_cents=55,
            side="yes",
            action="sell",  # Exit fill
            order_id="order2",
            raw_payload='{}',
            agent_id="BTC_15M"
        )
        mock_ledger.get_recent_fills.return_value = [mock_fill1, mock_fill2]
        
        with patch.object(cache, '_get_fills_ledger', return_value=mock_ledger):
            await cache._rebuild_from_fills_ledger()
        
        # Net position should be 10 - 3 = 7
        position = cache._positions.get("KXBTC15M-1234")
        assert position is not None
        assert position.contracts == 7


class TestPositionCacheSyncFromRestWithRebuild:
    """Test sync_from_rest with fills ledger rebuild fallback."""
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_empty_triggers_rebuild(self):
        """Test that empty REST response triggers rebuild when cache is empty."""
        cache = KalshiPositionCache()
        cache._positions.clear()  # Clear any existing positions
        
        # Mock fills ledger
        mock_ledger = Mock()
        mock_fill = KalshiFill(
            fill_id="fill1",
            market_id="KXBTC15M-1234",
            count=10,
            price_cents=50,
            side="yes",
            action="buy",
            order_id="order1",
            raw_payload='{}',
            agent_id="BTC_15M"
        )
        mock_ledger.get_recent_fills.return_value = [mock_fill]
        
        with patch.object(cache, '_get_fills_ledger', return_value=mock_ledger):
            # Call sync_from_rest with empty positions
            await cache.sync_from_rest(positions=[], rest_timestamp=None)
        
        # Should have rebuilt from fills ledger
        assert len(cache._positions) == 1
        assert "KXBTC15M-1234" in cache._positions
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_empty_preserves_existing(self):
        """Test that empty REST response preserves existing cache when not empty."""
        cache = KalshiPositionCache()
        cache._positions.clear()  # Clear any existing positions
        
        # Add existing position to cache
        from merid.event_venues.kalshi.position_cache import CachedPosition
        cache._positions["KXBTC15M-1234"] = CachedPosition(
            market_id="KXBTC15M-1234",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
        )
        
        # Call sync_from_rest with empty positions
        await cache.sync_from_rest(positions=[], rest_timestamp=None)
        
        # Existing position should be preserved
        assert len(cache._positions) == 1
        assert "KXBTC15M-1234" in cache._positions
    
    @pytest.mark.asyncio
    async def test_sync_from_rest_non_empty_skips_rebuild(self):
        """Test that non-empty REST response skips rebuild."""
        cache = KalshiPositionCache()
        
        # Mock fills ledger (should not be called)
        mock_ledger = Mock()
        
        with patch.object(cache, '_get_fills_ledger', return_value=mock_ledger):
            # Call sync_from_rest with non-empty positions
            await cache.sync_from_rest(
                positions=[{
                    "market_id": "KXBTC15M-1234",
                    "contracts": 10,
                    "side": "yes",
                    "avg_price_cents": 50,
                }],
                rest_timestamp=None
            )
        
        # Should not have called fills ledger
        mock_ledger.get_recent_fills.assert_not_called()
