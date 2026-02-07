"""Tests for merid/event_venues/base.py - Batch A (86% → 100%)."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict

from merid.event_venues.base import (
    EventOutcome, EventMarket, VenueOrder, PlacedOrder, VenuePosition,
    VenueTrade, VenueOrderBook, MarketFilter, QuoteEvent,
    EventVenueClient, EventVenueStream, VenueClientFactory
)


class TestEventMarketPostInit:
    """Tests for EventMarket.__post_init__ to cover lines 52-53."""
    
    def test_event_market_tags_none(self):
        """Test that tags=None gets converted to empty list."""
        market = EventMarket(
            market_id="test-123",
            venue="test",
            question="Test question?",
            description="Test description",
            outcomes=[],
            tags=None
        )
        assert market.tags == []
        assert market.tags is not None
    
    def test_event_market_tags_provided(self):
        """Test that provided tags are preserved."""
        market = EventMarket(
            market_id="test-123",
            venue="test",
            question="Test question?",
            description="Test description",
            outcomes=[],
            tags=["crypto", "bitcoin"]
        )
        assert market.tags == ["crypto", "bitcoin"]


class MockVenueClient(EventVenueClient):
    """Mock implementation of EventVenueClient for testing."""
    
    def __init__(self, name: str = "mock"):
        self._name = name
        self.connected = False
    
    @property
    def venue_name(self) -> str:
        return self._name
    
    async def connect(self) -> None:
        self.connected = True
    
    async def close(self) -> None:
        self.connected = False
    
    async def list_markets(self, filter_params: Optional[MarketFilter] = None) -> List[EventMarket]:
        return []
    
    async def get_market(self, market_id: str) -> Optional[EventMarket]:
        return None
    
    async def get_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> Optional[VenueOrderBook]:
        return None
    
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        return None
    
    async def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> bool:
        return True
    
    async def get_order(self, order_id: str, market_id: Optional[str] = None) -> Optional[PlacedOrder]:
        return None
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        return []
    
    async def get_positions(self) -> List[VenuePosition]:
        return []
    
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        return {}


class MockVenueStream(EventVenueStream):
    """Mock implementation of EventVenueStream for testing."""
    
    def __init__(self, name: str = "mock"):
        self._name = name
        self.connected = False
    
    @property
    def venue_name(self) -> str:
        return self._name
    
    async def connect(self) -> None:
        self.connected = True
    
    async def close(self) -> None:
        self.connected = False
    
    async def subscribe_quotes(self, market_ids: List[str]) -> None:
        pass
    
    async def subscribe_trades(self, market_ids: Optional[List[str]] = None) -> None:
        pass
    
    async def subscribe_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> None:
        pass
    
    async def listen(self, callback: callable) -> None:
        pass


class TestEventVenueClient:
    """Tests for EventVenueClient abstract base class."""
    
    @pytest.mark.asyncio
    async def test_client_lifecycle(self):
        """Test connect/close lifecycle."""
        client = MockVenueClient("test_venue")
        assert client.venue_name == "test_venue"
        assert not client.connected
        
        await client.connect()
        assert client.connected
        
        await client.close()
        assert not client.connected
    
    @pytest.mark.asyncio
    async def test_client_methods_return_expected_types(self):
        """Test that all abstract methods can be called and return expected types."""
        client = MockVenueClient()
        
        # Market data methods
        markets = await client.list_markets()
        assert isinstance(markets, list)
        
        market = await client.get_market("test-id")
        assert market is None or isinstance(market, EventMarket)
        
        orderbook = await client.get_orderbook("test-id")
        assert orderbook is None or isinstance(orderbook, VenueOrderBook)
        
        # Trading methods
        order = VenueOrder(market_id="test", side="buy", size=Decimal("1"))
        placed = await client.place_order(order)
        assert placed is None or isinstance(placed, PlacedOrder)
        
        cancelled = await client.cancel_order("order-id")
        assert isinstance(cancelled, bool)
        
        order_status = await client.get_order("order-id")
        assert order_status is None or isinstance(order_status, PlacedOrder)
        
        open_orders = await client.get_open_orders()
        assert isinstance(open_orders, list)
        
        # Account methods
        positions = await client.get_positions()
        assert isinstance(positions, list)
        
        trades = await client.get_trades()
        assert isinstance(trades, list)
        
        balance = await client.get_balance()
        assert isinstance(balance, dict)


class TestEventVenueStream:
    """Tests for EventVenueStream abstract base class."""
    
    @pytest.mark.asyncio
    async def test_stream_lifecycle(self):
        """Test connect/close lifecycle."""
        stream = MockVenueStream("test_venue")
        assert stream.venue_name == "test_venue"
        assert not stream.connected
        
        await stream.connect()
        assert stream.connected
        
        await stream.close()
        assert not stream.connected
    
    @pytest.mark.asyncio
    async def test_subscription_methods(self):
        """Test subscription methods can be called."""
        stream = MockVenueStream()
        
        # Should not raise
        await stream.subscribe_quotes(["market-1", "market-2"])
        await stream.subscribe_trades()
        await stream.subscribe_trades(["market-1"])
        await stream.subscribe_orderbook("market-1")
        await stream.subscribe_orderbook("market-1", "outcome-1")
    
    @pytest.mark.asyncio
    async def test_listen_method(self):
        """Test listen method can be called with callback."""
        stream = MockVenueStream()
        
        async def dummy_callback(event):
            pass
        
        # Should not raise
        await stream.listen(dummy_callback)


class TestVenueClientFactory:
    """Tests for VenueClientFactory to cover lines 287, 307-309, 314."""
    
    def setup_method(self):
        """Clear registry before each test."""
        VenueClientFactory._registry.clear()
    
    def teardown_method(self):
        """Clear registry after each test."""
        VenueClientFactory._registry.clear()
    
    def test_register_and_create(self):
        """Test registering and creating a venue client."""
        # Initially empty
        assert VenueClientFactory.available_venues() == []
        
        # Register mock client
        VenueClientFactory.register("mock", MockVenueClient)
        assert "mock" in VenueClientFactory.available_venues()
        
        # Create instance
        client = VenueClientFactory.create("mock", name="test_instance")
        assert isinstance(client, MockVenueClient)
        assert client.venue_name == "test_instance"
    
    def test_create_unknown_venue_raises(self):
        """Test that creating unknown venue raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            VenueClientFactory.create("unknown_venue")
        
        assert "Unknown venue: unknown_venue" in str(exc_info.value)
        assert "Available:" in str(exc_info.value)
    
    def test_multiple_venues(self):
        """Test registering multiple venues."""
        VenueClientFactory.register("mock1", MockVenueClient)
        VenueClientFactory.register("mock2", MockVenueClient)
        
        venues = VenueClientFactory.available_venues()
        assert len(venues) == 2
        assert "mock1" in venues
        assert "mock2" in venues
    
    def test_registry_is_class_attribute(self):
        """Test that _registry is shared across class."""
        VenueClientFactory.register("shared", MockVenueClient)
        # Accessing via class should show same registry
        assert "shared" in VenueClientFactory._registry


