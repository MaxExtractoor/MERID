"""
Tests for SentimentVolService

Tests the centralized service for sentiment, volatility, and sizing.
"""

import pytest
import time
import threading
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from merid.prediction.risk.sentiment_vol_service import (
    SentimentVolService,
    get_sentiment_vol_service,
    calculate_realized_volatility,
    calculate_vol_of_vol,
    calculate_atr_volatility_proxy,
    AssetState,
)
from merid.prediction.risk.sentiment_vol_types import (
    SentimentScalar,
    VolatilityScalar,
    FearGreedRegime,
    VolatilityRegime,
    create_sentiment_scalar,
    create_volatility_scalar,
)


# ═══════════════════════════════════════════════════════════════════════════
# Volatility Calculation Utility Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRealizedVolatilityCalculation:
    """Test realized volatility calculation."""
    
    def test_zero_returns(self):
        """Test with no returns."""
        assert calculate_realized_volatility([]) == 0.0
        assert calculate_realized_volatility([0.01]) == 0.0
    
    def test_constant_returns(self):
        """Test with constant returns (zero vol)."""
        returns = [0.001] * 10
        vol = calculate_realized_volatility(returns)
        assert vol == 0.0
    
    def test_variable_returns(self):
        """Test with variable returns."""
        returns = [0.01, -0.01, 0.02, -0.02, 0.01]
        vol = calculate_realized_volatility(returns)
        assert vol > 0.0
    
    def test_annualization_factor(self):
        """Test annualization factor application."""
        returns = [0.01, -0.01, 0.01, -0.01]
        
        # Higher annualization factor = higher vol
        vol1 = calculate_realized_volatility(returns, annualization_factor=100.0)
        vol2 = calculate_realized_volatility(returns, annualization_factor=200.0)
        
        assert vol2 > vol1
        assert vol2 == pytest.approx(vol1 * 2, rel=0.01)


class TestVolOfVolCalculation:
    """Test volatility-of-volatility calculation."""
    
    def test_insufficient_data(self):
        """Test with insufficient data."""
        assert calculate_vol_of_vol([0.1, 0.2], window=5) == 0.0
    
    def test_constant_vol(self):
        """Test with constant volatility (zero vol-of-vol)."""
        vol_series = [0.5] * 10
        vov = calculate_vol_of_vol(vol_series, window=5)
        assert vov == 0.0
    
    def test_variable_vol(self):
        """Test with variable volatility."""
        vol_series = [0.3, 0.5, 0.7, 0.4, 0.6, 0.8]
        vov = calculate_vol_of_vol(vol_series, window=5)
        assert vov > 0.0
        assert vov <= 1.0  # Should be normalized
    
    def test_normalization(self):
        """Test that result is properly normalized."""
        # Very high variation
        vol_series = [0.1, 0.9, 0.1, 0.9, 0.1]
        vov = calculate_vol_of_vol(vol_series, window=5)
        assert vov > 0.0
        assert vov <= 1.0


