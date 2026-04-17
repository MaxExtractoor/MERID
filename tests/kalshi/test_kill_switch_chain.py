"""Kill-switch chain integration tests.

Tests the critical path: risk_controller._global_kill → check_execution_gate()
→ ExecutionGateStatus.blocked, and VenueGate mode controls.

All tests use demo mode (KALSHI_USE_DEMO=true) to avoid false positives from
reconciliation or price-feed sources.
"""
import os
import pytest


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """Force demo mode so only kill_switch source can block in these tests."""
    monkeypatch.setenv("KALSHI_USE_DEMO", "true")
    monkeypatch.setenv("MERID_PROFILE", "kalshi-only")


@pytest.fixture(autouse=True)
def fresh_kill_switch():
    """Reset kill switch state before and after each test."""
    from merid.risk.kill_switches import risk_controller
    risk_controller.reset()
    yield
    risk_controller.reset()


# ── check_execution_gate + kill_switch ────────────────────────────────────

def test_gate_has_no_kill_reason_when_not_triggered():
    """When kill switch is inactive, check_execution_gate must have no kill_switch reason."""
    from core.execution_gate import check_execution_gate
    status = check_execution_gate()
    kill_reasons = [r for r in status.reasons if r.source == "kill_switch"]
    assert not kill_reasons, f"Unexpected kill_switch reason: {kill_reasons}"


def test_gate_blocked_when_emergency_stop():
    """emergency_stop() → gate must be BLOCKED with kill_switch source."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate, GateState

    risk_controller.emergency_stop("Test: operator emergency stop")

    status = check_execution_gate()
    assert status.blocked, "Gate must be blocked after emergency_stop()"
    assert status.gate_state == GateState.BLOCKED.value

    kill_reasons = [r for r in status.reasons if r.source == "kill_switch"]
    assert kill_reasons, "kill_switch reason must appear in blocked gate"
    assert kill_reasons[0].severity == "critical"


def test_gate_clears_after_reset():
    """reset_kill_switch() → gate must clear in demo mode (no other critical blockers)."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate

    risk_controller.emergency_stop("Test: temporary kill")
    blocked = check_execution_gate()
    assert blocked.blocked

    risk_controller.reset()
    cleared = check_execution_gate()

    kill_reasons = [r for r in cleared.reasons if r.source == "kill_switch" and r.severity == "critical"]
    assert not kill_reasons, f"Kill switch still critical after reset: {kill_reasons}"


def test_emergency_stop_blocks_gate():
    """emergency_stop() must set _global_kill and block the execution gate."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate

    risk_controller.emergency_stop("Test: alias")
    status = check_execution_gate()
    assert status.blocked


def test_live_execution_blocked_helper():
    """live_execution_blocked() must return True when gate is blocked."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate, live_execution_blocked

    risk_controller.emergency_stop("Test: live_execution_blocked")
    status = check_execution_gate()
    assert live_execution_blocked(status) is True

    risk_controller.reset()
    status_clear = check_execution_gate()
    assert live_execution_blocked(status_clear) is False


# ── Daily loss kill ────────────────────────────────────────────────────────

def test_daily_loss_triggers_kill():
    """Exceeding daily loss limit must set _global_kill and block execution."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate

    risk_controller.daily_loss_limit = 10.0
    risk_controller._daily_pnl = 0.0

    can_trade = risk_controller.record_pnl(-15.0)
    # record_pnl returns False when kill is triggered (can trade = False)
    assert can_trade is False, "record_pnl should return False (can_trade) when kill is triggered"
    assert risk_controller._global_kill is True

    status = check_execution_gate()
    assert status.blocked


def test_daily_loss_not_triggered_under_limit():
    """P&L within limit must NOT trigger the kill switch."""
    from merid.risk.kill_switches import risk_controller

    risk_controller.daily_loss_limit = 500.0
    risk_controller._daily_pnl = 0.0

    can_trade = risk_controller.record_pnl(-50.0)
    # record_pnl returns True when kill was NOT triggered (can still trade)
    assert can_trade is True
    assert risk_controller._global_kill is False


# ── can_trade() ────────────────────────────────────────────────────────────

def test_can_trade_true_when_active():
    from merid.risk.kill_switches import risk_controller
    risk_controller.reset()
    assert risk_controller.can_trade() is True


def test_can_trade_false_when_killed():
    from merid.risk.kill_switches import risk_controller
    risk_controller.emergency_stop("Test: can_trade=False")
    assert risk_controller.can_trade() is False


# ── VenueGate ────────────────────────────────────────────────────────────

def test_venue_gate_mock_mode_blocks_can_trade():
    """MOCK mode must raise ModeBlockedError on check_can_trade()."""
    from merid.prediction.venue_gate import VenueGate
    from trading.trade_mode import TradeMode

    gate = VenueGate(mode=TradeMode.MOCK)
    with pytest.raises(VenueGate.ModeBlockedError):
        gate.check_can_trade()


def test_venue_gate_kalshi_allowed():
    """check_venue('kalshi') must not raise."""
    from merid.prediction.venue_gate import VenueGate
    gate = VenueGate()
    gate.check_venue("kalshi")  # must not raise


def test_venue_gate_polymarket_blocked():
    """Polymarket is US-blocked and must raise VenueBlockedError."""
    from merid.prediction.venue_gate import VenueGate
    gate = VenueGate()
    with pytest.raises(VenueGate.VenueBlockedError):
        gate.check_venue("polymarket")


def test_venue_gate_unknown_venue_blocked():
    """Unknown venue must raise VenueBlockedError."""
    from merid.prediction.venue_gate import VenueGate
    gate = VenueGate()
    with pytest.raises(VenueGate.VenueBlockedError):
        gate.check_venue("some_random_venue")


def test_venue_gate_paper_mode_allows_check_can_trade(monkeypatch):
    """PAPER mode must NOT raise on check_can_trade()."""
    from merid.prediction.venue_gate import VenueGate
    from trading.trade_mode import TradeMode

    gate = VenueGate(mode=TradeMode.PAPER)
    gate.check_can_trade()  # must not raise


def test_venue_gate_live_mode_requires_merid_allow_live_trades(monkeypatch):
    """Without MERID_ALLOW_LIVE_TRADES, LIVE mode must be forced to PAPER."""
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "false")
    from merid.prediction.venue_gate import VenueGate
    from trading.trade_mode import TradeMode

    gate = VenueGate(mode=TradeMode.LIVE)
    # Should have been forced to PAPER
    assert gate.mode == TradeMode.PAPER


# ── kill_switch reason in gate ────────────────────────────────────────────

def test_kill_switch_reason_has_hint():
    """The kill_switch block reason must include a remediation hint."""
    from merid.risk.kill_switches import risk_controller
    from core.execution_gate import check_execution_gate

    risk_controller.emergency_stop("Test: hint check")
    status = check_execution_gate()

    kill_reason = next(r for r in status.reasons if r.source == "kill_switch")
    assert kill_reason.hint is not None
    assert len(kill_reason.hint) > 10, "Hint must be a non-trivial string"
