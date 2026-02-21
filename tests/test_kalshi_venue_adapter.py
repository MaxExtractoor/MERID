"""Tests for KalshiVenueAdapter — venue integration layer.

Tests:
- Instrument discovery and mapping
- Position aggregation (paper mode)
- Order submission and routing
- Risk snapshot generation
- Mode switching (paper/live)
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.venue_adapter import (
    KalshiVenueAdapter,
    get_kalshi_venue_adapter,
    reset_kalshi_venue_adapter,
)
from merid.event_venues.base import EventMarket, VenueOrder, VenuePosition, EventOutcome
from merid.matching_engine import Order, Fill, OrderSide, OrderStatus, MatchingEngine
from merid.paper_config import InstrumentConfig, DomainMode


@pytest.fixture
def mock_catalog():
    """Mock Kalshi market catalog."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_market_catalog") as mock:
        catalog = MagicMock()
        
        # Create mock markets
        markets = []
        for i in range(3):
            market = EventMarket(
                market_id=f"BTC-TEST-{i}",
                venue="kalshi",
                question=f"Will BTC hit $50k? (Market {i})",
                description="Test market",
                outcomes=[
                    EventOutcome("yes", "Yes", Decimal("0.55")),
                    EventOutcome("no", "No", Decimal("0.45")),
                ],
                category="crypto",
                active=True,
                volume=Decimal("10000"),
            )
            
            # Wrap in CatalogMarket-like object
            cm = MagicMock()
            cm.market = market
            cm.category = "crypto"
            markets.append(cm)
        
        catalog.get_all_markets.return_value = markets
        mock.return_value = catalog
        yield catalog


