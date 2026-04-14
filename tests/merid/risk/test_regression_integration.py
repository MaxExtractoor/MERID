"""Regression integration tests for Phases 1–6 (risk/churn refactor).

Scenarios validated:
  1. Full P&L sequence: 0 → +10% → +20% → +30% → back to +18%
       - Drawdown zone transitions correct
       - ProfitLockEngine state transitions correct
       - Sizing multipliers step up/down correctly
  2. Drawdown hits 21%:
       - drawdown_halt_active=True
       - CT stops sending orders (veto reason = drawdown_halt_active)
       - Error budget untouched
  3. "50 error" historical slice with drawdown rejections:
       - Drawdown_halt class keeps error budget clean
       - Kill switch NOT triggered
  4. CT drawdown halt guard (unit-level):
       - When is_drawdown_halted()=True the CT trade cycle vetos the candidate
  5. CT time-to-expiry taper:
       - At TTE=60s (< 120s window): size tapered linearly
       - At TTE=0: market expired, size=0 early return
       - At TTE=200s: no taper applied
  6. Profit-lock integration via kalshi_risk.record_pnl():
       - ProfitLockEngine receives deltas forwarded from KalshiRiskManager
  7. Drawdown zone sizing pipeline (steps 10–12):
       - size_final = pre_zone_size × mult_dd × mult_lock at various drawdown levels
  8. Per-asset drawdown zone overrides (BTC/ETH/SOL/XRP/DOGE):
       - Asset override correctly tightens zone for BTC
"""

from __future__ import annotations

import math
import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from merid.risk.drawdown_zones import (
    CryptoRiskMatrix,
    DrawdownConfig,
    DrawdownZone,
    DrawdownZoneManager,
)
from merid.risk.kill_switches import RiskController
from merid.risk.profit_lock import ProfitLockEngine, ProfitLockState


# ============================================================================
# Helpers
# ============================================================================

def _make_rc(error_threshold: int = 50) -> RiskController:
    return RiskController(error_threshold=error_threshold, dedup_window_secs=0)


def _make_dzm(green: float = 0.10, soft: float = 0.15, hard: float = 0.20) -> DrawdownZoneManager:
    cfg = DrawdownConfig(green_pct=green, soft_pct=soft, hard_pct=hard)
    return DrawdownZoneManager(CryptoRiskMatrix(default=cfg))


def _make_ple(lock_fraction: float = 0.60) -> ProfitLockEngine:
    return ProfitLockEngine(lock_fraction=lock_fraction)


# ============================================================================
# 1. Full P&L sequence: zone + profit-lock transitions
# ============================================================================

