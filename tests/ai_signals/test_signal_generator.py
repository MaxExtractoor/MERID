"""Tests for ai_signals/signal_generator.py - AI Signal Generation."""
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from ai_signals.signal_generator import (
    SignalType,
    SignalSource,
    SignalConfidence,
    TradingSignal,
    SignalModel,
    EnsembleConfig,
    AISignalGenerator,
)


class TestSignalType:
    """Test SignalType enum."""

    def test_buy_signal(self):
        """Test buy signal type."""
        assert SignalType.BUY.value == "buy"

    def test_sell_signal(self):
        """Test sell signal type."""
        assert SignalType.SELL.value == "sell"

    def test_hold_signal(self):
        """Test hold signal type."""
        assert SignalType.HOLD.value == "hold"

    def test_strong_buy_signal(self):
        """Test strong buy signal type."""
        assert SignalType.STRONG_BUY.value == "strong_buy"

    def test_strong_sell_signal(self):
        """Test strong sell signal type."""
        assert SignalType.STRONG_SELL.value == "strong_sell"


class TestSignalSource:
    """Test SignalSource enum."""

    def test_deep_learning_source(self):
        """Test deep learning source."""
        assert SignalSource.DEEP_LEARNING.value == "deep_learning"

    def test_ensemble_source(self):
        """Test ensemble source."""
        assert SignalSource.ENSEMBLE.value == "ensemble"

    def test_technical_source(self):
        """Test technical source."""
        assert SignalSource.TECHNICAL.value == "technical"

    def test_sentiment_source(self):
        """Test sentiment source."""
        assert SignalSource.SENTIMENT.value == "sentiment"


class TestSignalConfidence:
    """Test SignalConfidence enum."""

    def test_confidence_levels(self):
        """Test confidence level ordering."""
        assert SignalConfidence.VERY_LOW.value == 1
        assert SignalConfidence.LOW.value == 2
        assert SignalConfidence.MEDIUM.value == 3
        assert SignalConfidence.HIGH.value == 4
        assert SignalConfidence.VERY_HIGH.value == 5

    def test_confidence_ordering(self):
        """Test confidence ordering."""
        assert SignalConfidence.VERY_HIGH.value > SignalConfidence.HIGH.value
        assert SignalConfidence.HIGH.value > SignalConfidence.MEDIUM.value


class TestTradingSignal:
    """Test TradingSignal dataclass."""

    def test_buy_signal(self):
        """Test buy trading signal."""
        signal = TradingSignal(
            signal_id="sig_001",
            symbol="BTC/USD",
            signal_type=SignalType.BUY,
            signal_source=SignalSource.DEEP_LEARNING,
            confidence=SignalConfidence.HIGH,
            strength=0.75,
            expected_return=0.08,
            risk_score=0.3,
            time_horizon=7,
            entry_price=50000.0,
            stop_loss=47500.0,
            take_profit=55000.0,
            position_size=0.1,
            generated_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=7),
            features={"momentum": 0.8, "volatility": 0.3},
            model_predictions={"lstm": 0.75, "transformer": 0.80},
        )
        assert signal.signal_type == SignalType.BUY
        assert signal.stop_loss < signal.entry_price

    def test_sell_signal(self):
        """Test sell trading signal."""
        signal = TradingSignal(
            signal_id="sig_002",
            symbol="ETH/USD",
            signal_type=SignalType.SELL,
            signal_source=SignalSource.ENSEMBLE,
            confidence=SignalConfidence.MEDIUM,
            strength=0.60,
            expected_return=-0.05,
            risk_score=0.4,
            time_horizon=3,
            entry_price=3000.0,
            stop_loss=3150.0,
            take_profit=2850.0,
            position_size=0.05,
            generated_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=3),
            features={"trend": -0.6},
            model_predictions={"rf": 0.55},
        )
        assert signal.signal_type == SignalType.SELL
        assert signal.stop_loss > signal.entry_price  # For short

    def test_strong_buy_signal(self):
        """Test strong buy signal with high confidence."""
        signal = TradingSignal(
            signal_id="sig_003",
            symbol="SOL/USD",
            signal_type=SignalType.STRONG_BUY,
            signal_source=SignalSource.MULTI_FACTOR,
            confidence=SignalConfidence.VERY_HIGH,
            strength=0.92,
            expected_return=0.15,
            risk_score=0.25,
            time_horizon=14,
            entry_price=100.0,
            stop_loss=92.0,
            take_profit=120.0,
            position_size=0.15,
            generated_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=14),
            features={},
            model_predictions={},
        )
        assert signal.confidence == SignalConfidence.VERY_HIGH
        assert signal.strength > 0.9