@pytest.fixture
def mock_matching_engine():
    """Mock matching engine for paper mode."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_matching_engine") as mock:
        engine = MagicMock(spec=MatchingEngine)
        engine.domain = "prediction"
        engine._orders = {}
        engine._fills = []
        
        # Mock submit_order to return a fill
        def submit_order(order):
            fill = Fill(
                order_id=order.order_id,
                instrument_id=order.instrument_id,
                side=order.side,
                price=order.price if order.price > 0 else 0.50,
                quantity=order.quantity,
                notional_usd=order.quantity * (order.price if order.price > 0 else 0.50),
            )
            
            # Store order as filled
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.filled_price = fill.price
            engine._orders[order.order_id] = order
            engine._fills.append(fill)
            
            return fill
        
        engine.submit_order = MagicMock(side_effect=submit_order)
        mock.return_value = engine
        yield engine


@pytest.fixture
def adapter(mock_catalog, mock_matching_engine):
    """Create a KalshiVenueAdapter for testing."""
    reset_kalshi_venue_adapter()
    adapter = KalshiVenueAdapter(mode="paper")
    return adapter


# ── Test: Adapter Initialization ──────────────────────────────────────────

def test_adapter_initialization():
    """Test adapter initializes with correct defaults."""
    reset_kalshi_venue_adapter()
    adapter = KalshiVenueAdapter(mode="paper")
    
    assert adapter.venue_name == "kalshi"
    assert adapter.mode == DomainMode.PAPER
    assert adapter._instruments_cache == []
    assert adapter._cache_ts == 0.0


def test_adapter_singleton():
    """Test singleton accessor works correctly."""
    reset_kalshi_venue_adapter()
    
    adapter1 = get_kalshi_venue_adapter()
    adapter2 = get_kalshi_venue_adapter()
    
    assert adapter1 is adapter2


# ── Test: Instrument Discovery ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_instruments(adapter, mock_catalog):
    """Test listing instruments from catalog."""
    instruments = await adapter.list_instruments()
    
    assert len(instruments) == 3
    assert all(isinstance(inst, InstrumentConfig) for inst in instruments)
    assert all(inst.domain == "prediction" for inst in instruments)
    assert all("kalshi" in inst.venues for inst in instruments)
    assert instruments[0].id == "BTC-TEST-0"


@pytest.mark.asyncio
async def test_list_instruments_with_category_filter(adapter, mock_catalog):
    """Test filtering instruments by category."""
    instruments = await adapter.list_instruments(category="crypto")
    
    assert len(instruments) == 3
    assert all(inst.id.startswith("BTC") for inst in instruments)


@pytest.mark.asyncio
async def test_list_instruments_caching(adapter, mock_catalog):
    """Test instrument list is cached."""
    # First call
    instruments1 = await adapter.list_instruments()
    call_count_1 = mock_catalog.get_all_markets.call_count
    
    # Second call (should use cache)
    instruments2 = await adapter.list_instruments()
    call_count_2 = mock_catalog.get_all_markets.call_count
    
    assert instruments1 == instruments2
    assert call_count_2 == call_count_1  # No additional call
    
    # Force refresh
    instruments3 = await adapter.list_instruments(force_refresh=True)
    call_count_3 = mock_catalog.get_all_markets.call_count
    
    assert call_count_3 == call_count_1 + 1  # One more call


# ── Test: Positions (Paper Mode) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_positions_paper_mode_empty(adapter, mock_matching_engine):
    """Test getting positions when no orders exist."""
    positions = await adapter.get_positions()
    
    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_paper_mode_with_fills(adapter, mock_matching_engine):
    """Test position aggregation from filled orders."""
    # Create some filled orders
    order1 = Order(
        instrument_id="BTC-TEST-0",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    order1.status = OrderStatus.FILLED
    order1.filled_quantity = 10.0
    order1.filled_price = 0.55
    mock_matching_engine._orders[order1.order_id] = order1
    
    order2 = Order(
        instrument_id="BTC-TEST-0",
        side=OrderSide.BUY,
        price=0.60,
        quantity=5.0,
        domain="prediction",
    )
    order2.status = OrderStatus.FILLED
    order2.filled_quantity = 5.0
    order2.filled_price = 0.60
    mock_matching_engine._orders[order2.order_id] = order2
    
    positions = await adapter.get_positions()
    
    assert len(positions) == 1
    assert positions[0].market_id == "BTC-TEST-0"
    assert positions[0].size == Decimal("15")  # 10 + 5
    assert positions[0].venue == "kalshi"
    
    # Check average price: (10*0.55 + 5*0.60) / 15 = 0.5666...
    expected_avg = Decimal("0.5666666666666667")
    assert abs(positions[0].average_entry_price - expected_avg) < Decimal("0.0001")


# ── Test: Orders ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_orders_paper_mode(adapter, mock_matching_engine):
    """Test getting orders from matching engine."""
    # Add some orders
    order = Order(
        instrument_id="BTC-TEST-0",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    mock_matching_engine._orders[order.order_id] = order
    
    orders = await adapter.get_orders()
    
    assert len(orders) == 1
    assert orders[0].market_id == "BTC-TEST-0"
    assert orders[0].side == "buy"
    assert orders[0].size == Decimal("10")


# ── Test: Order Submission (Paper Mode) ───────────────────────────────────

@pytest.mark.asyncio
async def test_submit_order_paper_mode(adapter, mock_matching_engine):
    """Test submitting order in paper mode."""
    venue_order = VenueOrder(
        market_id="BTC-TEST-0",
        side="buy",
        size=Decimal("10"),
        price=Decimal("0.55"),
        order_type="limit",
    )
    
    placed = await adapter.submit_order(venue_order)
    
    assert placed.market_id == "BTC-TEST-0"
    assert placed.side == "buy"
    assert placed.size == Decimal("10")
    assert placed.filled_size == Decimal("10")  # Paper mode = immediate fill
    assert placed.status == "filled"
    assert placed.venue == "kalshi"


@pytest.mark.asyncio
async def test_submit_order_paper_mode_no_engine(adapter):
    """Test order submission fails gracefully without matching engine."""
    with patch("merid.event_venues.kalshi.venue_adapter.get_matching_engine", return_value=None):
        venue_order = VenueOrder(
            market_id="BTC-TEST-0",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.55"),
        )
        
        with pytest.raises(RuntimeError, match="Matching engine not available"):
            await adapter.submit_order(venue_order)


# ── Test: Risk Snapshot ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_risk_snapshot_empty(adapter, mock_matching_engine):
    """Test risk snapshot with no positions."""
    snapshot = await adapter.get_risk_snapshot()
    
    assert snapshot["venue"] == "kalshi"
    assert snapshot["mode"] == "paper"
    assert snapshot["total_notional_usd"] == 0.0
    assert snapshot["unrealized_pnl_usd"] == 0.0
    assert snapshot["position_count"] == 0
    assert snapshot["order_count"] == 0


@pytest.mark.asyncio
async def test_get_risk_snapshot_with_positions(adapter, mock_matching_engine):
    """Test risk snapshot with active positions."""
    # Add filled order
    order = Order(
        instrument_id="BTC-TEST-0",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    order.status = OrderStatus.FILLED
    order.filled_quantity = 10.0
    order.filled_price = 0.55
    mock_matching_engine._orders[order.order_id] = order
    
    snapshot = await adapter.get_risk_snapshot()
    
    assert snapshot["venue"] == "kalshi"
    assert snapshot["position_count"] == 1
    assert snapshot["total_notional_usd"] == 5.5  # 10 * 0.55


# ── Test: Mode Switching ───────────────────────────────────────────────────

def test_adapter_mode_paper():
    """Test adapter respects paper mode."""
    reset_kalshi_venue_adapter()
    adapter = KalshiVenueAdapter(mode="paper")
    assert adapter.mode == DomainMode.PAPER


def test_adapter_mode_live():
    """Test adapter respects live mode."""
    reset_kalshi_venue_adapter()
    adapter = KalshiVenueAdapter(mode="live")
    assert adapter.mode == DomainMode.LIVE


@pytest.mark.asyncio
async def test_live_mode_calls_client(adapter):
    """Test that live mode attempts to use KalshiVenueClient."""
    adapter.mode = DomainMode.LIVE
    
    # Mock the client
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(return_value=[])
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()
    adapter._client = mock_client
    
    positions = await adapter.get_positions()
    
    mock_client.connect.assert_called_once()
    mock_client.get_positions.assert_called_once()
    mock_client.close.assert_called_once()
    assert positions == []
