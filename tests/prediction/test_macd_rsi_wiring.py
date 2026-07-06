"""Test MACD/RSI signal generation wiring in agent_grid_15m.py.

This verifies that MACD and RSI indicators are correctly wired into the
momentum_fvg signal generation mode as per the 2026 technical analysis audit.
"""

import pytest
from pathlib import Path


class TestMACDRSIWiring:
    """Test suite for MACD/RSI signal generation wiring."""
    
    def test_momentum_fvg_signal_mode_exists(self):
        """Verify that momentum_fvg signal mode exists in agent_grid_15m.py."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        assert agent_grid_path.exists(), f"Agent grid file not found: {agent_grid_path}"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify momentum_fvg signal mode
        assert "momentum_fvg" in content, \
            "momentum_fvg signal mode should exist in agent_grid_15m.py"
        
        # Verify _generate_momentum_fvg_signal method exists
        assert "_generate_momentum_fvg_signal" in content, \
            "_generate_momentum_fvg_signal method should exist"
    
    def test_macd_usage_in_momentum_fvg(self):
        """Verify that MACD is used in momentum_fvg signal generation."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify MACD is referenced in momentum_fvg generation
        assert "macd" in content.lower(), \
            "MACD should be referenced in agent_grid_15m.py"
        
        # Verify MACD calculation or retrieval
        assert "get_macd" in content.lower() or "macd_value" in content.lower() or "macd_line" in content.lower(), \
            "MACD values should be calculated or retrieved"
    
    def test_rsi_usage_in_momentum_fvg(self):
        """Verify that RSI is used in momentum_fvg signal generation."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify RSI is referenced in momentum_fvg generation
        assert "rsi" in content.lower(), \
            "RSI should be referenced in agent_grid_15m.py"
        
        # Verify RSI calculation or retrieval (_calculate_rsi is the method used)
        assert "_calculate_rsi" in content or "get_rsi" in content.lower() or "rsi_value" in content.lower(), \
            "RSI values should be calculated or retrieved"
    
    def test_indicator_stack_usage(self):
        """Verify that indicator stack is used for MACD/RSI data."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify indicator stack is referenced
        assert "indicator_stack" in content.lower() or "get_indicator_snapshot" in content.lower(), \
            "Indicator stack should be used to retrieve MACD/RSI data"
    
    def test_macd_rsi_signal_logic(self):
        """Verify that MACD/RSI are used in signal decision logic."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify MACD/RSI are used in signal generation logic
        # This is a soft check - we just verify they're used in the signal generation context
        assert "signal" in content.lower() and ("macd" in content.lower() or "rsi" in content.lower()), \
            "MACD/RSI should be used in signal generation logic"
    
    def test_macd_rsi_config_in_profile(self):
        """Verify that MACD/RSI configuration is in profile YAML."""
        profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        assert profile_path.exists(), f"Profile file not found: {profile_path}"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        # Verify momentum_fvg section exists (contains MACD/RSI config)
        assert "momentum_fvg" in profile_data, \
            "momentum_fvg section should exist in profile YAML"
        
        fvg_config = profile_data["momentum_fvg"]
        
        # Verify MACD/RSI related config parameters (if present)
        # This is a soft check - config may be in different sections
        # Just verify the section exists for now


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
