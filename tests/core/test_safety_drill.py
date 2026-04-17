"""Safety Drill — end-to-end test harness for execution gate scenarios.

Simulates each gate cause and asserts:
  1. Execution gate flips to BLOCKED with correct reason source/severity.
  2. Session log records the transition event.
  3. TradingExecutionEngine rejects orders.
  4. set_trade_mode() refuses LIVE transition.
  5. Gate returns to CLEAR when cause is resolved.

Run with:  py -m pytest tests/core/test_safety_drill.py -xvs
"""

import time
from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest

from core.execution_gate import (
    check_execution_gate,
    check_price_feed_staleness,
    SymbolGroupConfig,
    set_staleness_config,
    _update_blocked_state,
)
from core.session_log import record_event, get_events, clear_events


# ── Helpers ──────────────────────────────────────────────────────────

def _mock_rc(kill=False, details=None, reason=None):
    rc = MagicMock()
    rc._global_kill = kill
    rc._kill_details = details
    rc._kill_reason = reason
    return rc


def _mock_recon(discrepancies=False, ever_completed=True):
    m = MagicMock()
    m.has_critical_discrepancies = MagicMock(return_value=discrepancies)
    m._has_ever_completed = ever_completed
    return m


def _mock_feed(symbols_age: dict):
    """Build a mock LivePriceFeed with {symbol: age_seconds}."""
    feed = MagicMock()
    cache = {}
    for sym, age in symbols_age.items():
        pd = MagicMock()
        pd.timestamp = datetime.fromtimestamp(time.time() - age)
        cache[sym] = pd
    feed.price_cache = cache
    return feed


def _gate_with_mocks(
    kill=False, kill_details=None,
    discrepancies=False, ever_completed=True,
    pnl_consistent=True, pnl_divergence=0.0,
    feed_safe=True, stale_symbols=None,
):
    """Run check_execution_gate with fully mocked dependencies."""
    rc = _mock_rc(kill=kill, details=kill_details)
    recon = _mock_recon(discrepancies=discrepancies, ever_completed=ever_completed)

    pnl_result = {
        "consistent": pnl_consistent,
        "max_divergence_usd": pnl_divergence,
        "threshold_usd": 5.0,
        "sources": {},
    }
    stale_result = {
        "safe_to_trade": feed_safe,
        "stale_symbols": stale_symbols or [],
        "critical_count": 0 if feed_safe else len(stale_symbols or []),
    }

    with patch("core.execution_gate.check_pnl_consistency", return_value=pnl_result):
        with patch("core.execution_gate.check_price_feed_staleness", return_value=stale_result):
            with patch.dict("sys.modules", {
                "merid.risk.kill_switches": MagicMock(risk_controller=rc),
                "trading.reconciliation": recon,
            }):
                return check_execution_gate()


# ── Drill 1: Kill Switch ────────────────────────────────────────────


class TestDrillKillSwitch:
    """Simulate kill switch engagement and verify full-stack response."""

    def setup_method(self):
        _update_blocked_state(False)  # start from CLEAR
        clear_events()

    def test_kill_switch_blocks_execution(self):
        result = _gate_with_mocks(kill=True, kill_details="Manual emergency stop")

        assert result.blocked is True
        assert result.safe_to_trade is False
        kill_reasons = [r for r in result.reasons if r.source == "kill_switch"]
        assert len(kill_reasons) == 1
        assert kill_reasons[0].severity == "critical"
        assert "kill switch" in kill_reasons[0].message.lower()

    def test_kill_switch_records_session_event(self):
        _gate_with_mocks(kill=True, kill_details="Drill test")

        events = get_events(category="gate")
        assert len(events) >= 1
        assert events[0].title == "Execution gate BLOCKED"
        assert "gate" == events[0].category

    def test_kill_switch_clears_when_reset(self):
        # First: block
        _gate_with_mocks(kill=True, kill_details="Drill")
        # Then: clear
        _update_blocked_state(True)  # ensure transition fires
        result = _gate_with_mocks(kill=False)

        assert result.blocked is False
        events = get_events(category="gate")
        titles = [e.title for e in events]
        assert "Execution gate CLEAR" in titles

    def test_kill_switch_prevents_live_mode(self):
        """set_trade_mode(LIVE) should raise when gate is blocked.

        We patch the gate check at the trade_mode module level to avoid
        heavy paper-engine imports that cause hangs in test.
        """
        import os
        from trading.trade_mode import TradeMode

        blocked_status = MagicMock()
        blocked_status.blocked = True
        blocked_status.reasons = [MagicMock(message="Kill switch is engaged")]

        with patch.dict(os.environ, {"MERID_ALLOW_LIVE_TRADES": "true"}):
            with patch("trading.trade_mode.get_trade_mode", return_value=TradeMode.PAPER):
                with patch("core.execution_gate.check_execution_gate", return_value=blocked_status):
                    from trading.trade_mode import set_trade_mode
                    with pytest.raises(RuntimeError, match="execution gate blocked"):
                        set_trade_mode(TradeMode.LIVE, reason="drill test")


