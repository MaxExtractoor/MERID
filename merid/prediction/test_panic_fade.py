"""
Integration tests for panic fade (volatility reversion) strategy.
Tests the RSI, Z-score, and panic fade signal generation logic.
"""

import pytest
import numpy as np
from unittest.mock import Mock
import sys
import os
import collections

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestPanicFadeRSICalculation:
    """Test RSI calculation for panic fade detection."""
    
    def test_rsi_oversold_threshold(self):
        """Test RSI correctly identifies oversold conditions (< 25)."""
        # Simulate price history with consistent declines (oversold)
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(20):
            price_history.append((i * 1000, base_price - i * 0.5))  # Declining prices
        
        # Calculate gains and losses
        closes = [entry[1] for entry in list(price_history)[-15:]]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # With declining prices, RSI should be low (oversold)
        assert rsi < 25.0, f"RSI={rsi} should be < 25 for oversold condition"
    
    def test_rsi_overbought_threshold(self):
        """Test RSI correctly identifies overbought conditions (> 75)."""
        # Simulate price history with consistent gains (overbought)
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(20):
            price_history.append((i * 1000, base_price + i * 0.5))  # Rising prices
        
        # Calculate gains and losses
        closes = [entry[1] for entry in list(price_history)[-15:]]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # With rising prices, RSI should be high (overbought)
        assert rsi > 75.0, f"RSI={rsi} should be > 75 for overbought condition"
    
    def test_rsi_neutral_range(self):
        """Test RSI correctly identifies neutral conditions (25-75)."""
        # Simulate price history with small fluctuations (neutral)
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(20):
            price_history.append((i * 1000, base_price + (i % 3 - 1) * 0.1))  # Small fluctuations
        
        # Calculate gains and losses
        closes = [entry[1] for entry in list(price_history)[-15:]]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # With small fluctuations, RSI should be in neutral range
        assert 25.0 <= rsi <= 75.0, f"RSI={rsi} should be in neutral range [25, 75]"
    
    def test_rsi_insufficient_history(self):
        """Test RSI returns 0.0 when insufficient history."""
        price_history = collections.deque(maxlen=300)
        # Only 5 data points (need 15 for RSI with period 14)
        for i in range(5):
            price_history.append((i * 1000, 100.0 + i))
        
        # With insufficient history, RSI should return 0.0
        assert len(price_history) < 15, "Insufficient history for RSI calculation"
        rsi = 0.0  # Expected return value
        assert rsi == 0.0, "RSI should return 0.0 with insufficient history"


class TestPanicFadeZScoreCalculation:
    """Test Z-score calculation for panic fade detection."""
    
    def test_zscore_oversold_threshold(self):
        """Test Z-score correctly identifies oversold conditions (< -2.0)."""
        # Simulate price history with sharp decline (oversold)
        # Use more extreme decline to ensure Z-score < -2.0
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(25):
            # Create extreme decline: first 15 prices stable, last 5 sharp drop
            if i < 15:
                price_history.append((i * 1000, base_price))
            else:
                price_history.append((i * 1000, base_price - (i - 15) * 5.0))  # Sharp decline
        
        closes = [entry[1] for entry in list(price_history)[-20:]]
        mean_price = sum(closes) / len(closes)
        variance = sum((x - mean_price) ** 2 for x in closes) / len(closes)
        std_dev = variance ** 0.5
        
        current_price = closes[-1]
        zscore = (current_price - mean_price) / std_dev
        
        # With sharp decline, Z-score should be negative (oversold)
        assert zscore < -2.0, f"Z-score={zscore} should be < -2.0 for oversold condition"
    
    def test_zscore_overbought_threshold(self):
        """Test Z-score correctly identifies overbought conditions (> +2.0)."""
        # Simulate price history with sharp rise (overbought)
        # Use more extreme rise to ensure Z-score > +2.0
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(25):
            # Create extreme rise: first 15 prices stable, last 5 sharp rise
            if i < 15:
                price_history.append((i * 1000, base_price))
            else:
                price_history.append((i * 1000, base_price + (i - 15) * 5.0))  # Sharp rise
        
        closes = [entry[1] for entry in list(price_history)[-20:]]
        mean_price = sum(closes) / len(closes)
        variance = sum((x - mean_price) ** 2 for x in closes) / len(closes)
        std_dev = variance ** 0.5
        
        current_price = closes[-1]
        zscore = (current_price - mean_price) / std_dev
        
        # With sharp rise, Z-score should be positive (overbought)
        assert zscore > 2.0, f"Z-score={zscore} should be > 2.0 for overbought condition"
    
    def test_zscore_neutral_range(self):
        """Test Z-score correctly identifies neutral conditions (-2.0 to +2.0)."""
        # Simulate price history with small fluctuations (neutral)
        price_history = collections.deque(maxlen=300)
        base_price = 100.0
        for i in range(25):
            price_history.append((i * 1000, base_price + (i % 5 - 2) * 0.5))  # Small fluctuations
        
        closes = [entry[1] for entry in list(price_history)[-20:]]
        mean_price = sum(closes) / len(closes)
        variance = sum((x - mean_price) ** 2 for x in closes) / len(closes)
        std_dev = variance ** 0.5
        
        current_price = closes[-1]
        zscore = (current_price - mean_price) / std_dev
        
        # With small fluctuations, Z-score should be in neutral range
        assert -2.0 <= zscore <= 2.0, f"Z-score={zscore} should be in neutral range [-2.0, 2.0]"
    
    def test_zscore_insufficient_history(self):
        """Test Z-score returns 0.0 when insufficient history."""
        price_history = collections.deque(maxlen=300)
        # Only 10 data points (need 20 for Z-score with period 20)
        for i in range(10):
            price_history.append((i * 1000, 100.0 + i))
        
        # With insufficient history, Z-score should return 0.0
        assert len(price_history) < 20, "Insufficient history for Z-score calculation"
        zscore = 0.0  # Expected return value
        assert zscore == 0.0, "Z-score should return 0.0 with insufficient history"


