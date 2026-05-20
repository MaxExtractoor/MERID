"""
Tests for Fear/Greed, Volatility & Sizing Canonical Types

Tests the pure transform functions for:
- Regime classification
- Sizing multiplier computation
- Edge cases and boundary conditions

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research
from datetime import datetime, timezone

from merid.prediction.risk.sentiment_vol_types import (
    FearGreedRegime,
    VolatilityRegime,
    UncertaintyRegime,
    SentimentScalar,
    VolatilityScalar,
    SizingMultiplier,
    SentimentVolConfig,
    compute_sentiment_regime,
    compute_volatility_regime,
    compute_uncertainty_regime,
    compute_sentiment_multiplier,
    compute_volatility_multiplier,
    compute_sizing_multiplier,
    create_sentiment_scalar,
    create_volatility_scalar,
)


# ═══════════════════════════════════════════════════════════════════════════
# Regime Classification Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentRegimeClassification:
    """Test sentiment regime classification logic."""
    
    def test_extreme_fear_boundary(self):
        """Test extreme fear boundary (0-25 with default config)."""
        cfg = SentimentVolConfig()
        
        assert compute_sentiment_regime(0, cfg) == FearGreedRegime.EXTREME_FEAR
        assert compute_sentiment_regime(10, cfg) == FearGreedRegime.EXTREME_FEAR
        assert compute_sentiment_regime(25, cfg) == FearGreedRegime.EXTREME_FEAR
        assert compute_sentiment_regime(26, cfg) == FearGreedRegime.FEAR
    
    def test_fear_boundary(self):
        """Test fear regime boundary (26-45 with default config)."""
        cfg = SentimentVolConfig()
        
        assert compute_sentiment_regime(26, cfg) == FearGreedRegime.FEAR
        assert compute_sentiment_regime(35, cfg) == FearGreedRegime.FEAR
        assert compute_sentiment_regime(45, cfg) == FearGreedRegime.FEAR
        assert compute_sentiment_regime(46, cfg) == FearGreedRegime.NEUTRAL
    
    def test_neutral_boundary(self):
        """Test neutral regime boundary (46-54 with default config)."""
        cfg = SentimentVolConfig()
        
        assert compute_sentiment_regime(46, cfg) == FearGreedRegime.NEUTRAL
        assert compute_sentiment_regime(50, cfg) == FearGreedRegime.NEUTRAL
        assert compute_sentiment_regime(54, cfg) == FearGreedRegime.NEUTRAL
    
    def test_greed_boundary(self):
        """Test greed regime boundary (55-74 with default config)."""
        cfg = SentimentVolConfig()
        
        assert compute_sentiment_regime(55, cfg) == FearGreedRegime.GREED
        assert compute_sentiment_regime(65, cfg) == FearGreedRegime.GREED
        assert compute_sentiment_regime(74, cfg) == FearGreedRegime.GREED
        assert compute_sentiment_regime(75, cfg) == FearGreedRegime.EXTREME_GREED
    
    def test_extreme_greed_boundary(self):
        """Test extreme greed boundary (75-100 with default config)."""
        cfg = SentimentVolConfig()
        
        assert compute_sentiment_regime(75, cfg) == FearGreedRegime.EXTREME_GREED
        assert compute_sentiment_regime(90, cfg) == FearGreedRegime.EXTREME_GREED
        assert compute_sentiment_regime(100, cfg) == FearGreedRegime.EXTREME_GREED


class TestVolatilityRegimeClassification:
    """Test volatility regime classification logic."""
    
    def test_dead_vol_boundary(self):
        """Test dead market regime (vol < 0.15)."""
        cfg = SentimentVolConfig()
        
        assert compute_volatility_regime(0.0, cfg) == VolatilityRegime.DEAD
        assert compute_volatility_regime(0.10, cfg) == VolatilityRegime.DEAD
        assert compute_volatility_regime(0.15, cfg) == VolatilityRegime.DEAD
        assert compute_volatility_regime(0.16, cfg) == VolatilityRegime.LOW
    
    def test_low_vol_boundary(self):
        """Test low vol regime (0.15-0.30)."""
        cfg = SentimentVolConfig()
        
        assert compute_volatility_regime(0.20, cfg) == VolatilityRegime.LOW
        assert compute_volatility_regime(0.30, cfg) == VolatilityRegime.LOW
        assert compute_volatility_regime(0.31, cfg) == VolatilityRegime.TARGET
    
    def test_target_vol_boundary(self):
        """Test target vol regime (0.30-0.70)."""
        cfg = SentimentVolConfig()
        
        assert compute_volatility_regime(0.31, cfg) == VolatilityRegime.TARGET
        assert compute_volatility_regime(0.50, cfg) == VolatilityRegime.TARGET
        # 0.70 is boundary - >= VOL_HIGH_MIN (0.70) means HIGH
        assert compute_volatility_regime(0.69, cfg) == VolatilityRegime.TARGET
        assert compute_volatility_regime(0.70, cfg) == VolatilityRegime.HIGH
        assert compute_volatility_regime(0.71, cfg) == VolatilityRegime.HIGH
    
    def test_high_vol_boundary(self):
        """Test high vol regime (0.70-1.20)."""
        cfg = SentimentVolConfig()
        
        # 0.70 is boundary - >= VOL_HIGH_MIN (0.70) means HIGH
        assert compute_volatility_regime(0.70, cfg) == VolatilityRegime.HIGH
        assert compute_volatility_regime(0.71, cfg) == VolatilityRegime.HIGH
        assert compute_volatility_regime(1.00, cfg) == VolatilityRegime.HIGH
        # 1.20 is boundary - >= VOL_EXTREME_MIN (1.20) means EXTREME
        assert compute_volatility_regime(1.19, cfg) == VolatilityRegime.HIGH
        assert compute_volatility_regime(1.20, cfg) == VolatilityRegime.EXTREME
        assert compute_volatility_regime(1.21, cfg) == VolatilityRegime.EXTREME
    
    def test_extreme_vol_boundary(self):
        """Test extreme vol regime (> 1.20)."""
        cfg = SentimentVolConfig()
        
        assert compute_volatility_regime(1.21, cfg) == VolatilityRegime.EXTREME
        assert compute_volatility_regime(2.00, cfg) == VolatilityRegime.EXTREME


class TestUncertaintyRegimeClassification:
    """Test uncertainty (vol-of-vol) classification."""
    
    def test_stable_uncertainty(self):
        """Test stable uncertainty regime (< 0.20)."""
        cfg = SentimentVolConfig()
        
        assert compute_uncertainty_regime(0.0, cfg) == UncertaintyRegime.STABLE
        assert compute_uncertainty_regime(0.15, cfg) == UncertaintyRegime.STABLE
        assert compute_uncertainty_regime(0.20, cfg) == UncertaintyRegime.STABLE
        assert compute_uncertainty_regime(0.21, cfg) == UncertaintyRegime.ELEVATED
    
    def test_elevated_uncertainty(self):
        """Test elevated uncertainty regime (0.20-0.40)."""
        cfg = SentimentVolConfig()
        
        assert compute_uncertainty_regime(0.21, cfg) == UncertaintyRegime.ELEVATED
        assert compute_uncertainty_regime(0.30, cfg) == UncertaintyRegime.ELEVATED
        assert compute_uncertainty_regime(0.40, cfg) == UncertaintyRegime.ELEVATED
        assert compute_uncertainty_regime(0.41, cfg) == UncertaintyRegime.UNSTABLE
    
    def test_unstable_uncertainty(self):
        """Test unstable uncertainty regime (> 0.40)."""
        cfg = SentimentVolConfig()
        
        assert compute_uncertainty_regime(0.41, cfg) == UncertaintyRegime.UNSTABLE
        assert compute_uncertainty_regime(0.80, cfg) == UncertaintyRegime.UNSTABLE
        assert compute_uncertainty_regime(1.00, cfg) == UncertaintyRegime.UNSTABLE


# ═══════════════════════════════════════════════════════════════════════════
# SentimentScalar Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentScalar:
    """Tests for sentiment volatility types."""
    
    def test_value_clamping(self):
        """Test that values are clamped to 0-100."""
        # Below 0 should clamp to 0
        s1 = create_sentiment_scalar(-10)
        assert s1.value == 0.0
        
        # Above 100 should clamp to 100
        s2 = create_sentiment_scalar(150)
        assert s2.value == 100.0
        
        # Within range stays same
        s3 = create_sentiment_scalar(50)
        assert s3.value == 50.0
    
    def test_confidence_clamping(self):
        """Test that confidence is clamped to 0-1."""
        s1 = SentimentScalar(value=50, regime=FearGreedRegime.NEUTRAL, confidence=-0.5)
        assert s1.confidence == 0.0
        
        s2 = SentimentScalar(value=50, regime=FearGreedRegime.NEUTRAL, confidence=1.5)
        assert s2.confidence == 1.0
    
    def test_is_extreme(self):
        """Test extreme detection."""
        extreme_fear = create_sentiment_scalar(10)
        assert extreme_fear.is_extreme() is True
        
        extreme_greed = create_sentiment_scalar(90)
        assert extreme_greed.is_extreme() is True
        
        neutral = create_sentiment_scalar(50)
        assert neutral.is_extreme() is False
        
        fear = create_sentiment_scalar(30)
        assert fear.is_extreme() is False
    
    def test_contrarian_signal(self):
        """Test contrarian signal generation."""
        extreme_fear = create_sentiment_scalar(10)
        assert extreme_fear.get_contrarian_signal() == "bullish_contrarian"
        
        extreme_greed = create_sentiment_scalar(90)
        assert extreme_greed.get_contrarian_signal() == "bearish_contrarian"
        
        neutral = create_sentiment_scalar(50)
        assert neutral.get_contrarian_signal() == "neutral"
    
    def test_to_dict(self):
        """Test serialization."""
        s = create_sentiment_scalar(75, confidence=0.8, source="cfgi")
        d = s.to_dict()
        
        assert d["value"] == 75.0
        # Value 75 is at EXTREME_GREED boundary (>=75)
        assert d["regime"] == "extreme_greed"
        assert d["confidence"] == 0.8
        assert d["source"] == "cfgi"
        assert "is_extreme" in d
        assert "contrarian_signal" in d


# ═══════════════════════════════════════════════════════════════════════════
# VolatilityScalar Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolatilityScalar:
    """Test VolatilityScalar dataclass."""
    
    def test_value_non_negative(self):
        """Test that negative vol values are clamped to 0."""
        v = VolatilityScalar(value=-0.1, regime=VolatilityRegime.DEAD)
        assert v.value == 0.0
    
    def test_is_tradeable(self):
        """Test tradeability detection."""
        dead = create_volatility_scalar(0.10)
        assert dead.is_tradeable() is False
        
        extreme = create_volatility_scalar(1.50)
        assert extreme.is_tradeable() is False
        
        target = create_volatility_scalar(0.50)
        assert target.is_tradeable() is True
        
        high = create_volatility_scalar(0.80)
        assert high.is_tradeable() is True
    
    def test_requires_size_reduction(self):
        """Test size reduction flag."""
        target = create_volatility_scalar(0.50)
        assert target.requires_size_reduction() is False
        
        high = create_volatility_scalar(0.80)
        assert high.requires_size_reduction() is True
        
        extreme = create_volatility_scalar(1.50)
        assert extreme.requires_size_reduction() is True


# ═══════════════════════════════════════════════════════════════════════════
# SizingMultiplier Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSizingMultiplier:
    """Test SizingMultiplier dataclass."""
    
    def test_value_clamping(self):
        """Test that multiplier values respect config floor/ceiling."""
        cfg = SentimentVolConfig()
        
        # Below floor should clamp up
        m1 = SizingMultiplier(
            value=0.05,
            sentiment_contribution=0.6,
            volatility_contribution=0.1,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert m1.value == pytest.approx(cfg.SIZING_MULT_FLOOR)
        
        # Above ceiling should clamp down
        m2 = SizingMultiplier(
            value=2.0,
            sentiment_contribution=1.5,
            volatility_contribution=1.0,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert m2.value == pytest.approx(cfg.SIZING_MULT_CEILING)
    
    def test_apply_to_size(self):
        """Test applying multiplier to base size."""
        m = SizingMultiplier(
            value=0.6,
            sentiment_contribution=0.6,
            volatility_contribution=1.0,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        
        assert m.apply_to_size(1000.0) == 600.0
        assert m.apply_to_size(500.0) == 300.0
        assert m.apply_to_size(0.0) == 0.0
    
    def test_regime_labels(self):
        """Test regime label generation."""
        cfg = SentimentVolConfig()
        
        halted = SizingMultiplier(
            value=cfg.SIZING_MULT_EXTREME_VOL,
            sentiment_contribution=0.3,
            volatility_contribution=0.3,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert halted.get_regime_label() == "HALTED"
        
        downsized = SizingMultiplier(
            value=cfg.SIZING_MULT_HIGH_VOL,
            sentiment_contribution=0.7,
            volatility_contribution=0.7,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert downsized.get_regime_label() == "DOWNSIZED"
        
        boosted = SizingMultiplier(
            value=cfg.SIZING_MULT_LOW_VOL,
            sentiment_contribution=1.1,
            volatility_contribution=1.1,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert boosted.get_regime_label() == "BOOSTED"
        
        normal = SizingMultiplier(
            value=1.0,
            sentiment_contribution=1.0,
            volatility_contribution=1.0,
            uncertainty_contribution=1.0,
            confidence_contribution=1.0,
        )
        assert normal.get_regime_label() == "NORMAL"


# ═══════════════════════════════════════════════════════════════════════════
# Multiplier Computation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentMultiplierComputation:
    """Test sentiment multiplier computation."""
    
    def test_extreme_sentiment_multiplier(self):
        """Test multiplier in extreme sentiment regimes."""
        cfg = SentimentVolConfig()
        
        extreme_fear = create_sentiment_scalar(10)
        mult = compute_sentiment_multiplier(extreme_fear, is_contrarian=False, config=cfg)
        # Extreme regime with full confidence should be ~0.6 * 1.0 = 0.6
        assert mult == pytest.approx(cfg.SIZING_MULT_EXTREME_SENTIMENT, rel=0.01)
    
    def test_fear_greed_multiplier(self):
        """Test multiplier in fear/greed (non-extreme) regimes."""
        cfg = SentimentVolConfig()
        
        fear = create_sentiment_scalar(30)
        mult = compute_sentiment_multiplier(fear, is_contrarian=False, config=cfg)
        # Fear regime with full confidence should be ~0.8 * 1.0 = 0.8
        assert mult == pytest.approx(cfg.SIZING_MULT_FEAR_GREED, rel=0.01)
    
    def test_neutral_multiplier(self):
        """Test multiplier in neutral regime."""
        cfg = SentimentVolConfig()
        
        neutral = create_sentiment_scalar(50)
        mult = compute_sentiment_multiplier(neutral, is_contrarian=False, config=cfg)
        # Neutral with full confidence should be 1.0 * 1.0 = 1.0
        assert mult == pytest.approx(cfg.SIZING_MULT_NEUTRAL, rel=0.01)
    
    def test_contrarian_boost(self):
        """Test contrarian boost in extremes."""
        cfg = SentimentVolConfig()
        
        extreme_fear = create_sentiment_scalar(10)
        
        non_contrarian = compute_sentiment_multiplier(extreme_fear, is_contrarian=False, config=cfg)
        contrarian = compute_sentiment_multiplier(extreme_fear, is_contrarian=True, config=cfg)
        
        # Contrarian should get boost
        assert contrarian > non_contrarian
        assert contrarian == pytest.approx(non_contrarian * cfg.CONTRARIAN_BOOST, rel=0.01)
    
    def test_low_confidence_scaling(self):
        """Test that low confidence reduces multiplier."""
        cfg = SentimentVolConfig()
        
        high_conf = SentimentScalar(value=50, regime=FearGreedRegime.NEUTRAL, confidence=1.0)
        low_conf = SentimentScalar(value=50, regime=FearGreedRegime.NEUTRAL, confidence=0.0)
        
        high_mult = compute_sentiment_multiplier(high_conf, is_contrarian=False, config=cfg)
        low_mult = compute_sentiment_multiplier(low_conf, is_contrarian=False, config=cfg)
        
        # Low confidence should have lower multiplier
        assert low_mult < high_mult
        # Difference should be the confidence scale max (0.5)
        assert high_mult == pytest.approx(low_mult + cfg.CONFIDENCE_SCALE_MAX, rel=0.01)


class TestVolatilityMultiplierComputation:
    """Test volatility multiplier computation."""
    
    def test_dead_vol_multiplier(self):
        """Test multiplier for dead market (low vol)."""
        cfg = SentimentVolConfig()
        
        dead = create_volatility_scalar(0.10)
        mult = compute_volatility_multiplier(dead, config=cfg)
        assert mult == pytest.approx(cfg.SIZING_MULT_DEAD_VOL, rel=0.01)
    
    def test_low_vol_multiplier(self):
        """Test multiplier for low vol regime (size boost)."""
        cfg = SentimentVolConfig()
        
        low = create_volatility_scalar(0.20)
        mult = compute_volatility_multiplier(low, config=cfg)
        # Low vol should have boost (> 1.0)
        assert mult > 1.0
        assert mult == pytest.approx(cfg.SIZING_MULT_LOW_VOL, rel=0.01)
    
    def test_target_vol_multiplier(self):
        """Test multiplier for target vol regime."""
        cfg = SentimentVolConfig()
        
        target = create_volatility_scalar(0.50)
        mult = compute_volatility_multiplier(target, config=cfg)
        assert mult == pytest.approx(cfg.SIZING_MULT_TARGET_VOL, rel=0.01)
    
    def test_high_vol_multiplier(self):
        """Test multiplier for high vol regime."""
        cfg = SentimentVolConfig()
        
        high = create_volatility_scalar(0.80)
        mult = compute_volatility_multiplier(high, config=cfg)
        assert mult == pytest.approx(cfg.SIZING_MULT_HIGH_VOL, rel=0.01)
    
    def test_extreme_vol_multiplier(self):
        """Test multiplier for extreme vol regime."""
        cfg = SentimentVolConfig()
        
        extreme = create_volatility_scalar(1.50)
        mult = compute_volatility_multiplier(extreme, config=cfg)
        assert mult == pytest.approx(cfg.SIZING_MULT_EXTREME_VOL, rel=0.01)
    
    def test_uncertainty_penalty_elevated(self):
        """Test uncertainty penalty for elevated vol-of-vol."""
        cfg = SentimentVolConfig()
        
        stable = create_volatility_scalar(0.50, uncertainty=0.1)
        elevated = create_volatility_scalar(0.50, uncertainty=0.3)
        
        stable_mult = compute_volatility_multiplier(stable, config=cfg)
        elevated_mult = compute_volatility_multiplier(elevated, config=cfg)
        
        # Elevated should be penalized
        assert elevated_mult < stable_mult
        assert elevated_mult == pytest.approx(stable_mult * cfg.UNCERTAINTY_ELEVATED_PENALTY, rel=0.01)
    
    def test_uncertainty_penalty_unstable(self):
        """Test uncertainty penalty for unstable vol-of-vol."""
        cfg = SentimentVolConfig()
        
        stable = create_volatility_scalar(0.50, uncertainty=0.1)
        unstable = create_volatility_scalar(0.50, uncertainty=0.5)
        
        stable_mult = compute_volatility_multiplier(stable, config=cfg)
        unstable_mult = compute_volatility_multiplier(unstable, config=cfg)
        
        # Unstable should be penalized more than stable
        assert unstable_mult < stable_mult
        assert unstable_mult == pytest.approx(stable_mult * cfg.UNCERTAINTY_UNSTABLE_PENALTY, rel=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Integration: Full Sizing Multiplier Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFullSizingMultiplier:
    """Test complete sizing multiplier computation."""
    
    def test_neutral_target_regime(self):
        """Test sizing multiplier in neutral sentiment + target vol."""
        sentiment = create_sentiment_scalar(50)  # Neutral
        volatility = create_volatility_scalar(0.50)  # Target
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        # Neutral (1.0) * Target (1.0) = 1.0
        assert mult.value == pytest.approx(1.0, rel=0.05)
        assert mult.get_regime_label() == "NORMAL"
    
    def test_extreme_fear_high_vol(self):
        """Test sizing multiplier in extreme fear + high vol."""
        cfg = SentimentVolConfig()
        
        sentiment = create_sentiment_scalar(10)  # Extreme fear
        volatility = create_volatility_scalar(0.80)  # High vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False, config=cfg)
        
        # Extreme sentiment (0.6) * High vol (0.7) = 0.42
        expected = cfg.SIZING_MULT_EXTREME_SENTIMENT * cfg.SIZING_MULT_HIGH_VOL
        assert mult.value == pytest.approx(expected, rel=0.05)
        assert mult.get_regime_label() == "DOWNSIZED"
    
    def test_contrarian_in_extreme_fear(self):
        """Test sizing multiplier for contrarian position in extreme fear."""
        cfg = SentimentVolConfig()
        
        sentiment = create_sentiment_scalar(10)  # Extreme fear
        volatility = create_volatility_scalar(0.50)  # Target vol
        
        non_contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False, config=cfg)
        contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=True, config=cfg)
        
        # Contrarian should be higher due to boost
        assert contrarian.value > non_contrarian.value
        # Boost is only applied to sentiment portion
    
    def test_low_confidence_high_uncertainty(self):
        """Test sizing multiplier with low confidence + high uncertainty."""
        cfg = SentimentVolConfig()
        
        sentiment = SentimentScalar(
            value=50,
            regime=FearGreedRegime.NEUTRAL,
            confidence=0.5,  # Low confidence
        )
        volatility = create_volatility_scalar(0.50, uncertainty=0.5)  # Unstable
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False, config=cfg)
        
        # Both confidence and uncertainty penalties apply
        # Neutral sentiment scaled by confidence (0.5 base + 0.5*0.5 = 0.75)
        # Target vol with unstable penalty (1.0 * 0.65 = 0.65)
        # Expected: 0.75 * 0.65 = ~0.49
        assert mult.value < 1.0
        assert mult.uncertainty_contribution < 1.0
        assert mult.confidence_contribution < 1.0
    
    def test_dead_market(self):
        """Test sizing multiplier in dead market (very low vol)."""
        cfg = SentimentVolConfig()
        
        sentiment = create_sentiment_scalar(50)
        volatility = create_volatility_scalar(0.10)  # Dead market
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False, config=cfg)
        
        # Dead vol reduces size significantly (0.50 multiplier for neutral + dead vol)
        assert mult.value == pytest.approx(cfg.SIZING_MULT_DEAD_VOL, rel=0.05)
        # 0.50 is > EXTREME_VOL (0.30) so it's DOWNSIZED, not HALTED
        assert mult.get_regime_label() == "DOWNSIZED"
    
    def test_extreme_vol_halt(self):
        """Test sizing multiplier in extreme volatility (market chaos)."""
        cfg = SentimentVolConfig()
        
        sentiment = create_sentiment_scalar(50)  # Neutral
        volatility = create_volatility_scalar(1.50)  # Extreme vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False, config=cfg)
        
        # Extreme vol should force halt/near-halt
        assert mult.value == pytest.approx(cfg.SIZING_MULT_EXTREME_VOL, rel=0.05)
        assert mult.get_regime_label() == "HALTED"
    
    def test_reasoning_includes_all_factors(self):
        """Test that reasoning string includes all relevant factors."""
        sentiment = create_sentiment_scalar(10)  # Extreme fear
        volatility = create_volatility_scalar(0.80, uncertainty=0.5)  # High + unstable
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=True)
        
        reasoning = mult.reasoning
        assert "extreme_fear" in reasoning or "sentiment" in reasoning
        assert "vol_" in reasoning
        assert "uncertainty_unstable" in reasoning
        assert "contrarian" in reasoning


# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases and Boundary Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_zero_volatility(self):
        """Test handling of zero volatility."""
        vol = create_volatility_scalar(0.0)
        assert vol.regime == VolatilityRegime.DEAD
        assert not vol.is_tradeable()
    
    def test_very_high_volatility(self):
        """Test handling of very high volatility."""
        vol = create_volatility_scalar(5.0)  # 500% annualized
        assert vol.regime == VolatilityRegime.EXTREME
        assert not vol.is_tradeable()
    
    def test_sentiment_boundary_exact(self):
        """Test exact boundary values for sentiment."""
        cfg = SentimentVolConfig()
        
        # Test at exact threshold
        at_extreme_fear_max = create_sentiment_scalar(cfg.EXTREME_FEAR_MAX)
        assert at_extreme_fear_max.regime == FearGreedRegime.EXTREME_FEAR
        
        just_above = create_sentiment_scalar(cfg.EXTREME_FEAR_MAX + 1)
        assert just_above.regime == FearGreedRegime.FEAR
    
    def test_vol_boundary_exact(self):
        """Test exact boundary values for volatility."""
        cfg = SentimentVolConfig()
        
        # Test at exact threshold
        at_dead_max = create_volatility_scalar(cfg.VOL_DEAD_MAX)
        assert at_dead_max.regime == VolatilityRegime.DEAD
        
        just_above = create_volatility_scalar(cfg.VOL_DEAD_MAX + 0.01)
        assert just_above.regime == VolatilityRegime.LOW
    
    def test_synthetic_sentiment(self):
        """Test synthetic sentiment flag."""
        synthetic = SentimentScalar(
            value=50,
            regime=FearGreedRegime.NEUTRAL,
            is_synthetic=True,
        )
        assert synthetic.is_synthetic is True
        
        d = synthetic.to_dict()
        assert d["is_synthetic"] is True
    
    def test_mult_floor_ceil_respected(self):
        """Test that hard floor and ceiling are always respected."""
        cfg = SentimentVolConfig()
        
        # Create a multiplier that would naturally exceed ceiling
        extreme_sentiment = SentimentScalar(value=10, regime=FearGreedRegime.EXTREME_FEAR, confidence=1.0)
        low_vol = create_volatility_scalar(0.20)  # Gets boost
        
        mult = compute_sizing_multiplier(extreme_sentiment, low_vol, is_contrarian=True)
        
        # Even with boost, should not exceed ceiling
        assert mult.value <= cfg.SIZING_MULT_CEILING
        
        # Create scenario that would naturally go below floor
        extreme_sentiment_2 = SentimentScalar(value=10, regime=FearGreedRegime.EXTREME_FEAR, confidence=0.0)
        extreme_vol = create_volatility_scalar(2.0)
        unstable = VolatilityScalar(
            value=2.0,
            regime=VolatilityRegime.EXTREME,
            uncertainty=0.5,
            uncertainty_regime=UncertaintyRegime.UNSTABLE,
        )
        
        mult_2 = compute_sizing_multiplier(extreme_sentiment_2, unstable, is_contrarian=False)
        
        # Should not go below floor
        assert mult_2.value >= cfg.SIZING_MULT_FLOOR


# ═══════════════════════════════════════════════════════════════════════════
# Config Validation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigValidation:
    """Test SentimentVolConfig validation."""
    
    def test_default_config_valid(self):
        """Test that default config passes validation."""
        cfg = SentimentVolConfig()
        errors = cfg.validate()
        assert errors == []
    
    def test_invalid_sentiment_ordering(self):
        """Test detection of invalid sentiment threshold ordering."""
        cfg = SentimentVolConfig()
        
        # Temporarily monkey-patch to create invalid config
        object.__setattr__(cfg, 'EXTREME_FEAR_MAX', 80)  # Too high
        
        errors = cfg.validate()
        assert len(errors) > 0
        assert any("ordering" in err.lower() for err in errors)
    
    def test_invalid_vol_ordering(self):
        """Test detection of invalid volatility threshold ordering."""
        cfg = SentimentVolConfig()
        
        # Create invalid config where LOW > HIGH
        object.__setattr__(cfg, 'VOL_LOW_MAX', 1.0)
        object.__setattr__(cfg, 'VOL_HIGH_MIN', 0.5)
        
        errors = cfg.validate()
        assert len(errors) > 0
        assert any("ordering" in err.lower() for err in errors)
    
    def test_invalid_multiplier_range(self):
        """Test detection of out-of-range multipliers."""
        cfg = SentimentVolConfig()
        
        # Extreme multiplier too high
        object.__setattr__(cfg, 'SIZING_MULT_EXTREME_SENTIMENT', 1.5)
        
        errors = cfg.validate()
        assert len(errors) > 0
        assert any("extreme" in err.lower() or "sizing" in err.lower() for err in errors)


# ═══════════════════════════════════════════════════════════════════════════
# Factory Function Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFactoryFunctions:
    """Test the create_* factory functions."""
    
    def test_create_sentiment_scalar_auto_classifies(self):
        """Test that create_sentiment_scalar auto-classifies regime."""
        s = create_sentiment_scalar(10)
        assert s.regime == FearGreedRegime.EXTREME_FEAR
        
        s2 = create_sentiment_scalar(50)
        assert s2.regime == FearGreedRegime.NEUTRAL
        
        s3 = create_sentiment_scalar(90)
        assert s3.regime == FearGreedRegime.EXTREME_GREED
    
    def test_create_sentiment_scalar_preserves_metadata(self):
        """Test that factory preserves source and raw data."""
        raw = {"api_response": "test"}
        s = create_sentiment_scalar(
            value=50,
            confidence=0.8,
            source="cfgi",
            is_synthetic=True,
            raw_data=raw,
        )
        
        assert s.source == "cfgi"
        assert s.confidence == 0.8
        assert s.is_synthetic is True
        assert s.raw_data == raw
    
    def test_create_volatility_scalar_auto_classifies(self):
        """Test that create_volatility_scalar auto-classifies regime."""
        v = create_volatility_scalar(0.10)
        assert v.regime == VolatilityRegime.DEAD
        
        v2 = create_volatility_scalar(0.50)
        assert v2.regime == VolatilityRegime.TARGET
        
        v3 = create_volatility_scalar(1.50)
        assert v3.regime == VolatilityRegime.EXTREME
    
    def test_create_volatility_scalar_uncertainty_regime(self):
        """Test uncertainty regime classification in factory."""
        v = create_volatility_scalar(0.50, uncertainty=0.1)
        assert v.uncertainty_regime == UncertaintyRegime.STABLE
        
        v2 = create_volatility_scalar(0.50, uncertainty=0.3)
        assert v2.uncertainty_regime == UncertaintyRegime.ELEVATED
        
        v3 = create_volatility_scalar(0.50, uncertainty=0.5)
        assert v3.uncertainty_regime == UncertaintyRegime.UNSTABLE
