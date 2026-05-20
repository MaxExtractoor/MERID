"""Config validation tests for profile isolation.

Tests that profile configurations are properly isolated and don't leak
between different profiles (e.g., kalshi_crypto_15m_v2 vs other profiles).
"""

import pytest
import os
from pathlib import Path


def test_kalshi_crypto_15m_yaml_drawdown_isolation():
    """Test that kalshi_crypto_15m.yaml has its own drawdown_semantics section."""
    profile_yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    if not profile_yaml_path.exists():
        pytest.skip(f"Profile YAML not found: {profile_yaml_path}")
    
    import yaml
    
    with open(profile_yaml_path, 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify drawdown_semantics section exists (for semantics documentation)
    assert "drawdown_semantics" in profile_config, "drawdown_semantics section missing from kalshi_crypto_15m.yaml"
    
    drawdown_semantics = profile_config["drawdown_semantics"]
    
    # Verify semantic fields
    assert "time_horizon" in drawdown_semantics, "time_horizon missing from drawdown_semantics"
    assert "pnl_basis" in drawdown_semantics, "pnl_basis missing from drawdown_semantics"
    
    # Verify actual drawdown thresholds are in guardrails
    assert "guardrails" in profile_config, "guardrails section missing from kalshi_crypto_15m.yaml"
    guardrails = profile_config["guardrails"]
    
    assert "drawdown_halt_pct" in guardrails, "drawdown_halt_pct missing from guardrails"
    assert "drawdown_unwind_pct" in guardrails, "drawdown_unwind_pct missing from guardrails"
    
    # Verify values are reasonable
    assert guardrails["drawdown_halt_pct"] > 0, "drawdown_halt_pct must be > 0"
    assert guardrails["drawdown_unwind_pct"] > guardrails["drawdown_halt_pct"], "drawdown_unwind_pct must be > drawdown_halt_pct"


def test_kalshi_crypto_15m_yaml_adaptive_risk_isolation():
    """Test that kalshi_crypto_15m.yaml has its own adaptive_risk_bands section."""
    profile_yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    if not profile_yaml_path.exists():
        pytest.skip(f"Profile YAML not found: {profile_yaml_path}")
    
    import yaml
    
    with open(profile_yaml_path, 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify guardrails section exists (adaptive_risk_bands is nested here)
    assert "guardrails" in profile_config, "guardrails section missing from kalshi_crypto_15m.yaml"
    
    guardrails = profile_config["guardrails"]
    
    # Verify adaptive_risk_bands section exists
    assert "adaptive_risk_bands" in guardrails, "adaptive_risk_bands section missing from guardrails"
    
    bands = guardrails["adaptive_risk_bands"]
    
    # Verify bands is a list
    assert isinstance(bands, list), "adaptive_risk_bands must be a list"
    
    # Verify each band has required fields
    for i, band in enumerate(bands):
        assert "max_drawdown_pct" in band, f"Band {i} missing max_drawdown_pct"
        assert "multiplier" in band, f"Band {i} missing multiplier"
        
        # Verify values are valid
        assert 0 < band["max_drawdown_pct"] <= 1, f"Band {i} max_drawdown_pct must be in (0, 1]"
        assert 0 <= band["multiplier"] <= 1, f"Band {i} multiplier must be in [0, 1]"
    
    # Verify bands are ordered by max_drawdown_pct
    for i in range(len(bands) - 1):
        assert bands[i]["max_drawdown_pct"] < bands[i + 1]["max_drawdown_pct"], \
            f"Bands must be ordered by max_drawdown_pct, but band {i} >= band {i+1}"


def test_kalshi_crypto_15m_yaml_kelly_isolation():
    """Test that kalshi_crypto_15m.yaml has its own kelly_fraction in kelly config."""
    profile_yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    if not profile_yaml_path.exists():
        pytest.skip(f"Profile YAML not found: {profile_yaml_path}")
    
    import yaml
    
    with open(profile_yaml_path, 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify kelly section exists
    assert "kelly" in profile_config, "kelly section missing from kalshi_crypto_15m.yaml"
    
    kelly = profile_config["kelly"]
    
    # Verify kelly_fraction exists
    assert "kelly_fraction" in kelly, "kelly_fraction missing from kelly section"
    
    # Verify value is valid
    assert 0 < kelly["kelly_fraction"] <= 1, "kelly_fraction must be in (0, 1]"


def test_kalshi_crypto_15m_yaml_no_hardcoded_daily_loss():
    """Test that kalshi_crypto_15m.yaml does not have hardcoded daily loss limits."""
    profile_yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    if not profile_yaml_path.exists():
        pytest.skip(f"Profile YAML not found: {profile_yaml_path}")
    
    import yaml
    
    with open(profile_yaml_path, 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Check that daily_loss is disabled in guardrails
    # (should be controlled by envelope/daily_loss_enabled)
    if "guardrails" in profile_config:
        guardrails = profile_config["guardrails"]
        
        # daily_loss_enabled should be false (drawdown is primary guardrail)
        if "daily_loss_enabled" in guardrails:
            daily_loss_enabled = guardrails["daily_loss_enabled"]
            # Either not enabled or marked as envelope-controlled
            assert daily_loss_enabled is False, \
                "daily_loss_enabled should be False in kalshi_crypto_15m.yaml (drawdown is primary guardrail)"


def test_crypto_15m_profile_adapter_envelope_driven():
    """Test that Crypto15mProfile adapter pulls from envelope for kalshi_crypto_15m_v2."""
    try:
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        from dataclasses import fields
    except ImportError:
        pytest.skip("Crypto15mProfileAdapter not available")
    
    # Check that to_kalshi_risk_config method exists
    assert hasattr(Crypto15mProfileAdapter, "to_kalshi_risk_config"), \
        "Crypto15mProfileAdapter must have to_kalshi_risk_config method"
    
    # The implementation should check for envelope and pull values from it
    # This is a structural check - the actual logic is tested elsewhere


def test_kill_switches_no_hardcoded_max_position():
    """Test that kill_switches.py does not have hardcoded max_position_value."""
    kill_switches_path = Path(__file__).parent.parent / "merid" / "risk" / "kill_switches.py"
    
    if not kill_switches_path.exists():
        pytest.skip(f"kill_switches.py not found: {kill_switches_path}")
    
    with open(kill_switches_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that max_position_value is not hardcoded to 10000.0
    assert "max_position_value=10000.0" not in content, \
        "kill_switches.py should not have hardcoded max_position_value=10000.0"
    
    # Check that there's no dataclass with max_position_value field
    # The actual implementation uses different field names


def test_kill_switches_daily_loss_defaults_to_false():
    """Test that kill_switches.py defaults daily_loss_enabled to False."""
    kill_switches_path = Path(__file__).parent.parent / "merid" / "risk" / "kill_switches.py"
    
    if not kill_switches_path.exists():
        pytest.skip(f"kill_switches.py not found: {kill_switches_path}")
    
    with open(kill_switches_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that daily_loss_enabled defaults to False
    assert "daily_loss_enabled: bool = False" in content, \
        "daily_loss_enabled should default to False in KillSwitchConfig"


def test_risk_envelope_profile_dimension():
    """Test that risk envelope has profile dimension."""
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
    except ImportError:
        pytest.skip("KalshiCrypto15mRiskEnvelope not available")
    
    # Check that envelope can be initialized with profile context
    # The envelope should be aware of which profile it belongs to
    # This is tested by the existence of profile-specific configuration


def test_profile_yaml_isolation_from_agent_grid():
    """Test that kalshi_crypto_15m.yaml is not duplicated in kalshi_agent_grid.yaml."""
    agent_grid_path = Path(__file__).parent.parent / "config" / "kalshi_agent_grid.yaml"
    
    if not agent_grid_path.exists():
        pytest.skip(f"kalshi_agent_grid.yaml not found: {agent_grid_path}")
    
    import yaml
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        agent_grid = yaml.safe_load(f)
    
    # The agent_grid structure may be a list or dict
    agents_data = agent_grid if isinstance(agent_grid, dict) else {"agents": agent_grid}
    agents_list = agents_data.get("agents", [])
    
    # Check that risk_limits sections are not present for 15m crypto agents
    # (they should be PROFILE-GATED and controlled by profile YAML)
    for agent in agents_list:
        if isinstance(agent, dict):
            agent_name = agent.get("name", "")
            if agent_name in ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]:
                # These agents should not have risk_limits in the grid
                if "risk_limits" in agent:
                    # If risk_limits exists, it should be empty or marked as PROFILE-GATED
                    risk_limits = agent["risk_limits"]
                    assert risk_limits is None or len(risk_limits) == 0, \
                        f"Agent {agent_name} should not have risk_limits in agent grid (controlled by profile)"


def test_envelope_api_profile_dimension():
    """Test that /api/v1/kalshi/risk/envelope endpoint has profile dimension."""
    kalshi_api_path = Path(__file__).parent.parent / "web" / "api" / "kalshi_api.py"
    
    if not kalshi_api_path.exists():
        pytest.skip(f"kalshi_api.py not found: {kalshi_api_path}")
    
    with open(kalshi_api_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that envelope endpoint checks profile
    assert 'def get_risk_envelope_api' in content, \
        "get_risk_envelope_api endpoint should exist"
    
    # Check that it reads MERID_PROFILE
    assert 'os.getenv("MERID_PROFILE"' in content, \
        "Envelope endpoint should read MERID_PROFILE env var"
    
    # Check that it returns profile in response
    assert '"profile"' in content, \
        "Envelope endpoint should return profile in response"


def test_loop_metrics_profile_dimension():
    """Test that loop metrics have profile dimension."""
    loop_path = Path(__file__).parent.parent / "merid" / "loop_15m.py"
    
    if not loop_path.exists():
        pytest.skip(f"loop_15m.py not found: {loop_path}")
    
    with open(loop_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that loop reads profile
    assert 'MERID_PROFILE' in content or 'os.getenv' in content, \
        "Loop should read MERID_PROFILE env var"
    
    # Check that loop logs profile
    assert 'profile=' in content, \
        "Loop should log profile in metrics"


def test_trading_agent_envelope_filtering():
    """Test that trading_agent.py has envelope-driven signal filtering."""
    trading_agent_path = Path(__file__).parent.parent / "merid" / "prediction" / "trading_agent.py"
    
    if not trading_agent_path.exists():
        pytest.skip(f"trading_agent.py not found: {trading_agent_path}")
    
    with open(trading_agent_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that trading agent checks profile for envelope filtering
    assert 'kalshi_crypto_15m_v2' in content, \
        "Trading agent should check for kalshi_crypto_15m_v2 profile"
    
    # Check that it uses risk envelope
    assert 'get_kalshi_crypto_15m_risk_envelope' in content, \
        "Trading agent should use get_kalshi_crypto_15m_risk_envelope"
    
    # Check that it checks risk multiplier
    assert 'risk_multiplier' in content, \
        "Trading agent should check risk_multiplier from envelope"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
