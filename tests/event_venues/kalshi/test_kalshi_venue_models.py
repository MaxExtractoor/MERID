"""Comprehensive tests for merid/event_venues/kalshi/models.py - REAL implementation coverage."""

import pytest
import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from merid.event_venues.kalshi.models import (
    KalshiOutcome,
    KalshiMarket,
    KalshiOrder,
    KalshiPosition,
    KalshiTrade,
    KalshiOrderBook,
    KalshiBalance,
    KalshiConfig,
)


class TestKalshiOutcome:
    """Test KalshiOutcome dataclass."""
    
    def test_kalshi_outcome_creation(self):
        """Test KalshiOutcome creation."""
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("65"),
            probability=Decimal("0.65"),
            volume=Decimal("1000000")
        )
        
        assert outcome.outcome_id == "yes"
        assert outcome.name == "Yes"
        assert outcome.price == Decimal("65")
        assert outcome.probability == Decimal("0.65")
        assert outcome.volume == Decimal("1000000")
    
    def test_kalshi_outcome_optional_fields(self):
        """Test KalshiOutcome with optional fields as None."""
        outcome = KalshiOutcome(
            outcome_id="no",
            name="No",
            price=Decimal("35")
        )
        
        assert outcome.probability is None
        assert outcome.volume is None


class TestKalshiMarket:
    """Test KalshiMarket dataclass."""
    
    def test_kalshi_market_creation(self):
        """Test KalshiMarket creation."""
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("65")
        )
        
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Fed Funds Rate",
            description="Will Fed raise rates?",
            outcomes=[outcome],
            category="finance",
            series_ticker="FED",
            active=True,
            status="active",
            volume=Decimal("1000000"),
            open_interest=Decimal("500000"),
            liquidity=Decimal("250000")
        )
        
        assert market.ticker == "FED-25DEC-T3.00"
        assert market.event_ticker == "FED-25DEC"
        assert market.title == "Fed Funds Rate"
        assert len(market.outcomes) == 1
        assert market.category == "finance"
        assert market.active is True
        assert market.status == "active"
    
    def test_kalshi_market_post_init(self):
        """Test KalshiMarket __post_init__ sets default tags."""
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("65")
        )
        
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Fed Funds Rate",
            description="Will Fed raise rates?",
            outcomes=[outcome]
        )
        
        assert market.tags == []
    
    def test_kalshi_market_with_datetimes(self):
        """Test KalshiMarket with datetime fields."""
        outcome = KalshiOutcome(
            outcome_id="yes",
            name="Yes",
            price=Decimal("65")
        )
        
        now = datetime.utcnow()
        
        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Fed Funds Rate",
            description="Will Fed raise rates?",
            outcomes=[outcome],
            open_time=now,
            close_time=now,
            expiration_time=now,
            settlement_time=now,
            created_at=now
        )
        
        assert market.open_time == now
        assert market.close_time == now


class TestKalshiOrder:
    """Test KalshiOrder dataclass."""
    
    def test_kalshi_order_creation(self):
        """Test KalshiOrder creation."""
        order = KalshiOrder(
            order_id="order_123",
            ticker="FED-25DEC-T3.00",
            action="buy",
            side="yes",
            order_type="limit",
            price=Decimal("65"),
            count=100,
            filled_count=50,
            remaining_count=50,
            status="pending",
            client_order_id="client_123"
        )
        
        assert order.order_id == "order_123"
        assert order.ticker == "FED-25DEC-T3.00"
        assert order.action == "buy"
        assert order.side == "yes"
        assert order.order_type == "limit"
        assert order.price == Decimal("65")
        assert order.count == 100
        assert order.filled_count == 50
        assert order.status == "pending"
    
    def test_kalshi_order_defaults(self):
        """Test KalshiOrder default values."""
        order = KalshiOrder(
            order_id="order_123",
            ticker="FED-25DEC-T3.00",
            action="buy",
            side="yes",
            order_type="market",
            price=None,
            count=100
        )
        
        assert order.filled_count == 0
        assert order.status == "pending"


class TestKalshiPosition:
    """Test KalshiPosition dataclass."""
    
    def test_kalshi_position_creation(self):
        """Test KalshiPosition creation."""
        position = KalshiPosition(
            ticker="FED-25DEC-T3.00",
            side="yes",
            count=100,
            avg_price=Decimal("65"),
            total_cost=Decimal("6500"),
            unrealized_pnl=Decimal("500"),
            realized_pnl=Decimal("0")
        )
        
        assert position.ticker == "FED-25DEC-T3.00"
        assert position.side == "yes"
        assert position.count == 100
        assert position.avg_price == Decimal("65")
        assert position.total_cost == Decimal("6500")
        assert position.unrealized_pnl == Decimal("500")


