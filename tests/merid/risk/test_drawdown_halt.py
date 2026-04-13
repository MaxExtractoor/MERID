"""Tests for the KalshiRiskManager drawdown halt state machine.

Covers:
- DrawdownHaltState transitions: NORMAL → TRIGGERED → COOLDOWN → NORMAL
- Regression: trigger halt, simulate equity recovery, verify trading resumes
- Kill-switch auto-reset via check_order() (not just record_pnl)
- Integration with central RiskController.record_drawdown_breach()
- Combined halt scenarios: error budget vs drawdown
- Daily reset clears DD state machine

Run:
    python3 -m pytest tests/merid/risk/test_drawdown_halt.py -v
"""

from __future__ import annotations

import time

import pytest

from merid.event_venues.kalshi.kalshi_risk import (
    DrawdownHaltState,
    KalshiRiskConfig,
    KalshiRiskManager,
)
from merid.risk.kill_switches import KillSwitchState, RiskController


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_risk(
    halt_pct: float = 0.10,
    unwind_pct: float = 0.15,
    recovery_buffer_pct: float = 0.02,
    cooldown_secs: float = 0.0,  # 0 for instant recovery in tests
    max_daily_loss_usd: float = 10_000.0,
) -> KalshiRiskManager:
    """Return a fresh KalshiRiskManager with fast/deterministic DD config."""
    cfg = KalshiRiskConfig(
        drawdown_halt_pct=halt_pct,
        drawdown_unwind_pct=unwind_pct,
        drawdown_recovery_buffer_pct=recovery_buffer_pct,
        drawdown_cooldown_secs=cooldown_secs,
        max_daily_loss_usd=max_daily_loss_usd,
    )
    return KalshiRiskManager(config=cfg)


def _set_equity(risk: KalshiRiskManager, peak: float, current: float) -> None:
    """Directly set peak and current equity for test setup."""
    risk._state.peak_equity_usd = peak
    risk._state.current_equity_usd = current


def _check(risk: KalshiRiskManager) -> tuple[bool, str]:
    """Call check_order with minimal args that pass all non-drawdown checks."""
    return risk.check_order(
        ticker="KXBTC-T1",
        category="crypto",
        contracts=1,
        price_cents=50,
    )


# ── Unit: _update_dd_halt_state ───────────────────────────────────────────────


