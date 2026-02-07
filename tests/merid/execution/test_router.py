"""Tests for merid/execution/router.py - Coverage improvement."""

import pytest
import time
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from merid.execution.router import (
    TraderIdentity,
    TradeIntent,
    ExecutionRouter,
    get_execution_router,
)
from merid.execution.base import TradeResult
from trading.guards.trading_guard import GuardDecision, GuardDecisionStatus


# =============================================================================
# TraderIdentity Tests
# =============================================================================

class TestTraderIdentity:
    """Test TraderIdentity dataclass."""
    
    def test_creation_minimal(self):
        """Test minimal TraderIdentity creation."""
        trader = TraderIdentity(
            trader_type="agent",
            trader_id="agent_001"
        )
        
        assert trader.trader_type == "agent"
        assert trader.trader_id == "agent_001"
        assert trader.strategy is None
    
    def test_creation_with_strategy(self):
        """Test TraderIdentity with strategy."""
        trader = TraderIdentity(
            trader_type="human",
            trader_id="user_123",
            strategy="momentum"
        )
        
        assert trader.strategy == "momentum"


# =============================================================================
# TradeIntent Tests
# =============================================================================

class TestTradeIntent:
    """Test TradeIntent dataclass."""
    
    def test_creation(self):
        """Test TradeIntent creation."""
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="binance",
            symbol="BTC/USDT",
            side="buy",
            size=1.0
        )
        
        assert intent.intent_id == "intent_123"
        assert intent.venue_id == "binance"
        assert intent.symbol == "BTC/USDT"
        assert intent.side == "buy"
        assert intent.size == 1.0
        assert intent.price is None
        assert intent.guard_decision is None
    
    def test_creation_with_all_fields(self):
        """Test TradeIntent with all optional fields."""
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        intent = TradeIntent(
            intent_id="intent_123",
            trader=trader,
            venue_id="binance",
            symbol="BTC/USDT",
            side="buy",
            size=1.0,
            price=50000.0,
            params={"order_type": "limit"},
            metadata={"source": "test"}
        )
        
        assert intent.price == 50000.0
        assert intent.params == {"order_type": "limit"}
        assert intent.metadata == {"source": "test"}


# =============================================================================
# ExecutionRouter Tests
# =============================================================================

class TestExecutionRouterInit:
    """Test ExecutionRouter initialization."""
    
    def test_default_init(self):
        """Test default initialization."""
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
        
        assert router._executors == {}
    
    def test_init_with_executors(self):
        """Test initialization with executors."""
        mock_executor = Mock()
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(executors={"binance": mock_executor})
        
        assert "binance" in router._executors


class TestExecutionRouterRegister:
    """Test executor and listener registration."""
    
    def test_register_executor(self):
        """Test registering an executor."""
        mock_executor = Mock()
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
            router.register_executor("coinbase", mock_executor)
        
        assert "coinbase" in router._executors
    
    def test_register_listener(self):
        """Test registering a listener."""
        mock_callback = Mock()
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
            router.register_listener(mock_callback)
        
        assert mock_callback in router._listeners


