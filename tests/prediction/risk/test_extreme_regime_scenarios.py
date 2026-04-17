"""
Scenario Tests for Extreme Fear/Greed and Volatility Regimes

These tests validate that the sizing multiplier behaves correctly under
extreme market conditions, ensuring proper risk reduction and contrarian
opportunity detection.

Test scenarios cover:
- Extreme fear (FGI <= 20)
- Extreme greed (FGI >= 80)
- Extreme volatility (annualized vol >= 120%)
- Combinations of extreme sentiment and volatility
- Contrarian vs non-contrarian sizing decisions
"""

import pytest
import time
from typing import List, Tuple

from merid.prediction.risk import (
    SentimentScalar,
    VolatilityScalar,
    SizingMultiplier,
    FearGreedRegime,
    VolatilityRegime,
    UncertaintyRegime,
    get_sentiment_vol_service,
    compute_sizing_multiplier,
    create_sentiment_scalar,
    create_volatility_scalar,
    get_sentiment_vol_config,
)


# ═══════════════════════════════════════════════════════════════════════════
# Scenario Test Data
# ═══════════════════════════════════════════════════════════════════════════

# Extreme fear scenarios (FGI 0-20)
EXTREME_FEAR_SCENARIOS = [
    (10, 0.9, "panic_selling"),   # Severe panic
    (15, 0.8, "capitulation"),    # Capitulation
    (20, 1.0, "extreme_fear_boundary"),  # At boundary
]

# Fear scenarios (FGI 21-45)
FEAR_SCENARIOS = [
    (25, 0.9, "anxiety"),
    (35, 0.85, "fear"),
    (45, 1.0, "fear_boundary"),
]

# Neutral scenarios (FGI 46-54)
NEUTRAL_SCENARIOS = [
    (50, 1.0, "neutral_center"),
]

# Greed scenarios (FGI 55-79)
GREED_SCENARIOS = [
    (55, 1.0, "greed_boundary"),
    (65, 0.85, "greed"),
    (75, 0.9, "euphoria"),
]

# Extreme greed scenarios (FGI 80-100)
EXTREME_GREED_SCENARIOS = [
    (80, 1.0, "extreme_greed_boundary"),
    (85, 0.9, "mania"),
    (95, 0.8, "bubble"),
]

