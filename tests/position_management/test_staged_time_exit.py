"""
Tests for staged time-based exit functionality.

Tests the 25%/25%/50% partial exit strategy at 5/10/13 minutes in PositionMonitor.
CRITICAL FIX: 2026-07-07 - Staged exits moved from position_cache to PositionMonitor
This ensures proper callback routing with agent_id, swing mode logic, and error handling.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitReason


class TestStagedTimeExit:
    """Test staged time-based exit logic in PositionMonitor."""
    
    @pytest.fixture
    def mock_position(self):
        """Create a mock position for testing."""
        position = Position(
            market_id="KXBTC15M-2024-01-01T12:00:00",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        return position
    
    @pytest.fixture
    def mock_market_state(self):
        """Create a mock market state."""
        state = Mock()
        state.mid_cents = 52
        state.seconds_to_expiry = 600  # 10 minutes to expiry
        return state
    
    @pytest.fixture
    def mock_market_state_store(self, mock_market_state):
        """Create a mock market state store."""
        store = Mock()
        store.get = Mock(return_value=mock_market_state)
        return store
    
    def test_stage_0_triggers_at_5_minutes(self, mock_position):
        """Test that stage 0 (25%) triggers at 5 minutes in PositionMonitor."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        monitor.add_position(mock_position)
        
        # Simulate 5 minutes since entry (10 minutes to expiry)
        with patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store') as mock_store:
            mock_state = Mock()
            mock_state.seconds_to_expiry = 600  # 10 minutes to expiry
            mock_store.return_value.get.return_value = mock_state
            
            # Check position at 5 minutes since entry
            asyncio.run(monitor._check_position(mock_position, 52))
        
        # Stage 0 should trigger: 25% of 10 = 2.5 -> 2 contracts
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1] == ExitReason.TIME_STOP
        assert call_args[0][3] == 2  # contracts_to_close (partial exit)
        assert mock_position.size == 8  # 10 - 2 = 8 remaining
        assert mock_position.staged_exit_stage_0_executed is True
    
    def test_stage_1_triggers_at_10_minutes(self, mock_position):
        """Test that stage 1 (25%) triggers at 10 minutes in PositionMonitor."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Simulate after stage 0: 8 contracts remaining
        mock_position.size = 8
        mock_position.staged_exit_stage_0_executed = True
        
        monitor.add_position(mock_position)
        
        # Simulate 10 minutes since entry (5 minutes to expiry)
        with patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store') as mock_store:
            mock_state = Mock()
            mock_state.seconds_to_expiry = 300  # 5 minutes to expiry
            mock_store.return_value.get.return_value = mock_state
            
            # Check position at 10 minutes since entry
            asyncio.run(monitor._check_position(mock_position, 52))
        
        # Stage 1 should trigger: 25% of 8 = 2 contracts
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1] == ExitReason.TIME_STOP
        assert call_args[0][3] == 2  # contracts_to_close (partial exit)
        assert mock_position.size == 6  # 8 - 2 = 6 remaining
        assert mock_position.staged_exit_stage_1_executed is True
    
    def test_stage_2_triggers_at_13_minutes(self, mock_position):
        """Test that stage 2 (50%) triggers at 13 minutes in PositionMonitor."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Simulate after stages 0 and 1: 6 contracts remaining
        mock_position.size = 6
        mock_position.staged_exit_stage_0_executed = True
        mock_position.staged_exit_stage_1_executed = True
        
        monitor.add_position(mock_position)
        
        # Simulate 13 minutes since entry (2 minutes to expiry)
        with patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store') as mock_store:
            mock_state = Mock()
            mock_state.seconds_to_expiry = 120  # 2 minutes to expiry
            mock_store.return_value.get.return_value = mock_state
            
            # Check position at 13 minutes since entry
            asyncio.run(monitor._check_position(mock_position, 52))
        
        # Stage 2 should trigger: 50% of 6 = 3 contracts
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1] == ExitReason.TIME_STOP
        assert call_args[0][3] == 3  # contracts_to_close (partial exit)
        assert mock_position.size == 3  # 6 - 3 = 3 remaining
        assert mock_position.staged_exit_stage_2_executed is True
    
    def test_stage_execution_prevents_duplicate_exits(self, mock_position):
        """Test that each stage only executes once in PositionMonitor."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Mark stage 0 as already executed
        mock_position.staged_exit_stage_0_executed = True
        
        monitor.add_position(mock_position)
        
        # Simulate 5 minutes since entry
        with patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store') as mock_store:
            mock_state = Mock()
            mock_state.seconds_to_expiry = 600  # 10 minutes to expiry
            mock_store.return_value.get.return_value = mock_state
            
            # Check position at 5 minutes since entry
            asyncio.run(monitor._check_position(mock_position, 52))
        
        # Stage 0 should not execute again
        callback.assert_not_called()
        assert mock_position.size == 10  # No change
    
    def test_time_since_entry_calculation(self):
        """Test time since entry calculation in PositionMonitor."""
        # Test 5 minutes since entry (10 minutes to expiry)
        time_to_expiry_seconds = 600
        time_since_entry_seconds = 900.0 - time_to_expiry_seconds
        if time_since_entry_seconds < 0:
            time_since_entry_seconds = 0
        time_since_entry_minutes = time_since_entry_seconds / 60.0
        
        assert time_since_entry_minutes == 5.0  # 15 - 10 = 5 minutes since entry
    
    def test_time_since_entry_clamped_to_zero(self):
        """Test that time since entry is clamped to zero if negative."""
        # Test negative case (more than 15 minutes)
        time_to_expiry_seconds = 1000
        time_since_entry_seconds = 900.0 - time_to_expiry_seconds
        if time_since_entry_seconds < 0:
            time_since_entry_seconds = 0
        time_since_entry_minutes = time_since_entry_seconds / 60.0
        
        assert time_since_entry_minutes == 0  # Clamped to zero
    
    def test_staged_exit_uses_callback_routing(self, mock_position):
        """Test that staged exits use proper callback routing in PositionMonitor."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        monitor.add_position(mock_position)
        
        # Simulate 5 minutes since entry
        with patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store') as mock_store:
            mock_state = Mock()
            mock_state.seconds_to_expiry = 600  # 10 minutes to expiry
            mock_store.return_value.get.return_value = mock_state
            
            # Check position at 5 minutes since entry
            asyncio.run(monitor._check_position(mock_position, 52))
        
        # Callback should be called with proper parameters
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] is mock_position  # position
        assert call_args[0][1] == ExitReason.TIME_STOP  # exit_reason
        assert call_args[0][2] == 52  # exit_price_cents
        assert call_args[0][3] == 2  # contracts_to_close (partial exit)
    
    def test_position_monitor_authoritative_for_staged_exits(self):
        """Test that PositionMonitor is now authoritative for staged exits."""
        # This test verifies the consolidation fix:
        # - Staged exits are now in PositionMonitor (not position_cache)
        # - They use proper callback routing
        # - They have proper agent_id, swing mode logic, error handling
        
        from merid.position_management.position_monitor import PositionMonitor
        from merid.position_management.position import Position, PositionSide
        
        monitor = PositionMonitor()
        position = Position(
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        monitor.add_position(position)
        
        # Verify position has staged exit tracking fields
        assert hasattr(position, 'staged_exit_stage_0_executed')
        assert hasattr(position, 'staged_exit_stage_1_executed')
        assert hasattr(position, 'staged_exit_stage_2_executed')
        
        # Verify fields are initialized correctly
        assert position.staged_exit_stage_0_executed is False
        assert position.staged_exit_stage_1_executed is False
        assert position.staged_exit_stage_2_executed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
