"""
Comprehensive tests for unified signal terminology.

Tests the new signal_terminology.py module to ensure:
1. Velocity-to-side mapping is correct for both strategy modes
2. Signal inversion bugs are prevented
3. Direction bias logic is consistent
4. All enums and data structures work correctly
5. Integration with existing code is backward compatible
"""

import pytest
from datetime import datetime, timezone
from merid.prediction.signal_terminology import (
    Direction, Momentum, Velocity, Side, Action, StrategyMode,
    TradingSignal, SignalMetadata, normalize_direction, normalize_side, normalize_action
)


class TestDirectionEnum:
    """Test Direction enum for trend bias."""
    
    def test_direction_values(self):
        """Test all direction values are defined."""
        assert Direction.BULLISH == "bullish"
        assert Direction.BEARISH == "bearish"
        assert Direction.NEUTRAL == "neutral"
    
    def test_direction_string_comparison(self):
        """Test Direction enum can be compared to strings."""
        assert Direction.BULLISH == "bullish"
        assert "bearish" == Direction.BEARISH


class TestMomentumEnum:
    """Test Momentum enum for conviction strength."""
    
    def test_momentum_values(self):
        """Test all momentum values are defined."""
        assert Momentum.NONE == "none"
        assert Momentum.WEAK == "weak"
        assert Momentum.MODERATE == "moderate"
        assert Momentum.STRONG == "strong"
        assert Momentum.EXTREME == "extreme"


class TestVelocityClass:
    """Test Velocity class for instantaneous rate of change."""
    
    def test_velocity_creation(self):
        """Test Velocity can be created from float."""
        v = Velocity(0.00015)
        assert v == 0.00015
        assert isinstance(v, float)
    
    def test_velocity_magnitude(self):
        """Test velocity magnitude property."""
        assert Velocity(0.00015).magnitude == 0.00015
        assert Velocity(-0.00015).magnitude == 0.00015
        assert Velocity(0.0).magnitude == 0.0
    
    def test_velocity_sign(self):
        """Test velocity sign property."""
        assert Velocity(0.00015).sign == 1
        assert Velocity(-0.00015).sign == -1
        assert Velocity(0.0).sign == 0


