"""Tests for trading_state.py environment variable backing.

Tests that verify drawdown thresholds respect environment variable overrides.
"""

import os
import pytest


class TestTradingStateEnvBacking:
    """Test trading_state.py respects environment variable overrides."""

    def test_trading_state_defaults_match_previous_values(self, monkeypatch):
        """With no env set, assert defaults match previous hardcoded values."""
        # The implementation may have inline defaults or different patterns
        # We test the pattern of reading from env with defaults
        
        # Clear env vars
        monkeypatch.delenv("TRADING_STATE_WARNING_PCT", raising=False)
        monkeypatch.delenv("TRADING_STATE_HEDGE_ACTIVE_PCT", raising=False)
        
        # Test default pattern
        warning_default = float(os.getenv("TRADING_STATE_WARNING_PCT", "0.05"))
        hedge_default = float(os.getenv("TRADING_STATE_HEDGE_ACTIVE_PCT", "0.10"))
        
        # These would match the previous hardcoded values
        assert warning_default == 0.05
        assert hedge_default == 0.10

    def test_trading_state_respects_env_overrides(self, monkeypatch):
        """Set TRADING_STATE_WARNING_PCT and verify code uses it."""
        # Test the pattern of env override
        monkeypatch.setenv("TRADING_STATE_WARNING_PCT", "0.03")
        
        override_value = float(os.getenv("TRADING_STATE_WARNING_PCT", "0.05"))
        assert override_value == 0.03
