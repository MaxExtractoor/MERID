"""Tests for asset name normalization in unified_sizing.py.

2026-07-05: Fixed critical bug where callers pass asset names like "XRP15M" but
profile config uses keys like "XRP". Without normalization, per-asset risk lookup
fails, causing assets to use global cap instead of their configured 3% allocation.

Run: py -m pytest tests/test_unified_sizing_asset_normalization.py -v
"""

from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

# Import the functions to test
from merid.prediction.unified_sizing import _get_per_asset_risk_pct, _get_max_contracts_per_asset


class TestAssetNameNormalization:
    """Tests for asset name normalization in per-asset lookups."""
    
    def test_get_per_asset_risk_pct_normalizes_15m_suffix(self, mocker):
        """Test that 'XRP15M' is normalized to 'XRP' for profile lookup."""
        # Mock profile with asset config
        mock_adapter = Mock()
        mock_profile = Mock()
        mock_asset_config = Mock()
        mock_asset_config.max_notional_pct = 0.03  # 3%
        
        mock_profile.asset_configs = {
            "XRP": mock_asset_config,
            "BTC": Mock(max_notional_pct=0.03),
            "ETH": Mock(max_notional_pct=0.03),
            "SOL": Mock(max_notional_pct=0.03),
            "DOGE": Mock(max_notional_pct=0.03),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with "XRP15M" (should normalize to "XRP")
        result = _get_per_asset_risk_pct("XRP15M")
        
        assert result is not None, "Should find asset config after normalization"
        assert result == Decimal("0.03"), "Should return 3% for XRP"
    
    def test_get_per_asset_risk_pct_works_without_suffix(self, mocker):
        """Test that 'XRP' (without suffix) still works."""
        # Mock profile with asset config
        mock_adapter = Mock()
        mock_profile = Mock()
        mock_asset_config = Mock()
        mock_asset_config.max_notional_pct = 0.03
        
        mock_profile.asset_configs = {
            "XRP": mock_asset_config,
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with "XRP" (no suffix)
        result = _get_per_asset_risk_pct("XRP")
        
        assert result is not None, "Should find asset config"
        assert result == Decimal("0.03"), "Should return 3% for XRP"
    
    def test_get_per_asset_risk_pct_all_crypto_assets(self, mocker):
        """Test normalization for all 5 crypto assets."""
        # Mock profile with all asset configs
        mock_adapter = Mock()
        mock_profile = Mock()
        
        mock_profile.asset_configs = {
            "BTC": Mock(max_notional_pct=0.03),
            "ETH": Mock(max_notional_pct=0.03),
            "SOL": Mock(max_notional_pct=0.03),
            "XRP": Mock(max_notional_pct=0.03),
            "DOGE": Mock(max_notional_pct=0.03),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test all assets with "15M" suffix
        for asset in ["BTC15M", "ETH15M", "SOL15M", "XRP15M", "DOGE15M"]:
            result = _get_per_asset_risk_pct(asset)
            assert result is not None, f"Should find {asset} after normalization"
            assert result == Decimal("0.03"), f"{asset} should return 3%"
    
    def test_get_per_asset_risk_pct_unknown_asset_returns_none(self, mocker):
        """Test that unknown asset returns None (uses global cap)."""
        # Mock profile with limited asset configs
        mock_adapter = Mock()
        mock_profile = Mock()
        
        mock_profile.asset_configs = {
            "BTC": Mock(max_notional_pct=0.03),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with unknown asset
        result = _get_per_asset_risk_pct("UNKNOWN15M")
        
        assert result is None, "Unknown asset should return None (use global cap)"
    
    def test_get_max_contracts_per_asset_normalizes_15m_suffix(self, mocker):
        """Test that 'XRP15M' is normalized to 'XRP' for max contracts lookup."""
        # Mock profile with asset config
        mock_adapter = Mock()
        mock_profile = Mock()
        mock_asset_config = Mock()
        mock_asset_config.max_contracts = 3
        
        mock_profile.asset_configs = {
            "XRP": mock_asset_config,
            "BTC": Mock(max_contracts=3),
            "ETH": Mock(max_contracts=3),
            "SOL": Mock(max_contracts=3),
            "DOGE": Mock(max_contracts=2),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with "XRP15M" (should normalize to "XRP")
        result = _get_max_contracts_per_asset("XRP15M")
        
        assert result == 3, "Should return 3 for XRP"
    
    def test_get_max_contracts_per_asset_all_crypto_assets(self, mocker):
        """Test normalization for all 5 crypto assets max contracts."""
        # Mock profile with all asset configs
        mock_adapter = Mock()
        mock_profile = Mock()
        
        mock_profile.asset_configs = {
            "BTC": Mock(max_contracts=3),
            "ETH": Mock(max_contracts=3),
            "SOL": Mock(max_contracts=3),
            "XRP": Mock(max_contracts=3),
            "DOGE": Mock(max_contracts=2),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test all assets with "15M" suffix
        expected = {
            "BTC15M": 3,
            "ETH15M": 3,
            "SOL15M": 3,
            "XRP15M": 3,
            "DOGE15M": 2,
        }
        
        for asset, expected_contracts in expected.items():
            result = _get_max_contracts_per_asset(asset)
            assert result == expected_contracts, f"{asset} should return {expected_contracts}"
    
    def test_get_max_contracts_per_asset_unknown_asset_uses_default(self, mocker):
        """Test that unknown asset uses default max_contracts=10."""
        # Mock profile with limited asset configs
        mock_adapter = Mock()
        mock_profile = Mock()
        
        mock_profile.asset_configs = {
            "BTC": Mock(max_contracts=3),
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with unknown asset
        result = _get_max_contracts_per_asset("UNKNOWN15M")
        
        assert result == 10, "Unknown asset should return default 10"
    
    def test_normalization_does_not_affect_non_15m_assets(self, mocker):
        """Test that assets without '15M' suffix are not affected."""
        # Mock profile with asset config
        mock_adapter = Mock()
        mock_profile = Mock()
        mock_asset_config = Mock()
        mock_asset_config.max_notional_pct = 0.03
        
        mock_profile.asset_configs = {
            "XRP": mock_asset_config,
        }
        
        mock_adapter.profile = mock_profile
        
        mocker.patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', True)
        mocker.patch('merid.prediction.unified_sizing.is_profile_active', return_value=True)
        mocker.patch('merid.prediction.unified_sizing.get_active_profile', return_value=mock_adapter)
        
        # Test with "XRP" (no suffix)
        result = _get_per_asset_risk_pct("XRP")
        
        assert result == Decimal("0.03"), "Should return 3% for XRP without suffix"
        
        # Test with "XRP_OTHER" (different suffix, should not match)
        result = _get_per_asset_risk_pct("XRP_OTHER")
        
        assert result is None, "Different suffix should not match"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