class TestDrawdownStateMachineTransitions:
    """Verify each state transition of the DD state machine."""

    def test_initial_state_is_normal(self):
        risk = _make_risk()
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_normal_to_triggered_when_dd_at_threshold(self):
        """NORMAL → TRIGGERED when drawdown exactly equals halt_pct."""
        risk = _make_risk(halt_pct=0.10)
        _set_equity(risk, peak=1000.0, current=900.0)  # exactly 10% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

    def test_normal_stays_normal_below_threshold(self):
        """State stays NORMAL when drawdown is below the halt threshold."""
        risk = _make_risk(halt_pct=0.10)
        _set_equity(risk, peak=1000.0, current=950.0)  # 5% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_triggered_stays_triggered_above_recovery_threshold(self):
        """State stays TRIGGERED while drawdown is still above recovery threshold."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02)
        # 10% DD → TRIGGERED
        _set_equity(risk, peak=1000.0, current=900.0)
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

        # Partially recover to 9% — still above recovery threshold (10%-2%=8%)
        _set_equity(risk, peak=1000.0, current=910.0)  # 9% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

    def test_triggered_to_cooldown_when_below_recovery_threshold(self):
        """TRIGGERED → COOLDOWN when drawdown falls below halt_pct - buffer."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=60.0)  # non-zero cooldown
        _set_equity(risk, peak=1000.0, current=900.0)  # 10% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

        # Recover to 7% — below recovery threshold (10%-2%=8%)
        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.COOLDOWN

    def test_cooldown_to_normal_when_cooldown_expires(self):
        """COOLDOWN → NORMAL once cooldown_secs have elapsed."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=60.0)
        _set_equity(risk, peak=1000.0, current=900.0)  # 10% DD → TRIGGERED
        risk._update_dd_halt_state()
        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD → COOLDOWN
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.COOLDOWN

        # Backdate the recovery timestamp to simulate elapsed cooldown
        risk._state.dd_recovery_at -= 61.0
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_cooldown_re_triggers_if_dd_exceeds_threshold(self):
        """COOLDOWN → TRIGGERED if drawdown rises back above halt_pct."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=60.0)
        _set_equity(risk, peak=1000.0, current=900.0)
        risk._update_dd_halt_state()  # → TRIGGERED
        _set_equity(risk, peak=1000.0, current=930.0)
        risk._update_dd_halt_state()  # → COOLDOWN

        # Equity deteriorates again
        _set_equity(risk, peak=1000.0, current=895.0)  # 10.5% DD
        risk._update_dd_halt_state()
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

    def test_timestamps_set_on_transition(self):
        """Verify dd_triggered_at and dd_recovery_at are set/cleared correctly."""
        # Use cooldown_secs=60 so COOLDOWN doesn't collapse to NORMAL immediately,
        # giving us a chance to observe dd_recovery_at being set.
        risk = _make_risk(halt_pct=0.10, cooldown_secs=60.0)
        assert risk._state.dd_triggered_at is None
        assert risk._state.dd_recovery_at is None

        _set_equity(risk, peak=1000.0, current=890.0)  # 11% DD → TRIGGERED
        risk._update_dd_halt_state()
        assert risk._state.dd_triggered_at is not None
        assert risk._state.dd_recovery_at is None

        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD → COOLDOWN (60s wait)
        risk._update_dd_halt_state()
        assert risk._state.dd_recovery_at is not None
        assert risk._state.dd_halt_state == DrawdownHaltState.COOLDOWN

        # Simulate elapsed cooldown and confirm final → NORMAL clears timestamps
        risk._state.dd_recovery_at -= 61.0
        risk._update_dd_halt_state()  # → NORMAL
        assert risk._state.dd_triggered_at is None
        assert risk._state.dd_recovery_at is None

    def test_no_peak_recorded_does_not_crash(self):
        """State machine is a no-op when no equity has ever been recorded."""
        risk = _make_risk()
        risk._update_dd_halt_state()  # peak=0 → should be silent
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL


# ── Unit: check_order blocks / allows based on DD state ─────────────────────


class TestCheckOrderDrawdownBlocking:
    """check_order() should block when DD state is TRIGGERED or COOLDOWN."""

    def test_check_order_allowed_when_normal(self):
        risk = _make_risk()
        ok, reason = _check(risk)
        assert ok, f"Unexpected block: {reason}"

    def test_check_order_blocked_when_triggered(self):
        """check_order() must return False when DD state is TRIGGERED."""
        risk = _make_risk(halt_pct=0.10)
        _set_equity(risk, peak=1000.0, current=880.0)  # 12% DD
        ok, reason = _check(risk)
        assert not ok
        assert "drawdown_halt:triggered" in reason

    def test_check_order_blocked_when_cooldown_secs_nonzero(self):
        """check_order() must return False during COOLDOWN when cooldown_secs > 0."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=60.0)
        _set_equity(risk, peak=1000.0, current=900.0)
        risk._update_dd_halt_state()  # → TRIGGERED
        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD
        risk._update_dd_halt_state()  # → COOLDOWN
        ok, reason = _check(risk)
        assert not ok
        assert "drawdown_halt:cooldown" in reason

    def test_check_order_allowed_after_full_recovery(self):
        """check_order() must allow trades once DD state returns to NORMAL."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=0.0)
        _set_equity(risk, peak=1000.0, current=880.0)  # 12% DD
        ok1, _ = _check(risk)
        assert not ok1  # blocked

        # Equity recovers fully
        _set_equity(risk, peak=1000.0, current=950.0)  # 5% DD
        ok2, reason2 = _check(risk)
        assert ok2, f"Still blocked after recovery: {reason2}"
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_reason_string_contains_drawdown_pct(self):
        """Block reason should include the current drawdown percentage."""
        risk = _make_risk(halt_pct=0.10)
        _set_equity(risk, peak=1000.0, current=870.0)  # 13% DD
        ok, reason = _check(risk)
        assert not ok
        assert "13" in reason or "0.13" in reason  # either format is fine


# ── Regression: kill-switch auto-reset via check_order ───────────────────────


