"""Tests for FaultManager - degraded mode by default, shutdown only on critical failure."""

from __future__ import annotations

import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from core.fault_manager import (
    FaultManager,
    HealthState,
    CircuitState,
    get_fault_manager,
    reset_fault_manager,
)


class TestFaultManagerBasics:
    """Test basic FaultManager functionality."""
    
    def setup_method(self):
        """Reset fault manager before each test."""
        reset_fault_manager()
    
    def test_venue_degraded_transition(self):
        """Venue should transition to DEGRADED on mark_venue_degraded."""
        fm = get_fault_manager()
        
        fm.mark_venue_degraded("kalshi", "test_failure")
        
        health = fm._get_venue("kalshi")
        assert health.state == HealthState.DEGRADED
        assert health.failure_count == 1
        assert len(health.reasons) == 1
        assert "test_failure" in health.reasons[0]
    
    def test_venue_offline_transition(self):
        """Venue should transition to OFFLINE on mark_venue_offline."""
        fm = get_fault_manager()
        
        fm.mark_venue_offline("kalshi", "circuit_open", circuit_open=True)
        
        health = fm._get_venue("kalshi")
        assert health.state == HealthState.OFFLINE
        assert health.circuit_state == CircuitState.OPEN
    
    def test_venue_recovered_transition(self):
        """Venue should transition to OK on mark_venue_recovered."""
        fm = get_fault_manager()
        
        # First degrade it
        fm.mark_venue_degraded("kalshi", "test_failure")
        # Then recover
        fm.mark_venue_recovered("kalshi")
        
        health = fm._get_venue("kalshi")
        assert health.state == HealthState.OK
        assert health.circuit_state == CircuitState.CLOSED
        assert health.failure_count == 0
    
    def test_core_health_updates_with_offline_venues(self):
        """Core health should track offline venues."""
        fm = get_fault_manager()
        
        fm.mark_venue_offline("kalshi", "test_failure")
        
        assert fm._core.state == HealthState.DEGRADED
        assert "kalshi" in fm._core.venues_offline
    
    def test_core_recovered_when_all_venues_online(self):
        """Core should return to OK when all venues recovered."""
        fm = get_fault_manager()
        
        fm.mark_venue_offline("kalshi", "test_failure")
        fm.mark_venue_recovered("kalshi")
        
        assert fm._core.state == HealthState.OK
        assert fm._core.venues_offline == []


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def setup_method(self):
        """Reset fault manager before each test."""
        reset_fault_manager()
        # Use short timeout for testing
        os.environ["MERID_KALSHI_CB_RECOVERY_TIMEOUT_SEC"] = "0.1"
    
    def test_circuit_closed_initially(self):
        """Circuit should start in CLOSED state."""
        fm = get_fault_manager()
        
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.CLOSED
        assert fm.can_attempt_reconnect("kalshi") is True
    
    def test_circuit_opens_after_failures(self):
        """Circuit should OPEN after threshold failures."""
        fm = get_fault_manager()
        threshold = fm._cb_failure_threshold
        
        # Record threshold failures
        for _ in range(threshold):
            fm.record_circuit_failure("kalshi")
        
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.OPEN
        # Cannot reconnect when circuit is open (and recovery timeout not elapsed)
        assert fm.can_attempt_reconnect("kalshi") is False
    
    def test_circuit_success_resets(self):
        """Recording success should reset circuit to CLOSED."""
        fm = get_fault_manager()
        
        # Open the circuit
        for _ in range(fm._cb_failure_threshold):
            fm.record_circuit_failure("kalshi")
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.OPEN
        
        # Success resets
        fm.record_circuit_success("kalshi")
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.CLOSED
    
    def test_circuit_half_open_after_recovery_timeout(self):
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        fm = get_fault_manager()
        threshold = fm._cb_failure_threshold
        
        # Open the circuit
        for _ in range(threshold):
            fm.record_circuit_failure("kalshi")
        
        # Wait for recovery timeout
        import time
        time.sleep(0.15)  # Wait slightly longer than 0.1s timeout
        
        # Should now allow reconnect (transition to half-open)
        assert fm.can_attempt_reconnect("kalshi") is True
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.HALF_OPEN
    
    def test_circuit_failure_in_half_open_returns_to_open(self):
        """Failure in half-open should return to open."""
        fm = get_fault_manager()
        threshold = fm._cb_failure_threshold
        
        # Open, wait, transition to half-open
        for _ in range(threshold):
            fm.record_circuit_failure("kalshi")
        
        import time
        time.sleep(0.15)
        fm.can_attempt_reconnect("kalshi")  # Trigger half-open transition
        
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.HALF_OPEN
        
        # Failure in half-open
        fm.record_circuit_failure("kalshi")
        assert fm.get_venue_circuit_state("kalshi") == CircuitState.OPEN


