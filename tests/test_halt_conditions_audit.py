"""Tests for Halt Conditions Audit implementation.

Covers:
- Error classification (CRITICAL vs LOW/MEDIUM, budget-exempt)
- Error deduplication (MERID_DEDUP_WINDOW_SECS)
- Kill switch tier transitions (WARNING 70%, LIMITED 90%, TRIGGERED 100%)
- Phantom kill switch arming/clearing
- Execution gate whitelist
- Halt diagnosis endpoint
"""

from __future__ import annotations

import os
import time
from typing import Dict, Any

import pytest

from merid.risk.error_classification import (
    classify_error,
    ErrorClass,
    ErrorSeverity,
    ErrorClassification,
    ErrorDedupTracker,
    should_count_error,
    compute_kill_tier,
    KillSwitchTier,
    TierThresholds,
)


class TestErrorClassification:
    """Test error classification per Halt Conditions Audit."""
    
    def test_critical_errors_count_toward_budget(self):
        """CRITICAL errors (auth_error, risk_violation, etc.) count toward budget."""
        critical_codes = [
            "auth_error",
            "risk_violation", 
            "insufficient_funds",
            "order_rejected",
            "generic",
        ]
        
        for code in critical_codes:
            classification = classify_error(code)
            assert classification.error_class.value == code, f"Failed for {code}"
            assert classification.severity == ErrorSeverity.CRITICAL, f"Failed for {code}"
            assert classification.counts_toward_budget is True, f"Failed for {code}"
            assert classification.severity_weight == 1.0, f"Failed for {code}"
    
    def test_low_errors_budget_exempt(self):
        """LOW errors (gate_blocked, duplicate_order, etc.) are budget-exempt."""
        low_codes = [
            "gate_blocked",
            "duplicate_order_rejected",
            "paper_session_error",
            "ws_reconnect",
            "stale_snapshot",
            "low_edge",
            "spread_too_wide",
            "depth_insufficient",
            "no_open_orders",
            "no_position",
        ]
        
        for code in low_codes:
            classification = classify_error(code)
            assert classification.counts_toward_budget is False, f"Failed for {code}"
            assert classification.severity == ErrorSeverity.LOW, f"Failed for {code}"
    
    def test_order_group_errors_medium_not_budget(self):
        """Order group lifecycle errors are MEDIUM, budget-exempt."""
        medium_codes = [
            "order_group_not_found",
            "order_group_not_active",
        ]
        
        for code in medium_codes:
            classification = classify_error(code)
            assert classification.severity == ErrorSeverity.MEDIUM, f"Failed for {code}"
            assert classification.counts_toward_budget is False, f"Failed for {code}"
    
    def test_auth_error_aliases(self):
        """Auth error codes resolve to AUTH_ERROR class."""
        aliases = ["401", "403", "auth_failed", "api_key_invalid", "forbidden", "unauthorized"]
        
        for alias in aliases:
            classification = classify_error(alias)
            assert classification.error_class == ErrorClass.AUTH_ERROR, f"Failed for {alias}"
            assert classification.is_critical is True, f"Failed for {alias}"
    
    def test_transient_errors_marked(self):
        """Transient errors (rate_limit, timeout, ws_reconnect) marked as transient."""
        transient_codes = ["rate_limit", "timeout", "ws_reconnect", "429"]
        
        for code in transient_codes:
            classification = classify_error(code)
            assert classification.is_transient is True, f"Failed for {code}"