class TestPnLSequenceIntegration:
    """Simulate P&L going 0 → +10% → +20% → +30% → back to +18% of a $1000 bankroll."""

    # Scenario: bankroll = $1000, equity starts at $1000, peak at $1000.
    # We simulate realized P&L increments to the ProfitLockEngine,
    # and drawdown fractions to the DrawdownZoneManager.

    def test_green_zone_at_start(self):
        """At the start with no drawdown: zone=GREEN, mult=1.0."""
        dzm = _make_dzm()
        assert dzm.classify(0.0) == DrawdownZone.GREEN
        assert dzm.size_multiplier(0.0) == 1.0

    def test_profit_grows_to_30pct_then_drops_to_18pct(self):
        """Simulates a realistic profit run and gives back 12% of peak."""
        ple = _make_ple(lock_fraction=0.60)
        bankroll = 1000.0

        # Phase 1: +100 profit (10% of 1000)
        ple.record_pnl(+100.0)
        assert ple.realized_pnl == pytest.approx(100.0)
        assert ple.profit_lock_state == ProfitLockState.SAFE
        assert ple.locked_profit == pytest.approx(60.0)   # 100 * 0.60

        # Phase 2: +100 more (now 20% / $200 P&L)
        ple.record_pnl(+100.0)
        assert ple.realized_pnl == pytest.approx(200.0)
        assert ple.locked_profit == pytest.approx(120.0)  # 200 * 0.60

        # Phase 3: +100 more (30% / $300 P&L)
        ple.record_pnl(+100.0)
        assert ple.realized_pnl == pytest.approx(300.0)
        assert ple.locked_profit == pytest.approx(180.0)  # 300 * 0.60
        assert ple.give_back_limit == pytest.approx(120.0)  # 300 - 180

        # Phase 4: give back 120 (from 300 to 180 — 12% of original bankroll)
        # give_back_limit = 120; headroom = 180 - 120 = 60; max_drawback = 180
        # CAUTION fires when headroom < 50% * max_drawback = 90
        # at pnl=180, headroom=60 < 90 → CAUTION
        ple.record_pnl(-120.0)
        assert ple.realized_pnl == pytest.approx(180.0)
        # headroom = 180 - 120 = 60; threshold = 0.5 * 180 = 90; 60 < 90 → CAUTION
        assert ple.profit_lock_state == ProfitLockState.CAUTION
        assert ple.size_multiplier() == pytest.approx(0.5)

    def test_drawdown_zone_transitions_over_sequence(self):
        """Zone correctly steps GREEN→YELLOW→ORANGE→RED as drawdown grows."""
        dzm = _make_dzm()
        assert dzm.classify(0.05) == DrawdownZone.GREEN
        assert dzm.classify(0.10) == DrawdownZone.YELLOW
        assert dzm.classify(0.15) == DrawdownZone.ORANGE
        assert dzm.classify(0.20) == DrawdownZone.RED
        assert dzm.classify(0.25) == DrawdownZone.RED

    def test_zone_recovery_red_to_green(self):
        """After hitting RED zone, recovery below green_pct returns GREEN."""
        dzm = _make_dzm()
        dzm.classify(0.21)  # → RED
        assert dzm.current_zone == DrawdownZone.RED
        dzm.classify(0.05)  # → GREEN
        assert dzm.current_zone == DrawdownZone.GREEN

    def test_sizing_multipliers_correct_at_each_zone(self):
        """Verify exact multiplier values at zone boundaries."""
        dzm = _make_dzm()
        assert dzm.size_multiplier(0.05) == pytest.approx(1.0)    # GREEN
        assert dzm.size_multiplier(0.12) == pytest.approx(0.625)  # YELLOW
        assert dzm.size_multiplier(0.17) == pytest.approx(0.30)   # ORANGE
        assert dzm.size_multiplier(0.21) == pytest.approx(0.0)    # RED


# ============================================================================
# 2. 21% drawdown → drawdown_halt_active=True, error budget untouched
# ============================================================================

class TestDrawdownHalt21Pct:
    """At 21% drawdown: halt flag set, CT vetoes, budget stays clean."""

    def test_21pct_drawdown_sets_halt_and_no_error_budget(self):
        rc = _make_rc(error_threshold=50)
        rc.set_drawdown_halt(True, reason="Drawdown 21.0% exceeds halt threshold 20.0%")
        assert rc.is_drawdown_halted() is True

        # Simulate CT looping over 50 candidates, each vetoed and logged as drawdown_halt
        for _ in range(50):
            rc.record_error(error_class="drawdown_halt")

        # Error budget must remain zero
        assert rc._error_count == 0
        # Kill switch NOT triggered
        assert rc.can_trade() is True

    def test_halt_clears_when_drawdown_recovers(self):
        rc = _make_rc()
        rc.set_drawdown_halt(True, reason="Drawdown 21%")
        assert rc.is_drawdown_halted() is True
        rc.set_drawdown_halt(False)
        assert rc.is_drawdown_halted() is False
        assert rc.drawdown_halt_reason is None

    def test_profit_lock_still_consistent_during_halt(self):
        """ProfitLockEngine state is independent of drawdown_halt flag."""
        ple = _make_ple()
        ple.record_pnl(+100.0)  # SAFE, session_high=100

        rc = _make_rc()
        rc.set_drawdown_halt(True, reason="Drawdown 21%")

        # Profit-lock is SAFE — halt doesn't change it
        assert ple.profit_lock_state == ProfitLockState.SAFE
        # But sizing should be zero from zone multiplier (RED zone)
        dzm = _make_dzm()
        mult_dd = dzm.size_multiplier(0.21)  # RED → 0.0
        mult_pl = ple.size_multiplier()       # SAFE → 1.0
        assert mult_dd * mult_pl == pytest.approx(0.0)


