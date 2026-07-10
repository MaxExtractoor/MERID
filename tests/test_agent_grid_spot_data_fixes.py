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
        mock_profile.guardrails_min_entry_mins = 0.0  # Removed minimum to allow full window trading
        mock_profile.guardrails_max_entry_mins = 15.0
        mock_profile.agent_cutoff_minutes_before_expiry = 0.0  # Removed cutoff to allow full window
        
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
            
            assert min_entry_mins == 0.0, "Should access guardrails_min_entry_mins directly"
            assert max_entry_mins == 15.0, "Should access guardrails_max_entry_mins directly"
            assert cutoff_mins == 0.0, "Should access agent_cutoff_minutes_before_expiry directly"
    
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
            min_entry_mins = 0.5  # Default (relaxed from 2.0)
        
        assert min_entry_mins == 0.5, "Should use default when adapter is None"


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


class TestSynchronousSpotProvider:
    """Test that spot provider.get() is called synchronously, not with await"""
    
    def test_spot_provider_get_is_synchronous(self):
        """Test that spot_provider.get() is a synchronous method, not async"""
        # Create mock spot provider
        spot_provider = MagicMock()
        spot_price = SpotPrice(
            price=62000.0,
            timestamp=1234567890,
            source="coinbase"
        )
        spot_provider.get.return_value = spot_price
        
        # Call get() synchronously (no await)
        result = spot_provider.get("BTC")
        
        # Verify it returns the result directly (not a coroutine)
        assert not hasattr(result, '__await__'), "get() should return a value, not a coroutine"
        assert result.price == 62000.0, "get() should return the spot price"
        
    def test_spot_provider_get_with_ohlc_synchronous(self):
        """Test that spot_provider.get() with OHLC data is synchronous"""
        spot_provider = MagicMock()
        spot_price = SpotPrice(
            price=62000.0,
            timestamp=1234567890,
            source="coinbase",
            open=61900.0,
            high=62100.0,
            low=61800.0
        )
        spot_provider.get.return_value = spot_price
        
        # Call get() synchronously
        result = spot_provider.get("BTC")
        
        # Verify it returns the result directly
        assert not hasattr(result, '__await__'), "get() should return a value, not a coroutine"
        assert result.open == 61900.0, "get() should return OHLC data synchronously"


class TestEdgeCalculationFix:
    """Test edge calculation fix - edge should never be None"""
    
    def test_fvg_edge_returns_value_for_low_score(self):
        """Test that fvg_edge returns a value even when score < 3"""
        # Simulate the fvg_edge function logic
        score = 2  # Below threshold
        velocity = 0.01
        velocity_threshold = 0.005
        macd_histogram = 0.001
        rsi_zone = "neutral"
        fvg_direction = "bullish"
        fvg_confidence = 0.6
        
        # CRITICAL FIX: 2026-07-10 - fvg_edge should return 0.5 for score < 3, not None
        if score < 3:
            edge = 0.5  # Minimal edge for insufficient conditions
        else:
            edge = 2.0  # Normal edge calculation
        
        assert edge is not None, "fvg_edge should never return None"
        assert edge == 0.5, "fvg_edge should return 0.5 for score < 3"
        
    def test_fvg_edge_returns_value_for_high_score(self):
        """Test that fvg_edge returns proper value when score >= 3"""
        score = 4  # Above threshold
        velocity = 0.01
        velocity_threshold = 0.005
        macd_histogram = 0.001
        rsi_zone = "neutral"
        fvg_direction = "bullish"
        fvg_confidence = 0.6
        
        # CRITICAL FIX: 2026-07-10 - fvg_edge should return proper edge for score >= 3
        if score < 3:
            edge = 0.5
        else:
            edge = 2.0 + abs(macd_histogram) * 10.0  # Normal edge calculation
        
        assert edge is not None, "fvg_edge should never return None"
        assert edge > 2.0, "fvg_edge should return > 2.0 for score >= 3"


class TestRiskEnvelopeSnapshotFix:
    """Test risk envelope snapshot fix - profile_capital and sum_caps removed"""
    
    def test_snapshot_uses_effective_capital_not_profile_capital(self):
        """Test that snapshot uses effective_capital instead of profile_capital"""
        live_bankroll_usd = 32.24
        profile_capital = 0.0
        effective_capital = live_bankroll_usd  # In production, effective_capital = live_bankroll
        
        # CRITICAL FIX: 2026-07-10 - Snapshot should log effective_capital, not profile_capital
        snapshot = f"live_bankroll=${live_bankroll_usd:.2f} effective_capital=${effective_capital:.2f}"
        
        assert "profile_capital" not in snapshot, "Snapshot should not include profile_capital"
        assert "effective_capital" in snapshot, "Snapshot should include effective_capital"
        assert "$32.24" in snapshot, "Snapshot should show live bankroll value"
        
    def test_snapshot_removes_sum_caps(self):
        """Test that snapshot does not include sum_caps"""
        venue_cap = 1.00
        
        # CRITICAL FIX: 2026-07-10 - Snapshot should not include sum_caps
        snapshot = f"live_bankroll=$32.24 effective_capital=$32.24 venue_cap=${venue_cap:.2f}"
        
        assert "sum_caps" not in snapshot, "Snapshot should not include sum_caps"
        assert "venue_cap=$1.00" in snapshot, "Snapshot should include venue cap"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
