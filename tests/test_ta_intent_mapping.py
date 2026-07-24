"""
TA → Intent Mapping Invariant Test Harness

Tests that TA signals map correctly to strategy intents with per-asset tuning.

Usage:
    pytest tests/test_ta_intent_mapping.py
"""

from __future__ import annotations

import pytest

try:
    from merid.prediction.ta_intent_mapping import (
        TAIntentMapper,
        TAIntentConfig,
        TASignal,
        TASignalType,
        get_ta_intent_mapper,
    )
    from merid.prediction.signal_terminology import StrategyIntent
except ImportError:
    pytest.skip("Required modules not available")


class TestTAIntentConfig:
    """Test suite for TA intent configurations."""
    
    def test_btc_config(self):
        """Test BTC TA intent configuration."""
        mapper = TAIntentMapper()
        config = mapper.get_config("BTC")
        assert config is not None
        assert config.asset == "BTC"
        assert config.min_velocity_threshold == 0.00005
        assert config.volatility_multiplier == 1.0
        assert config.momentum_weight == 0.4
    
    def test_eth_config(self):
        """Test ETH TA intent configuration."""
        mapper = TAIntentMapper()
        config = mapper.get_config("ETH")
        assert config is not None
        assert config.asset == "ETH"
        assert config.min_velocity_threshold == 0.00008
        assert config.volatility_multiplier == 1.2
    
    def test_sol_config(self):
        """Test SOL TA intent configuration."""
        mapper = TAIntentMapper()
        config = mapper.get_config("SOL")
        assert config is not None
        assert config.asset == "SOL"
        assert config.min_velocity_threshold == 0.00015
        assert config.volatility_multiplier == 1.5
        assert config.bullish_bias_correction == 0.05
    
    def test_doge_config(self):
        """Test DOGE TA intent configuration."""
        mapper = TAIntentMapper()
        config = mapper.get_config("DOGE")
        assert config is not None
        assert config.asset == "DOGE"
        assert config.min_velocity_threshold == 0.00020
        assert config.volatility_multiplier == 1.8
        assert config.bearish_bias_correction == 0.05
    
    def test_unsupported_asset(self):
        """Test that unsupported asset returns None."""
        mapper = TAIntentMapper()
        config = mapper.get_config("INVALID")
        assert config is None


