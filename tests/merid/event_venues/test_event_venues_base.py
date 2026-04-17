"""Tests for merid/event_venues/base.py."""
import pytest
from datetime import datetime
from decimal import Decimal
from merid.event_venues.base import (
    EventOutcome, EventMarket, VenueOrder, PlacedOrder, VenuePosition,
    VenueTrade, VenueOrderBook, MarketFilter, QuoteEvent,
    EventVenueClient, EventVenueStream, VenueClientFactory
)


class TestEventOutcome:
    """Test EventOutcome dataclass."""

    def test_creation(self):
        """Test EventOutcome creation."""
        outcome = EventOutcome(
            outcome_id="yes",
            outcome_name="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65"),
            best_ask=Decimal("0.66"),
            best_bid=Decimal("0.64")
        )
        assert outcome.outcome_id == "yes"
        assert outcome.outcome_name == "Yes"
        assert outcome.price == Decimal("0.65")
        assert outcome.probability == Decimal("0.65")
        assert outcome.best_ask == Decimal("0.66")
        assert outcome.best_bid == Decimal("0.64")


class TestEventMarket:
    """Test EventMarket dataclass."""

    def test_creation(self):
        """Test EventMarket creation."""
        outcome = EventOutcome(
            outcome_id="yes", outcome_name="Yes", price=Decimal("0.65")
        )
        market = EventMarket(
            market_id="market_123",
            venue="polymarket",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome],
            category="weather",
            active=True
        )
        assert market.market_id == "market_123"
        assert market.venue == "polymarket"
        assert market.question == "Will it rain?"
        assert len(market.outcomes) == 1
        assert market.active is True

    def test_post_init_tags_none(self):
        """Test __post_init__ when tags is None."""
        outcome = EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.65"))
        market = EventMarket(
            market_id="market_123",
            venue="kalshi",
            question="Test",
            description="Test desc",
            outcomes=[outcome],
            tags=None
        )
        assert market.tags == []


class TestVenueOrder:
    """Test VenueOrder dataclass."""

    def test_creation(self):
        """Test VenueOrder creation."""
        order = VenueOrder(
            market_id="market_123",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            order_type="limit",
            outcome_id="yes",
            client_order_id="client_123",
            time_in_force="GTC"
        )
        assert order.market_id == "market_123"
        assert order.side == "buy"
        assert order.size == Decimal("100")
        assert order.price == Decimal("0.65")
        assert order.order_type == "limit"
        assert order.outcome_id == "yes"
        assert order.client_order_id == "client_123"
        assert order.time_in_force == "GTC"


class TestPlacedOrder:
    """Test PlacedOrder dataclass."""

    def test_creation(self):
        """Test PlacedOrder creation."""
        order = PlacedOrder(
            order_id="ord_123",
            market_id="market_456",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            filled_size=Decimal("50"),
            remaining_size=Decimal("50"),
            status="partially_filled",
            venue="polymarket"
        )
        assert order.order_id == "ord_123"
        assert order.status == "partially_filled"
        assert order.venue == "polymarket"


class TestVenuePosition:
    """Test VenuePosition dataclass."""

    def test_creation(self):
        """Test VenuePosition creation."""
        position = VenuePosition(
            market_id="market_123",
            outcome_id="yes",
            size=Decimal("100"),
            average_entry_price=Decimal("0.60"),
            unrealized_pnl=Decimal("5.00"),
            realized_pnl=Decimal("0"),
            venue="kalshi"
        )
        assert position.market_id == "market_123"
        assert position.outcome_id == "yes"
        assert position.size == Decimal("100")
        assert position.average_entry_price == Decimal("0.60")
        assert position.venue == "kalshi"


class TestVenueTrade:
    """Test VenueTrade dataclass."""

    def test_creation(self):
        """Test VenueTrade creation."""
        now = datetime.now()
        trade = VenueTrade(
            trade_id="trd_123",
            market_id="market_456",
            order_id="ord_789",
            side="buy",
            size=Decimal("50"),
            price=Decimal("0.65"),
            fee=Decimal("0.50"),
            timestamp=now,
            venue="polymarket"
        )
        assert trade.trade_id == "trd_123"
        assert trade.venue == "polymarket"
        assert trade.timestamp == now


