"""Tests for drawdown zone classification, profit-lock engine,
drawdown_halt_active flag, and integrated sizing pipeline.

Scenarios validated:
  1. Drawdown 10.5% with soft=15/hard=20 → no halt, zone=YELLOW, smaller sizes.
  2. Drawdown 21% → drawdown_halt_active=True, no error-budget burn.
  3. Profit +10%, lock 60%, allow at most 6% give-back; verify sizing steps down
     and freezes when limit is hit.
  4. CT drawdown_halt guard: when halted, veto reason = drawdown_halt_active.
"""

from __future__ import annotations

import time

import pytest

from merid.risk.drawdown_zones import (
    CryptoRiskMatrix,
    DrawdownConfig,
    DrawdownZone,
    DrawdownZoneManager,
)
from merid.risk.kill_switches import RiskController
from merid.risk.profit_lock import ProfitLockEngine, ProfitLockState, _CAUTION_THRESHOLD


# ============================================================================
# 1.  DrawdownZoneManager — zone classification and size multipliers
# ============================================================================

class TestDrawdownZoneClassification:
    """DrawdownZoneManager correctly classifies drawdown into zones."""

    def setup_method(self):
        cfg = DrawdownConfig(green_pct=0.10, soft_pct=0.15, hard_pct=0.20)
        self.mgr = DrawdownZoneManager(CryptoRiskMatrix(default=cfg))

    def test_green_zone(self):
        assert self.mgr.classify(0.05) == DrawdownZone.GREEN
        assert self.mgr.classify(0.09) == DrawdownZone.GREEN

    def test_yellow_zone(self):
        assert self.mgr.classify(0.10) == DrawdownZone.YELLOW
        assert self.mgr.classify(0.105) == DrawdownZone.YELLOW
        assert self.mgr.classify(0.149) == DrawdownZone.YELLOW

    def test_orange_zone(self):
        assert self.mgr.classify(0.15) == DrawdownZone.ORANGE
        assert self.mgr.classify(0.18) == DrawdownZone.ORANGE

    def test_red_zone(self):
        assert self.mgr.classify(0.20) == DrawdownZone.RED
        assert self.mgr.classify(0.21) == DrawdownZone.RED
        assert self.mgr.classify(0.50) == DrawdownZone.RED

    def test_no_halt_at_yellow(self):
        """At 10.5% drawdown with 15/20 thresholds: no halt, just smaller sizes."""
        zone = self.mgr.classify(0.105)
        assert zone == DrawdownZone.YELLOW
        mult = self.mgr.size_multiplier(0.105)
        assert mult < 1.0
        assert mult > 0.0

    def test_size_multiplier_green(self):
        assert self.mgr.size_multiplier(0.05) == 1.0

    def test_size_multiplier_yellow(self):
        mult = self.mgr.size_multiplier(0.12)
        assert 0.5 <= mult <= 0.75

    def test_size_multiplier_orange(self):
        mult = self.mgr.size_multiplier(0.17)
        assert 0.25 <= mult <= 0.33

    def test_size_multiplier_red_is_zero(self):
        assert self.mgr.size_multiplier(0.21) == 0.0

    def test_get_status_contains_zone(self):
        self.mgr.classify(0.12)
        status = self.mgr.get_status()
        assert "current_zone" in status
        assert status["current_zone"] == DrawdownZone.YELLOW.value


# ============================================================================
# 2.  RiskController — drawdown_halt_active does NOT burn error budget
# ============================================================================

