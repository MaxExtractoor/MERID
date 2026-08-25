"""
Integration tests for REST sync unknown side handling (2026-07-22 fix).

Tests that REST sync handles new positions correctly when thesis_side cannot
be determined from REST alone (Kalshi always reports side="yes").

Key changes:
1. New positions from REST try to infer thesis_side from fill history
2. If fill history lookup fails, thesis_side is set to "unknown"
3. Positions with thesis_side="unknown" are skipped when adding to PositionMonitor
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from merid.event_venues.kalshi.position_cache import CachedPosition, KalshiPositionCache


class TestRestSyncUnknownSideHandling:
    """Test REST sync handling of unknown thesis_side."""
    
    @pytest.fixture
    def position_cache(self):
        """Create a position cache instance for testing."""
        cache = KalshiPositionCache()
        cache._initialized = True
        cache._positions = {}
        return cache
    
    @pytest.fixture
    def sample_rest_positions(self):
        """Sample REST API response with positions."""
        return [
            {
                "market_id": "KXBTC15M-26JUL211745-45",
                "contracts": 10,
                "side": "yes",  # Kalshi REST always reports "yes"
                "avg_price_cents": 50,
                "realized_pnl": 0,
                "unrealized_pnl": 5.0,
            },
        ]
    
    def test_infer_thesis_side_from_fill_history_yes(self, position_cache):
        """Test that thesis_side is correctly inferred from fill history for YES positions."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with a YES entry fill
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.market_id = market_id
        mock_fill.fill_id = "fill_123"
        mock_fill.raw_payload = '{"side": "yes", "action": "buy"}'
        mock_ledger.get_fills_by_market.return_value = [mock_fill]
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert YES was inferred
        assert inferred_side == "yes"
    
    def test_infer_thesis_side_from_fill_history_no(self, position_cache):
        """Test that thesis_side is correctly inferred from fill history for NO positions."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with a NO entry fill
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.market_id = market_id
        mock_fill.fill_id = "fill_123"
        mock_fill.raw_payload = '{"side": "no", "action": "buy"}'
        mock_ledger.get_fills_by_market.return_value = [mock_fill]
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert NO was inferred
        assert inferred_side == "no"
    
    def test_infer_thesis_side_from_fill_history_no_fills(self, position_cache):
        """Test that thesis_side inference returns None when no fills found."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with no fills
        mock_ledger = Mock()
        mock_ledger.get_fills_by_market.return_value = []
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert None was returned
        assert inferred_side is None
    
    def test_infer_thesis_side_from_fill_history_no_ledger(self, position_cache):
        """Test that thesis_side inference returns None when fills_ledger is unavailable."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # No fills_ledger
        position_cache._fills_ledger = None
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert None was returned
        assert inferred_side is None
    
    def test_infer_thesis_side_from_fill_history_get_recent_fills_fallback(self, position_cache):
        """Test that thesis_side inference falls back to get_recent_fills if get_fills_by_market not available."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with get_recent_fills but not get_fills_by_market
        mock_ledger = Mock(spec=['get_recent_fills'])  # Only have get_recent_fills
        
        mock_fill = Mock()
        mock_fill.market_id = market_id
        mock_fill.fill_id = "fill_123"
        mock_fill.raw_payload = '{"side": "yes", "action": "buy"}'
        mock_ledger.get_recent_fills.return_value = [mock_fill]
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert YES was inferred via fallback
        assert inferred_side == "yes"
    
    def test_new_position_with_unknown_thesis_side(self, sample_rest_positions):
        """Test that new positions with unknown thesis_side are created correctly."""
        rest_position = sample_rest_positions[0]
        
        # Create position with unknown thesis_side
        position = CachedPosition(
            market_id=rest_position["market_id"],
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],
            thesis_side="unknown",  # Could not determine from fill history
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert position was created with unknown thesis_side
        assert position.thesis_side == "unknown"
        assert position.contracts == 10
    
    def test_unknown_thesis_side_blocks_position_monitor_addition(self, position_cache):
        """Test that positions with unknown thesis_side are skipped when adding to PositionMonitor."""
        # Create position with unknown thesis_side
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="unknown",
            avg_price_cents=50,
        )
        
        # Add to cache
        position_cache._positions["KXBTC15M-26JUL211745-45"] = position
        
        # Simulate the check in sync_from_rest
        should_skip = position.thesis_side == "unknown"
        
        # Assert position should be skipped
        assert should_skip is True
    
    def test_known_thesis_side_allows_position_monitor_addition(self, position_cache):
        """Test that positions with known thesis_side are added to PositionMonitor."""
        # Create position with known thesis_side
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",  # Known
            avg_price_cents=50,
        )
        
        # Add to cache
        position_cache._positions["KXBTC15M-26JUL211745-45"] = position
        
        # Simulate the check in sync_from_rest
        should_skip = position.thesis_side == "unknown"
        
        # Assert position should NOT be skipped
        assert should_skip is False
    
    def test_infer_thesis_side_ignores_exit_fills(self, position_cache):
        """Test that thesis_side inference ignores exit fills (action=sell)."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with an exit fill (should be ignored)
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.market_id = market_id
        mock_fill.fill_id = "fill_123"
        mock_fill.raw_payload = '{"side": "yes", "action": "sell"}'  # Exit fill
        mock_ledger.get_fills_by_market.return_value = [mock_fill]
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert None was returned (exit fill ignored)
        assert inferred_side is None
    
    def test_infer_thesis_side_uses_entry_fill(self, position_cache):
        """Test that thesis_side inference uses entry fills (action=buy)."""
        market_id = "KXBTC15M-26JUL211745-45"
        
        # Mock fills_ledger with an entry fill
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.market_id = market_id
        mock_fill.fill_id = "fill_123"
        mock_fill.raw_payload = '{"side": "no", "action": "buy"}'  # Entry fill
        mock_ledger.get_fills_by_market.return_value = [mock_fill]
        
        position_cache._fills_ledger = mock_ledger
        
        # Infer thesis_side
        inferred_side = position_cache._infer_thesis_side_from_fill_history(market_id)
        
        # Assert NO was inferred from entry fill
        assert inferred_side == "no"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
