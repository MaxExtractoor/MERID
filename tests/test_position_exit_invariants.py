"""
Position State and Exit Invariants Test Harness

Tests that the position exit manager enforces:
1. Position state invariant: exactly one active exit plan per position
2. Exit sizing invariant: position-based sizing, not bankroll-based
3. Exit trigger invariants: TP/SL/trailing assigned correctly
4. Exit vs settlement invariant: positions end in active exit or settlement

Usage:
    pytest tests/test_position_exit_invariants.py
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

try:
    from merid.prediction.position_exit_invariants import (
        PositionExitManager,
        ExitPlanType,
        ExitPlanStatus,
        PositionExitState,
        ExitPlan,
        validate_position_state_invariant,
        validate_exit_sizing_invariant,
    )
except ImportError:
    pytest.skip("Required modules not available")


class TestPositionStateInvariant:
    """Test suite for position state invariant."""
    
    def test_exactly_one_active_exit_plan(self):
        """Test that a position can have exactly one active exit plan."""
        manager = PositionExitManager(max_exit_plans_per_position=1)
        
        # Create position
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add first exit plan (should succeed)
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.0,
            reason="Test TP",
        )
        assert success, f"First exit plan should succeed: {error}"
        
        # Try to add second exit plan (should fail)
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.STOP_LOSS,
            trigger_price_cents=25.0,
            size_fraction=1.0,
            reason="Test SL",
        )
        assert not success, "Second exit plan should fail"
        assert "already has" in error.lower()
    
    def test_no_active_exit_plan_violation(self):
        """Test that a position with no active exit plan fails validation."""
        state = PositionExitState(
            position_id="TEST-001",
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
            exit_plans=[],  # No exit plans
        )
        
        is_valid, error = validate_position_state_invariant(state)
        assert not is_valid, "Position with no exit plan should fail validation"
        assert "no active exit plan" in error.lower()
    
    def test_multiple_active_exit_plans_violation(self):
        """Test that multiple active exit plans fail validation."""
        state = PositionExitState(
            position_id="TEST-001",
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
            exit_plans=[
                ExitPlan(plan_type=ExitPlanType.TAKE_PROFIT, status=ExitPlanStatus.ACTIVE),
                ExitPlan(plan_type=ExitPlanType.STOP_LOSS, status=ExitPlanStatus.ACTIVE),
            ],
        )
        
        is_valid, error = validate_position_state_invariant(state)
        assert not is_valid, "Position with multiple active exit plans should fail validation"
        assert "2 active exit plans" in error or "multiple" in error.lower()
    
    def test_cancel_exit_plan(self):
        """Test cancelling an exit plan allows adding a new one."""
        manager = PositionExitManager(max_exit_plans_per_position=1)
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add first exit plan
        manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.0,
        )
        
        # Cancel it
        success, error = manager.cancel_exit_plan(position_id)
        assert success, f"Cancel should succeed: {error}"
        
        # Add new exit plan (should succeed now)
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.STOP_LOSS,
            trigger_price_cents=25.0,
            size_fraction=1.0,
        )
        assert success, f"New exit plan after cancel should succeed: {error}"
    
    def test_trigger_exit_plan(self):
        """Test triggering an exit plan."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add exit plan
        manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.0,
        )
        
        # Trigger it
        success, error = manager.trigger_exit_plan(position_id)
        assert success, f"Trigger should succeed: {error}"
        
        # Verify plan is triggered
        active_plan = state.get_active_exit_plan()
        assert active_plan is None, "No plan should be active after trigger"
        triggered_plans = [p for p in state.exit_plans if p.status == ExitPlanStatus.TRIGGERED]
        assert len(triggered_plans) == 1, "One plan should be triggered"


class TestExitSizingInvariant:
    """Test suite for exit sizing invariant."""
    
    def test_exit_size_from_position_state(self):
        """Test that exit size is computed from position state, not bankroll."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add exit plan with 50% fraction
        manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=0.5,
        )
        
        # Calculate exit size
        exit_size, error = manager.calculate_exit_size(position_id)
        assert exit_size == 5, f"Exit size should be 5 (50% of 10), got {exit_size}"
        assert error is None
    
    def test_exit_size_exceeds_position_size(self):
        """Test that exit size cannot exceed position size."""
        state = PositionExitState(
            position_id="TEST-001",
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Try to exit more than position size
        is_valid, error = validate_exit_sizing_invariant(state, exit_size=15)
        assert not is_valid, "Exit size exceeding position should fail validation"
        assert "exceeds open position size" in error.lower()
    
    def test_exit_size_zero_or_negative(self):
        """Test that exit size must be positive."""
        state = PositionExitState(
            position_id="TEST-001",
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Try zero exit size
        is_valid, error = validate_exit_sizing_invariant(state, exit_size=0)
        assert not is_valid, "Zero exit size should fail validation"
        
        # Try negative exit size
        is_valid, error = validate_exit_sizing_invariant(state, exit_size=-5)
        assert not is_valid, "Negative exit size should fail validation"
    
    def test_full_position_exit(self):
        """Test full position exit (size_fraction=1.0)."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add exit plan with 100% fraction
        manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.0,
        )
        
        # Calculate exit size
        exit_size, error = manager.calculate_exit_size(position_id)
        assert exit_size == 10, f"Full exit should be 10, got {exit_size}"
    
    def test_no_active_plan_defaults_to_full_exit(self):
        """Test that no active plan defaults to full position exit."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # No exit plan added
        exit_size, error = manager.calculate_exit_size(position_id)
        assert exit_size == 10, f"Default to full exit (10), got {exit_size}"
    
    def test_invalid_size_fraction(self):
        """Test that invalid size fractions are rejected."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Try size_fraction > 1.0
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.5,
        )
        assert not success, "size_fraction > 1.0 should fail"
        
        # Try size_fraction <= 0.0
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=0.0,
        )
        assert not success, "size_fraction <= 0.0 should fail"


class TestExitPlanTypes:
    """Test suite for different exit plan types."""
    
    def test_take_profit_plan(self):
        """Test take profit exit plan."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=1.0,
            reason="TP at 75c",
        )
        assert success, f"TP plan should succeed: {error}"
        
        active_plan = state.get_active_exit_plan()
        assert active_plan is not None
        assert active_plan.plan_type == ExitPlanType.TAKE_PROFIT
        assert active_plan.trigger_price_cents == 75.0
    
    def test_stop_loss_plan(self):
        """Test stop loss exit plan."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.STOP_LOSS,
            trigger_price_cents=25.0,
            size_fraction=1.0,
            reason="SL at 25c",
        )
        assert success, f"SL plan should succeed: {error}"
        
        active_plan = state.get_active_exit_plan()
        assert active_plan is not None
        assert active_plan.plan_type == ExitPlanType.STOP_LOSS
        assert active_plan.trigger_price_cents == 25.0
    
    def test_settlement_plan(self):
        """Test settlement exit plan (time-based)."""
        manager = PositionExitManager()
        
        position_id = "TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        trigger_time = datetime.now(timezone.utc) + timedelta(minutes=15)
        success, error = manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.SETTLEMENT,
            trigger_time=trigger_time,
            size_fraction=1.0,
            reason="Settlement at expiry",
        )
        assert success, f"Settlement plan should succeed: {error}"
        
        active_plan = state.get_active_exit_plan()
        assert active_plan is not None
        assert active_plan.plan_type == ExitPlanType.SETTLEMENT
        assert active_plan.trigger_time == trigger_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
