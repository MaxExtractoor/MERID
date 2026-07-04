"""Unit tests for ratchet profit floor mechanism.

This tests the research-backed profit locking mechanism that:
- Activates when price reaches a high threshold (e.g., 85¢)
- Sets a hard floor (e.g., 80¢) that never lowers
- Forces exit if price drops to the floor
- Prevents giving back significant gains when 99¢ TP is not guaranteed
"""

import pytest
from datetime import datetime, timezone
from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitPlan


class TestRatchetProfitFloor:
    """Test suite for ratchet profit floor mechanism."""
    
    def test_ratchet_activation_long(self):
        """Test ratchet activation for LONG (YES) positions."""
        engine = DynamicTakeProfitEngine()
        
        # Create a plan with ratchet enabled
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=True,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        # Should activate when price >= 85
        assert engine.should_activate_ratchet(84, "LONG", plan) is False
        assert engine.should_activate_ratchet(85, "LONG", plan) is True
        assert engine.should_activate_ratchet(90, "LONG", plan) is True
    
    def test_ratchet_activation_short(self):
        """Test ratchet activation for SHORT (NO) positions."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=15,  # For NO, lower is better
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=True,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        # For NO: activate when price <= threshold (lower is better)
        assert engine.should_activate_ratchet(16, "SHORT", plan) is False
        assert engine.should_activate_ratchet(15, "SHORT", plan) is True
        assert engine.should_activate_ratchet(10, "SHORT", plan) is True
    
    def test_ratchet_disabled(self):
        """Test that ratchet is not activated when disabled."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=False,  # Disabled
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        # Should never activate when disabled
        assert engine.should_activate_ratchet(90, "LONG", plan) is False
        assert engine.should_activate_ratchet(95, "LONG", plan) is False
    
    def test_ratchet_floor_computation(self):
        """Test ratchet floor price computation."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        # Floor = activation_price - offset
        assert engine.compute_ratchet_floor(85, plan, "LONG") == 80
        assert engine.compute_ratchet_floor(90, plan, "LONG") == 85
        assert engine.compute_ratchet_floor(87, plan, "LONG") == 82
    
    def test_ratchet_floor_clamping(self):
        """Test that ratchet floor is clamped to valid Kalshi range [1, 99]."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=100,  # Large offset
        )
        
        # Floor should be clamped to minimum 1
        assert engine.compute_ratchet_floor(5, plan, "LONG") == 1
        
        plan2 = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        # Floor should be clamped to maximum 99
        # 99 - 5 = 94, which is within [1, 99] range, so no clamping needed
        assert engine.compute_ratchet_floor(99, plan2, "LONG") == 94
    
    def test_ratchet_exit_long(self):
        """Test ratchet exit condition for LONG positions."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
        )
        
        floor_price = 80
        
        # Should exit when price drops to or below floor
        assert engine.should_exit_on_ratchet_floor(81, floor_price, "LONG") is False
        assert engine.should_exit_on_ratchet_floor(80, floor_price, "LONG") is True
        assert engine.should_exit_on_ratchet_floor(79, floor_price, "LONG") is True
    
    def test_ratchet_exit_short(self):
        """Test ratchet exit condition for SHORT positions."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
        )
        
        floor_price = 20
        
        # For NO: exit when price rises to or above floor
        assert engine.should_exit_on_ratchet_floor(19, floor_price, "SHORT") is False
        assert engine.should_exit_on_ratchet_floor(20, floor_price, "SHORT") is True
        assert engine.should_exit_on_ratchet_floor(21, floor_price, "SHORT") is True
    
    def test_ratchet_min_hold_time(self):
        """Test that ratchet exit respects minimum hold time."""
        import time
        
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        floor_price = 80
        activation_ts = time.time()  # Just activated
        
        # Should not exit immediately due to min hold time
        assert engine.should_exit_on_ratchet_floor(
            79, floor_price, "LONG", activation_ts, min_hold_seconds=30
        ) is False
        
        # Should exit after min hold time
        old_activation_ts = time.time() - 60  # 60 seconds ago
        assert engine.should_exit_on_ratchet_floor(
            79, floor_price, "LONG", old_activation_ts, min_hold_seconds=30
        ) is True
    
    def test_ratchet_no_activation_timestamp(self):
        """Test that ratchet exit works without activation timestamp (no min hold)."""
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
        )
        
        floor_price = 80
        
        # Should exit immediately when no activation timestamp provided
        assert engine.should_exit_on_ratchet_floor(
            79, floor_price, "LONG", activation_timestamp=None, min_hold_seconds=30
        ) is True
    
    def test_ratchet_integration_with_compute_tp(self):
        """Test that ratchet parameters are passed through compute_tp."""
        engine = DynamicTakeProfitEngine()
        
        plan = engine.compute_tp(
            entry_price=0.50,
            stop_price=0.45,
            direction="LONG",
            confidence=0.75,
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=True,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        # Verify ratchet parameters are in the plan
        assert plan.ratchet_enabled is True
        assert plan.ratchet_activation_threshold_cents == 85
        assert plan.ratchet_floor_offset_cents == 5
        assert plan.ratchet_force_exit_on_breach is True
        assert plan.ratchet_min_hold_after_activation_sec == 30
    
    def test_ratchet_plan_to_dict(self):
        """Test that ratchet parameters are serialized in to_dict()."""
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=True,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        plan_dict = plan.to_dict()
        
        # Verify ratchet parameters are in the dict
        assert plan_dict["ratchet_enabled"] is True
        assert plan_dict["ratchet_activation_threshold_cents"] == 85
        assert plan_dict["ratchet_floor_offset_cents"] == 5
        assert plan_dict["ratchet_force_exit_on_breach"] is True
        assert plan_dict["ratchet_min_hold_after_activation_sec"] == 30
    
    def test_ratchet_disabled_in_plan(self):
        """Test that ratchet can be disabled in TakeProfitPlan."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=False,  # Disabled
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        assert plan.ratchet_enabled is False
        assert engine.should_activate_ratchet(90, "LONG", plan) is False
    
    def test_ratchet_floor_at_boundary(self):
        """Test ratchet floor behavior at exact boundary."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        floor_price = 80
        
        # At exact floor should trigger exit
        assert engine.should_exit_on_ratchet_floor(80, floor_price, "LONG") is True
        # One cent above should not
        assert engine.should_exit_on_ratchet_floor(81, floor_price, "LONG") is False
    
    def test_ratchet_custom_thresholds(self):
        """Test ratchet with custom activation thresholds."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=90,  # Higher threshold
            ratchet_floor_offset_cents=10,  # Larger offset
        )
        
        # Should not activate at 85c (below 90c threshold)
        assert engine.should_activate_ratchet(85, "LONG", plan) is False
        # Should activate at 90c
        assert engine.should_activate_ratchet(90, "LONG", plan) is True
        # Floor should be 80c (90 - 10)
        assert engine.compute_ratchet_floor(90, plan, "LONG") == 80
    
    def test_ratchet_zero_floor_offset(self):
        """Test ratchet with zero floor offset (floor = activation price)."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=0,  # No offset
        )
        
        # Floor should equal activation price
        assert engine.compute_ratchet_floor(85, plan, "LONG") == 85
        assert engine.compute_ratchet_floor(90, plan, "LONG") == 90
    
    def test_ratchet_large_floor_offset(self):
        """Test ratchet with large floor offset."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=20,  # Large offset
        )
        
        # Floor should be clamped to minimum 1
        assert engine.compute_ratchet_floor(15, plan, "LONG") == 1
        # Normal case
        assert engine.compute_ratchet_floor(85, plan, "LONG") == 65
    
    def test_ratchet_min_hold_exact(self):
        """Test ratchet min hold time at exact boundary."""
        import time
        engine = DynamicTakeProfitEngine()
        
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        floor_price = 80
        activation_ts = time.time() - 30  # Exactly 30 seconds ago
        
        # Should exit at exact boundary
        assert engine.should_exit_on_ratchet_floor(
            79, floor_price, "LONG", activation_ts, min_hold_seconds=30
        ) is True
    
    def test_ratchet_short_high_threshold(self):
        """Test ratchet for SHORT with high activation threshold."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=50,  # For NO, lower is better
            ratchet_floor_offset_cents=5,
        )
        
        # For NO: activate when price <= threshold
        assert engine.should_activate_ratchet(51, "SHORT", plan) is False
        assert engine.should_activate_ratchet(50, "SHORT", plan) is True
        assert engine.should_activate_ratchet(45, "SHORT", plan) is True
        
        # Floor should be 55 (50 + 5 offset for NO)
        assert engine.compute_ratchet_floor(50, plan, "SHORT") == 55
    
    def test_ratchet_force_exit_disabled(self):
        """Test ratchet when force_exit_on_breach is disabled."""
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=False,  # Disabled
        )
        
        floor_price = 80
        
        # Should still detect floor breach
        should_exit = engine.should_exit_on_ratchet_floor(79, floor_price, "LONG")
        assert should_exit is True
        # But plan indicates force exit is disabled
        assert plan.ratchet_force_exit_on_breach is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