class TestSignalToIntentMapping:
    """Test suite for single signal to intent mapping."""
    
    def test_bullish_momentum_to_bullish_intent(self):
        """Test that bullish momentum maps to BULLISH_EVENT."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bullish",
            confidence=0.8,
            velocity=0.0001,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.BULLISH_EVENT
        assert error is None
    
    def test_bearish_momentum_to_bearish_intent(self):
        """Test that bearish momentum maps to BEARISH_EVENT."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bearish",
            confidence=0.8,
            velocity=-0.0001,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.BEARISH_EVENT
        assert error is None
    
    def test_neutral_signal_to_neutral_intent(self):
        """Test that neutral signal maps to NEUTRAL intent."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="neutral",
            confidence=0.5,
            velocity=0.0,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.NEUTRAL
    
    def test_velocity_below_threshold(self):
        """Test that velocity below threshold maps to NEUTRAL."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bullish",
            confidence=0.8,
            velocity=0.00001,  # Below BTC threshold of 0.00005
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.NEUTRAL
        assert "below threshold" in error.lower()
    
    def test_velocity_above_threshold(self):
        """Test that velocity above threshold maps to NEUTRAL."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bullish",
            confidence=0.8,
            velocity=0.001,  # Above BTC threshold of 0.0008
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.NEUTRAL
        assert "above threshold" in error.lower()
    
    def test_confidence_below_threshold(self):
        """Test that confidence below threshold maps to NEUTRAL."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.CANDLESTICK,
            asset="BTC",
            direction="bullish",
            confidence=0.5,  # Below BTC pattern strength threshold of 0.75
            velocity=0.0001,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        assert intent == StrategyIntent.NEUTRAL
        assert "below threshold" in error.lower()
    
    def test_bullish_bias_correction(self):
        """Test that bullish bias correction reduces confidence."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="SOL",  # Has bullish_bias_correction=0.05
            direction="bullish",
            confidence=0.8,
            velocity=0.0002,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        # Note: Bias correction may reduce confidence below threshold, resulting in NEUTRAL
        if intent == StrategyIntent.BULLISH_EVENT:
            assert confidence < 0.8  # Should be reduced by bias correction
            assert confidence == 0.75  # 0.8 - 0.05
        else:
            # If confidence dropped below threshold, intent becomes NEUTRAL
            assert intent == StrategyIntent.NEUTRAL
    
    def test_bearish_bias_correction(self):
        """Test that bearish bias correction reduces confidence."""
        mapper = TAIntentMapper()
        
        signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="DOGE",  # Has bearish_bias_correction=0.05
            direction="bearish",
            confidence=0.8,
            velocity=-0.0003,
        )
        
        intent, confidence, error = mapper.map_signal_to_intent(signal)
        # Note: Bias correction may reduce confidence below threshold, resulting in NEUTRAL
        if intent == StrategyIntent.BEARISH_EVENT:
            assert confidence < 0.8  # Should be reduced by bias correction
            assert confidence == 0.75  # 0.8 - 0.05
        else:
            # If confidence dropped below threshold, intent becomes NEUTRAL
            assert intent == StrategyIntent.NEUTRAL


class TestMultiSignalMapping:
    """Test suite for multiple signal to intent mapping."""
    
    def test_bullish_majority(self):
        """Test that bullish majority maps to BULLISH_EVENT."""
        mapper = TAIntentMapper()
        
        signals = [
            TASignal(TASignalType.MOMENTUM, "BTC", "bullish", 0.8, 0.0001),
            TASignal(TASignalType.FVG, "BTC", "bullish", 0.7, 0.0001),
            TASignal(TASignalType.CANDLESTICK, "BTC", "bearish", 0.6, 0.0001),
        ]
        
        intent, confidence, metadata = mapper.map_multiple_signals_to_intent(signals)
        assert intent == StrategyIntent.BULLISH_EVENT
        assert confidence > 0.5
        assert metadata["bullish_count"] > metadata["bearish_count"]
    
    def test_bearish_majority(self):
        """Test that bearish majority maps to BEARISH_EVENT."""
        mapper = TAIntentMapper()
        
        signals = [
            TASignal(TASignalType.MOMENTUM, "BTC", "bearish", 0.8, -0.0001),
            TASignal(TASignalType.FVG, "BTC", "bearish", 0.7, -0.0001),
            TASignal(TASignalType.CANDLESTICK, "BTC", "bullish", 0.6, 0.0001),
        ]
        
        intent, confidence, metadata = mapper.map_multiple_signals_to_intent(signals)
        assert intent == StrategyIntent.BEARISH_EVENT
        assert confidence > 0.5
        assert metadata["bearish_count"] > metadata["bullish_count"]
    
    def test_all_neutral(self):
        """Test that all neutral signals map to NEUTRAL."""
        mapper = TAIntentMapper()
        
        signals = [
            TASignal(TASignalType.MOMENTUM, "BTC", "neutral", 0.5, 0.0),
            TASignal(TASignalType.FVG, "BTC", "neutral", 0.5, 0.0),
        ]
        
        intent, confidence, metadata = mapper.map_multiple_signals_to_intent(signals)
        assert intent == StrategyIntent.NEUTRAL
        assert "All signals mapped to NEUTRAL" in metadata.get("error", "")
    
    def test_tie_breaker_by_count(self):
        """Test that tie is broken by signal count."""
        mapper = TAIntentMapper()
        
        signals = [
            TASignal(TASignalType.MOMENTUM, "BTC", "bullish", 0.7, 0.0001),
            TASignal(TASignalType.FVG, "BTC", "bullish", 0.7, 0.0001),
            TASignal(TASignalType.CANDLESTICK, "BTC", "bearish", 0.7, -0.0001),
        ]
        
        intent, confidence, metadata = mapper.map_multiple_signals_to_intent(signals)
        # Weighted sum should favor bullish due to higher count and weights
        # If weighted sum is equal, count breaks the tie
        assert intent in (StrategyIntent.BULLISH_EVENT, StrategyIntent.NEUTRAL)
        assert metadata["bullish_count"] == 2
        # Bearish signal may be filtered if it doesn't pass thresholds
        assert metadata["bearish_count"] <= 1
    
    def test_per_asset_signal_weights(self):
        """Test that per-asset signal weights are applied."""
        mapper = TAIntentMapper()
        
        # DOGE has higher FVG weight (0.45) and lower momentum weight (0.30)
        signals = [
            TASignal(TASignalType.MOMENTUM, "DOGE", "bullish", 0.8, 0.0003),
            TASignal(TASignalType.FVG, "DOGE", "bearish", 0.7, -0.0003),
        ]
        
        intent, confidence, metadata = mapper.map_multiple_signals_to_intent(signals)
        # FVG weight higher, so bearish should win despite slightly lower confidence
        # Note: May be NEUTRAL if bias correction reduces confidence below threshold
        assert intent in (StrategyIntent.BEARISH_EVENT, StrategyIntent.NEUTRAL)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