class TestKalshiTrade:
    """Test KalshiTrade dataclass."""
    
    def test_kalshi_trade_creation(self):
        """Test KalshiTrade creation."""
        now = datetime.utcnow()
        
        trade = KalshiTrade(
            trade_id="trade_123",
            ticker="FED-25DEC-T3.00",
            order_id="order_123",
            side="yes",
            count=50,
            price=Decimal("66"),
            fee=Decimal("0.50"),
            timestamp=now
        )
        
        assert trade.trade_id == "trade_123"
        assert trade.ticker == "FED-25DEC-T3.00"
        assert trade.order_id == "order_123"
        assert trade.side == "yes"
        assert trade.count == 50
        assert trade.price == Decimal("66")
        assert trade.fee == Decimal("0.50")
        assert trade.timestamp == now


class TestKalshiOrderBook:
    """Test KalshiOrderBook dataclass."""
    
    def test_kalshi_order_book_creation(self):
        """Test KalshiOrderBook creation."""
        now = datetime.utcnow()
        
        orderbook = KalshiOrderBook(
            ticker="FED-25DEC-T3.00",
            yes_bid=Decimal("64"),
            yes_ask=Decimal("66"),
            no_bid=Decimal("34"),
            no_ask=Decimal("36"),
            yes_price=Decimal("65"),
            no_price=Decimal("35"),
            timestamp=now
        )
        
        assert orderbook.ticker == "FED-25DEC-T3.00"
        assert orderbook.yes_bid == Decimal("64")
        assert orderbook.yes_ask == Decimal("66")
        assert orderbook.no_bid == Decimal("34")
        assert orderbook.no_ask == Decimal("36")
        assert orderbook.timestamp == now
    
    def test_kalshi_order_book_optional_fields(self):
        """Test KalshiOrderBook with optional fields as None."""
        orderbook = KalshiOrderBook(
            ticker="FED-25DEC-T3.00"
        )
        
        assert orderbook.yes_bid is None
        assert orderbook.yes_ask is None


class TestKalshiBalance:
    """Test KalshiBalance dataclass."""
    
    def test_kalshi_balance_creation(self):
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
    
    def test_kalshi_config_defaults(self):
        """Test KalshiConfig default values."""
        config = KalshiConfig()
        
        assert config.rest_api_url == "https://api.elections.kalshi.com/trade-api/v2"
        assert config.ws_api_url == "wss://ws.elections.kalshi.com/v2"
        assert config.demo_rest_api_url == "https://demo-api.kalshi.co/trade-api/v2"
        assert config.demo_ws_api_url == "wss://demo-ws.kalshi.co/v2"
        assert config.use_demo is False
        assert config.timeout == 30.0
        assert config.ws_timeout == 60.0
    
    def test_kalshi_config_post_init_with_env_vars(self):
        """Test KalshiConfig __post_init__ reads from environment."""
        with patch.dict(os.environ, {
            'KALSHI_EMAIL': 'test@example.com',
            'KALSHI_PASSWORD': 'secret',
            'KALSHI_API_KEY': 'api_key_123',
            'KALSHI_PRIVATE_KEY_PATH': '/path/to/key',
            'KALSHI_USE_DEMO': 'true'
        }):
            config = KalshiConfig()
            
            assert config.email == 'test@example.com'
            assert config.password == 'secret'
            assert config.api_key == 'api_key_123'
            assert config.private_key_path == '/path/to/key'
            assert config.use_demo is True
    
    def test_kalshi_config_base_url_prod(self):
        """Test base_url property in production."""
        config = KalshiConfig(use_demo=False)
        assert config.base_url == config.rest_api_url
    
    def test_kalshi_config_base_url_demo(self):
        """Test base_url property in demo."""
        config = KalshiConfig(use_demo=True)
        assert config.base_url == config.demo_rest_api_url
    
    def test_kalshi_config_ws_url_prod(self):
        """Test ws_url property in production."""
        config = KalshiConfig(use_demo=False)
        assert config.ws_url == config.ws_api_url
    
    def test_kalshi_config_ws_url_demo(self):
        """Test ws_url property in demo."""
        config = KalshiConfig(use_demo=True)
        assert config.ws_url == config.demo_ws_api_url
