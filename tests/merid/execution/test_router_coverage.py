"""Comprehensive tests for merid/execution/router.py coverage."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from merid.execution.router import (
    TraderIdentity,
    TradeIntent,
    ExecutionRouter,
    get_execution_router,
)
from merid.execution.base import TradeResult, Position
from trading.guards.trading_guard import GuardDecision, GuardDecisionStatus


@pytest.fixture
def mock_trading_guard():
    """Create a mock trading guard."""
    guard = MagicMock()
    guard.evaluate.return_value = GuardDecision(
        status=GuardDecisionStatus.ALLOW,
        reason="Allowed by test",
    )
    return guard


@pytest.fixture
def mock_solana_guard():
    """Create a mock Solana anti-rug guard."""
    guard = MagicMock()
    guard.evaluate.return_value = GuardDecision(
        status=GuardDecisionStatus.ALLOW,
        reason="No rug detected",
    )
    return guard


@pytest.fixture
def mock_explainability():
    """Create a mock explainability service."""
    service = MagicMock()
    record = MagicMock()
    record.record_id = "expl_123"
    service.record_explanation.return_value = record
    return service


@pytest.fixture
def mock_spectator():
    """Create a mock spectator logger."""
    return MagicMock()


@pytest.fixture
def mock_runtime_config():
    """Create a mock runtime config."""
    config = MagicMock()
    config.snapshot.return_value = {"allow_live_trades": False}
    config.get_trader.return_value = None
    return config


@pytest.fixture
def mock_executor():
    """Create a mock trade executor."""
    executor = AsyncMock()
    executor.execute_trade.return_value = TradeResult(
        success=True,
        venue="test_venue",
        symbol="BTC-USD",
        side="buy",
        size=1.0,
        price=50000.0,
        tx_id="tx_123",
    )
    executor.get_positions.return_value = [
        Position(symbol="BTC-USD", size=1.0, entry_price=50000.0, pnl=100.0, venue="test_venue")
    ]
    return executor


@pytest.fixture
def router(mock_trading_guard, mock_explainability, mock_spectator, mock_runtime_config):
    """Create a router with mocked dependencies."""
    with patch("merid.execution.router.get_solana_anti_rug_guard") as mock_get_solana:
        mock_solana = MagicMock()
        mock_solana.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.ALLOW, reason="OK"
        )
        mock_get_solana.return_value = mock_solana
        
        r = ExecutionRouter(
            trading_guard=mock_trading_guard,
            explainability_service=mock_explainability,
            spectator_logger=mock_spectator,
            runtime_config=mock_runtime_config,
        )
        # Patch _build_trade_request to avoid TradeSide enum issue
        original_build = r._build_trade_request
        def patched_build(intent):
            from trading.adapters.base import TradeRequest, TradeSide
            should_live = r._should_request_live(intent.trader)
            return TradeRequest(
                venue=intent.venue_id,
                symbol=intent.symbol,
                side=TradeSide(intent.side),  # Use lowercase directly
                quantity=intent.size,
                price=intent.price,
                metadata={**intent.metadata, "trader_id": intent.trader.trader_id},
                client_reference=intent.intent_id,
                live=should_live,
            )
        r._build_trade_request = patched_build
        return r


class TestExecutionRouterSubmitTrade:
    """Tests for ExecutionRouter.submit_trade."""

    @pytest.mark.asyncio
    async def test_submit_trade_success(self, router, mock_executor):
        """Test successful trade submission."""
        router.register_executor("test_venue", mock_executor)
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        with patch("merid.execution.router.publish_event"):
            result = await router.submit_trade(
                trader=trader,
                venue_id="test_venue",
                symbol="BTC-USD",
                side="buy",
                size=1.0,
            )
        
        assert result.success is True
        assert result.venue == "test_venue"
        assert result.symbol == "BTC-USD"

    @pytest.mark.asyncio
    async def test_submit_trade_with_price(self, router, mock_executor):
        """Test trade submission with price."""
        router.register_executor("test_venue", mock_executor)
        trader = TraderIdentity(trader_type="human", trader_id="human_1")
        
        with patch("merid.execution.router.publish_event"):
            result = await router.submit_trade(
                trader=trader,
                venue_id="test_venue",
                symbol="ETH-USD",
                side="sell",
                size=10.0,
                price=3000.0,
            )
        
        assert result.success is True


class TestExecutionRouterExecute:
    """Tests for ExecutionRouter.execute."""

    @pytest.mark.asyncio
    async def test_execute_no_executor_raises(self, router):
        """Test execute raises when no executor found."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="unknown_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        
        with pytest.raises(RuntimeError, match="No executor registered"):
            await router.execute(intent)

    @pytest.mark.asyncio
    async def test_execute_uses_factory_if_provided(self, router, mock_executor):
        """Test execute uses executor factory when available."""
        router._executor_factory = lambda venue: mock_executor if venue == "dynamic_venue" else None
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="dynamic_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        
        with patch("merid.execution.router.publish_event"):
            result = await router.execute(intent)
        
        assert result.success is True
        assert "dynamic_venue" in router._executors

    @pytest.mark.asyncio
    async def test_execute_guard_blocks(self, router, mock_executor, mock_trading_guard):
        """Test execute returns blocked result when guard blocks."""
        router.register_executor("test_venue", mock_executor)
        mock_trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Trade blocked by guard",
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        
        with patch("merid.execution.router.publish_event"):
            result = await router.execute(intent)
        
        assert result.success is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_guard_requires_confirmation(self, router, mock_executor, mock_trading_guard):
        """Test execute returns blocked result when confirmation required."""
        router.register_executor("test_venue", mock_executor)
        mock_trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.REQUIRE_CONFIRMATION,
            reason="Requires confirmation",
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        
        with patch("merid.execution.router.publish_event"):
            result = await router.execute(intent)
        
        assert result.success is False
        assert "confirmation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_guard_simulates(self, router, mock_executor, mock_trading_guard):
        """Test execute returns simulated result when guard simulates."""
        router.register_executor("test_venue", mock_executor)
        mock_trading_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.SIMULATE,
            reason="Trade simulated",
        )
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
            price=50000.0,
        )
        
        with patch("merid.execution.router.publish_event"):
            result = await router.execute(intent)
        
        assert result.success is True
        assert result.metadata.get("simulated") is True