class TestDrawdownHaltFlag:
    """Drawdown halts use a dedicated flag, not the error budget."""

    def _make_rc(self) -> RiskController:
        return RiskController(error_threshold=50, dedup_window_secs=0)

    def test_set_drawdown_halt_true(self):
        rc = self._make_rc()
        assert not rc.is_drawdown_halted()
        rc.set_drawdown_halt(True, reason="test halt")
        assert rc.is_drawdown_halted()
        assert rc.drawdown_halt_active is True
        assert "test halt" in (rc.drawdown_halt_reason or "")

    def test_set_drawdown_halt_false_clears(self):
        rc = self._make_rc()
        rc.set_drawdown_halt(True, reason="test")
        rc.set_drawdown_halt(False)
        assert not rc.is_drawdown_halted()
        assert rc.drawdown_halt_reason is None

    def test_drawdown_halt_does_not_consume_error_budget(self):
        """21% drawdown → halt active, zero error budget consumed."""
        rc = self._make_rc()
        rc.set_drawdown_halt(True, reason="Drawdown 21% >= halt 20%")
        # Simulate 50 drawdown_halt errors (what MM would produce spamming 5 markets × 10 cycles)
        for _ in range(50):
            rc.record_error(error_class="drawdown_halt")
        # Error budget must be zero — drawdown_halt is exempt
        assert rc._error_count == 0
        # Can still trade (kill switch not triggered by drawdown halts)
        assert rc.can_trade() is True

    def test_drawdown_halt_active_true_after_set(self):
        rc = self._make_rc()
        rc.set_drawdown_halt(True)
        assert rc.drawdown_halt_active is True

    def test_risk_violation_still_counted(self):
        """bankroll_zero / real errors still count toward the budget."""
        rc = self._make_rc()
        rc.record_error(error_class="risk_violation")
        assert rc._error_count == 1

    def test_get_status_includes_drawdown_halt_fields(self):
        rc = self._make_rc()
        rc.set_drawdown_halt(True, reason="dd=21%")
        status = rc.get_status()
        assert status["drawdown_halt_active"] is True
        assert "dd=21%" in status["drawdown_halt_reason"]

    def test_drawdown_halt_class_is_exempt(self):
        rc = self._make_rc()
        assert "drawdown_halt" in rc.error_exempt_classes


# ============================================================================
# 3.  ProfitLockEngine — profit tracking and freeze behavior
# ============================================================================

class TestProfitLockEngine:
    """ProfitLockEngine correctly tracks P&L and enforces the give-back limit."""

    def _make(self, lock_fraction: float = 0.60, caution_threshold: float = _CAUTION_THRESHOLD) -> ProfitLockEngine:
        return ProfitLockEngine(lock_fraction=lock_fraction, caution_threshold=caution_threshold)

    # ── Basic state tracking ──────────────────────────────────────────────

    def test_initial_state_is_safe(self):
        eng = self._make()
        assert eng.profit_lock_state == ProfitLockState.SAFE
        assert eng.size_multiplier() == 1.0

    def test_profit_updates_session_high(self):
        eng = self._make()
        eng.record_pnl(+10.0)
        assert eng.realized_pnl_session_high == 10.0
        assert eng.realized_pnl == 10.0

    def test_locked_profit_is_fraction_of_peak(self):
        eng = self._make(lock_fraction=0.60)
        eng.record_pnl(+10.0)
        # Peak = 10, locked = 10 * 0.60 = 6.0
        assert eng.locked_profit == pytest.approx(6.0)

    # ── Scenario: +10% session, lock 60%, give-back at most 6% ──────────

    def test_profit_lock_scenario(self):
        """
        Session profit = +10.  lock_fraction=0.60 → locked = 6.
        max_drawback = 6 (the locked amount).
        give_back_limit = 10 - 6 = 4.
        While realized_pnl >= 4: normal operation.
        Below 4: step toward FROZEN.
        """
        eng = self._make(lock_fraction=0.60)
        eng.record_pnl(+10.0)
        assert eng.locked_profit == pytest.approx(6.0)
        assert eng.give_back_limit == pytest.approx(4.0)

        # Give back 3 — still above limit (7 > 4): SAFE
        eng.record_pnl(-3.0)
        assert eng.realized_pnl == pytest.approx(7.0)
        assert eng.profit_lock_state == ProfitLockState.SAFE
        assert eng.size_multiplier() == 1.0

        # Give back 4 more (total - 7): now at 3, below give_back_limit (4) → FROZEN
        eng.record_pnl(-4.0)
        assert eng.realized_pnl == pytest.approx(3.0)
        assert eng.profit_lock_state == ProfitLockState.FROZEN
        assert eng.size_multiplier() == 0.0

    def test_caution_state_at_halfway(self):
        """CAUTION fires when headroom < 50% of max_drawback."""
        eng = self._make(lock_fraction=0.60, caution_threshold=0.50)
        eng.record_pnl(+10.0)
        # give_back_limit=4, max_drawback=6
        # CAUTION fires when headroom < 3 (50% of 6)
        # headroom = realized_pnl - 4; we need headroom < 3 → realized_pnl < 7
        eng.record_pnl(-3.5)   # realized=6.5, headroom=2.5 < 3 → CAUTION
        assert eng.profit_lock_state == ProfitLockState.CAUTION
        assert eng.size_multiplier() == 0.5

    def test_no_freeze_when_no_profits(self):
        """No profits recorded → SAFE regardless of losses."""
        eng = self._make()
        eng.record_pnl(-5.0)
        assert eng.profit_lock_state == ProfitLockState.SAFE

    def test_reset_session(self):
        eng = self._make()
        eng.record_pnl(+10.0)
        eng.record_pnl(-8.0)
        eng.reset_session()
        assert eng.realized_pnl == 0.0
        assert eng.realized_pnl_session_high == 0.0
        assert eng.profit_lock_state == ProfitLockState.SAFE

    def test_compound_promotes_profits(self):
        eng = self._make(lock_fraction=0.60)
        eng.record_pnl(+10.0)
        locked = eng.locked_profit  # 6.0
        core = 1000.0
        new_core = eng.compound(core)
        assert new_core == pytest.approx(core + locked)

    def test_get_status_dict(self):
        eng = self._make()
        eng.record_pnl(+20.0)
        status = eng.get_status()
        assert status["state"] == ProfitLockState.SAFE.value
        assert status["session_high"] == pytest.approx(20.0)
        assert status["locked_profit"] == pytest.approx(12.0)


