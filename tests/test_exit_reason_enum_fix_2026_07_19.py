"""
Test for ExitReason enum completeness fix (2026-07-19).

This test verifies that all ExitReason values used by position_monitor.py
are present in the ExitReason enum and have proper priority mappings.

Root cause: position_monitor.py was using ExitReason.STOP_LOSS and other
position-level exits, but the ExitReason enum only contained policy-layer exits.
This caused AttributeError during position monitoring.

Fix: Added position-level exit reasons (STOP_LOSS, TAKE_PROFIT, TRAIL, etc.)
to the ExitReason enum in merid/position_management/exit_policy.py and
updated the priority mapping in exit_decision.py.
"""

import pytest
from merid.position_management.exit_policy import ExitReason
from merid.position_management.exit_decision import (
    ExitPriority,
    get_priority_for_reason,
)


class TestExitReasonEnumCompleteness:
    """Test that ExitReason enum contains all required exit reasons."""
    
    def test_position_level_exits_exist(self):
        """Test that position-level exit reasons exist in enum."""
        # These are used by position_monitor.py
        assert hasattr(ExitReason, 'STOP_LOSS')
        assert hasattr(ExitReason, 'TAKE_PROFIT')
        assert hasattr(ExitReason, 'TRAIL')
        assert hasattr(ExitReason, 'EXTREME_PROFIT')
        assert hasattr(ExitReason, 'DYNAMIC_TAKE_PROFIT')
        assert hasattr(ExitReason, 'RATCHET_TRIM')
        assert hasattr(ExitReason, 'RATCHET_FLOOR')
    
    def test_policy_layer_exits_exist(self):
        """Test that policy-layer exit reasons exist in enum."""
        assert hasattr(ExitReason, 'RISK')
        assert hasattr(ExitReason, 'STALE_DATA')
        assert hasattr(ExitReason, 'CANDLE_REVERSAL')
        assert hasattr(ExitReason, 'ADAPTIVE_TIMING')
        assert hasattr(ExitReason, 'TIME_STOP')
        assert hasattr(ExitReason, 'EDGE_DECAY')
    
    def test_other_exits_exist(self):
        """Test that other exit reasons exist in enum."""
        assert hasattr(ExitReason, 'SCALE_OUT')
        assert hasattr(ExitReason, 'MANUAL')
    
    def test_exit_reason_values_are_strings(self):
        """Test that all ExitReason values are strings (str enum)."""
        for reason in ExitReason:
            assert isinstance(reason.value, str)
    
    def test_exit_reason_values_are_lowercase(self):
        """Test that all ExitReason values are lowercase (snake_case)."""
        for reason in ExitReason:
            assert reason.value == reason.value.lower()
            assert ' ' not in reason.value  # No spaces


class TestExitPriorityMapping:
    """Test that all ExitReason values have proper priority mappings."""
    
    def test_position_level_priorities_mapped(self):
        """Test that position-level exits have priority mappings."""
        assert get_priority_for_reason(ExitReason.STOP_LOSS) == ExitPriority.STOP_LOSS
        assert get_priority_for_reason(ExitReason.TAKE_PROFIT) == ExitPriority.TAKE_PROFIT
        assert get_priority_for_reason(ExitReason.TRAIL) == ExitPriority.TRAIL
        assert get_priority_for_reason(ExitReason.EXTREME_PROFIT) == ExitPriority.EXTREME_PROFIT
        assert get_priority_for_reason(ExitReason.DYNAMIC_TAKE_PROFIT) == ExitPriority.DYNAMIC_TAKE_PROFIT
        assert get_priority_for_reason(ExitReason.RATCHET_TRIM) == ExitPriority.RATCHET_TRIM
        assert get_priority_for_reason(ExitReason.RATCHET_FLOOR) == ExitPriority.RATCHET_FLOOR
    
    def test_policy_layer_priorities_mapped(self):
        """Test that policy-layer exits have priority mappings."""
        assert get_priority_for_reason(ExitReason.RISK) == ExitPriority.RISK
        assert get_priority_for_reason(ExitReason.STALE_DATA) == ExitPriority.STALE_DATA
        assert get_priority_for_reason(ExitReason.CANDLE_REVERSAL) == ExitPriority.CANDLE_REVERSAL
        assert get_priority_for_reason(ExitReason.ADAPTIVE_TIMING) == ExitPriority.ADAPTIVE_TIMING
        assert get_priority_for_reason(ExitReason.TIME_STOP) == ExitPriority.TIME_STOP
        assert get_priority_for_reason(ExitReason.EDGE_DECAY) == ExitPriority.EDGE_DECAY
    
    def test_other_priorities_mapped(self):
        """Test that other exits have priority mappings."""
        assert get_priority_for_reason(ExitReason.SCALE_OUT) == ExitPriority.SCALE_OUT
        assert get_priority_for_reason(ExitReason.MANUAL) == ExitPriority.MANUAL
    
    def test_all_exit_reasons_have_priority_mapping(self):
        """Test that every ExitReason has a priority mapping."""
        for reason in ExitReason:
            priority = get_priority_for_reason(reason)
            assert priority is not None
            assert isinstance(priority, ExitPriority)


