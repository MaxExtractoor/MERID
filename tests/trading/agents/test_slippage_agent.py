"""Tests for trading/agents/slippage_agent.py - Comprehensive coverage."""
import pytest
import time
from unittest.mock import patch

from trading.agents.slippage_agent import (
    SlippageAgent, OrderBookSnapshot, ExecutionStrategy,
    get_slippage_agent
)


class TestOrderBookSnapshot:
    """Tests for OrderBookSnapshot dataclass."""

    def test_creation(self):
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        assert snapshot.venue == "binance"
        assert snapshot.asset == "BTC"
        assert snapshot.mid_price == 50005.0

    def test_calculate_market_impact_buy(self):
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        # Small order should have low impact
        impact = snapshot.calculate_market_impact(1000.0, "buy")
        assert impact >= 0

    def test_calculate_market_impact_sell(self):
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        impact = snapshot.calculate_market_impact(1000.0, "sell")
        assert impact >= 0

    def test_calculate_market_impact_insufficient_liquidity(self):
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 0.01)],  # Very small liquidity
            asks=[(50010.0, 0.01)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        # Large order with insufficient liquidity
        impact = snapshot.calculate_market_impact(1000000.0, "buy")
        assert impact == float('inf')


class TestExecutionStrategy:
    """Tests for ExecutionStrategy dataclass."""

    def test_creation(self):
        strategy = ExecutionStrategy(
            strategy_type="market",
            order_size=10000.0,
            num_chunks=1,
            time_interval_seconds=None,
            limit_price=None,
            expected_slippage_bps=5.0,
            confidence=0.95
        )
        assert strategy.strategy_type == "market"
        assert strategy.order_size == 10000.0
        assert strategy.confidence == 0.95


class TestSlippageAgent:
    """Tests for SlippageAgent."""

    def test_initialization(self):
        agent = SlippageAgent()
        assert agent.max_acceptable_slippage_bps == 10.0
        assert agent.min_liquidity_ratio == 0.1

    def test_initialization_custom(self):
        agent = SlippageAgent(
            max_acceptable_slippage_bps=20.0,
            min_liquidity_ratio=0.2
        )
        assert agent.max_acceptable_slippage_bps == 20.0
        assert agent.min_liquidity_ratio == 0.2

    def test_analyze_order_book(self):
        agent = SlippageAgent()
        bids = [(50000.0, 1.0), (49990.0, 2.0)]
        asks = [(50010.0, 1.0), (50020.0, 2.0)]
        
        snapshot = agent.analyze_order_book("binance", "BTC", bids, asks)
        
        assert snapshot.venue == "binance"
        assert snapshot.asset == "BTC"
        assert snapshot.mid_price == 50005.0
        assert snapshot.spread_bps > 0

    def test_recommend_strategy_market_urgent(self):
        agent = SlippageAgent()
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 10.0), (49990.0, 20.0)],
            asks=[(50010.0, 10.0), (50020.0, 20.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        
        strategy = agent.recommend_execution_strategy(
            snapshot, order_size_usd=1000.0, side="buy", urgency="urgent"
        )
        
        assert strategy.strategy_type == "market"
        assert strategy.num_chunks == 1

    def test_recommend_strategy_market_low_impact(self):
        agent = SlippageAgent(max_acceptable_slippage_bps=100.0)  # High threshold
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 10.0), (49990.0, 20.0)],
            asks=[(50010.0, 10.0), (50020.0, 20.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        
        strategy = agent.recommend_execution_strategy(
            snapshot, order_size_usd=1000.0, side="buy", urgency="normal"
        )
        
        # With high threshold, should be market or iceberg depending on liquidity
        assert strategy.strategy_type in ("market", "iceberg")

    def test_recommend_strategy_twap_large_order(self):
        agent = SlippageAgent(max_acceptable_slippage_bps=0.1)  # Low threshold
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 0.1), (49990.0, 0.1)],  # Low liquidity
            asks=[(50010.0, 0.1), (50020.0, 0.1)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        
        strategy = agent.recommend_execution_strategy(
            snapshot, order_size_usd=100000.0, side="buy", urgency="normal"
        )
        
        assert strategy.strategy_type == "twap"
        assert strategy.num_chunks >= 5

    def test_recommend_strategy_limit_patient(self):
        agent = SlippageAgent(max_acceptable_slippage_bps=0.1)  # Low threshold
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        
        strategy = agent.recommend_execution_strategy(
            snapshot, order_size_usd=10000.0, side="buy", urgency="patient"
        )
        
        assert strategy.strategy_type == "limit"
        assert strategy.limit_price == 50005.0

    def test_recommend_strategy_iceberg_default(self):
        agent = SlippageAgent(max_acceptable_slippage_bps=0.1)  # Low threshold
        snapshot = OrderBookSnapshot(
            venue="binance",
            asset="BTC",
            timestamp=time.time(),
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            mid_price=50005.0,
            spread_bps=2.0
        )
        
        strategy = agent.recommend_execution_strategy(
            snapshot, order_size_usd=10000.0, side="buy", urgency="normal"
        )
        
        assert strategy.strategy_type == "iceberg"
        assert strategy.num_chunks == 3

    def test_track_execution(self):
        agent = SlippageAgent()
        
        agent.track_execution(
            expected_slippage=5.0,
            actual_slippage=6.0,
            order_size=10000.0
        )
        
        assert len(agent.slippage_history) == 1
        assert agent.avg_slippage == 6.0

    def test_track_multiple_executions(self):
        agent = SlippageAgent()
        
        agent.track_execution(5.0, 6.0, 10000.0)
        agent.track_execution(4.0, 5.0, 5000.0)
        agent.track_execution(3.0, 4.0, 8000.0)
        
        assert len(agent.slippage_history) == 3
        assert agent.avg_slippage == 5.0  # (6+5+4)/3

    def test_get_performance_stats_empty(self):
        agent = SlippageAgent()
        
        stats = agent.get_performance_stats()
        
        assert stats["total_executions"] == 0
        assert stats["avg_slippage_bps"] == 0.0

    def test_get_performance_stats_with_history(self):
        agent = SlippageAgent()
        
        agent.track_execution(5.0, 6.0, 10000.0)
        agent.track_execution(4.0, 8.0, 5000.0)
        agent.track_execution(3.0, 4.0, 8000.0)
        
        stats = agent.get_performance_stats()
        
        assert stats["total_executions"] == 3
        assert stats["avg_slippage_bps"] == 6.0  # (6+8+4)/3
        assert stats["max_slippage_bps"] == 8.0
        assert stats["min_slippage_bps"] == 4.0


class TestGetSlippageAgent:
    """Test singleton getter."""

    def test_get_slippage_agent(self):
        import trading.agents.slippage_agent as module
        module._slippage_agent = None
        
        agent1 = get_slippage_agent()
        agent2 = get_slippage_agent()
        
        assert agent1 is agent2
        assert isinstance(agent1, SlippageAgent)
