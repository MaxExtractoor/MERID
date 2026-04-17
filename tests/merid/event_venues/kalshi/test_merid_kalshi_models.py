"""Tests for merid/event_venues/kalshi/models.py."""
import os
import pytest
from unittest.mock import patch
from datetime import datetime
from decimal import Decimal
from merid.event_venues.kalshi.models import (
    KalshiOutcome, KalshiMarket, KalshiOrder, KalshiPosition,
    KalshiTrade, KalshiOrderBook, KalshiBalance, KalshiConfig
)


class TestKalshiOutcome:
    """Test KalshiOutcome dataclass."""

    def test_creation(self):
        """Test KalshiOutcome creation."""
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("55"),
            probability=Decimal("0.55"),
            volume=Decimal("10000")
        )
        assert outcome.outcome_id == "yes"
        assert outcome.name == "Yes"
        assert outcome.price == Decimal("55")
        assert outcome.probability == Decimal("0.55")
        assert outcome.volume == Decimal("10000")


class TestKalshiMarket:
    """Test KalshiMarket dataclass."""

    def test_creation(self):
        """Test KalshiMarket creation."""
        outcome = KalshiOutcome(outcome_id="yes", name="Yes", price=Decimal("55"))
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Fed Rate Decision",
            description="Will Fed raise rates?",
            outcomes=[outcome],
            category="economics",
            active=True
        )
        assert market.ticker == "FED-25DEC-T3.00"
        assert market.title == "Fed Rate Decision"
        assert len(market.outcomes) == 1
        assert market.active is True

    def test_post_init_tags_none(self):
        """Test __post_init__ when tags is None."""
        outcome = KalshiOutcome(outcome_id="yes", name="Yes", price=Decimal("55"))
        market = KalshiMarket(
            ticker="TEST",
            event_ticker="EVENT",
            title="Test",
            description="Test desc",
            outcomes=[outcome],
            tags=None
        )
        assert market.tags == []


class TestKalshiOrder:
    """Test KalshiOrder dataclass."""

    def test_creation(self):
        """Test KalshiOrder creation."""
        order = KalshiOrder(
            order_id="ord_123",
            ticker="FED-25DEC-T3.00",
            action="buy",
            side="yes",
            order_type="limit",
            price=Decimal("55"),
            count=10,
            status="pending"
        )
        assert order.order_id == "ord_123"
        assert order.ticker == "FED-25DEC-T3.00"
        assert order.action == "buy"
        assert order.side == "yes"
        assert order.order_type == "limit"
        assert order.price == Decimal("55")
        assert order.count == 10
        assert order.status == "pending"


class TestKalshiPosition:
    """Test KalshiPosition dataclass."""

    def test_creation(self):
        """Test KalshiPosition creation."""
        position = KalshiPosition(
            ticker="FED-25DEC-T3.00",
            side="yes",
            count=100,
            avg_price=Decimal("50"),
            total_cost=Decimal("5000"),
            unrealized_pnl=Decimal("500")
        )
        assert position.ticker == "FED-25DEC-T3.00"
        assert position.side == "yes"
        assert position.count == 100
        assert position.avg_price == Decimal("50")
        assert position.total_cost == Decimal("5000")
        assert position.unrealized_pnl == Decimal("500")


class TestKalshiTrade:
    """Test KalshiTrade dataclass."""

    def test_creation(self):
        """Test KalshiTrade creation."""
        now = datetime.now()
        trade = KalshiTrade(
            trade_id="trd_123",
            ticker="FED-25DEC-T3.00",
            order_id="ord_123",
            side="yes",
            count=10,
            price=Decimal("55"),
            fee=Decimal("1"),
            timestamp=now
        )
        assert trade.trade_id == "trd_123"
        assert trade.ticker == "FED-25DEC-T3.00"
        assert trade.side == "yes"
        assert trade.count == 10
        assert trade.price == Decimal("55")
        assert trade.fee == Decimal("1")
        assert trade.timestamp == now


class TestKalshiOrderBook:
    """Test KalshiOrderBook dataclass."""

    def test_creation(self):
        """Test KalshiOrderBook creation."""
        ob = KalshiOrderBook(
            ticker="FED-25DEC-T3.00",
            yes_bid=Decimal("54"),
            yes_ask=Decimal("56"),
            no_bid=Decimal("43"),
            no_ask=Decimal("45"),
            yes_price=Decimal("55"),
            no_price=Decimal("44")
        )
        assert ob.ticker == "FED-25DEC-T3.00"
        assert ob.yes_bid == Decimal("54")
        assert ob.yes_ask == Decimal("56")
        assert ob.no_bid == Decimal("43")
        assert ob.no_ask == Decimal("45")


class TestKalshiBalance:
    """Test KalshiBalance dataclass."""

    def test_creation(self):
        """Test KalshiBalance creation."""
        balance = KalshiBalance(
            balance=Decimal("10000"),
            locked_balance=Decimal("2000"),
            total_balance=Decimal("12000"),
            currency="USD"
        )
        assert balance.balance == Decimal("10000")
        assert balance.locked_balance == Decimal("2000")
        assert balance.total_balance == Decimal("12000")
        assert balance.currency == "USD"


class TestKalshiConfig:
    """Test KalshiConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = KalshiConfig()
        assert config.rest_api_url == "https://api.elections.kalshi.com/trade-api/v2"
        assert config.ws_api_url == "wss://api.elections.kalshi.com/trade-api/ws/v2"
        assert config.timeout == 30.0
        assert config.ws_timeout == 60.0
        assert config.use_demo is False

    def test_demo_mode(self):
        """Test demo mode URLs."""
        config = KalshiConfig(use_demo=True)
        assert config.use_demo is True
        assert config.base_url == config.demo_rest_api_url
        assert config.ws_url == config.demo_ws_api_url

    def test_production_mode(self):
        """Test production mode URLs."""
        config = KalshiConfig(use_demo=False)
        assert config.use_demo is False
        assert config.base_url == config.rest_api_url
        assert config.ws_url == config.ws_api_url

    def test_env_vars_loaded(self):
        """KalshiConfig loads credentials from merid.settings."""
        with patch.dict(os.environ, {"KALSHI_ENV": ""}):
            with patch.multiple(
                "merid.settings.settings",
                KALSHI_EMAIL="test@example.com",
                KALSHI_PASSWORD="secret",
                KALSHI_API_KEY_ID="api_key_123",
                KALSHI_PRIVATE_KEY_PATH="/path/to/key",
                KALSHI_USE_DEMO=True,
            ):
                config = KalshiConfig()
            assert config.email == "test@example.com"
            assert config.password == "secret"
            assert config.api_key == "api_key_123"
            assert config.private_key_path == "/path/to/key"
            assert config.use_demo is True