class TestKillSwitchAutoResetViaCheckOrder:
    """Bug regression: kill switch triggered by drawdown must auto-reset when
    equity recovers, even if record_pnl/record_equity_snapshot are not called.
    Previously, the auto-reset only ran inside those two methods, so any halt
    triggered while the trading loop had no fills would stay forever.
    """

    def test_kill_switch_auto_resets_on_check_order(self):
        """Kill switch activated at unwind level auto-resets via check_order()."""
        risk = _make_risk(halt_pct=0.10, unwind_pct=0.15)
        # Set equity such that drawdown triggers unwind kill switch
        _set_equity(risk, peak=1000.0, current=830.0)  # 17% DD
        ok1, _ = _check(risk)
        assert not ok1
        assert risk._state.kill_switch_active, "Kill switch should be active at unwind level"

        # Equity recovers well below the halt threshold — kill switch should
        # auto-reset on the NEXT check_order() call without needing record_pnl.
        _set_equity(risk, peak=1000.0, current=960.0)  # 4% DD
        ok2, reason2 = _check(risk)
        assert not risk._state.kill_switch_active, "Kill switch should have auto-reset"
        assert ok2, f"Trading should resume after recovery: {reason2}"

    def test_kill_switch_stays_active_if_only_partially_recovered(self):
        """Kill switch stays active if equity only recovers to between halt and unwind."""
        risk = _make_risk(halt_pct=0.10, unwind_pct=0.15)
        _set_equity(risk, peak=1000.0, current=830.0)  # 17% → kill switch
        _check(risk)
        assert risk._state.kill_switch_active

        # Recover to 12% — still above halt threshold (10%)
        _set_equity(risk, peak=1000.0, current=880.0)  # 12% DD
        _check(risk)
        assert risk._state.kill_switch_active, (
            "Kill switch should stay active until recovery below halt threshold"
        )

    def test_kill_switch_resets_when_below_halt_threshold(self):
        """Kill switch auto-resets once drawdown drops below halt_pct threshold."""
        risk = _make_risk(halt_pct=0.10, unwind_pct=0.15, cooldown_secs=0.0)
        _set_equity(risk, peak=1000.0, current=830.0)  # 17% → kill switch
        _check(risk)
        assert risk._state.kill_switch_active

        # Recover to 7% — below recovery_threshold (10%-2%=8%) AND below halt_pct
        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD
        ok, reason = _check(risk)
        assert not risk._state.kill_switch_active
        assert ok, f"Trading should resume: {reason}"


# ── Integration: drawdown halt + RiskController global view ──────────────────


class TestDrawdownIntegrationWithRiskController:
    """Verify the drawdown state notifies the central RiskController correctly."""

    def test_record_drawdown_breach_adds_to_active_breaches(self):
        rc = RiskController(dedup_window_secs=0)
        rc.record_drawdown_breach(True, details="test")
        assert "drawdown" in rc._active_breaches

    def test_record_drawdown_breach_clear_removes_from_active_breaches(self):
        rc = RiskController(dedup_window_secs=0)
        rc.record_drawdown_breach(True, "breach")
        rc.record_drawdown_breach(False, "recovered")
        assert "drawdown" not in rc._active_breaches

    def test_get_global_halt_view_normal_state(self):
        rc = RiskController(dedup_window_secs=0)
        view = rc.get_global_halt_view()
        assert view["trading_allowed"] is True
        assert view["is_global_kill"] is False
        assert view["active_breaches"] == []

    def test_get_global_halt_view_with_drawdown_breach(self):
        rc = RiskController(dedup_window_secs=0)
        rc.record_drawdown_breach(True, "drawdown=11%")
        view = rc.get_global_halt_view()
        assert "drawdown" in view["active_breaches"]
        assert any("drawdown" in r for r in view["halt_reasons"])
        assert view["trading_allowed"] is True  # DD breach alone doesn't trigger kill

    def test_get_global_halt_view_with_kill_switch(self):
        rc = RiskController(dedup_window_secs=0)
        rc.emergency_stop("test kill")
        view = rc.get_global_halt_view()
        assert view["trading_allowed"] is False
        assert view["is_global_kill"] is True
        assert view["kill_reason"] == "manual"
        assert "kill_switch:manual" in view["halt_reasons"]

    def test_dd_transition_updates_rc_via_update_dd_halt_state(self):
        """When KalshiRiskManager transitions to TRIGGERED, central RC is notified."""
        rc = RiskController(dedup_window_secs=0)
        risk = _make_risk(halt_pct=0.10)
        # Patch the singleton import so the notification goes to our test rc
        import merid.risk.kill_switches as ks_module
        original = ks_module.risk_controller
        ks_module.risk_controller = rc
        try:
            _set_equity(risk, peak=1000.0, current=880.0)  # 12% → TRIGGERED
            risk._update_dd_halt_state()
            assert "drawdown" in rc._active_breaches
        finally:
            ks_module.risk_controller = original

    def test_dd_recovery_clears_rc_breach(self):
        """Recovery from TRIGGERED to NORMAL clears the central RC breach."""
        rc = RiskController(dedup_window_secs=0)
        risk = _make_risk(halt_pct=0.10, cooldown_secs=0.0)
        import merid.risk.kill_switches as ks_module
        original = ks_module.risk_controller
        ks_module.risk_controller = rc
        try:
            _set_equity(risk, peak=1000.0, current=880.0)
            risk._update_dd_halt_state()  # TRIGGERED
            _set_equity(risk, peak=1000.0, current=940.0)  # 6% — below recovery threshold
            risk._update_dd_halt_state()  # COOLDOWN
            risk._update_dd_halt_state()  # NORMAL (cooldown=0)
            assert "drawdown" not in rc._active_breaches
        finally:
            ks_module.risk_controller = original