class TestErrorDeduplication:
    """Test error deduplication per audit: within window, same (class, context) counts once."""
    
    def test_dedup_within_window(self):
        """Same error within dedup window only counts once."""
        tracker = ErrorDedupTracker(dedup_window_seconds=5.0)
        
        # First occurrence counts
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "kalshi_api") is True
        # Second occurrence within window does not count
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "kalshi_api") is False
        # Different context counts
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "binance_api") is True
        # Different class counts
        assert tracker.should_count(ErrorClass.RISK_VIOLATION, "kalshi_api") is True
    
    def test_dedup_after_window_expires(self):
        """After dedup window, same error counts again."""
        tracker = ErrorDedupTracker(dedup_window_seconds=0.1)
        
        # First occurrence
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "kalshi_api") is True
        # Wait for window
        time.sleep(0.15)
        # Should count again
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "kalshi_api") is True
    
    def test_dedup_budget_exempt_errors(self):
        """Budget-exempt errors still tracked for dedup (for observability)."""
        tracker = ErrorDedupTracker()
        
        # Gate blocked tracked but not counted toward budget
        classification = classify_error("gate_blocked")
        assert classification.counts_toward_budget is False
        
        # Still deduped for tracking
        assert tracker.should_count(ErrorClass.GATE_BLOCKED, "order_router") is True
        assert tracker.should_count(ErrorClass.GATE_BLOCKED, "order_router") is False
    
    def test_purge_old_entries(self):
        """Old entries can be purged from tracker."""
        tracker = ErrorDedupTracker(dedup_window_seconds=0.1)
        
        tracker.should_count(ErrorClass.AUTH_ERROR, "api1")
        tracker.should_count(ErrorClass.AUTH_ERROR, "api2")
        
        time.sleep(0.25)
        purged = tracker.purge_old(max_age_seconds=0.2)
        assert purged == 2
        assert tracker.get_stats()["tracked_keys"] == 0


class TestKillSwitchTiers:
    """Test kill switch tier transitions (WARNING 70%, LIMITED 90%, TRIGGERED 100%)."""
    
    def test_tier_clear_below_warning(self):
        """Below 70% threshold = CLEAR tier."""
        tier, pct = compute_kill_tier(
            error_count=6,
            threshold=10,
            thresholds=TierThresholds(warning_pct=0.7, limited_pct=0.9, triggered_pct=1.0)
        )
        assert tier == KillSwitchTier.CLEAR
        assert pct == 0.6
    
    def test_tier_warning_at_70pct(self):
        """At 70% threshold = WARNING tier."""
        tier, pct = compute_kill_tier(
            error_count=7,
            threshold=10,
            thresholds=TierThresholds(warning_pct=0.7, limited_pct=0.9, triggered_pct=1.0)
        )
        assert tier == KillSwitchTier.WARNING
        assert pct == 0.7
    
    def test_tier_limited_at_90pct(self):
        """At 90% threshold = LIMITED tier."""
        tier, pct = compute_kill_tier(
            error_count=9,
            threshold=10,
            thresholds=TierThresholds(warning_pct=0.7, limited_pct=0.9, triggered_pct=1.0)
        )
        assert tier == KillSwitchTier.LIMITED
        assert pct == 0.9
    
    def test_tier_triggered_at_100pct(self):
        """At 100% threshold = TRIGGERED tier."""
        tier, pct = compute_kill_tier(
            error_count=10,
            threshold=10,
            thresholds=TierThresholds(warning_pct=0.7, limited_pct=0.9, triggered_pct=1.0)
        )
        assert tier == KillSwitchTier.TRIGGERED
        assert pct == 1.0
    
    def test_weighted_error_counting(self):
        """Weighted error counting: CRITICAL=1.0, HIGH=0.5."""
        # 5 CRITICAL + 2 HIGH = 5*1.0 + 2*0.5 = 6.0 weighted
        from merid.risk.error_classification import _SEVERITY_WEIGHTS
        
        assert _SEVERITY_WEIGHTS[ErrorSeverity.CRITICAL] == 1.0
        assert _SEVERITY_WEIGHTS[ErrorSeverity.HIGH] == 0.5
        assert _SEVERITY_WEIGHTS[ErrorSeverity.MEDIUM] == 0.0
        assert _SEVERITY_WEIGHTS[ErrorSeverity.LOW] == 0.0


