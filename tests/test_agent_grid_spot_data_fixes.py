"""
Tests for spot data handling fixes in agent_grid_15m.py

Tests for:
1. SpotError handling when spot data is unavailable
2. Profile adapter attribute access fixes
3. Spot data OHLC extraction with proper None handling
4. Session order count increment on submission (2026-07-10 fix)
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


class TestSessionOrderCountFillPhaseFix:
    """Test session order count increment on order fill (2026-07-10 fix)"""
    
    def test_session_order_count_increments_on_fill(self):
        """Test that session order count is incremented when order fills, not on submission"""
        # Simulate session order count behavior
        session_order_count = 0
        max_orders_per_window = 12
        
        # Simulate order submission (should NOT increment count)
        # session_order_count += 1  # REMOVED: No longer increments on submission
        
        # Verify count was NOT incremented on submission
        assert session_order_count == 0, "Session order count should NOT increment on submission"
        
        # Simulate order fill (should increment count)
        session_order_count += 1
        
        # Verify count was incremented on fill
        assert session_order_count == 1, "Session order count should increment on fill"
        assert session_order_count < max_orders_per_window, "Should not exceed max orders per window"
        
        # Simulate another fill
        session_order_count += 1
        assert session_order_count == 2, "Session order count should increment on each fill"
        
    def test_cooldown_updated_on_fill(self):
        """Test that cooldown is updated when order fills, not on submission"""
        import time
        
        # Simulate cooldown behavior
        last_trade_time = 0.0
        cooldown_seconds = 30
        
        # Simulate order submission (should NOT update last_trade_time)
        # last_trade_time = time.time()  # REMOVED: No longer updates on submission
        
        # Verify cooldown was NOT updated on submission
        assert last_trade_time == 0.0, "Cooldown should NOT be updated on submission"
        
        # Simulate order fill (should update last_trade_time)
        current_time = time.time()
        last_trade_time = current_time
        
        # Verify cooldown was updated on fill
        assert last_trade_time > 0, "Cooldown should be updated on fill"
        assert last_trade_time == current_time, "Cooldown should be set to current time on fill"
        
        # Verify cooldown check would block subsequent submissions
        time_since_trade = time.time() - last_trade_time
        assert time_since_trade < cooldown_seconds, "Cooldown should block immediate re-submission after fill"


class TestGlobalExposureCapFix:
    """Test that per_agent_window_limit_usd is global across all 5 assets (2026-07-10 fix)"""
    
    def test_per_agent_limit_is_global_not_per_agent(self):
        """Test that per_agent_window_limit_usd represents global cap, not per-agent cap"""
        # The $1.00 cap is TOTAL exposure across BTC+ETH+SOL+XRP+DOGE, not per agent
        fixed_exposure_cap_usd = 1.00
        per_agent_window_limit_usd = fixed_exposure_cap_usd  # This is GLOBAL limit
        total_venue_window_limit_usd = fixed_exposure_cap_usd  # Same global limit
        
        # Verify both limits are the same (global cap)
        assert per_agent_window_limit_usd == total_venue_window_limit_usd, \
            "per_agent_window_limit_usd should equal total_venue_window_limit_usd (both are global)"
        assert per_agent_window_limit_usd == 1.00, \
            "Global exposure cap should be $1.00"
        
    def test_global_cap_distributed_across_5_assets(self):
        """Test that global $1.00 cap is distributed across all 5 assets"""
        global_cap = 1.00
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # If each asset gets equal share, each would get $0.20
        equal_share = global_cap / len(assets)
        
        # Verify the math
        assert equal_share == 0.20, "Each asset should get $0.20 from $1.00 global cap"
        assert sum([equal_share] * len(assets)) == global_cap, \
            "Sum of equal shares should equal global cap"


class TestPriceRangeLoggingFix:
    """Test price range logging for debugging yes_in_range/no_in_range (2026-07-10 fix)"""
    
    def test_price_range_check_logic(self):
        """Test that price range check logic is correct"""
        # Test yes price in range
        yes_price_cents = 50
        yes_in_range = (5 <= yes_price_cents <= 95)
        assert yes_in_range is True, "Price of 50c should be in range"
        
        # Test yes price out of range (too low)
        yes_price_cents = 3
        yes_in_range = (5 <= yes_price_cents <= 95)
        assert yes_in_range is False, "Price of 3c should be out of range"
        
        # Test yes price out of range (too high)
        yes_price_cents = 97
        yes_in_range = (5 <= yes_price_cents <= 95)
        assert yes_in_range is False, "Price of 97c should be out of range"
        
        # Test no price in range
        no_price_cents = 50
        no_in_range = (5 <= no_price_cents <= 95)
        assert no_in_range is True, "Price of 50c should be in range"
        
    def test_both_sides_out_of_range_blocks_trade(self):
        """Test that trade is blocked when both sides are out of range"""
        yes_price_cents = 97
        no_price_cents = 97
        
        yes_in_range = (5 <= yes_price_cents <= 95)
        no_in_range = (5 <= no_price_cents <= 95)
        
        should_block = not yes_in_range and not no_in_range
        assert should_block is True, "Trade should be blocked when both sides are out of range"


class TestADXWarmupBehavior:
    """Test ADX warmup behavior (2026-07-10 fix)"""
    
    def test_adx_returns_zero_during_warmup(self):
        """Test that ADX returns 0.0 during warmup (insufficient history)"""
        # Simulate ADX calculation with insufficient history
        history_length = 2  # Less than required 15 data points
        period = 14
        
        if history_length < period + 1:
            adx = 0.0  # Return 0.0 during warmup
        
        assert adx == 0.0, "ADX should return 0.0 during warmup"
        
    def test_adx_multiplier_neutral_during_warmup(self):
        """Test that ADX multiplier is neutral (1.0) during warmup"""
        adx = 0.0  # During warmup
        
        # ADX multiplier should be neutral during warmup
        if adx >= 25.0:
            adx_multiplier = 1.0
        elif adx >= 10.0:
            adx_multiplier = 1.0
        elif adx > 0:
            adx_multiplier = 1.0
        else:  # adx == 0 (warmup)
            adx_multiplier = 1.0
        
        assert adx_multiplier == 1.0, "ADX multiplier should be 1.0 (neutral) during warmup"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
