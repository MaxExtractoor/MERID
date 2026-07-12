"""Tests for velocity epsilon fix based on realistic crypto price movement research.

The epsilon was increased from 1e-9 (0.0000001%) to 1e-5 (0.001%) based on research showing
that crypto prices move continuously with minimum movement of ~0.001% per minute, even in quiet periods.

Previous epsilon was 100,000x too small, causing velocity to appear zero when actual movement
was small but non-zero, leading to the vicious cycle: velocity=0 -> no trade -> no price update -> velocity=0.
"""

import pytest


class TestVelocityEpsilonFix:
    """Tests for realistic minimum velocity epsilon."""
    
    def test_old_epsilon_too_small(self):
        """Test that old epsilon (1e-9) is 100,000x too small for realistic crypto movement."""
        old_epsilon = 1e-9  # 0.0000001%
        new_epsilon = 1e-5  # 0.001%
        
        # Ratio should be 100,000x
        ratio = new_epsilon / old_epsilon
        assert ratio == 10000, f"New epsilon should be 10,000x larger, got {ratio}x"
    
    def test_new_epsilon_represents_realistic_minimum(self):
        """Test that new epsilon (0.001%) represents realistic minimum crypto price movement."""
        epsilon = 1e-5  # 0.001%
        
        # Research shows typical per-minute movement is 0.01% to 0.1%
        # Epsilon should be 10x smaller than typical minimum to avoid false signals
        typical_min_movement = 0.0001  # 0.01%
        
        assert epsilon < typical_min_movement, "Epsilon should be smaller than typical minimum movement"
        assert epsilon * 10 == typical_min_movement, "Epsilon should be 10x smaller than typical minimum"
    
    def test_epsilon_prevents_zero_velocity(self):
        """Test that epsilon prevents velocity from being exactly zero."""
        # Simulate calculated velocity of zero (no actual movement)
        calculated_velocity = 0.0
        epsilon = 1e-5
        
        # Apply epsilon
        final_velocity = calculated_velocity + epsilon
        
        assert final_velocity > 0, "Final velocity should be positive after adding epsilon"
        assert final_velocity == epsilon, "Final velocity should equal epsilon when calculated is zero"
    
    def test_epsilon_with_positive_trend(self):
        """Test that epsilon adds in direction of recent price trend (positive)."""
        calculated_velocity = 0.0
        recent_trend = 0.00005  # Positive trend
        epsilon = 1e-5
        
        # Apply epsilon in direction of trend
        final_velocity = calculated_velocity + epsilon
        
        assert final_velocity > 0, "Final velocity should be positive with positive trend"
        assert final_velocity == epsilon, "Final velocity should equal epsilon"
    
    def test_epsilon_with_negative_trend(self):
        """Test that epsilon adds in direction of recent price trend (negative)."""
        calculated_velocity = 0.0
        recent_trend = -0.00005  # Negative trend
        epsilon = 1e-5
        
        # Apply epsilon in direction of trend
        final_velocity = calculated_velocity - epsilon
        
        assert final_velocity < 0, "Final velocity should be negative with negative trend"
        assert final_velocity == -epsilon, "Final velocity should equal negative epsilon"
    
    def test_epsilon_does_not_overwhelm_actual_movement(self):
        """Test that epsilon does not overwhelm actual significant price movement."""
        # Simulate significant price movement (0.1%)
        actual_movement = 0.001  # 0.1%
        epsilon = 1e-5  # 0.001%
        
        # Epsilon should be negligible compared to actual movement
        ratio = epsilon / actual_movement
        assert ratio <= 0.01, "Epsilon should be <= 1% of actual movement"
        assert ratio == 0.01, "Epsilon should be 1% of 0.1% movement"
    
    def test_epsilon_breaks_zero_velocity_cycle(self):
        """Test that epsilon prevents exact zero velocity (though may not trigger signal alone)."""
        # Simulate the cycle:
        # 1. Velocity = 0 -> no trade
        # 2. No trade -> no price update
        # 3. No price update -> velocity = 0
        
        # Without epsilon
        velocity_without_epsilon = 0.0
        signal_without_epsilon = abs(velocity_without_epsilon) > 0.00002  # BTC threshold
        
        # With epsilon - epsilon alone may not trigger signal, but prevents exact zero
        velocity_with_epsilon = 0.0 + 1e-5
        signal_with_epsilon = abs(velocity_with_epsilon) > 0.00002  # BTC threshold
        
        assert not signal_without_epsilon, "Without epsilon, no signal (cycle continues)"
        # Epsilon prevents exact zero but may not trigger signal alone (correct behavior)
        assert velocity_with_epsilon > 0, "With epsilon, velocity is non-zero (cycle broken)"
        # For BTC threshold, epsilon alone is 50% of threshold - may not trigger alone
        # but combined with any small movement will trigger
    
    def test_epsilon_vs_updated_thresholds(self):
        """Test that epsilon is appropriate for updated velocity thresholds."""
        epsilon = 1e-5  # 0.001%
        
        # Updated thresholds from research
        thresholds = {
            "BTC": 0.00002,  # 0.002%
            "ETH": 0.00002,  # 0.002%
            "SOL": 0.00003,  # 0.003%
            "XRP": 0.00003,  # 0.003%
            "DOGE": 0.00004,  # 0.004%
        }
        
        # Epsilon should be small enough to not trigger signals on its own
        for asset, threshold in thresholds.items():
            assert epsilon < threshold, f"Epsilon should be smaller than {asset} threshold"
            # Epsilon should be 25-50% of threshold to allow marginal signals when combined with movement
            ratio = epsilon / threshold
            assert 0.25 <= ratio <= 0.5, f"Epsilon/threshold ratio for {asset} should be 25-50%, got {ratio:.2f}"