# ── Integration: combined halt scenarios ─────────────────────────────────────


class TestCombinedHaltScenarios:
    """Scenario A/B/C from the problem statement."""

    def test_scenario_a_only_error_budget_triggered(self):
        """Scenario A: Error budget halts. Drawdown state remains NORMAL."""
        rc = RiskController(
            error_threshold=3,
            daily_loss_limit=10_000.0,
            dedup_window_secs=0,
            multi_signal_required=1,  # single-signal for this test
        )
        risk = _make_risk()

        # Flood with P0 errors (auth_error is CRITICAL)
        for _ in range(5):
            rc.record_error("auth_error")

        # Error budget should be triggered
        assert not rc.can_trade()
        assert rc.get_state() == KillSwitchState.TRIGGERED

        # Drawdown state must be unaffected
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_scenario_b_only_drawdown_breached(self):
        """Scenario B: Drawdown halt engaged; ErrorBudget stays NORMAL."""
        rc = RiskController(dedup_window_secs=0)
        risk = _make_risk(halt_pct=0.10)

        _set_equity(risk, peak=1000.0, current=880.0)  # 12% DD
        ok, reason = _check(risk)
        assert not ok
        assert "drawdown_halt:triggered" in reason

        # ErrorBudget must still be ACTIVE (no errors were recorded)
        assert rc.can_trade() is True
        assert rc.get_state() == KillSwitchState.ACTIVE

    def test_scenario_c_drawdown_recovery_resumes_trading(self):
        """Scenario C: Drawdown recovers → DD returns to NORMAL → trading resumes."""
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=0.0)

        # Step 1: Trigger drawdown halt
        _set_equity(risk, peak=1000.0, current=880.0)  # 12% DD
        ok1, _ = _check(risk)
        assert not ok1
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

        # Step 2: Equity recovers below recovery threshold
        _set_equity(risk, peak=1000.0, current=930.0)  # 7% DD (below 10-2=8%)
        risk._update_dd_halt_state()  # → COOLDOWN
        risk._update_dd_halt_state()  # → NORMAL (cooldown=0)

        # Step 3: Trading resumes
        ok3, reason3 = _check(risk)
        assert ok3, f"Trading should be allowed after recovery: {reason3}"
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL


# ── Regression: daily reset clears DD state ──────────────────────────────────