class TestExecutionRouterSubmitTrade:
    """Test submit_trade method."""
    
    @pytest.mark.asyncio
    async def test_submit_trade_no_executor(self):
        """Test submit_trade with no executor raises error."""
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        with pytest.raises(RuntimeError, match="No executor registered"):
            await router.submit_trade(
                trader=trader,
                venue_id="unknown",
                symbol="BTC/USDT",
                side="buy",
                size=1.0
            )
    
    @pytest.mark.asyncio
    async def test_submit_trade_blocked(self):
        """Test submit_trade when guard blocks."""
        mock_executor = AsyncMock()
        mock_guard = Mock()
        mock_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Risk limit exceeded"
        )
        mock_spectator = Mock()
        mock_explainability = Mock()
        mock_explainability.record_explanation.return_value = Mock(record_id="exp_123")
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = None
        
        with patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.publish_event'):
            router = ExecutionRouter(
                executors={"binance": mock_executor},
                trading_guard=mock_guard,
                spectator_logger=mock_spectator,
                explainability_service=mock_explainability,
                runtime_config=mock_runtime
            )
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        # Mock _build_trade_request to avoid TradeSide enum issues
        with patch.object(router, '_build_trade_request') as mock_build:
            mock_build.return_value = Mock()
            result = await router.submit_trade(
                trader=trader,
                venue_id="binance",
                symbol="BTC/USDT",
                side="buy",
                size=1.0
            )
        
        assert result.success is False
        assert "block" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_submit_trade_simulated(self):
        """Test submit_trade with simulate decision."""
        mock_executor = AsyncMock()
        mock_guard = Mock()
        mock_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.SIMULATE,
            reason="Paper mode"
        )
        mock_spectator = Mock()
        mock_explainability = Mock()
        mock_explainability.record_explanation.return_value = Mock(record_id="exp_123")
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = None
        
        with patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.publish_event'):
            router = ExecutionRouter(
                executors={"binance": mock_executor},
                trading_guard=mock_guard,
                spectator_logger=mock_spectator,
                explainability_service=mock_explainability,
                runtime_config=mock_runtime
            )
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        # Mock _build_trade_request to avoid TradeSide enum issues
        with patch.object(router, '_build_trade_request') as mock_build:
            mock_build.return_value = Mock()
            result = await router.submit_trade(
                trader=trader,
                venue_id="binance",
                symbol="BTC/USDT",
                side="buy",
                size=1.0
            )
        
        assert result.success is True
        assert result.metadata.get("simulated") is True


class TestExecutionRouterExecute:
    """Test execute method."""
    
    @pytest.mark.asyncio
    async def test_execute_with_factory(self):
        """Test execute creates executor via factory."""
        mock_executor = AsyncMock()
        mock_executor.execute_trade.return_value = TradeResult(
            success=True,
            venue="binance",
            symbol="BTC/USDT",
            side="buy",
            size=1.0,
            price=50000.0
        )
        
        def factory(venue):
            return mock_executor if venue == "binance" else None
        
        mock_guard = Mock()
        mock_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="OK"
        )
        mock_spectator = Mock()
        mock_explainability = Mock()
        mock_explainability.record_explanation.return_value = Mock(record_id="exp_123")
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {"allow_live_trades": True}
        mock_runtime.get_trader.return_value = None
        
        with patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.publish_event'):
            router = ExecutionRouter(
                executor_factory=factory,
                trading_guard=mock_guard,
                spectator_logger=mock_spectator,
                explainability_service=mock_explainability,
                runtime_config=mock_runtime
            )
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        intent = TradeIntent(
            intent_id="i1",
            trader=trader,
            venue_id="binance",
            symbol="BTC/USDT",
            side="buy",
            size=1.0
        )
        
        # Mock _build_trade_request to avoid TradeSide enum issues
        with patch.object(router, '_build_trade_request') as mock_build:
            mock_build.return_value = Mock()
            result = await router.execute(intent)
        
        assert result.success is True
        mock_executor.execute_trade.assert_called_once()


