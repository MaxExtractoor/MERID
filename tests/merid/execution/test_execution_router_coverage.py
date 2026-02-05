"""Comprehensive tests for merid/execution/router.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

from merid.execution.router import (
    TraderIdentity, TradeIntent, ExecutionRouter, get_execution_router
)
from merid.execution.base import TradeResult, Position
from trading.guards.trading_guard import GuardDecision, GuardDecisionStatus


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestTraderIdentity:
    """Test TraderIdentity dataclass."""

    def test_creation(self):
        identity = TraderIdentity(
            trader_type="agent",
            trader_id="agent_001"
        )
        assert identity.trader_type == "agent"
        assert identity.trader_id == "agent_001"

    def test_with_strategy(self):
        identity = TraderIdentity(
            trader_type="human",
            trader_id="user_123",
            strategy="momentum"
        )
        assert identity.strategy == "momentum"


class TestTradeIntent:
    """Test TradeIntent dataclass."""

    def test_creation(self):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="alpaca",
            symbol="AAPL",
            side="buy",
            size=10.0
        )
        assert intent.intent_id == "intent_123"
        assert intent.venue_id == "alpaca"

    def test_defaults(self):
        trader = TraderIdentity(trader_type="human", trader_id="user_1")
        intent = TradeIntent(
            intent_id="intent_456",
            trader=trader,
            venue_id="coinbase",
            symbol="BTC/USD",
            side="sell",
            size=0.1
        )
        assert intent.price is None
        assert intent.params == {}
        assert intent.metadata == {}
        assert intent.guard_decision is None


# =============================================================================
# ExecutionRouter Tests
# =============================================================================

@pytest.fixture
def mock_executor():
    """Create mock executor."""
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="test_venue",
        symbol="BTC/USD",
        side="buy",
        size=1.0,
        price=50000.0,
        tx_id="tx_123"
    ))
    executor.get_positions = AsyncMock(return_value=[])
    return executor


@pytest.fixture
def router(mock_executor):
    """Create ExecutionRouter with mocks."""
    with patch("merid.execution.router.get_runtime_config") as mock_config, \
         patch("merid.execution.router.get_trading_guard") as mock_guard, \
         patch("merid.execution.router.get_solana_anti_rug_guard") as mock_solana, \
         patch("merid.execution.router.get_explainability_service") as mock_explain, \
         patch("merid.execution.router.get_spectator_log") as mock_spectator:
        
        mock_config.return_value = MagicMock()
        mock_config.return_value.snapshot.return_value = {"allow_live_trades": True}
        mock_config.return_value.get_trader.return_value = None
        
        mock_guard_instance = MagicMock()
        mock_guard_instance.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="Trade allowed"
        )
        mock_guard.return_value = mock_guard_instance
        
        mock_solana_instance = MagicMock()
        mock_solana_instance.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="Solana OK"
        )
        mock_solana.return_value = mock_solana_instance
        
        mock_explain_instance = MagicMock()
        mock_explain_instance.record_explanation.return_value = MagicMock(record_id="exp_123")
        mock_explain.return_value = mock_explain_instance
        
        mock_spectator.return_value = MagicMock()
        
        router = ExecutionRouter(executors={"test_venue": mock_executor})
        return router


class TestExecutionRouterInit:
    """Test ExecutionRouter initialization."""

    def test_init_with_executors(self, mock_executor):
        with patch("merid.execution.router.get_runtime_config"), \
             patch("merid.execution.router.get_trading_guard"), \
             patch("merid.execution.router.get_solana_anti_rug_guard"), \
             patch("merid.execution.router.get_explainability_service"), \
             patch("merid.execution.router.get_spectator_log"):
            
            router = ExecutionRouter(executors={"venue1": mock_executor})
            assert "venue1" in router._executors


class TestRegisterExecutor:
    """Test register_executor method."""

    def test_registers_executor(self, router, mock_executor):
        router.register_executor("new_venue", mock_executor)
        assert "new_venue" in router._executors


class TestRegisterListener:
    """Test register_listener method."""

    def test_registers_listener(self, router):
        callback = MagicMock()
        router.register_listener(callback)
        assert callback in router._listeners


class TestSubmitTrade:
    """Test submit_trade method."""

    @pytest.mark.asyncio
    async def test_submit_trade_success(self, router):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        
        with patch.object(router, "_publish_event"), \
             patch.object(router, "_build_trade_request") as mock_build:
            mock_build.return_value = MagicMock()
            result = await router.submit_trade(
                trader=trader,
                venue_id="test_venue",
                symbol="BTC/USD",
                side="buy",
                size=1.0
            )
        
        assert result.success is True


class TestExecute:
    """Test execute method."""

    @pytest.mark.asyncio
    async def test_execute_success(self, router):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC/USD",
            side="buy",
            size=1.0
        )
        
        with patch.object(router, "_publish_event"), \
             patch.object(router, "_build_trade_request") as mock_build:
            mock_build.return_value = MagicMock()
            result = await router.execute(intent)
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_no_executor_raises(self, router):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="unknown_venue",
            symbol="BTC/USD",
            side="buy",
            size=1.0
        )
        
        with pytest.raises(RuntimeError, match="No executor registered"):
            await router.execute(intent)

    @pytest.mark.asyncio
    async def test_execute_with_factory(self, mock_executor):
        with patch("merid.execution.router.get_runtime_config") as mock_config, \
             patch("merid.execution.router.get_trading_guard") as mock_guard, \
             patch("merid.execution.router.get_solana_anti_rug_guard") as mock_solana, \
             patch("merid.execution.router.get_explainability_service") as mock_explain, \
             patch("merid.execution.router.get_spectator_log") as mock_spectator:
            
            mock_config.return_value = MagicMock()
            mock_config.return_value.snapshot.return_value = {"allow_live_trades": True}
            mock_config.return_value.get_trader.return_value = None
            
            mock_guard.return_value.evaluate.return_value = GuardDecision(
                status=GuardDecisionStatus.ALLOW, reason="OK"
            )
            mock_solana.return_value.evaluate.return_value = GuardDecision(
                status=GuardDecisionStatus.ALLOW, reason="OK"
            )
            mock_explain.return_value.record_explanation.return_value = MagicMock(record_id="exp")
            mock_spectator.return_value = MagicMock()
            
            factory = MagicMock(return_value=mock_executor)
            router = ExecutionRouter(executor_factory=factory)
            
            trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
            intent = TradeIntent(
                intent_id="intent_123",
                trader=trader,
                venue_id="dynamic_venue",
                symbol="ETH/USD",
                side="sell",
                size=5.0
            )
            
            with patch.object(router, "_publish_event"), \
                 patch.object(router, "_build_trade_request") as mock_build:
                mock_build.return_value = MagicMock()
                result = await router.execute(intent)
            
            factory.assert_called_with("dynamic_venue")


class TestBlockedResult:
    """Test _blocked_result method."""

    def test_creates_blocked_result(self, router):
        trader = TraderIdentity(trader_type="human", trader_id="user_1")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test",
            symbol="BTC",
            side="buy",
            size=1.0
        )
        guard = GuardDecision(status=GuardDecisionStatus.BLOCK, reason="Risk limit")
        
        result = router._blocked_result(intent, "Blocked", guard)
        
        assert result.success is False
        assert "Blocked" in result.error


class TestSimulatedResult:
    """Test _simulated_result method."""

    def test_creates_simulated_result(self, router):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_456",
            trader=trader,
            venue_id="test",
            symbol="ETH",
            side="sell",
            size=10.0
        )
        guard = GuardDecision(status=GuardDecisionStatus.SIMULATE, reason="Paper mode")
        
        result = router._simulated_result(intent, guard)
        
        assert result.success is True
        assert result.metadata.get("simulated") is True


class TestGetPortfolioSnapshot:
    """Test get_portfolio_snapshot method."""

    @pytest.mark.asyncio
    async def test_aggregates_positions(self, router, mock_executor):
        mock_executor.get_positions.return_value = [
            Position(symbol="BTC", size=1.0, entry_price=50000.0, pnl=100.0, venue="test")
        ]
        
        with patch.object(router._portfolio_aggregator, "aggregate", new_callable=AsyncMock) as mock_agg:
            mock_agg.return_value = MagicMock()
            await router.get_portfolio_snapshot()
            mock_agg.assert_called_once()


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetExecutionRouter:
    """Test get_execution_router singleton."""

    def test_returns_router(self):
        import merid.execution.router as module
        module._execution_router = None
        
        with patch("merid.execution.router.get_runtime_config"), \
             patch("merid.execution.router.get_trading_guard"), \
             patch("merid.execution.router.get_solana_anti_rug_guard"), \
             patch("merid.execution.router.get_explainability_service"), \
             patch("merid.execution.router.get_spectator_log"):
            
            router = get_execution_router()
            assert isinstance(router, ExecutionRouter)


# =============================================================================
# Additional Coverage Tests
# =============================================================================

class TestShouldRequestLive:
    """Test _should_request_live method."""

    def test_trader_spectator_only(self, router):
        router._runtime_config.get_trader.return_value = {"spectator_only": True}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_trader_mode_live(self, router):
        router._runtime_config.get_trader.return_value = {"mode": "live"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        
        result = router._should_request_live(trader)
        
        assert result is True

    def test_trader_mode_sim(self, router):
        router._runtime_config.get_trader.return_value = {"mode": "sim"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_trader_mode_paper(self, router):
        router._runtime_config.get_trader.return_value = {"mode": "paper"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_human_spectator_mode(self, router):
        router._runtime_config.get_trader.return_value = None
        router._runtime_config.snapshot.return_value = {"spectator_mode": True}
        trader = TraderIdentity(trader_type="human", trader_id="user_001")
        
        result = router._should_request_live(trader)
        
        assert result is False


class TestEvaluateGuards:
    """Test _evaluate_guards method."""

    def test_memecoin_guard_blocks(self, router):
        router._solana_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="High risk token"
        )
        
        request = MagicMock()
        metadata = {"category": "memecoin", "token_context": {"token": "SCAM"}}
        
        decision = router._evaluate_guards(request, metadata)
        
        assert decision.status == GuardDecisionStatus.BLOCK

    def test_memecoin_guard_allows(self, router):
        router._solana_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="Safe token"
        )
        
        request = MagicMock()
        metadata = {"category": "memecoin", "token_context": {"token": "SAFE"}}
        
        decision = router._evaluate_guards(request, metadata)
        
        assert decision.status == GuardDecisionStatus.ALLOW


class TestRecordExplanation:
    """Test _record_explanation method."""

    def test_records_explanation(self, router):
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001", strategy="momentum")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test",
            symbol="BTC",
            side="buy",
            size=1.0,
            metadata={"notional_usd": 50000}
        )
        guard = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="OK")
        
        result = router._record_explanation(intent, guard)
        
        assert result == "exp_123"

    def test_handles_attribute_error(self, router):
        router._explainability.record_explanation.side_effect = AttributeError("Missing attr")
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test",
            symbol="BTC",
            side="buy",
            size=1.0
        )
        guard = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="OK")
        
        result = router._record_explanation(intent, guard)
        
        assert result is None

    def test_handles_runtime_error(self, router):
        router._explainability.record_explanation.side_effect = RuntimeError("Service down")
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test",
            symbol="BTC",
            side="buy",
            size=1.0
        )
        guard = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="OK")
        
        result = router._record_explanation(intent, guard)
        
        assert result is None


class TestNotify:
    """Test _notify method."""

    @pytest.mark.asyncio
    async def test_notify_sync_callback(self, router):
        callback = MagicMock()
        router._listeners.append(callback)
        
        await router._notify("test_event", {"data": "value"})
        
        callback.assert_called_with("test_event", {"data": "value"})

    @pytest.mark.asyncio
    async def test_notify_async_callback(self, router):
        callback = AsyncMock()
        router._listeners.append(callback)
        
        await router._notify("test_event", {"data": "value"})
        
        callback.assert_called_with("test_event", {"data": "value"})


class TestPublishEvent:
    """Test _publish_event method."""

    def test_publishes_event(self, router):
        with patch("merid.execution.router.publish_event") as mock_publish:
            router._publish_event("test.event", {"key": "value"})
            mock_publish.assert_called_with("test.event", {"key": "value"})

    def test_handles_connection_error(self, router):
        with patch("merid.execution.router.publish_event", side_effect=ConnectionError("Failed")):
            router._publish_event("test.event", {"key": "value"})

    def test_handles_runtime_error(self, router):
        with patch("merid.execution.router.publish_event", side_effect=RuntimeError("Unexpected")):
            router._publish_event("test.event", {"key": "value"})


class TestGetPortfolioSnapshotErrors:
    """Test get_portfolio_snapshot error handling."""

    @pytest.mark.asyncio
    async def test_handles_attribute_error(self, router, mock_executor):
        mock_executor.get_positions.side_effect = AttributeError("No positions method")
        
        with patch.object(router._portfolio_aggregator, "aggregate", new_callable=AsyncMock) as mock_agg:
            mock_agg.return_value = MagicMock()
            await router.get_portfolio_snapshot()
            mock_agg.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_type_error(self, router, mock_executor):
        mock_executor.get_positions.side_effect = TypeError("Invalid type")
        
        with patch.object(router._portfolio_aggregator, "aggregate", new_callable=AsyncMock) as mock_agg:
            mock_agg.return_value = MagicMock()
            await router.get_portfolio_snapshot()
            mock_agg.assert_called_once()


class TestExecuteGuardDecisions:
    """Test execute with different guard decisions."""

    @pytest.mark.asyncio
    async def test_execute_blocked(self, router):
        router._trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Risk limit exceeded"
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC/USD",
            side="buy",
            size=1.0
        )
        
        with patch.object(router, "_publish_event"), \
             patch.object(router, "_build_trade_request") as mock_build:
            mock_build.return_value = MagicMock()
            result = await router.execute(intent)
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_requires_confirmation(self, router):
        router._trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.REQUIRE_CONFIRMATION,
            reason="Manual approval needed"
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC/USD",
            side="buy",
            size=1.0
        )
        
        with patch.object(router, "_publish_event"), \
             patch.object(router, "_build_trade_request") as mock_build:
            mock_build.return_value = MagicMock()
            result = await router.execute(intent)
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_simulated(self, router):
        router._trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.SIMULATE,
            reason="Paper mode active"
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_001")
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC/USD",
            side="buy",
            size=1.0
        )
        
        with patch.object(router, "_publish_event"), \
             patch.object(router, "_build_trade_request") as mock_build:
            mock_build.return_value = MagicMock()
            result = await router.execute(intent)
        
        assert result.success is True
        assert result.metadata.get("simulated") is True