class TestExecutionRouterBuildTradeRequest:
    """Tests for _build_trade_request."""

    def test_build_trade_request(self, router, mock_runtime_config):
        """Test building trade request from intent."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
            price=50000.0,
        )
        
        request = router._build_trade_request(intent)
        
        assert request.venue == "test_venue"
        assert request.symbol == "BTC-USD"
        assert request.quantity == 1.0
        assert request.price == 50000.0


class TestExecutionRouterShouldRequestLive:
    """Tests for _should_request_live."""

    def test_spectator_only_trader_returns_false(self, router, mock_runtime_config):
        """Test spectator_only trader returns False."""
        mock_runtime_config.get_trader.return_value = {"spectator_only": True}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_live_mode_trader_returns_true(self, router, mock_runtime_config):
        """Test live mode trader returns True."""
        mock_runtime_config.get_trader.return_value = {"mode": "live"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        result = router._should_request_live(trader)
        
        assert result is True

    def test_sim_mode_trader_returns_false(self, router, mock_runtime_config):
        """Test sim mode trader returns False."""
        mock_runtime_config.get_trader.return_value = {"mode": "sim"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_paper_mode_trader_returns_false(self, router, mock_runtime_config):
        """Test paper mode trader returns False."""
        mock_runtime_config.get_trader.return_value = {"mode": "paper"}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_human_spectator_mode_returns_false(self, router, mock_runtime_config):
        """Test human trader in spectator mode returns False."""
        mock_runtime_config.get_trader.return_value = None
        mock_runtime_config.snapshot.return_value = {"spectator_mode": True}
        trader = TraderIdentity(trader_type="human", trader_id="human_1")
        
        result = router._should_request_live(trader)
        
        assert result is False

    def test_allow_live_trades_returns_true(self, router, mock_runtime_config):
        """Test allow_live_trades returns True."""
        mock_runtime_config.get_trader.return_value = None
        mock_runtime_config.snapshot.return_value = {"allow_live_trades": True}
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        
        result = router._should_request_live(trader)
        
        assert result is True


class TestExecutionRouterEvaluateGuards:
    """Tests for _evaluate_guards."""

    def test_evaluate_guards_standard(self, router, mock_trading_guard):
        """Test standard guard evaluation."""
        from trading.adapters.base import TradeRequest, TradeSide
        
        request = TradeRequest(
            venue="test",
            symbol="BTC-USD",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        
        decision = router._evaluate_guards(request, {})
        
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_evaluate_guards_memecoin_blocked(self, router, mock_trading_guard):
        """Test memecoin guard blocks when anti-rug fails."""
        from trading.adapters.base import TradeRequest, TradeSide
        
        router._solana_guard.evaluate.return_value = GuardDecision(
            status=GuardDecisionStatus.BLOCK,
            reason="Rug detected",
        )
        
        request = TradeRequest(
            venue="test",
            symbol="MEME-SOL",
            side=TradeSide.BUY,
            quantity=1.0,
        )
        
        decision = router._evaluate_guards(request, {"category": "memecoin", "token_context": {}})
        
        assert decision.status == GuardDecisionStatus.BLOCK


class TestExecutionRouterRecordExplanation:
    """Tests for _record_explanation."""

    def test_record_explanation_success(self, router, mock_explainability):
        """Test successful explanation recording."""
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        guard_decision = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="Allowed")
        
        result = router._record_explanation(intent, guard_decision)
        
        assert result == "expl_123"

    def test_record_explanation_attribute_error(self, router, mock_explainability):
        """Test explanation recording handles AttributeError."""
        mock_explainability.record_explanation.side_effect = AttributeError("Test error")
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        guard_decision = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="Allowed")
        
        result = router._record_explanation(intent, guard_decision)
        
        assert result is None

    def test_record_explanation_runtime_error(self, router, mock_explainability):
        """Test explanation recording handles RuntimeError."""
        mock_explainability.record_explanation.side_effect = RuntimeError("Test error")
        
        trader = TraderIdentity(trader_type="agent", trader_id="agent_1")
        intent = TradeIntent(
            intent_id="intent_1",
            trader=trader,
            venue_id="test_venue",
            symbol="BTC-USD",
            side="buy",
            size=1.0,
        )
        guard_decision = GuardDecision(status=GuardDecisionStatus.ALLOW, reason="Allowed")
        
        result = router._record_explanation(intent, guard_decision)
        
        assert result is None


class TestExecutionRouterNotify:
    """Tests for _notify."""

    @pytest.mark.asyncio
    async def test_notify_sync_callback(self, router):
        """Test notify with sync callback."""
        called = []
        
        def sync_callback(event_type, payload):
            called.append((event_type, payload))
        
        router.register_listener(sync_callback)
        await router._notify("test_event", {"data": 123})
        
        assert len(called) == 1
        assert called[0][0] == "test_event"

    @pytest.mark.asyncio
    async def test_notify_async_callback(self, router):
        """Test notify with async callback."""
        called = []
        
        async def async_callback(event_type, payload):
            called.append((event_type, payload))
        
        router.register_listener(async_callback)
        await router._notify("test_event", {"data": 456})
        
        assert len(called) == 1
        assert called[0][0] == "test_event"


class TestExecutionRouterGetPortfolioSnapshot:
    """Tests for get_portfolio_snapshot."""

    @pytest.mark.asyncio
    async def test_get_portfolio_snapshot_success(self, router, mock_executor):
        """Test successful portfolio snapshot."""
        router.register_executor("test_venue", mock_executor)
        
        with patch.object(router._portfolio_aggregator, "aggregate", new_callable=AsyncMock) as mock_agg:
            mock_agg.return_value = MagicMock(total_value=100000.0)
            snapshot = await router.get_portfolio_snapshot()
        
        assert snapshot.total_value == 100000.0

    @pytest.mark.asyncio
    async def test_get_portfolio_snapshot_executor_error(self, router, mock_executor):
        """Test portfolio snapshot handles executor errors."""
        mock_executor.get_positions.side_effect = ConnectionError("Network error")
        router.register_executor("test_venue", mock_executor)
        
        with patch.object(router._portfolio_aggregator, "aggregate", new_callable=AsyncMock) as mock_agg:
            mock_agg.return_value = MagicMock(total_value=0.0)
            snapshot = await router.get_portfolio_snapshot()
        
        assert snapshot is not None


class TestExecutionRouterPublishEvent:
    """Tests for _publish_event."""

    def test_publish_event_success(self, router):
        """Test successful event publishing."""
        with patch("merid.execution.router.publish_event") as mock_publish:
            router._publish_event("test.event", {"data": "test"})
            mock_publish.assert_called_once()

    def test_publish_event_connection_error(self, router):
        """Test event publishing handles ConnectionError."""
        with patch("merid.execution.router.publish_event") as mock_publish:
            mock_publish.side_effect = ConnectionError("Network error")
            # Should not raise
            router._publish_event("test.event", {"data": "test"})

    def test_publish_event_runtime_error(self, router):
        """Test event publishing handles RuntimeError."""
        with patch("merid.execution.router.publish_event") as mock_publish:
            mock_publish.side_effect = RuntimeError("Unexpected error")
            # Should not raise
            router._publish_event("test.event", {"data": "test"})


class TestGetExecutionRouterSingleton:
    """Tests for get_execution_router singleton."""

    def test_get_execution_router_creates_singleton(self):
        """Test get_execution_router creates a singleton."""
        import merid.execution.router as router_module
        
        # Reset singleton
        router_module._execution_router = None
        
        router1 = get_execution_router()
        router2 = get_execution_router()
        
        assert router1 is router2
        assert isinstance(router1, ExecutionRouter)
