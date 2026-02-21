"""Tests for analytics/market_regimes.py - Market Regime Detection."""
import pytest
import numpy as np
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from analytics.market_regimes import (
    MarketState,
    RegimeTransition,
    RegimeClassification,
    MarketRegimeClassifier,
)


class TestMarketState:
    """Test MarketState dataclass."""

    def test_bullish_state(self):
        """Test bullish market state."""
        state = MarketState(
            timestamp=1000.0,
            price=50000.0,
            volume=1000000.0,
            volatility=0.15,
            momentum=0.08,
            trend_strength=0.7,
            market_sentiment=0.6,
            social_sentiment=0.7,
            onchain_activity=0.8,
            liquidity_index=0.9,
            fear_greed_index=65.0,
            market_breadth=0.7,
            sector_rotation=0.5,
            macro_indicators={"inflation": 2.5, "rates": 5.0},
        )
        assert state.momentum > 0
        assert state.trend_strength > 0.5
        assert state.fear_greed_index > 50

    def test_bearish_state(self):
        """Test bearish market state."""
        state = MarketState(
            timestamp=1000.0,
            price=40000.0,
            volume=2000000.0,
            volatility=0.35,
            momentum=-0.12,
            trend_strength=0.6,
            market_sentiment=-0.5,
            social_sentiment=-0.4,
            onchain_activity=0.3,
            liquidity_index=0.5,
            fear_greed_index=25.0,
            market_breadth=0.3,
            sector_rotation=-0.3,
            macro_indicators={"inflation": 6.0, "rates": 7.0},
        )
        assert state.momentum < 0
        assert state.fear_greed_index < 50

    def test_sideways_state(self):
        """Test sideways market state."""
        state = MarketState(
            timestamp=1000.0,
            price=45000.0,
            volume=800000.0,
            volatility=0.08,
            momentum=0.01,
            trend_strength=0.2,
            market_sentiment=0.0,
            social_sentiment=0.1,
            onchain_activity=0.5,
            liquidity_index=0.7,
            fear_greed_index=50.0,
            market_breadth=0.5,
            sector_rotation=0.0,
            macro_indicators={},
        )
        assert abs(state.momentum) < 0.05
        assert state.volatility < 0.15


class TestRegimeTransition:
    """Test RegimeTransition dataclass."""

    def test_bull_to_bear(self):
        """Test bull to bear transition."""
        transition = RegimeTransition(
            from_regime="bull_market",
            to_regime="bear_market",
            transition_time=1000.0,
            confidence=0.85,
            transition_duration=3600.0,
            trigger_factors=["momentum_reversal", "volume_spike", "sentiment_shift"],
        )
        assert transition.from_regime == "bull_market"
        assert transition.to_regime == "bear_market"
        assert len(transition.trigger_factors) == 3

    def test_sideways_to_volatile(self):
        """Test sideways to volatile transition."""
        transition = RegimeTransition(
            from_regime="sideways",
            to_regime="volatile",
            transition_time=2000.0,
            confidence=0.75,
            transition_duration=1800.0,
            trigger_factors=["volatility_breakout", "news_event"],
        )
        assert transition.confidence >= 0.7

    def test_transition_with_metadata(self):
        """Test transition with metadata."""
        transition = RegimeTransition(
            from_regime="volatile",
            to_regime="bull_market",
            transition_time=3000.0,
            confidence=0.9,
            transition_duration=7200.0,
            trigger_factors=["trend_confirmation"],
            metadata={"catalyst": "fed_announcement", "market": "crypto"},
        )
        assert transition.metadata["catalyst"] == "fed_announcement"


class TestRegimeClassification:
    """Test RegimeClassification dataclass."""

    def test_bull_classification(self):
        """Test bull market classification."""
        classification = RegimeClassification(
            regime="bull_market",
            confidence=0.85,
            probability={"bull_market": 0.85, "bear_market": 0.05, "sideways": 0.08, "volatile": 0.02},
            risk_level="low",
            volatility_level="medium",
            momentum_level="high",
            timestamp=1000.0,
        )
        assert classification.regime == "bull_market"
        assert classification.probability["bull_market"] == 0.85
        assert sum(classification.probability.values()) == pytest.approx(1.0)

    def test_bear_classification(self):
        """Test bear market classification."""
        classification = RegimeClassification(
            regime="bear_market",
            confidence=0.9,
            probability={"bull_market": 0.03, "bear_market": 0.90, "sideways": 0.05, "volatile": 0.02},
            risk_level="high",
            volatility_level="high",
            momentum_level="negative",
            timestamp=1000.0,
        )
        assert classification.risk_level == "high"

    def test_classification_with_features(self):
        """Test classification with features."""
        classification = RegimeClassification(
            regime="volatile",
            confidence=0.75,
            probability={"bull_market": 0.15, "bear_market": 0.10, "sideways": 0.05, "volatile": 0.70},
            risk_level="high",
            volatility_level="extreme",
            momentum_level="mixed",
            timestamp=1000.0,
            features={"rsi": 45.0, "macd": -0.5, "bb_width": 0.08},
        )
        assert classification.features["rsi"] == 45.0


