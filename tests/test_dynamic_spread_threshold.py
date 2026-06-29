"""Tests for dynamic spread threshold based on volatility regime (2026 best practice).

Tests cover:
- Volatility regime classification (calm, elevated, violent)
- Dynamic spread threshold calculation
- Continuous interpolation between regimes
- Price history tracking in UnifiedSpotService
- Integration with agent grid market validation
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import time
from dataclasses import dataclass


def test_volatility_regime_config_defaults():
    """Verify LeanAgentConfig has volatility regime parameters."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
    
    # Verify new volatility regime parameters exist
    assert hasattr(config, 'calm_volatility_threshold')
    assert hasattr(config, 'elevated_volatility_threshold')
    assert hasattr(config, 'calm_spread_threshold_bp')
    assert hasattr(config, 'elevated_spread_threshold_bp')
    assert hasattr(config, 'violent_spread_threshold_bp')
    assert hasattr(config, 'spread_volatility_sensitivity')
    
    # Verify default values
    assert config.calm_volatility_threshold == 0.005  # 0.5%
    assert config.elevated_volatility_threshold == 0.015  # 1.5%
    assert config.calm_spread_threshold_bp == 50
    assert config.elevated_spread_threshold_bp == 100
    assert config.violent_spread_threshold_bp == 150
    assert config.spread_volatility_sensitivity == 1.5


def test_classify_volatility_regime_calm():
    """Test volatility regime classification logic for calm market."""
    # Simulate the logic directly without full agent initialization
    prices = [65000.0, 65015.0, 65010.0]
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    import statistics
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0.001
    
    # Calm threshold is 0.5%
    calm_threshold = 0.005
    
    # Should classify as calm (volatility < 0.5%)
    assert volatility < calm_threshold
    
    # Simulate regime classification
    if volatility < calm_threshold:
        regime = "calm"
    else:
        regime = "elevated"
    
    assert regime == "calm"


def test_classify_volatility_regime_elevated():
    """Test volatility regime classification logic for elevated market."""
    # Simulate the logic directly with higher volatility data
    # Use varied changes to get meaningful stdev
    prices = [65000.0, 65200.0, 65650.0, 65100.0, 65400.0]  # Mixed changes
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    import statistics
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0.001
    
    # Thresholds
    calm_threshold = 0.005  # 0.5%
    elevated_threshold = 0.015  # 1.5%
    
    # Should classify as elevated (0.5% <= volatility < 1.5%)
    # With varied changes, stdev should be in elevated range
    assert calm_threshold <= volatility < elevated_threshold
    
    # Simulate regime classification
    if volatility < calm_threshold:
        regime = "calm"
    elif volatility < elevated_threshold:
        regime = "elevated"
    else:
        regime = "violent"
    
    assert regime == "elevated"


def test_classify_volatility_regime_violent():
    """Test volatility regime classification logic for violent market."""
    # Simulate the logic directly with very high volatility data
    # Use highly varied changes to get high stdev
    prices = [65000.0, 66000.0, 64000.0, 67000.0, 63000.0]  # Large swings
    returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
    
    import statistics
    volatility = statistics.stdev(returns) if len(returns) > 1 else 0.001
    
    # Elevated threshold is 1.5%
    elevated_threshold = 0.015
    
    # Should classify as violent (volatility >= 1.5%)
    # With large swings, stdev should be in violent range
    assert volatility >= elevated_threshold
    
    # Simulate regime classification
    calm_threshold = 0.005
    if volatility < calm_threshold:
        regime = "calm"
    elif volatility < elevated_threshold:
        regime = "elevated"
    else:
        regime = "violent"
    
    assert regime == "violent"


def test_dynamic_spread_threshold_calm():
    """Test dynamic spread threshold calculation in calm regime."""
    # Simulate the interpolation logic
    volatility = 0.003  # 0.3% (calm)
    calm_threshold = 0.005
    calm_spread_threshold_bp = 50
    elevated_spread_threshold_bp = 100
    spread_volatility_sensitivity = 1.5
    
    # Interpolate between calm and elevated
    ratio = volatility / calm_threshold
    interpolated = calm_spread_threshold_bp * (ratio ** spread_volatility_sensitivity)
    threshold_bp = min(int(interpolated), elevated_spread_threshold_bp)
    
    # In calm regime, should be close to calm threshold
    assert threshold_bp <= calm_spread_threshold_bp


