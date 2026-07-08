"""Test startup config validator catches contradictions."""

import json
import os
import pytest
from pathlib import Path
from config.startup_config_validator import ConfigValidator


def test_validator_passes_with_correct_configs():
    """Validator should pass when configs are consistent."""
    validator = ConfigValidator()
    assert validator.validate_all() is True
    assert len(validator.errors) == 0


def test_validator_catches_edge_threshold_variance():
    """Validator should detect >50% edge threshold variance."""
    validator = ConfigValidator()
    
    # Find ETH_15M agent and modify its edge
    eth_15m_agent = None
    for agent in validator.kalshi_agent_grid["agents"]:
        if agent.get("name") == "ETH_15M":
            eth_15m_agent = agent
            break
    
    assert eth_15m_agent is not None, "ETH_15M agent not found"
    
    original_eth_mid = eth_15m_agent["strategy"]["min_edge_mid"]
    eth_15m_agent["strategy"]["min_edge_mid"] = 0.10  # 10% vs 2% matrix
    
    assert validator.validate_all() is False
    assert any("Edge threshold variance > 50%" in err for err in validator.errors)
    
    # Restore
    eth_15m_agent["strategy"]["min_edge_mid"] = original_eth_mid


def test_validator_catches_risk_limit_exceeded():
    """Validator should detect >2% risk limit."""
    validator = ConfigValidator()
    
    # Temporarily modify to exceed risk limit
    original_risk = validator.kalshi_distance["sizing_constraints"]["max_risk_per_trade_pct"]
    validator.kalshi_distance["sizing_constraints"]["max_risk_per_trade_pct"] = 0.05  # 5%
    
    assert validator.validate_all() is False
    assert any("Risk limit > 2%" in err for err in validator.errors)
    
    # Restore
    validator.kalshi_distance["sizing_constraints"]["max_risk_per_trade_pct"] = original_risk


def test_supervisor_config_live_mode_environment():
    """Test that supervisor config has correct live mode environment variables.
    
    This test ensures the supervisor config does not have conflicting environment
    variables that force demo mode (which was causing $1000 demo bankroll instead
    of live balance).
    """
    supervisor_config_path = Path(__file__).parent.parent / "supervisor" / "merid-service.json"
    
    if not supervisor_config_path.exists():
        pytest.skip(f"Supervisor config not found at {supervisor_config_path}")
    
    with open(supervisor_config_path) as f:
        config = json.load(f)
    
    env_vars = config.get("env", {})
    
    # Verify KALSHI_ENV is set to live (not demo)
    kalshi_env = env_vars.get("KALSHI_ENV")
    assert kalshi_env == "live", f"KALSHI_ENV must be 'live' for production, got '{kalshi_env}'"
    
    # Verify KALSHI_USE_DEMO is false
    kalshi_use_demo = env_vars.get("KALSHI_USE_DEMO")
    assert kalshi_use_demo == "false", f"KALSHI_USE_DEMO must be 'false' for production, got '{kalshi_use_demo}'"
    
    # Verify MERID_VALIDATION_MODE is false (to ensure risk envelope uses live bankroll)
    validation_mode = env_vars.get("MERID_VALIDATION_MODE")
    assert validation_mode == "0", f"MERID_VALIDATION_MODE must be '0' for production, got '{validation_mode}'"
    
    # Verify profile is kalshi_crypto_15m_v2
    profile = env_vars.get("MERID_PROFILE")
    assert profile == "kalshi_crypto_15m_v2", f"MERID_PROFILE must be 'kalshi_crypto_15m_v2', got '{profile}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
