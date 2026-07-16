"""
Test for YAML vs code alignment fixes (2026-07-16)

This test verifies that Python code defaults match the YAML configuration
in kalshi_crypto_15m_v2.yaml to prevent configuration drift.
"""
import pytest
import yaml
from pathlib import Path


class TestYAMLCodeAlignment:
    """Test that Python code defaults match YAML configuration."""
    
    @pytest.fixture
    def profile_yaml(self):
        """Load the profile YAML file."""
        yaml_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def test_max_yes_position_default_is_1(self, profile_yaml):
        """Verify max_yes_position default is 1 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_max_yes = agent_defaults.get('max_yes_position')
        assert yaml_max_yes == 1, f"YAML max_yes_position should be 1, got {yaml_max_yes}"
        
        # Check code default in kalshi_crypto_15m_risk_envelope.py
        # This is verified by the fix: agent_defaults.get('max_yes_position', 1)
        # We'll verify the file content directly
        envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        with open(envelope_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_yes_position', 1)" in content, \
                "kalshi_crypto_15m_risk_envelope.py should default to 1"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_yes_position', 1)" in content, \
                "crypto_15m_profile.py should default to 1"
    
    def test_max_no_position_default_is_1(self, profile_yaml):
        """Verify max_no_position default is 1 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_max_no = agent_defaults.get('max_no_position')
        assert yaml_max_no == 1, f"YAML max_no_position should be 1, got {yaml_max_no}"
        
        # Check code default in kalshi_crypto_15m_risk_envelope.py
        envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        with open(envelope_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_no_position', 1)" in content, \
                "kalshi_crypto_15m_risk_envelope.py should default to 1"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_no_position', 1)" in content, \
                "crypto_15m_profile.py should default to 1"
    
    def test_max_concurrent_trades_default_is_8(self, profile_yaml):
        """Verify max_concurrent_trades default is 8 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_max_concurrent = agent_defaults.get('max_concurrent_trades')
        assert yaml_max_concurrent == 8, f"YAML max_concurrent_trades should be 8, got {yaml_max_concurrent}"
        
        # Check code default in kalshi_crypto_15m_risk_envelope.py
        envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        with open(envelope_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_concurrent_trades', 8)" in content, \
                "kalshi_crypto_15m_risk_envelope.py should default to 8"
    
    def test_drawdown_halt_pct_default_is_0_20(self, profile_yaml):
        """Verify drawdown_halt_pct default is 0.20 in both YAML and code."""
        # Check YAML
        guardrails = profile_yaml.get('guardrails', {})
        drawdown_halt = guardrails.get('drawdown_halt_pct', {})
        if isinstance(drawdown_halt, dict):
            yaml_value = drawdown_halt.get('value')
        else:
            yaml_value = drawdown_halt
        assert yaml_value == 0.20, f"YAML drawdown_halt_pct should be 0.20, got {yaml_value}"
        
        # Check code default in kalshi_crypto_15m_risk_envelope.py
        envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        with open(envelope_path, 'r') as f:
            content = f.read()
            # Check both the outer get and the nested dict fallback
            assert "guardrails.get('drawdown_halt_pct', 0.20)" in content, \
                "kalshi_crypto_15m_risk_envelope.py should default to 0.20"
            assert "drawdown_halt_pct_raw.get('value', 0.20)" in content, \
                "kalshi_crypto_15m_risk_envelope.py nested dict fallback should default to 0.20"
    
    def test_minutes_before_expiry_default_is_15(self, profile_yaml):
        """Verify minutes_before_expiry default is 15 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_minutes = agent_defaults.get('minutes_before_expiry')
        assert yaml_minutes == 15, f"YAML minutes_before_expiry should be 15, got {yaml_minutes}"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('minutes_before_expiry', 15)" in content, \
                "crypto_15m_profile.py should default to 15"
    
    def test_cutoff_minutes_before_expiry_default_is_0(self, profile_yaml):
        """Verify cutoff_minutes_before_expiry default is 0 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_cutoff = agent_defaults.get('cutoff_minutes_before_expiry')
        assert yaml_cutoff == 0, f"YAML cutoff_minutes_before_expiry should be 0, got {yaml_cutoff}"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('cutoff_minutes_before_expiry', 0)" in content, \
                "crypto_15m_profile.py should default to 0"
    
    def test_throttling_global_orders_limit_default_is_30(self, profile_yaml):
        """Verify throttling_global_orders_limit default is 30 in both YAML and code."""
        # Check YAML
        throttling = profile_yaml.get('throttling', {})
        yaml_global_limit = throttling.get('global_orders_limit')
        assert yaml_global_limit == 30, f"YAML global_orders_limit should be 30, got {yaml_global_limit}"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "throttling.get('global_orders_limit', 30)" in content, \
                "crypto_15m_profile.py should default to 30"
    
    def test_kelly_min_edge_pct_default_is_0_015(self, profile_yaml):
        """Verify kelly_min_edge_pct default is 0.015 in both YAML and code."""
        # Check YAML
        kelly = profile_yaml.get('kelly', {})
        yaml_kelly_min_edge = kelly.get('kelly_min_edge_pct')
        assert yaml_kelly_min_edge == 0.015, f"YAML kelly_min_edge_pct should be 0.015, got {yaml_kelly_min_edge}"
        
        # Check code default in crypto_15m_profile.py
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "kelly.get('kelly_min_edge_pct', 0.015)" in content, \
                "crypto_15m_profile.py should default to 0.015"
    
    def test_max_orders_per_window_default_is_24(self, profile_yaml):
        """Verify max_orders_per_window default is 24 in both YAML and code."""
        # Check YAML
        agent_defaults = profile_yaml.get('agent_defaults', {})
        yaml_max_orders = agent_defaults.get('max_orders_per_window')
        assert yaml_max_orders == 24, f"YAML max_orders_per_window should be 24, got {yaml_max_orders}"
        
        # Check code defaults
        envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        with open(envelope_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_orders_per_window', 24)" in content, \
                "kalshi_crypto_15m_risk_envelope.py should default to 24"
        
        profile_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "crypto_15m_profile.py"
        with open(profile_path, 'r') as f:
            content = f.read()
            assert "agent_defaults.get('max_orders_per_window', 24)" in content, \
                "crypto_15m_profile.py should default to 24"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
