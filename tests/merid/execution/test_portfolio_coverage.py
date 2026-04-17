"""Comprehensive tests for merid/execution/portfolio.py - Coverage improvement."""

import pytest
from merid.execution.portfolio import (
    AggregatedPosition, PortfolioSnapshot, PortfolioAggregator
)
from merid.execution.base import Position


# =============================================================================
# AggregatedPosition Dataclass Tests
# =============================================================================

class TestAggregatedPosition:
    """Test AggregatedPosition dataclass."""

    def test_creation(self):
        position = AggregatedPosition(
            symbol="BTC/USD",
            total_size=1.5,
            avg_entry_price=50000.0,
            unrealized_pnl=1000.0
        )
        assert position.symbol == "BTC/USD"
        assert position.total_size == 1.5

    def test_with_venue_breakdown(self):
        position = AggregatedPosition(
            symbol="ETH/USD",
            total_size=10.0,
            avg_entry_price=3000.0,
            unrealized_pnl=500.0,
            venue_breakdown={"alpaca": 5.0, "coinbase": 5.0}
        )
        assert position.venue_breakdown["alpaca"] == 5.0


# =============================================================================
# PortfolioSnapshot Dataclass Tests
# =============================================================================

class TestPortfolioSnapshot:
    """Test PortfolioSnapshot dataclass."""

    def test_creation(self):
        snapshot = PortfolioSnapshot(
            positions=[],
            total_unrealized_pnl=1000.0,
            total_notional=50000.0
        )
        assert snapshot.total_unrealized_pnl == 1000.0

    def test_with_metadata(self):
        snapshot = PortfolioSnapshot(
            positions=[],
            total_unrealized_pnl=0.0,
            total_notional=0.0,
            metadata={"venues": ["alpaca", "coinbase"]}
        )
        assert "alpaca" in snapshot.metadata["venues"]


# =============================================================================
# PortfolioAggregator Tests
# =============================================================================

@pytest.fixture
def aggregator():
    """Create PortfolioAggregator."""
    return PortfolioAggregator()


class TestPortfolioAggregatorInit:
    """Test PortfolioAggregator initialization."""

    def test_defaults(self, aggregator):
        assert aggregator.daily_pnl == 0.0
        assert aggregator.open_orders_count == 0


class TestDailyPnl:
    """Test daily_pnl property."""

    def test_initial_value(self, aggregator):
        assert aggregator.daily_pnl == 0.0

    def test_after_recording(self, aggregator):
        aggregator.record_trade_pnl(100.0)
        assert aggregator.daily_pnl == 100.0


class TestOpenOrdersCount:
    """Test open_orders_count property."""

    def test_initial_value(self, aggregator):
        assert aggregator.open_orders_count == 0


class TestGetSymbolExposure:
    """Test get_symbol_exposure method."""

    def test_unknown_symbol(self, aggregator):
        exposure = aggregator.get_symbol_exposure("UNKNOWN")
        assert exposure == 0.0

    def test_after_update(self, aggregator):
        aggregator.update_symbol_exposure("BTC", 10000.0)
        assert aggregator.get_symbol_exposure("BTC") == 10000.0


class TestRecordTradePnl:
    """Test record_trade_pnl method."""

    def test_adds_to_daily_pnl(self, aggregator):
        aggregator.record_trade_pnl(50.0)
        aggregator.record_trade_pnl(30.0)
        assert aggregator.daily_pnl == 80.0

    def test_negative_pnl(self, aggregator):
        aggregator.record_trade_pnl(-100.0)
        assert aggregator.daily_pnl == -100.0


class TestUpdateSymbolExposure:
    """Test update_symbol_exposure method."""

    def test_adds_exposure(self, aggregator):
        aggregator.update_symbol_exposure("ETH", 5000.0)
        aggregator.update_symbol_exposure("ETH", 3000.0)
        assert aggregator.get_symbol_exposure("ETH") == 8000.0


class TestIncrementOpenOrders:
    """Test increment_open_orders method."""

    def test_increments(self, aggregator):
        aggregator.increment_open_orders()
        aggregator.increment_open_orders()
        assert aggregator.open_orders_count == 2


class TestDecrementOpenOrders:
    """Test decrement_open_orders method."""

    def test_decrements(self, aggregator):
        aggregator.increment_open_orders()
        aggregator.increment_open_orders()
        aggregator.decrement_open_orders()
        assert aggregator.open_orders_count == 1

    def test_does_not_go_negative(self, aggregator):
        aggregator.decrement_open_orders()
        assert aggregator.open_orders_count == 0


class TestResetDailyPnl:
    """Test reset_daily_pnl method."""

    def test_resets(self, aggregator):
        aggregator.record_trade_pnl(500.0)
        aggregator.reset_daily_pnl()
        assert aggregator.daily_pnl == 0.0


class TestAggregate:
    """Test aggregate method."""

    @pytest.mark.asyncio
    async def test_empty_positions(self, aggregator):
        snapshot = await aggregator.aggregate({})
        assert snapshot.positions == []
        assert snapshot.total_unrealized_pnl == 0.0

    @pytest.mark.asyncio
    async def test_single_venue(self, aggregator):
        positions = {
            "alpaca": [
                Position(symbol="AAPL", size=100.0, entry_price=150.0, pnl=100.0, venue="alpaca")
            ]
        }
        snapshot = await aggregator.aggregate(positions)
        
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0].symbol == "AAPL"
        assert snapshot.total_unrealized_pnl == 100.0

    @pytest.mark.asyncio
    async def test_multiple_venues_same_symbol(self, aggregator):
        positions = {
            "alpaca": [
                Position(symbol="BTC", size=0.5, entry_price=50000.0, pnl=500.0, venue="alpaca")
            ],
            "coinbase": [
                Position(symbol="BTC", size=0.5, entry_price=48000.0, pnl=1000.0, venue="coinbase")
            ]
        }
        snapshot = await aggregator.aggregate(positions)
        
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0].total_size == 1.0
        assert snapshot.total_unrealized_pnl == 1500.0

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, aggregator):
        positions = {
            "venue1": [
                Position(symbol="BTC", size=1.0, entry_price=50000.0, pnl=100.0, venue="venue1"),
                Position(symbol="ETH", size=10.0, entry_price=3000.0, pnl=50.0, venue="venue1")
            ]
        }
        snapshot = await aggregator.aggregate(positions)
        
        assert len(snapshot.positions) == 2

    @pytest.mark.asyncio
    async def test_with_price_cache(self, aggregator):
        aggregator.update_price_cache("BTC", 55000.0)
        
        positions = {
            "venue": [
                Position(symbol="BTC", size=1.0, entry_price=50000.0, pnl=5000.0, venue="venue")
            ]
        }
        snapshot = await aggregator.aggregate(positions)
        
        assert snapshot.total_notional == 55000.0


class TestUpdatePriceCache:
    """Test update_price_cache method."""

    def test_caches_price(self, aggregator):
        aggregator.update_price_cache("BTC", 50000.0)
        assert aggregator._price_cache["BTC"] == 50000.0

    def test_updates_existing(self, aggregator):
        aggregator.update_price_cache("ETH", 3000.0)
        aggregator.update_price_cache("ETH", 3200.0)
        assert aggregator._price_cache["ETH"] == 3200.0