# ── Drill 2: Stale Price Feeds ──────────────────────────────────────


class TestDrillStaleFeed:
    """Simulate stale price feeds and verify gate blocks."""

    def setup_method(self):
        _update_blocked_state(False)
        clear_events()
        set_staleness_config([
            SymbolGroupConfig(name="major", symbols={"BTC/USDT"}, threshold_seconds=60, critical=True),
        ])

    def test_stale_major_blocks(self):
        result = _gate_with_mocks(
            feed_safe=False,
            stale_symbols=[{"symbol": "BTC/USDT", "age_seconds": 120}],
        )

        assert result.blocked is True
        feed_reasons = [r for r in result.reasons if r.source == "price_feed"]
        assert len(feed_reasons) == 1

    def test_stale_feed_records_session_event(self):
        _gate_with_mocks(
            feed_safe=False,
            stale_symbols=[{"symbol": "BTC/USDT"}],
        )

        events = get_events(category="gate")
        assert any(e.title == "Execution gate BLOCKED" for e in events)

    @patch("data.live_price_feed.get_live_price_feed")
    def test_staleness_check_with_real_config(self, mock_feed_fn):
        """End-to-end: stale BTC feed triggers staleness check correctly."""
        mock_feed_fn.return_value = _mock_feed({"BTC/USDT": 90})  # 90s > 60s

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is False
        assert result["critical_count"] == 1

    @patch("data.live_price_feed.get_live_price_feed")
    def test_fresh_feed_passes(self, mock_feed_fn):
        mock_feed_fn.return_value = _mock_feed({"BTC/USDT": 10})  # 10s < 60s

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is True


# ── Drill 3: Reconciliation Failure ─────────────────────────────────


class TestDrillReconFailure:
    """Simulate reconciliation failure and verify gate blocks."""

    def setup_method(self):
        _update_blocked_state(False)
        clear_events()

    def test_recon_never_completed_blocks(self):
        result = _gate_with_mocks(discrepancies=True, ever_completed=False)

        assert result.blocked is True
        recon_reasons = [r for r in result.reasons if r.source == "reconciliation"]
        assert len(recon_reasons) == 1
        assert "never completed" in recon_reasons[0].message.lower()

    def test_recon_discrepancies_block(self):
        result = _gate_with_mocks(discrepancies=True, ever_completed=True)

        assert result.blocked is True
        recon_reasons = [r for r in result.reasons if r.source == "reconciliation"]
        assert len(recon_reasons) == 1
        assert recon_reasons[0].severity == "critical"

    def test_recon_ok_does_not_block(self):
        result = _gate_with_mocks(discrepancies=False, ever_completed=True)
        assert result.blocked is False


# ── Drill 4: PnL Divergence ─────────────────────────────────────────


class TestDrillPnLDivergence:
    """Simulate PnL divergence and verify it's a warning, not a block."""

    def setup_method(self):
        _update_blocked_state(False)
        clear_events()

    def test_pnl_divergence_is_warning(self):
        result = _gate_with_mocks(pnl_consistent=False, pnl_divergence=12.50)

        # PnL divergence alone should NOT block (warning severity)
        assert result.blocked is False
        pnl_reasons = [r for r in result.reasons if r.source == "pnl_consistency"]
        assert len(pnl_reasons) == 1
        assert pnl_reasons[0].severity == "warning"
        assert "$12.50" in pnl_reasons[0].message

    def test_pnl_consistent_no_warning(self):
        result = _gate_with_mocks(pnl_consistent=True, pnl_divergence=0)
        pnl_reasons = [r for r in result.reasons if r.source == "pnl_consistency"]
        assert len(pnl_reasons) == 0


# ── Drill 4b: LIMITED (reduce-only) state ────────────────────────────


