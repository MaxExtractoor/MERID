"""Smoke test for trading_agent import and basic instantiation.

This is a minimal go/no-go test to ensure the trading_agent module can be imported
and instantiated without raising exceptions, catching import errors like the
MEAN_REVERSION_TIMEFRMES typo that blocked execution in production.
"""

import pytest






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
