"""Comprehensive tests for merid/event_venues/base.py - REAL implementation coverage."""

import pytest
from datetime import datetime
from decimal import Decimal

from merid.event_venues.base import (
    EventOutcome,
    EventMarket,
    VenueOrder,
    PlacedOrder,
    VenuePosition,
    VenueTrade,
    VenueOrderBook,
    MarketFilter,
    EventVenueClient,
)


class TestEventOutcome:
    """Test EventOutcome dataclass."""
    
    def test_event_outcome_creation(self):
        """Test EventOutcome creation."""
        outcome = EventOutcome(
            outcome_id="outcome_1",
            outcome_name="Yes",
            price=Decimal("0.65"),
            probability=Decimal("0.65"),
            best_ask=Decimal("0.67"),
            best_bid=Decimal("0.63")
        )
        
        assert outcome.outcome_id == "outcome_1"
        assert outcome.outcome_name == "Yes"
        assert outcome.price == Decimal("0.65")
        assert outcome.probability == Decimal("0.65")
        assert outcome.best_ask == Decimal("0.67")
        assert outcome.best_bid == Decimal("0.63")
    
    def test_event_outcome_optional_fields(self):
        """Test EventOutcome with optional fields as None."""
        outcome = EventOutcome(
            outcome_id="outcome_1",
            outcome_name="Yes",
            price=Decimal("0.65")
        )
        
        assert outcome.probability is None
        assert outcome.best_ask is None
        assert outcome.best_bid is None


class TestEventMarket:
    """Test EventMarket dataclass."""
    
    def test_event_market_creation(self):
        """Test EventMarket creation."""
        outcome = EventOutcome(
            outcome_id="outcome_1",
            outcome_name="Yes",
            price=Decimal("0.65")
        )
        
        market = EventMarket(
            market_id="market_1",
            venue="polymarket",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome],
            category="weather",
            tags=["weather", "prediction"],
            volume=Decimal("100000"),
            liquidity=Decimal("50000"),
            active=True
        )
        
        assert market.market_id == "market_1"
        assert market.venue == "polymarket"
        assert market.question == "Will it rain?"
        assert len(market.outcomes) == 1
        assert market.category == "weather"
        assert market.tags == ["weather", "prediction"]
        assert market.volume == Decimal("100000")
        assert market.liquidity == Decimal("50000")
        assert market.active is True
        assert market.resolved is False
    
    def test_event_market_post_init(self):
        """Test EventMarket __post_init__ sets default tags."""
        outcome = EventOutcome(
            outcome_id="outcome_1",
            outcome_name="Yes",
            price=Decimal("0.65")
        )
        
        market = EventMarket(
            market_id="market_1",
            venue="polymarket",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome]
        )
        
        assert market.tags == []
    
    def test_event_market_with_resolution(self):
        """Test EventMarket with resolution data."""
        outcome = EventOutcome(
            outcome_id="outcome_1",
            outcome_name="Yes",
            price=Decimal("0.65")
        )
        
        market = EventMarket(
            market_id="market_1",
            venue="polymarket",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[outcome],
            resolved=True,
            resolution="Yes",
            resolved_at=datetime.utcnow()
        )
        
        assert market.resolved is True
        assert market.resolution == "Yes"
        assert market.resolved_at is not None


class TestVenueOrder:
    """Test VenueOrder dataclass."""
    
    def test_venue_order_creation(self):
        """Test VenueOrder creation."""
        order = VenueOrder(
            market_id="market_1",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            order_type="limit",
            outcome_id="outcome_1",
            client_order_id="client_123",
            time_in_force="GTC"
        )
        
        assert order.market_id == "market_1"
        assert order.side == "buy"
        assert order.size == Decimal("100")
        assert order.price == Decimal("0.65")
        assert order.order_type == "limit"
        assert order.outcome_id == "outcome_1"
        assert order.client_order_id == "client_123"
        assert order.time_in_force == "GTC"
    
    def test_venue_order_market_order(self):
        """Test VenueOrder as market order (no price)."""
        order = VenueOrder(
            market_id="market_1",
            side="sell",
            size=Decimal("50"),
            order_type="market"
        )
        
        assert order.price is None
        assert order.order_type == "market"
        assert order.time_in_force == "GTC"  # Default


