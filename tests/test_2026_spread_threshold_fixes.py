"""Tests for 2026-07-12 spread threshold fixes based on industry research.

Research findings:
- Industry standard: 15-20c max spread for 15m crypto (short-duration markets)
- Industry standard: 8-10c quality filter for momentum entries
- Industry standard: 5-10c for liquid markets, 15-20c for 15m crypto
- Previous 100c was 5-20x industry recommendation, allowing extremely illiquid markets
- Aligned with 10-75c canonical entry price range
"""

import os
from unittest.mock import patch
import pytest


def test_min_spread_gate_cents_aligned_to_8c():
    """Test that min_spread_gate_cents is aligned to 8c based on 2026 industry research."""
    import yaml
    
    # Load the profile YAML directly with UTF-8 encoding
    with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify min_spread_gate_cents is 8c (aligned with industry: 8-10c quality filter)
    assert profile_config['guardrails']['min_spread_gate_cents'] == 8, \
        f"min_spread_gate_cents should be 8c, got {profile_config['guardrails']['min_spread_gate_cents']}"


def test_volatility_regime_edge_adjustment_disabled():
    """Test that volatility_regime_edge_adjustment is disabled to prevent edge crushing."""
    with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
        from merid.risk.profiles.crypto_15m_profile import _active_adapter
        import merid.risk.profiles.crypto_15m_profile as profile_module
        profile_module._active_adapter = None
        
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        profile = adapter.profile
        
        # Verify volatility_regime_edge_adjustment is disabled
        assert profile.volatility_regime_edge_adjustment_enabled == False, \
            "volatility_regime_edge_adjustment should be disabled to prevent edge crushing to 0.01%"


def test_order_router_default_spread_threshold_20c():
    """Test that order_router default max_spread_cents is 20c (aligned with industry research)."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # Call with default parameters and sufficient depth
    # Both YES and NO spreads must be within threshold
    result, reason = check_market_microstructure(
        yes_bid_cents=40,
        yes_ask_cents=60,  # 20c YES spread
        no_bid_cents=35,
        no_ask_cents=55,  # 20c NO spread
        yes_depth=5,
        no_depth=5,
        min_depth_usd=0.0  # Disable depth check for this test
    )
    
    # Should pass with 20c spread (default)
    assert result, f"Should pass with 20c spread, but got: {reason}"
    
    # Test with 21c YES spread (should fail)
    result, reason = check_market_microstructure(
        yes_bid_cents=40,
        yes_ask_cents=61,  # 21c YES spread
        no_bid_cents=35,
        no_ask_cents=55,  # 20c NO spread
        yes_depth=5,
        no_depth=5,
        min_depth_usd=0.0  # Disable depth check for this test
    )
    
    assert not result, "Should fail with 21c spread"
    assert "spread" in reason.lower(), f"Reason should mention spread: {reason}"


def test_spread_gate_rejects_extreme_illiquid_spreads():
    """Test that spread gate rejects extremely illiquid spreads (79c) when using profile value."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # DOGE observed at 79c spread (1.3% on 59c price) - this is now rejected as too illiquid
    # Use profile's 20c threshold (2026-07-12: aligned with industry research)
    result, reason = check_market_microstructure(
        yes_bid_cents=20,
        yes_ask_cents=99,  # 79c spread
        no_bid_cents=1,
        no_ask_cents=80,
        yes_depth=20,
        no_depth=1030,
        max_spread_cents=20.0,  # Use profile value
        min_depth_usd=0.0  # Disable depth check
    )
    
    # Should fail with 79c spread (exceeds 20c threshold)
    assert not result, f"Should reject 79c spread (exceeds 20c), but got: {reason}"
    assert "spread" in reason.lower(), f"Reason should mention spread: {reason}"
    
    # Test with 19c spread (should pass)
    result, reason = check_market_microstructure(
        yes_bid_cents=35,
        yes_ask_cents=54,  # 19c spread
        no_bid_cents=36,
        no_ask_cents=55,  # 19c spread
        yes_depth=20,
        no_depth=1030,
        max_spread_cents=20.0,  # Use profile value
        min_depth_usd=0.0  # Disable depth check
    )
    
    assert result, f"Should pass with 19c spread, but got: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
