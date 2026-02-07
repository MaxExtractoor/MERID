"""Tests for trading agents arbitrage_agent module - Batch 35 Coverage."""
import pytest
from unittest.mock import patch, AsyncMock
import time

from trading.agents.arbitrage_agent import (
    ArbitrageOpportunity,
    ArbitrageExecution,
    ArbitrageAgent,
    get_arbitrage_agent,
    VENUE_FALLBACKS,
)


class TestVenueFallbacks:
    """Tests for venue fallbacks constant."""

    def test_venue_fallbacks_structure(self):
        assert "binance" in VENUE_FALLBACKS
        assert VENUE_FALLBACKS["binance"] == "binanceus"


class TestArbitrageOpportunity:
    """Tests for ArbitrageOpportunity dataclass."""

    @pytest.fixture
    def sample_opportunity(self):
        return ArbitrageOpportunity(
            opportunity_id="arb_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50100.0,
            spread_bps=20.0,
            expected_profit=10.0,
            slippage_estimate=2.0,
            gas_cost_estimate=5.0,
            net_profit=3.0,
            confidence=0.9,
        )

    def test_opportunity_creation(self, sample_opportunity):
        assert sample_opportunity.opportunity_id == "arb_123"
        assert sample_opportunity.type == "cross_venue"
        assert sample_opportunity.venue_a == "binance"
        assert sample_opportunity.venue_b == "coinbase"
        assert sample_opportunity.asset == "BTC"
        assert sample_opportunity.spread_bps == 20.0
        assert sample_opportunity.net_profit == 3.0

    def test_is_profitable_true(self, sample_opportunity):
        assert sample_opportunity.is_profitable(min_profit_threshold=0.001) is True

    def test_is_profitable_false(self, sample_opportunity):
        sample_opportunity.net_profit = 0.0001
        assert sample_opportunity.is_profitable(min_profit_threshold=0.001) is False

    def test_is_valid_profitable(self, sample_opportunity):
        assert sample_opportunity.is_valid() is True

    def test_is_valid_expired(self, sample_opportunity):
        sample_opportunity.expires_at = time.time() - 1  # Already expired
        assert sample_opportunity.is_valid() is False

    def test_is_valid_not_profitable(self, sample_opportunity):
        sample_opportunity.net_profit = -1.0
        assert sample_opportunity.is_valid() is False

    def test_default_timestamps(self, sample_opportunity):
        assert sample_opportunity.detected_at > 0


class TestArbitrageExecution:
    """Tests for ArbitrageExecution dataclass."""

    def test_execution_creation(self):
        execution = ArbitrageExecution(
            opportunity_id="arb_123",
            executed_at=time.time(),
            leg_a_status="pending",
            leg_b_status="pending",
        )
        assert execution.opportunity_id == "arb_123"
        assert execution.leg_a_status == "pending"
        assert execution.leg_b_status == "pending"
        assert execution.leg_a_fill_price is None
        assert execution.leg_b_fill_price is None
        assert execution.actual_profit is None

    def test_execution_with_fill_prices(self):
        execution = ArbitrageExecution(
            opportunity_id="arb_123",
            executed_at=time.time(),
            leg_a_status="filled",
            leg_b_status="filled",
            leg_a_fill_price=50000.0,
            leg_b_fill_price=50100.0,
            actual_profit=10.0,
            execution_time_ms=150.0,
        )
        assert execution.leg_a_fill_price == 50000.0
        assert execution.leg_b_fill_price == 50100.0
        assert execution.actual_profit == 10.0
        assert execution.execution_time_ms == 150.0


