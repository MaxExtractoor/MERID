"""Tests for ml/predictive_models.py - Predictive Models."""
import pytest
import numpy as np
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

from ml.predictive_models import (
    PricePrediction,
    TrendSignal,
    MarketRegime,
    VolatilityForecast,
    TradingSignal,
)


class TestPricePrediction:
    """Test PricePrediction dataclass."""

    def test_creation(self):
        """Test creating price prediction."""
        pred = PricePrediction(
            symbol="BTC/USD",
            current_price=50000.0,
            predicted_price=52000.0,
            confidence=0.85,
            time_horizon="1h",
            prediction_time=0.05,
        )
        assert pred.symbol == "BTC/USD"
        assert pred.predicted_price == 52000.0
        assert pred.confidence == 0.85

    def test_with_features(self):
        """Test with features list."""
        pred = PricePrediction(
            symbol="ETH/USD",
            current_price=3000.0,
            predicted_price=3100.0,
            confidence=0.75,
            time_horizon="4h",
            prediction_time=0.1,
            features_used=["rsi", "macd", "volume"],
        )
        assert len(pred.features_used) == 3
        assert "rsi" in pred.features_used

    def test_price_change_calculation(self):
        """Test calculating price change percentage."""
        pred = PricePrediction(
            symbol="BTC/USD",
            current_price=50000.0,
            predicted_price=55000.0,
            confidence=0.8,
            time_horizon="1d",
            prediction_time=0.05,
        )
        change_pct = (pred.predicted_price - pred.current_price) / pred.current_price * 100
        assert change_pct == pytest.approx(10.0)


class TestTrendSignal:
    """Test TrendSignal dataclass."""

    def test_bullish_signal(self):
        """Test bullish trend signal."""
        signal = TrendSignal(
            symbol="BTC/USD",
            trend_direction="bullish",
            strength=0.8,
            confidence=0.9,
            time_horizon="4h",
            signal_time=0.02,
        )
        assert signal.trend_direction == "bullish"
        assert signal.strength == 0.8

    def test_bearish_signal(self):
        """Test bearish trend signal."""
        signal = TrendSignal(
            symbol="ETH/USD",
            trend_direction="bearish",
            strength=0.6,
            confidence=0.75,
            time_horizon="1d",
            signal_time=0.03,
        )
        assert signal.trend_direction == "bearish"

    def test_with_indicators(self):
        """Test with technical indicators."""
        signal = TrendSignal(
            symbol="BTC/USD",
            trend_direction="bullish",
            strength=0.7,
            confidence=0.85,
            time_horizon="1h",
            signal_time=0.01,
            indicators={"rsi": 65.0, "macd": 0.5, "bb_position": 0.8},
        )
        assert signal.indicators["rsi"] == 65.0
        assert len(signal.indicators) == 3


class TestMarketRegime:
    """Test MarketRegime dataclass."""

    def test_bull_market(self):
        """Test bull market regime."""
        regime = MarketRegime(
            regime="bull_market",
            confidence=0.9,
            volatility_level="medium",
            momentum=0.7,
            regime_time=0.05,
        )
        assert regime.regime == "bull_market"
        assert regime.momentum == 0.7

    def test_bear_market(self):
        """Test bear market regime."""
        regime = MarketRegime(
            regime="bear_market",
            confidence=0.85,
            volatility_level="high",
            momentum=-0.6,
            regime_time=0.04,
        )
        assert regime.regime == "bear_market"
        assert regime.momentum < 0

    def test_sideways_market(self):
        """Test sideways market regime."""
        regime = MarketRegime(
            regime="sideways",
            confidence=0.7,
            volatility_level="low",
            momentum=0.1,
            regime_time=0.03,
        )
        assert regime.regime == "sideways"
        assert abs(regime.momentum) < 0.2

    def test_volatile_market(self):
        """Test volatile market regime."""
        regime = MarketRegime(
            regime="volatile",
            confidence=0.8,
            volatility_level="high",
            momentum=0.0,
            regime_time=0.06,
        )
        assert regime.volatility_level == "high"


class TestVolatilityForecast:
    """Test VolatilityForecast dataclass."""

    def test_creation(self):
        """Test creating volatility forecast."""
        forecast = VolatilityForecast(
            symbol="BTC/USD",
            current_volatility=0.02,
            predicted_volatility=0.025,
            confidence=0.8,
            time_horizon="1h",
            forecast_time=0.04,
            risk_level="medium",
        )
        assert forecast.current_volatility == 0.02
        assert forecast.risk_level == "medium"

    def test_high_volatility_forecast(self):
        """Test high volatility forecast."""
        forecast = VolatilityForecast(
            symbol="ETH/USD",
            current_volatility=0.05,
            predicted_volatility=0.08,
            confidence=0.75,
            time_horizon="4h",
            forecast_time=0.05,
            risk_level="high",
        )
        assert forecast.predicted_volatility > forecast.current_volatility
        assert forecast.risk_level == "high"

    def test_low_volatility_forecast(self):
        """Test low volatility forecast."""
        forecast = VolatilityForecast(
            symbol="USDC/USD",
            current_volatility=0.001,
            predicted_volatility=0.001,
            confidence=0.95,
            time_horizon="1d",
            forecast_time=0.02,
            risk_level="low",
        )
        assert forecast.risk_level == "low"