class TestRiskControllerClassifiedErrors:
    """Test RiskController.record_error_classified() integration."""
    
    def test_record_critical_error_increments_budget(self):
        """Critical errors increment error budget."""
        from merid.risk.kill_switches import RiskController
        from merid.risk.error_classification import get_dedup_tracker
        
        # Purge global dedup tracker so prior tests don't filter this error
        get_dedup_tracker()._last_seen.clear()
        
        controller = RiskController(error_threshold=100)
        
        # Record critical error (use unique context to avoid dedup collision)
        can_trade, metadata = controller.record_error_classified(
            error_code="auth_failed",
            context="test_record_critical_error_increments_budget",
            details="Auth failure test",
        )
        
        assert can_trade is True  # Not at threshold yet
        assert metadata["counts_toward_budget"] is True
        assert metadata["error_class"] == "auth_error"
        
        # Check budget status
        status = controller.get_error_budget_status()
        assert status["error_count"] >= 1
    
    def test_record_low_error_no_budget_increment(self):
        """LOW severity errors don't increment budget."""
        from merid.risk.kill_switches import RiskController
        
        controller = RiskController(error_threshold=100)
        initial_count = controller._error_count
        
        # Record low error
        can_trade, metadata = controller.record_error_classified(
            error_code="gate_blocked",
            context="order_router",
        )
        
        assert metadata["counts_toward_budget"] is False
        # Budget count should not increment
        assert controller._error_count == initial_count
    
    def test_dedup_prevents_double_counting(self):
        """Same error within dedup window only counts once."""
        from merid.risk.kill_switches import RiskController
        from merid.risk.error_classification import get_dedup_tracker
        
        # Reset dedup tracker
        tracker = get_dedup_tracker()
        tracker._last_seen.clear()
        
        controller = RiskController(error_threshold=100)
        
        # First occurrence
        _, meta1 = controller.record_error_classified("auth_failed", "kalshi")
        assert meta1["counts_toward_budget"] is True
        
        # Second occurrence within window — dedup filtered
        _, meta2 = controller.record_error_classified("auth_failed", "kalshi")
        assert meta2["dedup_filtered"] is True
        # Should still count toward budget (for dedup) but not increment
        assert meta2["counts_toward_budget"] is True