class TestDataclassFunctionality:
    """Tests for dataclass functionality and edge cases."""
    
    def test_venue_order_defaults(self):
        """Test VenueOrder default values."""
        order = VenueOrder(market_id="test", side="buy", size=Decimal("10"))
        assert order.order_type == "limit"
        assert order.outcome_id is None
        assert order.client_order_id is None
        assert order.time_in_force == "GTC"
        assert order.price is None
    
    def test_placed_order_defaults(self):
        """Test PlacedOrder default values."""
        order = PlacedOrder(
            order_id="123",
            market_id="test",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.5")
        )
        assert order.filled_size == Decimal("0")
        assert order.status == "pending"
        assert order.venue == ""
        assert order.remaining_size is None
    
    def test_venue_position_defaults(self):
        """Test VenuePosition default values."""
        pos = VenuePosition(
            market_id="test",
            outcome_id="yes",
            size=Decimal("100"),
            average_entry_price=Decimal("0.5")
        )
        assert pos.unrealized_pnl is None
        assert pos.realized_pnl is None
        assert pos.venue == ""
    
    def test_market_filter_defaults(self):
        """Test MarketFilter default values."""
        filter_params = MarketFilter()
        assert filter_params.active_only is True
        assert filter_params.category is None
        assert filter_params.search is None
        assert filter_params.limit == 100
        assert filter_params.offset == 0
        assert filter_params.min_volume is None
        assert filter_params.tags is None
    
    def test_quote_event_defaults(self):
        """Test QuoteEvent default values."""
        quote = QuoteEvent(
            market_id="test",
            outcome_id="yes",
            bid_price=Decimal("0.5"),
            ask_price=Decimal("0.6"),
            last_price=Decimal("0.55"),
            volume=Decimal("1000"),
            timestamp=datetime.now(timezone.utc)
        )
        assert quote.venue == ""
        assert quote.raw_data is None
