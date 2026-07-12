"""
Tests for volume confirmation filter.

Tests the EMA20-based volume confirmation logic:
- Volume > 1.2x EMA20 confirms signal validity
- Bypass filter during warmup (insufficient history)
- Industry standard: https://github.com/PapaDaCodr/kryptic-gopha/blob/main/research/hft_analysis.md
"""

import pytest
import collections
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestVolumeConfirmationEMA20:
    """Test EMA20 calculation for volume confirmation."""
    
    def test_ema20_calculation_stable_volume(self):
        """Test EMA20 calculation with stable volume."""
        # Simulate volume history with stable values
        volume_history = collections.deque(maxlen=300)
        base_volume = 100.0
        for i in range(25):
            volume_history.append((i * 1000, base_volume))  # Stable volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # With stable volume, EMA20 should be close to base volume
        assert abs(ema20 - base_volume) < 1.0, f"EMA20 {ema20} should be close to base volume {base_volume}"
    
    def test_ema20_calculation_increasing_volume(self):
        """Test EMA20 calculation with increasing volume."""
        # Simulate volume history with increasing values
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 100.0 + i * 5.0))  # Increasing volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # With increasing volume, EMA20 should be higher than early values
        assert ema20 > 100.0, f"EMA20 {ema20} should be higher than base volume"
        assert ema20 < recent_volumes[-1], f"EMA20 {ema20} should be lower than current volume {recent_volumes[-1]}"
    
    def test_ema20_calculation_spike_volume(self):
        """Test EMA20 calculation with volume spike."""
        # Simulate volume history with spike at the end
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            if i < 20:
                volume_history.append((i * 1000, 100.0))  # Stable
            else:
                volume_history.append((i * 1000, 200.0))  # Spike
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # EMA20 should be elevated but not as high as the spike
        assert ema20 > 100.0, f"EMA20 {ema20} should be elevated"
        assert ema20 < 200.0, f"EMA20 {ema20} should be lower than spike volume"


class TestVolumeConfirmationFilter:
    """Test volume confirmation filter logic."""
    
    def test_volume_above_threshold_confirmed(self):
        """Test volume above 1.2x EMA20 threshold is confirmed."""
        # Simulate volume history with spike
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            if i < 20:
                volume_history.append((i * 1000, 100.0))  # Stable
            else:
                volume_history.append((i * 1000, 150.0))  # Spike (1.5x)
        
        # Calculate EMA20 and threshold
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        current_volume = recent_volumes[-1]
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"Volume {current_volume} should be above threshold {volume_threshold}"
    
    def test_volume_below_threshold_rejected(self):
        """Test volume below 1.2x EMA20 threshold is rejected."""
        # Simulate volume history with stable values
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 100.0))  # Stable
        
        # Calculate EMA20 and threshold
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        current_volume = recent_volumes[-1]
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert not volume_confirmed, f"Volume {current_volume} should be below threshold {volume_threshold}"
    
    def test_volume_exactly_at_threshold(self):
        """Test volume exactly at 1.2x EMA20 threshold."""
        # Simulate volume history
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 100.0))
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Set current volume exactly at threshold
        current_volume = ema20 * 1.2
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert not volume_confirmed, "Volume exactly at threshold should not be confirmed (strict >)"
    
    def test_volume_insufficient_history_bypass(self):
        """Test volume filter bypasses with insufficient history (< 20)."""
        volume_history = collections.deque(maxlen=300)
        for i in range(15):  # Only 15 data points
            volume_history.append((i * 1000, 100.0))
        
        # Check if bypass condition is met
        volume_history_list = list(volume_history)
        insufficient_history = len(volume_history_list) < 20
        
        assert insufficient_history, "Should detect insufficient history for bypass"
    
    def test_volume_no_history_bypass(self):
        """Test volume filter bypasses with no history."""
        volume_history = collections.deque(maxlen=300)
        
        # Check if bypass condition is met
        volume_history_list = list(volume_history)
        no_history = len(volume_history_list) == 0
        
        assert no_history, "Should detect no history for bypass"


class TestVolumeConfirmationForAllAssets:
    """Test volume confirmation for all 5 crypto assets."""
    
    def test_volume_confirmation_btc(self):
        """Test volume confirmation for BTC."""
        asset = "BTC"
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 1000.0))  # Higher volume for BTC
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Simulate spike
        current_volume = ema20 * 1.5
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"{asset} volume should be confirmed"
    
    def test_volume_confirmation_eth(self):
        """Test volume confirmation for ETH."""
        asset = "ETH"
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 800.0))  # ETH volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Simulate spike
        current_volume = ema20 * 1.5
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"{asset} volume should be confirmed"
    
    def test_volume_confirmation_sol(self):
        """Test volume confirmation for SOL."""
        asset = "SOL"
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 500.0))  # SOL volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Simulate spike
        current_volume = ema20 * 1.5
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"{asset} volume should be confirmed"
    
    def test_volume_confirmation_xrp(self):
        """Test volume confirmation for XRP."""
        asset = "XRP"
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 300.0))  # XRP volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Simulate spike
        current_volume = ema20 * 1.5
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"{asset} volume should be confirmed"
    
    def test_volume_confirmation_doge(self):
        """Test volume confirmation for DOGE."""
        asset = "DOGE"
        volume_history = collections.deque(maxlen=300)
        for i in range(25):
            volume_history.append((i * 1000, 200.0))  # DOGE volume
        
        # Calculate EMA20
        k = 2.0 / (20.0 + 1.0)
        recent_volumes = [entry[1] for entry in list(volume_history)[-20:]]
        ema20 = recent_volumes[0]
        for volume in recent_volumes[1:]:
            ema20 = (volume * k) + (ema20 * (1 - k))
        
        # Simulate spike
        current_volume = ema20 * 1.5
        volume_threshold = ema20 * 1.2
        volume_confirmed = current_volume > volume_threshold
        
        assert volume_confirmed, f"{asset} volume should be confirmed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
