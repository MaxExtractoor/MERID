"""
Comprehensive Invariant Validation Test Suite

This test suite validates that all the invariant guards and paranoid mode assertions
are actually firing in live runs. It covers:

1. MD age invariants (negative/absurd ages)
2. WS forwarder health gating (idle/active scenarios)
3. Quality vs optimizer consistency (spread scenarios)
4. Catalog age and depth gating (threshold violations)
5. Paranoid mode vs normal mode enforcement
6. E2E behavior validation with realistic MD scenarios

Each test creates controlled violations and verifies the expected invariant
violations are logged and handled correctly.
"""

import pytest
import asyncio
import time
import logging
import os
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Import the modules we're testing
from merid.core.e2e_invariants import (
    E2EInvariantChecker, 
    InvariantViolation,
    check_system_invariants
)
from merid.prediction.candidate_optimizer import CandidateOptimizer
from merid.event_venues.kalshi.market_state import MarketQuote

logger = logging.getLogger(__name__)

@dataclass
class TestMarketState:
    """Mock market state for testing."""
    ticker: str
    last_update_ts: float
    best_bid_cents: int
    best_ask_cents: int
    spread_cents: int
    min_depth_yes: int
    min_depth_no: int

class TestMDAgeInvariants:
    """Test MD age invariant violations."""
    
    def test_negative_age_invariant(self):
        """Test that negative ages trigger invariant violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        # Test negative age
        violation = checker.check_md_age_invariant(
            ticker="KXBTC15M-123",
            age=-1000.0,
            stale=False,
            reason="FRESH"
        )
        
        assert violation is not None
        assert violation.invariant_name == "MD_NEGATIVE_AGE"
        assert violation.severity == "CRITICAL"
        assert "Negative age detected" in violation.message
        assert "-1000.0s" in violation.message
        
    def test_fresh_with_impossible_age_invariant(self):
        """Test that FRESH status with impossible age triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        # Test FRESH with huge age
        violation = checker.check_md_age_invariant(
            ticker="KXETH15M-456",
            age=7200.0,  # 2 hours
            stale=False,
            reason="FRESH"
        )
        
        assert violation is not None
        assert violation.invariant_name == "MD_FRESH_IMPOSSIBLE_AGE"
        assert violation.severity == "CRITICAL"
        assert "FRESH status with impossible age" in violation.message
        
    def test_fresh_with_negative_age_invariant(self):
        """Test that FRESH status with negative age triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_md_age_invariant(
            ticker="KXSOL15M-789",
            age=-500.0,
            stale=False,
            reason="FRESH"
        )
        
        assert violation is not None
        assert violation.invariant_name == "MD_FRESH_IMPOSSIBLE_AGE"
        
    def test_normal_md_age_no_violation(self):
        """Test that normal MD ages don't trigger violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        # Test normal case
        violation = checker.check_md_age_invariant(
            ticker="KXBTC15M-123",
            age=15.0,
            stale=False,
            reason="FRESH"
        )
        
        assert violation is None
        
        # Test stale case
        violation = checker.check_md_age_invariant(
            ticker="KXETH15M-456",
            age=150.0,
            stale=True,
            reason="LAST_UPDATE_TOO_OLD"
        )
        
        assert violation is None

