"""Extended tests for trading/execution.py - Coverage improvement for uncovered methods."""
import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import asdict

from trading.execution import (
    ExecutionMode,
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    Order,
    Position,
    ExecutionConfig,
    ExecutionEngine,
    ExecutionError,
    InsufficientFundsError,
    PositionLimitError,
    OrderRejectedError,
)

# Import singleton functions from the core module
import trading._execution_core as exec_core


@pytest.fixture
def mock_deps():
    """Mock all external dependencies for ExecutionEngine."""
    with patch('trading._execution_core.get_error_handler') as mock_eh, \
         patch('trading._execution_core.get_state_manager') as mock_sm, \
         patch('trading._execution_core.get_self_healing') as mock_sh, \
         patch('trading._execution_core.get_health_monitor') as mock_hm, \
         patch('trading._execution_core.get_logger') as mock_log:
        
        mock_eh.return_value = MagicMock()
        mock_eh.return_value.register_circuit_breaker.return_value = MagicMock()
        mock_eh.return_value.handle_error = AsyncMock()
        
        mock_sm.return_value = MagicMock()
        mock_sm.return_value.initialize = AsyncMock()
        mock_sm.return_value.start_auto_save = AsyncMock()
        mock_sm.return_value.stop_auto_save = AsyncMock()
        mock_sm.return_value.get_state = AsyncMock(return_value=None)
        mock_sm.return_value.update_state = AsyncMock()
        
        mock_sh.return_value = MagicMock()
        mock_sh.return_value.register_healing_strategy = MagicMock()
        
        mock_hm.return_value = MagicMock()
        mock_hm.return_value.register_health_check.return_value = MagicMock()
        mock_hm.return_value.start_monitoring = AsyncMock()
        mock_hm.return_value.stop_monitoring = AsyncMock()
        
        mock_log.return_value = MagicMock()
        
        yield {
            'error_handler': mock_eh,
            'state_manager': mock_sm,
            'self_healing': mock_sh,
            'health_monitor': mock_hm,
            'logger': mock_log,
        }


@pytest.fixture
def engine(mock_deps):
    """Create a test execution engine."""
    eng = ExecutionEngine()
    eng._reality_auditor = None
    eng._mev_defender = None
    eng._validator = None
    return eng


class TestCancelOrder:
    """Test cancel_order method."""

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, engine):
        """Test cancelling an order that doesn't exist."""
        result = await engine.cancel_order("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_pending_order(self, engine):
        """Test cancelling a pending order."""
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING
        )
        engine._orders["order_001"] = order
        
        result = await engine.cancel_order("order_001")
        
        assert result is True
        assert order.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_filled_order(self, engine):
        """Test cancelling an already filled order."""
        order = Order(
            order_id="order_002",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.FILLED
        )
        engine._orders["order_002"] = order
        
        result = await engine.cancel_order("order_002")
        
        assert result is False
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_cancel_order_emits_event(self, engine):
        """Test that cancelling order emits event."""
        order = Order(
            order_id="order_003",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING
        )
        engine._orders["order_003"] = order
        
        callback = MagicMock()
        engine.register_event_callback(callback)
        
        await engine.cancel_order("order_003")
        
        assert callback.called