class TestTradingSignal:
    """Test TradingSignal dataclass."""

    def test_buy_signal(self):
        """Test buy trading signal."""
        signal = TradingSignal(
            symbol="BTC/USD",
            signal_type="buy",
            strength=0.85,
            confidence=0.9,
            entry_price=50000.0,
            target_price=55000.0,
            stop_loss=48000.0,
            time_horizon="1d",
            signal_time=0.1,
            reasoning="Strong bullish momentum with RSI breakout",
        )
        assert signal.signal_type == "buy"
        assert signal.target_price > signal.entry_price
        assert signal.stop_loss < signal.entry_price

    def test_sell_signal(self):
        """Test sell trading signal."""
        signal = TradingSignal(
            symbol="ETH/USD",
            signal_type="sell",
            strength=0.7,
            confidence=0.8,
            entry_price=3000.0,
            target_price=2700.0,
            stop_loss=3150.0,
            time_horizon="4h",
            signal_time=0.08,
            reasoning="Bearish divergence detected",
        )
        assert signal.signal_type == "sell"
        assert signal.target_price < signal.entry_price

    def test_hold_signal(self):
        """Test hold trading signal."""
        signal = TradingSignal(
            symbol="BTC/USD",
            signal_type="hold",
            strength=0.3,
            confidence=0.6,
            entry_price=50000.0,
            target_price=50000.0,
            stop_loss=49000.0,
            time_horizon="1h",
            signal_time=0.05,
            reasoning="No clear direction, wait for confirmation",
        )
        assert signal.signal_type == "hold"
        assert signal.strength < 0.5

    def test_risk_reward_ratio(self):
        """Test calculating risk/reward ratio."""
        signal = TradingSignal(
            symbol="BTC/USD",
            signal_type="buy",
            strength=0.8,
            confidence=0.85,
            entry_price=50000.0,
            target_price=55000.0,
            stop_loss=48000.0,
            time_horizon="1d",
            signal_time=0.1,
            reasoning="Breakout pattern",
        )
        reward = signal.target_price - signal.entry_price
        risk = signal.entry_price - signal.stop_loss
        risk_reward = reward / risk
        assert risk_reward == pytest.approx(2.5)


class TestPricePredictor:
    """Test PricePredictor class."""

    @pytest.fixture
    def mock_ml_framework(self):
        """Create mock ML framework."""
        framework = Mock()
        framework.create_model = Mock(return_value=True)
        framework.models = {}
        return framework

    @pytest.fixture
    def predictor_config(self):
        """Create predictor config."""
        return {
            "cache_ttl": 300,
            "default_time_horizon": "1h",
        }

    def test_predictor_creation(self, mock_ml_framework, predictor_config):
        """Test creating price predictor."""
        from ml.predictive_models import PricePredictor
        
        predictor = PricePredictor(mock_ml_framework, predictor_config)
        
        assert predictor is not None
        assert predictor.cache_ttl == 300

    def test_predictor_has_feature_columns(self, mock_ml_framework, predictor_config):
        """Test predictor has feature columns."""
        from ml.predictive_models import PricePredictor
        
        predictor = PricePredictor(mock_ml_framework, predictor_config)
        
        assert len(predictor.feature_columns) > 0
        assert "rsi_14" in predictor.feature_columns

    @pytest.mark.asyncio
    async def test_initialize_models(self, mock_ml_framework, predictor_config):
        """Test initializing models."""
        from ml.predictive_models import PricePredictor
        
        predictor = PricePredictor(mock_ml_framework, predictor_config)
        result = await predictor.initialize_models()
        
        assert result is True
        assert mock_ml_framework.create_model.call_count == 4  # 4 time horizons


class TestTrendAnalyzer:
    """Test TrendAnalyzer class."""

    @pytest.fixture
    def mock_ml_framework(self):
        """Create mock ML framework."""
        framework = Mock()
        framework.create_model = Mock(return_value=True)
        return framework

    @pytest.fixture
    def analyzer_config(self):
        """Create analyzer config."""
        return {
            "min_confidence": 0.6,
            "trend_threshold": 0.02,
        }

    def test_analyzer_creation(self, mock_ml_framework, analyzer_config):
        """Test creating trend analyzer."""
        from ml.predictive_models import TrendAnalyzer
        
        analyzer = TrendAnalyzer(mock_ml_framework, analyzer_config)
        
        assert analyzer is not None


class TestMarketRegimeClassifier:
    """Test MarketRegimeClassifier class."""

    @pytest.fixture
    def mock_ml_framework(self):
        """Create mock ML framework."""
        framework = Mock()
        framework.create_model = Mock(return_value=True)
        return framework

    @pytest.fixture
    def classifier_config(self):
        """Create classifier config."""
        return {
            "regime_window": 20,
            "volatility_threshold": 0.03,
        }

    def test_classifier_creation(self, mock_ml_framework, classifier_config):
        """Test creating regime classifier."""
        from ml.predictive_models import MarketRegimeClassifier
        
        classifier = MarketRegimeClassifier(mock_ml_framework, classifier_config)
        
        assert classifier is not None