# Volatility scenarios
VOL_SCENARIOS = [
    # (vol_value, regime, description)
    (0.05, VolatilityRegime.DEAD, "dead_low_vol"),
    (0.12, VolatilityRegime.DEAD, "near_dead_boundary"),
    (0.20, VolatilityRegime.LOW, "low_vol"),
    (0.40, VolatilityRegime.TARGET, "target_vol"),
    (0.60, VolatilityRegime.TARGET, "near_high_boundary"),
    (0.80, VolatilityRegime.HIGH, "high_vol"),
    (1.20, VolatilityRegime.EXTREME, "extreme_vol_boundary"),
    (2.00, VolatilityRegime.EXTREME, "hyper_volatility"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Extreme Regime Test Cases
# ═══════════════════════════════════════════════════════════════════════════

class TestExtremeFearRegime:
    """Test sizing behavior under extreme fear conditions."""
    
    def test_extreme_fear_reduces_size(self):
        """Extreme fear should significantly reduce position size."""
        sentiment = create_sentiment_scalar(value=15, confidence=0.9)
        volatility = create_volatility_scalar(value=0.50)  # Normal vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value < 0.7, f"Expected < 0.7, got {mult.value}"
        assert mult.sentiment_contribution < 0.8
        assert "extreme_fear" in mult.reasoning.lower() or "fear" in mult.reasoning.lower()
    
    def test_extreme_fear_contrarian_boost(self):
        """Contrarian positions should get boost in extreme fear."""
        sentiment = create_sentiment_scalar(value=15, confidence=0.9)
        volatility = create_volatility_scalar(value=0.50)
        
        non_contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=True)
        
        assert contrarian.value > non_contrarian.value, \
            f"Contrarian {contrarian.value} should be > non-contrarian {non_contrarian.value}"
    
    @pytest.mark.parametrize("fgi,confidence,scenario", EXTREME_FEAR_SCENARIOS)
    def test_various_extreme_fear_levels(self, fgi, confidence, scenario):
        """Test multiple extreme fear levels."""
        sentiment = create_sentiment_scalar(value=fgi, confidence=confidence)
        volatility = create_volatility_scalar(value=0.50)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        # Should always be reduced
        assert mult.value <= 1.0, f"Scenario {scenario}: {mult.value} should be <= 1.0"
        assert mult.value >= 0.2, f"Scenario {scenario}: should respect floor"
        
        # Regime classification
        assert sentiment.regime == FearGreedRegime.EXTREME_FEAR


class TestExtremeGreedRegime:
    """Test sizing behavior under extreme greed conditions."""
    
    def test_extreme_greed_reduces_size(self):
        """Extreme greed should significantly reduce position size."""
        sentiment = create_sentiment_scalar(value=85, confidence=0.9)
        volatility = create_volatility_scalar(value=0.50)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value < 0.7, f"Expected < 0.7, got {mult.value}"
        assert mult.sentiment_contribution < 0.8
    
    def test_extreme_greed_contrarian_boost(self):
        """Contrarian positions should get boost in extreme greed."""
        sentiment = create_sentiment_scalar(value=85, confidence=0.9)
        volatility = create_volatility_scalar(value=0.50)
        
        non_contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=True)
        
        assert contrarian.value > non_contrarian.value, \
            f"Contrarian {contrarian.value} should be > non-contrarian {non_contrarian.value}"
    
    @pytest.mark.parametrize("fgi,confidence,scenario", EXTREME_GREED_SCENARIOS)
    def test_various_extreme_greed_levels(self, fgi, confidence, scenario):
        """Test multiple extreme greed levels."""
        sentiment = create_sentiment_scalar(value=fgi, confidence=confidence)
        volatility = create_volatility_scalar(value=0.50)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value <= 1.0, f"Scenario {scenario}: {mult.value} should be <= 1.0"
        assert mult.value >= 0.2, f"Scenario {scenario}: should respect floor"
        
        assert sentiment.regime == FearGreedRegime.EXTREME_GREED


class TestExtremeVolatilityRegime:
    """Test sizing behavior under extreme volatility conditions."""
    
    def test_extreme_volatility_reduces_size(self):
        """Extreme volatility should severely reduce position size."""
        sentiment = create_sentiment_scalar(value=50)  # Neutral sentiment
        volatility = create_volatility_scalar(value=1.50, uncertainty=0.5)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value < 0.5, f"Expected < 0.5, got {mult.value}"
        assert mult.volatility_contribution < 0.5
    
    def test_high_volatility_reduces_size(self):
        """High volatility should reduce position size."""
        sentiment = create_sentiment_scalar(value=50)
        volatility = create_volatility_scalar(value=0.80)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value < 0.8, f"Expected < 0.8, got {mult.value}"
    
    def test_dead_volatility_reduces_size(self):
        """Dead/low volatility should reduce position size."""
        sentiment = create_sentiment_scalar(value=50)
        volatility = create_volatility_scalar(value=0.10)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value < 0.8, f"Expected < 0.8, got {mult.value}"
    
    @pytest.mark.parametrize("vol_value,regime,scenario", VOL_SCENARIOS)
    def test_various_volatility_levels(self, vol_value, regime, scenario):
        """Test multiple volatility levels."""
        sentiment = create_sentiment_scalar(value=50)
        volatility = create_volatility_scalar(value=vol_value)
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        # Volatility multiplier should always be within bounds
        assert 0.2 <= mult.volatility_contribution <= 1.2
        assert volatility.regime == regime


