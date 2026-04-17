"""Regression tests for risk limit alert + breach logging fix.

Bug: KalshiRiskManager._check_order_locked() silently rejected orders
for non-kill-switch breaches (order size, position limit, category cap,
portfolio notional, drawdown halt, post-fee edge, rate limit) without:
  1. Logging to breach_log → breach_count always 0 in UI
  2. Firing PredictionAlert → RiskAlertFeed component never showed rejections

Fix: Every rejection path in _check_order_locked now calls _log_breach(),
and check_order() fires a PredictionAlert outside the lock for all rejections.
Also converted self._lock from threading.Lock to threading.RLock to prevent
deadlock when _activate_kill_switch is called from _check_order_locked.
"""

import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from merid.event_venues.kalshi.kalshi_risk import (
    KalshiRiskConfig,
    KalshiRiskManager,
    CategoryLimit,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _fresh_manager(**overrides) -> KalshiRiskManager:
    """Create a KalshiRiskManager with tight limits for testing."""
    defaults = dict(
        max_single_order_contracts=10,
        max_single_order_notional_usd=500.0,
        max_position_per_contract=20,
        max_total_notional_usd=1000.0,
        max_daily_loss_usd=100.0,
        drawdown_halt_pct=0.05,
        drawdown_unwind_pct=0.10,
        min_edge=0.02,
        min_post_fee_edge=0.01,
        max_orders_per_minute=3,
        max_orders_per_hour=10,
        category_limits={
            "crypto": CategoryLimit("crypto", max_notional_usd=200, max_contracts=15),
        },
    )
    defaults.update(overrides)
    return KalshiRiskManager(config=KalshiRiskConfig(**defaults))


# ── Breach log tests ─────────────────────────────────────────────────────

class TestBreachLogging:
    """Every risk rejection must appear in breach_log."""

    def test_order_size_breach_logged(self):
        mgr = _fresh_manager()
        ok, reason = mgr.check_order("TICKER-A", None, contracts=999, price_cents=50)
        assert not ok
        assert len(mgr.state.breach_log) == 1
        assert mgr.state.breach_log[0]["check"] == "max_single_order_contracts"

    def test_order_notional_breach_logged(self):
        # max_single_order_notional_usd=500; 10 contracts @ 51c = $5.10 OK
        # Need 10 contracts where notional > $500: impossible at <=99c with 10 contracts
        # So use a manager with tighter notional cap
        mgr = _fresh_manager(max_single_order_notional_usd=2.0)
        ok, reason = mgr.check_order("TICKER-A", None, contracts=5, price_cents=50)
        assert not ok  # 5 * 50/100 = $2.50 > $2.00
        assert len(mgr.state.breach_log) == 1
        assert mgr.state.breach_log[0]["check"] == "max_single_order_notional"

    def test_position_limit_breach_logged(self):
        mgr = _fresh_manager()
        ok, reason = mgr.check_order("TICKER-A", None, contracts=5, price_cents=50, existing_position=18)
        assert not ok
        assert len(mgr.state.breach_log) == 1
        assert mgr.state.breach_log[0]["check"] == "max_position_per_contract"

    def test_category_notional_breach_logged(self):
        mgr = _fresh_manager()
        # crypto cap is $200; 5 contracts @ 50c = $2.50 each time, but let's exceed it
        ok, reason = mgr.check_order("TICKER-A", "crypto", contracts=5, price_cents=50)
        assert ok  # $2.50 < $200
        mgr.record_order("crypto", 5, 50)
        # Now push notional over the limit by making a big order
        ok2, reason2 = mgr.check_order("TICKER-B", "crypto", contracts=8, price_cents=50)
        assert ok2  # $4 + $2.50 = $6.50 < $200
        mgr.record_order("crypto", 8, 50)
        # Force a breach: record enough to near limit, then try to exceed
        mgr._state.category_notional["crypto"] = 199.0
        ok3, reason3 = mgr.check_order("TICKER-C", "crypto", contracts=5, price_cents=50)
        assert not ok3
        assert any(b["check"] == "category_notional_cap" for b in mgr.state.breach_log)

    def test_category_contracts_breach_logged(self):
        mgr = _fresh_manager()
        mgr._state.category_contracts["crypto"] = 14
        ok, reason = mgr.check_order("TICKER-A", "crypto", contracts=5, price_cents=10)
        assert not ok
        assert any(b["check"] == "category_contracts_cap" for b in mgr.state.breach_log)

    def test_total_notional_breach_logged(self):
        mgr = _fresh_manager()
        mgr._state.total_notional_usd = 999.0
        ok, reason = mgr.check_order("TICKER-A", None, contracts=5, price_cents=50)
        assert not ok
        assert any(b["check"] == "max_total_notional" for b in mgr.state.breach_log)

    def test_drawdown_halt_breach_logged(self):
        mgr = _fresh_manager()
        mgr._state.peak_equity_usd = 1000.0
        mgr._state.current_equity_usd = 940.0  # 6% drawdown > 5% halt
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert any(b["check"] == "drawdown_halt" for b in mgr.state.breach_log)

    def test_rate_limit_minute_breach_logged(self):
        mgr = _fresh_manager()
        now = datetime.now(timezone.utc)
        # Prevent _maybe_reset_daily from clearing order counters
        mgr._last_reset_day = now.strftime("%Y-%m-%d")
        # Prevent _reset_rate_counters from clearing counters
        mgr._state.last_minute_reset = now
        mgr._state.last_hour_reset = now
        mgr._state.orders_this_minute = 999
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert any(b["check"] == "rate_limit_minute" for b in mgr.state.breach_log)

    def test_rate_limit_hour_breach_logged(self):
        mgr = _fresh_manager()
        now = datetime.now(timezone.utc)
        mgr._last_reset_day = now.strftime("%Y-%m-%d")
        mgr._state.last_minute_reset = now
        mgr._state.last_hour_reset = now
        mgr._state.orders_this_minute = 0
        # __post_init__ loads hour cap from settings (often 1000), not the test defaults
        mgr._state.orders_this_hour = mgr._config.max_orders_per_hour + 1
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert any(b["check"] == "rate_limit_hour" for b in mgr.state.breach_log)

    def test_kill_switch_breach_logged(self):
        mgr = _fresh_manager()
        mgr._state.kill_switch_active = True
        mgr._state.kill_switch_reason = "test"
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert any(b["check"] == "kill_switch" for b in mgr.state.breach_log)

    def test_post_fee_edge_breach_logged(self):
        mgr = _fresh_manager(min_post_fee_edge=0.50)
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50, edge=0.03)
        assert not ok
        assert any(b["check"] == "min_post_fee_edge" for b in mgr.state.breach_log)

    def test_passing_order_no_breach(self):
        mgr = _fresh_manager()
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert ok
        assert len(mgr.state.breach_log) == 0


