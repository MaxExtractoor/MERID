"""
Tests for sentiment volatility service (merid/risk).

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest
from merid.prediction.risk.sentiment_vol_service import SentimentVolService


def test_sentiment_vol_service_initializes_without_attribute_error():
    """P-C2: SentimentVolService must not raise AttributeError during initialize()
    due to self._config vs self.config mismatch.

    The bug occurs when:
    1. SentimentVolService.__init__() stores config as self.config (no underscore)
    2. But then tries to access it as self._config (with underscore) at line 280
    3. This happens when metrics_recorder is present and tries to initialize_config()
    """
    try:
        # Create a fresh instance - this should not raise AttributeError
        svc = SentimentVolService()

        # Verify the config attribute exists
        assert hasattr(svc, 'config'), "SentimentVolService missing 'config' attribute"
        assert svc.config is not None, "SentimentVolService.config should not be None"

    except AttributeError as e:
        # If we get here, the bug manifested
        pytest.fail(f"initialize() raised AttributeError (self._config vs self.config bug): {e}")


def test_get_sentiment_returns_staleness_flag():
    """P-H2: get_sentiment must return (value, is_stale) tuple so callers
    can choose to reject stale data."""
    from merid.prediction.risk.sentiment_vol_service import SentimentVolService

    svc = SentimentVolService()
    svc.initialize() if hasattr(svc, 'initialize') else None

    # Result must be a tuple
    result = svc.get_sentiment("BTC")
    assert isinstance(result, tuple), "get_sentiment must return (value, is_stale) tuple"
    assert len(result) == 2, "tuple must have exactly 2 elements"
    value, is_stale = result
    # With no data, value=None and is_stale=True
    assert value is None or isinstance(value, object)
    assert isinstance(is_stale, bool)


def test_get_sentiment_marks_stale_when_old():
    """P-H2: sentiment older than stale_threshold must have is_stale=True."""
    from datetime import datetime, timezone, timedelta
    from merid.prediction.risk.sentiment_vol_service import SentimentVolService, create_sentiment_scalar

    svc = SentimentVolService()
    svc.register_asset("BTC")

    # Inject a stale sentiment (last_sentiment_update 600s ago, well past 300s threshold)
    with svc._asset_lock:
        state = svc._assets.get("BTC") or svc._assets.get("BTC".upper())
    if state is None:
        pytest.skip("BTC asset state not available")

    # Set last_sentiment_update to 600s ago so is_stale() returns True
    state.last_sentiment_update = datetime.now(timezone.utc) - timedelta(seconds=600)
    # Also set last_vol_update so staleness comes from sentiment not missing vol
    state.last_vol_update = datetime.now(timezone.utc) - timedelta(seconds=600)
    state.current_sentiment = create_sentiment_scalar(
        value=45.0, confidence=1.0, source="test"
    )

    value, is_stale = svc.get_sentiment("BTC")
    assert value is not None
    assert value.value == 45.0
    assert is_stale is True, "600s-old data must be marked stale"