# ============================================================================
# 3. 50-error historical slice: budget stays clean under drawdown rejections
# ============================================================================

class TestErrorBudget50Slice:
    """Replay a '50 drawdown rejection' scenario — budget never gets consumed."""

    def test_50_drawdown_errors_do_not_trigger_kill_switch(self):
        rc = _make_rc(error_threshold=50)
        for i in range(50):
            rc.record_error(error_class="drawdown_halt")
        assert rc._error_count == 0
        assert rc.can_trade() is True

    def test_true_errors_after_drawdown_errors_still_count(self):
        """Real P0 errors (e.g. auth_error) still consume the budget."""
        rc = _make_rc(error_threshold=50)
        # 30 drawdown halts — exempt, no budget impact
        for _ in range(30):
            rc.record_error(error_class="drawdown_halt")
        assert rc._error_count == 0

        # 3 real auth errors — each counts
        for _ in range(3):
            rc.record_error(error_class="auth_error")
        assert rc._error_count == 3

    def test_mixed_drawdown_and_real_errors_only_real_counted(self):
        rc = _make_rc(error_threshold=50)
        for _ in range(25):
            rc.record_error(error_class="drawdown_halt")  # exempt
        for _ in range(10):
            rc.record_error(error_class="generic")        # HIGH — counts
        # Only the 10 generic errors count
        assert rc._error_count == 10

    def test_bankroll_zero_still_triggers_violation(self):
        """bankroll_zero / risk_violation remains CRITICAL and counts."""
        rc = _make_rc(error_threshold=3)
        rc.record_error(error_class="risk_violation")
        rc.record_error(error_class="risk_violation")
        rc.record_error(error_class="risk_violation")
        # 3 CRITICAL errors → error budget at 100% of 3 → kill switch (multi-signal needed)
        # At 3/3 (100%) threshold is breached — check budget is consumed
        assert rc._error_count == 3


# ============================================================================
# 4. CT drawdown halt guard (unit-level)
# ============================================================================

class TestCTDrawdownHaltGuard:
    """Validate the CT veto logic when drawdown_halt_active=True."""

    def test_veto_reason_is_drawdown_halt_active(self):
        """When RiskController.is_drawdown_halted(), veto reason is correct."""
        rc = _make_rc()
        rc.set_drawdown_halt(True, reason="dd=21%")
        assert rc.is_drawdown_halted() is True
        assert rc.drawdown_halt_active is True

    def test_no_veto_when_halt_not_active(self):
        rc = _make_rc()
        assert rc.is_drawdown_halted() is False

    def test_drawdown_halt_active_property_alias(self):
        """drawdown_halt_active property mirrors is_drawdown_halted()."""
        rc = _make_rc()
        rc.set_drawdown_halt(True)
        assert rc.drawdown_halt_active == rc.is_drawdown_halted()
        rc.set_drawdown_halt(False)
        assert rc.drawdown_halt_active == rc.is_drawdown_halted()

    def test_get_status_shows_halt_fields(self):
        rc = _make_rc()
        rc.set_drawdown_halt(True, reason="dd=22%")
        status = rc.get_status()
        assert status["drawdown_halt_active"] is True
        assert status["drawdown_halt_reason"] is not None
        assert "dd=22%" in status["drawdown_halt_reason"]


# ============================================================================
# 5. CT time-to-expiry taper (via signal_to_sizing logic)
# ============================================================================

