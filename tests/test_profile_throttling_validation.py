"""Tests for profile-driven throttling and market state validation.

This test suite ensures:
- Throttling config is loaded from profile
- Market state validation rejects orders on all invariant violations
- Failsafe sizing is profile-configured
"""

import os
import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch, MagicMock

# Set profile for tests
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"


class TestThrottlingProfileLoading:
    """Test that throttling config is loaded from profile correctly."""
    
    def test_throttling_config_loaded_from_profile(self):
        """Test that throttling values are loaded from profile YAML."""
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        assert profile_adapter is not None, "Profile should be loaded"
        
        profile = profile_adapter.profile
        
        # Verify throttling fields are loaded
        assert hasattr(profile, 'throttling_global_orders_window_sec')
        assert hasattr(profile, 'throttling_global_orders_limit')
        assert hasattr(profile, 'throttling_per_asset_cooldown_sec')
        assert hasattr(profile, 'throttling_per_strip_order_limit')
        assert hasattr(profile, 'throttling_per_strip_notional_usd')
        
        # Verify reasonable defaults
        assert profile.throttling_global_orders_window_sec > 0
        assert profile.throttling_global_orders_limit > 0
        assert profile.throttling_per_asset_cooldown_sec >= 0
        assert profile.throttling_per_strip_order_limit >= 1
        assert profile.throttling_per_strip_notional_usd >= 0


class TestMarketStateValidation:
    """Test that validate_market_state_for_entry rejects on all invariants."""
    
    def test_state_none_rejection(self):
        """Test that state=None is rejected with STATE-NONE reason."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=None,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "STATE-NONE"
    
    def test_book_not_initialized_rejection(self):
        """Test that book_initialized=False is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = False
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "BOOK-NOT-INITIALIZED"
    
    def test_not_executable_rejection(self):
        """Test that executable=False is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = False
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "NOT-EXECUTABLE"
    
    def test_md_stale_rejection(self):
        """Test that stale MD is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc).timestamp() - 20  # 20 seconds ago
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "MD-STALE"
    
    def test_pattern_0_100_rejection(self):
        """Test that 0/100 bid/ask pattern is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 0
        state.best_ask_cents = 100
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "PATTERN-0100"
    
    def test_no_bidask_rejection(self):
        """Test that zero bid/ask is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 0
        state.best_ask_cents = 0
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "NO-BIDASK"
    
    def test_expiry_too_close_rejection(self):
        """Test that expiry too close is rejected."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.yes_depth = 10
        state.no_depth = 10
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=2,  # Below 3 minute threshold
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "EXPIRY-TOO-CLOSE"


class TestFailsafeSizing:
    """Test that failsafe sizing is profile-configured."""
    
    def test_failsafe_config_loaded_from_profile(self):
        """Test that failsafe max contracts is loaded from profile."""
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        if profile_adapter is None:
            pytest.skip("Profile not available")
        
        profile = profile_adapter.profile
        
        # Verify failsafe field is loaded
        assert hasattr(profile, 'failsafe_max_contracts_per_order')
        assert profile.failsafe_max_contracts_per_order >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
