"""Comprehensive tests for merid/execution/portfolio.py."""

import pytest
from dataclasses import asdict

from merid.execution.portfolio import (
    AggregatedPosition,
    PortfolioSnapshot,
    PortfolioAggregator,
)
from merid.execution.base import Position


class TestAggregatedPosition:
    """Test AggregatedPosition dataclass."""

    def test_default_creation(self):
        """Test default AggregatedPosition creation."""
        pos = AggregatedPosition(
            symbol="AAPL",
            total_size=100.0,
            avg_entry_price=150.0,
            unrealized_pnl=500.0
        )
        assert pos.symbol == "AAPL"
        assert pos.total_size == 100.0
        assert pos.avg_entry_price == 150.0
        assert pos.unrealized_pnl == 500.0
        assert pos.venue_breakdown == {}

    def test_with_venue_breakdown(self):
        """Test AggregatedPosition with venue breakdown."""
        pos = AggregatedPosition(
            symbol="BTC",
            total_size=1.5,
            avg_entry_price=45000.0,
            unrealized_pnl=1500.0,
            venue_breakdown={"coinbase": 1.0, "binance": 0.5}
        )
        assert pos.venue_breakdown == {"coinbase": 1.0, "binance": 0.5}

    def test_slots_behavior(self):
        """Test that AggregatedPosition uses slots."""
        pos = AggregatedPosition("AAPL", 100.0, 150.0, 500.0)
        # Slots should prevent adding new attributes
        with pytest.raises(AttributeError):
            pos.new_field = "test"


class TestPortfolioSnapshot:
    """Test PortfolioSnapshot dataclass."""

    def test_default_creation(self):
        """Test default PortfolioSnapshot creation."""
        positions = [
            AggregatedPosition("AAPL", 100.0, 150.0, 500.0),
            AggregatedPosition("TSLA", 50.0, 200.0, -200.0),
        ]
        snapshot = PortfolioSnapshot(
            positions=positions,
            total_unrealized_pnl=300.0,
            total_notional=25000.0
        )
        assert len(snapshot.positions) == 2
        assert snapshot.total_unrealized_pnl == 300.0
        assert snapshot.total_notional == 25000.0
        assert snapshot.metadata == {}

    def test_with_metadata(self):
        """Test PortfolioSnapshot with metadata."""
        snapshot = PortfolioSnapshot(
            positions=[],
            total_unrealized_pnl=0.0,
            total_notional=0.0,
            metadata={"venues": ["coinbase", "binance"], "timestamp": "2024-01-01"}
        )
        assert snapshot.metadata["venues"] == ["coinbase", "binance"]


class TestPortfolioAggregatorInitialization:
    """Test PortfolioAggregator initialization."""

    def test_default_initialization(self):
        """Test default PortfolioAggregator initialization."""
        aggregator = PortfolioAggregator()
        assert aggregator._price_cache == {}
        assert aggregator._daily_pnl == 0.0
        assert aggregator._symbol_exposure == {}
        assert aggregator._open_orders_count == 0


class TestPortfolioAggregatorProperties:
    """Test PortfolioAggregator properties."""

    def test_daily_pnl_property(self):
        """Test daily_pnl property."""
        aggregator = PortfolioAggregator()
        assert aggregator.daily_pnl == 0.0
        
        aggregator._daily_pnl = 1000.0
        assert aggregator.daily_pnl == 1000.0

    def test_open_orders_count_property(self):
        """Test open_orders_count property."""
        aggregator = PortfolioAggregator()
        assert aggregator.open_orders_count == 0
        
        aggregator._open_orders_count = 5
        assert aggregator.open_orders_count == 5


class TestPortfolioAggregatorSymbolExposure:
    """Test symbol exposure methods."""

    def test_get_symbol_exposure_existing(self):
        """Test getting exposure for existing symbol."""
        aggregator = PortfolioAggregator()
        aggregator._symbol_exposure["AAPL"] = 15000.0
        
        assert aggregator.get_symbol_exposure("AAPL") == 15000.0

    def test_get_symbol_exposure_nonexistent(self):
        """Test getting exposure for non-existent symbol."""
        aggregator = PortfolioAggregator()
        
        assert aggregator.get_symbol_exposure("UNKNOWN") == 0.0

    def test_update_symbol_exposure_new(self):
        """Test updating exposure for new symbol."""
        aggregator = PortfolioAggregator()
        
        aggregator.update_symbol_exposure("AAPL", 10000.0)
        
        assert aggregator._symbol_exposure["AAPL"] == 10000.0

    def test_update_symbol_exposure_existing(self):
        """Test updating exposure for existing symbol."""
        aggregator = PortfolioAggregator()
        aggregator._symbol_exposure["AAPL"] = 5000.0
        
        aggregator.update_symbol_exposure("AAPL", 3000.0)
        
        assert aggregator._symbol_exposure["AAPL"] == 8000.0

    def test_update_symbol_exposure_multiple_symbols(self):
        """Test updating exposure for multiple symbols."""
        aggregator = PortfolioAggregator()
        
        aggregator.update_symbol_exposure("AAPL", 10000.0)
        aggregator.update_symbol_exposure("TSLA", 5000.0)
        aggregator.update_symbol_exposure("AAPL", 2000.0)
        
        assert aggregator._symbol_exposure["AAPL"] == 12000.0
        assert aggregator._symbol_exposure["TSLA"] == 5000.0


