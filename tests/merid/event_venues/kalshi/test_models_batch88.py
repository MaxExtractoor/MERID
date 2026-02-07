"""Tests for merid/event_venues/kalshi/models.py - Batch 88."""
import pytest
from decimal import Decimal
from unittest.mock import patch

from merid.event_venues.kalshi.models import (
    KalshiOutcome, KalshiMarket, KalshiOrder, KalshiOrderBook,
    KalshiPosition, KalshiTrade, KalshiBalance, KalshiConfig
)


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
        config = KalshiConfig()
        assert config.api_key is None
        assert config.use_demo is False

    def test_base_url_demo(self):
        config = KalshiConfig(use_demo=True)
        assert "demo" in config.base_url

    def test_base_url_production(self):
        config = KalshiConfig(use_demo=False)
        assert "elections" in config.base_url
