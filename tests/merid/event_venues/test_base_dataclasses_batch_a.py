"""Tests for merid/event_venues/base.py dataclasses - Batch A."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from merid.event_venues.base import (
    EventOutcome, EventMarket, VenueOrder, PlacedOrder,
    VenuePosition, VenueTrade, VenueOrderBook, MarketFilter
)


class TestEventOutcomeDataclass:
    """Tests for EventOutcome dataclass."""

    def test_event_outcome_creation(self):
        outcome = EventOutcome(
            outcome_id="yes",
            outcome_name="Yes",
            price=Decimal("0.60"),
            probability=Decimal("0.60"),
            best_ask=Decimal("0.61"),
            best_bid=Decimal("0.59")
        )
        assert outcome.outcome_id == "yes"
        assert outcome.outcome_name == "Yes"
        assert outcome.price == Decimal("0.60")
        assert outcome.probability == Decimal("0.60")
        assert outcome.best_ask == Decimal("0.61")
        assert outcome.best_bid == Decimal("0.59")

    def test_event_outcome_defaults(self):
        outcome = EventOutcome(
            outcome_id="no",
            outcome_name="No",
            price=Decimal("0.40")
        )
        assert outcome.probability is None
        assert outcome.best_ask is None
        assert outcome.best_bid is None


class TestEventMarketDataclass:
    """Tests for EventMarket dataclass."""

    def test_event_market_creation(self):
        outcome = EventOutcome(
            outcome_id="yes",
            outcome_name="Yes",
            price=Decimal("0.60")
        )
        market = EventMarket(
            market_id="BTC-PRICE-100K",
            venue="kalshi",
            question="Will BTC hit $100K?",
            description="Bitcoin price prediction",
            outcomes=[outcome],
            active=True
        )
        assert market.market_id == "BTC-PRICE-100K"
        assert market.venue == "kalshi"
        assert market.question == "Will BTC hit $100K?"
        assert len(market.outcomes) == 1
        assert market.active is True

    def test_event_market_post_init(self):
        """Test that __post_init__ initializes tags to empty list."""
        market = EventMarket(
            market_id="TEST",
            venue="test",
            question="Test?",
            description="Test desc",
            outcomes=[]
        )
        assert market.tags == []


class TestVenueOrderDataclass:
    """Tests for VenueOrder dataclass."""

    def test_venue_order_creation(self):
        order = VenueOrder(
            market_id="BTC-PRICE-100K",
            side="buy",
            size=Decimal("10"),
            order_type="limit",
            price=Decimal("0.60"),
            outcome_id="yes"
        )
        assert order.market_id == "BTC-PRICE-100K"
        assert order.side == "buy"
        assert order.size == Decimal("10")
        assert order.order_type == "limit"
        assert order.price == Decimal("0.60")
        assert order.outcome_id == "yes"

    def test_venue_order_defaults(self):
        order = VenueOrder(
            market_id="TEST",
            side="sell",
            size=Decimal("5")
        )
        assert order.price is None
        assert order.order_type == "limit"
        assert order.outcome_id is None
        assert order.client_order_id is None
        assert order.time_in_force == "GTC"


class TestPlacedOrderDataclass:
    """Tests for PlacedOrder dataclass."""

    def test_placed_order_creation(self):
        order = PlacedOrder(
            order_id="order_123",
            market_id="BTC-PRICE-100K",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.60"),
            status="filled",
            venue="kalshi"
        )
        assert order.order_id == "order_123"
        assert order.status == "filled"
        assert order.venue == "kalshi"

    def test_placed_order_defaults(self):
        order = PlacedOrder(
            order_id="order_456",
            market_id="TEST",
            side="sell",
            size=Decimal("5"),
            price=None
        )
        assert order.filled_size == Decimal("0")
        assert order.remaining_size is None
        assert order.status == "pending"
        assert order.venue == ""


class TestVenuePositionDataclass:
    """Tests for VenuePosition dataclass."""

    def test_venue_position_creation(self):
        position = VenuePosition(
            market_id="BTC-PRICE-100K",
            outcome_id="yes",
            size=Decimal("100"),
            average_entry_price=Decimal("0.55"),
            unrealized_pnl=Decimal("5.0"),
            venue="kalshi"
        )
        assert position.market_id == "BTC-PRICE-100K"
        assert position.outcome_id == "yes"
        assert position.size == Decimal("100")
        assert position.average_entry_price == Decimal("0.55")
        assert position.unrealized_pnl == Decimal("5.0")
        assert position.venue == "kalshi"


class TestVenueOrderBookDataclass:
    """Tests for VenueOrderBook dataclass."""

    def test_venue_orderbook_creation(self):
        from datetime import datetime, timezone
        orderbook = VenueOrderBook(
            market_id="BTC-PRICE-100K",
            outcome_id="yes",
            bids=[(Decimal("0.59"), Decimal("100"))],
            asks=[(Decimal("0.61"), Decimal("50"))],
            timestamp=datetime.now(timezone.utc),
            venue="kalshi"
        )
        assert orderbook.market_id == "BTC-PRICE-100K"
        assert len(orderbook.bids) == 1
        assert len(orderbook.asks) == 1
        assert orderbook.venue == "kalshi"


class TestMarketFilterDataclass:
    """Tests for MarketFilter dataclass."""

    def test_market_filter_creation(self):
        filter_params = MarketFilter(
            category="crypto",
            active_only=True,
            limit=50
        )
        assert filter_params.category == "crypto"
        assert filter_params.active_only is True
        assert filter_params.limit == 50

    def test_market_filter_defaults(self):
        filter_params = MarketFilter()
        assert filter_params.category is None
        assert filter_params.active_only is True
        assert filter_params.limit == 100