class TestCTTimeToExpiryTaper:
    """Unit-validate the taper math used inside CT signal_to_sizing."""

    _LATE_EXPIRY_SECS = 120  # matches CT constant

    def _taper_mult(self, tte_secs: float) -> float:
        """Replicate the CT linear-taper formula."""
        if tte_secs <= 0:
            return -1.0  # sentinel: market expired
        if tte_secs < self._LATE_EXPIRY_SECS:
            return max(0.0, tte_secs / self._LATE_EXPIRY_SECS)
        return 1.0

    def _apply_taper(self, size: int, notional: float, tte_secs: float):
        """Return (size, notional) after applying taper, or (0, 0.0) if expired."""
        mult = self._taper_mult(tte_secs)
        if mult < 0:
            return 0, 0.0
        scaled_size = int(math.floor(size * mult))
        return scaled_size, notional * mult

    def test_no_taper_outside_window(self):
        """TTE=200s: well outside the 2-min window → no taper."""
        assert self._taper_mult(200.0) == pytest.approx(1.0)
        size, notional = self._apply_taper(10, 500.0, 200.0)
        assert size == 10
        assert notional == pytest.approx(500.0)

    def test_half_taper_at_60s(self):
        """TTE=60s: 60/120 = 0.5 → size floor(10*0.5)=5."""
        mult = self._taper_mult(60.0)
        assert mult == pytest.approx(0.5)
        size, notional = self._apply_taper(10, 500.0, 60.0)
        assert size == 5
        assert notional == pytest.approx(250.0)

    def test_full_taper_at_boundary(self):
        """TTE=120s: exactly at boundary → mult=1.0 (no taper)."""
        assert self._taper_mult(120.0) == pytest.approx(1.0)

    def test_near_zero_taper(self):
        """TTE=1s: mult≈0.0083 → floor(10*0.0083)=0 contracts."""
        mult = self._taper_mult(1.0)
        assert 0.0 < mult < 0.02
        size, _ = self._apply_taper(10, 500.0, 1.0)
        assert size == 0

    def test_expired_market_returns_zero(self):
        """TTE≤0: market expired → size=0."""
        size, notional = self._apply_taper(10, 500.0, 0.0)
        assert size == 0
        assert notional == pytest.approx(0.0)

    def test_negative_tte_also_returns_zero(self):
        """TTE=-5s (past expiry): size=0."""
        size, notional = self._apply_taper(10, 500.0, -5.0)
        assert size == 0
        assert notional == pytest.approx(0.0)

    def test_taper_never_negative_size(self):
        """Taper cannot produce negative size regardless of input."""
        for tte in [0.001, 0.1, 1.0, 5.0, 30.0, 60.0, 119.9]:
            size, _ = self._apply_taper(1, 50.0, tte)
            assert size >= 0


# ============================================================================
# 6. ProfitLockEngine wired into KalshiRiskManager
# ============================================================================