class TestSignalModel:
    """Test SignalModel dataclass."""

    def test_high_accuracy_model(self):
        """Test high accuracy model."""
        model = SignalModel(
            model_id="model_001",
            model_name="LSTM Price Predictor",
            model_type="lstm",
            model_version="2.1.0",
            features=["price", "volume", "momentum", "volatility"],
            target_variable="direction",
            accuracy=0.85,
            precision=0.82,
            recall=0.88,
            f1_score=0.85,
            auc_score=0.90,
            training_data_points=100000,
            last_trained=datetime.now(),
            is_active=True,
        )
        assert model.accuracy > 0.8
        assert model.is_active is True

    def test_ensemble_model(self):
        """Test ensemble model."""
        model = SignalModel(
            model_id="model_002",
            model_name="Multi-Model Ensemble",
            model_type="ensemble",
            model_version="1.0.0",
            features=["technical", "sentiment", "fundamental"],
            target_variable="signal",
            accuracy=0.78,
            precision=0.75,
            recall=0.80,
            f1_score=0.77,
            auc_score=0.82,
            training_data_points=50000,
            last_trained=datetime.now() - timedelta(days=7),
            is_active=True,
        )
        assert model.model_type == "ensemble"


class TestEnsembleConfig:
    """Test EnsembleConfig dataclass."""

    def test_weighted_ensemble(self):
        """Test weighted ensemble configuration."""
        config = EnsembleConfig(
            ensemble_id="ens_001",
            ensemble_name="Primary Ensemble",
            models=["lstm", "transformer", "rf"],
            weights=[0.4, 0.35, 0.25],
            voting_method="weighted",
            threshold=0.6,
        )
        assert sum(config.weights) == pytest.approx(1.0)
        assert config.voting_method == "weighted"

    def test_majority_voting(self):
        """Test majority voting ensemble."""
        config = EnsembleConfig(
            ensemble_id="ens_002",
            ensemble_name="Majority Ensemble",
            models=["model_a", "model_b", "model_c", "model_d", "model_e"],
            weights=[0.2, 0.2, 0.2, 0.2, 0.2],
            voting_method="majority",
            threshold=0.5,
        )
        assert len(config.models) == 5
        assert config.voting_method == "majority"


class TestAISignalGenerator:
    """Test AISignalGenerator class."""

    @pytest.fixture
    def generator_config(self):
        """Create generator config."""
        return {
            "min_confidence": 0.6,
            "max_signals_per_symbol": 5,
            "signal_expiry_hours": 24,
        }

    @pytest.fixture
    def signal_generator(self, generator_config):
        """Create signal generator instance."""
        return AISignalGenerator(generator_config)

    def test_generator_creation(self, signal_generator):
        """Test creating generator."""
        assert signal_generator is not None

    def test_models_registry(self, signal_generator):
        """Test models registry."""
        assert hasattr(signal_generator, 'models')
        assert isinstance(signal_generator.models, dict)