class TestPhantomKillSwitch:
    """Test phantom kill switch arming and clearing."""
    
    def test_phantom_arms_on_true_mismatch(self):
        """Phantom kill arms when genuine position mismatch exists."""
        from merid.reconciliation.venue_reconciler import (
            VenuePositionDiscrepancy,
            _evaluate_phantom_kill_locked,
            is_phantom_kill_armed,
            _phantom_kill_switch,
            _phantom_positions,
        )
        
        # Create discrepancies: venue has position, MERID has none (true phantom)
        discrepancies = [
            VenuePositionDiscrepancy(
                venue="kalshi",
                symbol="KXBTC-15M",
                merid_qty=0.0,
                venue_qty=100.0,
                merid_entry_price=0.0,
                venue_entry_price=50000.0,
            )
        ]
        
        # Reset phantom state
        import merid.reconciliation.venue_reconciler as vr
        vr._phantom_kill_switch = False
        vr._phantom_positions = []
        
        _evaluate_phantom_kill_locked(discrepancies)
        
        assert is_phantom_kill_armed() is True
        assert "KXBTC-15M" in vr._phantom_positions
    
    def test_phantom_not_armed_on_venue_unreachable(self):
        """Phantom kill does NOT arm on venue unreachable (transient)."""
        from merid.reconciliation.venue_reconciler import (
            VenuePositionDiscrepancy,
            _evaluate_phantom_kill_locked,
            is_phantom_kill_armed,
        )
        import merid.reconciliation.venue_reconciler as vr
        
        # Create synthetic venue unreachable discrepancy
        discrepancies = [
            VenuePositionDiscrepancy(
                venue="kalshi",
                symbol="__VENUE_UNREACHABLE__kalshi",
                merid_qty=0.0,
                venue_qty=0.0,
                merid_entry_price=0.0,
                venue_entry_price=0.0,
                severity="critical",
                reason="venue adapter raised: ConnectionError",
            )
        ]
        
        # Reset state
        vr._phantom_kill_switch = False
        vr._phantom_positions = []
        
        _evaluate_phantom_kill_locked(discrepancies)
        
        # Should NOT arm on venue unreachable
        assert is_phantom_kill_armed() is False
    
    def test_clear_phantom_requires_operator_reason(self):
        """clear_phantom_kill_switch requires operator and reason."""
        from merid.reconciliation import clear_phantom_kill_switch
        import merid.reconciliation.venue_reconciler as vr
        
        # First arm the phantom kill
        vr._phantom_kill_switch = True
        vr._phantom_kill_reason = "Test phantom"
        vr._phantom_kill_timestamp = time.time()
        vr._phantom_positions = ["KXBTC-15M"]
        
        # Clear it
        result = clear_phantom_kill_switch(
            operator="test_operator",
            reason="Reconciliation verified clean",
        )
        
        assert result["cleared"] is True
        assert result["operator"] == "test_operator"
        assert result["reason"] == "Reconciliation verified clean"
    
    def test_clear_phantom_when_not_armed(self):
        """clear_phantom_kill_switch returns appropriate message when not armed."""
        from merid.reconciliation import clear_phantom_kill_switch, is_phantom_kill_armed
        import merid.reconciliation.venue_reconciler as vr
        
        # Ensure not armed
        vr._phantom_kill_switch = False
        
        result = clear_phantom_kill_switch(operator="test")
        
        assert result["cleared"] is False
        assert result["was_armed"] is False


class TestExecutionGateWhitelist:
    """Test execution gate whitelist enforcement."""
    
    def test_whitelisted_can_set_blocked(self):
        """Whitelisted sources can set gate=BLOCKED."""
        from core.execution_gate import can_source_set_gate, GateState
        
        whitelisted = ["kill_switch", "phantom_kill", "reconciliation", "price_feed"]
        
        for source in whitelisted:
            assert can_source_set_gate(source, GateState.BLOCKED.value) is True, f"Failed for {source}"
    
    def test_advisory_only_blocked_from_blocked(self):
        """Advisory-only sources cannot set gate=BLOCKED."""
        from core.execution_gate import can_source_set_gate, GateState
        
        advisory = ["event_loop_monitor", "session_guard", "alt_crypto_feed", "news_feed"]
        
        for source in advisory:
            assert can_source_set_gate(source, GateState.BLOCKED.value) is False, f"Failed for {source}"
    
    def test_advisory_only_blocked_from_limited(self):
        """Advisory-only sources cannot set gate=LIMITED."""
        from core.execution_gate import can_source_set_gate, GateState
        
        advisory = ["event_loop_monitor", "session_guard"]
        
        for source in advisory:
            assert can_source_set_gate(source, GateState.LIMITED.value) is False, f"Failed for {source}"
    
    def test_clearing_always_allowed(self):
        """All sources can clear gate to CLEAR state."""
        from core.execution_gate import can_source_set_gate, GateState
        
        any_source = "some_random_source"
        assert can_source_set_gate(any_source, GateState.CLEAR.value) is True