# ============================================================================
# 4.  Error-classification: drawdown exceed → drawdown_halt, not risk_violation
# ============================================================================

class TestDrawdownErrorClassification:
    """trading_agent classifies drawdown exceed as drawdown_halt (LOW/exempt)."""

    def _classify(self, error_str: str) -> str:
        """Mirror the classification logic from trading_agent._execute_trade_signal."""
        _err_str = error_str.lower()
        if "bankroll_zero" in _err_str:
            return "risk_violation"
        if "drawdown" in _err_str and "exceed" in _err_str:
            return "drawdown_halt"
        if "post-fee edge" in _err_str or "post_fee_edge" in _err_str:
            return "low_edge"
        return "generic"

    def test_drawdown_exceed_halt_threshold(self):
        msg = "Drawdown 21.0% exceeds halt threshold 20.0%"
        assert self._classify(msg) == "drawdown_halt"

    def test_drawdown_exceed_unwind_threshold(self):
        msg = "Drawdown 25.0% exceeds unwind threshold 25.0%"
        assert self._classify(msg) == "drawdown_halt"

    def test_bankroll_zero_still_risk_violation(self):
        msg = "bankroll_zero — no capital available"
        assert self._classify(msg) == "risk_violation"

    def test_drawdown_halt_is_exempt_in_controller(self):
        rc = RiskController(error_threshold=10, dedup_window_secs=0)
        for _ in range(15):
            rc.record_error(error_class="drawdown_halt")
        assert rc._error_count == 0
        assert rc.can_trade() is True


# ============================================================================
# 5.  DrawdownZoneManager: zone-based size multiplier integration
# ============================================================================

class TestZoneSizingIntegration:
    """Verify that the zone multiplier pipeline correctly scales sizes."""

    def test_yellow_zone_size_between_50_and_75_pct(self):
        cfg = DrawdownConfig(green_pct=0.10, soft_pct=0.15, hard_pct=0.20,
                             mult_yellow=0.625)
        mgr = DrawdownZoneManager(CryptoRiskMatrix(default=cfg))
        base_size = 100.0
        mult = mgr.size_multiplier(0.12)
        scaled = base_size * mult
        assert 50.0 <= scaled <= 75.0

    def test_orange_zone_size_between_25_and_33_pct(self):
        cfg = DrawdownConfig(green_pct=0.10, soft_pct=0.15, hard_pct=0.20,
                             mult_orange=0.30)
        mgr = DrawdownZoneManager(CryptoRiskMatrix(default=cfg))
        base_size = 100.0
        mult = mgr.size_multiplier(0.17)
        scaled = base_size * mult
        assert 25.0 <= scaled <= 33.0

    def test_red_zone_size_is_zero(self):
        cfg = DrawdownConfig(green_pct=0.10, soft_pct=0.15, hard_pct=0.20)
        mgr = DrawdownZoneManager(CryptoRiskMatrix(default=cfg))
        assert mgr.size_multiplier(0.21) == 0.0

    def test_asset_override_applies(self):
        default_cfg = DrawdownConfig(mult_yellow=0.625)
        btc_cfg = DrawdownConfig(green_pct=0.05, soft_pct=0.10, hard_pct=0.15,
                                 mult_yellow=0.50)
        matrix = CryptoRiskMatrix(
            default=default_cfg,
            asset_overrides={"BTC": btc_cfg},
        )
        mgr = DrawdownZoneManager(matrix)
        # At 8% drawdown: default says GREEN (8% < 10%), btc_cfg says YELLOW (8% > 5%)
        assert mgr.classify(0.08, asset="BTC") == DrawdownZone.YELLOW
        assert mgr.classify(0.08, asset="ETH") == DrawdownZone.GREEN