# ── Alert firing tests ───────────────────────────────────────────────────

class TestAlertFiring:
    """check_order must fire a PredictionAlert for every rejection."""

    @patch("merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager._fire_risk_alert")
    def test_alert_fired_on_order_size_breach(self, mock_fire):
        mgr = _fresh_manager()
        mgr.check_order("TICKER-A", None, contracts=999, price_cents=50)
        mock_fire.assert_called_once()
        args = mock_fire.call_args[0]
        assert args[0] == "TICKER-A"
        assert "exceeds max" in args[1]

    @patch("merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager._fire_risk_alert")
    def test_alert_not_fired_on_passing_order(self, mock_fire):
        mgr = _fresh_manager()
        mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        mock_fire.assert_not_called()

    @patch("merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager._fire_risk_alert")
    def test_alert_fired_on_rate_limit(self, mock_fire):
        mgr = _fresh_manager()
        now = datetime.now(timezone.utc)
        mgr._last_reset_day = now.strftime("%Y-%m-%d")
        mgr._state.last_minute_reset = now
        mgr._state.last_hour_reset = now
        mgr._state.orders_this_minute = 999
        mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        mock_fire.assert_called_once()
        assert "Rate limit" in mock_fire.call_args[0][1]

    def test_fire_risk_alert_calls_warning_for_normal_breach(self):
        mgr = _fresh_manager()
        with patch("merid.prediction.alerts.get_alert_manager") as mock_get:
            mock_mgr = MagicMock()
            mock_get.return_value = mock_mgr
            mgr._fire_risk_alert("TICKER-A", "Order size 999 exceeds max 10")
            mock_mgr.fire_risk_warning.assert_called_once()
            mock_mgr.fire_risk_breach.assert_not_called()

    def test_fire_risk_alert_calls_breach_for_kill_switch(self):
        mgr = _fresh_manager()
        with patch("merid.prediction.alerts.get_alert_manager") as mock_get:
            mock_mgr = MagicMock()
            mock_get.return_value = mock_mgr
            mgr._fire_risk_alert("TICKER-A", "Kill switch active: Daily loss limit breached")
            mock_mgr.fire_risk_breach.assert_called_once()
            mock_mgr.fire_risk_warning.assert_not_called()

    def test_fire_risk_alert_calls_breach_for_unwind(self):
        mgr = _fresh_manager()
        with patch("merid.prediction.alerts.get_alert_manager") as mock_get:
            mock_mgr = MagicMock()
            mock_get.return_value = mock_mgr
            mgr._fire_risk_alert("TICKER-A", "Drawdown 15.0% exceeds unwind threshold")
            mock_mgr.fire_risk_breach.assert_called_once()