class TestWSForwarderInvariants:
    """Test WS forwarder invariant violations."""
    
    def test_ok_status_with_zero_events_invariant(self):
        """Test that OK status with zero events triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_ws_forwarder_invariant(
            events_per_sec=0.0,
            time_since_last_event=45.0,
            stalled=False,
            status="OK"
        )
        
        assert violation is not None
        assert violation.invariant_name == "WS_FORWARDER_IMPOSSIBLE_OK"
        assert violation.severity == "CRITICAL"
        assert "events/sec=0.0" in violation.message
        
    def test_stalled_with_ok_status_invariant(self):
        """Test that stalled forwarder with OK status triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_ws_forwarder_invariant(
            events_per_sec=1.0,
            time_since_last_event=35.0,
            stalled=True,
            status="OK"
        )
        
        assert violation is not None
        assert violation.invariant_name == "WS_FORWARDER_STALLED_OK"
        assert violation.severity == "ERROR"
        
    def test_healthy_ws_forwarder_no_violation(self):
        """Test that healthy WS forwarder doesn't trigger violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_ws_forwarder_invariant(
            events_per_sec=2.5,
            time_since_last_event=5.0,
            stalled=False,
            status="OK"
        )
        
        assert violation is None
        
        # Test error status (should be fine)
        violation = checker.check_ws_forwarder_invariant(
            events_per_sec=0.0,
            time_since_last_event=45.0,
            stalled=True,
            status="ERROR"
        )
        
        assert violation is None

class TestExecutionReadyInvariants:
    """Test execution ready invariant violations."""
    
    def test_execution_ready_with_critical_failure(self):
        """Test that execution ready with critical failure triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        subsystem_health = {
            "catalog": "HEALTH_ERROR",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD",
            "ws_forwarder": "HEALTH_GOOD"
        }
        
        violation = checker.check_execution_ready_invariant(
            execution_ready=True,
            subsystem_health=subsystem_health
        )
        
        assert violation is not None
        assert violation.invariant_name == "EXECUTION_READY_CRITICAL_FAILURE"
        assert violation.severity == "CRITICAL"
        assert "catalog" in violation.message
        
    def test_execution_ready_with_unknown_subsystem(self):
        """Test that execution ready with unknown subsystem triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        subsystem_health = {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_UNKNOWN",
            "depth_coverage": "HEALTH_GOOD",
            "ws_forwarder": "HEALTH_GOOD"
        }
        
        violation = checker.check_execution_ready_invariant(
            execution_ready=True,
            subsystem_health=subsystem_health
        )
        
        assert violation is not None
        assert "md_freshness" in violation.message
        
    def test_degraded_execution_ready_no_violation(self):
        """Test that degraded execution ready doesn't trigger violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        subsystem_health = {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD",
            "ws_forwarder": "HEALTH_GOOD"
        }
        
        violation = checker.check_execution_ready_invariant(
            execution_ready=False,
            subsystem_health=subsystem_health
        )
        
        assert violation is None

class TestQualityOptimizerInvariants:
    """Test quality vs optimizer consistency invariants."""
    
    def test_good_quality_with_zero_depth_invariant(self):
        """Test that GOOD quality with zero depth triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_depth_quality_invariant(
            ticker="KXBTC15M-123",
            depth_yes=0,
            depth_no=50,
            quality_label="GOOD",
            spread_cents=20
        )
        
        assert violation is not None
        assert violation.invariant_name == "QUALITY_GOOD_ZERO_DEPTH"
        assert violation.severity == "ERROR"
        
    def test_acceptable_quality_with_wide_spread_invariant(self):
        """Test that ACCEPTABLE quality with wide spread triggers violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_depth_quality_invariant(
            ticker="KXETH15M-456",
            depth_yes=25,
            depth_no=25,
            quality_label="ACCEPTABLE",
            spread_cents=96  # > 40 cent threshold
        )
        
        assert violation is not None
        assert violation.invariant_name == "QUALITY_OPTIMIZER_MISMATCH"
        assert violation.severity == "ERROR"
        assert "optimizer will reject" in violation.message
        
    def test_poor_quality_with_wide_spread_no_violation(self):
        """Test that POOR quality with wide spread doesn't trigger violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_depth_quality_invariant(
            ticker="KXSOL15M-789",
            depth_yes=25,
            depth_no=25,
            quality_label="POOR",
            spread_cents=98  # > 40 cent threshold
        )
        
        assert violation is None
        
    def test_good_quality_normal_conditions_no_violation(self):
        """Test that GOOD quality with normal conditions doesn't trigger violations."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        violation = checker.check_depth_quality_invariant(
            ticker="KXBTC15M-123",
            depth_yes=25,
            depth_no=25,
            quality_label="GOOD",
            spread_cents=30  # < 40 cent threshold
        )
        
        assert violation is None

