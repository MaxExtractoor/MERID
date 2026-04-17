"""Test suite for 15-minute Cycle Drawdown Manager.

This test suite validates:
1. Cycle state machine (ACTIVE → RESTRICTED → RESET_PENDING)
2. Automatic reset on timer expiry and profit achievement
3. De-risk curve (risk multiplier based on drawdown)
4. Profit-lock floor (prevent giving back cycle gains)
5. Bankroll regime-based drawdown thresholds
6. Integration with KalshiRiskManager
7. Integration with PositionSizer
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from merid.event_venues.kalshi.cycle_drawdown import (
    CycleDrawdownManager,
    CycleDrawdownConfig,
    CycleStatus,
    get_cycle_drawdown_manager,
    reset_cycle_drawdown_manager,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fresh_manager():
    """Create a fresh CycleDrawdownManager for each test."""
    reset_cycle_drawdown_manager()
    mgr = get_cycle_drawdown_manager()
    # Reset to known state with $100 equity
    mgr._initialize_cycle(100.0, "test_setup")
    return mgr


@pytest.fixture
def fast_config():
    """Config with shortened cycle duration for faster tests."""
    return CycleDrawdownConfig(
        cycle_duration_seconds=2,  # 2 seconds for tests
        cycle_drawdown_pct_small=0.05,
        cycle_drawdown_pct_medium=0.03,
        cycle_drawdown_pct_large=0.02,
        small_bankroll_threshold_cents=5000,   # $50
        medium_bankroll_threshold_cents=10000,  # $100
        cycle_min_notional_to_reset_usd=0.10,
    )


# ═══════════════════════════════════════════════════════════════════════════
# State Machine Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCycleStateMachine:
    """Test cycle state transitions and lifecycle."""

    def test_initial_state(self, fresh_manager):
        """Cycle starts in ACTIVE state."""
        mgr = fresh_manager
        assert mgr.current_status == CycleStatus.ACTIVE
        assert mgr.current_cycle_id >= 1  # At least first cycle

    def test_cycle_id_increments_on_reset(self, fresh_manager):
        """Cycle ID increments on each reset."""
        mgr = fresh_manager
        initial_id = mgr.current_cycle_id
        
        mgr.force_reset("test")
        assert mgr.current_cycle_id == initial_id + 1

    def test_time_based_reset(self, fresh_manager, fast_config):
        """Cycle resets automatically after duration expires."""
        mgr = CycleDrawdownManager(fast_config)
        
        initial_id = mgr.current_cycle_id
        
        # Wait for cycle to expire
        time.sleep(2.5)
        
        # Update state triggers reset check
        status = mgr.update_cycle_state(100.0)
        
        assert mgr.current_cycle_id == initial_id + 1
        assert status == CycleStatus.ACTIVE

    def test_active_to_restricted_transition(self, fresh_manager):
        """Cycle transitions to RESTRICTED on drawdown breach."""
        mgr = fresh_manager
        
        # Start with $100, floor should be at $95 (5% DD)
        mgr.update_cycle_state(100.0)
        
        # Trigger breach by going below floor
        status = mgr.update_cycle_state(94.0)  # Below $95 floor
        
        assert status == CycleStatus.RESTRICTED
        assert mgr.current_status == CycleStatus.RESTRICTED

    def test_restricted_blocks_new_risk(self, fresh_manager):
        """RESTRICTED status blocks new risk."""
        mgr = fresh_manager
        
        # Force RESTRICTED state
        mgr.update_cycle_state(100.0)
        mgr._state.cycle_status = CycleStatus.RESTRICTED
        
        assert not mgr.can_open_new_risk(10.0)

    def test_active_allows_new_risk(self, fresh_manager):
        """ACTIVE status allows new risk."""
        mgr = fresh_manager
        
        mgr.update_cycle_state(100.0)
        
        assert mgr.can_open_new_risk(10.0)

    def test_profit_based_reset(self, fresh_manager):
        """Cycle resets early on profit achievement."""
        mgr = fresh_manager
        initial_id = mgr.current_cycle_id
        
        # Start cycle
        mgr.update_cycle_state(100.0)
        
        # Make profit that exceeds threshold and recovery level
        # Profit threshold: 0.5% of 100 = $0.50
        # Recovery: within 2.5% of peak (half of 5% max DD)
        status = mgr.update_cycle_state(100.6)  # $0.60 profit
        
        # Should trigger reset to PENDING
        assert status == CycleStatus.RESET_PENDING


# ═══════════════════════════════════════════════════════════════════════════
# De-risk Curve Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDeRiskCurve:
    """Test risk multiplier curve based on drawdown."""

    def test_full_risk_at_low_drawdown(self, fresh_manager):
        """Risk multiplier is 1.0 at low drawdown (< 25% of max)."""
        mgr = fresh_manager
        
        # At 1% drawdown (well below 25% of 5% max)
        mult = mgr.get_cycle_risk_multiplier(99.0)  # 1% DD from $100 peak
        
        assert mult == 1.0

    def test_linear_derisk_between_thresholds(self, fresh_manager):
        """Risk multiplier linearly decreases between 25% and 100% of max DD."""
        mgr = fresh_manager
        
        # Configure known state
        mgr._state.cycle_peak_equity_usd = 100.0
        mgr._state.cycle_start_equity_usd = 100.0
        mgr._state.cycle_status = CycleStatus.ACTIVE
        
        # At 50% of max DD (2.5% DD on 5% max = $97.50)
        # Should be roughly halfway between 1.0 and 0.3
        mult = mgr.get_cycle_risk_multiplier(97.5)
        
        # Should be around 0.65 (midway between 1.0 and 0.3)
        assert 0.5 < mult < 0.8

    def test_min_risk_at_max_drawdown(self, fresh_manager):
        """Risk multiplier is 0.1 at max drawdown."""
        mgr = fresh_manager
        
        # Configure known state
        mgr._state.cycle_peak_equity_usd = 100.0
        mgr._state.cycle_start_equity_usd = 100.0
        mgr._state.cycle_status = CycleStatus.RESTRICTED
        
        mult = mgr.get_cycle_risk_multiplier(90.0)  # 10% DD, exceeds 5% max
        
        assert mult == 0.1

    def test_restricted_status_uses_min_multiplier(self, fresh_manager):
        """RESTRICTED status always returns minimum multiplier."""
        mgr = fresh_manager
        mgr._state.cycle_status = CycleStatus.RESTRICTED
        
        mult = mgr.get_cycle_risk_multiplier(100.0)
        
        assert mult == 0.1


# ═══════════════════════════════════════════════════════════════════════════
# Profit-Lock Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestProfitLock:
    """Test profit-lock floor logic."""

    def test_profit_lock_floor_raises_on_profit(self, fresh_manager):
        """Profit-lock floor raises when realized PnL exceeds threshold."""
        mgr = fresh_manager
        
        mgr.update_cycle_state(100.0)
        
        # Record profit above threshold (0.5% of $100 = $0.50)
        mgr.record_realized_pnl(0.60)
        
        # Floor should be: start + 60% of realized = 100 + 0.36 = 100.36
        metrics = mgr.get_cycle_metrics()
        assert metrics["profit_lock_floor"] > 100.0

    def test_profit_lock_triggers_restricted(self, fresh_manager):
        """Dropping to profit-lock floor triggers RESTRICTED."""
        mgr = fresh_manager
        
        # Start fresh with $100
        mgr._initialize_cycle(100.0, "test_setup")
        
        # Record small profit (above min_notional 0.50, but below reset threshold)
        mgr.record_realized_pnl(0.60)  # $0.60 profit
        
        # Floor should be 100 + 0.60 * 0.60 = 100.36
        # Now drop below floor - profit-based reset won't trigger because
        # we're dropping below start, not making profit
        status = mgr.update_cycle_state(100.20)  # Below 100.36 floor
        
        assert status == CycleStatus.RESTRICTED

    def test_profit_lock_never_lowers_floor(self, fresh_manager):
        """Profit-lock floor only rises, never lowers."""
        mgr = fresh_manager
        
        mgr._initialize_cycle(100.0, "test_setup")
        mgr.record_realized_pnl(1.0)  # Floor at 100 + 0.6*1.0 = 100.60
        
        # Record loss
        mgr.record_realized_pnl(-0.50)  # Net PnL now $0.50
        
        # Floor should still be at 100.60 (based on original $1.00 profit)
        # It should NOT drop to 100.30 (which would be 60% of $0.50)
        metrics = mgr.get_cycle_metrics()
        assert metrics["profit_lock_floor"] >= 100.59  # Allow small FP tolerance


# ═══════════════════════════════════════════════════════════════════════════
# Bankroll Regime Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBankrollRegime:
    """Test bankroll-based cycle drawdown thresholds."""

    def test_small_bankroll_uses_7pct_drawdown(self, fresh_manager):
        """Small bankroll (<$70) uses 7% cycle drawdown."""
        mgr = fresh_manager
        
        # Start with $50 equity
        mgr.update_cycle_state(50.0)
        
        pct = mgr._get_cycle_drawdown_pct(50.0)
        
        assert pct == 0.07

    def test_medium_bankroll_uses_5pct_drawdown(self, fresh_manager):
        """Medium bankroll ($70-$100) uses 5% cycle drawdown."""
        mgr = fresh_manager
        
        pct = mgr._get_cycle_drawdown_pct(85.0)
        
        assert pct == 0.05

    def test_large_bankroll_uses_3pct_drawdown(self, fresh_manager):
        """Large bankroll (>$100) uses 3% cycle drawdown."""
        mgr = fresh_manager
        
        pct = mgr._get_cycle_drawdown_pct(150.0)
        
        assert pct == 0.03

    def test_floor_computed_with_regime(self, fresh_manager):
        """Floor equity computed using regime-appropriate DD pct."""
        mgr = fresh_manager
        
        # Start fresh with $50 equity → 7% DD → floor at $46.50
        mgr._initialize_cycle(50.0, "test_setup")
        
        metrics = mgr.get_cycle_metrics()
        expected_floor = 50.0 * (1.0 - 0.07)
        
        assert abs(metrics["floor_equity_usd"] - expected_floor) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Metrics and History Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMetricsAndHistory:
    """Test cycle metrics and history tracking."""

    def test_get_cycle_metrics_structure(self, fresh_manager):
        """Cycle metrics contains expected fields."""
        mgr = fresh_manager
        mgr.update_cycle_state(100.0)
        
        metrics = mgr.get_cycle_metrics()
        
        required_fields = [
            "cycle_id", "status", "start_ts", "end_ts", "seconds_remaining",
            "start_equity_usd", "peak_equity_usd", "current_equity_usd",
            "floor_equity_usd", "profit_lock_floor", "cycle_drawdown_pct",
            "max_drawdown_pct", "cycle_profit_usd", "cycle_realized_pnl_usd",
            "risk_multiplier", "can_open_new_risk", "breach_count_this_cycle",
        ]
        
        for field in required_fields:
            assert field in metrics, f"Missing field: {field}"

    def test_cycle_history_tracked(self, fresh_manager):
        """Cycle history is recorded on each update."""
        mgr = fresh_manager
        
        # The fixture records history on init, count current entries
        initial_count = len(mgr._state.cycle_history)
        
        # Add more updates
        for i in range(1, 5):
            mgr.update_cycle_state(100.0 + i)
        
        metrics = mgr.get_cycle_metrics()
        # Should have more entries than initial
        assert len(metrics["cycle_history"]) > initial_count

    def test_history_limited_to_60_entries(self, fresh_manager):
        """History is capped at 60 entries."""
        mgr = fresh_manager
        
        for i in range(70):
            mgr.update_cycle_state(100.0)
        
        assert len(mgr._state.cycle_history) == 60

    def test_seconds_remaining_computed(self, fresh_manager):
        """Seconds remaining until cycle end is computed."""
        mgr = fresh_manager
        mgr.update_cycle_state(100.0)
        
        metrics = mgr.get_cycle_metrics()
        
        assert metrics["seconds_remaining"] > 0
        assert metrics["seconds_remaining"] <= 900  # Default 15 min


# ═══════════════════════════════════════════════════════════════════════════
# Thread Safety Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    """Test thread-safe operation."""

    def test_concurrent_updates(self, fresh_manager):
        """Concurrent updates are thread-safe."""
        mgr = fresh_manager
        errors = []
        
        def update_worker(equity: float):
            try:
                for _ in range(50):
                    mgr.update_cycle_state(equity)
                    mgr.get_cycle_metrics()
                    mgr.get_cycle_risk_multiplier()
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=update_worker, args=(100.0,)),
            threading.Thread(target=update_worker, args=(99.0,)),
            threading.Thread(target=update_worker, args=(101.0,)),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_singleton_thread_safety(self):
        """Singleton creation is thread-safe."""
        reset_cycle_drawdown_manager()
        instances = []
        
        def get_instance():
            instances.append(get_cycle_drawdown_manager())
        
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All instances should be the same object
        assert all(i is instances[0] for i in instances)


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiRiskManagerIntegration:
    """Test integration with KalshiRiskManager."""

    def test_risk_manager_includes_cycle_metrics(self):
        """KalshiRiskManager summary includes cycle drawdown metrics."""
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        risk = get_kalshi_risk()
        risk.record_equity_snapshot(100.0)
        
        summary = risk.summary()
        
        assert "cycle_drawdown" in summary
        assert isinstance(summary["cycle_drawdown"], dict)

    def test_risk_manager_get_cycle_risk_multiplier(self):
        """KalshiRiskManager provides cycle risk multiplier."""
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        risk = get_kalshi_risk()
        risk.record_equity_snapshot(100.0)
        
        mult = risk.get_cycle_risk_multiplier()
        
        assert 0.1 <= mult <= 1.0

    def test_risk_manager_records_cycle_pnl(self):
        """KalshiRiskManager records PnL to cycle manager."""
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        risk = get_kalshi_risk()
        
        # Should not raise
        risk.record_cycle_pnl(5.0)


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases and Error Handling
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_equity_handled(self, fresh_manager):
        """Zero equity is handled gracefully."""
        mgr = fresh_manager
        
        status = mgr.update_cycle_state(0.0)
        
        # Should not crash, likely goes RESTRICTED
        assert isinstance(status, CycleStatus)

    def test_negative_equity_handled(self, fresh_manager):
        """Negative equity is handled gracefully."""
        mgr = fresh_manager
        
        status = mgr.update_cycle_state(-10.0)
        
        # Should not crash
        assert isinstance(status, CycleStatus)

    def test_configure_updates_settings(self, fresh_manager):
        """Configure method updates settings."""
        mgr = fresh_manager
        
        mgr.configure(cycle_drawdown_pct_small=0.10)
        
        assert mgr._config.cycle_drawdown_pct_small == 0.10

    def test_force_reset_manual(self, fresh_manager):
        """Force reset with manual reason."""
        mgr = fresh_manager
        initial_id = mgr.current_cycle_id
        
        mgr.force_reset("operator_action")
        
        assert mgr.current_cycle_id == initial_id + 1


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Audit Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelineAudit:
    """Upstream/downstream pipeline audit tests."""

    def test_signal_to_cycle_state_flow(self):
        """Full flow: equity signal → cycle state update → metrics."""
        # Use completely fresh manager (not fixture)
        from merid.event_venues.kalshi.cycle_drawdown import reset_cycle_drawdown_manager, get_cycle_drawdown_manager
        reset_cycle_drawdown_manager()
        mgr = get_cycle_drawdown_manager()
        
        # Configure with higher reset threshold to avoid auto-reset
        from merid.event_venues.kalshi.cycle_drawdown import CycleDrawdownConfig
        mgr._config = CycleDrawdownConfig(
            cycle_min_notional_to_reset_usd=10.0,  # High threshold to avoid auto-reset
            cycle_drawdown_pct_small=0.05,
            cycle_drawdown_pct_medium=0.05,
            cycle_drawdown_pct_large=0.05,
        )
        
        # Start fresh with known equity
        mgr._initialize_cycle(100.0, "test_setup")
        
        # Simulate signal ingestion (small moves to avoid profit reset)
        equity_updates = [100.0, 101.0, 100.5, 102.0, 99.0]
        
        for equity in equity_updates:
            status = mgr.update_cycle_state(equity)
        
        # Verify downstream metrics
        metrics = mgr.get_cycle_metrics()
        # Final equity should be 99.0 (last update recorded in history)
        assert metrics["current_equity_usd"] == 99.0, f"Expected 99.0 but got {metrics['current_equity_usd']}. History: {metrics.get('cycle_history', [])}"
        # Should have 5 history entries
        assert len(metrics["cycle_history"]) == 5, f"Expected 5 history entries but got {len(metrics['cycle_history'])}"
        
    def test_risk_multiplier_scaling(self, fresh_manager):
        """Risk multiplier correctly scales with drawdown."""
        mgr = fresh_manager
        
        # Start fresh at $100 with 5% max DD
        mgr._initialize_cycle(100.0, "test_setup")
        
        # Verify scaling at different equity levels
        full_risk = mgr.get_cycle_risk_multiplier(100.0)  # 0% DD
        mid_risk = mgr.get_cycle_risk_multiplier(97.5)   # 2.5% DD = 50% of max
        max_dd_risk = mgr.get_cycle_risk_multiplier(95.0)   # 5% DD = max, returns 0.3 (min mult)
        
        # Force restricted status to get 0.1 multiplier
        mgr._state.cycle_status = CycleStatus.RESTRICTED
        restricted_risk = mgr.get_cycle_risk_multiplier(95.0)
        
        assert full_risk == 1.0
        assert 0.5 < mid_risk < 1.0  # Midway between 1.0 and 0.3
        assert max_dd_risk == 0.3  # At max DD, returns derisk_min_mult
        assert restricted_risk == 0.1  # When RESTRICTED, returns derisk_restricted_mult

    def test_profit_lock_prevents_giveback(self, fresh_manager):
        """Profit lock prevents giving back more than X% of profits."""
        mgr = fresh_manager
        
        # Start fresh and make profit (but below reset threshold)
        mgr._initialize_cycle(100.0, "test_setup")
        mgr.record_realized_pnl(0.60)  # $0.60 profit, above lock threshold but below reset
        
        # Verify profit-lock floor is set
        metrics = mgr.get_cycle_metrics()
        # Floor should be: 100 + 0.60 * 0.60 = 100.36
        assert abs(metrics["profit_lock_floor"] - 100.36) < 0.01
        
        # Simulate giveback below floor (but still profitable)
        status = mgr.update_cycle_state(100.20)  # Below 100.36 floor, still profitable
        
        assert status == CycleStatus.RESTRICTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
