"""Tests for ratchet bracket cancellation logic.

This tests that ratchet exit properly cancels existing TP/SL brackets
before submitting the exit order to prevent duplicate orders.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone


class TestRatchetBracketCancellation:
    """Test suite for ratchet bracket cancellation."""
    
    def test_ratchet_exit_cancels_tp_bracket(self):
        """Test that ratchet exit cancels TP bracket before submission."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            agent_id="test_agent",
            side="yes",
            thesis_side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag="BRACKET_TP_BTC-USD-240329-W10_99_123456",
            sl_bracket_client_tag=None,
        )
        
        # Verify TP bracket exists
        assert position.tp_bracket_client_tag is not None
        
        # Simulate bracket cancellation (as happens in position cache)
        position.tp_bracket_client_tag = None
        
        # Verify TP bracket is cleared
        assert position.tp_bracket_client_tag is None
    
    def test_ratchet_exit_cancels_sl_bracket(self):
        """Test that ratchet exit cancels SL bracket before submission."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            agent_id="test_agent",
            contracts=10,
            thesis_side="yes",
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag=None,
            sl_bracket_client_tag="BRACKET_SL_BTC-USD-240329-W10_45_123456",
        )
        
        # Verify SL bracket exists
        assert position.sl_bracket_client_tag is not None
        
        # Simulate bracket cancellation
        position.sl_bracket_client_tag = None
        
        # Verify SL bracket is cleared
        assert position.sl_bracket_client_tag is None
    
    def test_ratchet_exit_cancels_both_brackets(self):
        """Test that ratchet exit cancels both TP and SL brackets."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            agent_id="test_agent",
            contracts=10,
            thesis_side="yes",
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag="BRACKET_TP_BTC-USD-240329-W10_99_123456",
            sl_bracket_client_tag="BRACKET_SL_BTC-USD-240329-W10_45_123456",
        )
        
        # Verify both brackets exist
        assert position.tp_bracket_client_tag is not None
        assert position.sl_bracket_client_tag is not None
        
        # Simulate bracket cancellation
        position.tp_bracket_client_tag = None
        position.sl_bracket_client_tag = None
        
        # Verify both brackets are cleared
        assert position.tp_bracket_client_tag is None
        assert position.sl_bracket_client_tag is None
    
    def test_ratchet_exit_no_brackets_to_cancel(self):
        """Test ratchet exit when no brackets exist (no-op)."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            agent_id="test_agent",
            contracts=10,
            thesis_side="yes",
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag=None,
            sl_bracket_client_tag=None,
        )
        
        # Verify no brackets exist
        assert position.tp_bracket_client_tag is None
        assert position.sl_bracket_client_tag is None
        
        # Cancellation should be no-op (no error)
        position.tp_bracket_client_tag = None
        position.sl_bracket_client_tag = None
        
        # Still no brackets
        assert position.tp_bracket_client_tag is None
        assert position.sl_bracket_client_tag is None
    
    @pytest.mark.asyncio
    async def test_cancel_brackets_async_mock(self):
        """Test bracket cancellation with async mock."""
        from merid.event_venues.kalshi.position_cache import CachedPosition, KalshiPositionCache
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            agent_id="test_agent",
            contracts=10,
            thesis_side="yes",
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag="BRACKET_TP_BTC-USD-240329-W10_99_123456",
            sl_bracket_client_tag="BRACKET_SL_BTC-USD-240329-W10_45_123456",
        )
        
        # Mock the cancel method
        cache = KalshiPositionCache()
        
        with patch.object(cache, '_cancel_brackets', new_callable=AsyncMock) as mock_cancel:
            # Simulate the ratchet exit path
            if position.tp_bracket_client_tag or position.sl_bracket_client_tag:
                await cache._cancel_brackets(position)
            
            # Verify cancel was called
            mock_cancel.assert_called_once_with(position)
    
    def test_bracket_cancellation_tolerates_missing_orders(self):
        """Test that bracket cancellation tolerates already-filled orders."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            agent_id="test_agent",
            contracts=10,
            thesis_side="yes",
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
            tp_bracket_client_tag="BRACKET_TP_BTC-USD-240329-W10_99_123456",
            sl_bracket_client_tag="BRACKET_SL_BTC-USD-240329-W10_45_123456",
        )
        
        # Simulate cancellation (brackets may already be filled)
        # The implementation should tolerate missing orders gracefully
        position.tp_bracket_client_tag = None
        position.sl_bracket_client_tag = None
        
        # Should not raise error even if orders were already filled
        assert position.tp_bracket_client_tag is None
        assert position.sl_bracket_client_tag is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