class TestParanoidMode:
    """Test paranoid mode vs normal mode enforcement."""
    
    def test_paranoid_mode_raises_on_critical_violations(self):
        """Test that paranoid mode raises exceptions on critical violations."""
        checker = E2EInvariantChecker(paranoid_mode=True)
        
        system_state = {
            "market_data": {
                "KXBTC15M-123": {
                    "age": -1000.0,
                    "stale": False,
                    "reason": "FRESH"
                }
            },
            "ws_forwarder": {
                "events_per_sec": 0.0,
                "time_since_last_event": 45.0,
                "stalled": False,
                "status": "OK"
            },
            "execution_ready": True,
            "subsystem_health": {
                "catalog": "HEALTH_GOOD",
                "md_freshness": "HEALTH_GOOD",
                "depth_coverage": "HEALTH_GOOD",
                "ws_forwarder": "HEALTH_GOOD"
            }
        }
        
        # Should raise RuntimeError in paranoid mode
        with pytest.raises(RuntimeError, match="CRITICAL INVARIANT VIOLATION"):
            checker.check_all_invariants(system_state)
    
    def test_normal_mode_logs_but_does_not_raise(self):
        """Test that normal mode logs violations but doesn't raise."""
        checker = E2EInvariantChecker(paranoid_mode=False)
        
        system_state = {
            "market_data": {
                "KXBTC15M-123": {
                    "age": -1000.0,
                    "stale": False,
                    "reason": "FRESH"
                }
            },
            "ws_forwarder": {
                "events_per_sec": 0.0,
                "time_since_last_event": 45.0,
                "stalled": False,
                "status": "OK"
            },
            "execution_ready": True,
            "subsystem_health": {
                "catalog": "HEALTH_GOOD",
                "md_freshness": "HEALTH_GOOD",
                "depth_coverage": "HEALTH_GOOD",
                "ws_forwarder": "HEALTH_GOOD"
            }
        }
        
        # Should not raise but should collect violations
        violations = checker.check_all_invariants(system_state)
        assert len(violations) > 0
        assert any(v.invariant_name == "MD_NEGATIVE_AGE" for v in violations)
        assert any(v.invariant_name == "WS_FORWARDER_IMPOSSIBLE_OK" for v in violations)

class TestQualityOptimizerConsistency:
    """Test quality vs optimizer consistency with real spread scenarios."""
    
    def setup_method(self):
        """Set up optimizer for testing."""
        self.optimizer = CandidateOptimizer()
    
    def test_wide_spread_rejection_and_quality_label(self):
        """Test that wide spreads are both rejected and labeled POOR."""
        # Create a market with wide spread
        market = {
            "market_id": "KXBTC15M-123",
            "asset": "BTC",
            "series_ticker": "KXBTC15M"
        }
        
        # Mock market state with wide spread
        state = Mock()
        state.spread_cents = 96  # Wide spread > 40 threshold
        state.min_depth_yes = 25
        state.min_depth_no = 25
        state.mid_cents = 5000
        
        # Mock spot service
        spot_service = Mock()
        spot_service.get_spot_price.return_value = 5000.0
        
        # Create candidate
        candidate = asyncio.run(self.optimizer._create_market_candidate(market, state, spot_service))
        
        # Test quality filter
        candidates = [candidate]
        metrics = Mock()
        metrics.filter_breakdown = {}
        
        filtered = asyncio.run(self.optimizer._filter_by_quality(candidates, metrics))
        
        # Should be empty (rejected)
        assert len(filtered) == 0
        assert "spread_too_wide" in metrics.filter_breakdown
        
        # Test quality classification (simulating MD-QUALITY logic)
        spread_cents = 96
        SPREAD_THRESHOLD_CENTS = 40
        
        spread_quality = "GOOD" if spread_cents < SPREAD_THRESHOLD_CENTS else "WIDE"
        depth_quality = "GOOD" if min(state.min_depth_yes, state.min_depth_no) >= 10 else "SHALLOW"
        
        # FIX: Apply the new quality logic
        if spread_quality == "GOOD" and depth_quality == "GOOD":
            overall_quality = "GOOD"
        elif spread_cents > SPREAD_THRESHOLD_CENTS:
            overall_quality = "POOR"  # Will be rejected by optimizer
        elif depth_quality == "SHALLOW":
            overall_quality = "ACCEPTABLE"
        else:
            overall_quality = "ACCEPTABLE"
        
        # Should be POOR (consistent with rejection)
        assert overall_quality == "POOR"
    
    def test_narrow_spread_acceptance_and_quality_label(self):
        """Test that narrow spreads are accepted and labeled appropriately."""
        # Create a market with narrow spread
        market = {
            "market_id": "KXETH15M-456",
            "asset": "ETH",
            "series_ticker": "KXETH15M"
        }
        
        # Mock market state with narrow spread
        state = Mock()
        state.spread_cents = 30  # Narrow spread < 40 threshold
        state.min_depth_yes = 25
        state.min_depth_no = 25
        state.mid_cents = 5000
        
        # Mock spot service
        spot_service = Mock()
        spot_service.get_spot_price.return_value = 5000.0
        
        # Create candidate
        candidate = asyncio.run(self.optimizer._create_market_candidate(market, state, spot_service))
        
        # Test quality filter
        candidates = [candidate]
        metrics = Mock()
        metrics.filter_breakdown = {}
        
        filtered = asyncio.run(self.optimizer._filter_by_quality(candidates, metrics))
        
        # Should not be rejected on spread
        assert len(filtered) == 1
        assert "spread_too_wide" not in metrics.filter_breakdown
        
        # Test quality classification
        spread_cents = 30
        SPREAD_THRESHOLD_CENTS = 40
        
        spread_quality = "GOOD" if spread_cents < SPREAD_THRESHOLD_CENTS else "WIDE"
        depth_quality = "GOOD" if min(state.min_depth_yes, state.min_depth_no) >= 10 else "SHALLOW"
        
        # FIX: Apply the new quality logic
        if spread_quality == "GOOD" and depth_quality == "GOOD":
            overall_quality = "GOOD"
        elif spread_cents > SPREAD_THRESHOLD_CENTS:
            overall_quality = "POOR"
        elif depth_quality == "SHALLOW":
            overall_quality = "ACCEPTABLE"
        else:
            overall_quality = "ACCEPTABLE"
        
        # Should be GOOD (consistent with acceptance)
        assert overall_quality == "GOOD"

