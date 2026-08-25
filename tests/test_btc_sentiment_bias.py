"""Tests for BTC sentiment bias implementation."""

import pytest
from unittest.mock import Mock, patch
import time


class TestSentimentBiasConfig:
    """Test sentiment bias configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        from merid.prediction.btc_sentiment_bias import SentimentBiasConfig
        
        config = SentimentBiasConfig()
        assert config.enabled is False
        assert config.btc_sentiment_threshold == 0.7
        assert config.bias_strength == 0.05
        assert config.correlated_assets == ["ETH", "SOL", "XRP", "DOGE"]
        assert config.correlation_threshold == 0.8
        assert config.sentiment_window_seconds == 300
    
    def test_custom_config(self):
        """Test custom configuration values."""
        from merid.prediction.btc_sentiment_bias import SentimentBiasConfig
        
        config = SentimentBiasConfig(
            enabled=True,
            btc_sentiment_threshold=0.8,
            bias_strength=0.10,
            correlated_assets=["ETH", "SOL"],
            correlation_threshold=0.9,
            sentiment_window_seconds=600
        )
        
        assert config.enabled is True
        assert config.btc_sentiment_threshold == 0.8
        assert config.bias_strength == 0.10
        assert config.correlated_assets == ["ETH", "SOL"]
        assert config.correlation_threshold == 0.9
        assert config.sentiment_window_seconds == 600


class TestBTCSentimentBias:
    """Test BTC sentiment bias calculator."""
    
    @pytest.fixture
    def enabled_config(self):
        """Create enabled sentiment bias configuration."""
        from merid.prediction.btc_sentiment_bias import SentimentBiasConfig
        return SentimentBiasConfig(enabled=True)
    
    @pytest.fixture
    def disabled_config(self):
        """Create disabled sentiment bias configuration."""
        from merid.prediction.btc_sentiment_bias import SentimentBiasConfig
        return SentimentBiasConfig(enabled=False)
    
    def test_initialization_disabled(self, disabled_config):
        """Test initialization with disabled config."""
        from merid.prediction.btc_sentiment_bias import BTCSentimentBias
        
        bias = BTCSentimentBias(disabled_config)
        assert bias.config.enabled is False
    
    def test_initialization_enabled(self, enabled_config):
        """Test initialization with enabled config."""
        from merid.prediction.btc_sentiment_bias import BTCSentimentBias
        
        bias = BTCSentimentBias(enabled_config)
        assert bias.config.enabled is True
        assert bias._correlation_matrix == {
            "ETH": 0.85,
            "SOL": 0.80,
            "XRP": 0.75,
            "DOGE": 0.70
        }
    
    def test_update_btc_sentiment(self, enabled_config):
        """Test updating BTC sentiment signal."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.STRONG_BULLISH,
            confidence=0.85,
            source="internal"
        )
        
        bias.update_btc_sentiment(sentiment)
        
        assert bias._btc_sentiment is not None
        assert bias._btc_sentiment.direction == SentimentDirection.STRONG_BULLISH
        assert bias._btc_sentiment.confidence == 0.85
    
    def test_get_bias_adjustment_strong_bullish(self, enabled_config):
        """Test bias adjustment for strong bullish BTC sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set strong bullish sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.STRONG_BULLISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        # Get bias for ETH (highly correlated)
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be positive (bias in same direction as YES)
        assert adjustment > 0
        # Bias = strength * confidence * correlation = 0.05 * 0.9 * 0.85 = 0.03825
        expected = 0.05 * 0.9 * 0.85
        assert abs(adjustment - expected) < 0.001
    
    def test_get_bias_adjustment_strong_bearish(self, enabled_config):
        """Test bias adjustment for strong bearish BTC sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set strong bearish sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.STRONG_BEARISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        # Get bias for ETH with NO side
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="no"
        )
        
        # Should be positive (bias in same direction as NO)
        assert adjustment > 0
    
    def test_get_bias_adjustment_opposite_side(self, enabled_config):
        """Test bias adjustment when current side opposes sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set strong bullish sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.STRONG_BULLISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        # Get bias for ETH with NO side (opposes bullish sentiment)
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="no"
        )
        
        # Should be negative (bias against current side)
        assert adjustment < 0
    
    def test_get_bias_adjustment_no_sentiment(self, enabled_config):
        """Test bias adjustment when no BTC sentiment available."""
        from merid.prediction.btc_sentiment_bias import BTCSentimentBias
        
        bias = BTCSentimentBias(enabled_config)
        
        # No sentiment set
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be zero
        assert adjustment == 0.0
    
    def test_get_bias_adjustment_low_confidence(self, enabled_config):
        """Test bias adjustment when confidence is below threshold."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set low confidence sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.BULLISH,
            confidence=0.5,  # Below threshold of 0.7
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be zero (confidence below threshold)
        assert adjustment == 0.0
    
    def test_get_bias_adjustment_stale_sentiment(self, enabled_config):
        """Test bias adjustment when sentiment is stale."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set old sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.BULLISH,
            confidence=0.9,
            source="internal"
        )
        sentiment.timestamp = time.time() - 400  # 400s ago (beyond 300s window)
        bias.update_btc_sentiment(sentiment)
        
        adjustment = bias.get_bias_adjustment(
            asset="ETH",
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be zero (sentiment stale)
        assert adjustment == 0.0
    
    def test_get_bias_adjustment_non_correlated_asset(self, enabled_config):
        """Test bias adjustment for non-correlated asset."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set strong bullish sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.BULLISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        # Get bias for asset not in correlated list
        adjustment = bias.get_bias_adjustment(
            asset="AAPL",  # Not a crypto asset
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be zero (not correlated)
        assert adjustment == 0.0
    
    def test_get_bias_adjustment_low_correlation(self, enabled_config):
        """Test bias adjustment when correlation is below threshold."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # Set strong bullish sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.BULLISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        
        # Manually set low correlation for DOGE
        bias._correlation_matrix["DOGE"] = 0.6  # Below threshold of 0.8
        
        adjustment = bias.get_bias_adjustment(
            asset="DOGE",
            base_edge=0.05,
            current_side="yes"
        )
        
        # Should be zero (correlation below threshold)
        assert adjustment == 0.0
    
    def test_is_sentiment_fresh(self, enabled_config):
        """Test sentiment freshness check."""
        from merid.prediction.btc_sentiment_bias import (
            BTCSentimentBias,
            SentimentSignal,
            SentimentDirection
        )
        
        bias = BTCSentimentBias(enabled_config)
        
        # No sentiment
        assert bias.is_sentiment_fresh() is False
        
        # Fresh sentiment
        sentiment = SentimentSignal(
            asset="BTC",
            direction=SentimentDirection.BULLISH,
            confidence=0.9,
            source="internal"
        )
        bias.update_btc_sentiment(sentiment)
        assert bias.is_sentiment_fresh() is True
        
        # Stale sentiment
        sentiment.timestamp = time.time() - 400
        bias.update_btc_sentiment(sentiment)
        assert bias.is_sentiment_fresh() is False


class TestInternalSentimentCalculator:
    """Test internal BTC sentiment calculator."""
    
    def test_strong_bullish_sentiment(self):
        """Test calculation of strong bullish sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            calculate_internal_btc_sentiment,
            SentimentDirection
        )
        
        sentiment = calculate_internal_btc_sentiment(
            btc_price_change_pct=0.08,  # +8%
            btc_volume_change_pct=0.10,  # +10%
            btc_volatility=0.05
        )
        
        assert sentiment.direction == SentimentDirection.STRONG_BULLISH
        assert sentiment.confidence > 0.7
        assert sentiment.source == "internal"
    
    def test_strong_bearish_sentiment(self):
        """Test calculation of strong bearish sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            calculate_internal_btc_sentiment,
            SentimentDirection
        )
        
        sentiment = calculate_internal_btc_sentiment(
            btc_price_change_pct=-0.12,  # -12% (more extreme for strong)
            btc_volume_change_pct=0.10,
            btc_volatility=0.05
        )
        
        assert sentiment.direction == SentimentDirection.STRONG_BEARISH
        assert sentiment.confidence >= 0.65  # Allow floating point precision
        assert sentiment.source == "internal"
    
    def test_neutral_sentiment(self):
        """Test calculation of neutral sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            calculate_internal_btc_sentiment,
            SentimentDirection
        )
        
        sentiment = calculate_internal_btc_sentiment(
            btc_price_change_pct=0.01,  # +1%
            btc_volume_change_pct=0.01,
            btc_volatility=0.05
        )
        
        assert sentiment.direction == SentimentDirection.NEUTRAL
        assert sentiment.source == "internal"
    
    def test_bullish_sentiment(self):
        """Test calculation of moderate bullish sentiment."""
        from merid.prediction.btc_sentiment_bias import (
            calculate_internal_btc_sentiment,
            SentimentDirection
        )
        
        sentiment = calculate_internal_btc_sentiment(
            btc_price_change_pct=0.03,  # +3% (moderate for bullish)
            btc_volume_change_pct=0.05,
            btc_volatility=0.05
        )
        
        assert sentiment.direction == SentimentDirection.BULLISH
        assert sentiment.source == "internal"


class TestBTCSentimentBiasSingleton:
    """Test BTC sentiment bias singleton pattern."""
    
    def test_singleton_initialization(self):
        """Test singleton initialization."""
        from merid.prediction.btc_sentiment_bias import (
            init_btc_sentiment_bias,
            get_btc_sentiment_bias,
            SentimentBiasConfig
        )
        
        config = SentimentBiasConfig(enabled=True)
        bias = init_btc_sentiment_bias(config)
        
        # Should return same instance
        bias2 = get_btc_sentiment_bias()
        assert bias is bias2
    
    def test_singleton_reset(self):
        """Test singleton reset."""
        from merid.prediction.btc_sentiment_bias import (
            init_btc_sentiment_bias,
            get_btc_sentiment_bias,
            reset_btc_sentiment_bias,
            SentimentBiasConfig
        )
        
        config = SentimentBiasConfig(enabled=True)
        bias1 = init_btc_sentiment_bias(config)
        
        # Reset
        reset_btc_sentiment_bias()
        
        # Should return None after reset
        bias2 = get_btc_sentiment_bias()
        assert bias2 is None
        
        # Can reinitialize
        bias3 = init_btc_sentiment_bias(config)
        assert bias3 is not None