class TestHaltDiagnosisEndpoint:
    """Test halt diagnosis endpoint structure."""
    
    @pytest.mark.asyncio
    async def test_halt_diagnosis_returns_expected_structure(self):
        """Halt diagnosis returns expected structure."""
        from web.api.halt_diagnosis_api import get_halt_diagnosis
        
        diagnosis = await get_halt_diagnosis()
        
        # Check required fields
        assert "timestamp" in diagnosis
        assert "gate_state" in diagnosis
        assert "execution_blocked" in diagnosis
        assert "safe_to_trade" in diagnosis
        assert "gate_reasons" in diagnosis
        assert "kill_switch" in diagnosis
        assert "phantom_kill" in diagnosis
        assert "reconciliation" in diagnosis
        assert "ws_health" in diagnosis
        assert "price_feed" in diagnosis
        assert "kalshi_client" in diagnosis
        assert "next_steps" in diagnosis
        assert "summary" in diagnosis
    
    @pytest.mark.asyncio
    async def test_next_steps_when_kill_active(self):
        """Next steps includes P0 action when kill switch active."""
        from web.api.halt_diagnosis_api import _compute_next_steps
        
        diagnosis = {
            "kill_switch": {"active": True, "reason": "Test kill"},
            "phantom_kill": {"armed": False},
            "reconciliation": {"execution_gate_blocked": False},
            "price_feed": {"critical_count": 0},
            "ws_health": {"status": "ok"},
            "kalshi_client": {"authenticated": True},
            "gate_state": "blocked",
            "execution_blocked": True,
        }
        
        steps = _compute_next_steps(diagnosis)
        
        p0_steps = [s for s in steps if s.get("priority") == "P0"]
        assert len(p0_steps) >= 1
        assert any("kill switch" in s["action"].lower() for s in p0_steps)
    
    @pytest.mark.asyncio  
    async def test_summary_format(self):
        """Summary format includes key state indicators."""
        from web.api.halt_diagnosis_api import _compute_summary
        
        # Blocked state
        diagnosis_blocked = {
            "gate_state": "blocked",
            "kill_switch": {"active": True},
            "phantom_kill": {"armed": False},
        }
        summary = _compute_summary(diagnosis_blocked)
        assert "EXECUTION BLOCKED" in summary
        assert "KILL SWITCH ACTIVE" in summary
        
        # Phantom state
        diagnosis_phantom = {
            "gate_state": "blocked",
            "kill_switch": {"active": False},
            "phantom_kill": {"armed": True},
        }
        summary = _compute_summary(diagnosis_phantom)
        assert "PHANTOM KILL ARMED" in summary


class TestIntegration:
    """Integration tests for halt conditions."""
    
    @pytest.mark.asyncio
    async def test_benign_errors_dont_trigger_kill(self):
        """Many benign errors should not trigger kill switch."""
        from merid.risk.kill_switches import RiskController
        
        controller = RiskController(error_threshold=10)
        
        # Generate many benign errors
        for _ in range(20):
            controller.record_error_classified("gate_blocked", "test")
            controller.record_error_classified("duplicate_order_rejected", "test")
            controller.record_error_classified("ws_reconnect", "test")
        
        # Should still be able to trade (no critical errors counted)
        assert controller.can_trade() is True
        
        # Error budget should be minimal (weighted count near 0)
        status = controller.get_error_budget_status()
        assert status["weighted_error_count"] < 1.0
    
    @pytest.mark.asyncio
    async def test_critical_errors_escalate_tiers(self):
        """Critical errors should escalate through tiers."""
        from merid.risk.kill_switches import RiskController
        from merid.risk.error_classification import get_dedup_tracker
        
        # Reset dedup
        get_dedup_tracker()._last_seen.clear()
        
        controller = RiskController(error_threshold=10)
        
        # Start at CLEAR
        tier = controller.get_error_budget_status()["tier"]
        assert tier == "clear"
        
        # Add errors to reach WARNING (70% = 7 errors)
        for i in range(7):
            controller.record_error_classified("auth_failed", f"api{i}")  # Different contexts
        
        status = controller.get_error_budget_status()
        assert status["tier"] == "warning"
        
        # Add more to reach LIMITED (90% = 9 errors)
        for i in range(7, 9):
            controller.record_error_classified("auth_failed", f"api{i}")
        
        status = controller.get_error_budget_status()
        assert status["tier"] == "limited"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
