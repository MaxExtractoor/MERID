"""Tests for E2 – Bankroll zero guard + phantom kill switch group lock."""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, KalshiRiskManager, RiskState


@pytest.fixture
def risk():
    cfg = KalshiRiskConfig()
    return KalshiRiskManager(config=cfg)


# ── Bankroll zero guard ───────────────────────────────────────────────────

def test_check_order_blocked_when_equity_at_zero(risk):
    """Orders are rejected when current equity reaches zero."""
    risk._state.peak_equity_usd = 1000.0
    risk._state.current_equity_usd = 0.0

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert not ok
    assert "bankroll_zero" in reason


def test_check_order_blocked_when_equity_below_zero(risk):
    """Orders are rejected when current equity is negative."""
    risk._state.peak_equity_usd = 1000.0
    risk._state.current_equity_usd = -50.0

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert not ok
    assert "bankroll_zero" in reason


def test_check_order_allowed_when_equity_positive(risk):
    """Orders are allowed when bankroll is positive."""
    risk._state.peak_equity_usd = 1000.0
    risk._state.current_equity_usd = 500.0

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert ok, f"Unexpected rejection: {reason}"


def test_bankroll_guard_not_triggered_before_first_equity_update(risk):
    """Guard does not fire if peak_equity has never been recorded (fresh state)."""
    # peak_equity_usd defaults to 0.0; current_equity also 0.0 → guard skipped
    assert risk._state.peak_equity_usd == 0.0
    assert risk._state.current_equity_usd == 0.0

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert ok, f"Unexpected rejection before any equity was recorded: {reason}"


# ── Phantom kill switch (F2) integration ─────────────────────────────────

def test_phantom_kill_switch_blocks_check_order(risk, monkeypatch):
    """When the phantom kill switch is armed, check_order is blocked."""
    monkeypatch.setattr(
        "merid.reconciliation._phantom_kill_switch",
        True,
    )

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert not ok
    assert "phantom_kill_switch" in reason


def test_phantom_kill_switch_inactive_allows_order(risk, monkeypatch):
    """When the phantom kill switch is NOT armed, check_order proceeds normally."""
    monkeypatch.setattr(
        "merid.reconciliation._phantom_kill_switch",
        False,
    )

    ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)

    assert ok, f"Unexpected rejection: {reason}"


def test_arm_phantom_kill_switch_then_check_order(risk):
    """arm_phantom_kill_switch + check_order integration test."""
    from merid.reconciliation import arm_phantom_kill_switch, _phantom_kill_lock
    import merid.reconciliation as recon

    original = recon._phantom_kill_switch
    try:
        arm_phantom_kill_switch("test scenario")
        ok, reason = risk.check_order("KXBTC", "crypto", 10, 50)
        assert not ok
        assert "phantom_kill_switch" in reason
    finally:
        # Restore original state so other tests aren't affected
        with _phantom_kill_lock:
            recon._phantom_kill_switch = original
