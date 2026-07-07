"""Test price filtering consistency across all layers.

This test verifies that price filtering is consistent across:
- Profile YAML (guardrails_min_contract_price_cents)
- Risk parameters (DEEP_OTM_CHEAP_CENTS)
- Agent grid (min_entry_prices)
- Order gate (price validation)
- Order router (deep OTM policy)

All layers should enforce a 10c minimum entry price.
"""

import pytest
import yaml
import re


class TestPriceFilteringConsistency:
    """Test price filtering consistency across all layers."""
    
    def test_profile_yaml_min_price_is_10c(self):
        """Test that profile YAML sets min_contract_price_cents to 10."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        guardrails = profile.get("guardrails", {})
        min_price = guardrails.get("min_contract_price_cents")
        
        assert min_price == 10, \
            f"Profile guardrails_min_contract_price_cents should be 10, got {min_price}"
    
    def test_profile_yaml_max_price_is_75c(self):
        """Test that profile YAML sets max_contract_price_cents to 75."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        guardrails = profile.get("guardrails", {})
        max_price = guardrails.get("max_contract_price_cents")
        
        assert max_price == 75, \
            f"Profile guardrails_max_contract_price_cents should be 75, got {max_price}"
    
    def test_risk_parameters_deep_otm_cheap_is_10c(self):
        """Test that risk_parameters.py DEEP_OTM_CHEAP_CENTS is 10."""
        with open("merid/event_venues/kalshi/risk_parameters.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Extract DEEP_OTM_CHEAP_CENTS value
        match = re.search(r'DEEP_OTM_CHEAP_CENTS.*?=\s*(\d+)', content)
        assert match, "DEEP_OTM_CHEAP_CENTS not found in risk_parameters.py"
        
        value = int(match.group(1))
        assert value == 10, \
            f"DEEP_OTM_CHEAP_CENTS should be 10, got {value}"
    
    def test_risk_parameters_deep_otm_expensive_is_75c(self):
        """Test that risk_parameters.py DEEP_OTM_EXPENSIVE_CENTS is 75."""
        with open("merid/event_venues/kalshi/risk_parameters.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Extract DEEP_OTM_EXPENSIVE_CENTS value
        match = re.search(r'DEEP_OTM_EXPENSIVE_CENTS.*?=\s*(\d+)', content)
        assert match, "DEEP_OTM_EXPENSIVE_CENTS not found in risk_parameters.py"
        
        value = int(match.group(1))
        assert value == 75, \
            f"DEEP_OTM_EXPENSIVE_CENTS should be 75, got {value}"
    
    def test_agent_grid_min_entry_prices_are_10c(self):
        """Test that agent_grid_15m.py min_entry_prices are all 10c."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Extract min_entry_prices dictionary
        match = re.search(r'min_entry_prices\s*=\s*\{([^}]+)\}', content, re.DOTALL)
        assert match, "min_entry_prices not found in agent_grid_15m.py"
        
        dict_content = match.group(1)
        
        # Check all assets are set to 10
        assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        for asset in assets:
            asset_match = re.search(rf"'{asset}'\s*:\s*(\d+)", dict_content)
            assert asset_match, f"{asset} not found in min_entry_prices"
            value = int(asset_match.group(1))
            assert value == 10, \
                f"min_entry_prices['{asset}'] should be 10, got {value}"
    
    def test_agent_grid_no_10_19c_rejection(self):
        """Test that agent_grid_15m.py does NOT reject 10-19c range."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that the 10-19c rejection code is NOT present
        # The old code had: if 10 <= market_price_cents <= 19:
        assert "10 <= market_price_cents <= 19" not in content, \
            "agent_grid_15m.py should not reject 10-19c range"
        assert "PRICE-FILTER-LOW-PRICE" not in content, \
            "agent_grid_15m.py should not have PRICE-FILTER-LOW-PRICE logic"
    
    def test_agent_grid_hard_ban_below_10c(self):
        """Test that agent_grid_15m.py hard bans below 10c."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that hard ban below 10c is present
        assert "market_price_cents < 10" in content, \
            "agent_grid_15m.py should hard ban below 10c"
        assert "PRICE-FILTER-HARD-BAN" in content, \
            "agent_grid_15m.py should have PRICE-FILTER-HARD-BAN logic"
    
    def test_order_gate_uses_profile_min_price(self):
        """Test that order_gate.py uses profile guardrails_min_contract_price_cents."""
        with open("merid/event_venues/kalshi/order_gate.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that order_gate uses profile value
        assert "guardrails_min_contract_price_cents" in content, \
            "order_gate.py should use guardrails_min_contract_price_cents from profile"
        assert "deep_otm_longshot_blocked" in content, \
            "order_gate.py should have deep_otm_longshot_blocked logic"
    
    def test_order_router_validates_deep_otm(self):
        """Test that order_router.py validates deep OTM policy."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that order_router has deep OTM validation
        assert "_validate_deep_otm_policy" in content, \
            "order_router.py should have _validate_deep_otm_policy function"
        assert "DEEP_OTM_CHEAP_CENTS" in content, \
            "order_router.py should use DEEP_OTM_CHEAP_CENTS"
        assert "DEEP_OTM_EXPENSIVE_CENTS" in content, \
            "order_router.py should use DEEP_OTM_EXPENSIVE_CENTS"
    
    def test_unified_edge_uses_profile_price_range(self):
        """Test that unified_edge.py uses profile price_range."""
        with open("merid/prediction/unified_edge.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that unified_edge uses profile values
        assert "guardrails_min_contract_price_cents" in content, \
            "unified_edge.py should use guardrails_min_contract_price_cents from profile"
        assert "guardrails_max_contract_price_cents" in content, \
            "unified_edge.py should use guardrails_max_contract_price_cents from profile"
        assert "longshot_trap_price_too_low" in content, \
            "unified_edge.py should have longshot_trap logic"
    
    def test_profile_adapter_defaults_match_yaml(self):
        """Test that profile adapter defaults match YAML values."""
        with open("merid/risk/profiles/crypto_15m_profile.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Extract guardrails_min_contract_price_cents default
        min_match = re.search(
            r'guardrails_min_contract_price_cents.*?=\s*guardrails\.get\([\'"]min_contract_price_cents[\'"]\s*,\s*(\d+)\)',
            content
        )
        assert min_match, "guardrails_min_contract_price_cents default not found"
        min_default = int(min_match.group(1))
        assert min_default == 10, \
            f"Profile adapter default for min should be 10, got {min_default}"
        
        # Extract guardrails_max_contract_price_cents default
        max_match = re.search(
            r'guardrails_max_contract_price_cents.*?=\s*guardrails\.get\([\'"]max_contract_price_cents[\'"]\s*,\s*(\d+)\)',
            content
        )
        assert max_match, "guardrails_max_contract_price_cents default not found"
        max_default = int(max_match.group(1))
        assert max_default == 75, \
            f"Profile adapter default for max should be 75, got {max_default}"
    
    def test_all_layers_consistent_10c_minimum(self):
        """Test that all layers are consistent with 10c minimum."""
        # Profile YAML
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        profile_min = profile["guardrails"]["min_contract_price_cents"]
        
        # Risk parameters
        with open("merid/event_venues/kalshi/risk_parameters.py", "r", encoding="utf-8") as f:
            risk_content = f.read()
        risk_match = re.search(r'DEEP_OTM_CHEAP_CENTS.*?=\s*(\d+)', risk_content)
        risk_min = int(risk_match.group(1))
        
        # Agent grid
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            agent_content = f.read()
        agent_match = re.search(r"'BTC'\s*:\s*(\d+)", agent_content)
        agent_min = int(agent_match.group(1))
        
        # All should be 10
        assert profile_min == 10, f"Profile min is {profile_min}, expected 10"
        assert risk_min == 10, f"Risk min is {risk_min}, expected 10"
        assert agent_min == 10, f"Agent grid min is {agent_min}, expected 10"
        
        # All should be equal
        assert profile_min == risk_min == agent_min, \
            f"Inconsistent minimums: profile={profile_min}, risk={risk_min}, agent={agent_min}"
    
    def test_all_layers_consistent_75c_maximum(self):
        """Test that all layers are consistent with 75c maximum."""
        # Profile YAML
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        profile_max = profile["guardrails"]["max_contract_price_cents"]
        
        # Risk parameters
        with open("merid/event_venues/kalshi/risk_parameters.py", "r", encoding="utf-8") as f:
            risk_content = f.read()
        risk_match = re.search(r'DEEP_OTM_EXPENSIVE_CENTS.*?=\s*(\d+)', risk_content)
        risk_max = int(risk_match.group(1))
        
        # Profile price_range
        price_range_max = profile["price_range"]["max_price_cents"]
        
        # All should be 75
        assert profile_max == 75, f"Profile max is {profile_max}, expected 75"
        assert risk_max == 75, f"Risk max is {risk_max}, expected 75"
        assert price_range_max == 75, f"Price range max is {price_range_max}, expected 75"
        
        # All should be equal
        assert profile_max == risk_max == price_range_max, \
            f"Inconsistent maximums: profile={profile_max}, risk={risk_max}, price_range={price_range_max}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