class TestClosePosition:
    """Test close_position method."""

    @pytest.mark.asyncio
    async def test_close_nonexistent_position(self, engine):
        """Test closing a position that doesn't exist."""
        result = await engine.close_position("NONEXISTENT/USD")
        assert result is None

    @pytest.mark.asyncio
    async def test_close_long_position(self, engine):
        """Test closing a long position."""
        position = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=51000.0
        )
        engine._positions["BTC/USD"] = position
        engine._price_cache["BTC/USD"] = 51000.0
        
        with patch.object(engine, 'submit_order', new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = Order(
                order_id="close_order",
                symbol="BTC/USD",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=1.0
            )
            
            result = await engine.close_position("BTC/USD", reason="test")
        
        assert result is not None
        mock_submit.assert_called_once()
        # Should be SELL order for LONG position
        call_args = mock_submit.call_args
        assert call_args.kwargs['side'] == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_close_short_position(self, engine):
        """Test closing a short position."""
        position = Position(
            position_id="pos_002",
            symbol="ETH/USD",
            side=PositionSide.SHORT,
            quantity=5.0,
            entry_price=3000.0,
            current_price=2900.0
        )
        engine._positions["ETH/USD"] = position
        engine._price_cache["ETH/USD"] = 2900.0
        
        with patch.object(engine, 'submit_order', new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = Order(
                order_id="close_order",
                symbol="ETH/USD",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=5.0
            )
            
            result = await engine.close_position("ETH/USD")
        
        assert result is not None
        # Should be BUY order for SHORT position
        call_args = mock_submit.call_args
        assert call_args.kwargs['side'] == OrderSide.BUY


class TestGetters:
    """Test getter methods."""

    def test_get_position_exists(self, engine):
        """Test getting an existing position."""
        position = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        engine._positions["BTC/USD"] = position
        
        result = engine.get_position("BTC/USD")
        assert result == position

    def test_get_position_not_exists(self, engine):
        """Test getting a non-existent position."""
        result = engine.get_position("NONEXISTENT/USD")
        assert result is None

    def test_get_all_positions(self, engine):
        """Test getting all positions."""
        pos1 = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        pos2 = Position(
            position_id="pos_002",
            symbol="ETH/USD",
            side=PositionSide.SHORT,
            quantity=5.0,
            entry_price=3000.0,
            current_price=3000.0
        )
        engine._positions["BTC/USD"] = pos1
        engine._positions["ETH/USD"] = pos2
        
        result = engine.get_all_positions()
        assert len(result) == 2
        assert pos1 in result
        assert pos2 in result

    def test_get_order_exists(self, engine):
        """Test getting an existing order."""
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        engine._orders["order_001"] = order
        
        result = engine.get_order("order_001")
        assert result == order

    def test_get_order_not_exists(self, engine):
        """Test getting a non-existent order."""
        result = engine.get_order("nonexistent")
        assert result is None

    def test_get_open_orders(self, engine):
        """Test getting open orders only."""
        order1 = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING
        )
        order2 = Order(
            order_id="order_002",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=5.0,
            status=OrderStatus.FILLED
        )
        order3 = Order(
            order_id="order_003",
            symbol="SOL/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0,
            status=OrderStatus.SUBMITTED
        )
        engine._orders["order_001"] = order1
        engine._orders["order_002"] = order2
        engine._orders["order_003"] = order3
        
        result = engine.get_open_orders()
        assert len(result) == 2  # Only pending and submitted
        assert order1 in result
        assert order3 in result
        assert order2 not in result


class TestAccountSummary:
    """Test get_account_summary method."""

    def test_account_summary_empty(self, engine):
        """Test account summary with no positions."""
        summary = engine.get_account_summary()
        
        assert summary["mode"] == "paper"
        assert summary["balance"] == 100000.0
        assert summary["equity"] == 100000.0
        assert summary["total_exposure"] == 0.0
        assert summary["unrealized_pnl"] == 0.0
        assert summary["realized_pnl"] == 0.0
        assert summary["open_positions"] == 0
        assert summary["open_orders"] == 0

    def test_account_summary_with_positions(self, engine):
        """Test account summary with positions."""
        pos = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=1000.0,
            realized_pnl=500.0,
            margin_used=5000.0
        )
        engine._positions["BTC/USD"] = pos
        engine._total_exposure = 50000.0
        
        summary = engine.get_account_summary()
        
        assert summary["open_positions"] == 1
        assert summary["unrealized_pnl"] == 1000.0
        assert summary["realized_pnl"] == 500.0
        assert summary["margin_used"] == 5000.0