class TestPlacedOrder:
    """Test PlacedOrder dataclass."""
    
    def test_placed_order_creation(self):
        """Test PlacedOrder creation."""
        order = PlacedOrder(
            order_id="order_123",
            market_id="market_1",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65"),
            filled_size=Decimal("50"),
            remaining_size=Decimal("50"),
            status="partially_filled",
            venue="polymarket"
        )
        
        assert order.order_id == "order_123"
        assert order.market_id == "market_1"
        assert order.side == "buy"
        assert order.size == Decimal("100")
        assert order.price == Decimal("0.65")
        assert order.filled_size == Decimal("50")
        assert order.remaining_size == Decimal("50")
        assert order.status == "partially_filled"
        assert order.venue == "polymarket"
    
    def test_placed_order_defaults(self):
        """Test PlacedOrder default values."""
        order = PlacedOrder(
            order_id="order_123",
            market_id="market_1",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.65")
        )
        
        assert order.filled_size == Decimal("0")
        assert order.status == "pending"
        assert order.venue == ""


class TestVenuePosition:
    """Test VenuePosition dataclass."""
    
    def test_venue_position_creation(self):
        """Test VenuePosition creation."""
        position = VenuePosition(
            market_id="market_1",
            outcome_id="outcome_1",
            size=Decimal("100"),
            average_entry_price=Decimal("0.65"),
            unrealized_pnl=Decimal("10.50"),
            realized_pnl=Decimal("5.25"),
            venue="polymarket"
        )
        
        assert position.market_id == "market_1"
        assert position.outcome_id == "outcome_1"
        assert position.size == Decimal("100")
        assert position.average_entry_price == Decimal("0.65")
        assert position.unrealized_pnl == Decimal("10.50")
        assert position.realized_pnl == Decimal("5.25")
        assert position.venue == "polymarket"


class TestVenueOrderBook:
    """Test VenueOrderBook dataclass."""
    
    def test_venue_order_book_creation(self):
        """Test VenueOrderBook creation."""
        orderbook = VenueOrderBook(
            market_id="market_1",
            outcome_id="outcome_1",
            bids=[(Decimal("0.63"), Decimal("100"))],
            asks=[(Decimal("0.67"), Decimal("100"))],
            timestamp=datetime.utcnow()
        )
        
        assert orderbook.market_id == "market_1"
        assert orderbook.outcome_id == "outcome_1"
        assert len(orderbook.bids) == 1
        assert len(orderbook.asks) == 1
        assert orderbook.timestamp is not None


class TestMarketFilter:
    """Test MarketFilter dataclass."""
    
    def test_market_filter_creation(self):
        """Test MarketFilter creation."""
        filter_obj = MarketFilter(
            active_only=True,
            category="sports",
            limit=100,
            offset=0
        )
        
        assert filter_obj.active_only is True
        assert filter_obj.category == "sports"
        assert filter_obj.limit == 100
        assert filter_obj.offset == 0


# =============================================================================
# POINTER MARKS FOR PYTEST-CHECKLIST
# =============================================================================

class TestEventVenuesBasePointers:
    """Pointer tests for pytest-checklist to track critical function coverage."""
    
    @pytest.mark.asyncio
    async def test_event_outcome_creation_coverage(self):
        """Pointer: EventOutcome creation coverage."""
        outcome = EventOutcome(
            outcome_id="test",
            outcome_name="Test",
            price=Decimal("0.5")
        )
        assert outcome.outcome_id == "test"
    
    @pytest.mark.asyncio
    async def test_event_market_creation_coverage(self):
        """Pointer: EventMarket creation coverage."""
        outcome = EventOutcome(
            outcome_id="test",
            outcome_name="Test",
            price=Decimal("0.5")
        )
        market = EventMarket(
            market_id="test",
            venue="test",
            question="Test?",
            description="Test",
            outcomes=[outcome]
        )
        assert market.market_id == "test"
    
    @pytest.mark.asyncio
    async def test_venue_order_creation_coverage(self):
        """Pointer: VenueOrder creation coverage."""
        order = VenueOrder(
            market_id="test",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.5")
        )
        assert order.market_id == "test"
    
    @pytest.mark.asyncio
    async def test_placed_order_creation_coverage(self):
        """Pointer: PlacedOrder creation coverage."""
        order = PlacedOrder(
            order_id="test",
            market_id="test",
            side="buy",
            size=Decimal("100"),
            price=Decimal("0.5")
        )
        assert order.order_id == "test"