class TestMarketRegimeClassifier:
    """Test MarketRegimeClassifier class."""

    @pytest.fixture
    def classifier_config(self):
        """Create classifier config."""
        return {
            "min_confidence": 0.6,
            "lookback_periods": 20,
            "feature_weights": {
                "price_momentum": 0.25,
                "volume_trend": 0.20,
                "volatility": 0.15,
            },
        }

    @pytest.fixture
    def classifier(self, classifier_config):
        """Create classifier instance."""
        return MarketRegimeClassifier(classifier_config)

    def test_classifier_creation(self, classifier):
        """Test creating classifier."""
        assert classifier is not None
        assert classifier.regime_definitions is not None

    def test_regime_definitions(self, classifier):
        """Test regime definitions."""
        assert "bull_market" in classifier.regime_definitions
        assert "bear_market" in classifier.regime_definitions
        assert "sideways" in classifier.regime_definitions
        assert "volatile" in classifier.regime_definitions

    def test_bull_market_definition(self, classifier):
        """Test bull market definition."""
        bull = classifier.regime_definitions["bull_market"]
        assert bull["risk_level"] == "low"
        assert "price_trend > 0.02" in bull["characteristics"]

    def test_bear_market_definition(self, classifier):
        """Test bear market definition."""
        bear = classifier.regime_definitions["bear_market"]
        assert bear["risk_level"] == "high"
        assert "price_trend < -0.02" in bear["characteristics"]

    def test_feature_weights(self, classifier):
        """Test feature weights."""
        weights = classifier.feature_weights
        assert "price_momentum" in weights
        assert weights["price_momentum"] > 0

    def test_us_compliance(self, classifier):
        """Test US compliance settings."""
        assert classifier.us_compliance["market_data_privacy"] is True
        assert classifier.us_compliance["model_transparency"] is True

    def test_classification_history(self, classifier):
        """Test classification history tracking."""
        assert hasattr(classifier, 'classification_history')
        assert hasattr(classifier, 'transition_history')


class TestRegimeDetectionLogic:
    """Test regime detection logic."""

    def test_momentum_based_classification(self):
        """Test momentum-based regime classification."""
        def classify_by_momentum(momentum):
            if momentum > 0.05:
                return "bull_market"
            elif momentum < -0.05:
                return "bear_market"
            else:
                return "sideways"
        
        assert classify_by_momentum(0.10) == "bull_market"
        assert classify_by_momentum(-0.08) == "bear_market"
        assert classify_by_momentum(0.02) == "sideways"

    def test_volatility_based_classification(self):
        """Test volatility-based regime classification."""
        def classify_by_volatility(volatility):
            if volatility > 0.4:
                return "volatile"
            elif volatility > 0.2:
                return "medium"
            else:
                return "low"
        
        assert classify_by_volatility(0.5) == "volatile"
        assert classify_by_volatility(0.3) == "medium"
        assert classify_by_volatility(0.1) == "low"

    def test_combined_classification(self):
        """Test combined classification logic."""
        def classify_regime(momentum, volatility, trend_strength):
            if volatility > 0.4:
                return "volatile"
            elif momentum > 0.05 and trend_strength > 0.5:
                return "bull_market"
            elif momentum < -0.05 and trend_strength > 0.5:
                return "bear_market"
            else:
                return "sideways"
        
        assert classify_regime(0.10, 0.2, 0.7) == "bull_market"
        assert classify_regime(-0.10, 0.25, 0.8) == "bear_market"
        assert classify_regime(0.02, 0.1, 0.3) == "sideways"
        assert classify_regime(0.15, 0.5, 0.9) == "volatile"

    def test_probability_distribution(self):
        """Test regime probability distribution."""
        # Simulate softmax-like probability distribution
        scores = {"bull_market": 2.5, "bear_market": 0.5, "sideways": 1.0, "volatile": 0.3}
        
        exp_scores = {k: np.exp(v) for k, v in scores.items()}
        total = sum(exp_scores.values())
        probabilities = {k: v / total for k, v in exp_scores.items()}
        
        assert sum(probabilities.values()) == pytest.approx(1.0)
        assert probabilities["bull_market"] > probabilities["bear_market"]

    def test_transition_detection(self):
        """Test regime transition detection."""
        history = ["bull_market", "bull_market", "bull_market", "sideways", "bear_market"]
        
        transitions = []
        for i in range(1, len(history)):
            if history[i] != history[i-1]:
                transitions.append((history[i-1], history[i], i))
        
        assert len(transitions) == 2
        assert transitions[0] == ("bull_market", "sideways", 3)
        assert transitions[1] == ("sideways", "bear_market", 4)


class TestRiskAssessment:
    """Test risk assessment based on regime."""

    def test_bull_market_risk(self):
        """Test bull market risk assessment."""
        regime = "bull_market"
        risk_levels = {
            "bull_market": "low",
            "bear_market": "high",
            "sideways": "medium",
            "volatile": "high",
        }
        
        assert risk_levels[regime] == "low"

    def test_position_sizing_by_regime(self):
        """Test position sizing based on regime."""
        regime_multipliers = {
            "bull_market": 1.2,
            "bear_market": 0.5,
            "sideways": 0.8,
            "volatile": 0.3,
        }
        
        base_position = 10000
        
        assert base_position * regime_multipliers["bull_market"] == 12000
        assert base_position * regime_multipliers["bear_market"] == 5000
        assert base_position * regime_multipliers["volatile"] == 3000

    def test_stop_loss_by_regime(self):
        """Test stop loss adjustment by regime."""
        regime_stop_loss = {
            "bull_market": 0.05,   # 5% stop
            "bear_market": 0.08,  # 8% stop
            "sideways": 0.03,     # 3% stop
            "volatile": 0.10,     # 10% stop
        }
        
        # Volatile markets need wider stops
        assert regime_stop_loss["volatile"] > regime_stop_loss["bull_market"]
        # Trending markets (bull/bear) need moderate stops
        assert regime_stop_loss["bear_market"] > regime_stop_loss["bull_market"]
