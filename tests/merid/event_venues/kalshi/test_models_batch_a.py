"""Tests for merid/event_venues/kalshi/models.py - Batch A."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from merid.event_venues.kalshi.models import (
    KalshiOutcome, KalshiMarket, KalshiOrder, KalshiPosition,
    KalshiTrade, KalshiOrderBook, KalshiBalance, KalshiConfig
)


class TestKalshiOutcome:
    """Tests for KalshiOutcome dataclass."""

    def test_kalshi_outcome_creation(self):
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("55.5"),
            probability=Decimal("0.555"),
            volume=Decimal("10000")
        )
        assert outcome.outcome_id == "yes"
        assert outcome.name == "Yes"
        assert outcome.price == Decimal("55.5")
        assert outcome.probability == Decimal("0.555")
        assert outcome.volume == Decimal("10000")

    def test_kalshi_outcome_minimal(self):
        outcome = KalshiOutcome(
            outcome_id="no",
            name="No",
            price=Decimal("44.5")
        )
        assert outcome.probability is None
        assert outcome.volume is None


class TestKalshiMarket:
    """Tests for KalshiMarket dataclass."""

    def test_kalshi_market_creation(self):
        outcomes = [
            KalshiOutcome("yes", "Yes", Decimal("60.0")),
            KalshiOutcome("no", "No", Decimal("40.0"))
        ]
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Fed Rate Decision",
            description="Will Fed raise rates?",
            outcomes=outcomes,
            category="Finance",
            status="active"
        )
        assert market.ticker == "FED-25DEC-T3.00"
        assert len(market.outcomes) == 2
        assert market.active is True

    def test_kalshi_market_post_init(self):
        market = KalshiMarket(
            ticker="TEST-123",
            event_ticker="TEST",
            title="Test",
            description="Test market",
            outcomes=[],
            tags=None
        )
        assert market.tags == []


class TestKalshiOrder:
    """Tests for KalshiOrder dataclass."""

    def test_kalshi_order_creation(self):
        order = KalshiOrder(
            order_id="ord_123",
            ticker="FED-25DEC-T3.00",
            action="buy",
            side="yes",
            order_type="limit",
            price=Decimal("55.0"),
            count=10
        )
        assert order.order_id == "ord_123"
        assert order.action == "buy"
        assert order.filled_count == 0
        assert order.status == "pending"


class TestKalshiPosition:
    """Tests for KalshiPosition dataclass."""

    def test_kalshi_position_creation(self):
        position = KalshiPosition(
            ticker="FED-25DEC-T3.00",
            side="yes",
            count=100,
            avg_price=Decimal("52.5"),
            total_cost=Decimal("5250")
        )
        assert position.ticker == "FED-25DEC-T3.00"
        assert position.side == "yes"
        assert position.count == 100


class TestKalshiTrade:
    """Tests for KalshiTrade dataclass."""

    def test_kalshi_trade_creation(self):
        trade = KalshiTrade(
            trade_id="trd_456",
            ticker="FED-25DEC-T3.00",
            order_id="ord_123",
            side="yes",
            count=5,
            price=Decimal("53.0"),
            fee=Decimal("1.5"),
            timestamp=datetime.now(timezone.utc)
        )
        assert trade.trade_id == "trd_456"
        assert trade.count == 5
        assert trade.fee == Decimal("1.5")


class TestKalshiOrderBook:
    """Tests for KalshiOrderBook dataclass."""

    def test_kalshi_orderbook_creation(self):
        book = KalshiOrderBook(
            ticker="FED-25DEC-T3.00",
            yes_bid=Decimal("54.0"),
            yes_ask=Decimal("56.0"),
            no_bid=Decimal("43.0"),
            no_ask=Decimal("45.0")
        )
        assert book.ticker == "FED-25DEC-T3.00"
        assert book.yes_bid == Decimal("54.0")
        assert book.yes_ask == Decimal("56.0")


class TestKalshiBalance:
    """Tests for KalshiBalance dataclass."""

    def test_kalshi_balance_creation(self):
        balance = KalshiBalance(
            balance=Decimal("10000"),
            locked_balance=Decimal("2000"),
            total_balance=Decimal("12000")
        )
        assert balance.balance == Decimal("10000")
        assert balance.locked_balance == Decimal("2000")
        assert balance.total_balance == Decimal("12000")
        assert balance.currency == "USD"


class TestKalshiConfig:
    """Tests for KalshiConfig dataclass."""

    def test_kalshi_config_defaults(self):
        config = KalshiConfig()
        assert config.rest_api_url == "https://api.elections.kalshi.com/trade-api/v2"
        assert config.use_demo is False
        assert config.timeout == 30.0

    def test_kalshi_config_demo_mode(self):
        config = KalshiConfig(use_demo=True)
        assert config.use_demo is True
        assert config.base_url == config.demo_rest_api_url
        assert config.ws_url == config.demo_ws_api_url

    def test_kalshi_config_production_urls(self):
        config = KalshiConfig(use_demo=False)
        assert config.base_url == config.rest_api_url
        assert config.ws_url == config.ws_api_url
