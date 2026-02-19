"""Tests for KalshiReconciler — deep position/order reconciliation.

Test Cases:
1. Perfect match → severity OK, no issues
2. Phantom position on venue → severity CRITICAL
3. Quantity mismatch on active market → severity CRITICAL
4. Stale open orders on venue → severity WARNING
5. Price mismatch → severity WARNING
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.reconciliation.kalshi_reconciler import (
    KalshiReconciler,
    ReconciliationIssue,
    ReconciliationReport,
    IssueSeverity,
    IssueType,
    get_kalshi_reconciler,
    reset_kalshi_reconciler,
)
from merid.event_venues.base import VenuePosition, PlacedOrder
from merid.matching_engine import Order, OrderSide, OrderStatus


@pytest.fixture
def mock_venue_adapter():
    """Mock KalshiVenueAdapter."""
    with patch("merid.reconciliation.kalshi_reconciler.get_kalshi_venue_adapter") as mock:
        adapter = MagicMock()
        adapter.get_positions = AsyncMock(return_value=[])
        adapter.get_orders = AsyncMock(return_value=[])
        mock.return_value = adapter
        yield adapter


@pytest.fixture
def mock_matching_engine():
    """Mock matching engine for internal state."""
    with patch("merid.reconciliation.kalshi_reconciler.get_matching_engine") as mock:
        engine = MagicMock()
        engine._orders = {}
        mock.return_value = engine
        yield engine


@pytest.fixture
def reconciler(mock_venue_adapter, mock_matching_engine):
    """Create a KalshiReconciler for testing."""
    reset_kalshi_reconciler()
    return KalshiReconciler()


# ── Test: Perfect Match ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_perfect_match(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test reconciliation when everything matches perfectly."""
    # Setup: 2 positions, both matching
    internal_order1 = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    internal_order1.status = OrderStatus.FILLED
    internal_order1.filled_quantity = 10.0
    internal_order1.filled_price = 0.55
    mock_matching_engine._orders[internal_order1.order_id] = internal_order1

    internal_order2 = Order(
        instrument_id="ETH-TEST-1",
        side=OrderSide.BUY,
        price=0.60,
        quantity=5.0,
        domain="prediction",
    )
    internal_order2.status = OrderStatus.FILLED
    internal_order2.filled_quantity = 5.0
    internal_order2.filled_price = 0.60
    mock_matching_engine._orders[internal_order2.order_id] = internal_order2

    # Venue has matching positions
    mock_venue_adapter.get_positions.return_value = [
        VenuePosition(
            market_id="BTC-TEST-1",
            outcome_id=None,
            size=Decimal("10.0"),
            average_entry_price=Decimal("0.55"),
            venue="kalshi",
        ),
        VenuePosition(
            market_id="ETH-TEST-1",
            outcome_id=None,
            size=Decimal("5.0"),
            average_entry_price=Decimal("0.60"),
            venue="kalshi",
        ),
    ]

    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "OK"
    assert len(report.issues) == 0
    assert report.summary == "All positions and orders reconciled successfully"
    assert report.internal_position_count == 2
    assert report.venue_position_count == 2


# ── Test: Phantom Position ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_phantom_position(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of phantom position (on venue, not in MERID)."""
    # No internal positions
    mock_matching_engine._orders = {}

    # Venue has a position
    mock_venue_adapter.get_positions.return_value = [
        VenuePosition(
            market_id="PHANTOM-MARKET",
            outcome_id=None,
            size=Decimal("20.0"),
            average_entry_price=Decimal("0.65"),
            venue="kalshi",
        ),
    ]
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "CRITICAL"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.PHANTOM_POSITION
    assert report.issues[0].severity == IssueSeverity.CRITICAL
    assert report.issues[0].instrument_id == "PHANTOM-MARKET"
    assert "exists on venue but not in MERID" in report.issues[0].message


# ── Test: Quantity Mismatch ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_quantity_mismatch_critical(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of significant quantity mismatch."""
    # Internal: 10 contracts
    internal_order = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 10.0
    internal_order.filled_price = 0.55
    mock_matching_engine._orders[internal_order.order_id] = internal_order

    # Venue: 15 contracts (5 contract difference)
    mock_venue_adapter.get_positions.return_value = [
        VenuePosition(
            market_id="BTC-TEST-1",
            outcome_id=None,
            size=Decimal("15.0"),
            average_entry_price=Decimal("0.55"),
            venue="kalshi",
        ),
    ]
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "CRITICAL"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.QUANTITY_MISMATCH
    assert report.issues[0].severity == IssueSeverity.CRITICAL
    assert report.issues[0].details["delta"] == 5.0