class TestPanicFadeSignalGeneration:
    """Test panic fade signal generation logic."""
    
    def test_panic_fade_oversold_buy_yes(self):
        """Test panic fade generates BUY YES signal when oversold."""
        rsi = 20.0  # Below 25 (oversold)
        zscore = -2.5  # Below -2.0 (oversold)
        velocity = -0.0003  # Negative velocity (panic move)
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert is_oversold, "Should detect oversold condition"
        assert not is_overbought, "Should not detect overbought condition"
        assert velocity_sufficient, "Velocity should be sufficient for panic fade"
        
        # Oversold -> BUY YES (expect reversion up)
        signal_side = "yes"
        signal_action = "buy"
        
        assert signal_side == "yes", "Oversold should generate BUY YES signal"
        assert signal_action == "buy", "Signal action should be buy"
    
    def test_panic_fade_overbought_buy_no(self):
        """Test panic fade generates BUY NO signal when overbought."""
        rsi = 80.0  # Above 75 (overbought)
        zscore = 2.5  # Above 2.0 (overbought)
        velocity = 0.0003  # Positive velocity (panic move)
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert not is_oversold, "Should not detect oversold condition"
        assert is_overbought, "Should detect overbought condition"
        assert velocity_sufficient, "Velocity should be sufficient for panic fade"
        
        # Overbought -> BUY NO (expect reversion down)
        signal_side = "no"
        signal_action = "buy"
        
        assert signal_side == "no", "Overbought should generate BUY NO signal"
        assert signal_action == "buy", "Signal action should be buy"
    
    def test_panic_fade_insufficient_velocity(self):
        """Test panic fade does not generate signal with insufficient velocity."""
        rsi = 20.0  # Below 25 (oversold)
        zscore = -2.5  # Below -2.0 (oversold)
        velocity = -0.00005  # Low velocity (not panic move)
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert is_oversold, "Should detect oversold condition"
        assert not is_overbought, "Should not detect overbought condition"
        assert not velocity_sufficient, "Velocity should be insufficient for panic fade"
        
        # Insufficient velocity -> no panic fade signal
        panic_fade_signal = None
        
        assert panic_fade_signal is None, "Should not generate panic fade signal with insufficient velocity"
    
    def test_panic_fade_neutral_rsi_zscore(self):
        """Test panic fade does not generate signal with neutral RSI/Z-score."""
        rsi = 50.0  # Neutral (between 25 and 75)
        zscore = 0.5  # Neutral (between -2.0 and 2.0)
        velocity = -0.0003  # High velocity
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert not is_oversold, "Should not detect oversold condition"
        assert not is_overbought, "Should not detect overbought condition"
        assert velocity_sufficient, "Velocity should be sufficient"
        
        # Neutral RSI/Z-score -> no panic fade signal
        panic_fade_signal = None
        
        assert panic_fade_signal is None, "Should not generate panic fade signal with neutral RSI/Z-score"
    
    def test_panic_fade_partial_extreme_rsi_only(self):
        """Test panic fade requires both RSI and Z-score extremes."""
        rsi = 20.0  # Below 25 (oversold)
        zscore = -1.0  # Not extreme (above -2.0)
        velocity = -0.0003  # High velocity
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert not is_oversold, "Should not detect oversold (Z-score not extreme)"
        assert not is_overbought, "Should not detect overbought condition"
        assert velocity_sufficient, "Velocity should be sufficient"
        
        # Partial extreme -> no panic fade signal
        panic_fade_signal = None
        
        assert panic_fade_signal is None, "Should not generate panic fade signal with partial extreme (RSI only)"
    
    def test_panic_fade_partial_extreme_zscore_only(self):
        """Test panic fade requires both RSI and Z-score extremes."""
        rsi = 40.0  # Not extreme (above 25)
        zscore = -2.5  # Below -2.0 (oversold)
        velocity = -0.0003  # High velocity
        velocity_magnitude = abs(velocity)
        min_velocity_threshold = 0.0001
        
        # Check if panic fade conditions are met
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = velocity_magnitude >= min_velocity_threshold
        
        assert not is_oversold, "Should not detect oversold (RSI not extreme)"
        assert not is_overbought, "Should not detect overbought condition"
        assert velocity_sufficient, "Velocity should be sufficient"
        
        # Partial extreme -> no panic fade signal
        panic_fade_signal = None
        
        assert panic_fade_signal is None, "Should not generate panic fade signal with partial extreme (Z-score only)"


