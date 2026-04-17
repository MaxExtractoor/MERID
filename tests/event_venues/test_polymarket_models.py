"""Tests for Polymarket modules - Batch 11 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from decimal import Decimal
from datetime import datetime
import os

from merid.event_venues._legacy.polymarket.models import (
    MarketOutcome,
    Market,
    Order,
    Position,
    Trade,
    OrderBook,
    PolymarketConfig,
)


class TestMarketOutcome:
    """Tests for MarketOutcome dataclass."""

    def test_outcome_creation(self):
        """Test creating market outcome."""
        outcome = MarketOutcome(
            outcome="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65")
        )
        assert outcome.outcome == "Yes"
        assert outcome.price == Decimal("0.65")
        assert outcome.probability == Decimal("0.65")

    def test_outcome_with_bid_ask(self):
        """Test outcome with bid/ask prices."""
        outcome = MarketOutcome(
            outcome="No",
            price=Decimal("0.35"),
            probability=Decimal("0.35"),
            best_ask_price=Decimal("0.36"),
            best_bid_price=Decimal("0.34")
        )
        assert outcome.best_ask_price == Decimal("0.36")
        assert outcome.best_bid_price == Decimal("0.34")


class TestMarket:
    """Tests for Market dataclass."""

    def test_market_creation(self):
        """Test creating market."""
        outcomes = [
            MarketOutcome("Yes", Decimal("0.65"), Decimal("0.65")),
            MarketOutcome("No", Decimal("0.35"), Decimal("0.35"))
        ]
        market = Market(
            id="market_123",
            question="Will BTC hit $100k?",
            description="Bitcoin price prediction",
            outcomes=outcomes,
            active=True
        )
        assert market.id == "market_123"
        assert market.question == "Will BTC hit $100k?"
        assert len(market.outcomes) == 2
        assert market.active is True

    def test_market_with_metadata(self):
        """Test market with optional metadata."""
        market = Market(
            id="market_456",
            question="Will ETH 2.0 launch?",
            description="Ethereum upgrade",
            outcomes=[],
            volume=Decimal("1000000"),
            liquidity=Decimal("500000"),
            category="crypto",
            tags=["ethereum", "blockchain"]
        )
        assert market.volume == Decimal("1000000")
        assert market.liquidity == Decimal("500000")
        assert market.category == "crypto"
        assert market.tags == ["ethereum", "blockchain"]


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        """Test creating order."""
        order = Order(
            id="order_123",
            market_id="market_456",
            outcome="Yes",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65")
        )
        assert order.id == "order_123"
        assert order.market_id == "market_456"
        assert order.side == "buy"
        assert order.status == "pending"

    def test_order_defaults(self):
        """Test order default values."""
        order = Order(
            id="order_123",
            market_id="market_456",
            outcome="Yes",
            side="sell",
            size=Decimal("50"),
            price=Decimal("0.35")
        )
        assert order.filled == Decimal("0")
        assert order.status == "pending"


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        """Test creating position."""
        position = Position(
            market_id="market_123",
            outcome="Yes",
            size=Decimal("100"),
            average_price=Decimal("0.60")
        )
        assert position.market_id == "market_123"
        assert position.outcome == "Yes"
        assert position.size == Decimal("100")
        assert position.average_price == Decimal("0.60")

    def test_position_with_pnl(self):
        """Test position with PnL."""
        position = Position(
            market_id="market_456",
            outcome="No",
            size=Decimal("-50"),
            average_price=Decimal("0.40"),
            unrealized_pnl=Decimal("5.0"),
            realized_pnl=Decimal("2.5")
        )
        assert position.unrealized_pnl == Decimal("5.0")
        assert position.realized_pnl == Decimal("2.5")


class TestTrade:
    """Tests for Trade dataclass."""

    def test_trade_creation(self):
        """Test creating trade."""
        trade = Trade(
            id="trade_123",
            market_id="market_456",
            outcome="Yes",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            fee=Decimal("0.10"),
            timestamp=datetime.now()
        )
        assert trade.id == "trade_123"
        assert trade.fee == Decimal("0.10")


class TestOrderBook:
    """Tests for OrderBook dataclass."""

    def test_orderbook_creation(self):
        """Test creating orderbook."""
        bids = [(Decimal("0.64"), Decimal("100")), (Decimal("0.63"), Decimal("200"))]
        asks = [(Decimal("0.66"), Decimal("150")), (Decimal("0.67"), Decimal("300"))]
        
        orderbook = OrderBook(
            market_id="market_123",
            outcome="Yes",
            bids=bids,
            asks=asks,
            timestamp=datetime.now()
        )
        assert orderbook.market_id == "market_123"
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2


class TestPolymarketConfig:
    """Tests for PolymarketConfig dataclass."""

    def test_config_defaults(self):
        """Test config with default values."""
        config = PolymarketConfig()
        assert config.gamma_api_base == "https://gamma-api.polymarket.com"
        assert config.clob_api_base == "https://clob.polymarket.com"
        assert config.timeout == 30.0
        assert config.ws_timeout == 60.0

    def test_config_custom_values(self):
        """Test config with custom values."""
        config = PolymarketConfig(
            gamma_api_base="https://custom.gamma.com",
            timeout=45.0,
            api_key="test_key"
        )
        assert config.gamma_api_base == "https://custom.gamma.com"
        assert config.timeout == 45.0
        assert config.api_key == "test_key"

    def test_config_from_env(self):
        """Test config loads from environment."""
        with patch.dict(os.environ, {
            "POLYMARKET_API_KEY": "env_key",
            "POLYMARKET_API_SECRET": "env_secret",
            "POLYMARKET_WALLET_ADDRESS": "0x123",
            "POLYMARKET_PRIVATE_KEY": "private_key"
        }):
            config = PolymarketConfig()
            assert config.api_key == "env_key"
            assert config.api_secret == "env_secret"
            assert config.wallet_address == "0x123"
            assert config.private_key == "private_key"