class TestSignalScoring:
    """Test signal scoring logic."""

    def test_combined_score(self):
        """Test combined signal score calculation."""
        model_predictions = {
            "lstm": 0.75,
            "transformer": 0.82,
            "rf": 0.70,
        }
        weights = {"lstm": 0.4, "transformer": 0.35, "rf": 0.25}
        
        combined_score = sum(
            model_predictions[m] * weights[m] 
            for m in model_predictions
        )
        
        assert 0 < combined_score < 1

    def test_confidence_to_position_size(self):
        """Test confidence to position size mapping."""
        def get_position_size(confidence: SignalConfidence, base_size: float) -> float:
            multipliers = {
                SignalConfidence.VERY_LOW: 0.2,
                SignalConfidence.LOW: 0.4,
                SignalConfidence.MEDIUM: 0.6,
                SignalConfidence.HIGH: 0.8,
                SignalConfidence.VERY_HIGH: 1.0,
            }
            return base_size * multipliers[confidence]
        
        base = 0.1
        assert get_position_size(SignalConfidence.VERY_HIGH, base) == 0.1
        assert get_position_size(SignalConfidence.MEDIUM, base) == 0.06

    def test_risk_adjusted_strength(self):
        """Test risk-adjusted signal strength."""
        strength = 0.80
        risk_score = 0.30
        
        risk_adjusted = strength * (1 - risk_score)
        
        assert risk_adjusted == pytest.approx(0.56)


class TestSignalValidation:
    """Test signal validation logic."""

    def test_stop_loss_validation_long(self):
        """Test stop loss validation for long signals."""
        entry_price = 100.0
        stop_loss = 95.0  # 5% stop
        
        is_valid = stop_loss < entry_price
        stop_distance = (entry_price - stop_loss) / entry_price
        
        assert is_valid is True
        assert stop_distance == 0.05

    def test_stop_loss_validation_short(self):
        """Test stop loss validation for short signals."""
        entry_price = 100.0
        stop_loss = 105.0  # 5% stop for short
        
        is_valid = stop_loss > entry_price
        stop_distance = (stop_loss - entry_price) / entry_price
        
        assert is_valid is True
        assert stop_distance == 0.05

    def test_risk_reward_ratio(self):
        """Test risk/reward ratio calculation."""
        entry_price = 100.0
        stop_loss = 95.0
        take_profit = 115.0
        
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk
        
        assert rr_ratio == 3.0

    def test_signal_expiry(self):
        """Test signal expiry validation."""
        generated_at = datetime.now()
        expires_at = generated_at + timedelta(hours=24)
        
        is_expired = datetime.now() > expires_at
        
        assert is_expired is False


class TestEnsembleMethods:
    """Test ensemble voting methods."""

    def test_weighted_voting(self):
        """Test weighted voting."""
        predictions = [0.7, 0.8, 0.6]
        weights = [0.4, 0.35, 0.25]
        
        weighted_avg = sum(p * w for p, w in zip(predictions, weights))
        
        assert weighted_avg == pytest.approx(0.71)

    def test_majority_voting(self):
        """Test majority voting."""
        predictions = [1, 1, 0, 1, 0]  # 1 = buy, 0 = sell
        
        buy_votes = sum(predictions)
        sell_votes = len(predictions) - buy_votes
        
        signal = "buy" if buy_votes > sell_votes else "sell"
        
        assert signal == "buy"

    def test_consensus_voting(self):
        """Test consensus voting (all must agree)."""
        predictions = [1, 1, 1, 1, 1]
        
        is_consensus = len(set(predictions)) == 1
        
        assert is_consensus is True

    def test_no_consensus(self):
        """Test no consensus scenario."""
        predictions = [1, 1, 0, 1, 0]
        
        is_consensus = len(set(predictions)) == 1
        
        assert is_consensus is False


class TestFeatureEngineering:
    """Test feature engineering for signals."""

    def test_momentum_feature(self):
        """Test momentum feature calculation."""
        prices = np.array([100, 102, 105, 103, 108, 112, 110])
        lookback = 5
        
        momentum = (prices[-1] - prices[-lookback]) / prices[-lookback]
        
        assert momentum > 0

    def test_volatility_feature(self):
        """Test volatility feature calculation."""
        returns = np.array([0.01, -0.02, 0.015, -0.01, 0.025, -0.005])
        
        volatility = np.std(returns) * np.sqrt(252)
        
        assert volatility > 0

    def test_rsi_feature(self):
        """Test RSI feature calculation."""
        prices = np.array([44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10])
        
        changes = np.diff(prices)
        gains = changes[changes > 0].sum() / len(changes)
        losses = abs(changes[changes < 0].sum()) / len(changes)
        
        rs = gains / losses if losses != 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        assert 0 <= rsi <= 100