class TestArbitrageAgent:
    """Tests for ArbitrageAgent class."""

    @pytest.fixture
    def agent(self):
        return ArbitrageAgent(
            min_spread_bps=10.0,
            max_slippage_bps=5.0,
            min_confidence=0.85,
            max_position_size_usd=10000.0,
        )

    def test_initialization(self, agent):
        assert agent.min_spread_bps == 10.0
        assert agent.max_slippage_bps == 5.0
        assert agent.min_confidence == 0.85
        assert agent.max_position_size_usd == 10000.0
        assert agent.total_opportunities_detected == 0
        assert agent.total_executed == 0
        assert agent.total_profit == 0.0
        assert agent.win_rate == 0.0
        assert agent.active_opportunities == {}
        assert agent.execution_history == []

    def test_get_performance_stats_empty(self, agent):
        stats = agent.get_performance_stats()
        assert stats["total_opportunities_detected"] == 0
        assert stats["total_executed"] == 0
        assert stats["total_profit"] == 0.0
        assert stats["win_rate"] == 0.0
        assert stats["avg_profit_per_trade"] == 0.0
        assert stats["execution_history_count"] == 0

    def test_get_performance_stats_with_data(self, agent):
        agent.total_opportunities_detected = 10
        agent.total_executed = 5
        agent.total_profit = 500.0
        agent.win_rate = 0.8
        agent.execution_history = [ArbitrageExecution(
            opportunity_id="arb_1",
            executed_at=time.time(),
            leg_a_status="filled",
            leg_b_status="filled",
        )]
        
        stats = agent.get_performance_stats()
        assert stats["total_opportunities_detected"] == 10
        assert stats["total_executed"] == 5
        assert stats["total_profit"] == 500.0
        assert stats["win_rate"] == 0.8
        assert stats["avg_profit_per_trade"] == 100.0
        assert stats["execution_history_count"] == 1

    def test_estimate_slippage(self, agent):
        slippage = agent._estimate_slippage("BTC", "binance", "coinbase")
        assert slippage == 5.0  # 0.05% of 10000

    def test_estimate_gas_cost_cex(self, agent):
        gas = agent._estimate_gas_cost("binance", "coinbase")
        assert gas == 5.0

    def test_estimate_gas_cost_dex(self, agent):
        gas = agent._estimate_gas_cost("binance_dex", "coinbase")
        assert gas == 20.0

    def test_calculate_confidence_high_spread(self, agent):
        confidence = agent._calculate_confidence(spread_bps=50.0, slippage=5.0)
        assert confidence > 0.7  # High spread score

    def test_calculate_confidence_low_spread(self, agent):
        confidence = agent._calculate_confidence(spread_bps=5.0, slippage=5.0)
        assert confidence < 0.7  # Lower spread score

    @pytest.mark.asyncio
    async def test_execute_arbitrage_not_valid(self, agent):
        opp = ArbitrageOpportunity(
            opportunity_id="arb_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50000.0,
            spread_bps=0.0,
            expected_profit=0.0,
            slippage_estimate=0.0,
            gas_cost_estimate=0.0,
            net_profit=-1.0,  # Not profitable
            confidence=0.9,
        )
        result = await agent.execute_arbitrage(opp)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_arbitrage_low_confidence(self, agent):
        opp = ArbitrageOpportunity(
            opportunity_id="arb_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50100.0,
            spread_bps=20.0,
            expected_profit=10.0,
            slippage_estimate=2.0,
            gas_cost_estimate=5.0,
            net_profit=3.0,
            confidence=0.5,  # Below min_confidence of 0.85
        )
        result = await agent.execute_arbitrage(opp)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_arbitrage_manual(self, agent):
        opp = ArbitrageOpportunity(
            opportunity_id="arb_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50100.0,
            spread_bps=20.0,
            expected_profit=10.0,
            slippage_estimate=2.0,
            gas_cost_estimate=5.0,
            net_profit=3.0,
            confidence=0.9,
        )
        result = await agent.execute_arbitrage(opp, auto_execute=False)
        assert result is not None
        assert result.opportunity_id == "arb_123"
        assert result.leg_a_status == "pending"

    @pytest.mark.asyncio
    async def test_execute_arbitrage_auto(self, agent):
        opp = ArbitrageOpportunity(
            opportunity_id="arb_123",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50100.0,
            spread_bps=20.0,
            expected_profit=10.0,
            slippage_estimate=2.0,
            gas_cost_estimate=5.0,
            net_profit=3.0,
            confidence=0.9,
        )
        result = await agent.execute_arbitrage(opp, auto_execute=True)
        assert result is not None
        assert result.leg_a_status == "filled"
        assert result.leg_b_status == "filled"
        assert result.actual_profit == 3.0
        assert agent.total_executed == 1
        assert agent.total_profit == 3.0

    @pytest.mark.asyncio
    async def test_scan_cross_venue_arbitrage_no_ccxt(self, agent):
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            opportunities = await agent.scan_cross_venue_arbitrage(
                venues=["binance", "coinbase"],
                assets=["BTC"]
            )
            # Should return empty list when prices are identical
            assert opportunities == []

    @pytest.mark.asyncio
    async def test_scan_funding_rate_arbitrage_no_ccxt(self, agent):
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            opportunities = await agent.scan_funding_rate_arbitrage(
                perp_venues=["binance", "bybit"],
                assets=["BTC"]
            )
            # Should return empty list when rates are identical
            assert opportunities == []

    @pytest.mark.asyncio
    async def test_fetch_prices_across_venues_no_ccxt(self, agent):
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            prices = await agent._fetch_prices_across_venues("BTC", ["binance", "coinbase"])
            # Should return cached prices when CCXT unavailable
            assert "binance" in prices
            assert "coinbase" in prices
            assert prices["binance"] == 100.0

    @pytest.mark.asyncio
    async def test_fetch_funding_rates_no_ccxt(self, agent):
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            rates = await agent._fetch_funding_rates("BTC", ["binance", "bybit"])
            # Should return default rates when CCXT unavailable
            assert "binance" in rates
            assert "bybit" in rates
            assert rates["binance"] == 0.0001


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_arbitrage_agent(self):
        # Reset singleton
        import trading.agents.arbitrage_agent as arb_agent_module
        arb_agent_module._arbitrage_agent = None

        agent1 = get_arbitrage_agent()
        agent2 = get_arbitrage_agent()
        assert agent1 is agent2
