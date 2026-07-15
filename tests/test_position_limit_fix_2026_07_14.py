"""Test position limit fix (2026-07-14).

This test verifies that per-side position limits are set to 1 to match
max_single_order_contracts=1 and prevent position accumulation.

Bug: max_yes_position and max_no_position were set to 5, allowing accumulation
of up to 5 contracts per side despite max_single_order_contracts=1. This caused
multi-contract exit orders to be required to close accumulated positions.

Fix: Reduced max_yes_position and max_no_position to 1 in kalshi_crypto_15m_v2.yaml.
"""

import pytest
from pathlib import Path
import yaml


class TestPositionLimitFix:
    """Test that per-side position limits match single-contract entry limit."""
    
    def test_max_yes_position_is_1(self):
        """Verify max_yes_position is 1 to match max_single_order_contracts."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        assert profile_path.exists(), "Profile YAML not found"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        agent_defaults = profile_data.get("agent_defaults", {})
        max_yes = agent_defaults.get("max_yes_position")
        
        assert max_yes == 1, \
            f"max_yes_position should be 1 to match max_single_order_contracts=1, got {max_yes}"
    
    def test_max_no_position_is_1(self):
        """Verify max_no_position is 1 to match max_single_order_contracts."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        assert profile_path.exists(), "Profile YAML not found"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        agent_defaults = profile_data.get("agent_defaults", {})
        max_no = agent_defaults.get("max_no_position")
        
        assert max_no == 1, \
            f"max_no_position should be 1 to match max_single_order_contracts=1, got {max_no}"
    
    def test_max_single_order_contracts_is_1(self):
        """Verify max_single_order_contracts is 1."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        assert profile_path.exists(), "Profile YAML not found"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        contract_caps = profile_data.get("contract_caps", {})
        max_single = contract_caps.get("max_single_order_contracts")
        
        assert max_single == 1, \
            f"max_single_order_contracts should be 1, got {max_single}"
    
    def test_position_limits_match_entry_limit(self):
        """Verify per-side position limits match single-contract entry limit."""
        profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
        assert profile_path.exists(), "Profile YAML not found"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        agent_defaults = profile_data.get("agent_defaults", {})
        contract_caps = profile_data.get("contract_caps", {})
        
        max_yes = agent_defaults.get("max_yes_position")
        max_no = agent_defaults.get("max_no_position")
        max_single = contract_caps.get("max_single_order_contracts")
        
        # All should be 1 to prevent position accumulation
        assert max_yes == max_single == 1, \
            f"max_yes_position ({max_yes}) should match max_single_order_contracts ({max_single})"
        assert max_no == max_single == 1, \
            f"max_no_position ({max_no}) should match max_single_order_contracts ({max_single})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
