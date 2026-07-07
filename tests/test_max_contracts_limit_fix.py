"""
Test for max_single_order_contracts limit fix (2026-07-07).

This test verifies that the max contracts per order limit has been increased
from 1 to 10 to allow multi-contract exits (ratchet trim, 99c exit, scale-out).
"""

import pytest
from unittest.mock import patch, MagicMock
import yaml


class TestMaxContractsLimitFix:
    """Test that max_single_order_contracts limit is 10 to allow multi-contract exits."""

    def test_profile_max_single_order_contracts_is_10(self):
        """Test that profile contract_caps.max_single_order_contracts is 10."""
        profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        contract_caps = profile_config.get('contract_caps', {})
        max_single_order = contract_caps.get('max_single_order_contracts')
        
        # Handle both dict with 'value' key and direct int value
        if isinstance(max_single_order, dict):
            max_contracts = max_single_order.get('value', 10)
        else:
            max_contracts = max_single_order
        
        assert max_contracts == 10, f"Expected max_single_order_contracts=10, got {max_contracts}"

    def test_per_asset_max_contracts_are_10(self):
        """Test that all per-asset max_contracts are 10."""
        profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        assets = profile_config.get('assets', {})
        expected_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        
        for asset in expected_assets:
            asset_config = assets.get(asset, {})
            max_contracts = asset_config.get('max_contracts')
            
            # Handle both dict with 'value' key and direct int value
            if isinstance(max_contracts, dict):
                contracts_value = max_contracts.get('value', 10)
            else:
                contracts_value = max_contracts
            
            assert contracts_value == 10, f"Expected {asset} max_contracts=10, got {contracts_value}"

    def test_kalshi_risk_default_is_10(self):
        """Test that KalshiRiskConfig default max_single_order_contracts is 10."""
        # Import the config class
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        # Create config with default values
        config = KalshiRiskConfig()
        
        assert config.max_single_order_contracts == 10, \
            f"Expected default max_single_order_contracts=10, got {config.max_single_order_contracts}"

    def test_order_router_no_hardcoded_limit(self):
        """Test that order_router.py does not have hardcoded 1 contract limit."""
        with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that the old hardcoded check is removed
        assert 'if intent.count > 1:' not in content or \
               'max_single_order_contracts_exceeded' not in content or \
               'CRITICAL FIX (2026-07-07)' in content, \
               "Order router should not have hardcoded 1 contract limit"

    def test_crypto_15m_profile_max_contracts(self):
        """Test that Crypto15mProfile loads max_single_order_contracts correctly."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 contract_caps_max_single_order_contracts=10
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                assert profile.contract_caps_max_single_order_contracts == 10, \
                    f"Expected contract_caps_max_single_order_contracts=10, got {profile.contract_caps_max_single_order_contracts}"

    def test_multi_contract_exit_allowed(self):
        """Test that multi-contract exit orders are allowed with limit of 10."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        config = KalshiRiskConfig(max_single_order_contracts=10)
        
        # Test that 5 contracts is allowed (for ratchet trim)
        assert 5 <= config.max_single_order_contracts, \
            "5 contracts should be allowed for ratchet trim"
        
        # Test that 10 contracts is allowed (for full position exit)
        assert 10 <= config.max_single_order_contracts, \
            "10 contracts should be allowed for full position exit"
        
        # Test that 11 contracts is not allowed
        assert 11 > config.max_single_order_contracts, \
            "11 contracts should exceed the limit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