class TestExitPrecedenceOrder:
    """Test that exit precedence order is correct."""
    
    def test_risk_has_highest_priority(self):
        """Test that RISK has the highest priority (100)."""
        assert ExitPriority.RISK.value == 100
        assert ExitPriority.RISK.value > ExitPriority.EXTREME_PROFIT.value
    
    def test_extreme_profit_has_second_highest(self):
        """Test that EXTREME_PROFIT has second highest priority (90)."""
        assert ExitPriority.EXTREME_PROFIT.value == 90
        assert ExitPriority.EXTREME_PROFIT.value > ExitPriority.STALE_DATA.value
    
    def test_stale_data_has_high_priority(self):
        """Test that STALE_DATA has high priority (85)."""
        assert ExitPriority.STALE_DATA.value == 85
        assert ExitPriority.STALE_DATA.value > ExitPriority.DYNAMIC_TAKE_PROFIT.value
    
    def test_stop_loss_priority(self):
        """Test that STOP_LOSS has priority 60."""
        assert ExitPriority.STOP_LOSS.value == 60
        assert ExitPriority.STOP_LOSS.value > ExitPriority.TAKE_PROFIT.value
    
    def test_take_profit_priority(self):
        """Test that TAKE_PROFIT has priority 55."""
        assert ExitPriority.TAKE_PROFIT.value == 55
        assert ExitPriority.TAKE_PROFIT.value > ExitPriority.CANDLE_REVERSAL.value
    
    def test_trail_priority(self):
        """Test that TRAIL has priority 25."""
        assert ExitPriority.TRAIL.value == 25
        assert ExitPriority.TRAIL.value > ExitPriority.MANUAL.value
    
    def test_manual_has_lowest_priority(self):
        """Test that MANUAL has the lowest priority (20)."""
        assert ExitPriority.MANUAL.value == 20
        # Should be lower than all others
        for priority in ExitPriority:
            if priority != ExitPriority.MANUAL:
                assert priority.value > ExitPriority.MANUAL.value


class TestExitReasonSynchronization:
    """Test that ExitReason enums are synchronized across modules."""
    
    def test_exit_feedback_handler_synchronized(self):
        """Test that exit_feedback_handler.ExitReason is synchronized."""
        from merid.position_management.exit_feedback_handler import ExitReason as FeedbackExitReason
        
        # Check that key values match
        assert FeedbackExitReason.STOP_LOSS.value == ExitReason.STOP_LOSS.value
        assert FeedbackExitReason.TAKE_PROFIT.value == ExitReason.TAKE_PROFIT.value
        assert FeedbackExitReason.TRAIL.value == ExitReason.TRAIL.value
        assert FeedbackExitReason.RISK.value == ExitReason.RISK.value
        assert FeedbackExitReason.TIME_STOP.value == ExitReason.TIME_STOP.value
        assert FeedbackExitReason.EDGE_DECAY.value == ExitReason.EDGE_DECAY.value
        assert FeedbackExitReason.STALE_DATA.value == ExitReason.STALE_DATA.value
        assert FeedbackExitReason.MANUAL.value == ExitReason.MANUAL.value
    
    def test_unified_exit_policy_engine_synchronized(self):
        """Test that unified_exit_policy_engine.ExitReason is synchronized."""
        from merid.position_management.unified_exit_policy_engine import ExitReason as UnifiedExitReason
        
        # Check that key values match
        assert UnifiedExitReason.STOP_LOSS.value == ExitReason.STOP_LOSS.value
        assert UnifiedExitReason.TAKE_PROFIT.value == ExitReason.TAKE_PROFIT.value
        assert UnifiedExitReason.TRAIL.value == ExitReason.TRAIL.value
        assert UnifiedExitReason.RISK.value == ExitReason.RISK.value
        assert UnifiedExitReason.TIME_STOP.value == ExitReason.TIME_STOP.value
        assert UnifiedExitReason.EDGE_DECAY.value == ExitReason.EDGE_DECAY.value
        assert UnifiedExitReason.STALE_DATA.value == ExitReason.STALE_DATA.value
        assert UnifiedExitReason.MANUAL.value == ExitReason.MANUAL.value
    
    def test_risk_exit_policy_synchronized(self):
        """Test that risk.exit_policy.ExitReason is synchronized."""
        from merid.risk.exit_policy import ExitReason as RiskExitReason
        
        # Check that key values match
        assert RiskExitReason.STOP_LOSS.value == ExitReason.STOP_LOSS.value
        assert RiskExitReason.TAKE_PROFIT.value == ExitReason.TAKE_PROFIT.value
        assert RiskExitReason.RISK.value == ExitReason.RISK.value
        assert RiskExitReason.TIME_STOP.value == ExitReason.TIME_STOP.value
        assert RiskExitReason.EDGE_DECAY.value == ExitReason.EDGE_DECAY.value
        assert RiskExitReason.STALE_DATA.value == ExitReason.STALE_DATA.value
        assert RiskExitReason.MANUAL.value == ExitReason.MANUAL.value
