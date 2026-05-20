"""Test startup config validator catches contradictions."""

import pytest
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