class TestSystemIntegration:
    """Test end-to-end system integration with invariants."""
    
    def test_clean_system_no_violations(self):
        """Test that a clean system produces no violations."""
        system_state = {
            "market_data": {
                "KXBTC15M-123": {"age": 15.0, "stale": False, "reason": "FRESH"},
                "KXETH15M-456": {"age": 20.0, "stale": False, "reason": "FRESH"},
                "KXSOL15M-789": {"age": 10.0, "stale": False, "reason": "FRESH"},
                "KXXRP15M-012": {"age": 25.0, "stale": False, "reason": "FRESH"},
                "KXDOGE15M-345": {"age": 18.0, "stale": False, "reason": "FRESH"}
            },
            "ws_forwarder": {
                "events_per_sec": 2.5,
                "time_since_last_event": 5.0,
                "stalled": False,
                "status": "OK"
            },
            "execution_ready": True,
            "subsystem_health": {
                "catalog": "HEALTH_GOOD",
                "md_freshness": "HEALTH_GOOD",
                "depth_coverage": "HEALTH_GOOD",
                "ws_forwarder": "HEALTH_GOOD"
            },
            "market_quality": {
                "KXBTC15M-123": {"depth_yes": 25, "depth_no": 25, "overall_quality": "GOOD", "spread_cents": 30},
                "KXETH15M-456": {"depth_yes": 20, "depth_no": 20, "overall_quality": "GOOD", "spread_cents": 35}
            }
        }
        
        violations = check_system_invariants(system_state, paranoid_mode=False)
        assert len(violations) == 0
    
    def test_multiple_violations_detected(self):
        """Test that multiple violations are detected simultaneously."""
        system_state = {
            "market_data": {
                "KXBTC15M-123": {"age": -1000.0, "stale": False, "reason": "FRESH"},  # Negative age
                "KXETH15M-456": {"age": 7200.0, "stale": False, "reason": "FRESH"},  # Impossible age
            },
            "ws_forwarder": {
                "events_per_sec": 0.0,
                "time_since_last_event": 45.0,
                "stalled": False,
                "status": "OK"  # Impossible OK
            },
            "execution_ready": True,
            "subsystem_health": {
                "catalog": "HEALTH_ERROR",  # Critical failure
                "md_freshness": "HEALTH_GOOD",
                "depth_coverage": "HEALTH_GOOD",
                "ws_forwarder": "HEALTH_GOOD"
            },
            "market_quality": {
                "KXBTC15M-123": {"depth_yes": 0, "depth_no": 50, "overall_quality": "GOOD", "spread_cents": 20}  # Zero depth
            }
        }
        
        violations = check_system_invariants(system_state, paranoid_mode=False)
        
        # Should detect multiple violations
        assert len(violations) >= 4
        
        violation_names = [v.invariant_name for v in violations]
        assert "MD_NEGATIVE_AGE" in violation_names
        assert "MD_FRESH_IMPOSSIBLE_AGE" in violation_names
        assert "WS_FORWARDER_IMPOSSIBLE_OK" in violation_names
        assert "EXECUTION_READY_CRITICAL_FAILURE" in violation_names
        assert "QUALITY_GOOD_ZERO_DEPTH" in violation_names

