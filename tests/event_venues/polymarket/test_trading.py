"""Comprehensive tests for merid/event_venues/polymarket/trading.py."""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.trading import PolymarketTrader
from merid.event_venues.polymarket.models import PolymarketConfig
from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
    VenuePosition,
    VenueOrderBook,
)


@pytest.fixture
def mock_client():
    """Create mock PolymarketVenueClient."""
    client = AsyncMock()
    return client


@pytest.fixture
def trader(mock_client):
    """Create PolymarketTrader with mock client."""
    return PolymarketTrader(client=mock_client)


class TestPolymarketTraderInitialization:
    """Test PolymarketTrader initialization."""

    def test_init_with_client(self, mock_client):
        """Test initialization with provided client."""
        trader = PolymarketTrader(client=mock_client)
        assert trader.client is mock_client

    def test_init_without_client(self):
        """Test initialization without client creates new one."""
        with patch('merid.event_venues.polymarket.trading.PolymarketVenueClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            trader = PolymarketTrader()
            mock_client_class.assert_called_once()
            assert trader.client is mock_client

    def test_init_with_config(self):
        """Test initialization with config."""
        config = PolymarketConfig()
        with patch('merid.event_venues.polymarket.trading.PolymarketVenueClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            trader = PolymarketTrader(config=config)
            mock_client_class.assert_called_once_with(config)


class TestPolymarketTraderConnection:
    """Test PolymarketTrader connection management."""

    @pytest.mark.asyncio
    async def test_connect(self, trader, mock_client):
        """Test connect delegates to client."""
        await trader.connect()
        mock_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, trader, mock_client):
        """Test close delegates to client."""
        await trader.close()
        mock_client.close.assert_called_once()


class TestPolymarketTraderBuyOperations:
    """Test PolymarketTrader buy operations."""

    @pytest.mark.asyncio
    async def test_buy_yes_market_order(self, trader, mock_client):
        """Test buying YES shares at market price."""
        expected_order = PlacedOrder(
            order_id="order_123",
            market_id="0x123abc",
            side="buy",
            size=Decimal("10"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_yes("0x123abc", Decimal("10"))

        assert result == expected_order
        mock_client.place_order.assert_called_once()
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.market_id == "0x123abc"
        assert call_args.side == "buy"
        assert call_args.size == Decimal("10")
        assert call_args.outcome_id == "Yes"
        assert call_args.order_type == "market"

    @pytest.mark.asyncio
    async def test_buy_yes_limit_order(self, trader, mock_client):
        """Test buying YES shares at limit price."""
        expected_order = PlacedOrder(
            order_id="order_124",
            market_id="0x123abc",
            side="buy",
            size=Decimal("5"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_yes("0x123abc", Decimal("5"), price=Decimal("0.65"))

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.order_type == "limit"
        assert call_args.price == Decimal("0.65")

    @pytest.mark.asyncio
    async def test_buy_no_market_order(self, trader, mock_client):
        """Test buying NO shares at market price."""
        expected_order = PlacedOrder(
            order_id="order_125",
            market_id="0x123abc",
            side="buy",
            size=Decimal("20"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_no("0x123abc", Decimal("20"))

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.outcome_id == "No"

    @pytest.mark.asyncio
    async def test_buy_no_limit_order(self, trader, mock_client):
        """Test buying NO shares at limit price."""
        expected_order = PlacedOrder(
            order_id="order_126",
            market_id="0x123abc",
            side="buy",
            size=Decimal("15"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.buy_no("0x123abc", Decimal("15"), price=Decimal("0.35"))

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.order_type == "limit"


class TestPolymarketTraderSellOperations:
    """Test PolymarketTrader sell operations."""

    @pytest.mark.asyncio
    async def test_sell_yes_market_order(self, trader, mock_client):
        """Test selling YES shares at market price."""
        expected_order = PlacedOrder(
            order_id="order_127",
            market_id="0x123abc",
            side="sell",
            size=Decimal("8"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.sell_yes("0x123abc", Decimal("8"))

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "Yes"

    @pytest.mark.asyncio
    async def test_sell_no_market_order(self, trader, mock_client):
        """Test selling NO shares at market price."""
        expected_order = PlacedOrder(
            order_id="order_128",
            market_id="0x123abc",
            side="sell",
            size=Decimal("12"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order

        result = await trader.sell_no("0x123abc", Decimal("12"))

        assert result == expected_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.outcome_id == "No"


class TestPolymarketTraderClosePosition:
    """Test PolymarketTrader position closing."""

    @pytest.mark.asyncio
    async def test_close_position_with_yes_position(self, trader, mock_client):
        """Test closing YES position."""
        position = VenuePosition(
            market_id="0x123abc",
            outcome_id="Yes",
            size=Decimal("10"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        placed_order = PlacedOrder(
            order_id="order_close",
            market_id="0x123abc",
            side="sell",
            size=Decimal("10"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = placed_order

        result = await trader.close_position("0x123abc")

        assert len(result) == 1
        assert result[0] == placed_order
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "sell"
        assert call_args.size == Decimal("10")

    @pytest.mark.asyncio
    async def test_close_position_with_no_position(self, trader, mock_client):
        """Test closing NO position."""
        position = VenuePosition(
            market_id="0x123abc",
            outcome_id="No",
            size=Decimal("-5"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        placed_order = PlacedOrder(
            order_id="order_close",
            market_id="0x123abc",
            side="buy",
            size=Decimal("5"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = placed_order

        result = await trader.close_position("0x123abc")

        assert len(result) == 1
        call_args = mock_client.place_order.call_args[0][0]
        assert call_args.side == "buy"
        assert call_args.size == Decimal("5")

    @pytest.mark.asyncio
    async def test_close_position_zero_size_skipped(self, trader, mock_client):
        """Test that zero-size positions are skipped."""
        position = VenuePosition(
            market_id="0x123abc",
            outcome_id="Yes",
            size=Decimal("0"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        result = await trader.close_position("0x123abc")

        assert len(result) == 0
        mock_client.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_position_no_positions(self, trader, mock_client):
        """Test closing position when no positions exist."""
        mock_client.get_positions.return_value = []

        result = await trader.close_position("0x123abc")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_close_position_other_market_ignored(self, trader, mock_client):
        """Test that positions in other markets are ignored."""
        position = VenuePosition(
            market_id="0xOTHER",
            outcome_id="Yes",
            size=Decimal("10"),
            average_entry_price=Decimal("0.50")
        )
        mock_client.get_positions.return_value = [position]

        result = await trader.close_position("0x123abc")

        assert len(result) == 0


class TestPolymarketTraderMarketOperations:
    """Test PolymarketTrader market operations."""

    @pytest.mark.asyncio
    async def test_get_market_by_slug_exact_match(self, trader, mock_client):
        """Test finding market by exact slug match."""
        expected_market = EventMarket(
            market_id="0x123abc",
            venue="polymarket",
            question="Will Bitcoin hit 100k?",
            description="BTC price prediction",
            outcomes=[]
        )
        mock_client.list_markets.return_value = [expected_market]

        result = await trader.get_market_by_slug("Bitcoin hit 100k")

        assert result == expected_market

    @pytest.mark.asyncio
    async def test_get_market_by_slug_partial_match(self, trader, mock_client):
        """Test finding market by partial slug match."""
        market1 = EventMarket(
            market_id="0x123abc",
            venue="polymarket",
            question="Will Bitcoin hit 100k in 2024?",
            description="BTC price",
            outcomes=[]
        )
        market2 = EventMarket(
            market_id="0x456def",
            venue="polymarket",
            question="Ethereum prediction",
            description="ETH price",
            outcomes=[]
        )
        mock_client.list_markets.return_value = [market1, market2]

        result = await trader.get_market_by_slug("bitcoin")

        assert result == market1

    @pytest.mark.asyncio
    async def test_get_market_by_slug_no_match(self, trader, mock_client):
        """Test when no markets match."""
        mock_client.list_markets.return_value = []

        result = await trader.get_market_by_slug("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_market_by_slug_returns_first(self, trader, mock_client):
        """Test returns first market when no exact match."""
        market1 = EventMarket(
            market_id="0x123abc",
            venue="polymarket",
            question="Market One",
            description="Desc",
            outcomes=[]
        )
        mock_client.list_markets.return_value = [market1]

        result = await trader.get_market_by_slug("different")

        assert result == market1


class TestPolymarketTraderGetBestPrice:
    """Test PolymarketTrader get_best_price method."""

    @pytest.mark.asyncio
    async def test_get_best_price_buy_yes(self, trader, mock_client):
        """Test getting best price to buy YES."""
        orderbook = VenueOrderBook(
            market_id="0x123abc",
            outcome_id="Yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[(Decimal("0.65"), Decimal("200"))],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("0x123abc", outcome="Yes", side="buy")

        assert result == Decimal("0.65")

    @pytest.mark.asyncio
    async def test_get_best_price_sell_yes(self, trader, mock_client):
        """Test getting best price to sell YES."""
        orderbook = VenueOrderBook(
            market_id="0x123abc",
            outcome_id="Yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[(Decimal("0.65"), Decimal("200"))],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("0x123abc", outcome="Yes", side="sell")

        assert result == Decimal("0.60")

    @pytest.mark.asyncio
    async def test_get_best_price_no_orderbook(self, trader, mock_client):
        """Test getting best price when no orderbook."""
        mock_client.get_orderbook.return_value = None

        result = await trader.get_best_price("0x123abc")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_best_price_empty_asks(self, trader, mock_client):
        """Test getting best price when asks are empty."""
        orderbook = VenueOrderBook(
            market_id="0x123abc",
            outcome_id="Yes",
            bids=[(Decimal("0.60"), Decimal("100"))],
            asks=[],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("0x123abc", side="buy")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_best_price_empty_bids(self, trader, mock_client):
        """Test getting best price when bids are empty."""
        orderbook = VenueOrderBook(
            market_id="0x123abc",
            outcome_id="Yes",
            bids=[],
            asks=[(Decimal("0.65"), Decimal("200"))],
            timestamp=datetime.now()
        )
        mock_client.get_orderbook.return_value = orderbook

        result = await trader.get_best_price("0x123abc", side="sell")

        assert result is None