class TestDailyResetClearsDDState:
    """reset_daily() must reset the DD state machine to NORMAL for a fresh session."""

    def test_reset_daily_clears_triggered_state(self):
        risk = _make_risk(halt_pct=0.10, cooldown_secs=60.0)
        _set_equity(risk, peak=1000.0, current=880.0)
        risk._update_dd_halt_state()  # → TRIGGERED
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

        risk.reset_daily()
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL
        assert risk._state.dd_triggered_at is None
        assert risk._state.dd_recovery_at is None

    def test_reset_daily_clears_cooldown_state(self):
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=60.0)
        _set_equity(risk, peak=1000.0, current=880.0)
        risk._update_dd_halt_state()  # → TRIGGERED
        _set_equity(risk, peak=1000.0, current=930.0)
        risk._update_dd_halt_state()  # → COOLDOWN
        assert risk._state.dd_halt_state == DrawdownHaltState.COOLDOWN

        risk.reset_daily()
        assert risk._state.dd_halt_state == DrawdownHaltState.NORMAL

    def test_trading_allowed_after_reset_daily(self):
        risk = _make_risk(halt_pct=0.10)
        _set_equity(risk, peak=1000.0, current=880.0)
        ok1, _ = _check(risk)
        assert not ok1  # blocked

        risk.reset_daily()
        ok2, reason2 = _check(risk)
        assert ok2, f"Should be allowed after daily reset: {reason2}"


# ── Regression: exact bug sequence from production ──────────────────────────


class TestRegressionDrawdownHaltNotResetting:
    """Reproduce the original bug: drawdown halt triggered, equity recovered,
    but system stayed halted because the reset path was never triggered.

    The fix: _update_dd_halt_state() and _maybe_auto_reset_drawdown_kill_switch()
    are now called at the top of check_order(), so recovery is detected on the
    very next order attempt even if no record_pnl/record_equity_snapshot called.
    """

    def test_regression_halt_then_recovery_via_check_order_only(self):
        """Simulate the production bug: halt is set, fills stop, equity improves.
        Previously the kill switch would stay active forever in this scenario.
        Now, check_order() itself clears the halt on the next call.
        """
        risk = _make_risk(
            halt_pct=0.10, unwind_pct=0.15,
            recovery_buffer_pct=0.02, cooldown_secs=0.0,
        )
        # Step 1: Large loss triggers unwind kill switch
        _set_equity(risk, peak=1000.0, current=820.0)  # 18% DD
        ok1, _ = _check(risk)
        assert not ok1
        assert risk._state.kill_switch_active, "Kill switch must be active"

        # Step 2: No PnL updates flow in (simulating a stale trading session)
        # Equity is manually updated (e.g. by background balance poll)
        risk._state.current_equity_usd = 950.0  # recovered to 5% DD (below 10%)
        # Note: peak stays at 1000 because _update_peak only runs in record_pnl

        # Step 3: Next order attempt — check_order() should now auto-reset the kill
        # switch because it calls _maybe_auto_reset_drawdown_kill_switch() first.
        ok3, reason3 = _check(risk)
        assert not risk._state.kill_switch_active, (
            "REGRESSION: Kill switch should have auto-reset via check_order(). "
            f"reason={reason3}"
        )
        assert ok3, f"Trading should resume: {reason3}"

    def test_regression_no_state_tracking_at_halt_level(self):
        """The halt level (10-15%) previously had NO state flag, making it
        invisible. Now it transitions to DD_TRIGGERED, which is visible via
        summary() and queryable for observability.
        """
        risk = _make_risk(halt_pct=0.10, unwind_pct=0.15)
        _set_equity(risk, peak=1000.0, current=885.0)  # 11.5% — halt level

        ok, reason = _check(risk)
        assert not ok  # still blocked

        # State must be TRIGGERED (not silent) — this is the fix for "invisible halt"
        assert risk._state.dd_halt_state == DrawdownHaltState.TRIGGERED

        # Visible in summary
        s = risk.summary()
        assert s["dd_halt_state"] == "triggered"
        assert s["dd_trading_blocked"] is True

    def test_regression_summary_shows_normal_after_recovery(self):
        """summary() must report dd_halt_state=normal and dd_trading_blocked=False
        after recovery so operators and dashboards see the correct state.
        """
        risk = _make_risk(halt_pct=0.10, recovery_buffer_pct=0.02, cooldown_secs=0.0)
        _set_equity(risk, peak=1000.0, current=880.0)
        _check(risk)  # triggers TRIGGERED

        _set_equity(risk, peak=1000.0, current=960.0)  # 4% — fully recovered
        _check(risk)  # triggers COOLDOWN then NORMAL (cooldown=0)

        s = risk.summary()
        assert s["dd_halt_state"] == "normal"
        assert s["dd_trading_blocked"] is False
