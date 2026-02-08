"""
Integration tests for full trade flow.

Tests the complete end-to-end flow from trade signal to execution:
1. Agent generates trade signal
2. Risk guard reviews trade plan
3. Order is placed with paper trading engine
4. Position is tracked
5. P&L is calculated
6. Position is closed
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch

from risk.risk_guard import (
    RiskGuard,
    TradePlanInput,
    RiskDecision,
    PortfolioState,
)
from trading.paper_trading import (
    PaperTradingEngine,
    PaperOrderStatus,
)


@pytest.fixture
def reset_singletons():
    """Reset singleton instances for clean tests."""
    RiskGuard._instance = None
    # Note: PaperTradingEngine uses a global variable, reset if needed
    yield
    RiskGuard._instance = None


@pytest.fixture
def risk_guard(reset_singletons):
    """Create a configured risk guard."""
    guard = RiskGuard()
    guard.add_symbol("BTC", max_position_usd=10000.0)
    guard.add_symbol("ETH", max_position_usd=5000.0)
    guard.add_venue("binance")
    guard.add_venue("paper")
    return guard


@pytest.fixture
def paper_engine():
    """Create a paper trading engine."""
    with patch('data.live_price_feed.get_live_price_feed'):
        engine = PaperTradingEngine(starting_balance=10000.0)
        # Set initial prices
        engine.current_prices = {
            "BTC": 50000.0,
            "BTC/USDT": 50000.0,
            "ETH": 3000.0,
            "ETH/USDT": 3000.0,
        }
        return engine


class TestBasicTradeFlow:
    """Test basic trade flow from signal to execution."""
    
    @pytest.mark.asyncio
    async def test_successful_trade_flow(self, risk_guard, paper_engine):
        """Test a successful end-to-end trade flow."""
        # Step 1: Create trade plan
        plan = TradePlanInput(
            plan_id="test_trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="test_agent",
        )
        
        # Step 2: Risk review
        result = await risk_guard.review_plan(plan)
        
        assert result.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
        approved_size = result.approved_size_usd
        assert approved_size > 0
        
        # Step 3: Execute order
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=approved_size,
            order_type="market",
        )
        
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price > 0
        
        # Step 4: Verify position created
        portfolio = paper_engine.get_portfolio("test_user")
        assert len(portfolio.positions) == 1
        
        position_key = "BTC_long_perp"
        assert position_key in portfolio.positions
        position = portfolio.positions[position_key]
        assert position.size_usd == approved_size
        
        # Step 5: Update price and check P&L
        new_price = 51000.0  # 2% gain
        paper_engine.update_prices({"BTC": new_price, "BTC/USDT": new_price})
        
        # Step 6: Close position
        pnl = paper_engine.close_position("test_user", position_key)
        
        assert pnl is not None
        assert pnl > 0  # Should be profitable
        assert position_key not in portfolio.positions
    
    @pytest.mark.asyncio
    async def test_rejected_trade_flow(self, risk_guard, paper_engine):
        """Test trade flow with risk rejection."""
        # Create a trade plan that will be rejected (low confidence)
        plan = TradePlanInput(
            plan_id="test_trade_002",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.3,  # Below minimum
            agent_id="test_agent",
        )
        
        # Risk review should reject
        result = await risk_guard.review_plan(plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "LOW_CONFIDENCE" in result.limit_breaches
        
        # Order should not be placed
        portfolio = paper_engine.get_portfolio("test_user")
        initial_balance = portfolio.current_balance
        
        # Verify no position created
        assert len(portfolio.positions) == 0
        assert portfolio.current_balance == initial_balance


class TestMultipleTradesFlow:
    """Test flow with multiple trades."""
    
    @pytest.mark.asyncio
    async def test_multiple_sequential_trades(self, risk_guard, paper_engine):
        """Test multiple trades in sequence."""
        user_id = "test_user"
        
        # Trade 1: BTC long
        plan1 = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result1 = await risk_guard.review_plan(plan1)
        assert result1.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
        
        order1 = paper_engine.place_order(
            user_id=user_id,
            asset="BTC",
            side="long",
            size_usd=result1.approved_size_usd,
            order_type="market",
        )
        assert order1.status == PaperOrderStatus.FILLED
        
        # Update risk guard with trade
        risk_guard.record_trade("BTC", result1.approved_size_usd)
        
        # Trade 2: ETH long (after time delay)
        await asyncio.sleep(0.1)  # Small delay
        risk_guard.portfolio.last_trade_time = time.time() - 61  # Simulate 61 seconds
        
        plan2 = TradePlanInput(
            plan_id="trade_002",
            symbol="ETH",
            venue="paper",
            direction="long",
            target_size_usd=500.0,
            confidence=0.70,
            agent_id="agent_2",
        )
        
        result2 = await risk_guard.review_plan(plan2)
        assert result2.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
        
        order2 = paper_engine.place_order(
            user_id=user_id,
            asset="ETH",
            side="long",
            size_usd=result2.approved_size_usd,
            order_type="market",
        )
        assert order2.status == PaperOrderStatus.FILLED
        
        # Verify both positions exist
        portfolio = paper_engine.get_portfolio(user_id)
        assert len(portfolio.positions) == 2
        assert "BTC_long_perp" in portfolio.positions
        assert "ETH_long_perp" in portfolio.positions


class TestRiskLimitEnforcement:
    """Test risk limits are enforced in trade flow."""
    
    @pytest.mark.asyncio
    async def test_position_limit_enforcement(self, risk_guard, paper_engine):
        """Test that position limits are enforced."""
        user_id = "test_user"
        
        # Set a lower position limit for BTC
        risk_guard.universe.symbol_limits["BTC"] = 2000.0
        
        # Trade 1: 1500 USD
        plan1 = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1500.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result1 = await risk_guard.review_plan(plan1)
        assert result1.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
        
        order1 = paper_engine.place_order(
            user_id=user_id,
            asset="BTC",
            side="long",
            size_usd=result1.approved_size_usd,
            order_type="market",
        )
        
        # Update risk guard
        risk_guard.portfolio.positions["BTC"] = result1.approved_size_usd
        risk_guard.portfolio.last_trade_time = time.time() - 61
        
        # Trade 2: Try to add 1000 more (would exceed 2000 limit)
        plan2 = TradePlanInput(
            plan_id="trade_002",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result2 = await risk_guard.review_plan(plan2)
        
        # Should be reduced or rejected
        if result2.decision == RiskDecision.APPROVE_REDUCED:
            assert result2.approved_size_usd < 1000.0
            assert result2.approved_size_usd <= (2000.0 - result1.approved_size_usd)
        else:
            assert result2.decision == RiskDecision.REJECT
    
    @pytest.mark.asyncio
    async def test_daily_loss_limit_triggers_veto(self, risk_guard, paper_engine):
        """Test that daily loss limit stops trading."""
        user_id = "test_user"
        
        # Simulate daily loss at limit
        risk_guard.portfolio.daily_pnl_usd = -5000.0
        
        # Try to place trade
        plan = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result = await risk_guard.review_plan(plan)
        
        assert result.decision == RiskDecision.VETO
        assert "DAILY_LOSS_LIMIT" in result.limit_breaches
        
        # No order should be placed
        portfolio = paper_engine.get_portfolio(user_id)
        assert len(portfolio.positions) == 0


class TestProfitAndLoss:
    """Test P&L calculation in trade flow."""
    
    @pytest.mark.asyncio
    async def test_profitable_trade_flow(self, risk_guard, paper_engine):
        """Test a profitable trade from entry to exit."""
        user_id = "test_user"
        
        # Entry
        plan = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result = await risk_guard.review_plan(plan)
        order = paper_engine.place_order(
            user_id=user_id,
            asset="BTC",
            side="long",
            size_usd=result.approved_size_usd,
            order_type="market",
        )
        
        entry_price = order.fill_price
        initial_balance = paper_engine.get_portfolio(user_id).current_balance
        
        # Price increases 10%
        new_price = entry_price * 1.10
        paper_engine.update_prices({"BTC": new_price, "BTC/USDT": new_price})
        
        # Exit
        pnl = paper_engine.close_position(user_id, "BTC_long_perp")
        
        # Verify profit
        assert pnl > 0
        assert abs(pnl - (result.approved_size_usd * 0.10)) < 50  # ~10% profit minus slippage
        
        # Verify balance increased
        final_balance = paper_engine.get_portfolio(user_id).current_balance
        assert final_balance > initial_balance
    
    @pytest.mark.asyncio
    async def test_losing_trade_flow(self, risk_guard, paper_engine):
        """Test a losing trade from entry to exit."""
        user_id = "test_user"
        
        # Entry
        plan = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result = await risk_guard.review_plan(plan)
        order = paper_engine.place_order(
            user_id=user_id,
            asset="BTC",
            side="long",
            size_usd=result.approved_size_usd,
            order_type="market",
        )
        
        entry_price = order.fill_price
        initial_balance = paper_engine.get_portfolio(user_id).current_balance
        
        # Price decreases 5%
        new_price = entry_price * 0.95
        paper_engine.update_prices({"BTC": new_price, "BTC/USDT": new_price})
        
        # Exit
        pnl = paper_engine.close_position(user_id, "BTC_long_perp")
        
        # Verify loss
        assert pnl < 0
        assert abs(pnl + (result.approved_size_usd * 0.05)) < 50  # ~5% loss plus slippage
        
        # Verify balance reflects loss (initial - margin + margin + pnl = initial + pnl)
        final_balance = paper_engine.get_portfolio(user_id).current_balance
        expected_balance = initial_balance + result.approved_size_usd + pnl  # Return margin + P&L
        assert abs(final_balance - expected_balance) < 10  # Allow small variance


class TestKillSwitchIntegration:
    """Test kill switch integration in trade flow."""
    
    @pytest.mark.asyncio
    async def test_kill_switch_blocks_all_trades(self, risk_guard, paper_engine):
        """Test that kill switch blocks all trading."""
        user_id = "test_user"
        
        # Trigger kill switch
        await risk_guard.trigger_kill_switch("Emergency stop", "admin")
        
        # Try to place trade
        plan = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result = await risk_guard.review_plan(plan)
        
        assert result.decision == RiskDecision.VETO
        assert "KILL_SWITCH_ACTIVE" in result.limit_breaches
        
        # Verify no trades executed
        portfolio = paper_engine.get_portfolio(user_id)
        assert len(portfolio.positions) == 0
        assert portfolio.total_trades == 0


class TestPortfolioStateSync:
    """Test portfolio state synchronization between components."""
    
    @pytest.mark.asyncio
    async def test_portfolio_state_updates(self, risk_guard, paper_engine):
        """Test that portfolio state is properly synchronized."""
        user_id = "test_user"
        
        # Execute trade
        plan = TradePlanInput(
            plan_id="trade_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="agent_1",
        )
        
        result = await risk_guard.review_plan(plan)
        order = paper_engine.place_order(
            user_id=user_id,
            asset="BTC",
            side="long",
            size_usd=result.approved_size_usd,
            order_type="market",
        )
        
        # Update risk guard with new portfolio state
        portfolio = paper_engine.get_portfolio(user_id)
        
        new_state = PortfolioState(
            total_exposure_usd=result.approved_size_usd,
            positions={"BTC": result.approved_size_usd},
            daily_trades=1,
            last_trade_time=time.time(),
        )
        
        risk_guard.update_portfolio(new_state)
        
        # Verify state is synchronized
        assert risk_guard.portfolio.total_exposure_usd == result.approved_size_usd
        assert risk_guard.portfolio.positions["BTC"] == result.approved_size_usd
        assert risk_guard.portfolio.daily_trades == 1
