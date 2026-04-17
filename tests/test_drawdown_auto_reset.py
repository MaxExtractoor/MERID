"""Tests for drawdown auto-reset functionality.

This verifies the fixes for:
1. KalshiRiskEngine.check_drawdown() auto-resets halt when drawdown recovers
2. KalshiRiskManager.record_equity_snapshot() auto-resets kill switch when drawdown recovers
"""

import pytest
from decimal import Decimal


class TestKalshiRiskEngineDrawdownAutoReset:
    """Test auto-reset logic in KalshiRiskEngine."""

    def test_auto_reset_when_drawdown_recovers(self):
        """Verify halt is auto-reset when drawdown drops below reduce threshold."""
        from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine, KalshiRiskConfig

        config = KalshiRiskConfig(
            drawdown_halt_pct=0.20,  # 20% halt
            drawdown_reduce_pct=0.10,  # 10% reduce
        )
        engine = KalshiRiskEngine(config)

        # Set initial peak
        engine.update_peak(10000)  # $100.00
        assert engine.peak_balance_cents == 10000
        assert not engine.is_halted

        # Trigger halt with 25% drawdown (equity = $75.00)
        result = engine.check_drawdown(7500)
        assert not result  # Trading not allowed
        assert engine.is_halted
        assert "Drawdown 25.0% >= halt threshold" in engine.halt_reason

        # Recovery: drawdown drops to 5% (equity = $95.00) - below reduce threshold
        result = engine.check_drawdown(9500)
        assert result  # Trading allowed again
        assert not engine.is_halted
        assert engine.halt_reason == ""

    def test_no_reset_when_still_in_reduce_zone(self):
        """Verify halt is NOT reset when drawdown is still above reduce threshold."""
        from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine, KalshiRiskConfig

        config = KalshiRiskConfig(
            drawdown_halt_pct=0.20,
            drawdown_reduce_pct=0.10,
        )
        engine = KalshiRiskEngine(config)

        # Set initial peak and trigger halt
        engine.update_peak(10000)
        engine.check_drawdown(7500)  # 25% drawdown - halt triggered
        assert engine.is_halted

        # Partial recovery: 15% drawdown - still above reduce threshold
        result = engine.check_drawdown(8500)  # 15% drawdown
        assert not result  # Still halted because 15% > 10% reduce threshold
        assert engine.is_halted

    def test_reset_only_when_previously_halted(self):
        """Verify no special handling when not previously halted."""
        from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine, KalshiRiskConfig

        config = KalshiRiskConfig(
            drawdown_halt_pct=0.20,
            drawdown_reduce_pct=0.10,
        )
        engine = KalshiRiskEngine(config)

        # Set peak but never halt
        engine.update_peak(10000)
        result = engine.check_drawdown(9500)  # 5% drawdown
        assert result  # Trading allowed
        assert not engine.is_halted


class TestKalshiRiskManagerKillSwitchAutoReset:
    """Test auto-reset logic in KalshiRiskManager."""

    def test_kill_switch_auto_reset_on_recovery(self):
        """Verify kill switch auto-resets when drawdown recovers below unwind threshold."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig, RiskState

        config = KalshiRiskConfig(
            drawdown_halt_pct=0.15,  # 15% halt
            drawdown_unwind_pct=0.08,  # 8% unwind
        )
        risk_manager = KalshiRiskManager(config)

        # Simulate a kill switch activation due to drawdown
        risk_manager._state.peak_equity_usd = 1000.0
        risk_manager._state.current_equity_usd = 700.0  # 30% drawdown
        risk_manager._state.kill_switch_active = True
        risk_manager._state.kill_switch_reason = "drawdown_halt"

        # Recovery: equity back to $950 (5% drawdown, below 8% unwind threshold)
        risk_manager.record_equity_snapshot(950.0)

        # Kill switch should be auto-reset
        assert not risk_manager._state.kill_switch_active
        assert risk_manager._state.kill_switch_reason is None

    def test_kill_switch_not_reset_when_still_high_drawdown(self):
        """Verify kill switch stays active when drawdown still above unwind threshold."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig

        config = KalshiRiskConfig(
            drawdown_halt_pct=0.15,
            drawdown_unwind_pct=0.08,
        )
        risk_manager = KalshiRiskManager(config)

        # Simulate a kill switch activation
        risk_manager._state.peak_equity_usd = 1000.0
        risk_manager._state.current_equity_usd = 700.0
        risk_manager._state.kill_switch_active = True
        risk_manager._state.kill_switch_reason = "drawdown_halt"

        # Partial recovery: equity to $880 (12% drawdown, still above 8% unwind)
        risk_manager.record_equity_snapshot(880.0)

        # Kill switch should still be active
        assert risk_manager._state.kill_switch_active
        assert risk_manager._state.kill_switch_reason == "drawdown_halt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
