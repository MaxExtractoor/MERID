"""Smoke test for trading_agent import and basic instantiation.

This is a minimal go/no-go test to ensure the trading_agent module can be imported
and instantiated without raising exceptions, catching import errors like the
MEAN_REVERSION_TIMEFRMES typo that blocked execution in production.
"""

import pytest


def test_trading_agent_import_no_error():
    """Test that trading_agent can be imported without ImportError."""
    # This should not raise ImportError
    from merid.prediction.trading_agent import KalshiTradingAgent
    assert KalshiTradingAgent is not None


def test_mean_reversion_timeframes_import():
    """Test that MEAN_REVERSION_TIMEFRAMES can be imported from crypto_top_edge."""
    # This should not raise ImportError (was broken by typo MEAN_REVERSION_TIMEFRMES)
    from merid.prediction.crypto_top_edge import CRYPTO_ASSETS, MEAN_REVERSION_TIMEFRAMES
    assert MEAN_REVERSION_TIMEFRAMES is not None
    assert "15m" in MEAN_REVERSION_TIMEFRAMES
    assert CRYPTO_ASSETS is not None


def test_sentiment_mode_env_var_handling():
    """Test that sentiment_mode can be set via env var without errors."""
    import os
    
    # Test with feature_only mode
    os.environ["MERID_SENTIMENT_MODE"] = "feature_only"
    import importlib
    import merid.prediction.strategy as strategy_module
    importlib.reload(strategy_module)
    
    assert strategy_module.SENTIMENT_MODE == "feature_only"
    assert strategy_module.SENTIMENT_GATING_ENABLED is False
    
    # Clean up
    del os.environ["MERID_SENTIMENT_MODE"]