# ═══════════════════════════════════════════════════════════════════════════
# Combined Extreme Regime Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCombinedExtremeRegimes:
    """Test sizing when both sentiment and volatility are extreme."""
    
    def test_extreme_fear_plus_extreme_vol(self):
        """Extreme fear + extreme vol should result in minimal sizing."""
        sentiment = create_sentiment_scalar(value=10)  # Extreme fear
        volatility = create_volatility_scalar(value=1.50)  # Extreme vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        # Should be at or near floor
        assert mult.value <= 0.3, f"Expected <= 0.3, got {mult.value}"
        assert mult.get_regime_label() == "HALTED"
    
    def test_extreme_greed_plus_extreme_vol(self):
        """Extreme greed + extreme vol should result in minimal sizing."""
        sentiment = create_sentiment_scalar(value=90)  # Extreme greed
        volatility = create_volatility_scalar(value=1.50)  # Extreme vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        assert mult.value <= 0.3, f"Expected <= 0.3, got {mult.value}"
    
    def test_extreme_fear_plus_high_vol_contrarian(self):
        """Contrarian opportunity in extreme fear + high vol."""
        sentiment = create_sentiment_scalar(value=15)  # Extreme fear
        volatility = create_volatility_scalar(value=0.80)  # High vol
        
        non_contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        contrarian = compute_sizing_multiplier(sentiment, volatility, is_contrarian=True)
        
        # Even with vol penalty, contrarian should be higher
        assert contrarian.value > non_contrarian.value
    
    def test_neutral_plus_extreme_vol(self):
        """Neutral sentiment doesn't offset extreme volatility."""
        sentiment = create_sentiment_scalar(value=50)  # Neutral
        volatility = create_volatility_scalar(value=2.00)  # Hyper vol
        
        mult = compute_sizing_multiplier(sentiment, volatility, is_contrarian=False)
        
        # Vol dominates
        assert mult.value <= 0.3, f"Expected <= 0.3, got {mult.value}"


