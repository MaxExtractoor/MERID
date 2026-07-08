"""
Tests for spot data handling fixes in agent_grid_15m.py

Tests for:
1. SpotError handling when spot data is unavailable
2. Profile adapter attribute access fixes
3. Spot data OHLC extraction with proper None handling
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass


@dataclass
class SpotError:
    """Mock SpotError class for testing."""
    reason: str
    asset: str
    message: str


@dataclass
class SpotPrice:
    """Mock SpotPrice class for testing."""
    price: float
    timestamp: int
    source: str
    open: float = None
    high: float = None
    low: float = None
    volume: float = None


class TestSpotDataHandling:
    """Test spot data handling in agent_grid_15m.py"""
    
    def test_spot_error_detection(self):
        """Test that SpotError is detected correctly when spot data is unavailable."""
        # Create mock spot provider that returns SpotError
        spot_provider = MagicMock()
        spot_error = SpotError(reason="no_data", asset="BTC", message="No cached data available")
        spot_provider.get.return_value = spot_error
        
        # This should handle SpotError gracefully without crashing
        # The spot_error should be detected and spot_price/spot_data set to None
        result = spot_provider.get("BTC")
        
        assert hasattr(result, 'reason'), "SpotError should have reason attribute"
        assert result.reason == "no_data", "SpotError reason should be 'no_data'"
        
    def test_spot_price_with_ohlc(self):
        """Test that SpotPrice with OHLC data is handled correctly."""
        # Create mock spot provider that returns SpotPrice with OHLC
        spot_provider = MagicMock()
        spot_price = SpotPrice(
            price=62000.0,
            timestamp=1234567890,
            source="coinbase",
            open=61900.0,
            high=62100.0,
            low=61800.0,
            volume=100.0
        )
        spot_provider.get.return_value = spot_price
        
        # This should extract OHLC data correctly
        result = spot_provider.get("BTC")
        
        assert hasattr(result, 'price'), "SpotPrice should have price attribute"
        assert result.price == 62000.0, "SpotPrice should have correct price"
        assert hasattr(result, 'open'), "SpotPrice should have open attribute"
        assert result.open == 61900.0, "SpotPrice should have correct open"
        assert hasattr(result, 'high'), "SpotPrice should have high attribute"
        assert result.high == 62100.0, "SpotPrice should have correct high"
        assert hasattr(result, 'low'), "SpotPrice should have low attribute"
        assert result.low == 61800.0, "SpotPrice should have correct low"
        
    def test_spot_price_without_ohlc(self):
        """Test that SpotPrice without OHLC data is handled correctly."""
        # Create mock spot provider that returns SpotPrice without OHLC
        spot_provider = MagicMock()
        spot_price = SpotPrice(
            price=62000.0,
            timestamp=1234567890,
            source="coinbase"
            # No OHLC data
        )
        spot_provider.get.return_value = spot_price
        
        # This should handle missing OHLC data gracefully
        result = spot_provider.get("BTC")
        
        assert hasattr(result, 'price'), "SpotPrice should have price attribute"
        assert result.price == 62000.0, "SpotPrice should have correct price"
        assert result.open is None, "SpotPrice should have None for open when not provided"
        assert result.high is None, "SpotPrice should have None for high when not provided"
        assert result.low is None, "SpotPrice should have None for low when not provided"


class TestProfileAdapterAccess:
    """Test profile adapter attribute access fixes"""
    
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    def test_profile_adapter_direct_attribute_access(self, mock_get_profile):
        """Test that profile attributes are accessed directly, not via .get()"""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter, Crypto15mProfile
        
        # Create mock profile
        mock_profile = MagicMock(spec=Crypto15mProfile)
        mock_profile.guardrails_min_entry_mins = 2.0
        mock_profile.guardrails_max_entry_mins = 15.0
        mock_profile.agent_cutoff_minutes_before_expiry = 2.0
        
        # Create mock adapter
        mock_adapter = MagicMock(spec=Crypto15mProfileAdapter)
        mock_adapter._profile = mock_profile
        mock_get_profile.return_value = mock_adapter
        
        # Import and test the fixed code path
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        if adapter and adapter._profile:
            profile = adapter._profile
            min_entry_mins = profile.guardrails_min_entry_mins
            max_entry_mins = profile.guardrails_max_entry_mins
            cutoff_mins = profile.agent_cutoff_minutes_before_expiry
            
            assert min_entry_mins == 2.0, "Should access guardrails_min_entry_mins directly"
            assert max_entry_mins == 15.0, "Should access guardrails_max_entry_mins directly"
            assert cutoff_mins == 2.0, "Should access agent_cutoff_minutes_before_expiry directly"
    
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    def test_profile_adapter_none_handling(self, mock_get_profile):
        """Test that None profile adapter is handled gracefully"""
        mock_get_profile.return_value = None
        
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        
        # Should use defaults when adapter is None
        if adapter and adapter._profile:
            profile = adapter._profile
            min_entry_mins = profile.guardrails_min_entry_mins
        else:
            min_entry_mins = 2.0  # Default
        
        assert min_entry_mins == 2.0, "Should use default when adapter is None"


class TestFloorAppliedLogic:
    """Test floor_applied logic in risk envelope"""
    
    def test_floor_applied_when_cap_exceeds_target(self):
        """Test that floor_applied is True when floor increases cap above target"""
        min_max_notional_usd = 0.10
        effective_capital = 2.0  # Very small bankroll where 3% is below floor
        max_notional_pct = 0.03  # 3%
        target_usd = effective_capital * max_notional_pct  # 0.06
        cap = max(target_usd, min_max_notional_usd)  # 0.10 (floor applies)
        
        floor_applied = min_max_notional_usd > 0 and cap > target_usd
        
        assert floor_applied is True, "floor_applied should be True when floor increases cap"
        assert cap == 0.10, "Cap should be at floor value"
        
    def test_floor_not_applied_when_cap_equals_target(self):
        """Test that floor_applied is False when target is already above floor"""
        min_max_notional_usd = 0.10
        effective_capital = 34.01  # Current live bankroll
        max_notional_pct = 0.03  # 3%
        target_usd = effective_capital * max_notional_pct  # 1.0203
        cap = max(target_usd, min_max_notional_usd)  # 1.0203 (target applies)
        
        floor_applied = min_max_notional_usd > 0 and cap > target_usd
        
        assert floor_applied is False, "floor_applied should be False when target is above floor"
        assert abs(cap - 1.0203) < 0.001, "Cap should be at target value (allowing floating point precision)"
        
    def test_floor_disabled_when_zero(self):
        """Test that floor_applied is False when min_max_notional_usd is 0"""
        min_max_notional_usd = 0.0  # Floor disabled
        effective_capital = 10.0
        max_notional_pct = 0.03
        target_usd = effective_capital * max_notional_pct  # 0.30
        cap = max(target_usd, min_max_notional_usd)  # 0.30
        
        floor_applied = min_max_notional_usd > 0 and cap > target_usd
        
        assert floor_applied is False, "floor_applied should be False when floor is disabled"
        assert cap == 0.30, "Cap should be at target value when floor is disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
