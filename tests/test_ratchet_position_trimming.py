"""Test ratchet position trimming logic.

Tests the position trimming feature that reduces position size when >1 contract
and price crosses the trim threshold (80c) to lock in partial profits.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitReason


class TestRatchetPositionTrimming:
    """Test suite for ratchet position trimming logic."""
    
    def test_ratchet_trim_triggered_for_yes_position(self):
        """Test that ratchet trim is triggered for YES position when price >80c and size >1."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a YES position with 3 contracts
        position = Position(
            position_id="test-trim-yes",
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=3,
            avg_entry_price_cents=30,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        
        monitor.add_position(position)
        
        # Mock profile to enable trimming
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = True
            mock_adapter.profile.ratchet_trim_threshold_cents = 80
            mock_adapter.profile.ratchet_trim_to_contracts = 1
            mock_adapter.profile.ratchet_mandatory_exit_at_99c = True
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.ratchet_activation_threshold_cents = 85
            mock_adapter.profile.ratchet_floor_offset_cents = 5
            mock_adapter.profile.ratchet_force_exit_on_floor_breach = True
            mock_adapter.profile.ratchet_min_hold_after_activation_sec = 30
            # Mock staged_time_exit as dict with empty stages to avoid Mock iteration error
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate price crossing 80c threshold
            asyncio.run(monitor._legacy_check_position(position, 81, poll_count=1))
            
            # Verify trim logic executed (position size is NOT mutated here; it updates via fill callback)
            assert position.ratchet_trimmed is True, "Position should be marked as trimmed"
            
            # Verify trim intent was emitted with partial close
            assert callback.called, "Callback should have been called for trim"
            call_args = callback.call_args
            assert call_args[0][1] == ExitReason.RATCHET_TRIM  # exit_reason
            assert call_args[0][2] == 81  # exit_price_cents
            assert call_args[0][3] == 2  # contracts_to_close (3 - 1 = 2)
    
    def test_ratchet_trim_triggered_for_no_position(self):
        """Test that ratchet trim is triggered for NO position when own-side price >=80c and size >1."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a NO position with 3 contracts
        position = Position(
            position_id="test-trim-no",
            market_id="KXBTC15M-5678",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=3,
            avg_entry_price_cents=70,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        
        monitor.add_position(position)
        
        # Mock profile to enable trimming
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = True
            mock_adapter.profile.ratchet_trim_threshold_cents = 80
            mock_adapter.profile.ratchet_trim_to_contracts = 1
            mock_adapter.profile.ratchet_mandatory_exit_at_99c = True
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.ratchet_activation_threshold_cents = 85
            mock_adapter.profile.ratchet_floor_offset_cents = 5
            mock_adapter.profile.ratchet_force_exit_on_floor_breach = True
            mock_adapter.profile.ratchet_min_hold_after_activation_sec = 30
            # Mock staged_time_exit as dict with empty stages to avoid Mock iteration error
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate own-side price crossing 80c threshold (side-space fix: NO uses own-side price directly)
            asyncio.run(monitor._legacy_check_position(position, 81, poll_count=1))
            
            # Verify trim logic executed (position size is NOT mutated here; it updates via fill callback)
            assert position.ratchet_trimmed is True, "Position should be marked as trimmed"
            
            # Verify trim intent was emitted with partial close
            assert callback.called, "Callback should have been called for trim"
            call_args = callback.call_args
            assert call_args[0][1] == ExitReason.RATCHET_TRIM  # exit_reason
            assert call_args[0][2] == 81  # exit_price_cents
            assert call_args[0][3] == 2  # contracts_to_close (3 - 1 = 2)
    
    def test_ratchet_trim_not_triggered_when_size_equals_trim_target(self):
        """Test that trim is not triggered when position size already equals trim target."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a YES position with 1 contract (already at trim target)
        position = Position(
            position_id="test-no-trim",
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=30,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        
        monitor.add_position(position)
        
        # Mock profile to enable trimming
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = True
            mock_adapter.profile.ratchet_trim_threshold_cents = 80
            mock_adapter.profile.ratchet_trim_to_contracts = 1
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.ratchet_activation_threshold_cents = 85
            mock_adapter.profile.ratchet_floor_offset_cents = 5
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate price crossing 80c threshold
            asyncio.run(monitor._legacy_check_position(position, 81, poll_count=1))
            
            # Verify trim intent was NOT emitted
            assert not callback.called
            assert position.size == 1
            assert position.ratchet_trimmed is False
    
    def test_ratchet_trim_not_triggered_when_price_below_threshold(self):
        """Test that trim is not triggered when price is below threshold."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a YES position with 3 contracts
        position = Position(
            position_id="test-below-threshold",
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=3,
            avg_entry_price_cents=30,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        
        monitor.add_position(position)
        
        # Mock profile to enable trimming
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = True
            mock_adapter.profile.ratchet_trim_threshold_cents = 80
            mock_adapter.profile.ratchet_trim_to_contracts = 1
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.ratchet_activation_threshold_cents = 85
            mock_adapter.profile.ratchet_floor_offset_cents = 5
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate price below threshold
            asyncio.run(monitor._legacy_check_position(position, 75, poll_count=1))
            
            # Verify trim intent was NOT emitted
            assert not callback.called
            assert position.size == 3
            assert position.ratchet_trimmed is False
    
    def test_ratchet_trim_not_triggered_when_already_trimmed(self):
        """Test that trim is not triggered again after position has already been trimmed."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a YES position with 3 contracts, already marked as trimmed
        position = Position(
            position_id="test-already-trimmed",
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=3,
            avg_entry_price_cents=30,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        position.ratchet_trimmed = True
        
        monitor.add_position(position)
        
        # Mock profile to enable trimming
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = True
            mock_adapter.profile.ratchet_trim_threshold_cents = 80
            mock_adapter.profile.ratchet_trim_to_contracts = 1
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.ratchet_activation_threshold_cents = 85
            mock_adapter.profile.ratchet_floor_offset_cents = 5
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate price crossing 80c threshold
            asyncio.run(monitor._legacy_check_position(position, 81, poll_count=1))
            
            # Verify trim intent was NOT emitted (already trimmed)
            assert not callback.called
            assert position.size == 3  # Size unchanged
            assert position.ratchet_trimmed is True
    
    def test_ratchet_trim_not_triggered_when_disabled(self):
        """Test that trim is not triggered when trim is disabled in profile."""
        monitor = PositionMonitor()
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Create a YES position with 3 contracts
        position = Position(
            position_id="test-disabled",
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=3,
            avg_entry_price_cents=30,
            take_profit_price_cents=99,
            stop_loss_price_cents=1,
        )
        
        monitor.add_position(position)
        
        # Mock profile with trimming disabled
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_profile:
            mock_adapter = Mock()
            mock_profile.return_value = mock_adapter
            mock_adapter.profile.ratchet_profit_floor_enabled = True
            mock_adapter.profile.ratchet_trim_position_enabled = False  # Disabled
            mock_adapter.profile.trailing_stop_min_profit_cents = 12  # Add missing attribute
            mock_adapter.profile.staged_time_exit = {"enabled": False, "stages": []}
            
            # Simulate price crossing 80c threshold
            asyncio.run(monitor._legacy_check_position(position, 81, poll_count=1))
            
            # Verify trim intent was NOT emitted
            assert not callback.called
            assert position.size == 3
            assert position.ratchet_trimmed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