# ═══════════════════════════════════════════════════════════════════════════
# Service Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestServiceExtremeScenarios:
    """Test the service end-to-end with extreme scenarios."""
    
    def test_service_extreme_fear_flow(self):
        """Full flow: update to extreme fear, verify sizing reduction."""
        svc = get_sentiment_vol_service()
        
        # Register and update
        svc.register_asset("BTC")
        svc.update_sentiment("BTC", value=10, confidence=0.9, source="test")
        svc.update_volatility_direct("BTC", annualized_vol=0.50, confidence=1.0)
        
        mult = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        
        assert mult.value < 0.7, f"Expected reduced sizing, got {mult.value}"
        assert "fear" in mult.reasoning.lower()
    
    def test_service_contrarian_boost_flow(self):
        """Full flow: verify contrarian boost in extreme fear."""
        svc = get_sentiment_vol_service()
        
        svc.register_asset("ETH")
        svc.update_sentiment("ETH", value=15, confidence=0.9)
        svc.update_volatility_direct("ETH", annualized_vol=0.50)
        
        regular = svc.get_sizing_multiplier("ETH", is_contrarian=False)
        contrarian = svc.get_sizing_multiplier("ETH", is_contrarian=True)
        
        assert contrarian.value > regular.value
        assert contrarian.value > 0.6  # Should still be reasonable
    
    def test_service_stale_data_handling(self):
        """Service should handle stale data gracefully."""
        svc = get_sentiment_vol_service()
        
        svc.register_asset("SOL")
        # Don't update - data is stale/missing
        
        # Should return fallback multiplier
        mult = svc.get_sizing_multiplier("SOL", is_contrarian=False)
        
        assert 0.2 <= mult.value <= 1.2
        assert mult.is_fallback is True
    
    def test_multi_asset_extreme_scenario(self):
        """Multiple assets in different extreme regimes simultaneously."""
        svc = get_sentiment_vol_service()
        
        # BTC in extreme fear
        svc.register_asset("BTC")
        svc.update_sentiment("BTC", value=10)
        svc.update_volatility_direct("BTC", annualized_vol=0.50)
        
        # ETH in extreme greed
        svc.register_asset("ETH")
        svc.update_sentiment("ETH", value=90)
        svc.update_volatility_direct("ETH", annualized_vol=0.50)
        
        # SOL in extreme vol
        svc.register_asset("SOL")
        svc.update_sentiment("SOL", value=50)
        svc.update_volatility_direct("SOL", annualized_vol=1.50)
        
        btc_mult = svc.get_sizing_multiplier("BTC")
        eth_mult = svc.get_sizing_multiplier("ETH")
        sol_mult = svc.get_sizing_multiplier("SOL")
        
        # All should be reduced
        assert btc_mult.value < 1.0
        assert eth_mult.value < 1.0
        assert sol_mult.value < 0.5
        
        # Reasons should differ
        assert "fear" in btc_mult.reasoning.lower()
        assert "greed" in eth_mult.reasoning.lower()
        assert "vol" in sol_mult.reasoning.lower() or "extreme" in sol_mult.reasoning.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Bankroll Impact Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBankrollImpact:
    """Test that sizing multiplier correctly affects bankroll calculations."""
    
    def test_position_sizing_integration(self):
        """Verify position sizer respects sentiment/vol multiplier."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        
        sizer = PositionSizer()
        
        # Base case without sentiment/vol
        size_without = sizer.compute(
            agent_name="BTC_TEST",
            edge_pct=3.0,
            price_cents=55,
            bankroll_cents=1000000,
            profit_factor=1.5,
            expectancy_cents=10,
            total_trades=100,
        )
        
        # With sentiment/vol (would need to set up service data first)
        # This test verifies the parameter exists and is wired
        size_with_param = sizer.compute(
            agent_name="BTC_TEST",
            edge_pct=3.0,
            price_cents=55,
            bankroll_cents=1000000,
            profit_factor=1.5,
            expectancy_cents=10,
            total_trades=100,
            sentiment_vol_asset="BTC",  # Should use service if available
        )
        
        # With no service data, should be same as without
        assert size_with_param == size_without


# ═══════════════════════════════════════════════════════════════════════════
# Edge Case Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_boundary_extreme_fear(self):
        """Test exactly at extreme fear boundary (20)."""
        sentiment = create_sentiment_scalar(value=20)
        
        # At boundary, should be classified as FEAR (not EXTREME_FEAR)
        # per threshold: extreme_fear_max = 25, fear_max = 45
        # Actually looking at config: EXTREME_FEAR_MAX = 25
        # So 20 is in EXTREME_FEAR
        assert sentiment.regime == FearGreedRegime.EXTREME_FEAR
    
    def test_boundary_extreme_greed(self):
        """Test exactly at extreme greed boundary (80)."""
        sentiment = create_sentiment_scalar(value=80)
        
        # extreme_greed_min = 75, so 80 is EXTREME_GREED
        assert sentiment.regime == FearGreedRegime.EXTREME_GREED
    
    def test_zero_volatility(self):
        """Test handling of zero volatility."""
        sentiment = create_sentiment_scalar(value=50)
        volatility = create_volatility_scalar(value=0.0)
        
        mult = compute_sizing_multiplier(sentiment, volatility)
        
        # Should handle gracefully
        assert mult.value >= 0.2
    
    def test_very_high_volatility(self):
        """Test handling of extremely high volatility (>200%)."""
        sentiment = create_sentiment_scalar(value=50)
        volatility = create_volatility_scalar(value=3.00)
        
        mult = compute_sizing_multiplier(sentiment, volatility)
        
        # Should clamp to floor
        assert mult.value >= 0.2
        assert mult.value <= 0.4
    
    def test_confidence_scaling_extreme(self):
        """Test that confidence affects sizing in extreme regimes."""
        high_conf = create_sentiment_scalar(value=10, confidence=1.0)
        low_conf = create_sentiment_scalar(value=10, confidence=0.3)
        volatility = create_volatility_scalar(value=0.50)
        
        mult_high = compute_sizing_multiplier(high_conf, volatility)
        mult_low = compute_sizing_multiplier(low_conf, volatility)
        
        # Low confidence should result in lower multiplier
        assert mult_low.value <= mult_high.value


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_service():
    """Reset service singleton before each test."""
    import merid.prediction.risk.sentiment_vol_service as svc_module
    svc_module._service_instance = None
    yield
    svc_module._service_instance = None