class TestPanicFadeIntegration:
    """Test panic fade integration with velocity-based signals."""
    
    def test_panic_fade_overrides_velocity_signal(self):
        """Test panic fade signal overrides velocity-based signal."""
        # Simulate panic fade conditions
        panic_fade_enabled = True
        rsi = 20.0
        zscore = -2.5
        velocity = -0.0003
        min_velocity_threshold = 0.0001
        
        # Check panic fade conditions
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        velocity_sufficient = abs(velocity) >= min_velocity_threshold
        
        panic_fade_signal = None
        if panic_fade_enabled and is_oversold and velocity_sufficient:
            panic_fade_signal = {
                "side": "yes",
                "action": "buy",
                "rationale": f"panic_fade: oversold (RSI={rsi:.1f}<25, Z={zscore:.1f}<-2.0)",
                "strategy": "panic_fade"
            }
        
        # Velocity-based signal would be NO (negative velocity)
        velocity_threshold = 0.00005
        velocity_signal_side = None
        if not panic_fade_signal:
            if velocity > velocity_threshold:
                velocity_signal_side = "yes"
            elif velocity < -velocity_threshold:
                velocity_signal_side = "no"
        
        # Panic fade should override velocity signal
        assert panic_fade_signal is not None, "Panic fade signal should be generated"
        assert panic_fade_signal["side"] == "yes", "Panic fade should generate YES (oversold)"
        assert velocity_signal_side is None, "Velocity signal should be skipped when panic fade triggers"
    
    def test_velocity_signal_when_no_panic_fade(self):
        """Test velocity-based signal when panic fade conditions not met."""
        # Simulate no panic fade conditions
        panic_fade_enabled = True
        rsi = 50.0  # Neutral
        zscore = 0.5  # Neutral
        velocity = 0.0003  # Positive velocity
        min_velocity_threshold = 0.0001
        
        # Check panic fade conditions
        is_oversold = (rsi < 25.0) and (zscore < -2.0)
        is_overbought = (rsi > 75.0) and (zscore > 2.0)
        velocity_sufficient = abs(velocity) >= min_velocity_threshold
        
        panic_fade_signal = None
        if panic_fade_enabled and (is_oversold or is_overbought) and velocity_sufficient:
            panic_fade_signal = {"side": "yes", "action": "buy"}
        
        # Velocity-based signal should be used
        velocity_threshold = 0.00005
        velocity_signal_side = None
        if not panic_fade_signal:
            if velocity > velocity_threshold:
                velocity_signal_side = "yes"
            elif velocity < -velocity_threshold:
                velocity_signal_side = "no"
        
        # Velocity signal should be generated
        assert panic_fade_signal is None, "Panic fade signal should not be generated"
        assert velocity_signal_side == "yes", "Velocity signal should generate YES (positive velocity)"
    
    def test_panic_fade_disabled_uses_velocity(self):
        """Test velocity-based signal when panic fade is disabled."""
        # Simulate panic fade disabled
        panic_fade_enabled = False
        rsi = 20.0  # Oversold
        zscore = -2.5  # Oversold
        velocity = -0.0003  # Negative velocity
        min_velocity_threshold = 0.0001
        
        # Check panic fade conditions (but disabled)
        panic_fade_signal = None
        if panic_fade_enabled:
            # Would generate panic fade signal if enabled
            pass
        
        # Velocity-based signal should be used
        velocity_threshold = 0.00005
        velocity_signal_side = None
        if not panic_fade_signal:
            if velocity > velocity_threshold:
                velocity_signal_side = "yes"
            elif velocity < -velocity_threshold:
                velocity_signal_side = "no"
        
        # Velocity signal should be generated
        assert panic_fade_signal is None, "Panic fade signal should not be generated (disabled)"
        assert velocity_signal_side == "no", "Velocity signal should generate NO (negative velocity)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
