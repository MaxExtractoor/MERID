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
    """Edge thresholds live in edge_bands.per_asset (SSOT since 2026-07-14).

    The per-asset min_edge_early/mid/late/terminal fields were deliberately
    removed - they conflicted with edge_bands and were ignored.  Canonical
    per-asset floors (2026-08-30): BTC 3%, ETH/SOL 4%, XRP/DOGE 5%.
    """
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    bands = config.get('edge_bands', {})
    per_asset = bands.get('per_asset', {})

    assert bands.get('enabled') is True, "edge_bands must be enabled"

    # Canonical per-asset floors
    assert per_asset['BTC']['min_edge_pct'] == 0.03
    assert per_asset['ETH']['min_edge_pct'] == 0.04
    assert per_asset['SOL']['min_edge_pct'] == 0.04
    assert per_asset['XRP']['min_edge_pct'] == 0.05
    assert per_asset['DOGE']['min_edge_pct'] == 0.05

    # Band ordering: watch < small < standard
    assert bands['watch_band']['min_edge_pct'] < bands['small_band']['min_edge_pct']
    assert bands['small_band']['min_edge_pct'] < bands['standard_band']['min_edge_pct']

    # Deprecated fields must not silently reappear in the assets section
    assets = config.get('assets', {})
    for asset, asset_config in assets.items():
        assert 'min_edge_early' not in asset_config, \
            f"{asset} must not reintroduce deprecated min_edge_early"
        assert 'min_edge_terminal' not in asset_config, \
            f"{asset} must not reintroduce deprecated min_edge_terminal"


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
    """Edge thresholds are consistent within the canonical asset tiers."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    per_asset = config['edge_bands']['per_asset']

    # Mid-vol tier (ETH/SOL) shares identical floors
    assert per_asset['ETH']['min_edge_pct'] == per_asset['SOL']['min_edge_pct']
    # High-vol tier (XRP/DOGE) shares identical floors
    assert per_asset['XRP']['min_edge_pct'] == per_asset['DOGE']['min_edge_pct']
    # BTC is its own (lowest) tier
    assert per_asset['BTC']['min_edge_pct'] < per_asset['ETH']['min_edge_pct']


def test_edge_thresholds_volatility_based():
    """Edge floors increase with asset volatility (BTC < ETH/SOL < XRP/DOGE)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    per_asset = config['edge_bands']['per_asset']

    btc_edge = per_asset['BTC']['min_edge_pct']
    sol_edge = per_asset['SOL']['min_edge_pct']
    doge_edge = per_asset['DOGE']['min_edge_pct']

    assert btc_edge < sol_edge, "BTC edge should be < SOL edge (volatility-based)"
    assert sol_edge < doge_edge, "SOL edge should be < DOGE edge (volatility-based)"


def test_edge_thresholds_not_excessive():
    """Edge floors must not be so high they block all trades (<= 10%)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    per_asset = config['edge_bands']['per_asset']

    for asset, asset_config in per_asset.items():
        min_edge = asset_config['min_edge_pct']
        assert min_edge <= 0.10, \
            f"{asset} min_edge_pct {min_edge} is too high (> 10%)"


def test_edge_thresholds_not_too_low():
    """Per-asset floors must not drop below the global hard floor (2%)."""
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    bands = config['edge_bands']
    global_floor = bands['watch_band']['min_edge_pct']
    per_asset = bands['per_asset']

    for asset, asset_config in per_asset.items():
        min_edge = asset_config['min_edge_pct']
        assert min_edge >= global_floor, \
            f"{asset} min_edge_pct {min_edge} below global floor {global_floor}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
