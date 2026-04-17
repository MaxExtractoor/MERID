"""Tests for Polymarket client - Batch 11 Coverage continued."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from decimal import Decimal
import aiohttp

from merid.event_venues._legacy.polymarket.client import PolymarketVenueClient
from merid.event_venues._legacy.polymarket.models import PolymarketConfig
from merid.event_venues._legacy.polymarket.trading import PolymarketTrader
from merid.event_venues.base import (
    EventMarket,
    EventOutcome,
    VenueOrder,
    MarketFilter
)


class TestPolymarketVenueClient:
    """Tests for PolymarketVenueClient."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        config = PolymarketConfig(
            api_key="test_key",
            api_secret="test_secret"
        )
        return PolymarketVenueClient(config)

    def test_initialization(self, client):
        """Test client initialization."""
        assert client.venue_name == "polymarket"
        assert client.config.api_key == "test_key"
        assert client._http_client is None

    def test_initialization_no_config(self):
        """Test client initialization without config."""
        client = PolymarketVenueClient()
        assert client.config is not None
        assert isinstance(client.config, PolymarketConfig)

    @pytest.mark.asyncio
    async def test_connect(self, client):
        """Test client connection."""
        await client.connect()
        assert client._http_client is not None
        assert isinstance(client._http_client, aiohttp.ClientSession)
        await client.close()

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Test client close."""
        await client.connect()
        await client.close()
        assert client._http_client is None or client._http_client.closed


class TestPolymarketTrader:
    """Tests for PolymarketTrader."""

    @pytest.fixture
    def trader(self):
        """Create trader instance with mocked client."""
        mock_client = AsyncMock()
        return PolymarketTrader(client=mock_client)

    @pytest.fixture
    def trader_with_config(self):
        """Create trader with config."""
        config = PolymarketConfig(api_key="test")
        return PolymarketTrader(config=config)

    def test_initialization_with_client(self, trader):
        """Test trader initialization with client."""
        assert trader.client is not None

    def test_initialization_with_config(self, trader_with_config):
        """Test trader initialization with config."""
        assert trader_with_config.client is not None
        assert trader_with_config.client.config.api_key == "test"

    @pytest.mark.asyncio
    async def test_connect(self, trader):
        """Test trader connect."""
        await trader.connect()
        trader.client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, trader):
        """Test trader close."""
        await trader.close()
        trader.client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_buy_yes_market_order(self, trader):
        """Test buy YES market order."""
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        result = await trader.buy_yes("market_123", Decimal("100"))
        
        assert result is not None
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.market_id == "market_123"
        assert call_args.side == "buy"
        assert call_args.outcome_id == "Yes"
        assert call_args.order_type == "market"

    @pytest.mark.asyncio
    async def test_buy_yes_limit_order(self, trader):
        """Test buy YES limit order."""
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        result = await trader.buy_yes("market_123", Decimal("100"), Decimal("0.65"))
        
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.order_type == "limit"
        assert call_args.price == Decimal("0.65")

    @pytest.mark.asyncio
    async def test_buy_no(self, trader):
        """Test buy NO order."""
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        result = await trader.buy_no("market_123", Decimal("50"))
        
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.outcome_id == "No"
        assert call_args.side == "buy"

    @pytest.mark.asyncio
    async def test_sell_yes(self, trader):
        """Test sell YES order."""
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        result = await trader.sell_yes("market_123", Decimal("75"))
        
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "Yes"

    @pytest.mark.asyncio
    async def test_sell_no(self, trader):
        """Test sell NO order."""
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        result = await trader.sell_no("market_123", Decimal("25"))
        
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "No"

    @pytest.mark.asyncio
    async def test_close_position(self, trader):
        """Test close position."""
        # Mock positions
        mock_position = MagicMock()
        mock_position.market_id = "market_123"
        mock_position.outcome_id = "Yes"
        mock_position.size = Decimal("100")
        
        trader.client.get_positions = AsyncMock(return_value=[mock_position])
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        
        results = await trader.close_position("market_123")
        
        assert len(results) == 1
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.side == "sell"  # Selling to close long
        assert call_args.order_type == "market"

    @pytest.mark.asyncio
    async def test_close_position_short(self, trader):
        """Test close short position."""
        mock_position = MagicMock()
        mock_position.market_id = "market_123"
        mock_position.outcome_id = "No"
        mock_position.size = Decimal("-50")  # Short position
        
        trader.client.get_positions = AsyncMock(return_value=[mock_position])
        trader.client.place_order = AsyncMock(return_value=MagicMock())
        
        results = await trader.close_position("market_123")
        
        call_args = trader.client.place_order.call_args[0][0]
        assert call_args.side == "buy"  # Buying to close short
        assert call_args.size == Decimal("50")

    @pytest.mark.asyncio
    async def test_close_position_empty(self, trader):
        """Test close position with no positions."""
        trader.client.get_positions = AsyncMock(return_value=[])
        
        results = await trader.close_position("market_123")
        
        assert len(results) == 0
        trader.client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_market_by_slug(self, trader):
        """Test get market by slug."""
        mock_market = MagicMock()
        mock_market.question = "Will BTC hit 100k?"
        trader.client.list_markets = AsyncMock(return_value=[mock_market])
        
        result = await trader.get_market_by_slug("BTC")
        
        assert result is not None
        assert result.question == "Will BTC hit 100k?"

    @pytest.mark.asyncio
    async def test_get_market_by_slug_no_match(self, trader):
        """Test get market by slug with no matches."""
        trader.client.list_markets = AsyncMock(return_value=[])
        
        result = await trader.get_market_by_slug("nonexistent")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_get_best_price_buy(self, trader):
        """Test get best buy price."""
        mock_orderbook = MagicMock()
        mock_orderbook.asks = [(Decimal("0.65"), Decimal("100")), (Decimal("0.66"), Decimal("200"))]
        mock_orderbook.bids = [(Decimal("0.64"), Decimal("150"))]
        
        trader.client.get_orderbook = AsyncMock(return_value=mock_orderbook)
        
        price = await trader.get_best_price("market_123", "Yes", "buy")
        
        assert price == Decimal("0.65")  # Best ask

    @pytest.mark.asyncio
    async def test_get_best_price_sell(self, trader):
        """Test get best sell price."""
        mock_orderbook = MagicMock()
        mock_orderbook.bids = [(Decimal("0.64"), Decimal("150")), (Decimal("0.63"), Decimal("100"))]
        mock_orderbook.asks = []
        
        trader.client.get_orderbook = AsyncMock(return_value=mock_orderbook)
        
        price = await trader.get_best_price("market_123", "Yes", "sell")
        
        assert price == Decimal("0.64")  # Best bid

    @pytest.mark.asyncio
    async def test_get_best_price_no_orderbook(self, trader):
        """Test get best price with no orderbook."""
        trader.client.get_orderbook = AsyncMock(return_value=None)
        
        price = await trader.get_best_price("market_123", "Yes", "buy")
        
        assert price is None

    @pytest.mark.asyncio
    async def test_get_best_price_empty_book(self, trader):
        """Test get best price with empty orderbook."""
        mock_orderbook = MagicMock()
        mock_orderbook.asks = []
        mock_orderbook.bids = []
        
        trader.client.get_orderbook = AsyncMock(return_value=mock_orderbook)
        
        price = await trader.get_best_price("market_123", "Yes", "buy")
        
        assert price is None
