"""Tests for trading agents - Batch 12 Coverage (slippage, arbitrage)."""
import pytest
from unittest.mock import MagicMock, patch
import time

from trading.agents.slippage_agent import (
    SlippageAgent,
    OrderBookSnapshot,
    ExecutionStrategy,
    get_slippage_agent
)
from trading.agents.arbitrage_agent import (
    ArbitrageAgent,
    ArbitrageOpportunity,
    ArbitrageExecution
)


class TestOrderBookSnapshot:
    """Tests for OrderBookSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating order book snapshot."""
        bids = [(45000.0, 1.0), (44900.0, 2.0)]
        asks = [(45100.0, 1.5), (45200.0, 2.5)]
        
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTCUSD",
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            mid_price=45050.0,
            spread_bps=22.2
        )
        
        assert snapshot.venue == "binance"
        assert snapshot.asset == "BTCUSD"
        assert snapshot.mid_price == 45050.0
        assert len(snapshot.bids) == 2

    def test_calculate_market_impact_buy(self):
        """Test market impact calculation for buy order."""
        bids = [(45000.0, 1.0)]
        asks = [(45100.0, 1.0), (45200.0, 2.0)]
        
        snapshot = OrderBookSnapshot(
            venue="test",
            asset="BTC",
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            mid_price=45050.0,
            spread_bps=22.2
        )
        
        # Small order that fits in first level
        impact = snapshot.calculate_market_impact(22550.0, "buy")  # 0.5 BTC at $45100
        assert impact >= 0

    def test_calculate_market_impact_insufficient_liquidity(self):
        """Test market impact with insufficient liquidity."""
        bids = [(45000.0, 0.1)]
        asks = [(45100.0, 0.1)]
        
        snapshot = OrderBookSnapshot(
            venue="test",
            asset="BTC",
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            mid_price=45050.0,
            spread_bps=22.2
        )
        
        # Large order that exceeds available liquidity
        impact = snapshot.calculate_market_impact(1000000.0, "buy")
        assert impact == float('inf')


class TestExecutionStrategy:
    """Tests for ExecutionStrategy dataclass."""

    def test_strategy_creation(self):
        """Test creating execution strategy."""
        strategy = ExecutionStrategy(
            strategy_type="twap",
            order_size=100000.0,
            num_chunks=5,
            time_interval_seconds=60.0,
            limit_price=None,
            expected_slippage_bps=5.0,
            confidence=0.85
        )
        
        assert strategy.strategy_type == "twap"
        assert strategy.num_chunks == 5
        assert strategy.expected_slippage_bps == 5.0


class TestSlippageAgent:
    """Tests for SlippageAgent."""

    @pytest.fixture
    def agent(self):
        """Create slippage agent."""
        return SlippageAgent(
            max_acceptable_slippage_bps=10.0,
            min_liquidity_ratio=0.1
        )

    def test_initialization(self, agent):
        """Test agent initialization."""
        assert agent.max_acceptable_slippage_bps == 10.0
        assert agent.min_liquidity_ratio == 0.1
        assert len(agent.slippage_history) == 0
        assert agent.avg_slippage == 0.0

    def test_analyze_order_book(self, agent):
        """Test order book analysis."""
        bids = [(45000.0, 1.0), (44900.0, 2.0)]
        asks = [(45100.0, 1.5), (45200.0, 2.5)]
        
        snapshot = agent.analyze_order_book("binance", "BTCUSD", bids, asks)
        
        assert snapshot.venue == "binance"
        assert snapshot.asset == "BTCUSD"
        assert snapshot.mid_price == 45050.0  # (45100 + 45000) / 2
        assert snapshot.spread_bps > 0

    def test_recommend_market_strategy(self, agent):
        """Test market order recommendation."""
        bids = [(45000.0, 10.0)]
        asks = [(45100.0, 10.0)]
        
        snapshot = agent.analyze_order_book("binance", "BTCUSD", bids, asks)
        
        # Use urgent urgency to force market order
        strategy = agent.recommend_execution_strategy(
            snapshot, 1000.0, "buy", urgency="urgent"
        )
        
        assert strategy.strategy_type == "market"
        assert strategy.num_chunks == 1

    def test_recommend_twap_strategy(self, agent):
        """Test TWAP recommendation for large order."""
        bids = [(45000.0, 0.1)]
        asks = [(45100.0, 0.1)]
        
        snapshot = agent.analyze_order_book("binance", "BTCUSD", bids, asks)
        
        # Large order relative to liquidity
        strategy = agent.recommend_execution_strategy(
            snapshot, 500000.0, "buy", urgency="normal"
        )
        
        assert strategy.strategy_type == "twap"
        assert strategy.num_chunks >= 5
        assert strategy.time_interval_seconds is not None

    def test_recommend_limit_strategy(self, agent):
        """Test limit order recommendation for patient urgency."""
        bids = [(45000.0, 1.0)]
        asks = [(45100.0, 1.0)]
        
        snapshot = agent.analyze_order_book("binance", "BTCUSD", bids, asks)
        
        strategy = agent.recommend_execution_strategy(
            snapshot, 10000.0, "buy", urgency="patient"
        )
        
        assert strategy.strategy_type == "limit"
        assert strategy.limit_price == snapshot.mid_price

    def test_track_execution(self, agent):
        """Test execution tracking."""
        agent.track_execution(5.0, 6.0, 10000.0)
        
        assert len(agent.slippage_history) == 1
        assert agent.slippage_history[0]["expected_slippage"] == 5.0
        assert agent.slippage_history[0]["actual_slippage"] == 6.0

    def test_get_performance_stats_empty(self, agent):
        """Test performance stats with no history."""
        stats = agent.get_performance_stats()
        
        assert stats["total_executions"] == 0
        assert stats["avg_slippage_bps"] == 0.0

    def test_get_performance_stats_with_data(self, agent):
        """Test performance stats with history."""
        agent.track_execution(5.0, 6.0, 10000.0)
        agent.track_execution(4.0, 4.5, 5000.0)
        
        stats = agent.get_performance_stats()
        
        assert stats["total_executions"] == 2
        assert stats["avg_slippage_bps"] > 0


