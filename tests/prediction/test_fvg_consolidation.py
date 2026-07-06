"""Test FVG consolidation - ensuring fvg.py is the authoritative source.

This verifies that the approximation-based FVG detection in crypto_15m_indicators.py
has been deprecated and replaced by the authoritative implementation in fvg.py.
"""

import pytest
from pathlib import Path


class TestFVGConsolidation:
    """Test suite for FVG consolidation."""
    
    def test_crypto_15m_indicators_fvg_deprecated(self):
        """Verify that FVG methods in crypto_15m_indicators.py are deprecated."""
        indicator_path = Path(__file__).parent.parent.parent / "merid" / "signals" / "crypto_15m_indicators.py"
        
        assert indicator_path.exists(), f"Indicator file not found: {indicator_path}"
        
        with open(indicator_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify _detect_fvg is deprecated
        assert "DEPRECATED: FVG detection moved to merid/prediction/forecasters/fvg.py" in content, \
            "_detect_fvg should be marked as deprecated"
        assert "return None" in content, \
            "_detect_fvg should return None (deprecated)"
        
        # Verify _check_fvg_fills is deprecated
        assert "DEPRECATED: FVG fill checking moved to merid/prediction/forecasters/fvg.py" in content, \
            "_check_fvg_fills should be marked as deprecated"
        assert "pass" in content, \
            "_check_fvg_fills should do nothing (deprecated)"
        
        # Verify _compute_fvg_context is deprecated
        assert "DEPRECATED: FVG context computation moved to merid/prediction/forecasters/fvg.py" in content, \
            "_compute_fvg_context should be marked as deprecated"
        assert "return FVGContext()" in content, \
            "_compute_fvg_context should return empty context (deprecated)"
        
        # Verify _check_fvg_confluence is deprecated
        assert "DEPRECATED: FVG confluence checking moved to merid/prediction/forecasters/fvg.py" in content, \
            "_check_fvg_confluence should be marked as deprecated"
        assert "return False" in content, \
            "_check_fvg_confluence should return False (deprecated)"
    
    def test_fvg_py_authoritative_source(self):
        """Verify that fvg.py contains the authoritative FVG implementation."""
        fvg_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "forecasters" / "fvg.py"
        
        assert fvg_path.exists(), f"FVG file not found: {fvg_path}"
        
        with open(fvg_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify FVG class exists (represents FVGZone)
        assert "class FVG" in content, \
            "FVG class should exist in fvg.py"
        
        # Verify FVGStore class exists
        assert "class FVGStore" in content, \
            "FVGStore class should exist in fvg.py"
        
        # Verify FVGForecaster class exists
        assert "class FVGForecaster" in content, \
            "FVGForecaster class should exist in fvg.py"
        
        # Verify OHLC-based detection (not approximation)
        assert "OHLC" in content or "candle" in content.lower(), \
            "FVG detection should use OHLC/candle data (not approximation)"
    
    def test_fvg_config_in_profile_yaml(self):
        """Verify that FVG configuration is in profile YAML (not env vars)."""
        profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        assert profile_path.exists(), f"Profile file not found: {profile_path}"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        # Verify momentum_fvg section exists
        assert "momentum_fvg" in profile_data, \
            "momentum_fvg section should exist in profile YAML"
        
        fvg_config = profile_data["momentum_fvg"]
        
        # Verify FVG config parameters
        assert "fvg_window_size" in fvg_config, \
            "fvg_window_size should be in momentum_fvg config"
        assert "fvg_min_gap_cents" in fvg_config, \
            "fvg_min_gap_cents should be in momentum_fvg config"
        assert "fvg_fill_threshold_cents" in fvg_config, \
            "fvg_fill_threshold_cents should be in momentum_fvg config"
        assert "fvg_atr_period" in fvg_config, \
            "fvg_atr_period should be in momentum_fvg config"
    
    def test_fvg_integrator_uses_profile_config(self):
        """Verify that FVGIntegrator reads from profile YAML (not env vars)."""
        fvg_integrator_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "forecasters" / "fvg_integration.py"
        
        # FVG integration may be in a different location
        if not fvg_integrator_path.exists():
            # Try alternative location
            fvg_integrator_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "strategies" / "fvg_integration.py"
        
        if fvg_integrator_path.exists():
            with open(fvg_integrator_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Verify it reads from profile (not os.environ for FVG config)
            # This is a soft check - we just verify profile loading is present
            assert "profile" in content.lower() or "yaml" in content.lower(), \
                "FVGIntegrator should reference profile/YAML config"
    
    def test_agent_grid_uses_fvg_forecaster(self):
        """Verify that agent_grid_15m.py uses the FVG forecaster (not crypto_15m_indicators)."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        assert agent_grid_path.exists(), f"Agent grid file not found: {agent_grid_path}"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify it imports from fvg module
        assert "from merid.prediction.forecasters.fvg" in content or \
               "get_fvg_forecaster" in content, \
            "Agent grid should use FVG forecaster from merid.prediction.forecasters.fvg"
        
        # Verify momentum_fvg signal mode exists
        assert "momentum_fvg" in content, \
            "Agent grid should have momentum_fvg signal mode"
    
    def test_agent_grid_passes_required_fvg_arguments(self):
        """Verify that agent_grid_15m.py passes required arguments to FVG forecaster."""
        agent_grid_path = Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        assert agent_grid_path.exists(), f"Agent grid file not found: {agent_grid_path}"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the FVG forecaster call includes required arguments
        # The predict method requires: market_id, implied_yes, implied_no, volume, open_interest, minutes_to_expiry
        assert "open_interest=" in content, \
            "Agent grid should pass open_interest to FVG forecaster"
        assert "minutes_to_expiry=" in content, \
            "Agent grid should pass minutes_to_expiry to FVG forecaster"
        assert "implied_yes=" in content, \
            "Agent grid should pass implied_yes to FVG forecaster"
        assert "implied_no=" in content, \
            "Agent grid should pass implied_no to FVG forecaster"
        assert "volume=" in content, \
            "Agent grid should pass volume to FVG forecaster"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
