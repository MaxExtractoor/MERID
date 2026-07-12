"""Test offset hedging configuration is disabled for crypto with public markets.

This verifies that offset_hedging is disabled based on research findings that
binary contracts are structurally mismatched for linear loss hedging.
"""

import pytest
from pathlib import Path


class TestOffsetHedgingDisabled:
    """Test suite for offset hedging disabled configuration."""
    
    def test_profile_yaml_has_offset_hedging_disabled(self):
        """Verify the profile YAML has offset_hedging disabled."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        assert profile_path.exists(), f"Profile file not found: {profile_path}"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        assert "offset_hedging" in profile_data, "offset_hedging section missing from YAML"
        
        hedging_config = profile_data["offset_hedging"]
        assert hedging_config["enabled"] is False, "offset_hedging should be disabled"
        
        # Verify the configuration still has the required fields for documentation
        assert "hedge_ratio" in hedging_config
        assert "min_edge_for_hedge" in hedging_config
        assert "max_hedge_notional_pct" in hedging_config
        assert "description" in hedging_config
        assert "inefficient" in hedging_config["description"].lower(), \
            "Description should mention inefficiency for crypto"
    
    def test_offset_hedging_disabled_reasoning(self):
        """Verify offset_hedging is disabled for the right reasons."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        hedging_config = profile_data["offset_hedging"]
        
        # Check that the description mentions the research-based reasoning
        description = hedging_config.get("description", "")
        assert "inefficient" in description.lower(), \
            "Description should mention inefficiency"
        assert "crypto" in description.lower(), \
            "Description should mention crypto"
        assert "disabled" in description.lower(), \
            "Description should mention it's disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
