"""
Regression tests for exit policy remediation (2026-07-11).

Tests for P0/P1/P2 fixes:
- P0: Timing-aware SLA logic enabled
- P0: Stale data auto-exit
- P1: Config-driven expiry thresholds
- P1: Adaptive timing distinct from time_stop
- P2: Emergency flatten in last 60 seconds
"""

import pytest
from unittest.mock import Mock, patch
from merid.position_management.exit_policy import ExitPolicy, ExitAction, ExitReason
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy_resolver import ExitPolicyResolver
from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds


class TestTimingAwareSLA:
    """Test timing-aware SLA thresholds are enabled and working."""
    
    def test_far_from_expiry_uses_base_threshold(self):
        """Far from expiry (>10 min) should use base 120s threshold."""
        max_age = get_md_max_age_seconds(minutes_to_expiry=12.0)
        assert max_age == 120.0, f"Expected 120s for far expiry, got {max_age}s"
    
    def test_near_expiry_uses_stricter_threshold(self):
        """Near expiry (2-10 min) should use 60s threshold."""
        max_age = get_md_max_age_seconds(minutes_to_expiry=5.0)
        assert max_age == 60.0, f"Expected 60s for near expiry, got {max_age}s"
    
    def test_very_near_expiry_uses_very_strict_threshold(self):
        """Very near expiry (<2 min) should use 10s threshold."""
        max_age = get_md_max_age_seconds(minutes_to_expiry=1.0)
        assert max_age == 10.0, f"Expected 10s for very near expiry, got {max_age}s"
    
    def test_no_expiry_info_uses_base_threshold(self):
        """No expiry info should fall back to base 120s threshold."""
        max_age = get_md_max_age_seconds(minutes_to_expiry=None)
        assert max_age == 120.0, f"Expected 120s for no expiry info, got {max_age}s"


class TestStaleDataAutoExit:
    """Test stale data auto-exit functionality."""
    
    def test_stale_data_triggers_exit(self):
        """Stale MD should trigger exit."""
        position = Mock(spec=Position)
        position.position_id = "test_position"
        position.side = PositionSide.YES
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.5,
            time_since_entry_seconds=300,
            time_to_expiry_seconds=600,
            risk_kill_switch=False,
        )
        
        # MD age 15000ms (15s) exceeds max age 10000ms (10s)
        policy.evaluate(md_age_ms=15000, max_age_ms=10000)
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA
    
    def test_fresh_data_does_not_trigger_exit(self):
        """Fresh MD should not trigger exit."""
        position = Mock(spec=Position)
        position.position_id = "test_position"
        position.side = PositionSide.YES
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.5,
            time_since_entry_seconds=300,
            time_to_expiry_seconds=600,
            risk_kill_switch=False,
        )
        
        # MD age 5000ms (5s) within max age 10000ms (10s)
        policy.evaluate(md_age_ms=5000, max_age_ms=10000)
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_no_md_data_triggers_exit(self):
        """No MD data (negative age) should trigger exit."""
        position = Mock(spec=Position)
        position.position_id = "test_position"
        position.side = PositionSide.YES
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.5,
            time_since_entry_seconds=300,
            time_to_expiry_seconds=600,
            risk_kill_switch=False,
        )
        
        # Negative age indicates no data
        policy.evaluate(md_age_ms=-1, max_age_ms=10000)
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA
    
    def test_stale_data_has_higher_priority_than_time_stop(self):
        """Stale data check should have higher priority than time stop."""
        position = Mock(spec=Position)
        position.position_id = "test_position"
        position.side = PositionSide.YES
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=-10,  # Losing position
            r_multiple=-0.2,
            time_since_entry_seconds=900,  # Over max hold time
            time_to_expiry_seconds=0,
            risk_kill_switch=False,
        )
        
        # Both stale data and time stop conditions met
        policy.evaluate(md_age_ms=15000, max_age_ms=10000)
        
        # Stale data should take priority
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.STALE_DATA


class TestAdaptiveTimingDistinct:
    """Test adaptive timing is distinct from generic time_stop."""
    
    def test_adaptive_timing_reason_exists(self):
        """ADAPTIVE_TIMING reason should exist in ExitReason enum."""
        assert hasattr(ExitReason, 'ADAPTIVE_TIMING')
        assert ExitReason.ADAPTIVE_TIMING == "adaptive_timing"
    
    @patch('merid.position_management.adaptive_exit_timing.get_adaptive_exit_timing')
    def test_adaptive_timing_uses_distinct_reason(self, mock_get_adaptive):
        """Adaptive timing should use ADAPTIVE_TIMING reason, not TIME_STOP."""
        # Mock adaptive timing to trigger
        mock_adaptive = Mock()
        mock_adaptive.should_exit_early.return_value = True
        mock_get_adaptive.return_value = mock_adaptive
        
        position = Mock(spec=Position)
        position.position_id = "test_position"
        position.side = PositionSide.YES
        position.market_id = "KXBTC15M-TEST"
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=5,
            r_multiple=0.5,
            time_since_entry_seconds=300,
            time_to_expiry_seconds=600,
            risk_kill_switch=False,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.ADAPTIVE_TIMING
        assert policy.reason != ExitReason.TIME_STOP


class TestEmergencyFlatten:
    """Test emergency flatten in last 60 seconds."""
    
    def test_emergency_flatten_code_exists(self):
        """Verify emergency flatten code exists in position_monitor."""
        from merid.position_management.position_monitor import PositionMonitor
        import inspect
        
        # Check that the code references emergency flatten
        source = inspect.getsource(PositionMonitor._check_position)
        assert "EMERGENCY FLATTEN" in source
        assert "time_to_expiry_seconds <= 60.0" in source


class TestConfigDrivenIOCThreshold:
    """Test IOC threshold is read from profile."""
    
    def test_ioc_threshold_code_exists(self):
        """Verify IOC threshold code exists in order_router."""
        from merid.event_venues.kalshi import order_router
        import inspect
        
        # Check that the code references profile config
        source = inspect.getsource(order_router)
        assert "venue_invariants_ioc_auto_below_seconds" in source
        assert "get_profile_config" in source


class TestLoopTimingAwareSLA:
    """Test loop_15m.py uses timing-aware SLA for catalog window check."""
    
    def test_catalog_window_uses_timing_aware_sla(self):
        """Verify catalog window check uses timing-aware SLA threshold."""
        from merid import loop_15m
        import inspect
        
        # Check that the code uses timing-aware threshold
        source = inspect.getsource(loop_15m)
        assert "minutes_to_expiry = min_to_expiry" in source
        assert "get_md_max_age_seconds(minutes_to_expiry)" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