class TestGetSlippageAgent:
    """Tests for get_slippage_agent singleton."""

    def test_singleton_creation(self):
        """Test singleton is created."""
        agent1 = get_slippage_agent()
        agent2 = get_slippage_agent()
        
        assert agent1 is agent2  # Same instance
        assert isinstance(agent1, SlippageAgent)

    def test_singleton_persistence(self):
        """Test singleton persists across calls."""
        agent = get_slippage_agent()
        agent.track_execution(1.0, 2.0, 1000.0)
        
        agent2 = get_slippage_agent()
        assert len(agent2.slippage_history) == 1


class TestArbitrageOpportunity:
    """Tests for ArbitrageOpportunity dataclass."""

    def test_opportunity_creation(self):
        """Test creating arbitrage opportunity."""
        opp = ArbitrageOpportunity(
            opportunity_id="opp_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTCUSD",
            price_a=45000.0,
            price_b=45100.0,
            spread_bps=22.2,
            expected_profit=100.0,
            slippage_estimate=10.0,
            gas_cost_estimate=5.0,
            net_profit=85.0,
            confidence=0.9
        )
        
        assert opp.opportunity_id == "opp_123"
        assert opp.type == "cross_venue"
        assert opp.net_profit == 85.0

    def test_is_profitable(self):
        """Test profitability check."""
        opp = ArbitrageOpportunity(
            opportunity_id="opp_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTCUSD",
            price_a=45000.0,
            price_b=45100.0,
            spread_bps=22.2,
            expected_profit=100.0,
            slippage_estimate=10.0,
            gas_cost_estimate=5.0,
            net_profit=0.002,  # 0.2%
            confidence=0.9
        )
        
        assert opp.is_profitable(min_profit_threshold=0.001) is True
        assert opp.is_profitable(min_profit_threshold=0.005) is False

    def test_is_valid_expired(self):
        """Test validity check for expired opportunity."""
        opp = ArbitrageOpportunity(
            opportunity_id="opp_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTCUSD",
            price_a=45000.0,
            price_b=45100.0,
            spread_bps=22.2,
            expected_profit=100.0,
            slippage_estimate=10.0,
            gas_cost_estimate=5.0,
            net_profit=85.0,
            confidence=0.9,
            expires_at=time.time() - 10  # Expired 10 seconds ago
        )
        
        assert opp.is_valid() is False


class TestArbitrageExecution:
    """Tests for ArbitrageExecution dataclass."""

    def test_execution_creation(self):
        """Test creating arbitrage execution."""
        execution = ArbitrageExecution(
            opportunity_id="opp_123",
            executed_at=time.time(),
            leg_a_status="filled",
            leg_b_status="pending",
            leg_a_fill_price=45000.0,
            leg_b_fill_price=None,
            actual_profit=None,
            execution_time_ms=150.0
        )
        
        assert execution.opportunity_id == "opp_123"
        assert execution.leg_a_status == "filled"
        assert execution.execution_time_ms == 150.0


class TestArbitrageAgent:
    """Tests for ArbitrageAgent."""

    @pytest.fixture
    def agent(self):
        """Create arbitrage agent."""
        return ArbitrageAgent()

    def test_initialization(self, agent):
        """Test agent initialization."""
        assert agent is not None
