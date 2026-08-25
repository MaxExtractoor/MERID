"""
Tests for position cache entry price calculation and auto-fix (2026-08-01).

This test suite validates the critical fixes for:
1. Calculating avg_price_cents from market_exposure_dollars when REST API doesn't provide it
2. Auto-fixing invalid positions using fills ledger
3. Position monitor validation to skip positions with invalid data

Run with: pytest tests/test_position_cache_entry_price_fix_2026_08_01.py -v
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
from merid.event_venues.kalshi.position_cache import get_position_cache, KalshiPositionCache, CachedPosition
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.position import Position, PositionSide


class TestAvgPriceCalculationFromREST:
    """Test avg_price_cents calculation from market_exposure_dollars."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        # Clear any existing positions for clean test
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_calculate_avg_price_from_market_exposure(self, position_cache):
        """Test calculating avg_price_cents from market_exposure_dollars / position_fp."""
        # Mock REST position without avg_price_cents but with market_exposure_dollars
        # Use a future date ticker that won't be filtered as expired
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        rest_positions = [
            {
                "market_id": market_id,
                "contracts": 10,
                "side": "yes",
                "market_exposure_dollars": "5.00",  # $5.00 total exposure
                "position_fp": "10.00",  # 10 contracts
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should calculate avg_price_cents = 5.00 / 10 * 100 = 50c
        assert len(position_cache._positions) == 1
        position = position_cache._positions[market_id]
        assert position.avg_price_cents == 50
        assert position.entry_price_state == "known"
    
    @pytest.mark.asyncio
    async def test_calculate_avg_price_out_of_range_rejected(self, position_cache):
        """Test that calculated avg_price_cents out of 10-75c range is rejected."""
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        # Mock REST position with market_exposure that would calculate to 100c (out of range)
        rest_positions = [
            {
                "ticker": market_id,  # Use ticker field
                "contracts": 10,
                "side": "yes",
                "market_exposure_dollars": "10.00",  # $10.00 total exposure
                "position_fp": "10.00",  # 10 contracts -> would calculate to 100c
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should reject calculated price (100c out of range)
        # Position may still be added but with invalid price
        if market_id in position_cache._positions:
            position = position_cache._positions[market_id]
            assert position.avg_price_cents is None  # Rejected
            assert position.entry_price_state == "invalid"
        else:
            # Position was filtered out entirely (acceptable behavior)
            pass
    
    @pytest.mark.asyncio
    async def test_calculate_avg_price_below_range_rejected(self, position_cache):
        """Test that calculated avg_price_cents below 10c is rejected."""
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        # Mock REST position with market_exposure that would calculate to 5c (out of range)
        rest_positions = [
            {
                "ticker": market_id,  # Use ticker field
                "contracts": 10,
                "side": "yes",
                "market_exposure_dollars": "0.50",  # $0.50 total exposure
                "position_fp": "10.00",  # 10 contracts -> would calculate to 5c
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should reject calculated price (5c out of range)
        # Position may still be added but with invalid price
        if market_id in position_cache._positions:
            position = position_cache._positions[market_id]
            assert position.avg_price_cents is None  # Rejected
            assert position.entry_price_state == "invalid"
        else:
            # Position was filtered out entirely (acceptable behavior)
            pass
    
    @pytest.mark.asyncio
    async def test_use_api_provided_avg_price_when_available(self, position_cache):
        """Test that API-provided avg_price_cents is used when available."""
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        # Mock REST position with both avg_price_cents and market_exposure_dollars
        rest_positions = [
            {
                "market_id": market_id,
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 42,  # API provides this
                "market_exposure_dollars": "5.00",
                "position_fp": "10.00",
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should use API-provided avg_price_cents, not calculate
        assert len(position_cache._positions) == 1
        position = position_cache._positions[market_id]
        assert position.avg_price_cents == 42  # API value, not calculated 50
        assert position.entry_price_state == "known"
    
    @pytest.mark.asyncio
    async def test_missing_market_exposure_sets_unknown_state(self, position_cache):
        """Test that missing market_exposure_dollars sets entry_price_state to unknown."""
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        # Mock REST position without avg_price_cents or market_exposure_dollars
        rest_positions = [
            {
                "market_id": market_id,
                "contracts": 10,
                "side": "yes",
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should set to unknown state
        assert len(position_cache._positions) == 1
        position = position_cache._positions[market_id]
        assert position.avg_price_cents is None
        assert position.entry_price_state == "unknown"
    
    @pytest.mark.asyncio
    async def test_zero_position_fp_rejected(self, position_cache):
        """Test that position_fp=0 is rejected (division by zero protection)."""
        from datetime import datetime, timezone, timedelta
        future_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%d%b")
        future_time = "2000"
        market_id = f"KXBTC15M-{future_date}{future_time}-30"

        # Mock REST position with position_fp=0
        rest_positions = [
            {
                "market_id": market_id,
                "contracts": 10,
                "side": "yes",
                "market_exposure_dollars": "5.00",
                "position_fp": "0.00",  # Invalid
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.5
            }
        ]

        await position_cache.sync_from_rest(rest_positions, force=True)

        # Should reject due to division by zero
        assert len(position_cache._positions) == 1
        position = position_cache._positions[market_id]
        assert position.avg_price_cents is None
        assert position.entry_price_state == "invalid"


class TestAutoFixInvalidPositions:
    """Test auto-fix functionality for invalid positions."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        # Clear any existing positions for clean test
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_force_health_check_and_fix(self, position_cache):
        """Test force_health_check_and_fix method."""
        # Add position with invalid avg_price_cents
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=None,  # Invalid
            entry_price_state="unknown"
        )
        
        # Mock fills ledger
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.count = 10
        mock_fill.contracts = 10
        mock_fill.price_cents = 50
        mock_fill.side = "yes"
        mock_fill.action = "buy"
        mock_ledger.get_fills = Mock(return_value=[mock_fill])
        
        with patch.object(position_cache, '_get_fills_ledger', return_value=mock_ledger):
            fixed_count = position_cache.force_health_check_and_fix()
        
        # Position should be fixed
        position = position_cache._positions["KXBTC15M-26JUL012015-30"]
        assert position.avg_price_cents == 50
        assert position.entry_price_state == "known"
    
    @pytest.mark.asyncio
    async def test_auto_fix_updates_thesis_side(self, position_cache):
        """Test that auto-fix updates thesis_side from fills."""
        # Add position with invalid avg_price_cents and unknown thesis_side
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="unknown",  # Unknown
            avg_price_cents=None,
            entry_price_state="unknown"
        )
        
        # Mock fills ledger with NO side
        mock_ledger = Mock()
        mock_fill = Mock()
        mock_fill.count = 10
        mock_fill.contracts = 10
        mock_fill.price_cents = 50
        mock_fill.side = "no"  # NO side
        mock_fill.action = "buy"
        mock_ledger.get_fills = Mock(return_value=[mock_fill])
        
        with patch.object(position_cache, '_get_fills_ledger', return_value=mock_ledger):
            position_cache.force_health_check_and_fix()
        
        # Position should be fixed with correct thesis_side
        position = position_cache._positions["KXBTC15M-26JUL012015-30"]
        assert position.avg_price_cents == 50
        assert position.thesis_side == "no"  # Updated from fills
        assert position.side == "no"  # Side updated for consistency
    
    @pytest.mark.asyncio
    async def test_auto_fix_no_fills_available(self, position_cache):
        """Test auto-fix when no fills are available."""
        # Add position with invalid avg_price_cents
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=None,
            entry_price_state="unknown"
        )
        
        # Mock fills ledger with no fills
        mock_ledger = Mock()
        mock_ledger.get_fills = Mock(return_value=[])
        
        with patch.object(position_cache, '_get_fills_ledger', return_value=mock_ledger):
            position_cache.force_health_check_and_fix()
        
        # Position should remain invalid
        position = position_cache._positions["KXBTC15M-26JUL012015-30"]
        assert position.avg_price_cents is None
        assert position.entry_price_state == "unknown"


class TestPositionMonitorValidation:
    """Test position monitor validation for invalid positions."""
    
    @pytest.fixture
    def position_cache(self):
        """Get position cache instance for testing."""
        cache = get_position_cache()
        # Clear any existing positions for clean test
        cache._positions.clear()
        cache._last_sync = None
        return cache
    
    @pytest.mark.asyncio
    async def test_skip_position_with_unknown_thesis_side(self, position_cache):
        """Test that positions with unknown thesis_side are skipped during startup."""
        # Add position with unknown thesis_side to cache
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="unknown",  # Unknown - should be skipped
            avg_price_cents=50,
            entry_price_state="known"
        )
        
        # Mock risk envelope
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = Mock()
            mock_get_envelope.return_value = mock_envelope
            
            monitor = PositionMonitor()
            
            # Start monitor (which loads positions from cache)
            await monitor.start()
            await monitor.stop()
            
            # Position should NOT be added to monitor
            assert len(monitor.get_open_positions()) == 0
    
    @pytest.mark.asyncio
    async def test_skip_position_with_invalid_avg_price(self, position_cache):
        """Test that positions with invalid avg_price_cents are skipped during startup."""
        # Add position with invalid avg_price_cents to cache
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=None,  # Invalid - should be skipped
            entry_price_state="unknown"
        )
        
        # Mock risk envelope
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = Mock()
            mock_get_envelope.return_value = mock_envelope
            
            monitor = PositionMonitor()
            
            # Start monitor (which loads positions from cache)
            await monitor.start()
            await monitor.stop()
            
            # Position should NOT be added to monitor
            assert len(monitor.get_open_positions()) == 0
    
    @pytest.mark.asyncio
    async def test_skip_position_with_zero_avg_price(self, position_cache):
        """Test that positions with avg_price_cents=0 are skipped during startup."""
        # Add position with avg_price_cents=0 to cache
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=0,  # Invalid - should be skipped
            entry_price_state="invalid"
        )
        
        # Mock risk envelope
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = Mock()
            mock_get_envelope.return_value = mock_envelope
            
            monitor = PositionMonitor()
            
            # Start monitor (which loads positions from cache)
            await monitor.start()
            await monitor.stop()
            
            # Position should NOT be added to monitor
            assert len(monitor.get_open_positions()) == 0
    
    @pytest.mark.asyncio
    async def test_add_valid_position(self, position_cache):
        """Test that valid positions are added to monitor during startup."""
        # Add valid position to cache
        position_cache._positions["KXBTC15M-26JUL012015-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL012015-30",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",  # Valid
            avg_price_cents=50,  # Valid
            entry_price_state="known"
        )
        
        # Mock risk envelope
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = Mock()
            mock_get_envelope.return_value = mock_envelope
            
            monitor = PositionMonitor()
            
            # Start monitor (which loads positions from cache)
            await monitor.start()
            await monitor.stop()
            
            # Position SHOULD be added to monitor
            assert len(monitor.get_open_positions()) == 1
            position = monitor.get_position_by_market("KXBTC15M-26JUL012015-30")
            assert position is not None
            assert position.avg_entry_price_cents == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
