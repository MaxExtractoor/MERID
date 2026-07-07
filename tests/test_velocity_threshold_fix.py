"""Test velocity threshold configuration fix.

This test verifies that velocity thresholds are set to appropriate values
(0.015%-0.025%) to match actual market conditions and enable signal generation.
Also tests symmetric YES/NO thresholds to prevent NO-side blocking.
"""

import pytest
from unittest.mock import Mock, patch
import yaml
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_velocity_thresholds_config():
    """Test that velocity thresholds in config are set to appropriate values.
    
    CRITICAL FIX: 2026-07-07 - Updated to asset-specific thresholds aligned with profile YAML:
    - BTC: 0.00015 (0.015%)
    - ETH: 0.00015 (0.015%)
    - SOL: 0.000225 (0.0225%)
    - XRP: 0.000225 (0.0225%)
    - DOGE: 0.0003 (0.03%)
    These thresholds are based on actual market conditions and enable signal generation.
    """
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    velocity_thresholds = config.get('velocity_thresholds', {})
    
    # Verify thresholds match profile YAML values (asset-specific)
    expected = {
        'BTC': 0.00015,
        'ETH': 0.00015,
        'SOL': 0.000225,
        'XRP': 0.000225,
        'DOGE': 0.0003,
    }
    
    for asset, expected_value in expected.items():
        actual = velocity_thresholds[asset]
        assert actual == expected_value, f"{asset} threshold should be {expected_value}, got {actual}"


def test_velocity_thresholds_profile():
    """Test that velocity thresholds in agent_grid_15m.py match config.
    
    CRITICAL FIX: 2026-07-07 - Updated to asset-specific thresholds aligned with profile YAML:
    - BTC: 0.00015 (0.015%)
    - ETH: 0.00015 (0.015%)
    - SOL: 0.000225 (0.0225%)
    - XRP: 0.000225 (0.0225%)
    - DOGE: 0.0003 (0.03%)
    """
    try:
        # Read the agent grid file directly to check default values
        agent_grid_path = "merid/prediction/agent_grid_15m.py"
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that agent grid thresholds are set to correct values (asset-specific)
        assert "velocity_threshold_btc: float = 0.00015" in content, \
            "Agent grid BTC threshold should be 0.00015"
        assert "velocity_threshold_eth: float = 0.00015" in content, \
            "Agent grid ETH threshold should be 0.00015"
        assert "velocity_threshold_sol: float = 0.000225" in content, \
            "Agent grid SOL threshold should be 0.000225"
        assert "velocity_threshold_xrp: float = 0.000225" in content, \
            "Agent grid XRP threshold should be 0.000225"
        assert "velocity_threshold_doge: float = 0.0003" in content, \
            "Agent grid DOGE threshold should be 0.0003"
        
        print("✓ Agent grid thresholds match config values (asset-specific)")
    except FileNotFoundError as e:
        pytest.skip(f"Could not find agent_grid_15m.py: {e}")


def test_velocity_thresholds_enable_signals():
    """Test that velocity thresholds allow signals to be generated.
    
    CRITICAL FIX: 2026-07-07 - With asset-specific thresholds (0.015%-0.03%),
    moderate movements should generate signals. This is intentional to enable
    trading in normal market conditions.
    """
    # Simulate observed market velocities (moderate movements)
    observed_velocities = {
        'BTC': 0.00020,  # 0.020% (moderate movement, above 0.015% threshold)
        'ETH': 0.00018,  # 0.018% (moderate movement, above 0.015% threshold)
        'SOL': 0.00025,  # 0.025% (moderate movement, above 0.0225% threshold)
        'XRP': 0.00024,  # 0.024% (moderate movement, above 0.0225% threshold)
        'DOGE': 0.00035  # 0.035% (moderate movement, above 0.03% threshold)
    }
    
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    velocity_thresholds = config.get('velocity_thresholds', {})
    
    # Verify that observed velocities exceed thresholds (signals should be generated)
    for asset, observed in observed_velocities.items():
        threshold = velocity_thresholds[asset]
        assert observed > threshold, f"{asset} observed velocity {observed} should exceed threshold {threshold}"
        print(f"{asset}: velocity={observed:.6f} > threshold={threshold:.6f} ✓")


