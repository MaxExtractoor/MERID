"""Comprehensive tests for merid/event_venues/polymarket/models.py - REAL implementation coverage."""

import pytest
import os
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from merid.event_venues.polymarket.models import (
    MarketOutcome,
    Market,
    Order,
    Position,
    Trade,
    OrderBook,
    PolymarketConfig,
)


class TestMarketOutcome:
    """Test MarketOutcome dataclass."""
    
    def test_market_outcome_creation(self):
        """Test MarketOutcome creation."""
        outcome = MarketOutcome(
            outcome="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65"),
            best_ask_price=Decimal("0.67"),
            best_bid_price=Decimal("0.63")
        )
        
        assert outcome.outcome == "Yes"
        assert outcome.price == Decimal("0.65")
        assert outcome.probability == Decimal("0.65")
        assert outcome.best_ask_price == Decimal("0.67")
        assert outcome.best_bid_price == Decimal("0.63")
    
    def test_market_outcome_optional_fields(self):
        """Test MarketOutcome with optional fields as None."""
        outcome = MarketOutcome(
            outcome="No",
            price=Decimal("0.35"),
            probability=Decimal("0.35")
        )
        
        assert outcome.best_ask_price is None
        assert outcome.best_bid_price is None


class TestMarket:
    """Test Market dataclass."""
    
    def test_market_creation(self):
        """Test Market creation."""
        outcome = MarketOutcome(
            outcome="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65")
        )
        
        market = Market(
            id="0x123abc",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome],
            active=True,
            volume=Decimal("100000"),
            liquidity=Decimal("50000"),
            category="weather"
        )
        
        assert market.id == "0x123abc"
        assert market.question == "Will it rain?"
        assert len(market.outcomes) == 1
        assert market.active is True
        assert market.volume == Decimal("100000")
        assert market.liquidity == Decimal("50000")
        assert market.category == "weather"
    
    def test_market_default_tags(self):
        """Test Market default tags."""
        outcome = MarketOutcome(
            outcome="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65")
        )
        
        market = Market(
            id="0x123abc",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome]
        )
        
        assert market.tags == []
    
    def test_market_with_resolution(self):
        """Test Market with resolution."""
        outcome = MarketOutcome(
            outcome="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65")
        )
        
        now = datetime.utcnow()
        
        market = Market(
            id="0x123abc",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome],
            resolution="Yes",
            resolved_at=now
        )
        
        assert market.resolution == "Yes"
        assert market.resolved_at == now


class TestOrder:
    """Test Order dataclass."""
    
    def test_order_creation(self):
        """Test Order creation."""
        order = Order(
            id="order_123",
            market_id="0x123abc",
            outcome="Yes",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            filled=Decimal("50"),
            remaining=Decimal("50"),
            status="pending"
        )
        
        assert order.id == "order_123"
        assert order.market_id == "0x123abc"
        assert order.outcome == "Yes"
        assert order.side == "buy"
        assert order.size == Decimal("100")
        assert order.price == Decimal("0.65")
        assert order.filled == Decimal("50")
        assert order.remaining == Decimal("50")
        assert order.status == "pending"
    
    def test_order_defaults(self):
        """Test Order default values."""
        order = Order(
            id="order_123",
            market_id="0x123abc",
            outcome="Yes",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65")
        )
        
        assert order.filled == Decimal("0")
        assert order.status == "pending"


class TestPosition:
    """Test Position dataclass."""
    
    def test_position_creation(self):
        """Test Position creation."""
        position = Position(
            market_id="0x123abc",
            outcome="Yes",
            size=Decimal("100"),
            average_price=Decimal("0.65"),
            unrealized_pnl=Decimal("10.50"),
            realized_pnl=Decimal("5.25")
        )
        
        assert position.market_id == "0x123abc"
        assert position.outcome == "Yes"
        assert position.size == Decimal("100")
        assert position.average_price == Decimal("0.65")
        assert position.unrealized_pnl == Decimal("10.50")
        assert position.realized_pnl == Decimal("5.25")


class TestTrade:
    """Test Trade dataclass."""
    
    def test_trade_creation(self):
        """Test Trade creation."""
        now = datetime.utcnow()
        
        trade = Trade(
            id="trade_123",
            market_id="0x123abc",
            outcome="Yes",
            side="buy",
            size=Decimal("50"),
            price=Decimal("0.66"),
            fee=Decimal("0.50"),
            timestamp=now
        )
        
        assert trade.id == "trade_123"
        assert trade.market_id == "0x123abc"
        assert trade.outcome == "Yes"
        assert trade.side == "buy"
        assert trade.size == Decimal("50")
        assert trade.price == Decimal("0.66")
        assert trade.fee == Decimal("0.50")
        assert trade.timestamp == now


class TestOrderBook:
    """Test OrderBook dataclass."""
    
    def test_order_book_creation(self):
        """Test OrderBook creation."""
        now = datetime.utcnow()
        
        orderbook = OrderBook(
            market_id="0x123abc",
            outcome="Yes",
            bids=[(Decimal("0.63"), Decimal("100")), (Decimal("0.62"), Decimal("200"))],
            asks=[(Decimal("0.67"), Decimal("150")), (Decimal("0.68"), Decimal("100"))],
            timestamp=now
        )
        
        assert orderbook.market_id == "0x123abc"
        assert orderbook.outcome == "Yes"
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.bids[0] == (Decimal("0.63"), Decimal("100"))
        assert orderbook.asks[0] == (Decimal("0.67"), Decimal("150"))
        assert orderbook.timestamp == now


class TestPolymarketConfig:
    """Test PolymarketConfig dataclass."""
    
    def test_polymarket_config_defaults(self):
        """Test PolymarketConfig default values."""
        config = PolymarketConfig()
        
        assert config.gamma_api_base == "https://gamma-api.polymarket.com"
        assert config.clob_api_base == "https://clob.polymarket.com"
        assert config.data_api_base == "https://data.polymarket.com"
        assert config.graphql_url == "https://polymarket.com/graphql"
        assert config.ws_url == "wss://ws.polymarket.com"
        assert config.timeout == 30.0
        assert config.ws_timeout == 60.0
    
    def test_polymarket_config_post_init_with_env_vars(self):
        """Test PolymarketConfig __post_init__ reads from environment."""
        with patch.dict(os.environ, {
            'POLYMARKET_API_KEY': 'api_key_123',
            'POLYMARKET_API_SECRET': 'secret_456',
            'POLYMARKET_WALLET_ADDRESS': '0x123abc',
            'POLYMARKET_PRIVATE_KEY': 'private_key_xyz'
        }):
            config = PolymarketConfig()
            
            assert config.api_key == 'api_key_123'
            assert config.api_secret == 'secret_456'
            assert config.wallet_address == '0x123abc'
            assert config.private_key == 'private_key_xyz'
    
    def test_polymarket_config_custom_values(self):
        """Test PolymarketConfig with custom values."""
        config = PolymarketConfig(
            api_key="custom_key",
            api_secret="custom_secret",
            timeout=60.0,
            ws_timeout=120.0
        )
        
        assert config.api_key == "custom_key"
        assert config.api_secret == "custom_secret"
        assert config.timeout == 60.0
        assert config.ws_timeout == 120.0