class TestATRVolatilityProxy:
    """Test ATR-based volatility proxy."""
    
    def test_insufficient_data(self):
        """Test with insufficient data."""
        result = calculate_atr_volatility_proxy([100], [99], [100], period=14)
        assert result == 0.0
    
    def test_constant_prices(self):
        """Test with constant prices (no volatility)."""
        closes = [100.0] * 10
        # When highs/lows match closes exactly, there's no volatility
        highs = [100.0] * 10
        lows = [100.0] * 10
        
        result = calculate_atr_volatility_proxy(highs, lows, closes, period=14)
        # No price movement = no volatility
        assert result == 0.0
    
    def test_trending_prices(self):
        """Test with trending prices."""
        closes = [100.0 + i for i in range(20)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        
        result = calculate_atr_volatility_proxy(highs, lows, closes, period=14)
        assert result > 0.0
    
    def test_close_only_data(self):
        """Test with only close prices (no OHLC)."""
        closes = [100.0, 101.0, 99.0, 102.0, 98.0]
        
        result = calculate_atr_volatility_proxy([], [], closes, period=14)
        assert result >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# AssetState Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAssetState:
    """Test AssetState tracking."""
    
    def test_initial_state(self):
        """Test initial asset state."""
        state = AssetState(asset="BTC")
        
        assert state.asset == "BTC"
        assert state.current_sentiment is None
        assert state.current_volatility is None
        assert state.last_sentiment_update is None
        assert state.last_vol_update is None
    
    def test_stale_detection_no_data(self):
        """Test stale detection with no data."""
        state = AssetState(asset="BTC")
        
        is_stale, reason = state.is_stale(max_age_seconds=300)
        assert is_stale is True
        assert "no_sentiment_data" in reason
    
    def test_stale_detection_fresh(self):
        """Test stale detection with fresh data."""
        state = AssetState(asset="BTC")
        state.current_sentiment = create_sentiment_scalar(50)
        state.last_sentiment_update = datetime.now(timezone.utc)
        state.current_volatility = create_volatility_scalar(0.5)
        state.last_vol_update = datetime.now(timezone.utc)
        
        is_stale, reason = state.is_stale(max_age_seconds=300)
        assert is_stale is False
        assert reason == "fresh"
    
    def test_stale_detection_old(self):
        """Test stale detection with old data."""
        from datetime import timedelta
        state = AssetState(asset="BTC")
        state.current_sentiment = create_sentiment_scalar(50)
        # Set update time to 10 minutes ago using timedelta
        state.last_sentiment_update = datetime.now(timezone.utc) - timedelta(minutes=10)
        state.current_volatility = create_volatility_scalar(0.5)
        state.last_vol_update = datetime.now(timezone.utc) - timedelta(minutes=10)
        
        is_stale, reason = state.is_stale(max_age_seconds=300)
        assert is_stale is True
        assert "stale" in reason


# ═══════════════════════════════════════════════════════════════════════════
# SentimentVolService Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentVolServiceBasic:
    """Test basic SentimentVolService operations."""
    
    def test_singleton_pattern(self):
        """Test that service is a singleton."""
        svc1 = get_sentiment_vol_service()
        svc2 = get_sentiment_vol_service()
        assert svc1 is svc2
    
    def test_register_asset(self):
        """Test asset registration."""
        svc = SentimentVolService()
        svc.register_asset("BTC")
        svc.register_asset("ETH")
        
        assert "BTC" in svc.get_tracked_assets()
        assert "ETH" in svc.get_tracked_assets()
    
    def test_unregister_asset(self):
        """Test asset unregistration."""
        svc = SentimentVolService()
        svc.register_asset("BTC")
        assert "BTC" in svc.get_tracked_assets()
        
        svc.unregister_asset("BTC")
        assert "BTC" not in svc.get_tracked_assets()
    
    def test_case_insensitive_registration(self):
        """Test that asset registration is case-insensitive."""
        svc = SentimentVolService()
        svc.register_asset("btc")
        
        assert "BTC" in svc.get_tracked_assets()


class TestSentimentUpdates:
    """Test sentiment update operations."""
    
    def test_update_sentiment(self):
        """Test basic sentiment update."""
        svc = SentimentVolService()
        
        result = svc.update_sentiment("BTC", value=75, confidence=0.9, source="test")
        
        assert isinstance(result, SentimentScalar)
        assert result.value == 75.0
        assert result.confidence == 0.9
        assert result.source == "test"
        # Value 75 is at EXTREME_GREED boundary (>=75)
        assert result.regime == FearGreedRegime.EXTREME_GREED
    
    def test_get_sentiment(self):
        """Test getting sentiment."""
        svc = SentimentVolService()
        svc.update_sentiment("BTC", value=30, confidence=0.8)  # Use 30 to get FEAR regime (26-45)
        svc.update_volatility_direct("BTC", annualized_vol=0.50)  # Also update vol so data isn't stale
        
        sentiment, is_stale = svc.get_sentiment("BTC")
        
        assert sentiment is not None
        assert sentiment.value == 30.0
        assert sentiment.regime == FearGreedRegime.FEAR  # 30 is in FEAR range (26-45)
        assert is_stale is False
    
    def test_get_sentiment_unregistered(self):
        """Test getting sentiment for unregistered asset."""
        svc = SentimentVolService()
        
        sentiment, is_stale = svc.get_sentiment("XXX")
        assert sentiment is None
        assert is_stale is True
    
    def test_sentiment_history_tracking(self):
        """Test that sentiment history is tracked."""
        # Use a unique asset name to avoid interference from other tests
        test_asset = "TEST_HIST_" + str(id(self))
        svc = SentimentVolService()
        
        svc.update_sentiment(test_asset, value=50)
        svc.update_sentiment(test_asset, value=60)
        svc.update_sentiment(test_asset, value=70)
        
        # Check that state has history
        assert test_asset in svc._assets
        state = svc._assets[test_asset]
        assert len(state.sentiment_history) == 3


class TestVolatilityUpdates:
    """Test volatility update operations."""
    
    def test_update_price_builds_volatility(self):
        """Test that price updates build volatility."""
        svc = SentimentVolService()
        
        # Feed price updates
        vol = None
        for i in range(10):
            price = 50000.0 + (i * 100)
            vol = svc.update_price("BTC", price)
        
        # After enough samples, should have volatility
        assert vol is not None
        assert isinstance(vol, VolatilityScalar)
        assert vol.value >= 0.0
    
    def test_update_volatility_direct(self):
        """Test direct volatility update."""
        svc = SentimentVolService()
        
        result = svc.update_volatility_direct(
            "BTC",
            annualized_vol=0.75,
            uncertainty=0.2,
            source="test_direct",
            confidence=0.9,
        )
        
        assert isinstance(result, VolatilityScalar)
        assert result.value == 0.75
        assert result.uncertainty == 0.2
        assert result.source == "test_direct"
    
    def test_get_volatility(self):
        """Test getting volatility."""
        svc = SentimentVolService()
        svc.update_volatility_direct("BTC", annualized_vol=0.60)
        
        vol = svc.get_volatility("BTC")
        
        assert vol is not None
        assert vol.value == 0.60
        assert vol.regime == VolatilityRegime.TARGET


class TestSizingMultiplier:
    """Test sizing multiplier operations."""
    
    def test_get_sizing_multiplier_with_data(self):
        """Test sizing multiplier computation with data."""
        svc = SentimentVolService()
        svc.update_sentiment("BTC", value=50)
        svc.update_volatility_direct("BTC", annualized_vol=0.50)
        
        mult = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        
        assert mult is not None
        assert 0.2 <= mult.value <= 1.2
    
    def test_get_sizing_multiplier_fallback(self):
        """Test sizing multiplier fallback when no data."""
        svc = SentimentVolService()
        # Don't register or update BTC
        
        mult = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        
        # Should return fallback/neutral multiplier
        assert mult is not None
        assert 0.2 <= mult.value <= 1.2
    
    def test_sizing_multiplier_extreme_scenario(self):
        """Test sizing multiplier in extreme scenario."""
        svc = SentimentVolService()
        svc.update_sentiment("BTC", value=10)  # Extreme fear
        svc.update_volatility_direct("BTC", annualized_vol=1.5)  # Extreme vol
        
        mult = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        
        # Should be significantly reduced
        assert mult.value < 0.5
        assert mult.get_regime_label() == "HALTED"


class TestCompositeState:
    """Test composite state retrieval."""
    
    def test_get_composite_state(self):
        """Test getting full composite state."""
        svc = SentimentVolService()
        svc.update_sentiment("BTC", value=50)
        svc.update_volatility_direct("BTC", annualized_vol=0.50)
        
        state = svc.get_composite_state("BTC")
        
        assert "asset" in state
        assert state["asset"] == "BTC"
        assert "sentiment" in state
        assert "volatility" in state
        assert "sizing_multiplier" in state
        assert "effective_size_factor" in state
        assert "regime_label" in state
    
    def test_get_all_states(self):
        """Test getting state for all assets."""
        svc = SentimentVolService()
        svc.update_sentiment("BTC", value=50)
        svc.update_sentiment("ETH", value=60)
        
        all_states = svc.get_all_states()
        
        assert "BTC" in all_states
        assert "ETH" in all_states


class TestSubscription:
    """Test subscription/callback functionality."""
    
    def test_subscribe_and_notify(self):
        """Test subscription and notification."""
        svc = SentimentVolService()
        
        callback_called = threading.Event()
        received_sentiment = None
        received_volatility = None
        
        def callback(sentiment, volatility):
            nonlocal received_sentiment, received_volatility
            received_sentiment = sentiment
            received_volatility = volatility
            callback_called.set()
        
        svc.subscribe("BTC", callback)
        
        # Trigger update
        svc.update_sentiment("BTC", value=50)
        
        # Wait for callback (with timeout)
        callback_called.wait(timeout=1.0)
        
        assert callback_called.is_set()
        assert received_sentiment is not None
    
    def test_unsubscribe(self):
        """Test unsubscription."""
        svc = SentimentVolService()
        
        call_count = 0
        
        def callback(sentiment, volatility):
            nonlocal call_count
            call_count += 1
        
        svc.subscribe("BTC", callback)
        svc.update_sentiment("BTC", value=50)
        
        assert call_count == 1
        
        svc.unsubscribe("BTC", callback)
        svc.update_sentiment("BTC", value=60)
        
        # Should not have incremented
        assert call_count == 1


class TestHealthAndMetrics:
    """Test health and metrics reporting."""
    
    def test_get_health(self):
        """Test health status."""
        # Use unique asset names to avoid interference from other tests
        test_asset1 = "HEALTH_1_" + str(id(self))
        test_asset2 = "HEALTH_2_" + str(id(self))
        svc = SentimentVolService()
        svc.update_sentiment(test_asset1, value=50)
        svc.update_sentiment(test_asset2, value=60)
        
        health = svc.get_health()
        
        assert "service" in health
        assert health["tracked_assets"] >= 2  # Service may have other assets from other tests
        assert "fresh_assets" in health
        assert "stale_assets" in health
    
    def test_error_counting(self):
        """Test that errors are counted."""
        svc = SentimentVolService()
        initial_errors = svc._error_count
        
        # Simulate an error
        svc._error_count += 1
        
        health = svc.get_health()
        assert health["error_count"] == initial_errors + 1


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestServiceIntegration:
    """Integration tests for the full service."""
    
    def test_end_to_end_workflow(self):
        """Test end-to-end workflow with multiple updates."""
        svc = SentimentVolService()
        
        # Initial setup
        svc.register_asset("BTC")
        
        # Feed price updates to build vol
        for i in range(30):
            price = 50000 + (i * 50) + (i % 5) * 10  # Trending with noise
            svc.update_price("BTC", price)
        
        # Update sentiment
        svc.update_sentiment("BTC", value=25, confidence=0.8, source="cfgi")
        
        # Get sizing multiplier
        mult = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        
        # Verify structure
        assert mult.sentiment_contribution is not None
        assert mult.volatility_contribution is not None
        assert mult.reasoning
        
        # Get composite state
        state = svc.get_composite_state("BTC")
        assert state["sentiment"]["value"] == 25.0
        assert state["effective_size_factor"] == mult.value
    
    def test_contrarian_vs_non_contrarian(self):
        """Test that contrarian flag affects multiplier."""
        svc = SentimentVolService()
        
        # Extreme fear scenario
        svc.update_sentiment("BTC", value=10, confidence=1.0)
        svc.update_volatility_direct("BTC", annualized_vol=0.50)
        
        non_contrarian = svc.get_sizing_multiplier("BTC", is_contrarian=False)
        contrarian = svc.get_sizing_multiplier("BTC", is_contrarian=True)
        
        # Contrarian should be higher
        assert contrarian.value > non_contrarian.value
    
    def test_multi_asset_tracking(self):
        """Test tracking multiple assets independently."""
        svc = SentimentVolService()
        
        # Set up different regimes for different assets
        svc.update_sentiment("BTC", value=10)  # Extreme fear
        svc.update_volatility_direct("BTC", annualized_vol=0.50)
        
        svc.update_sentiment("ETH", value=90)  # Extreme greed
        svc.update_volatility_direct("ETH", annualized_vol=0.80)  # High vol
        
        btc_mult = svc.get_sizing_multiplier("BTC")
        eth_mult = svc.get_sizing_multiplier("ETH")
        
        # Both should be reduced but for different reasons
        assert btc_mult.value < 1.0
        assert eth_mult.value < 1.0
        
        # Reasoning should differ
        assert "extreme_fear" in btc_mult.reasoning or "fear" in btc_mult.reasoning
        assert "vol_high" in eth_mult.reasoning or "volatility" in eth_mult.reasoning


# ═══════════════════════════════════════════════════════════════════════════
# Error Handling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_callback_error_handling(self):
        """Test that callback errors don't crash the service."""
        svc = SentimentVolService()
        
        def failing_callback(sentiment, volatility):
            raise ValueError("Test error")
        
        svc.subscribe("BTC", failing_callback)
        
        # Should not raise
        svc.update_sentiment("BTC", value=50)
    
    def test_invalid_sentiment_values(self):
        """Test handling of invalid sentiment values."""
        svc = SentimentVolService()
        
        # Negative and >100 should be clamped
        result = svc.update_sentiment("BTC", value=-10)
        assert result.value == 0.0
        
        result2 = svc.update_sentiment("BTC", value=150)
        assert result2.value == 100.0
    
    def test_volatility_direct_edge_cases(self):
        """Test edge cases in direct volatility update."""
        svc = SentimentVolService()
        
        # Zero vol
        result = svc.update_volatility_direct("BTC", annualized_vol=0.0)
        assert result.value == 0.0
        
        # Very high vol
        result2 = svc.update_volatility_direct("BTC", annualized_vol=5.0)
        assert result2.regime == VolatilityRegime.EXTREME


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_service_singleton():
    """Reset service singleton before each test."""
    # Reset before test
    import merid.prediction.risk.sentiment_vol_service as svc_module
    svc_module._service_instance = None
    
    yield
    
    # Reset after test
    svc_module._service_instance = None
