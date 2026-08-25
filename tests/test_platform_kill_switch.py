"""Tests for Platform-Level Kill Switch implementation.

CRITICAL FIX (2026-07-17): Tests for platform-level kill switch with circuit breaker hierarchy.
"""

import pytest
import threading
from datetime import datetime, timezone
from merid.risk.platform_kill_switch import (
    PlatformKillSwitch,
    KillSwitchReason,
    CircuitBreaker,
    CircuitBreakerState,
    get_platform_kill_switch,
    can_trade,
    get_kill_reason,
)


class TestPlatformKillSwitch:
    """Test platform kill switch functionality."""
    
    def _reset_singleton(self):
        """Helper to reset singleton state."""
        PlatformKillSwitch._instance = None
        PlatformKillSwitch._initialized = False
        PlatformKillSwitch._lock = threading.Lock()
    
    def test_singleton_pattern(self):
        """Test that PlatformKillSwitch is a singleton."""
        self._reset_singleton()
        
        ks1 = get_platform_kill_switch()
        ks2 = get_platform_kill_switch()
        
        assert ks1 is ks2
    
    def test_initial_state(self):
        """Test initial kill switch state."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        assert ks.state.active is False
        assert ks.state.reason is None
        assert ks.can_trade() is True
    
    def test_activate_kill_switch(self):
        """Test activating kill switch."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        result = ks.activate(KillSwitchReason.MANUAL, triggered_by="test")
        
        assert result is True
        assert ks.state.active is True
        assert ks.state.reason == KillSwitchReason.MANUAL
        assert ks.state.triggered_by == "test"
        assert ks.can_trade() is False
    
    def test_activate_already_active_no_force(self):
        """Test activating when already active without force."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        ks.activate(KillSwitchReason.MANUAL, triggered_by="test1")
        result = ks.activate(KillSwitchReason.DAILY_LOSS, triggered_by="test2")
        
        assert result is False
        assert ks.state.reason == KillSwitchReason.MANUAL  # Original reason preserved
    
    def test_activate_already_active_with_force(self):
        """Test activating when already active with force."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        ks.activate(KillSwitchReason.MANUAL, triggered_by="test1")
        result = ks.activate(KillSwitchReason.DAILY_LOSS, triggered_by="test2", force=True)
        
        assert result is True
        assert ks.state.reason == KillSwitchReason.DAILY_LOSS  # New reason
    
    def test_deactivate_kill_switch(self):
        """Test deactivating kill switch."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        ks.activate(KillSwitchReason.MANUAL, triggered_by="test")
        result = ks.deactivate(triggered_by="test")
        
        assert result is True
        assert ks.state.active is False
        assert ks.state.reason is None
        assert ks.can_trade() is True
    
    def test_deactivate_not_active(self):
        """Test deactivating when not active."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        result = ks.deactivate(triggered_by="test")
        
        assert result is False
    
    def test_update_metrics_daily_loss_breach(self):
        """Test that daily loss breach activates kill switch."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        # Set daily loss below limit (should not activate)
        ks.update_metrics(daily_loss_pct=-0.01, drawdown_pct=0.0)
        assert ks.can_trade() is True
        
        # Set daily loss at limit (should not activate yet)
        ks.update_metrics(daily_loss_pct=-0.02, drawdown_pct=0.0)
        assert ks.can_trade() is True
        
        # Set daily loss below limit (should activate after circuit breaker failures)
        ks.update_metrics(daily_loss_pct=-0.03, drawdown_pct=0.0)
        # Circuit breaker needs multiple failures
        for _ in range(3):
            ks.update_metrics(daily_loss_pct=-0.03, drawdown_pct=0.0)
        
        # After enough failures, should activate
        assert ks.state.active is True
        assert ks.state.reason == KillSwitchReason.DAILY_LOSS
    
    def test_update_metrics_drawdown_breach(self):
        """Test that drawdown breach activates kill switch."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        # Set drawdown below limit
        ks.update_metrics(daily_loss_pct=0.0, drawdown_pct=-0.06)
        
        # Circuit breaker needs multiple failures
        for _ in range(3):
            ks.update_metrics(daily_loss_pct=0.0, drawdown_pct=-0.06)
        
        # After enough failures, should activate
        assert ks.state.active is True
        assert ks.state.reason == KillSwitchReason.DRAWDOWN
    
    def test_circuit_breaker_state(self):
        """Test circuit breaker states."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        # Initially closed
        assert ks._daily_loss_breaker.state == CircuitBreakerState.CLOSED
        assert ks._daily_loss_breaker.can_proceed() is True
        
        # Record failures
        ks._daily_loss_breaker.record_failure()
        ks._daily_loss_breaker.record_failure()
        assert ks._daily_loss_breaker.state == CircuitBreakerState.CLOSED
        
        # Third failure opens circuit
        ks._daily_loss_breaker.record_failure()
        assert ks._daily_loss_breaker.state == CircuitBreakerState.OPEN
        assert ks._daily_loss_breaker.can_proceed() is False
    
    def test_circuit_breaker_reset(self):
        """Test circuit breaker reset."""
        ks = get_platform_kill_switch()
        
        # Open circuit
        for _ in range(3):
            ks._daily_loss_breaker.record_failure()
        assert ks._daily_loss_breaker.state == CircuitBreakerState.OPEN
        
        # Reset
        ks._daily_loss_breaker.reset()
        assert ks._daily_loss_breaker.state == CircuitBreakerState.CLOSED
        assert ks._daily_loss_breaker.failure_count == 0
    
    def test_callback_registration(self):
        """Test callback registration on state change."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        callback_called = []
        
        def callback(state):
            callback_called.append(state)
        
        ks.register_callback(callback)
        ks.activate(KillSwitchReason.MANUAL, triggered_by="test")
        
        assert len(callback_called) == 1
        assert callback_called[0].active is True
    
    def test_get_status(self):
        """Test getting kill switch status."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        status = ks.get_status()
        
        assert "state" in status
        assert "circuit_breakers" in status
        assert "can_trade" in status
        assert status["can_trade"] is True


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def _reset_singleton(self):
        """Helper to reset singleton state."""
        PlatformKillSwitch._instance = None
        PlatformKillSwitch._initialized = False
        PlatformKillSwitch._lock = threading.Lock()
    
    def test_can_trade_function(self):
        """Test can_trade convenience function."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        assert can_trade() is True
        
        ks.activate(KillSwitchReason.MANUAL, triggered_by="test")
        assert can_trade() is False
    
    def test_get_kill_reason_function(self):
        """Test get_kill_reason convenience function."""
        self._reset_singleton()
        
        ks = get_platform_kill_switch()
        
        assert get_kill_reason() is None
        
        ks.activate(KillSwitchReason.DAILY_LOSS, triggered_by="test")
        assert get_kill_reason() == "daily_loss"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
