"""Tests for trading/agents/arbitrage_agent.py - Batch 94."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from trading.agents.arbitrage_agent import (
    ArbitrageAgent, ArbitrageOpportunity, ArbitrageExecution,
    get_arbitrage_agent
)


@pytest.fixture
def clear_execution_gate():
    """Patch execution gate to allow trading for tests."""
    with patch("core.execution_gate.check_execution_gate") as mock_gate:
        mock_status = MagicMock()
        mock_status.blocked = False
        mock_status.is_limited = False
        mock_status.safe_to_trade = True
        mock_status.gate_state = "clear"
        mock_status.reasons = []
        mock_gate.return_value = mock_status
        yield mock_gate


class TestArbitrageOpportunity:
    """Tests for ArbitrageOpportunity dataclass."""

    def test_creation(self):
        opp = ArbitrageOpportunity(
            opportunity_id="test_1",
            type="cross_venue",
            venue_a="binance",
            venue_b="coinbase",
            asset="BTC",
            price_a=50000.0,
            price_b=50100.0,
            spread_bps=20.0,
            expected_profit=100.0,
            slippage_estimate=5.0,
            gas_cost_estimate=5.0,
            net_profit=90.0,
            confidence=0.9
        )
        assert opp.opportunity_id == "test_1"
        assert opp.type == "cross_venue"

    def test_is_profitable_true(self):
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9
        )
        assert opp.is_profitable() is True

    def test_is_profitable_false(self):
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=0.0001, confidence=0.9
        )
        assert opp.is_profitable() is False

    def test_is_valid_expired(self):
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9,
            expires_at=time.time() - 10  # Expired
        )
        assert opp.is_valid() is False

    def test_is_valid_not_expired(self):
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9,
            expires_at=time.time() + 100  # Not expired
        )
        assert opp.is_valid() is True


class TestArbitrageAgent:
    """Tests for ArbitrageAgent."""

    def test_agent_initialization(self):
        agent = ArbitrageAgent()
        assert agent is not None
        assert agent.min_spread_bps == 10.0
        assert agent.total_opportunities_detected == 0

    def test_agent_custom_params(self):
        agent = ArbitrageAgent(
            min_spread_bps=20.0,
            max_slippage_bps=10.0,
            min_confidence=0.90,
            max_position_size_usd=5000.0
        )
        assert agent.min_spread_bps == 20.0
        assert agent.max_position_size_usd == 5000.0

    def test_get_performance_stats(self):
        agent = ArbitrageAgent()
        stats = agent.get_performance_stats()
        assert "total_opportunities_detected" in stats
        assert "total_executed" in stats
        assert "total_profit" in stats
        assert "win_rate" in stats

    def test_estimate_slippage(self):
        agent = ArbitrageAgent(max_position_size_usd=10000.0)
        slippage = agent._estimate_slippage("BTC", "binance", "coinbase")
        assert slippage == 5.0  # 0.05% of 10000

    def test_estimate_gas_cost_cex(self):
        agent = ArbitrageAgent()
        gas = agent._estimate_gas_cost("binance", "coinbase")
        assert gas == 5.0

    def test_estimate_gas_cost_dex(self):
        agent = ArbitrageAgent()
        gas = agent._estimate_gas_cost("uniswap_dex", "coinbase")
        assert gas == 20.0

    def test_calculate_confidence(self):
        agent = ArbitrageAgent()
        conf = agent._calculate_confidence(spread_bps=50.0, slippage=0.0)
        assert conf > 0.5
        assert conf <= 1.0

    @pytest.mark.asyncio
    async def test_scan_cross_venue_no_ccxt(self):
        agent = ArbitrageAgent(min_spread_bps=0.1)
        
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            opps = await agent.scan_cross_venue_arbitrage(
                venues=["binance", "coinbase"],
                assets=["BTC"]
            )
            # With mocked prices all same, no opportunities
            assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_scan_funding_rate_no_ccxt(self):
        agent = ArbitrageAgent(min_spread_bps=0.1)
        
        with patch('trading.agents.arbitrage_agent.get_ccxt_async', return_value=None):
            opps = await agent.scan_funding_rate_arbitrage(
                perp_venues=["binance", "bybit"],
                assets=["BTC"]
            )
            assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_execute_arbitrage_invalid(self):
        agent = ArbitrageAgent()
        
        # Create expired opportunity
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9,
            expires_at=time.time() - 10
        )
        
        result = await agent.execute_arbitrage(opp)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_arbitrage_low_confidence(self):
        agent = ArbitrageAgent(min_confidence=0.95)
        
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.5,  # Low confidence
            expires_at=time.time() + 100
        )
        
        result = await agent.execute_arbitrage(opp)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_arbitrage_manual(self, clear_execution_gate):
        agent = ArbitrageAgent(min_confidence=0.5)
        
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9,
            expires_at=time.time() + 100
        )
        
        result = await agent.execute_arbitrage(opp, auto_execute=False)
        assert result is not None
        assert result.leg_a_status == "pending"

    @pytest.mark.asyncio
    async def test_execute_arbitrage_auto(self, clear_execution_gate):
        agent = ArbitrageAgent(min_confidence=0.5)
        
        opp = ArbitrageOpportunity(
            opportunity_id="test_1", type="cross_venue", venue_a="a", venue_b="b",
            asset="BTC", price_a=100.0, price_b=101.0, spread_bps=100.0,
            expected_profit=10.0, slippage_estimate=1.0, gas_cost_estimate=1.0,
            net_profit=8.0, confidence=0.9,
            expires_at=time.time() + 100
        )
        
        result = await agent.execute_arbitrage(opp, auto_execute=True)
        assert result is not None
        assert result.leg_a_status == "filled"
        assert result.leg_b_status == "filled"
        assert agent.total_executed == 1


class TestGetArbitrageAgent:
    """Test singleton getter."""

    def test_get_arbitrage_agent(self):
        import trading.agents.arbitrage_agent as module
        module._arbitrage_agent = None
        
        agent1 = get_arbitrage_agent()
        agent2 = get_arbitrage_agent()
        
        assert agent1 is agent2
        assert isinstance(agent1, ArbitrageAgent)