class TestSideEnum:
    """Test Side enum for Kalshi contract sides."""
    
    def test_side_values(self):
        """Test all side values are defined."""
        assert Side.YES == "yes"
        assert Side.NO == "no"
    
    def test_side_string_comparison(self):
        """Test Side enum can be compared to strings."""
        assert Side.YES == "yes"
        assert "no" == Side.NO
    
    def test_side_opposite(self):
        """Test opposite method."""
        assert Side.YES.opposite() == Side.NO
        assert Side.NO.opposite() == Side.YES
    
    def test_side_from_velocity_trend_following(self):
        """Test side selection in trend_following mode."""
        # Positive velocity → YES
        assert Side.from_velocity_and_mode(0.00015, "trend_following") == Side.YES
        # Negative velocity → NO
        assert Side.from_velocity_and_mode(-0.00015, "trend_following") == Side.NO
    
    def test_side_from_velocity_mean_reversion(self):
        """Test side selection in mean_reversion mode (INVERTED)."""
        # Positive velocity → NO (inverted)
        assert Side.from_velocity_and_mode(0.00015, "mean_reversion") == Side.NO
        # Negative velocity → YES (inverted)
        assert Side.from_velocity_and_mode(-0.00015, "mean_reversion") == Side.YES
    
    def test_side_from_velocity_invalid_mode(self):
        """Test invalid strategy mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy_mode"):
            Side.from_velocity_and_mode(0.00015, "invalid_mode")


class TestActionEnum:
    """Test Action enum for order actions."""
    
    def test_action_values(self):
        """Test all action values are defined."""
        assert Action.BUY == "buy"
        assert Action.SELL == "sell"
    
    def test_action_string_comparison(self):
        """Test Action enum can be compared to strings."""
        assert Action.BUY == "buy"
        assert "sell" == Action.SELL
    
    def test_action_from_position_state(self):
        """Test action determination from position state."""
        # No position → BUY
        assert Action.from_position_state(None, Side.YES) == Action.BUY
        # Same side → BUY (adding to position)
        assert Action.from_position_state(Side.YES, Side.YES) == Action.BUY
        # Different side → SELL (closing position)
        assert Action.from_position_state(Side.YES, Side.NO) == Action.SELL


class TestStrategyModeEnum:
    """Test StrategyMode enum for velocity-to-side mapping."""
    
    def test_strategy_mode_values(self):
        """Test all strategy mode values are defined."""
        assert StrategyMode.TREND_FOLLOWING == "trend_following"
        assert StrategyMode.MEAN_REVERSION == "mean_reversion"
    
    def test_strategy_mode_from_regime_bull(self):
        """Test BULL regime uses trend_following."""
        assert StrategyMode.from_regime("BULL", 0.8) == StrategyMode.TREND_FOLLOWING
    
    def test_strategy_mode_from_regime_bear(self):
        """Test BEAR regime uses trend_following."""
        assert StrategyMode.from_regime("BEAR", 0.8) == StrategyMode.TREND_FOLLOWING
    
    def test_strategy_mode_from_regime_choppy_high_confidence(self):
        """Test CHOPPY regime with high confidence uses mean_reversion."""
        assert StrategyMode.from_regime("CHOPPY", 0.8) == StrategyMode.MEAN_REVERSION
    
    def test_strategy_mode_from_regime_choppy_low_confidence(self):
        """Test CHOPPY regime with low confidence uses trend_following (safe default)."""
        assert StrategyMode.from_regime("CHOPPY", 0.5) == StrategyMode.TREND_FOLLOWING


class TestSignalMetadata:
    """Test SignalMetadata dataclass."""
    
    def test_signal_metadata_creation(self):
        """Test SignalMetadata can be created."""
        metadata = SignalMetadata(
            asset="BTC",
            velocity_threshold=0.00015,
            velocity_windows=[10, 30, 60],
            momentum_weights=[0.5, 0.3, 0.2],
            regime="BULL",
            regime_confidence=0.8,
            indicators_used={"rsi": 65.0, "macd": 0.5},
            rationale="Strong bullish momentum"
        )
        assert metadata.asset == "BTC"
        assert metadata.velocity_threshold == 0.00015
    
    def test_signal_metadata_to_dict(self):
        """Test SignalMetadata can be converted to dict."""
        metadata = SignalMetadata(asset="BTC")
        d = metadata.to_dict()
        assert "timestamp" in d
        assert d["asset"] == "BTC"
        assert d["velocity_threshold"] == 0.0


class TestTradingSignal:
    """Test TradingSignal dataclass."""
    
    def test_trading_signal_creation(self):
        """Test TradingSignal can be created."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.YES,
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8,
            edge_pct=0.05
        )
        assert signal.direction == Direction.BULLISH
        assert signal.momentum == Momentum.STRONG
        assert signal.velocity == 0.00015
        assert signal.side == Side.YES
        assert signal.action == Action.BUY
        assert signal.strategy_mode == StrategyMode.TREND_FOLLOWING
    
    def test_trading_signal_to_kalshi_format(self):
        """Test TradingSignal can be converted to Kalshi format."""
        # BUY_YES
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.YES,
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING
        )
        assert signal.to_kalshi_format() == "BUY_YES"
        
        # SELL_YES
        signal.action = Action.SELL
        assert signal.to_kalshi_format() == "SELL_YES"
        
        # BUY_NO
        signal.side = Side.NO
        signal.action = Action.BUY
        assert signal.to_kalshi_format() == "BUY_NO"
        
        # SELL_NO
        signal.action = Action.SELL
        assert signal.to_kalshi_format() == "SELL_NO"
    
    def test_trading_signal_to_dict(self):
        """Test TradingSignal can be converted to dict."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.YES,
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8,
            edge_pct=0.05
        )
        d = signal.to_dict()
        assert d["direction"] == "bullish"
        assert d["momentum"] == "strong"
        assert d["velocity"] == 0.00015
        assert d["side"] == "yes"
        assert d["action"] == "buy"
        assert d["strategy_mode"] == "trend_following"
        assert d["confidence"] == 0.8
        assert d["edge_pct"] == 0.05
        assert d["kalshi_format"] == "BUY_YES"
    
    def test_trading_signal_validate_consistent(self):
        """Test validation passes for consistent signal."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.YES,  # Consistent with trend_following
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8
        )
        assert signal.validate() is True
    
    def test_trading_signal_validate_inconsistent_side(self):
        """Test validation fails for inconsistent side."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.NO,  # INCONSISTENT: positive velocity should be YES in trend_following
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8
        )
        with pytest.raises(ValueError, match="Side inconsistency"):
            signal.validate()
    
    def test_trading_signal_validate_invalid_confidence(self):
        """Test validation fails for invalid confidence."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.YES,
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=1.5  # Invalid: > 1.0
        )
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            signal.validate()
    
    def test_trading_signal_validate_momentum_velocity_mismatch(self):
        """Test validation fails for momentum/velocity mismatch."""
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.NONE,  # No conviction
            velocity=Velocity(0.00015),  # But velocity is non-zero
            side=Side.YES,
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8
        )
        with pytest.raises(ValueError, match="Momentum inconsistency"):
            signal.validate()