class TestExecutionRouterHelpers:
    """Test helper methods."""
    
    def test_should_request_live_spectator_mode(self):
        """Test _should_request_live in spectator mode."""
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {"spectator_mode": True}
        mock_runtime.get_trader.return_value = None
        
        with patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(runtime_config=mock_runtime)
        
        trader = TraderIdentity(trader_type="human", trader_id="u1")
        
        result = router._should_request_live(trader)
        
        assert result is False
    
    def test_should_request_live_trader_config_live(self):
        """Test _should_request_live with trader config set to live."""
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = {"mode": "live"}
        
        with patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(runtime_config=mock_runtime)
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        result = router._should_request_live(trader)
        
        assert result is True
    
    def test_should_request_live_trader_config_sim(self):
        """Test _should_request_live with trader config set to sim."""
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = {"mode": "sim"}
        
        with patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(runtime_config=mock_runtime)
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        result = router._should_request_live(trader)
        
        assert result is False
    
    def test_should_request_live_spectator_only(self):
        """Test _should_request_live with spectator_only trader."""
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = {"spectator_only": True}
        
        with patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(runtime_config=mock_runtime)
        
        trader = TraderIdentity(trader_type="agent", trader_id="a1")
        
        result = router._should_request_live(trader)
        
        assert result is False
    
    def test_evaluate_guards_memecoin(self):
        """Test _evaluate_guards with memecoin category."""
        mock_guard = Mock()
        mock_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW,
            reason="OK"
        )
        mock_solana_guard = Mock()
        mock_solana_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Rug risk detected"
        )
        mock_runtime = Mock()
        mock_runtime.snapshot.return_value = {}
        mock_runtime.get_trader.return_value = None
        
        with patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(
                trading_guard=mock_guard,
                runtime_config=mock_runtime
            )
            router._solana_guard = mock_solana_guard
        
        from trading.adapters.base import TradeRequest, TradeSide
        request = TradeRequest(
            venue="raydium",
            symbol="MEME/SOL",
            side=TradeSide.BUY,
            quantity=1.0
        )
        
        result = router._evaluate_guards(request, {"category": "memecoin"})
        
        assert result.status == GuardDecisionStatus.BLOCK


class TestExecutionRouterNotify:
    """Test _notify method."""
    
    @pytest.mark.asyncio
    async def test_notify_sync_callback(self):
        """Test _notify with sync callback."""
        callback = Mock()
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
            router.register_listener(callback)
        
        await router._notify("test_event", {"data": "test"})
        
        callback.assert_called_once_with("test_event", {"data": "test"})
    
    @pytest.mark.asyncio
    async def test_notify_async_callback(self):
        """Test _notify with async callback."""
        callback = AsyncMock()
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter()
            router.register_listener(callback)
        
        await router._notify("test_event", {"data": "test"})
        
        callback.assert_awaited_once_with("test_event", {"data": "test"})


class TestExecutionRouterPortfolio:
    """Test get_portfolio_snapshot method."""
    
    @pytest.mark.asyncio
    async def test_get_portfolio_snapshot(self):
        """Test getting portfolio snapshot."""
        mock_executor = AsyncMock()
        mock_executor.get_positions.return_value = []
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(executors={"binance": mock_executor})
        
        snapshot = await router.get_portfolio_snapshot()
        
        assert snapshot is not None
    
    @pytest.mark.asyncio
    async def test_get_portfolio_snapshot_executor_error(self):
        """Test portfolio snapshot handles executor errors."""
        mock_executor = AsyncMock()
        mock_executor.get_positions.side_effect = RuntimeError("Connection failed")
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router = ExecutionRouter(executors={"binance": mock_executor})
        
        # Should not raise, returns snapshot with empty positions
        snapshot = await router.get_portfolio_snapshot()
        
        assert snapshot is not None


class TestExecutionRouterPublishEvent:
    """Test _publish_event method."""
    
    def test_publish_event_success(self):
        """Test successful event publishing."""
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'), \
             patch('merid.execution.router.publish_event') as mock_publish:
            router = ExecutionRouter()
            router._publish_event("test.event", {"key": "value"})
        
        mock_publish.assert_called_once_with("test.event", {"key": "value"})
    
    def test_publish_event_connection_error(self):
        """Test event publishing handles connection error."""
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'), \
             patch('merid.execution.router.publish_event', side_effect=ConnectionError("Failed")):
            router = ExecutionRouter()
            # Should not raise
            router._publish_event("test.event", {"key": "value"})


class TestGetExecutionRouter:
    """Test get_execution_router singleton."""
    
    def test_singleton(self):
        """Test get_execution_router returns singleton."""
        import merid.execution.router as router_module
        router_module._execution_router = None
        
        with patch('merid.execution.router.get_runtime_config'), \
             patch('merid.execution.router.get_trading_guard'), \
             patch('merid.execution.router.get_solana_anti_rug_guard'), \
             patch('merid.execution.router.get_explainability_service'), \
             patch('merid.execution.router.get_spectator_log'):
            router1 = get_execution_router()
            router2 = get_execution_router()
        
        assert router1 is router2
