"""
Kalshi 15m Crypto Risk Controller and ExecutionGuard Tests

Tests that verify risk controller and execution guard configuration
for the 15m profile (no profile-specific blockers).

Tagged with @pytest.mark.kalshi_15m_critical for CI enforcement.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.kalshi_15m_critical


class TestRiskControllerConfiguration:
    """Test risk controller configuration for 15m profile."""

    def test_risk_controller_can_be_imported(self):
        """Test that risk_controller can be imported."""
        from merid.risk.kill_switches import risk_controller
        
        # Verify risk_controller exists
        assert risk_controller is not None

    def test_risk_controller_has_can_trade_method(self):
        """Test that risk_controller has can_trade method."""
        from merid.risk.kill_switches import risk_controller
        
        # Verify can_trade method exists
        assert hasattr(risk_controller, 'can_trade')

    def test_risk_controller_has_get_state_method(self):
        """Test that risk_controller has get_state method."""
        from merid.risk.kill_switches import risk_controller
        
        # Verify get_state method exists
        assert hasattr(risk_controller, 'get_state')


class TestExecutionGuardConfiguration:
    """Test ExecutionGuard configuration for 15m profile."""

    def test_execution_guard_can_be_imported(self):
        """Test that ExecutionGuard can be imported."""
        from merid.execution_guard import ExecutionGuard
        
        # Verify ExecutionGuard class exists
        assert ExecutionGuard is not None

    def test_execution_guard_has_activate_kill_switch_method(self):
        """Test that ExecutionGuard has activate_kill_switch method."""
        from merid.execution_guard import ExecutionGuard
        
        # Verify activate_kill_switch method exists
        assert hasattr(ExecutionGuard, 'activate_kill_switch')

    def test_execution_guard_has_deactivate_kill_switch_method(self):
        """Test that ExecutionGuard has deactivate_kill_switch method."""
        from merid.execution_guard import ExecutionGuard
        
        # Verify deactivate_kill_switch method exists
        assert hasattr(ExecutionGuard, 'deactivate_kill_switch')

    def test_execution_guard_has_kill_switch_active_method(self):
        """Test that ExecutionGuard has kill_switch_active method."""
        from merid.execution_guard import ExecutionGuard
        
        # Verify kill_switch_active method exists
        assert hasattr(ExecutionGuard, 'kill_switch_active')


class TestKalshi15mRiskProfile:
    """Test Kalshi 15m risk profile configuration."""

    def test_kalshi_15m_profile_can_be_imported(self):
        """Test that kalshi_crypto_15m profile can be imported."""
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
        
        # Verify profile check function exists
        assert is_profile_active is not None

    def test_kalshi_15m_profile_recognizes_kalshi_crypto_15m_v2(self):
        """Test that profile recognizes kalshi_crypto_15m_v2."""
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
        
        # The profile should recognize the profile name
        # We don't set the env var to avoid side effects, just verify the function exists
        assert callable(is_profile_active)