class TestSignalInversionPrevention:
    """Test that signal inversion bugs are prevented."""
    
    def test_trend_following_positive_velocity_to_yes(self):
        """Test trend_following: positive velocity → YES."""
        side = Side.from_velocity_and_mode(0.00015, "trend_following")
        assert side == Side.YES, "Positive velocity should map to YES in trend_following"
    
    def test_trend_following_negative_velocity_to_no(self):
        """Test trend_following: negative velocity → NO."""
        side = Side.from_velocity_and_mode(-0.00015, "trend_following")
        assert side == Side.NO, "Negative velocity should map to NO in trend_following"
    
    def test_mean_reversion_positive_velocity_to_no(self):
        """Test mean_reversion: positive velocity → NO (inverted)."""
        side = Side.from_velocity_and_mode(0.00015, "mean_reversion")
        assert side == Side.NO, "Positive velocity should map to NO in mean_reversion (inverted)"
    
    def test_mean_reversion_negative_velocity_to_yes(self):
        """Test mean_reversion: negative velocity → YES (inverted)."""
        side = Side.from_velocity_and_mode(-0.00015, "mean_reversion")
        assert side == Side.YES, "Negative velocity should map to YES in mean_reversion (inverted)"
    
    def test_signal_validation_catches_inversion(self):
        """Test that signal validation catches side inversion."""
        # Create signal with wrong side for velocity/mode combination
        signal = TradingSignal(
            direction=Direction.BULLISH,
            momentum=Momentum.STRONG,
            velocity=Velocity(0.00015),
            side=Side.NO,  # WRONG: should be YES for positive velocity in trend_following
            action=Action.BUY,
            strategy_mode=StrategyMode.TREND_FOLLOWING,
            confidence=0.8
        )
        with pytest.raises(ValueError, match="Side inconsistency"):
            signal.validate()


class TestNormalizationFunctions:
    """Test normalization functions for backward compatibility."""
    
    def test_normalize_direction(self):
        """Test direction normalization."""
        assert normalize_direction("BULLISH") == "bullish"
        assert normalize_direction("bullish") == "bullish"
    
    def test_normalize_side(self):
        """Test side normalization."""
        assert normalize_side("YES") == "yes"
        assert normalize_side("yes") == "yes"
    
    def test_normalize_action(self):
        """Test action normalization."""
        assert normalize_action("BUY") == "buy"
        assert normalize_action("buy") == "buy"


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""
    
    def test_side_enum_string_comparison(self):
        """Test Side enum works with existing string comparisons."""
        side = Side.YES
        assert side == "yes"  # Existing code pattern
        assert side.value == "yes"
    
    def test_action_enum_string_comparison(self):
        """Test Action enum works with existing string comparisons."""
        action = Action.BUY
        assert action == "buy"  # Existing code pattern
        assert action.value == "buy"
    
    def test_velocity_as_float(self):
        """Test Velocity works as float in existing code."""
        velocity = Velocity(0.00015)
        assert velocity * 100 == 0.015  # Float arithmetic works
        assert velocity > 0.0001  # Float comparisons work


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_zero_velocity_trend_following(self):
        """Test zero velocity in trend_following mode."""
        side = Side.from_velocity_and_mode(0.0, "trend_following")
        # Zero velocity → NO (negative branch)
        assert side == Side.NO
    
    def test_zero_velocity_mean_reversion(self):
        """Test zero velocity in mean_reversion mode."""
        side = Side.from_velocity_and_mode(0.0, "mean_reversion")
        # Zero velocity → YES (negative branch, inverted)
        assert side == Side.YES
    
    def test_very_small_velocity(self):
        """Test very small velocity values."""
        side = Side.from_velocity_and_mode(0.000001, "trend_following")
        assert side == Side.YES
    
    def test_very_large_velocity(self):
        """Test very large velocity values."""
        side = Side.from_velocity_and_mode(0.01, "trend_following")
        assert side == Side.YES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