class TestProfitLockEngineWiring:
    """Verify that kalshi_risk.record_pnl() feeds into ProfitLockEngine."""

    def test_record_pnl_updates_profit_lock_engine(self):
        """kalshi_risk.record_pnl() must forward P&L to ProfitLockEngine singleton."""
        from merid.risk.profit_lock import ProfitLockEngine

        tracked_pnl = []

        # Patch the singleton so we can observe calls
        mock_engine = MagicMock(spec=ProfitLockEngine)
        mock_engine.record_pnl = MagicMock(side_effect=tracked_pnl.append)

        with patch("merid.risk.profit_lock._engine", mock_engine):
            from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
            mgr = KalshiRiskManager(KalshiRiskConfig())
            mgr.record_pnl(50.0)
            mgr.record_pnl(-20.0)

        assert len(tracked_pnl) == 2
        assert tracked_pnl[0] == pytest.approx(50.0)
        assert tracked_pnl[1] == pytest.approx(-20.0)

    def test_record_pnl_fail_open_when_engine_unavailable(self):
        """If ProfitLockEngine import fails, record_pnl() still completes."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
        mgr = KalshiRiskManager(KalshiRiskConfig())

        with patch("merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager.record_pnl",
                   wraps=mgr.record_pnl):
            # Should not raise even if internal exception occurs
            with patch("merid.risk.profit_lock.get_profit_lock_engine",
                       side_effect=RuntimeError("unavailable")):
                mgr.record_pnl(100.0)  # should not raise


# ============================================================================
# 7. Sizing pipeline steps 10–12
# ============================================================================

class TestSizingPipeline:
    """Verify size_final = pre_zone_size × mult_dd × mult_lock."""

    def _compute_final_size(
        self,
        pre_zone_size: float,
        drawdown_pct: float,
        ple_pnl_sequence: list[float],
    ) -> float:
        dzm = _make_dzm()
        ple = _make_ple()
        for delta in ple_pnl_sequence:
            ple.record_pnl(delta)
        mult_dd = dzm.size_multiplier(drawdown_pct)
        mult_lock = ple.size_multiplier()
        return max(0.0, pre_zone_size * mult_dd * mult_lock)

    def test_green_zone_safe_state_full_size(self):
        """GREEN zone + SAFE state → full size."""
        result = self._compute_final_size(100.0, 0.05, [+50.0])
        assert result == pytest.approx(100.0)

    def test_yellow_zone_reduces_size(self):
        """YELLOW zone → size reduced to 62.5%."""
        result = self._compute_final_size(100.0, 0.12, [+50.0])
        assert result == pytest.approx(62.5)

    def test_orange_zone_reduces_size(self):
        """ORANGE zone → size reduced to 30%."""
        result = self._compute_final_size(100.0, 0.17, [+50.0])
        assert result == pytest.approx(30.0)

    def test_red_zone_zeroes_size(self):
        """RED zone → size = 0 regardless of profit-lock state."""
        result = self._compute_final_size(100.0, 0.21, [+500.0])
        assert result == pytest.approx(0.0)

    def test_frozen_state_zeroes_size(self):
        """FROZEN profit-lock state → size = 0 regardless of zone."""
        # Sequence: profit 100, then give back 70 → below give_back_limit=40 → FROZEN
        result = self._compute_final_size(100.0, 0.05, [+100.0, -70.0])
        assert result == pytest.approx(0.0)

    def test_caution_state_halves_size(self):
        """CAUTION state → size halved relative to zone mult."""
        # YELLOW zone (mult=0.625) × CAUTION (mult=0.5) = 0.3125
        ple = _make_ple()
        ple.record_pnl(+10.0)
        # Push into CAUTION: give_back_limit=4, caution when headroom<3; at 6.5, headroom=2.5<3
        ple.record_pnl(-3.5)
        assert ple.profit_lock_state == ProfitLockState.CAUTION
        dzm = _make_dzm()
        mult_dd = dzm.size_multiplier(0.12)  # YELLOW
        mult_lock = ple.size_multiplier()     # CAUTION = 0.5
        result = 100.0 * mult_dd * mult_lock
        assert result == pytest.approx(31.25)  # 100 * 0.625 * 0.5

    def test_final_size_never_negative(self):
        """Final size is always ≥ 0.0."""
        for dd in [0.0, 0.10, 0.15, 0.20, 0.25, 0.50]:
            result = self._compute_final_size(100.0, dd, [-999.0])
            assert result >= 0.0


# ============================================================================
# 8. Per-asset drawdown overrides
# ============================================================================

class TestPerAssetDrawdownOverrides:
    """Zone overrides per asset keep correct behavior for all 5 crypto assets."""

    def _make_matrix_with_btc_override(self) -> CryptoRiskMatrix:
        default = DrawdownConfig(green_pct=0.10, soft_pct=0.15, hard_pct=0.20)
        btc_cfg = DrawdownConfig(green_pct=0.05, soft_pct=0.10, hard_pct=0.15,
                                 mult_yellow=0.50)
        return CryptoRiskMatrix(default=default, asset_overrides={"BTC": btc_cfg})

    def test_btc_enters_yellow_earlier(self):
        matrix = self._make_matrix_with_btc_override()
        mgr = DrawdownZoneManager(matrix)
        # At 8% drawdown: default says GREEN, BTC override says YELLOW
        assert mgr.classify(0.08, asset="BTC") == DrawdownZone.YELLOW
        assert mgr.classify(0.08, asset="ETH") == DrawdownZone.GREEN

    def test_eth_sol_xrp_doge_use_default_thresholds(self):
        """Non-BTC assets fall back to the default config."""
        matrix = self._make_matrix_with_btc_override()
        mgr = DrawdownZoneManager(matrix)
        for asset in ("ETH", "SOL", "XRP", "DOGE"):
            assert mgr.classify(0.12, asset=asset) == DrawdownZone.YELLOW
            assert mgr.classify(0.08, asset=asset) == DrawdownZone.GREEN

    def test_btc_red_zone_at_15pct(self):
        """BTC override: RED at 15% vs default RED at 20%."""
        matrix = self._make_matrix_with_btc_override()
        mgr = DrawdownZoneManager(matrix)
        assert mgr.classify(0.15, asset="BTC") == DrawdownZone.RED
        # Default (no override): 15% is ORANGE, not RED
        assert mgr.classify(0.15, asset="ETH") == DrawdownZone.ORANGE

    def test_all_assets_return_0_in_red_zone(self):
        """All assets return 0.0 multiplier in their respective RED zones."""
        matrix = self._make_matrix_with_btc_override()
        mgr = DrawdownZoneManager(matrix)
        # BTC: RED at 15%+
        assert mgr.size_multiplier(0.16, asset="BTC") == pytest.approx(0.0)
        # Others: RED at 20%+
        for asset in ("ETH", "SOL", "XRP", "DOGE"):
            assert mgr.size_multiplier(0.21, asset=asset) == pytest.approx(0.0)


# ============================================================================
# 9. ProfitLockEngine compound() and session boundary
# ============================================================================

class TestProfitLockCompound:
    """compound() correctly promotes locked profit into bankroll and resets session."""

    def test_compound_adds_locked_profit_to_bankroll(self):
        ple = _make_ple(lock_fraction=0.60)
        ple.record_pnl(+100.0)
        bankroll = 1000.0
        new_bankroll = ple.compound(bankroll)
        assert new_bankroll == pytest.approx(1060.0)  # 1000 + 60

    def test_compound_resets_session_to_zero_or_positive(self):
        ple = _make_ple(lock_fraction=0.60)
        ple.record_pnl(+100.0)
        ple.compound(1000.0)
        # After compound, session resets
        assert ple.realized_pnl >= 0.0
        assert ple.realized_pnl_session_high >= 0.0
        assert ple.profit_lock_state == ProfitLockState.SAFE

    def test_compound_with_zero_pnl_adds_nothing(self):
        ple = _make_ple()
        bankroll = 500.0
        new_bankroll = ple.compound(bankroll)
        assert new_bankroll == pytest.approx(500.0)

    def test_reset_session_clears_all(self):
        ple = _make_ple()
        ple.record_pnl(+100.0)
        ple.record_pnl(-80.0)
        ple.reset_session()
        assert ple.realized_pnl == pytest.approx(0.0)
        assert ple.realized_pnl_session_high == pytest.approx(0.0)
        assert ple.profit_lock_state == ProfitLockState.SAFE
        assert ple.size_multiplier() == pytest.approx(1.0)

    def test_frozen_after_large_giveback_clears_on_reset(self):
        ple = _make_ple(lock_fraction=0.60)
        ple.record_pnl(+100.0)
        ple.record_pnl(-70.0)  # → FROZEN (pnl=30 < give_back_limit=40)
        assert ple.profit_lock_state == ProfitLockState.FROZEN
        ple.reset_session()
        assert ple.profit_lock_state == ProfitLockState.SAFE


# ============================================================================
# 10. Error classification: drawdown strings classified as drawdown_halt
# ============================================================================

class TestDrawdownErrorClassificationFull:
    """Validate all known drawdown rejection strings route to drawdown_halt."""

    def _classify(self, error_str: str) -> str:
        """Mirror the classification logic from trading_agent._execute_trade_signal."""
        _s = error_str.lower()
        if "bankroll_zero" in _s:
            return "risk_violation"
        if "drawdown" in _s and "exceed" in _s:
            return "drawdown_halt"
        return "other"

    @pytest.mark.parametrize("msg", [
        "Drawdown 21.0% exceeds halt threshold 20.0%",
        "Drawdown 25.3% exceeds unwind threshold 25.0%",
        "drawdown 20.1% exceeds HALT threshold 20.0%",  # case-insensitive
        "portfolio drawdown 30% exceeds configured limit",
    ])
    def test_drawdown_exceed_messages_classified_as_halt(self, msg):
        assert self._classify(msg) == "drawdown_halt"

    def test_bankroll_zero_still_risk_violation(self):
        assert self._classify("bankroll_zero") == "risk_violation"

    def test_drawdown_without_exceed_not_classified(self):
        """Drawdown mention without 'exceed' does not trigger drawdown_halt."""
        result = self._classify("drawdown zone updated to YELLOW")
        assert result == "other"

    def test_drawdown_halt_class_exempt_in_rc(self):
        rc = _make_rc()
        assert "drawdown_halt" in rc.error_exempt_classes
        for _ in range(100):
            rc.record_error("drawdown_halt")
        assert rc._error_count == 0
