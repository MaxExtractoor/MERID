"""Unit tests for offset hedging functionality."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


class TestOffsetHedging:
    """Test offset hedging logic."""
    
    @pytest.mark.asyncio
    async def test_should_hedge_position_enabled(self):
        """Test that hedging is enabled when conditions are met."""
        from merid.event_venues.kalshi.offset_hedging import should_hedge_position
        
        # Mock profile to enable hedging
        with patch('merid.event_venues.kalshi.offset_hedging._is_offset_hedging_enabled', return_value=True), \
             patch('merid.event_venues.kalshi.offset_hedging._get_min_edge_for_hedge', return_value=0.03), \
             patch('merid.event_venues.kalshi.offset_hedging._get_hedge_ratio', return_value=0.30), \
             patch('merid.event_venues.kalshi.offset_hedging._get_max_hedge_notional_pct', return_value=0.02), \
             patch('merid.event_venues.kalshi.offset_hedging._get_min_hedge_contracts', return_value=1), \
             patch('merid.event_venues.kalshi.offset_hedging._get_max_hedge_contracts', return_value=3):
            
            should_hedge, hedge_contracts, reason = await should_hedge_position(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.05,  # 5% edge > 3% threshold
                fill_price_cents=50,
                fill_count=10,
                bankroll_usd=1000.0
            )
            
            assert should_hedge is True
            assert hedge_contracts == 3  # 10 * 0.30 = 3
            assert reason == "hedge_approved"
    
    @pytest.mark.asyncio
    async def test_should_hedge_position_disabled(self):
        """Test that hedging is disabled when feature is off."""
        from merid.event_venues.kalshi.offset_hedging import should_hedge_position
        
        with patch('merid.event_venues.kalshi.offset_hedging._is_offset_hedging_enabled', return_value=False):
            should_hedge, hedge_contracts, reason = await should_hedge_position(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.05,
                fill_price_cents=50,
                fill_count=10,
                bankroll_usd=1000.0
            )
            
            assert should_hedge is False
            assert hedge_contracts is None
            assert reason == "offset_hedging_disabled"
    
    @pytest.mark.asyncio
    async def test_should_hedge_position_edge_below_threshold(self):
        """Test that hedging is skipped when edge is below threshold."""
        from merid.event_venues.kalshi.offset_hedging import should_hedge_position
        
        with patch('merid.event_venues.kalshi.offset_hedging._is_offset_hedging_enabled', return_value=True), \
             patch('merid.event_venues.kalshi.offset_hedging._get_min_edge_for_hedge', return_value=0.03):
            
            should_hedge, hedge_contracts, reason = await should_hedge_position(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.02,  # 2% edge < 3% threshold
                fill_price_cents=50,
                fill_count=10,
                bankroll_usd=1000.0
            )
            
            assert should_hedge is False
            assert hedge_contracts is None
            assert "edge_below_threshold" in reason
    
    @pytest.mark.asyncio
    async def test_should_hedge_position_notional_cap(self):
        """Test that hedge notional is capped at max percentage."""
        from merid.event_venues.kalshi.offset_hedging import should_hedge_position
        
        with patch('merid.event_venues.kalshi.offset_hedging._is_offset_hedging_enabled', return_value=True), \
             patch('merid.event_venues.kalshi.offset_hedging._get_min_edge_for_hedge', return_value=0.03), \
             patch('merid.event_venues.kalshi.offset_hedging._get_hedge_ratio', return_value=0.30), \
             patch('merid.event_venues.kalshi.offset_hedging._get_max_hedge_notional_pct', return_value=0.01), \
             patch('merid.event_venues.kalshi.offset_hedging._get_min_hedge_contracts', return_value=1), \
             patch('merid.event_venues.kalshi.offset_hedging._get_max_hedge_contracts', return_value=3):
            
            # Small bankroll, should cap hedge
            should_hedge, hedge_contracts, reason = await should_hedge_position(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.05,
                fill_price_cents=50,
                fill_count=100,  # Large fill
                bankroll_usd=100.0  # Small bankroll
            )
            
            assert should_hedge is True
            # Max notional = 100 * 0.01 = $1.00
            # Hedge notional at 30 contracts = 30 * 0.50 = $15.00 (exceeds cap)
            # Should be reduced to fit within $1.00 cap
            assert hedge_contracts <= 2  # Reduced from 30
    
    @pytest.mark.asyncio
    async def test_place_hedge_order_success(self):
        """Test successful hedge order placement."""
        from merid.event_venues.kalshi.offset_hedging import place_hedge_order
        
        # Mock order router
        mock_result = MagicMock()
        mock_result.status = "filled_live"
        
        with patch('merid.event_venues.kalshi.offset_hedging.route_order_async', new_callable=AsyncMock, return_value=mock_result):
            success = await place_hedge_order(
                ticker="KXBTC15M-26JUL020700-00",
                hedge_side="no",
                hedge_contracts=3,
                fill_price_cents=50
            )
            
            assert success is True
    
    @pytest.mark.asyncio
    async def test_place_hedge_order_failure(self):
        """Test hedge order placement failure."""
        from merid.event_venues.kalshi.offset_hedging import place_hedge_order
        
        # Mock order router failure
        mock_result = MagicMock()
        mock_result.status = "rejected"
        mock_result.reason = "insufficient_balance"
        
        with patch('merid.event_venues.kalshi.offset_hedging.route_order_async', new_callable=AsyncMock, return_value=mock_result):
            success = await place_hedge_order(
                ticker="KXBTC15M-26JUL020700-00",
                hedge_side="no",
                hedge_contracts=3,
                fill_price_cents=50
            )
            
            assert success is False
    
    @pytest.mark.asyncio
    async def test_handle_fill_for_hedging_no_hedge_needed(self):
        """Test that no hedge is placed when conditions not met."""
        from merid.event_venues.kalshi.offset_hedging import handle_fill_for_hedging
        
        with patch('merid.event_venues.kalshi.offset_hedging.should_hedge_position', new_callable=AsyncMock, return_value=(False, None, "edge_below_threshold")):
            result = await handle_fill_for_hedging(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.02,
                fill_price_cents=50,
                fill_count=10,
                bankroll_usd=1000.0
            )
            
            assert result is True  # No hedge needed is not a failure
    
    @pytest.mark.asyncio
    async def test_handle_fill_for_hedging_hedge_placed(self):
        """Test that hedge is placed when conditions are met."""
        from merid.event_venues.kalshi.offset_hedging import handle_fill_for_hedging
        
        with patch('merid.event_venues.kalshi.offset_hedging.should_hedge_position', new_callable=AsyncMock, return_value=(True, 3, "hedge_approved")), \
             patch('merid.event_venues.kalshi.offset_hedging.place_hedge_order', new_callable=AsyncMock, return_value=True):
            
            result = await handle_fill_for_hedging(
                ticker="KXBTC15M-26JUL020700-00",
                side="yes",
                edge_pct=0.05,
                fill_price_cents=50,
                fill_count=10,
                bankroll_usd=1000.0
            )
            
            assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