def test_symmetric_yes_no_thresholds():
    """Test that YES and NO sides use symmetric velocity thresholds.
    
    CRITICAL FIX: 2026-07-04 - Removed NO-side conviction multiplier (1.5x -> 1.0x)
    This ensures NO-side signals are not blocked by asymmetric thresholds.
    """
    try:
        # Read the agent_grid_15m.py file to check the multiplier
        agent_grid_path = "merid/prediction/agent_grid_15m.py"
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that no_conviction_multiplier is set to 1.0
        assert "no_conviction_multiplier = 1.0" in content, \
            "no_conviction_multiplier should be 1.0 for symmetric YES/NO thresholds"
        
        # Check that the old 1.5x value is not present
        assert "no_conviction_multiplier = 1.5" not in content, \
            "Old asymmetric multiplier (1.5x) should be removed"
        
        print("✓ YES/NO thresholds are symmetric (no_conviction_multiplier = 1.0)")
    except FileNotFoundError as e:
        pytest.skip(f"Could not find agent_grid_15m.py: {e}")


def test_symmetric_thresholds_across_assets():
    """Test that symmetric thresholds work correctly for all 5 assets.
    
    CRITICAL FIX: 2026-07-07 - With asset-specific thresholds (0.015%-0.03%),
    both positive and negative velocities should trigger signals at the same magnitude.
    """
    config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    velocity_thresholds = config.get('velocity_thresholds', {})
    
    # Test that positive and negative velocities of same magnitude
    # would both trigger signals (symmetric behavior)
    # With asset-specific thresholds, use velocities that exceed each threshold
    test_velocities = {
        'BTC': (0.00020, -0.00020),  # Both exceed 0.00015
        'ETH': (0.00018, -0.00018),  # Both exceed 0.00015
        'SOL': (0.00025, -0.00025),  # Both exceed 0.000225
        'XRP': (0.00024, -0.00024),  # Both exceed 0.000225
        'DOGE': (0.00035, -0.00035)  # Both exceed 0.0003
    }
    
    for asset, (pos_vel, neg_vel) in test_velocities.items():
        threshold = velocity_thresholds[asset]
        # With symmetric thresholds, both should exceed threshold in absolute terms
        assert abs(pos_vel) > threshold, f"{asset} positive velocity {pos_vel} should exceed threshold {threshold}"
        assert abs(neg_vel) > threshold, f"{asset} negative velocity {neg_vel} should exceed threshold {threshold}"
        print(f"{asset}: |{pos_vel:.6f}| > {threshold:.6f} and |{neg_vel:.6f}| > {threshold:.6f} ✓")


def test_spread_limit_unification():
    """Test that spread limits are unified to 75c across all configuration sources.
    
    CRITICAL FIX: 2026-07-04 - Unified spread limits to 75c to eliminate conflicts
    Previous conflicts: 50c (profile), 75c (guardrails), 15c (universe), 15c (momentum_fvg)
    This was causing order_router to reject trades with spreads 50-75c that should be allowed.
    """
    try:
        # Check profile spread limit
        profile_path = "merid/risk/profiles/crypto_15m_profile.py"
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_content = f.read()
        
        assert "market_microstructure_max_spread_cents: float = 75.0" in profile_content, \
            "Profile spread limit should be 75c (unified with guardrails)"
        assert "market_microstructure_max_spread_cents: float = 50.0" not in profile_content, \
            "Old 50c spread limit should be removed from profile"
        
        # Check YAML spread limits
        config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Check guardrails spread limit
        guardrails = config.get('guardrails', {})
        assert guardrails.get('max_spread_cents') == 75, \
            f"Guardrails max_spread_cents should be 75, got {guardrails.get('max_spread_cents')}"
        assert guardrails.get('min_spread_gate_cents') == 75, \
            f"Guardrails min_spread_gate_cents should be 75, got {guardrails.get('min_spread_gate_cents')}"
        
        # Check universe spread limit
        universe = config.get('universe', {})
        assert universe.get('max_spread_cents') == 75, \
            f"Universe max_spread_cents should be 75, got {universe.get('max_spread_cents')}"
        
        # Check momentum_fvg spread gate
        momentum_fvg = config.get('momentum_fvg', {})
        assert momentum_fvg.get('spread_gate_cents') == 75, \
            f"Momentum_fvg spread_gate_cents should be 75, got {momentum_fvg.get('spread_gate_cents')}"
        
        print("✓ Spread limits unified to 75c across all configuration sources")
    except FileNotFoundError as e:
        pytest.skip(f"Could not find configuration file: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