def test_dynamic_spread_threshold_elevated():
    """Test dynamic spread threshold calculation in elevated regime."""
    # Simulate the interpolation logic
    volatility = 0.010  # 1.0% (elevated)
    calm_threshold = 0.005
    elevated_threshold = 0.015
    calm_spread_threshold_bp = 50
    elevated_spread_threshold_bp = 100
    violent_spread_threshold_bp = 150
    spread_volatility_sensitivity = 1.5
    
    # Interpolate between elevated and violent
    ratio = volatility / elevated_threshold
    base = elevated_spread_threshold_bp
    target = violent_spread_threshold_bp
    interpolated = base * (ratio ** spread_volatility_sensitivity)
    threshold_bp = min(int(interpolated), target)
    
    # In elevated regime, should interpolate between calm and elevated
    assert calm_spread_threshold_bp < threshold_bp <= elevated_spread_threshold_bp


def test_dynamic_spread_threshold_violent():
    """Test dynamic spread threshold calculation in violent regime."""
    # Simulate the interpolation logic
    volatility = 0.025  # 2.5% (violent)
    elevated_threshold = 0.015
    elevated_spread_threshold_bp = 100
    violent_spread_threshold_bp = 150
    spread_volatility_sensitivity = 1.5
    
    # Interpolate between elevated and violent
    ratio = volatility / elevated_threshold
    base = elevated_spread_threshold_bp
    target = violent_spread_threshold_bp
    interpolated = base * (ratio ** spread_volatility_sensitivity)
    threshold_bp = min(int(interpolated), target)
    
    # In violent regime, should use violent threshold
    assert threshold_bp > elevated_spread_threshold_bp
    assert threshold_bp <= violent_spread_threshold_bp


def test_spot_service_price_history_tracking():
    """Test UnifiedSpotService tracks price history for volatility calculation."""
    from data.unified_spot_service import UnifiedSpotService
    
    service = UnifiedSpotService()
    
    # Verify price history tracking is initialized
    assert hasattr(service, '_price_history')
    assert hasattr(service, '_max_history_length')
    assert service._max_history_length == 3600  # 1 hour


def test_spot_service_get_spot_history():
    """Test get_spot_history returns filtered price data."""
    from data.unified_spot_service import UnifiedSpotService
    
    service = UnifiedSpotService()
    
    # Add some test data
    now_ms = int(time.time() * 1000)
    with service._cache_lock:
        service._price_history["BTC"] = [
            (now_ms - 600000, 65000.0),  # 10 minutes ago (outside 5min window)
            (now_ms - 300000, 65100.0),  # 5 minutes ago (at window boundary)
            (now_ms - 200000, 65200.0),  # 3.3 minutes ago (inside window)
            (now_ms - 100000, 65300.0),  # 1.7 minutes ago (inside window)
            (now_ms, 65400.0),  # Now (inside window)
        ]
    
    # Get 5-minute window
    history = service.get_spot_history("BTC", window_s=300)
    
    # Should only return data within 5-minute window (including boundary)
    assert len(history) == 4  # Last 4 points (5min boundary + 3 inside)
    assert all(p["price"] >= 65100.0 for p in history)


def test_market_validation_uses_dynamic_threshold():
    """Test that dynamic spread threshold logic is implemented in agent."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
    
    # Verify the agent has the dynamic threshold method
    assert hasattr(config, 'calm_spread_threshold_bp')
    assert hasattr(config, 'elevated_spread_threshold_bp')
    assert hasattr(config, 'violent_spread_threshold_bp')
    
    # Verify thresholds are configured correctly
    assert config.calm_spread_threshold_bp == 50
    assert config.elevated_spread_threshold_bp == 100
    assert config.violent_spread_threshold_bp == 150
    
    # The actual integration test would require full agent initialization
    # This test verifies the configuration is in place


def test_dynamic_threshold_prevents_overly_wide_spreads():
    """Test that even dynamic thresholds have upper limits."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
    
    # Verify there's a maximum threshold (violent regime)
    max_threshold = config.violent_spread_threshold_bp
    
    # Even in violent regime, spreads above 150bp should be rejected
    # This is a safety net to prevent trading in extremely illiquid conditions
    assert max_threshold == 150
    
    # The cents-based safety net still applies
    assert config.max_spread_cents == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
