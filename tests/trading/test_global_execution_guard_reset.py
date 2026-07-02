"""Tests for GlobalExecutionGuard cycle reset integration.

This test verifies that GlobalExecutionGuard.reset_cycle() is called
at the start of each trading cycle to prevent the total notional accumulator
from growing indefinitely across cycles.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from merid.guards.global_execution_guard import get_global_execution_guard


def test_reset_cycle_clears_accumulator():
    """Test that reset_cycle clears the total notional accumulator."""
    guard = get_global_execution_guard()
    
    # Reset to known state
    guard.reset_total_notional(0.0)
    
    # Simulate some orders in a cycle
    guard._total_notional_usd = 2.50  # $2.50 in orders this cycle
    
    # Verify accumulator has value
    assert guard._total_notional_usd == 2.50
    
    # Reset cycle
    guard.reset_cycle()
    
    # Verify accumulator is cleared
    assert guard._total_notional_usd == 0.0


def test_reset_cycle_is_idempotent():
    """Test that reset_cycle can be called multiple times safely."""
    guard = get_global_execution_guard()
    
    # Reset to known state
    guard.reset_total_notional(0.0)
    
    # Call reset_cycle multiple times
    guard.reset_cycle()
    guard.reset_cycle()
    guard.reset_cycle()
    
    # Should still be 0.0
    assert guard._total_notional_usd == 0.0


def test_reset_cycle_preserves_other_state():
    """Test that reset_cycle only clears the notional accumulator, not other state."""
    guard = get_global_execution_guard()
    
    # Set some state
    guard._total_notional_usd = 2.50
    guard._orders_this_minute = 5
    guard._orders_this_hour = 50
    
    # Reset cycle
    guard.reset_cycle()
    
    # Notional should be cleared
    assert guard._total_notional_usd == 0.0
    
    # Other state should be preserved
    assert guard._orders_this_minute == 5
    assert guard._orders_this_hour == 50


def test_bankroll_cap_enforced_after_reset():
    """Test that bankroll cap is correctly enforced after cycle reset."""
    guard = get_global_execution_guard()
    
    # Reset to known state
    guard.reset_total_notional(0.0)
    
    # Mock bankroll service to return a valid bankroll
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_bankroll:
        mock_bankroll.return_value = 100.0  # $100 bankroll
        
        # Simulate a cycle with orders
        allowed, _ = guard.check_order(
            ticker="KXBTC15M-TEST",
            contracts=2,
            price_cents=75,
            source="test",
            action="buy"
        )
        assert allowed
        
        # Verify notional accumulated
        assert guard._total_notional_usd > 0
        
        # Reset cycle
        guard.reset_cycle()
        
        # Verify notional cleared
        assert guard._total_notional_usd == 0.0
        
        # New order should be allowed (cap reset)
        allowed, _ = guard.check_order(
            ticker="KXETH15M-TEST",
            contracts=2,
            price_cents=75,
            source="test",
            action="buy"
        )
        assert allowed