# ── RLock / deadlock prevention ──────────────────────────────────────────

class TestRLockSafety:
    """Verify the lock is reentrant so _activate_kill_switch doesn't deadlock."""

    def test_lock_is_rlock(self):
        mgr = _fresh_manager()
        assert isinstance(mgr._lock, type(threading.RLock()))

    def test_daily_loss_activates_kill_switch_without_deadlock(self):
        mgr = _fresh_manager()
        mgr._state.daily_pnl_usd = -999.0  # way past limit
        # Must also set _last_reset_day to today so _maybe_reset_daily doesn't clear it
        from datetime import datetime, timezone
        mgr._last_reset_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Mock _sync_pnl_from_ledger to prevent it from overwriting our test value
        mgr._sync_pnl_from_ledger = lambda: None
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert mgr.state.kill_switch_active
        assert "Daily loss" in reason

    def test_drawdown_unwind_activates_kill_switch_without_deadlock(self):
        mgr = _fresh_manager()
        mgr._state.peak_equity_usd = 1000.0
        mgr._state.current_equity_usd = 850.0  # 15% drawdown > 10% unwind
        ok, reason = mgr.check_order("TICKER-A", None, contracts=1, price_cents=50)
        assert not ok
        assert mgr.state.kill_switch_active
        assert "unwind" in reason.lower()


# ── Summary / breach_count integration ───────────────────────────────────

class TestSummaryBreachCount:
    """summary() must reflect breach_count from breach_log."""

    def test_breach_count_increments(self):
        mgr = _fresh_manager()
        mgr.check_order("T1", None, contracts=999, price_cents=50)
        mgr.check_order("T2", None, contracts=999, price_cents=50)
        s = mgr.summary()
        assert s["breach_count"] == 2

    def test_breach_count_zero_when_passing(self):
        mgr = _fresh_manager()
        mgr.check_order("T1", None, contracts=1, price_cents=50)
        s = mgr.summary()
        assert s["breach_count"] == 0

    def test_recent_breaches_in_summary(self):
        mgr = _fresh_manager()
        mgr.check_order("T1", None, contracts=999, price_cents=50)
        s = mgr.summary()
        assert len(s["recent_breaches"]) == 1
        assert s["recent_breaches"][0]["check"] == "max_single_order_contracts"
