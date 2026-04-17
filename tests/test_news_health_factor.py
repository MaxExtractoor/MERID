"""Tests for news health factor integration in position sizing.

Validates D6/D7 invariants:
- News feed failures only inform conviction, never block execution
- News degradation reduces sizing but never to zero
"""

import pytest
from datetime import datetime, timezone

from merid.prediction.risk.sentiment_vol_types import (
    SentimentVolConfig,
    SentimentScalar,
    VolatilityScalar,
    FearGreedRegime,
    VolatilityRegime,
    UncertaintyRegime,
    compute_news_health_factor,
    compute_sizing_multiplier,
    create_sentiment_scalar,
    create_volatility_scalar,
    get_sentiment_vol_config,
)


class TestNewsHealthFactor:
    """Test news health factor computation and integration."""

    def test_news_health_healthy(self):
        """Healthy news status returns full factor (1.0)."""
        factor = compute_news_health_factor("healthy")
        assert factor == 1.0

    def test_news_health_stale(self):
        """Stale news returns degraded factor (0.5)."""
        factor = compute_news_health_factor("stale")
        assert factor == 0.5

    def test_news_health_zero_data(self):
        """Zero data news returns degraded factor (0.5)."""
        factor = compute_news_health_factor("zero_data")
        assert factor == 0.5

    def test_news_health_no_matches(self):
        """No matches news returns degraded factor (0.5)."""
        factor = compute_news_health_factor("no_matches")
        assert factor == 0.5

    def test_news_health_error(self):
        """Error news returns degraded factor (0.5)."""
        factor = compute_news_health_factor("error")
        assert factor == 0.5

    def test_news_health_not_configured(self):
        """Not configured news returns degraded factor (0.5)."""
        factor = compute_news_health_factor("not_configured")
        assert factor == 0.5

    def test_news_health_unknown(self):
        """Unknown news status defaults to healthy (1.0)."""
        factor = compute_news_health_factor("unknown")
        assert factor == 1.0

    def test_news_health_never_zero(self):
        """News degradation never returns zero (D6/D7 invariant)."""
        # Even with very low config values, floor should prevent zero
        cfg = SentimentVolConfig(NEWS_HEALTH_FLOOR=0.3)
        
        for status in ["stale", "zero_data", "no_matches", "error", "not_configured"]:
            factor = compute_news_health_factor(status, cfg)
            assert factor > 0, f"Status {status} should never return zero"
            assert factor >= cfg.NEWS_HEALTH_FLOOR, f"Status {status} should respect floor"

    def test_news_health_floor_enforced(self):
        """NEWS_HEALTH_FLOOR is enforced even with extreme degradation."""
        cfg = SentimentVolConfig(NEWS_HEALTH_FLOOR=0.3)
        factor = compute_news_health_factor("error", cfg)
        assert factor >= 0.3


class TestNewsHealthSizingIntegration:
    """Test news health factor integration into sizing multiplier."""

    def setup_method(self):
        """Create standard sentiment and volatility for tests."""
        self.sentiment = create_sentiment_scalar(
            value=50.0,  # Neutral
            confidence=1.0,
            source="cfgi"
        )
        self.volatility = create_volatility_scalar(
            value=0.50,  # Target vol
            uncertainty=0.1,
            source="realized"
        )

    def test_healthy_news_full_sizing(self):
        """Healthy news allows full sizing multiplier."""
        mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="healthy"
        )
        assert mult.news_health_contribution == 1.0
        assert mult.value > 0.8  # Should be near full multiplier

    def test_degraded_news_reduces_sizing(self):
        """Degraded news reduces sizing multiplier."""
        healthy_mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="healthy"
        )
        
        degraded_mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="stale"
        )
        
        # Degraded should be smaller than healthy
        assert degraded_mult.value < healthy_mult.value
        assert degraded_mult.news_health_contribution == 0.5

    def test_news_never_blocks_sizing(self):
        """News degradation never reduces sizing to zero (D6/D7)."""
        for status in ["stale", "zero_data", "no_matches", "error"]:
            mult = compute_sizing_multiplier(
                self.sentiment,
                self.volatility,
                is_contrarian=False,
                news_health_status=status
            )
            assert mult.value > 0, f"Status {status} should never produce zero multiplier"
            assert "news" in mult.reasoning, f"Status {status} should appear in reasoning"

    def test_news_reasoning_included(self):
        """News health appears in sizing reasoning when degraded."""
        mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="zero_data"
        )
        
        assert "news_zero_data" in mult.reasoning
        assert "0.50" in mult.reasoning  # Factor value shown

    def test_news_healthy_not_in_reasoning(self):
        """Healthy news doesn't clutter reasoning."""
        mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="healthy"
        )
        
        assert "news" not in mult.reasoning  # No need to mention healthy

    def test_news_inputs_included(self):
        """News health status included in multiplier inputs."""
        mult = compute_sizing_multiplier(
            self.sentiment,
            self.volatility,
            is_contrarian=False,
            news_health_status="stale"
        )
        
        assert mult.inputs is not None
        assert mult.inputs.get("news_health_status") == "stale"


class TestNewsHealthConfigurability:
    """Test that news health thresholds are configurable."""

    def test_custom_healthy_factor(self):
        """NEWS_HEALTH_HEALTHY is configurable."""
        cfg = SentimentVolConfig(NEWS_HEALTH_HEALTHY=0.9)
        factor = compute_news_health_factor("healthy", cfg)
        assert factor == 0.9

    def test_custom_degraded_factor(self):
        """NEWS_HEALTH_DEGRADED is configurable."""
        cfg = SentimentVolConfig(NEWS_HEALTH_DEGRADED=0.4)
        factor = compute_news_health_factor("stale", cfg)
        assert factor == 0.4

    def test_custom_floor(self):
        """NEWS_HEALTH_FLOOR is enforced."""
        cfg = SentimentVolConfig(
            NEWS_HEALTH_ERROR=0.1,
            NEWS_HEALTH_FLOOR=0.3
        )
        factor = compute_news_health_factor("error", cfg)
        assert factor == 0.3  # Floor enforced, not 0.1


class TestNewsHealthInSentimentVolService:
    """Integration tests with SentimentVolService."""

    def test_service_includes_news_health(self):
        """SentimentVolService.get_sizing_multiplier includes news health."""
        from merid.prediction.risk.sentiment_vol_service import get_sentiment_vol_service
        
        service = get_sentiment_vol_service()
        
        # Ensure asset is registered with some data
        service.update_sentiment("BTC", 50.0, confidence=1.0, source="test")
        
        mult = service.get_sizing_multiplier("BTC", is_contrarian=False)
        
        # Should have news_health_contribution field
        assert hasattr(mult, 'news_health_contribution')
        assert mult.news_health_contribution > 0
        assert mult.news_health_contribution <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