class TestPortfolioAggregatorPnlTracking:
    """Test P&L tracking methods."""

    def test_record_trade_pnl_single(self):
        """Test recording single trade P&L."""
        aggregator = PortfolioAggregator()
        
        aggregator.record_trade_pnl(500.0)
        
        assert aggregator._daily_pnl == 500.0

    def test_record_trade_pnl_multiple(self):
        """Test recording multiple trade P&Ls."""
        aggregator = PortfolioAggregator()
        
        aggregator.record_trade_pnl(500.0)
        aggregator.record_trade_pnl(-200.0)
        aggregator.record_trade_pnl(300.0)
        
        assert aggregator._daily_pnl == 600.0

    def test_record_trade_pnl_negative(self):
        """Test recording negative P&L (loss)."""
        aggregator = PortfolioAggregator()
        
        aggregator.record_trade_pnl(-1000.0)
        
        assert aggregator._daily_pnl == -1000.0

    def test_reset_daily_pnl(self):
        """Test resetting daily P&L."""
        aggregator = PortfolioAggregator()
        aggregator._daily_pnl = 5000.0
        
        aggregator.reset_daily_pnl()
        
        assert aggregator._daily_pnl == 0.0

    def test_reset_daily_pnl_already_zero(self):
        """Test resetting daily P&L when already zero."""
        aggregator = PortfolioAggregator()
        
        aggregator.reset_daily_pnl()
        
        assert aggregator._daily_pnl == 0.0


class TestPortfolioAggregatorOpenOrders:
    """Test open orders counting methods."""

    def test_increment_open_orders(self):
        """Test incrementing open orders."""
        aggregator = PortfolioAggregator()
        
        aggregator.increment_open_orders()
        assert aggregator._open_orders_count == 1
        
        aggregator.increment_open_orders()
        assert aggregator._open_orders_count == 2

    def test_decrement_open_orders(self):
        """Test decrementing open orders."""
        aggregator = PortfolioAggregator()
        aggregator._open_orders_count = 3
        
        aggregator.decrement_open_orders()
        assert aggregator._open_orders_count == 2

    def test_decrement_open_orders_not_below_zero(self):
        """Test decrementing doesn't go below zero."""
        aggregator = PortfolioAggregator()
        
        aggregator.decrement_open_orders()
        assert aggregator._open_orders_count == 0
        
        aggregator.decrement_open_orders()
        assert aggregator._open_orders_count == 0

    def test_increment_decrement_sequence(self):
        """Test sequence of increment and decrement operations."""
        aggregator = PortfolioAggregator()
        
        aggregator.increment_open_orders()
        aggregator.increment_open_orders()
        aggregator.increment_open_orders()
        assert aggregator._open_orders_count == 3
        
        aggregator.decrement_open_orders()
        assert aggregator._open_orders_count == 2
        
        aggregator.increment_open_orders()
        assert aggregator._open_orders_count == 3


class TestPortfolioAggregatorPriceCache:
    """Test price cache methods."""

    def test_update_price_cache_single(self):
        """Test updating price cache for single symbol."""
        aggregator = PortfolioAggregator()
        
        aggregator.update_price_cache("AAPL", 150.0)
        
        assert aggregator._price_cache["AAPL"] == 150.0

    def test_update_price_cache_multiple(self):
        """Test updating price cache for multiple symbols."""
        aggregator = PortfolioAggregator()
        
        aggregator.update_price_cache("AAPL", 150.0)
        aggregator.update_price_cache("TSLA", 200.0)
        aggregator.update_price_cache("BTC", 45000.0)
        
        assert aggregator._price_cache["AAPL"] == 150.0
        assert aggregator._price_cache["TSLA"] == 200.0
        assert aggregator._price_cache["BTC"] == 45000.0

    def test_update_price_cache_update_existing(self):
        """Test updating price cache for existing symbol."""
        aggregator = PortfolioAggregator()
        aggregator._price_cache["AAPL"] = 140.0
        
        aggregator.update_price_cache("AAPL", 155.0)
        
        assert aggregator._price_cache["AAPL"] == 155.0


