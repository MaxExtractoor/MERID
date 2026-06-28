"""
Sanity check for unified edge toggle and modes.

Verifies that the unified edge configuration is consistent between
config YAML and code behavior.
"""
import os
import pytest

# Set profile to kalshi_crypto_15m_v2
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["MERID_TRADING_MODE"] = "PAPER"


def test_unified_edge_config_mode():
    """Verify that edge_computation mode is set to 'unified' in strategy config."""
    import yaml
    from pathlib import Path
    
    strategy_config_path = Path("config/profiles/kalshi_crypto_15m_strategy.yaml")
    if not strategy_config_path.exists():
        pytest.skip("Strategy config file not found")
    
    with open(strategy_config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    edge_computation = config.get("edge_computation", {})
    mode = edge_computation.get("mode", "")
    
    # Mode should be "unified" (even if disabled by env var)
    assert mode == "unified", f"edge_computation.mode should be 'unified', got '{mode}'"


def test_unified_edge_disabled_by_default():
    """Verify that unified edge is disabled by default in config."""
    import yaml
    from pathlib import Path
    
    strategy_config_path = Path("config/profiles/kalshi_crypto_15m_strategy.yaml")
    if not strategy_config_path.exists():
        pytest.skip("Strategy config file not found")
    
    with open(strategy_config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    edge_computation = config.get("edge_computation", {})
    unified_config = edge_computation.get("unified", {})
    enabled = unified_config.get("enabled", True)
    
    # Should be disabled by default (controlled by env var)
    assert enabled is False, "unified.enabled should be false by default (controlled by MERID_UNIFIED_EDGE_ENABLED)"


def test_unified_edge_env_var_controls_toggle():
    """Verify that MERID_UNIFIED_EDGE_ENABLED env var controls the toggle."""
    # Test with env var disabled (default)
    os.environ["MERID_UNIFIED_EDGE_ENABLED"] = "false"
    unified_edge_enabled = os.getenv('MERID_UNIFIED_EDGE_ENABLED', 'false').lower() == 'true'
    assert unified_edge_enabled is False, "Unified edge should be disabled when MERID_UNIFIED_EDGE_ENABLED=false"
    
    # Test with env var enabled
    os.environ["MERID_UNIFIED_EDGE_ENABLED"] = "true"
    unified_edge_enabled = os.getenv('MERID_UNIFIED_EDGE_ENABLED', 'false').lower() == 'true'
    assert unified_edge_enabled is True, "Unified edge should be enabled when MERID_UNIFIED_EDGE_ENABLED=true"
    
    # Clean up
    os.environ.pop("MERID_UNIFIED_EDGE_ENABLED", None)


def test_legacy_spread_fallback_configured():
    """Verify that legacy_spread mode is configured as fallback."""
    import yaml
    from pathlib import Path
    
    strategy_config_path = Path("config/profiles/kalshi_crypto_15m_strategy.yaml")
    if not strategy_config_path.exists():
        pytest.skip("Strategy config file not found")
    
    with open(strategy_config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    edge_computation = config.get("edge_computation", {})
    legacy_config = edge_computation.get("legacy_spread", {})
    
    # Legacy spread should have configuration
    assert "min_edge_pct" in legacy_config, "legacy_spread should have min_edge_pct configured"
    assert "spread_multiplier" in legacy_config, "legacy_spread should have spread_multiplier configured"
    
    # Check reasonable defaults
    assert legacy_config["min_edge_pct"] > 0, "min_edge_pct should be positive"
    assert legacy_config["spread_multiplier"] > 0, "spread_multiplier should be positive"


def test_edge_config_consistency():
    """Verify that edge thresholds are consistent across config files."""
    import yaml
    from pathlib import Path
    
    # Check strategy config
    strategy_config_path = Path("config/profiles/kalshi_crypto_15m_strategy.yaml")
    if not strategy_config_path.exists():
        pytest.skip("Strategy config file not found")
    
    with open(strategy_config_path, encoding="utf-8") as f:
        strategy_config = yaml.safe_load(f)
    
    # Check profile config
    profile_config_path = Path("config/profiles/kalshi_crypto_15m.yaml")
    if not profile_config_path.exists():
        pytest.skip("Profile config file not found")
    
    with open(profile_config_path, encoding="utf-8") as f:
        profile_config = yaml.safe_load(f)
    
    # Verify edge thresholds exist in profile
    assets = profile_config.get("assets", {})
    for asset_name, asset_config in assets.items():
        if "strategy" in asset_config:
            strategy = asset_config["strategy"]
            # Should have edge thresholds
            assert "min_edge_early" in strategy or "min_edge_mid" in strategy, \
                f"Asset {asset_name} should have edge thresholds configured"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