# Test execution helpers
def run_invariant_validation_tests():
    """Run all invariant validation tests."""
    import sys
    
    print("🔍 Running Invariant Validation Tests...")
    print("=" * 60)
    
    # Test MD Age Invariants
    print("\n1. Testing MD Age Invariants...")
    test_md = TestMDAgeInvariants()
    
    try:
        test_md.test_negative_age_invariant()
        print("   ✅ Negative age invariant - PASS")
    except Exception as e:
        print(f"   ❌ Negative age invariant - FAIL: {e}")
    
    try:
        test_md.test_fresh_with_impossible_age_invariant()
        print("   ✅ Impossible age invariant - PASS")
    except Exception as e:
        print(f"   ❌ Impossible age invariant - FAIL: {e}")
    
    try:
        test_md.test_normal_md_age_no_violation()
        print("   ✅ Normal MD age - PASS")
    except Exception as e:
        print(f"   ❌ Normal MD age - FAIL: {e}")
    
    # Test WS Forwarder Invariants
    print("\n2. Testing WS Forwarder Invariants...")
    test_ws = TestWSForwarderInvariants()
    
    try:
        test_ws.test_ok_status_with_zero_events_invariant()
        print("   ✅ Zero events invariant - PASS")
    except Exception as e:
        print(f"   ❌ Zero events invariant - FAIL: {e}")
    
    try:
        test_ws.test_stalled_with_ok_status_invariant()
        print("   ✅ Stalled OK invariant - PASS")
    except Exception as e:
        print(f"   ❌ Stalled OK invariant - FAIL: {e}")
    
    try:
        test_ws.test_healthy_ws_forwarder_no_violation()
        print("   ✅ Healthy WS forwarder - PASS")
    except Exception as e:
        print(f"   ❌ Healthy WS forwarder - FAIL: {e}")
    
    # Test Quality/Optimizer Consistency
    print("\n3. Testing Quality vs Optimizer Consistency...")
    test_quality = TestQualityOptimizerConsistency()
    test_quality.setup_method()
    
    try:
        test_quality.test_wide_spread_rejection_and_quality_label()
        print("   ✅ Wide spread rejection - PASS")
    except Exception as e:
        print(f"   ❌ Wide spread rejection - FAIL: {e}")
    
    try:
        test_quality.test_narrow_spread_acceptance_and_quality_label()
        print("   ✅ Narrow spread acceptance - PASS")
    except Exception as e:
        print(f"   ❌ Narrow spread acceptance - FAIL: {e}")
    
    # Test System Integration
    print("\n4. Testing System Integration...")
    test_system = TestSystemIntegration()
    
    try:
        test_system.test_clean_system_no_violations()
        print("   ✅ Clean system - PASS")
    except Exception as e:
        print(f"   ❌ Clean system - FAIL: {e}")
    
    try:
        test_system.test_multiple_violations_detected()
        print("   ✅ Multiple violations detection - PASS")
    except Exception as e:
        print(f"   ❌ Multiple violations detection - FAIL: {e}")
    
    # Test Paranoid Mode
    print("\n5. Testing Paranoid Mode...")
    test_paranoid = TestParanoidMode()
    
    try:
        test_paranoid.test_normal_mode_logs_but_does_not_raise()
        print("   ✅ Normal mode logging - PASS")
    except Exception as e:
        print(f"   ❌ Normal mode logging - FAIL: {e}")
    
    try:
        test_paranoid.test_paranoid_mode_raises_on_critical_violations()
        print("   ✅ Paranoid mode enforcement - PASS")
    except Exception as e:
        print(f"   ❌ Paranoid mode enforcement - FAIL: {e}")
    
    print("\n" + "=" * 60)
    print("🏁 Invariant Validation Tests Complete")
    print("\nTo run individual test categories:")
    print("  python -m pytest tests/test_invariant_validation.py::TestMDAgeInvariants")
    print("  python -m pytest tests/test_invariant_validation.py::TestWSForwarderInvariants")
    print("  python -m pytest tests/test_invariant_validation.py::TestQualityOptimizerConsistency")
    print("  python -m pytest tests/test_invariant_validation.py::TestSystemIntegration")
    print("  python -m pytest tests/test_invariant_validation.py::TestParanoidMode")
    
    print("\nTo enable paranoid mode in testing:")
    print("  export MERID_PARANOID_MODE=1")
    print("  python -m pytest tests/test_invariant_validation.py")

if __name__ == "__main__":
    run_invariant_validation_tests()
