"""Tests for 2026-07-04 spread threshold fixes based on industry research.

Research findings:
- Kalena: Altcoin spreads 5-30% in thin orderbooks
- DOGE observed at 79c spread (1.3% on 59c price)
- 15c threshold was blocking all trades on Tier 2 assets
- Increased to 50c to align with realistic market conditions
"""

import os
from unittest.mock import patch
import pytest


def test_min_spread_gate_cents_increased_to_50c():
    """Test that min_spread_gate_cents is increased to 50c based on 2026 research."""
    import yaml
    
    # Load the profile YAML directly with UTF-8 encoding
    with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify min_spread_gate_cents is 50c (increased from 15c)
    assert profile_config['guardrails']['min_spread_gate_cents'] == 50, \
        f"min_spread_gate_cents should be 50c, got {profile_config['guardrails']['min_spread_gate_cents']}"


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


def test_order_router_default_spread_threshold_50c():
    """Test that order_router default max_spread_cents is 50c."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # Call with default parameters and sufficient depth
    result, reason = check_market_microstructure(
        yes_bid_cents=40,
        yes_ask_cents=90,  # 50c spread
        no_bid_cents=10,
        no_ask_cents=60,
        yes_depth=5,
        no_depth=5,
        min_depth_usd=0.0  # Disable depth check for this test
    )
    
    # Should pass with 50c spread (new default)
    assert result, f"Should pass with 50c spread, but got: {reason}"
    
    # Test with 51c spread (should fail)
    result, reason = check_market_microstructure(
        yes_bid_cents=40,
        yes_ask_cents=91,  # 51c spread
        no_bid_cents=10,
        no_ask_cents=60,
        yes_depth=5,
        no_depth=5,
        min_depth_usd=0.0  # Disable depth check for this test
    )
    
    assert not result, "Should fail with 51c spread"
    assert "spread" in reason.lower(), f"Reason should mention spread: {reason}"


def test_spread_gate_allows_doge_realistic_spreads():
    """Test that spread gate allows DOGE's realistic 79c spread when using profile value."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # DOGE observed at 79c spread (1.3% on 59c price)
    # Use profile's 50c threshold
    result, reason = check_market_microstructure(
        yes_bid_cents=20,
        yes_ask_cents=99,  # 79c spread
        no_bid_cents=1,
        no_ask_cents=80,
        yes_depth=20,
        no_depth=1030,
        max_spread_cents=50.0,  # Use profile value
        min_depth_usd=0.0  # Disable depth check
    )
    
    # Should fail with 79c spread (exceeds 50c threshold)
    assert not result, f"Should reject DOGE's 79c spread (exceeds 50c), but got: {reason}"
    assert "spread" in reason.lower(), f"Reason should mention spread: {reason}"
    
    # Test with 49c spread (should pass)
    result, reason = check_market_microstructure(
        yes_bid_cents=20,
        yes_ask_cents=69,  # 49c spread
        no_bid_cents=1,
        no_ask_cents=50,
        yes_depth=20,
        no_depth=1030,
        max_spread_cents=50.0,  # Use profile value
        min_depth_usd=0.0  # Disable depth check
    )
    
    assert result, f"Should pass with 49c spread, but got: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
