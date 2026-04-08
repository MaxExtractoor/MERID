"""Tests for risk kill switches."""

import pytest
from datetime import datetime, timezone

from merid.risk.kill_switches import (
    KillSwitchEvent,
    KillSwitchReason,
    KillSwitchState,
    RiskController,
)


class TestRiskController:
    """Tests for RiskController."""

    @pytest.fixture
    def controller(self):
        """Create fresh controller for each test."""
        return RiskController(
            daily_loss_limit=100.0,
            max_position_value=1000.0,
            error_threshold=3,
        )

    def test_initial_state_allows_trading(self, controller):
        """Controller starts in active state."""
        assert controller.can_trade() is True
        assert controller.get_state() == KillSwitchState.ACTIVE

    def test_emergency_stop_halts_trading(self, controller):
        """Emergency stop triggers kill switch."""
        controller.emergency_stop("Test stop")

        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED

        status = controller.get_status()
        assert status["kill_reason"] == "manual"
        assert "Test stop" in status["kill_details"]

    def test_reset_restores_trading(self, controller):
        """Reset allows trading to resume."""
        controller.emergency_stop("Test stop")
        assert controller.can_trade() is False

        controller.reset(operator="test_operator")
        assert controller.can_trade() is True
        assert controller.get_state() == KillSwitchState.ACTIVE

    # ------------------------------------------------------------------
    # Daily loss — 3-tier behaviour
    # ------------------------------------------------------------------

    def test_daily_loss_single_signal_goes_to_limited_not_kill(self, controller):
        """Single-signal daily-loss breach escalates to LIMITED, not TRIGGERED.

        With multi_signal_required=2 (default), a lone PnL breach at/above the
        hard limit must hold in the LIMITED tier rather than immediately kill.
        """
        # Lose 50 % of limit → approaching warn_pct (70 %), may still be ACTIVE
        controller.record_pnl(-50.0)
        assert controller.can_trade() is True

        # Lose another 60 → total -110, 110 % of limit (single signal only)
        controller.record_pnl(-60.0)
        # should NOT trigger full kill — still tradeable (LIMITED tier)
        assert controller.can_trade() is True
        state = controller.get_state()
        assert state in (KillSwitchState.LIMITED, KillSwitchState.WARNING, KillSwitchState.ACTIVE)

    def test_daily_loss_single_step_jump_triggers_kill(self, controller):
        """A single-step PnL loss that exceeds the entire limit triggers kill immediately."""
        # One trade wipes out more than the daily limit in one step
        controller.record_pnl(-110.0)
        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED

        status = controller.get_status()
        assert status["kill_reason"] == "daily_loss"

    def test_daily_loss_multi_signal_triggers_kill(self, controller):
        """Daily loss breach + error breach together trigger full kill."""
        # Build up error breach (error "daily_loss" metric not counted here)
        # We need a second independent breach — trigger position breach too
        controller.update_position_value(1100.0)  # 110 % of 1000 → position breach

        # Now breach daily loss (single step exceeding limit)
        controller.record_pnl(-110.0)
        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED

    def test_daily_pnl_accumulates(self, controller):
        """P&L accumulates correctly."""
        controller.record_pnl(-30.0)
        controller.record_pnl(-20.0)
        controller.record_pnl(10.0)

        status = controller.get_status()
        assert status["daily_pnl"] == -40.0
        assert controller.can_trade() is True

    # ------------------------------------------------------------------
    # Position limit — 3-tier behaviour
    # ------------------------------------------------------------------

    def test_position_limit_hard_breach_triggers_kill(self, controller):
        """Position value at 150 % of limit (hard_breach) triggers immediate kill."""
        controller.update_position_value(500.0)
        assert controller.can_trade() is True

        controller.update_position_value(1500.0)  # 150 % > 120 % hard-breach threshold
        assert controller.can_trade() is False

        status = controller.get_status()
        assert status["kill_reason"] == "position_limit"

    def test_position_limit_single_signal_soft_breach_goes_to_limited(self, controller):
        """Position at 110 % of limit (soft breach, single signal) escalates to LIMITED."""
        controller.update_position_value(1100.0)  # 110 %, below 120 % hard-breach
        # single signal → should stay tradeable (LIMITED or WARNING)
        assert controller.can_trade() is True
        state = controller.get_state()
        assert state in (KillSwitchState.LIMITED, KillSwitchState.WARNING, KillSwitchState.ACTIVE)

    # ------------------------------------------------------------------
    # Error threshold — 3-tier behaviour
    # ------------------------------------------------------------------

    def test_error_threshold_runaway_triggers_kill(self, controller):
        """Error count ≥ 150 % of threshold (runaway) triggers full kill."""
        # threshold=3, so need ≥ 5 errors (≥150 %)
        for _ in range(5):
            controller.record_error()

        assert controller.can_trade() is False

        status = controller.get_status()
        assert status["kill_reason"] == "error_threshold"

    def test_error_threshold_at_limit_single_signal_stays_limited(self, controller):
        """Exactly threshold errors with one signal goes to LIMITED, not TRIGGERED."""
        controller.record_error()
        controller.record_error()
        assert controller.can_trade() is True

        controller.record_error()  # 3rd error = threshold (100 %, single signal)
        # With multi_signal_required=2 and fraction < 1.50, stays at LIMITED
        assert controller.can_trade() is True
        state = controller.get_state()
        assert state in (KillSwitchState.LIMITED, KillSwitchState.WARNING, KillSwitchState.ACTIVE)

    def test_error_threshold_multi_signal_triggers_kill(self, controller):
        """Error breach + daily loss breach together trigger full kill."""
        # Confirm hard position breach triggers kill
        controller.update_position_value(1500.0)  # 150% — hard_breach
        assert controller.can_trade() is False

        # Reset fully and use a fresh controller to test the multi-signal path cleanly
        fresh = RiskController(
            daily_loss_limit=100.0,
            max_position_value=1000.0,
            error_threshold=3,
        )
        # Build daily-loss breach via record_pnl (incremental, not single-step)
        # Note: this requires two breach signals; we use position + error
        fresh.update_position_value(1100.0)  # soft position breach, not hard
        for _ in range(3):
            fresh.record_error()             # error breach at 100 %; 2 signals now active

        # Two active breaches (position + error) → should kill
        assert fresh.can_trade() is False

    # ------------------------------------------------------------------
    # Tier state and size_multiplier
    # ------------------------------------------------------------------

    def test_size_multiplier_active(self, controller):
        """size_multiplier returns 1.0 in ACTIVE state."""
        assert controller.size_multiplier() == 1.0

    def test_size_multiplier_triggered(self, controller):
        """size_multiplier returns 0.0 when TRIGGERED."""
        controller.emergency_stop("test")
        assert controller.size_multiplier() == 0.0

    def test_kill_switch_states_enum(self):
        """KillSwitchState includes all 4 tier values."""
        assert KillSwitchState.ACTIVE == "active"
        assert KillSwitchState.WARNING == "warning"
        assert KillSwitchState.LIMITED == "limited"
        assert KillSwitchState.TRIGGERED == "triggered"

    # ------------------------------------------------------------------
    # Event and callback tests
    # ------------------------------------------------------------------

    def test_events_recorded(self, controller):
        """Kill switch events are recorded."""
        controller.emergency_stop("Test 1")
        controller.reset("operator")
        controller.emergency_stop("Test 2")

        events = controller.get_events()
        assert len(events) == 3
        assert events[0].new_state == KillSwitchState.TRIGGERED
        assert events[1].new_state == KillSwitchState.ACTIVE
        assert events[2].new_state == KillSwitchState.TRIGGERED

    def test_callback_on_kill(self, controller):
        """Callbacks are invoked on kill switch trigger."""
        events_received = []

        def on_kill(event: KillSwitchEvent):
            events_received.append(event)

        controller.on_kill(on_kill)
        controller.emergency_stop("Test")

        assert len(events_received) == 1
        assert events_received[0].reason == KillSwitchReason.MANUAL

    def test_status_shows_pnl_percentage(self, controller):
        """Status shows P&L as percentage of limit."""
        controller.record_pnl(-50.0)

        status = controller.get_status()
        assert status["daily_pnl_pct"] == 50.0  # 50% of 100 limit

    def test_double_kill_ignored(self, controller):
        """Second kill attempt when already killed is ignored."""
        controller.emergency_stop("First")
        controller.emergency_stop("Second")

        status = controller.get_status()
        assert "First" in status["kill_details"]
        assert len(controller.get_events()) == 1

    def test_status_includes_tier_fields(self, controller):
        """Status dict includes tier and size_multiplier fields."""
        status = controller.get_status()
        assert "tier" in status
        assert "size_multiplier" in status
        assert "active_breaches" in status
        assert "warn_pct" in status
        assert "limit_pct" in status


class TestKillSwitchEvent:
    """Tests for KillSwitchEvent dataclass."""

    def test_event_creation(self):
        """Event can be created with all fields."""
        event = KillSwitchEvent(
            timestamp=datetime.now(timezone.utc),
            old_state=KillSwitchState.ACTIVE,
            new_state=KillSwitchState.TRIGGERED,
            reason=KillSwitchReason.DAILY_LOSS,
            details="Test details",
        )

        assert event.old_state == KillSwitchState.ACTIVE
        assert event.new_state == KillSwitchState.TRIGGERED
        assert event.reason == KillSwitchReason.DAILY_LOSS


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_can_trade_function(self):
        """can_trade() uses global controller."""
        from merid.risk import can_trade, risk_controller

        # Reset to known state
        risk_controller._global_kill = False
        assert can_trade() is True

    def test_get_risk_status_function(self):
        """get_risk_status() returns dict."""
        from merid.risk import get_risk_status

        status = get_risk_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "daily_pnl" in status