class TestValidateOrder:
    """Test _validate_order method."""

    def test_validate_order_no_price(self, engine):
        """Test validation fails when no price available."""
        order = Order(
            order_id="order_001",
            symbol="UNKNOWN/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        with pytest.raises(ExecutionError, match="No price available"):
            engine._validate_order(order)

    def test_validate_order_exceeds_position_limit(self, engine):
        """Test validation fails when order exceeds position limit."""
        engine._price_cache["BTC/USD"] = 50000.0
        engine.config.mode = ExecutionMode.LIVE
        engine.config.max_position_size_usd = 10000.0
        engine.config.api_key = "test"
        engine.config.api_secret = "test"
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0  # 1 BTC = $50000 > $10000 limit
        )
        
        with pytest.raises(PositionLimitError):
            engine._validate_order(order, execution_mode=ExecutionMode.LIVE)

    def test_validate_order_exceeds_total_exposure(self, engine):
        """Test validation fails when total exposure exceeded."""
        engine._price_cache["BTC/USD"] = 1000.0
        engine.config.mode = ExecutionMode.LIVE
        engine.config.max_total_exposure_usd = 5000.0
        engine.config.max_position_size_usd = 10000.0  # Allow single position
        engine.config.api_key = "test"
        engine.config.api_secret = "test"
        engine._total_exposure = 4500.0
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0  # Would add $1000 > remaining $500
        )
        
        with pytest.raises(PositionLimitError):
            engine._validate_order(order, execution_mode=ExecutionMode.LIVE)

    def test_validate_order_insufficient_funds(self, engine):
        """Test validation fails when insufficient funds."""
        engine._price_cache["BTC/USD"] = 50000.0
        engine._balance = 10000.0
        engine.config.max_position_size_usd = 100000.0
        engine.config.max_total_exposure_usd = 200000.0
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0  # $50000 > $10000 balance
        )
        
        with pytest.raises(InsufficientFundsError):
            engine._validate_order(order)

    def test_validate_order_success(self, engine):
        """Test successful order validation."""
        engine._price_cache["BTC/USD"] = 1000.0
        engine._balance = 100000.0
        engine.config.max_position_size_usd = 50000.0
        engine.config.max_total_exposure_usd = 100000.0
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0  # $1000 within limits
        )
        
        # Should not raise
        engine._validate_order(order)

    def test_validate_order_paper_mode_limits(self, engine):
        """Test paper mode uses paper limits."""
        engine._price_cache["BTC/USD"] = 30000.0
        engine.config.mode = ExecutionMode.PAPER
        engine.config.max_position_size_usd = 10000.0
        engine.config.paper_max_position_size_usd = 50000.0
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0  # $30000 > live limit but < paper limit
        )
        
        # Should use paper limits and pass
        engine._validate_order(order, execution_mode=ExecutionMode.PAPER)


class TestExecutePaperOrder:
    """Test _execute_paper_order method."""

    @pytest.mark.asyncio
    async def test_execute_paper_buy_order(self, engine):
        """Test paper order execution for buy."""
        engine._price_cache["BTC/USD"] = 50000.0
        
        order = Order(
            order_id="order_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        await engine._execute_paper_order(order, None, None)
        
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 1.0
        assert order.filled_price > 50000.0  # Includes slippage
        assert order.filled_at is not None

    @pytest.mark.asyncio
    async def test_execute_paper_sell_order(self, engine):
        """Test paper order execution for sell."""
        engine._price_cache["ETH/USD"] = 3000.0
        
        order = Order(
            order_id="order_002",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=5.0
        )
        
        await engine._execute_paper_order(order, None, None)
        
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 5.0
        assert order.filled_price < 3000.0  # Includes negative slippage

    @pytest.mark.asyncio
    async def test_execute_paper_order_creates_position(self, engine):
        """Test paper order creates position."""
        engine._price_cache["SOL/USD"] = 100.0
        
        order = Order(
            order_id="order_003",
            symbol="SOL/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0
        )
        
        await engine._execute_paper_order(order, 90.0, 120.0)
        
        assert "SOL/USD" in engine._positions
        position = engine._positions["SOL/USD"]
        assert position.side == PositionSide.LONG
        assert position.quantity == 10.0
        assert position.stop_loss == 90.0
        assert position.take_profit == 120.0


class TestDefaultStopAndTarget:
    """Test default stop loss and take profit calculations."""

    def test_calculate_default_stop_long(self, engine):
        """Test default stop loss for long position."""
        engine.config.default_stop_loss_pct = 0.05  # 5%
        
        stop = engine._calculate_default_stop(100.0, PositionSide.LONG)
        
        assert stop == 95.0  # 100 - (100 * 0.05)

    def test_calculate_default_stop_short(self, engine):
        """Test default stop loss for short position."""
        engine.config.default_stop_loss_pct = 0.05  # 5%
        
        stop = engine._calculate_default_stop(100.0, PositionSide.SHORT)
        
        assert stop == 105.0  # 100 + (100 * 0.05)

    def test_calculate_default_target_long(self, engine):
        """Test default take profit for long position."""
        engine.config.default_take_profit_pct = 0.10  # 10%
        
        target = engine._calculate_default_target(100.0, PositionSide.LONG)
        
        assert target == 110.0  # 100 + (100 * 0.10)

    def test_calculate_default_target_short(self, engine):
        """Test default take profit for short position."""
        engine.config.default_take_profit_pct = 0.10  # 10%
        
        target = engine._calculate_default_target(100.0, PositionSide.SHORT)
        
        assert target == 90.0  # 100 - (100 * 0.10)


class TestUpdateEquity:
    """Test _update_equity method."""

    def test_update_equity_no_positions(self, engine):
        """Test equity equals balance when no positions."""
        engine._balance = 50000.0
        engine._equity = 0.0
        
        engine._update_equity()
        
        assert engine._equity == 50000.0

    def test_update_equity_with_profit(self, engine):
        """Test equity with profitable positions."""
        engine._balance = 50000.0
        pos = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=55000.0,
            unrealized_pnl=5000.0
        )
        engine._positions["BTC/USD"] = pos
        
        engine._update_equity()
        
        assert engine._equity == 55000.0  # 50000 + 5000

    def test_update_equity_with_loss(self, engine):
        """Test equity with losing positions."""
        engine._balance = 50000.0
        pos = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=45000.0,
            unrealized_pnl=-5000.0
        )
        engine._positions["BTC/USD"] = pos
        
        engine._update_equity()
        
        assert engine._equity == 45000.0  # 50000 - 5000