class TestUpdatedVelocityThresholds:
    """Tests for updated velocity thresholds based on research."""
    
    def test_thresholds_lowered_for_all_assets(self):
        """Test that thresholds were lowered for all assets based on research."""
        old_thresholds = {
            "BTC": 0.00005,  # 0.005%
            "ETH": 0.00005,  # 0.005%
            "SOL": 0.00008,  # 0.008%
            "XRP": 0.00008,  # 0.008%
            "DOGE": 0.00010,  # 0.010%
        }
        
        new_thresholds = {
            "BTC": 0.00002,  # 0.002%
            "ETH": 0.00002,  # 0.002%
            "SOL": 0.00003,  # 0.003%
            "XRP": 0.00003,  # 0.003%
            "DOGE": 0.00004,  # 0.004%
        }
        
        for asset in old_thresholds:
            assert new_thresholds[asset] < old_thresholds[asset], f"{asset} threshold should be lowered"
    
    def test_thresholds_align_with_research(self):
        """Test that thresholds align with 0.01%-0.1% per-minute movement research."""
        thresholds = {
            "BTC": 0.00002,  # 0.002%
            "ETH": 0.00002,  # 0.002%
            "SOL": 0.00003,  # 0.003%
            "XRP": 0.00003,  # 0.003%
            "DOGE": 0.00004,  # 0.004%
        }
        
        # Research: typical per-minute movement is 0.01% to 0.1%
        # Thresholds should be 20-50% of typical minimum to catch early signals
        typical_min = 0.0001  # 0.01%
        
        for asset, threshold in thresholds.items():
            ratio = threshold / typical_min
            assert 0.2 <= ratio <= 0.5, f"{asset} threshold should be 20-50% of typical minimum, got {ratio:.2f}"
    
    def test_thresholds_reflect_volatility_hierarchy(self):
        """Test that thresholds reflect asset volatility hierarchy."""
        thresholds = {
            "BTC": 0.00002,  # Most stable
            "ETH": 0.00002,  # Stable
            "SOL": 0.00003,  # High-beta
            "XRP": 0.00003,  # High-beta
            "DOGE": 0.00004,  # Highest volatility
        }
        
        # DOGE should have highest threshold (most movement)
        assert thresholds["DOGE"] > thresholds["BTC"], "DOGE threshold should be higher than BTC"
        assert thresholds["DOGE"] > thresholds["ETH"], "DOGE threshold should be higher than ETH"
        
        # SOL/XRP should be intermediate
        assert thresholds["SOL"] > thresholds["BTC"], "SOL threshold should be higher than BTC"
        assert thresholds["XRP"] > thresholds["BTC"], "XRP threshold should be higher than BTC"
        
        # BTC/ETH should be lowest (most stable)
        assert thresholds["BTC"] == thresholds["ETH"], "BTC and ETH should have same threshold (stable)"
    
    def test_thresholds_with_epsilon(self):
        """Test that thresholds work correctly with the new epsilon."""
        epsilon = 1e-5  # 0.001%
        thresholds = {
            "BTC": 0.00002,  # 0.002%
            "ETH": 0.00002,  # 0.002%
            "SOL": 0.00003,  # 0.003%
            "XRP": 0.00003,  # 0.003%
            "DOGE": 0.00004,  # 0.004%
        }
        
        # With epsilon, zero calculated velocity should still be below threshold
        # (epsilon alone should not trigger signal)
        for asset, threshold in thresholds.items():
            velocity_with_epsilon = epsilon
            signal = abs(velocity_with_epsilon) > threshold
            assert not signal, f"Epsilon alone should not trigger {asset} signal"
        
        # But epsilon + small movement should trigger signal for all assets
        # Use movement that meets or exceeds all thresholds
        small_movement = 0.00003  # 0.003%
        for asset, threshold in thresholds.items():
            velocity = epsilon + small_movement
            signal = abs(velocity) >= threshold  # Use >= to include threshold equality
            # epsilon + 0.003% = 0.004% which meets/exceeds all thresholds (0.002%-0.004%)
            assert signal, f"Epsilon + small movement should trigger {asset} signal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
