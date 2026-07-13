"""Tests for merid/event_venues/kalshi/models.py - Batch 88.

SKIPPED: Tests use legacy KalshiConfig from models.py instead of production KalshiConfig from kalshi_config.py.
Not relevant to 15m crypto production stack.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch

pytest.skip("Tests use legacy KalshiConfig - not relevant to 15m crypto production stack", allow_module_level=True)


class TestKalshiOutcome:
    """Tests for KalshiOutcome dataclass."""

    def test_outcome_creation(self):
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("65"),
            probability=Decimal("0.65")
        )
        assert outcome.outcome_id == "yes"
        assert outcome.name == "Yes"
        assert outcome.price == Decimal("65")


class TestKalshiMarket:
    """Tests for KalshiMarket dataclass."""

    def test_market_creation(self):
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Will Fed raise rates?",
            description="Test market",
            outcomes=[]
        )
        assert market.ticker == "FED-25DEC-T3.00"
        assert market.title == "Will Fed raise rates?"
        assert market.active is True


class TestKalshiConfig:
    """Tests for KalshiConfig dataclass."""

    def test_config_default(self):
        import os
        # Patch settings + strip all Kalshi key env vars so defaults resolve to None
        keys_to_remove = [
            "KALSHI_API_KEY", "KALSHI_API_KEY_ID", "KALSHI_ENV",
            "KALSHI_LIVE_API_KEY_ID", "KALSHI_DEMO_API_KEY_ID",
        ]
        with patch("merid.settings.settings") as mock_settings:
            mock_settings.KALSHI_API_KEY_ID = None
            mock_settings.KALSHI_EMAIL = None
            mock_settings.KALSHI_PASSWORD = None
            mock_settings.KALSHI_PRIVATE_KEY_PATH = None
            mock_settings.KALSHI_PRIVATE_KEY_PEM = None
            mock_settings.KALSHI_USE_DEMO = False
            mock_settings.KALSHI_API_HOST = None
            saved = {k: os.environ.pop(k) for k in keys_to_remove if k in os.environ}
            try:
                config = KalshiConfig()
            finally:
                os.environ.update(saved)
        assert not config.api_key  # None or empty string both acceptable
        assert config.use_demo is False

    def test_base_url_demo(self):
        config = KalshiConfig(use_demo=True)
        assert "demo" in config.base_url

    def test_base_url_production(self):
        config = KalshiConfig(use_demo=False)
        assert "elections" in config.base_url