@pytest.mark.asyncio
async def test_reconcile_quantity_mismatch_warning(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of minor quantity mismatch (WARNING level)."""
    # Internal: 10 contracts
    internal_order = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 10.0
    internal_order.filled_price = 0.55
    mock_matching_engine._orders[internal_order.order_id] = internal_order

    # Venue: 10.5 contracts (0.5 contract difference)
    mock_venue_adapter.get_positions.return_value = [
        VenuePosition(
            market_id="BTC-TEST-1",
            outcome_id=None,
            size=Decimal("10.5"),
            average_entry_price=Decimal("0.55"),
            venue="kalshi",
        ),
    ]
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "WARNING"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.QUANTITY_MISMATCH
    assert report.issues[0].severity == IssueSeverity.WARNING
    assert report.issues[0].details["delta"] == 0.5


# ── Test: Stale Orders ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_stale_order(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of stale orders (MERID thinks open, venue doesn't have it)."""
    # Internal: pending order
    internal_order = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.PENDING
    mock_matching_engine._orders[internal_order.order_id] = internal_order

    mock_venue_adapter.get_positions.return_value = []
    # Venue doesn't have this order
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "WARNING"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.STALE_ORDER
    assert report.issues[0].severity == IssueSeverity.WARNING
    assert internal_order.order_id in report.issues[0].message or "pending" in report.issues[0].message.lower()


@pytest.mark.asyncio
async def test_reconcile_order_status_mismatch(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of order status mismatch."""
    order_id = "TEST-ORDER-123"
    
    # Internal: filled
    internal_order = Order(
        order_id=order_id,
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=10.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 10.0
    mock_matching_engine._orders[order_id] = internal_order

    mock_venue_adapter.get_positions.return_value = []
    # Venue: pending
    mock_venue_adapter.get_orders.return_value = [
        PlacedOrder(
            order_id=order_id,
            market_id="BTC-TEST-1",
            side="buy",
            size=Decimal("10.0"),
            price=Decimal("0.55"),
            filled_size=Decimal("0"),
            status="pending",
            venue="kalshi",
        ),
    ]

    report = await reconciler.reconcile()

    assert report.severity == "WARNING"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.STALE_ORDER
    assert report.issues[0].severity == IssueSeverity.WARNING
    assert "status mismatch" in report.issues[0].message.lower()


# ── Test: Price Mismatch ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_price_mismatch(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of entry price mismatch."""
    # Internal: entry price 0.50
    internal_order = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.50,
        quantity=10.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 10.0
    internal_order.filled_price = 0.50
    mock_matching_engine._orders[internal_order.order_id] = internal_order

    # Venue: entry price 0.60 (20% difference)
    mock_venue_adapter.get_positions.return_value = [
        VenuePosition(
            market_id="BTC-TEST-1",
            outcome_id=None,
            size=Decimal("10.0"),
            average_entry_price=Decimal("0.60"),
            venue="kalshi",
        ),
    ]
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    assert report.severity == "WARNING"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.PRICE_MISMATCH
    assert report.issues[0].severity == IssueSeverity.WARNING
    assert report.issues[0].details["pct_diff"] > 5.0


# ── Test: Missing Position (Paper Mode) ───────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_missing_position_large_size(reconciler, mock_venue_adapter, mock_matching_engine):
    """Test detection of missing position on venue (large size triggers warning)."""
    # Internal: 50 contracts
    internal_order = Order(
        instrument_id="BTC-TEST-1",
        side=OrderSide.BUY,
        price=0.55,
        quantity=50.0,
        domain="prediction",
    )
    internal_order.status = OrderStatus.FILLED
    internal_order.filled_quantity = 50.0
    internal_order.filled_price = 0.55
    mock_matching_engine._orders[internal_order.order_id] = internal_order

    # Venue: no position (expected in paper mode)
    mock_venue_adapter.get_positions.return_value = []
    mock_venue_adapter.get_orders.return_value = []

    report = await reconciler.reconcile()

    # Should warn for large missing position
    assert report.severity == "WARNING"
    assert len(report.issues) == 1
    assert report.issues[0].issue_type == IssueType.MISSING_POSITION
    assert report.issues[0].severity == IssueSeverity.WARNING


# ── Test: Report Serialization ────────────────────────────────────────────

def test_reconciliation_issue_to_dict():
    """Test ReconciliationIssue serialization."""
    issue = ReconciliationIssue(
        issue_type=IssueType.PHANTOM_POSITION,
        severity=IssueSeverity.CRITICAL,
        instrument_id="TEST-MARKET",
        message="Test message",
        details={"test": "data"},
    )

    d = issue.to_dict()
    assert d["issue_type"] == "phantom_position"
    assert d["severity"] == "critical"
    assert d["instrument_id"] == "TEST-MARKET"
    assert d["message"] == "Test message"
    assert d["details"]["test"] == "data"


def test_reconciliation_report_to_dict():
    """Test ReconciliationReport serialization."""
    issues = [
        ReconciliationIssue(
            issue_type=IssueType.QUANTITY_MISMATCH,
            severity=IssueSeverity.CRITICAL,
            instrument_id="TEST-1",
            message="Test 1",
        ),
        ReconciliationIssue(
            issue_type=IssueType.PRICE_MISMATCH,
            severity=IssueSeverity.WARNING,
            instrument_id="TEST-2",
            message="Test 2",
        ),
    ]

    report = ReconciliationReport(
        venue="kalshi",
        domain="prediction",
        timestamp=1234567890.0,
        issues=issues,
        internal_position_count=5,
        venue_position_count=6,
    )

    d = report.to_dict()
    assert d["venue"] == "kalshi"
    assert d["severity"] == "CRITICAL"  # Has critical issue
    assert d["issue_count"] == 2
    assert len(d["issues"]) == 2


# ── Test: Singleton ────────────────────────────────────────────────────────

def test_singleton_accessor():
    """Test singleton accessor returns same instance."""
    reset_kalshi_reconciler()
    
    r1 = get_kalshi_reconciler()
    r2 = get_kalshi_reconciler()
    
    assert r1 is r2