class TestShutdownDecision:
    """Test shutdown decision logic."""
    
    def setup_method(self):
        """Reset fault manager before each test."""
        reset_fault_manager()
    
    def test_no_shutdown_without_fatal(self):
        """Should not shutdown without any fatal errors."""
        fm = get_fault_manager()
        
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is False
    
    def test_shutdown_with_core_critical(self):
        """Should shutdown when core is CRITICAL."""
        fm = get_fault_manager()
        
        fm.mark_core_critical("test_critical")
        
        # With core critical, should shutdown even with moderate lag
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is True
    
    def test_shutdown_with_extreme_lag_and_critical(self):
        """Should shutdown with extreme lag and critical event."""
        fm = get_fault_manager()
        
        fm.mark_core_critical("test_critical")
        
        # Extreme lag (>5000ms) + critical = shutdown
        assert fm.should_initiate_shutdown(lag_ms=6000, lag_p95=6000) is True
    
    def test_no_shutdown_with_only_venue_offline(self):
        """Should NOT shutdown with only one venue offline (degraded mode)."""
        fm = get_fault_manager()
        
        fm.mark_venue_offline("kalshi", "test_failure")
        
        # Single venue offline should not trigger shutdown
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is False
    
    def test_shutdown_with_multiple_venues_offline(self):
        """Should shutdown when multiple venues are offline."""
        fm = get_fault_manager()
        
        fm.mark_venue_offline("kalshi", "test_failure")
        fm.mark_venue_offline("other_venue", "test_failure")
        
        # Multiple venues offline = shutdown
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is True
    
    def test_no_shutdown_when_degraded_mode_allowed(self):
        """Should NOT shutdown when MERID_ALLOW_DEGRADED_KALSHI=1."""
        os.environ["MERID_ALLOW_DEGRADED_KALSHI"] = "1"
        reset_fault_manager()
        
        fm = get_fault_manager()
        fm.mark_venue_offline("kalshi", "test_failure")
        
        # With degraded mode enabled, single venue failure shouldn't shutdown
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is False
    
    def test_shutdown_on_asgi_fatal_flag(self):
        """Should shutdown immediately when MERID_SHUTDOWN_ON_ASGI_FATAL=1."""
        os.environ["MERID_SHUTDOWN_ON_ASGI_FATAL"] = "1"
        reset_fault_manager()
        
        fm = get_fault_manager()
        fm.mark_core_critical("test_fatal")
        
        # With shutdown_on_fatal enabled, critical events trigger shutdown
        assert fm.should_initiate_shutdown(lag_ms=100, lag_p95=100) is True
    
    def test_no_shutdown_before_n_fails(self):
        """Should NOT shutdown before N failures when threshold set."""
        os.environ["MERID_FATAL_SHUTDOWN_AFTER_N_FAILS"] = "3"
        reset_fault_manager()
        
        fm = get_fault_manager()
        
        # Only 2 critical events, threshold is 3
        fm.mark_core_critical("fail1")
        fm.mark_core_critical("fail2")
        
        assert fm.should_initiate_shutdown(lag_ms=6000, lag_p95=6000) is False
        
        # After 3rd critical event, should shutdown
        fm.mark_core_critical("fail3")
        assert fm.should_initiate_shutdown(lag_ms=6000, lag_p95=6000) is True


class TestHealthSummary:
    """Test health summary generation."""
    
    def setup_method(self):
        """Reset fault manager before each test."""
        reset_fault_manager()
    
    def test_health_summary_structure(self):
        """Health summary should have correct structure."""
        fm = get_fault_manager()
        
        fm.mark_venue_degraded("kalshi", "test_failure")
        
        summary = fm.get_health_summary()
        
        assert "core" in summary
        assert "venues" in summary
        assert "config" in summary
        assert "kalshi" in summary["venues"]
        assert summary["venues"]["kalshi"]["state"] == "DEGRADED"


@pytest.mark.asyncio
class TestAsyncIntegration:
    """Test async integration patterns."""
    
    def setup_method(self):
        """Reset fault manager before each test."""
        reset_fault_manager()
    
    async def test_recovery_attempt_tracking(self):
        """Test recovery attempt tracking."""
        fm = get_fault_manager()
        
        fm.mark_recovery_attempt("kalshi", 1, half_open=True)
        
        health = fm._get_venue("kalshi")
        assert health.recovery_attempts == 1
        assert health.circuit_state == CircuitState.HALF_OPEN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
