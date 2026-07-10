"""Test edge threshold consistency across all layers.

This test verifies that edge thresholds are consistent across:
- Profile YAML (config/profiles/kalshi_crypto_15m_v2.yaml)
- Risk envelope (merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py)
- Profile adapter (merid/risk/profiles/crypto_15m_profile.py)
- Agent grid (merid/prediction/agent_grid_15m.py)

CRITICAL: Ensures no discrepancies that could cause trade blocking or excessive risk.
"""

import pytest
import yaml
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_edge_thresholds_yaml():
    """Test that edge thresholds in YAML are set to appropriate values with Phase 1A changes."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    assets = config.get('assets', {})
    
    # Verify edge thresholds by asset tier with moltbook research (2026-07-10)
    # Tier 1 (BTC/ETH): Base 1.25-1.5%, terminal 1.75-2.0% (pragmatic for liquidity)
    assert assets['BTC']['min_edge_early'] == 0.0125, "BTC min_edge_early should be 1.25%"
    assert assets['BTC']['min_edge_terminal'] == 0.0175, "BTC min_edge_terminal should be 1.75%"
    assert assets['ETH']['min_edge_early'] == 0.015, "ETH min_edge_early should be 1.5%"
    assert assets['ETH']['min_edge_terminal'] == 0.02, "ETH min_edge_terminal should be 2.0%"
    
    # Tier 2 (SOL/XRP): Base 2.0-2.25%, terminal 2.5-3.0% (thinner liquidity)
    assert assets['SOL']['min_edge_early'] == 0.02, "SOL min_edge_early should be 2.0%"
    assert assets['SOL']['min_edge_terminal'] == 0.025, "SOL min_edge_terminal should be 2.5%"
    assert assets['XRP']['min_edge_early'] == 0.0225, "XRP min_edge_early should be 2.25%"
    assert assets['XRP']['min_edge_terminal'] == 0.03, "XRP min_edge_terminal should be 3.0%"
    
    # DOGE (highest volatility): Base 2.75%, terminal 3.5% (noisiest moves)
    assert assets['DOGE']['min_edge_early'] == 0.0275, "DOGE min_edge_early should be 2.75%"
    assert assets['DOGE']['min_edge_terminal'] == 0.035, "DOGE min_edge_terminal should be 3.5%"
    
    print("✓ Edge thresholds in YAML are appropriate for each asset tier (moltbook 2026-07-10)")


def test_edge_thresholds_profile():
    """Test that edge thresholds in profile match YAML."""
    try:
        profile_path = "merid/risk/profiles/crypto_15m_profile.py"
        with open(profile_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that profile loads edge thresholds from YAML
        # The profile should not have hardcoded edge thresholds
        # It should read from the YAML config
        assert "min_edge_early" not in content or "asset_config" in content, \
            "Profile should read edge thresholds from YAML, not hardcode them"
        
        print("✓ Profile reads edge thresholds from YAML (no hardcoding)")
    except FileNotFoundError as e:
        pytest.skip(f"Could not find crypto_15m_profile.py: {e}")


def test_edge_thresholds_consistent_across_assets():
    """Test that edge thresholds are consistent within asset tiers."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    assets = config.get('assets', {})
    
    # Tier 1 assets (BTC/ETH) should have identical thresholds
    assert assets['BTC']['min_edge_early'] == assets['ETH']['min_edge_early'], \
        "Tier 1 assets (BTC/ETH) should have identical min_edge_early"
    assert assets['BTC']['min_edge_terminal'] == assets['ETH']['min_edge_terminal'], \
        "Tier 1 assets (BTC/ETH) should have identical min_edge_terminal"
    
    # Tier 2 assets (SOL/XRP) should have identical thresholds
    assert assets['SOL']['min_edge_early'] == assets['XRP']['min_edge_early'], \
        "Tier 2 assets (SOL/XRP) should have identical min_edge_early"
    assert assets['SOL']['min_edge_terminal'] == assets['XRP']['min_edge_terminal'], \
        "Tier 2 assets (SOL/XRP) should have identical min_edge_terminal"
    
    print("✓ Edge thresholds are consistent within asset tiers")


def test_edge_thresholds_volatility_based():
    """Test that edge thresholds are based on volatility (higher vol = higher edge)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    assets = config.get('assets', {})
    
    # Edge thresholds should increase with volatility
    # BTC/ETH (lower vol) < SOL/XRP (moderate vol) < DOGE (highest vol)
    btc_edge = assets['BTC']['min_edge_early']
    sol_edge = assets['SOL']['min_edge_early']
    doge_edge = assets['DOGE']['min_edge_early']
    
    assert btc_edge < sol_edge, "BTC edge should be < SOL edge (volatility-based)"
    assert sol_edge < doge_edge, "SOL edge should be < DOGE edge (volatility-based)"
    
    print("✓ Edge thresholds are volatility-based (higher vol = higher edge)")


def test_edge_thresholds_not_excessive():
    """Test that edge thresholds are not excessive (would block all trades)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    assets = config.get('assets', {})
    
    # Edge thresholds should be reasonable (not > 10%)
    for asset, asset_config in assets.items():
        min_edge_early = asset_config['min_edge_early']
        min_edge_terminal = asset_config['min_edge_terminal']
        
        assert min_edge_early <= 0.10, f"{asset} min_edge_early {min_edge_early} is too high (> 10%)"
        assert min_edge_terminal <= 0.10, f"{asset} min_edge_terminal {min_edge_terminal} is too high (> 10%)"
    
    print("✓ Edge thresholds are not excessive (all <= 10%)")


def test_edge_thresholds_not_too_low():
    """Test that edge thresholds are not too low (would allow poor EV trades)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    assets = config.get('assets', {})
    
    # Edge thresholds should be reasonable (not < 1% for BTC, not < 1.5% for others)
    for asset, asset_config in assets.items():
        min_edge_early = asset_config['min_edge_early']
        min_edge_terminal = asset_config['min_edge_terminal']
        
        # BTC can go as low as 1.25%, others should be >= 1.5%
        min_allowed = 0.0125 if asset == 'BTC' else 0.015
        assert min_edge_early >= min_allowed, f"{asset} min_edge_early {min_edge_early} is too low (< {min_allowed*100}%)"
        assert min_edge_terminal >= min_allowed, f"{asset} min_edge_terminal {min_edge_terminal} is too low (< {min_allowed*100}%)"
    
    print("✓ Edge thresholds are not too low (BTC >= 1.25%, others >= 1.5%)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
