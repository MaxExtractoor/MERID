"""Tests for E1 – check_order receives real orderbook params.

Verifies that spread_cents and depth_at_price actually change check_order's
decision, and that tests serve as regression guards against silent acceptance
of dummy values.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, KalshiRiskManager


@pytest.fixture
def risk():
    cfg = KalshiRiskConfig(
        max_spread_cents=10,
        min_depth_contracts=5,
    )
    return KalshiRiskManager(config=cfg)


def test_check_order_allowed_without_orderbook_params(risk):
    """Without spread/depth, check_order passes (no orderbook checks applied)."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
    )
    assert ok, f"Expected allowed but got: {reason}"


def test_check_order_blocked_when_spread_exceeds_max(risk):
    """Spread above max_spread_cents causes rejection."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        spread_cents=15,   # > max_spread_cents=10
    )
    assert not ok
    assert "Spread" in reason
    assert "orderbook check" in reason


def test_check_order_allowed_when_spread_at_max(risk):
    """Spread exactly at max_spread_cents is allowed."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        spread_cents=10,   # == max_spread_cents
    )
    assert ok, reason


def test_check_order_blocked_when_depth_below_min(risk):
    """Depth below min_depth_contracts causes rejection."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        depth_at_price=3,   # < min_depth_contracts=5
    )
    assert not ok
    assert "Depth" in reason
    assert "orderbook check" in reason


def test_check_order_allowed_when_depth_meets_min(risk):
    """Depth exactly at min_depth_contracts is allowed."""
    ok, reason = risk.check_order(
        ticker="KXBTC-TEST",
        category="crypto",
        contracts=10,
        price_cents=50,
        depth_at_price=5,   # == min_depth_contracts
    )
    assert ok, reason


def test_changing_spread_changes_decision(risk):
    """Varying spread around the threshold flips the decision."""
    ok_tight, _ = risk.check_order("KXBTC", "crypto", 5, 50, spread_cents=5)
    ok_wide, _  = risk.check_order("KXBTC", "crypto", 5, 50, spread_cents=20)

    assert ok_tight, "tight spread should be allowed"
    assert not ok_wide, "wide spread should be blocked"


def test_changing_depth_changes_decision(risk):
    """Varying depth around the threshold flips the decision."""
    ok_deep, _    = risk.check_order("KXBTC", "crypto", 5, 50, depth_at_price=10)
    ok_shallow, _ = risk.check_order("KXBTC", "crypto", 5, 50, depth_at_price=2)

    assert ok_deep,    "deep orderbook should be allowed"
    assert not ok_shallow, "shallow orderbook should be blocked"


def test_order_intent_carries_orderbook_params():
    """OrderIntent now has spread_cents and depth_at_price fields (E1)."""
    from merid.event_venues.kalshi.order_router import OrderIntent, TradingMode
    intent = OrderIntent(
        ticker="KXBTC",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        spread_cents=8,
        depth_at_price=20,
    )
    assert intent.spread_cents == 8
    assert intent.depth_at_price == 20


# ── Max YES price cap tests ───────────────────────────────────────────────

class TestMaxYesPriceCap:
    """check_order enforces max_yes_price_cents for YES outcome orders."""

    @pytest.fixture
    def risk_with_cap(self):
        cfg = KalshiRiskConfig(max_yes_price_cents=50)  # 50¢ cap
        return KalshiRiskManager(config=cfg)

    def test_yes_price_below_cap_allowed(self, risk_with_cap):
        """YES order at 45¢ < 50¢ cap → allowed."""
        ok, reason = risk_with_cap.check_order(
            ticker="KXBTC-TEST", category="crypto",
            contracts=10, price_cents=45, outcome="yes",
        )
        assert ok, reason

    def test_yes_price_at_cap_allowed(self, risk_with_cap):
        """YES order exactly at 50¢ cap → allowed."""
        ok, reason = risk_with_cap.check_order(
            ticker="KXBTC-TEST", category="crypto",
            contracts=10, price_cents=50, outcome="yes",
        )
        assert ok, reason

    def test_yes_price_above_cap_blocked(self, risk_with_cap):
        """YES order at 65¢ > 50¢ cap → rejected with max_yes_price_cap reason."""
        ok, reason = risk_with_cap.check_order(
            ticker="KXBTC-TEST", category="crypto",
            contracts=10, price_cents=65, outcome="yes",
        )
        assert not ok
        assert "max_yes_price_cap" in reason

    def test_no_price_above_cap_allowed(self, risk_with_cap):
        """NO orders are not constrained by the YES price cap."""
        ok, reason = risk_with_cap.check_order(
            ticker="KXBTC-TEST", category="crypto",
            contracts=10, price_cents=75, outcome="no",
        )
        assert ok, reason

    def test_default_outcome_is_yes(self, risk_with_cap):
        """Default outcome parameter is 'yes', so cap is applied without explicit param."""
        ok, reason = risk_with_cap.check_order(
            ticker="KXBTC-TEST", category="crypto",
            contracts=10, price_cents=65,  # above cap, no outcome= kwarg
        )
        assert not ok
        assert "max_yes_price_cap" in reason

    def test_custom_cap_enforced(self):
        """A non-default max_yes_price_cents is respected."""
        cfg = KalshiRiskConfig(max_yes_price_cents=40)  # tighter, 40¢
        risk = KalshiRiskManager(config=cfg)

        ok_below, _ = risk.check_order("KXBTC", "crypto", 5, 38, outcome="yes")
        ok_above, reason_above = risk.check_order("KXBTC", "crypto", 5, 45, outcome="yes")

        assert ok_below
        assert not ok_above
        assert "max_yes_price_cap" in reason_above


# ── Drawdown kill switch auto-reset (venue status: ok on recovery) ────────────

class TestDrawdownKillSwitchAutoReset:
    """Kill switch set by drawdown unwind auto-resets when equity recovers."""

    @pytest.fixture
    def rm(self):
        cfg = KalshiRiskConfig(
            drawdown_halt_pct=0.10,
            drawdown_unwind_pct=0.15,
        )
        mgr = KalshiRiskManager(config=cfg)
        # Seed a realistic equity baseline
        mgr._state.peak_equity_usd = 10_000.0
        mgr._state.current_equity_usd = 10_000.0
        return mgr

    def test_drawdown_kill_switch_stays_clear_in_normal_operation(self, rm):
        """No kill switch when drawdown is within limits."""
        rm.record_equity_snapshot(9_500.0)  # 5% drawdown
        assert rm.kill_switch_active is False

    def test_drawdown_below_halt_pct_does_not_trigger_kill_switch(self, rm):
        """Drawdown just below halt threshold does not trigger kill switch."""
        rm.record_equity_snapshot(9_010.0)  # ~9.9% drawdown
        assert rm.kill_switch_active is False

    def test_drawdown_unwind_activates_kill_switch(self, rm):
        """Drawdown >= unwind threshold activates kill switch via check_order."""
        rm._state.current_equity_usd = 8_300.0  # 17% drawdown
        ok, reason = rm.check_order("KXBTC", "crypto", 10, 50)
        assert not ok
        assert rm.kill_switch_active is True
        assert "drawdown" in rm._state.kill_switch_reason.lower()

    def test_kill_switch_auto_resets_when_drawdown_recovers(self, rm):
        """After a drawdown kill switch is activated, recovery clears venue status back to ok."""
        # Activate kill switch via drawdown unwind
        rm._state.current_equity_usd = 8_300.0  # 17% drawdown
        rm.check_order("KXBTC", "crypto", 10, 50)
        assert rm.kill_switch_active is True

        # Equity recovers well above halt threshold (< 10% drawdown)
        rm.record_equity_snapshot(9_200.0)  # 8% drawdown — below halt_pct
        assert rm.kill_switch_active is False, "Kill switch should auto-clear on drawdown recovery"

    def test_kill_switch_stays_active_while_drawdown_above_halt_pct(self, rm):
        """Kill switch stays active when drawdown has not fully recovered."""
        rm._state.current_equity_usd = 8_300.0
        rm.check_order("KXBTC", "crypto", 10, 50)
        assert rm.kill_switch_active is True

        # Partial recovery but still above halt_pct (10%)
        rm.record_equity_snapshot(8_900.0)  # 11% drawdown
        assert rm.kill_switch_active is True

    def test_daily_loss_kill_switch_not_auto_reset_by_equity_recovery(self, rm):
        """Kill switch triggered by daily loss is NOT auto-reset by equity recovery."""
        rm._state.daily_pnl_usd = -rm._config.max_daily_loss_usd - 1.0
        rm._activate_kill_switch("Daily loss limit breached")
        assert rm.kill_switch_active is True

        # Equity snapshot at good level — should NOT clear kill switch
        rm.record_equity_snapshot(9_500.0)  # only 5% drawdown
        assert rm.kill_switch_active is True, "Daily-loss kill switch must not auto-reset"

    def test_kill_switch_full_cycle_via_record_pnl(self, rm):
        """Full cycle via record_pnl: normal → kill switch → recovery → ok."""
        assert rm.kill_switch_active is False

        # Simulate a loss that activates kill switch via check_order drawdown path
        rm._state.current_equity_usd = 8_400.0  # 16% drawdown
        rm.check_order("KXBTC", "crypto", 10, 50)
        assert rm.kill_switch_active is True

        # Gradual equity recovery via record_pnl
        rm.record_pnl(500.0)   # equity 8_900 (~11% dd) — still halted
        assert rm.kill_switch_active is True

        rm.record_pnl(500.0)   # equity 9_400 (~6% dd) — recovered
        assert rm.kill_switch_active is False
