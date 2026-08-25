"""Tests for $2 global exposure cap as single source of truth.

Verifies that:
- GlobalSlotAllocator enforces $2 cap as the only exposure limit
- All contradictory order flow limits have been removed
- Rate limits are behavioral throttles, not exposure limits
- No code path uses removed limits (max_concurrent_trades, max_orders_per_15m_window, per_strip_order_limit)
"""

import os
import pytest
from pathlib import Path

# Set profile for tests
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"


class Test2DollarCapSingleSourceOfTruth:
    """Verify $2 cap is the single source of truth for exposure."""

    def test_global_slot_allocator_enforces_2dollar_cap(self):
        """Verify GlobalSlotAllocator enforces $2 exposure cap."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        
        assert GlobalSlotAllocator.MAX_EXPOSURE_USD == 2.00, "MAX_EXPOSURE_USD must be $2.00"
        assert GlobalSlotAllocator.MAX_CONTRACTS_PER_ORDER == 2, "MAX_CONTRACTS_PER_ORDER must be 2"
        assert GlobalSlotAllocator.MAX_POSITIONS_PER_ASSET == 1, "MAX_POSITIONS_PER_ASSET must be 1"

    def test_profile_yaml_has_no_contradictory_limits(self):
        """Verify profile YAML has no contradictory order flow limits."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        content = profile_path.read_text(encoding="utf-8")
        
        # These limits should NOT exist (contradict $1 cap)
        assert "max_concurrent_trades:" not in content, "max_concurrent_trades should be removed from profile"
        assert "max_orders_per_15m_window:" not in content, "max_orders_per_15m_window should be removed from profile"
        assert "max_orders_per_cycle:" not in content, "max_orders_per_cycle should be removed from profile"
        assert "max_contracts_total:" not in content, "max_contracts_total should be removed from profile"
        assert "max_contracts_per_asset:" not in content, "max_contracts_per_asset should be removed from profile"
        assert "max_contracts_per_cluster:" not in content, "max_contracts_per_cluster should be removed from profile"
        
        # These should exist (align with $2 cap)
        assert "max_single_order_contracts: 2" in content, "max_single_order_contracts should be 2"
        assert "max_yes_position: 2" in content, "max_yes_position should be 2"
        assert "max_no_position: 2" in content, "max_no_position should be 2"
        assert "fixed_exposure_cap_usd: 2.00" in content, "fixed_exposure_cap_usd should be 2.00"

    def test_agent_grid_config_has_removed_limits(self):
        """Verify LeanAgentConfig has removed contradictory limits."""
        from merid.prediction.agent_grid_15m import LeanAgentConfig
        
        config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
        
        # These should NOT exist (removed)
        assert not hasattr(config, 'per_strip_order_limit'), "per_strip_order_limit should be removed"
        assert not hasattr(config, 'max_orders_per_15m_window'), "max_orders_per_15m_window should be removed"
        
        # These should exist (behavioral throttles, not exposure limits)
        assert hasattr(config, 'per_asset_cooldown_s'), "per_asset_cooldown_s should exist"
        assert hasattr(config, 'consecutive_loss_pause'), "consecutive_loss_pause should exist"

    def test_loop_15m_has_removed_max_concurrent_trades(self):
        """Verify loop_15m has removed max_concurrent_trades."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Check that _max_concurrent_trades is not used for limiting
        # It may exist for tracking but should not enforce limits
        import inspect
        source = inspect.getsource(Kalshi15mLoop.__init__)
        
        # Should not have max_concurrent_trades enforcement
        assert "max_concurrent_trades" not in source or "tracking only" in source.lower(), \
            "max_concurrent_trades should not enforce limits (may be used for tracking only)"

    def test_risk_envelope_has_removed_max_concurrent_trades(self):
        """Verify risk envelope has removed max_concurrent_trades."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        # Should not have max_concurrent_trades field
        assert not hasattr(KalshiCrypto15mRiskEnvelope, 'max_concurrent_trades'), \
            "KalshiCrypto15mRiskEnvelope should not have max_concurrent_trades"

    def test_crypto_15m_profile_has_removed_fields(self):
        """Verify crypto_15m_profile has removed contradictory fields."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # These should NOT exist in the dataclass
        profile_fields = [f.name for f in Crypto15mProfile.__dataclass_fields__.values()]
        
        assert 'agent_max_concurrent_trades' not in profile_fields, \
            "agent_max_concurrent_trades should be removed from profile"
        assert 'throttling_per_strip_order_limit' not in profile_fields, \
            "throttling_per_strip_order_limit should be removed from profile"
        assert 'throttling_max_orders_per_15m_window' not in profile_fields, \
            "throttling_max_orders_per_15m_window should be removed from profile"

    def test_rate_limits_are_behavioral_not_exposure(self):
        """Verify rate limits are behavioral throttles, not exposure limits."""
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        profile = profile_adapter.profile
        
        # Rate limits should be conservative (behavioral throttles)
        # With $1 cap, realistic usage is ~0.67-1.33 orders/min
        # Rate limit should be generous ceiling (4-7x realistic usage)
        assert profile.throttling_global_orders_limit <= 10, \
            f"global_orders_limit should be conservative (got {profile.throttling_global_orders_limit})"
        
        # Should have comment explaining it's behavioral, not exposure
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        content = profile_path.read_text(encoding="utf-8")
        
        throttling_section = content[content.find("throttling:"):content.find("throttling:") + 500]
        assert "behavioral throttle" in throttling_section.lower() or "not exposure limit" in throttling_section.lower(), \
            "Throttling section should document that it's behavioral, not exposure limit"

    def test_settings_aligned_with_profile(self):
        """Verify settings.py has comment explaining $2 cap alignment."""
        # Note: Settings may load from .env file, so we only check the comment
        # The actual value alignment is tested in test_risk_threshold_fixes.py
        
        import inspect
        from merid.settings import Settings
        source = inspect.getsource(Settings)
        assert "$2 cap" in source or "exposure cap" in source, \
            "Settings should document alignment with $2 cap"


class Test2DollarCapMathematicalConsistency:
    """Verify mathematical consistency of $2 cap with other limits."""

    def test_2dollar_cap_max_positions(self):
        """Verify $2 cap allows realistic number of positions."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        
        # With $2 cap and 2 contracts/order at max 75c
        # Maximum positions = floor(2.00 / 0.10) = 20 (at min price)
        # Realistic positions = 1-4 (at 50-75c)
        max_positions_min_price = int(GlobalSlotAllocator.MAX_EXPOSURE_USD / 0.10)
        max_positions_max_price = int(GlobalSlotAllocator.MAX_EXPOSURE_USD / 0.75)
        
        assert max_positions_min_price >= 1, "Should allow at least 1 position at min price"
        assert max_positions_max_price >= 1, "Should allow at least 1 position at max price"
        assert max_positions_max_price <= 4, "Should allow at most 4 positions at max price"

    def test_rate_limits_generous_ceiling(self):
        """Verify rate limits are generous ceiling relative to realistic usage."""
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        profile = profile_adapter.profile
        
        # Realistic orders per 15m cycle: 1-2 positions × 1-2 entries/exits = 2-4 orders
        # Realistic orders per minute: 2-4 orders / 15 min = 0.13-0.27 orders/min
        # Rate limit should be generous ceiling (10-20x realistic usage)
        realistic_orders_per_min = 4 / 15  # 0.27
        rate_limit = profile.throttling_global_orders_limit
        
        ceiling_ratio = rate_limit / realistic_orders_per_min
        assert ceiling_ratio >= 10, \
            f"Rate limit should be at least 10x realistic usage (got {ceiling_ratio:.1f}x)"
        assert ceiling_ratio <= 50, \
            f"Rate limit should not be excessively high (got {ceiling_ratio:.1f}x)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