class TestPositionMonitorLoop:
    """Test _position_monitor_loop method."""

    @pytest.mark.asyncio
    async def test_monitor_triggers_stop_loss(self, engine):
        """Test monitor triggers stop loss."""
        pos = Position(
            position_id="pos_001",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        engine._positions["BTC/USD"] = pos
        engine._price_cache["BTC/USD"] = 47000.0  # Below stop loss
        engine._running = True
        
        with patch.object(engine, 'close_position', new_callable=AsyncMock) as mock_close:
            # Run one iteration then stop
            async def run_once():
                engine._running = False
                
            asyncio.get_event_loop().call_later(0.1, lambda: setattr(engine, '_running', False))
            
            try:
                await asyncio.wait_for(engine._position_monitor_loop(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            
            mock_close.assert_called_with("BTC/USD", reason="stop_loss")

    @pytest.mark.asyncio
    async def test_monitor_triggers_take_profit(self, engine):
        """Test monitor triggers take profit."""
        pos = Position(
            position_id="pos_001",
            symbol="ETH/USD",
            side=PositionSide.LONG,
            quantity=5.0,
            entry_price=3000.0,
            current_price=3000.0,
            take_profit=3500.0
        )
        engine._positions["ETH/USD"] = pos
        engine._price_cache["ETH/USD"] = 3600.0  # Above take profit
        engine._running = True
        
        with patch.object(engine, 'close_position', new_callable=AsyncMock) as mock_close:
            asyncio.get_event_loop().call_later(0.1, lambda: setattr(engine, '_running', False))
            
            try:
                await asyncio.wait_for(engine._position_monitor_loop(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            
            mock_close.assert_called_with("ETH/USD", reason="take_profit")


class TestEmitEvent:
    """Test _emit_event method."""

    def test_emit_event_calls_callbacks(self, engine):
        """Test event emitted to all callbacks."""
        callback1 = MagicMock()
        callback2 = MagicMock()
        
        engine.register_event_callback(callback1)
        engine.register_event_callback(callback2)
        
        mock_event = MagicMock()
        engine._emit_event(mock_event)
        
        callback1.assert_called_once_with(mock_event)
        callback2.assert_called_once_with(mock_event)

    def test_emit_event_handles_callback_error(self, engine):
        """Test event emission handles callback errors."""
        callback1 = MagicMock(side_effect=Exception("Callback error"))
        callback2 = MagicMock()
        
        engine.register_event_callback(callback1)
        engine.register_event_callback(callback2)
        
        mock_event = MagicMock()
        # Should not raise, and second callback should still be called
        engine._emit_event(mock_event)
        
        callback1.assert_called_once()
        callback2.assert_called_once()


class TestHealExecutionEngine:
    """Test _heal_execution_engine method."""

    @pytest.mark.asyncio
    async def test_heal_restores_state(self, engine, mock_deps):
        """Test healing restores state from manager."""
        mock_deps['state_manager'].return_value.get_state = AsyncMock(
            return_value={"balance": 75000.0, "equity": 80000.0}
        )
        
        result = await engine._heal_execution_engine(Exception("Test error"))
        
        assert result is True
        assert engine._balance == 75000.0
        # Equity is recalculated based on balance + unrealized P&L (which is 0 with no positions)
        assert engine._equity == 75000.0

    @pytest.mark.asyncio
    async def test_heal_clears_stale_orders(self, engine):
        """Test healing clears stale orders."""
        # Create a stale order (older than 5 minutes)
        stale_order = Order(
            order_id="stale_001",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING,
            created_at=time.time() - 400  # 400 seconds ago
        )
        engine._orders["stale_001"] = stale_order
        
        result = await engine._heal_execution_engine(Exception("Test error"))
        
        assert result is True
        assert "stale_001" not in engine._orders

    @pytest.mark.asyncio
    async def test_heal_clears_invalid_positions(self, engine):
        """Test healing clears invalid positions."""
        invalid_pos = Position(
            position_id="invalid_001",
            symbol="INVALID/USD",
            side=PositionSide.LONG,
            quantity=0,  # Invalid: zero quantity
            entry_price=100.0,
            current_price=100.0
        )
        engine._positions["INVALID/USD"] = invalid_pos
        
        result = await engine._heal_execution_engine(Exception("Test error"))
        
        assert result is True
        assert "INVALID/USD" not in engine._positions

    @pytest.mark.asyncio
    async def test_heal_handles_error(self, engine, mock_deps):
        """Test healing handles errors gracefully."""
        mock_deps['state_manager'].return_value.get_state = AsyncMock(
            side_effect=Exception("State manager error")
        )
        
        result = await engine._heal_execution_engine(Exception("Test error"))
        
        assert result is False


class TestSingletons:
    """Test singleton functions."""

    def test_get_execution_engine(self, mock_deps):
        """Test get_execution_engine returns singleton."""
        exec_core._execution_engine = None
        
        engine1 = exec_core.get_execution_engine()
        engine2 = exec_core.get_execution_engine()
        
        assert engine1 is engine2
        
        # Cleanup
        exec_core._execution_engine = None

    @pytest.mark.asyncio
    async def test_start_execution_engine(self, mock_deps):
        """Test start_execution_engine creates and starts engine."""
        exec_core._execution_engine = None
        
        config = ExecutionConfig(max_position_size_usd=25000.0)
        engine = await exec_core.start_execution_engine(config)
        
        assert engine is not None
        assert engine._running is True
        assert engine.config.max_position_size_usd == 25000.0
        
        await exec_core.stop_execution_engine()
        exec_core._execution_engine = None

    @pytest.mark.asyncio
    async def test_stop_execution_engine(self, mock_deps):
        """Test stop_execution_engine stops engine."""
        exec_core._execution_engine = None
        
        engine = await exec_core.start_execution_engine()
        assert engine._running is True
        
        await exec_core.stop_execution_engine()
        assert engine._running is False
        
        exec_core._execution_engine = None


class TestSyncWithExchange:
    """Test sync_with_exchange method."""

    @pytest.mark.asyncio
    async def test_sync_skipped_in_paper_mode(self, engine):
        """Test sync is skipped in paper mode."""
        engine.config.mode = ExecutionMode.PAPER
        
        result = await engine.sync_with_exchange()
        
        assert result["status"] == "skipped"
        assert "Not in live mode" in result["reason"]

    @pytest.mark.asyncio
    async def test_sync_error_no_api_keys(self, engine):
        """Test sync fails without API keys."""
        engine.config.mode = ExecutionMode.LIVE
        engine.config.api_key = None
        engine.config.api_secret = None
        
        result = await engine.sync_with_exchange()
        
        assert result["status"] == "error"
        assert "No API keys" in result["reason"]

    @pytest.mark.asyncio
    async def test_sync_error_no_ccxt(self, engine):
        """Test sync fails without CCXT."""
        engine.config.mode = ExecutionMode.LIVE
        engine.config.api_key = "test_key"
        engine.config.api_secret = "test_secret"
        
        with patch('trading._execution_core.get_ccxt_async', return_value=None):
            result = await engine.sync_with_exchange()
        
        assert result["status"] == "error"
        assert "CCXT not installed" in result["reason"]