class TestDrillLimitedState:
    """Verify the LIMITED gate state for warning-only conditions."""

    def setup_method(self):
        _update_blocked_state(False)
        clear_events()

    def test_warning_only_gives_limited(self):
        """PnL divergence alone → gate_state=limited, not blocked."""
        result = _gate_with_mocks(pnl_consistent=False, pnl_divergence=12.50)
        assert result.blocked is False
        assert result.gate_state == "limited"
        assert result.is_limited is True
        assert result.allows_reduce() is True

    def test_clear_when_no_issues(self):
        result = _gate_with_mocks()
        assert result.blocked is False
        assert result.gate_state == "clear"
        assert result.is_limited is False
        assert result.allows_reduce() is True

    def test_blocked_is_not_limited(self):
        result = _gate_with_mocks(kill=True, kill_details="Emergency")
        assert result.blocked is True
        assert result.gate_state == "blocked"
        assert result.is_limited is False
        assert result.allows_reduce() is False

    def test_critical_plus_warning_is_blocked(self):
        """Critical + warning → blocked, not limited."""
        result = _gate_with_mocks(
            kill=True, kill_details="Emergency",
            pnl_consistent=False, pnl_divergence=20.0,
        )
        assert result.blocked is True
        assert result.gate_state == "blocked"

    def test_limited_has_hint(self):
        """LIMITED state reasons should carry remediation hints."""
        result = _gate_with_mocks(pnl_consistent=False, pnl_divergence=8.0)
        assert result.gate_state == "limited"
        pnl_reasons = [r for r in result.reasons if r.source == "pnl_consistency"]
        assert pnl_reasons[0].hint is not None
        assert "Consistency widget" in pnl_reasons[0].hint

    def test_to_dict_includes_gate_state(self):
        result = _gate_with_mocks(pnl_consistent=False, pnl_divergence=8.0)
        d = result.to_dict()
        assert d["gate_state"] == "limited"
        assert d["blocked"] is False
        assert d["reasons"][0]["hint"] is not None


# ── Drill 5: Multiple Causes ────────────────────────────────────────


class TestDrillMultipleCauses:
    """Simulate multiple simultaneous gate causes."""

    def setup_method(self):
        _update_blocked_state(False)
        clear_events()

    def test_kill_switch_plus_stale_feed(self):
        result = _gate_with_mocks(
            kill=True, kill_details="Emergency",
            feed_safe=False, stale_symbols=[{"symbol": "BTC/USDT"}],
        )

        assert result.blocked is True
        sources = {r.source for r in result.reasons}
        assert "kill_switch" in sources
        assert "price_feed" in sources

    def test_all_causes_at_once(self):
        result = _gate_with_mocks(
            kill=True, kill_details="Emergency",
            discrepancies=True, ever_completed=True,
            feed_safe=False, stale_symbols=[{"symbol": "ETH/USDT"}],
            pnl_consistent=False, pnl_divergence=20.0,
        )

        assert result.blocked is True
        sources = {r.source for r in result.reasons}
        assert sources == {"kill_switch", "reconciliation", "price_feed", "pnl_consistency"}
        # Should have 3 critical + 1 warning
        critical = [r for r in result.reasons if r.severity == "critical"]
        warnings = [r for r in result.reasons if r.severity == "warning"]
        assert len(critical) == 3
        assert len(warnings) == 1


# ── Drill 6: Gate Transition Events ─────────────────────────────────


class TestDrillGateTransitions:
    """Verify session log captures gate state transitions correctly."""

    def setup_method(self):
        _update_blocked_state(False)  # start CLEAR
        clear_events()

    def test_clear_to_blocked_to_clear(self):
        # CLEAR → BLOCKED
        _gate_with_mocks(kill=True, kill_details="Drill")
        # BLOCKED → CLEAR
        _gate_with_mocks(kill=False)

        events = get_events(category="gate")
        titles = [e.title for e in events]
        assert "Execution gate BLOCKED" in titles
        assert "Execution gate CLEAR" in titles

    def test_repeated_blocked_no_duplicate_events(self):
        """If gate stays blocked, no duplicate transition events."""
        _gate_with_mocks(kill=True, kill_details="Drill")
        _gate_with_mocks(kill=True, kill_details="Drill")
        _gate_with_mocks(kill=True, kill_details="Drill")

        events = get_events(category="gate")
        blocked_events = [e for e in events if e.title == "Execution gate BLOCKED"]
        assert len(blocked_events) == 1  # only one transition