class TestPortfolioAggregatorAggregate:
    """Test the aggregate method."""

    @pytest.mark.asyncio
    async def test_aggregate_empty_positions(self):
        """Test aggregation with empty positions."""
        aggregator = PortfolioAggregator()
        
        snapshot = await aggregator.aggregate({})
        
        assert snapshot.positions == []
        assert snapshot.total_unrealized_pnl == 0.0
        assert snapshot.total_notional == 0.0
        assert snapshot.metadata["venues"] == []

    @pytest.mark.asyncio
    async def test_aggregate_single_venue_single_position(self):
        """Test aggregation with single venue and single position."""
        aggregator = PortfolioAggregator()
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 1.0, 45000.0, 500.0, "coinbase")
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        assert len(snapshot.positions) == 1
        pos = snapshot.positions[0]
        assert pos.symbol == "BTC"
        assert pos.total_size == 1.0
        assert pos.avg_entry_price == 45000.0
        assert pos.unrealized_pnl == 500.0
        assert pos.venue_breakdown == {"coinbase": 1.0}
        assert snapshot.total_unrealized_pnl == 500.0

    @pytest.mark.asyncio
    async def test_aggregate_single_venue_multiple_positions(self):
        """Test aggregation with single venue and multiple positions."""
        aggregator = PortfolioAggregator()
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 1.0, 45000.0, 500.0, "coinbase"),
                Position("ETH", 10.0, 3000.0, -200.0, "coinbase"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        assert len(snapshot.positions) == 2
        symbols = {p.symbol for p in snapshot.positions}
        assert symbols == {"BTC", "ETH"}
        assert snapshot.total_unrealized_pnl == 300.0

    @pytest.mark.asyncio
    async def test_aggregate_multiple_venues_same_symbol(self):
        """Test aggregation with multiple venues holding same symbol."""
        aggregator = PortfolioAggregator()
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 1.0, 40000.0, 1000.0, "coinbase"),
            ],
            "binance": [
                Position("BTC", 0.5, 42000.0, 500.0, "binance"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        assert len(snapshot.positions) == 1
        pos = snapshot.positions[0]
        assert pos.symbol == "BTC"
        assert pos.total_size == 1.5
        assert pos.unrealized_pnl == 1500.0
        assert pos.venue_breakdown == {"coinbase": 1.0, "binance": 0.5}
        # Weighted average: (40000 * 1 + 42000 * 0.5) / 1.5 = 40666.67
        assert abs(pos.avg_entry_price - 40666.67) < 0.01

    @pytest.mark.asyncio
    async def test_aggregate_multiple_venues_different_symbols(self):
        """Test aggregation with multiple venues and different symbols."""
        aggregator = PortfolioAggregator()
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 1.0, 45000.0, 500.0, "coinbase"),
            ],
            "binance": [
                Position("ETH", 10.0, 3000.0, -100.0, "binance"),
            ],
            "kraken": [
                Position("SOL", 100.0, 100.0, 200.0, "kraken"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        assert len(snapshot.positions) == 3
        assert snapshot.total_unrealized_pnl == 600.0
        assert set(snapshot.metadata["venues"]) == {"coinbase", "binance", "kraken"}

    @pytest.mark.asyncio
    async def test_aggregate_with_price_cache(self):
        """Test aggregation using price cache for notional calculation."""
        aggregator = PortfolioAggregator()
        aggregator._price_cache["BTC"] = 50000.0
        aggregator._price_cache["ETH"] = 3500.0
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 2.0, 45000.0, 10000.0, "coinbase"),
                Position("ETH", 5.0, 3000.0, 2500.0, "coinbase"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        # Notional = 2 * 50000 + 5 * 3500 = 100000 + 17500 = 117500
        assert snapshot.total_notional == 117500.0

    @pytest.mark.asyncio
    async def test_aggregate_missing_price_in_cache(self):
        """Test aggregation when price is missing from cache."""
        aggregator = PortfolioAggregator()
        # No price cache set
        
        venue_positions = {
            "coinbase": [
                Position("BTC", 1.0, 45000.0, 500.0, "coinbase"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        # Notional should be 1.0 * 0 = 0 (price not in cache)
        assert snapshot.total_notional == 0.0

    @pytest.mark.asyncio
    async def test_aggregate_complex_scenario(self):
        """Test complex aggregation scenario."""
        aggregator = PortfolioAggregator()
        aggregator._price_cache["AAPL"] = 160.0
        aggregator._price_cache["TSLA"] = 220.0
        
        venue_positions = {
            "alpaca": [
                Position("AAPL", 100.0, 150.0, 1000.0, "alpaca"),
                Position("TSLA", 50.0, 200.0, 1000.0, "alpaca"),
            ],
            "webull": [
                Position("AAPL", 50.0, 155.0, 250.0, "webull"),
            ]
        }
        
        snapshot = await aggregator.aggregate(venue_positions)
        
        assert len(snapshot.positions) == 2
        
        # AAPL aggregated
        aapl_pos = next(p for p in snapshot.positions if p.symbol == "AAPL")
        assert aapl_pos.total_size == 150.0
        assert aapl_pos.unrealized_pnl == 1250.0
        assert aapl_pos.venue_breakdown == {"alpaca": 100.0, "webull": 50.0}
        
        # TSLA (only in alpaca)
        tsla_pos = next(p for p in snapshot.positions if p.symbol == "TSLA")
        assert tsla_pos.total_size == 50.0
        assert tsla_pos.venue_breakdown == {"alpaca": 50.0}
        
        # Totals
        assert snapshot.total_unrealized_pnl == 2250.0
        # Notional: 150 * 160 + 50 * 220 = 24000 + 11000 = 35000
        assert snapshot.total_notional == 35000.0
