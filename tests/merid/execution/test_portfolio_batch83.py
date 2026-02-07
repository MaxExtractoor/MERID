"""Tests for merid/execution/portfolio.py - Batch 83."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.portfolio import (
    AggregatedPosition, PortfolioSnapshot, PortfolioAggregator
)
from merid.execution.base import Position


class TestAggregatedPosition:
    """Tests for AggregatedPosition dataclass."""

    def test_aggregated_position_creation(self):
        """Test AggregatedPosition creation."""
        pos = AggregatedPosition(
            symbol="BTC-USD",
            total_size=1.5,
            avg_entry_price=45000.0,
            unrealized_pnl=5000.0
        )
        assert pos.symbol == "BTC-USD"
        assert pos.total_size == 1.5
        assert pos.avg_entry_price == 45000.0
        assert pos.unrealized_pnl == 5000.0
        assert pos.venue_breakdown == {}


class TestPortfolioSnapshot:
    """Tests for PortfolioSnapshot dataclass."""

    def test_portfolio_snapshot_creation(self):
        """Test PortfolioSnapshot creation."""
        positions = [AggregatedPosition("BTC-USD", 1.0, 40000.0, 1000.0)]
        snapshot = PortfolioSnapshot(
            positions=positions,
            total_unrealized_pnl=1000.0,
            total_notional=40000.0
        )
        assert len(snapshot.positions) == 1
        assert snapshot.total_unrealized_pnl == 1000.0
        assert snapshot.total_notional == 40000.0


class TestPortfolioAggregator:
    """Tests for PortfolioAggregator."""

    @pytest.fixture
    def aggregator(self):
        return PortfolioAggregator()

    def test_init(self, aggregator):
        """Test initialization."""
        assert aggregator.daily_pnl == 0.0
        assert aggregator.open_orders_count == 0

    def test_record_trade_pnl(self, aggregator):
        """Test record_trade_pnl."""
        aggregator.record_trade_pnl(100.0)
        assert aggregator.daily_pnl == 100.0
        
        aggregator.record_trade_pnl(-50.0)
        assert aggregator.daily_pnl == 50.0

    def test_update_symbol_exposure(self, aggregator):
        """Test update_symbol_exposure."""
        aggregator.update_symbol_exposure("BTC-USD", 1000.0)
        assert aggregator.get_symbol_exposure("BTC-USD") == 1000.0
        
        aggregator.update_symbol_exposure("BTC-USD", 500.0)
        assert aggregator.get_symbol_exposure("BTC-USD") == 1500.0

    def test_increment_open_orders(self, aggregator):
        """Test increment_open_orders."""
        assert aggregator.open_orders_count == 0
        aggregator.increment_open_orders()
        assert aggregator.open_orders_count == 1
        aggregator.increment_open_orders()
        assert aggregator.open_orders_count == 2

    def test_decrement_open_orders(self, aggregator):
        """Test decrement_open_orders."""
        aggregator.increment_open_orders()
        aggregator.increment_open_orders()
        assert aggregator.open_orders_count == 2
        
        aggregator.decrement_open_orders()
        assert aggregator.open_orders_count == 1
        
        aggregator.decrement_open_orders()
        aggregator.decrement_open_orders()  # Should not go below 0
        assert aggregator.open_orders_count == 0

    def test_reset_daily_pnl(self, aggregator):
        """Test reset_daily_pnl."""
        aggregator.record_trade_pnl(100.0)
        assert aggregator.daily_pnl == 100.0
        
        aggregator.reset_daily_pnl()
        assert aggregator.daily_pnl == 0.0

    @pytest.mark.asyncio
    async def test_aggregate_empty(self, aggregator):
        """Test aggregate with empty positions."""
        result = await aggregator.aggregate({})
        assert isinstance(result, PortfolioSnapshot)
        assert result.positions == []