class TestVenueOrderBook:
    """Test VenueOrderBook dataclass."""

    def test_creation(self):
        """Test VenueOrderBook creation."""
        now = datetime.now()
        ob = VenueOrderBook(
            market_id="market_123",
            outcome_id="yes",
            bids=[(Decimal("0.64"), Decimal("100"))],
            asks=[(Decimal("0.66"), Decimal("150"))],
            timestamp=now,
            venue="kalshi"
        )
        assert ob.market_id == "market_123"
        assert ob.outcome_id == "yes"
        assert len(ob.bids) == 1
        assert len(ob.asks) == 1
        assert ob.venue == "kalshi"


class TestMarketFilter:
    """Test MarketFilter dataclass."""

    def test_default_values(self):
        """Test default filter values."""
        filter_params = MarketFilter()
        assert filter_params.active_only is True
        assert filter_params.limit == 100
        assert filter_params.offset == 0
        assert filter_params.category is None

    def test_custom_values(self):
        """Test custom filter values."""
        filter_params = MarketFilter(
            active_only=False,
            category="sports",
            limit=50,
            min_volume=Decimal("10000")
        )
        assert filter_params.active_only is False
        assert filter_params.category == "sports"
        assert filter_params.limit == 50
        assert filter_params.min_volume == Decimal("10000")


class TestQuoteEvent:
    """Test QuoteEvent dataclass."""

    def test_creation(self):
        """Test QuoteEvent creation."""
        now = datetime.now()
        quote = QuoteEvent(
            market_id="market_123",
            outcome_id="yes",
            bid_price=Decimal("0.64"),
            ask_price=Decimal("0.66"),
            last_price=Decimal("0.65"),
            volume=Decimal("10000"),
            timestamp=now,
            venue="polymarket"
        )
        assert quote.market_id == "market_123"
        assert quote.bid_price == Decimal("0.64")
        assert quote.ask_price == Decimal("0.66")
        assert quote.last_price == Decimal("0.65")
        assert quote.venue == "polymarket"


class TestEventVenueClient:
    """Test EventVenueClient abstract class."""

    def test_cannot_instantiate(self):
        """Test EventVenueClient cannot be instantiated directly."""
        with pytest.raises(TypeError):
            EventVenueClient()


class TestEventVenueStream:
    """Test EventVenueStream abstract class."""

    def test_cannot_instantiate(self):
        """Test EventVenueStream cannot be instantiated directly."""
        with pytest.raises(TypeError):
            EventVenueStream()


class TestVenueClientFactory:
    """Test VenueClientFactory class."""

    def setup_method(self):
        """Clear registry before each test."""
        VenueClientFactory._registry.clear()

    def test_register_and_create(self):
        """Test registering and creating a client."""
        class MockClient(EventVenueClient):
            @property
            def venue_name(self):
                return "mock"
            async def connect(self): pass
            async def close(self): pass
            async def list_markets(self, filter_params=None): return []
            async def get_market(self, market_id): return None
            async def get_orderbook(self, market_id, outcome_id=None): return None
            async def place_order(self, order): return None
            async def cancel_order(self, order_id, market_id=None): return False
            async def get_order(self, order_id, market_id=None): return None
            async def get_open_orders(self, market_id=None): return []
            async def get_positions(self): return []
            async def get_trades(self, limit=100): return []
            async def get_balance(self): return {}

        VenueClientFactory.register("mock", MockClient)
        client = VenueClientFactory.create("mock")
        assert isinstance(client, MockClient)

    def test_create_unknown_venue_raises(self):
        """Test creating unknown venue raises ValueError."""
        with pytest.raises(ValueError, match="Unknown venue"):
            VenueClientFactory.create("unknown")

    def test_available_venues(self):
        """Test listing available venues."""
        class MockClient:
            pass
        
        VenueClientFactory.register("venue1", MockClient)
        VenueClientFactory.register("venue2", MockClient)
        
        venues = VenueClientFactory.available_venues()
        assert "venue1" in venues
        assert "venue2" in venues
