"""Comprehensive tests for trading/execution.py - Core coverage."""
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
    _is_abort_action,
    _is_high_threat,
)
from trading.execution.defense import DefenseAction, ThreatLevel


class TestEnums:
    """Test enum definitions."""

    def test_execution_mode_values(self):
        """Test ExecutionMode enum values."""
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"
        assert ExecutionMode.DISABLED.value == "disabled"

    def test_order_side_values(self):
        """Test OrderSide enum values."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_type_values(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"

    def test_order_status_values(self):
        """Test OrderStatus enum values."""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.EXPIRED.value == "expired"

    def test_position_side_values(self):
        """Test PositionSide enum values."""
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.FLAT.value == "flat"


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_abort_action_true(self):
        """Test _is_abort_action returns True for ABORT."""
        assert _is_abort_action(DefenseAction.ABORT) is True

    def test_is_abort_action_false(self):
        """Test _is_abort_action returns False for non-ABORT."""
        assert _is_abort_action(DefenseAction.PROCEED) is False
        assert _is_abort_action(DefenseAction.DELAY) is False
        assert _is_abort_action(DefenseAction.SLICE) is False

    def test_is_high_threat_true(self):
        """Test _is_high_threat returns True for HIGH/CRITICAL."""
        assert _is_high_threat(ThreatLevel.HIGH) is True
        assert _is_high_threat(ThreatLevel.CRITICAL) is True

    def test_is_high_threat_false(self):
        """Test _is_high_threat returns False for lower threats."""
        assert _is_high_threat(ThreatLevel.NONE) is False
        assert _is_high_threat(ThreatLevel.LOW) is False
        assert _is_high_threat(ThreatLevel.MEDIUM) is False


class TestOrder:
    """Test Order dataclass."""

    def test_order_creation(self):
        """Test creating an order."""
        order = Order(
            order_id="order_123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        assert order.order_id == "order_123"
        assert order.symbol == "BTC/USD"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0.0

    def test_order_with_price(self):
        """Test creating a limit order with price."""
        order = Order(
            order_id="order_456",
            symbol="ETH/USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=5.0,
            price=3000.0
        )
        assert order.price == 3000.0
        assert order.order_type == OrderType.LIMIT

    def test_order_is_complete_filled(self):
        """Test is_complete for filled order."""
        order = Order(
            order_id="order_789",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.FILLED
        )
        assert order.is_complete() is True

    def test_order_is_complete_cancelled(self):
        """Test is_complete for cancelled order."""
        order = Order(
            order_id="order_101",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.CANCELLED
        )
        assert order.is_complete() is True

    def test_order_is_complete_rejected(self):
        """Test is_complete for rejected order."""
        order = Order(
            order_id="order_102",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.REJECTED
        )
        assert order.is_complete() is True

    def test_order_is_complete_pending(self):
        """Test is_complete for pending order."""
        order = Order(
            order_id="order_103",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING
        )
        assert order.is_complete() is False

    def test_order_is_complete_partial(self):
        """Test is_complete for partial order."""
        order = Order(
            order_id="order_104",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PARTIAL
        )
        assert order.is_complete() is False


class TestPosition:
    """Test Position dataclass."""

    def test_position_creation(self):
        """Test creating a position."""
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.position_id == "pos_123"
        assert position.symbol == "BTC/USD"
        assert position.side == PositionSide.LONG
        assert position.unrealized_pnl == 0.0

    def test_position_update_pnl_long_profit(self):
        """Test P&L update for long position with profit."""
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        assert position.unrealized_pnl == 1000.0  # (51000 - 50000) * 1

    def test_position_update_pnl_long_loss(self):
        """Test P&L update for long position with loss."""
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=2.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(49000.0)
        assert position.unrealized_pnl == -2000.0  # (49000 - 50000) * 2

    def test_position_update_pnl_short_profit(self):
        """Test P&L update for short position with profit."""
        position = Position(
            position_id="pos_456",
            symbol="BTC/USD",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(49000.0)
        assert position.unrealized_pnl == 1000.0  # (50000 - 49000) * 1

    def test_position_update_pnl_short_loss(self):
        """Test P&L update for short position with loss."""
        position = Position(
            position_id="pos_456",
            symbol="BTC/USD",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        assert position.unrealized_pnl == -1000.0  # (50000 - 51000) * 1

    def test_position_update_pnl_flat(self):
        """Test P&L update for flat position."""
        position = Position(
            position_id="pos_789",
            symbol="BTC/USD",
            side=PositionSide.FLAT,
            quantity=0.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        assert position.unrealized_pnl == 0.0

    def test_position_check_stop_loss_long_triggered(self):
        """Test stop loss triggered for long position."""
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        assert position.check_stop_loss(47000.0) is True
        assert position.check_stop_loss(48000.0) is True
        assert position.check_stop_loss(49000.0) is False

    def test_position_check_stop_loss_short_triggered(self):
        """Test stop loss triggered for short position."""
        position = Position(
            position_id="pos_456",
            symbol="BTC/USD",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=52000.0
        )
        assert position.check_stop_loss(53000.0) is True
        assert position.check_stop_loss(52000.0) is True
        assert position.check_stop_loss(51000.0) is False

    def test_position_check_stop_loss_no_stop(self):
        """Test stop loss check when not set."""
        position = Position(
            position_id="pos_789",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.check_stop_loss(10000.0) is False

    def test_position_check_take_profit_long_triggered(self):
        """Test take profit triggered for long position."""
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        assert position.check_take_profit(56000.0) is True
        assert position.check_take_profit(55000.0) is True
        assert position.check_take_profit(54000.0) is False

    def test_position_check_take_profit_short_triggered(self):
        """Test take profit triggered for short position."""
        position = Position(
            position_id="pos_456",
            symbol="BTC/USD",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=45000.0
        )
        assert position.check_take_profit(44000.0) is True
        assert position.check_take_profit(45000.0) is True
        assert position.check_take_profit(46000.0) is False

    def test_position_check_take_profit_no_tp(self):
        """Test take profit check when not set."""
        position = Position(
            position_id="pos_789",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.check_take_profit(100000.0) is False


class TestExecutionConfig:
    """Test ExecutionConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ExecutionConfig()
        assert config.mode == ExecutionMode.PAPER
        assert config.exchange == "coinbase"
        assert config.sandbox is True
        assert config.max_position_size_usd == 10000.0
        assert config.max_total_exposure_usd == 50000.0
        assert config.require_consensus is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = ExecutionConfig(
            mode=ExecutionMode.LIVE,
            exchange="binance",
            api_key="test_key",
            api_secret="test_secret",
            sandbox=False,
            max_position_size_usd=50000.0
        )
        assert config.mode == ExecutionMode.LIVE
        assert config.exchange == "binance"
        assert config.api_key == "test_key"
        assert config.sandbox is False


class TestExceptions:
    """Test custom exceptions."""

    def test_execution_error(self):
        """Test ExecutionError exception."""
        with pytest.raises(ExecutionError):
            raise ExecutionError("Test error")

    def test_insufficient_funds_error(self):
        """Test InsufficientFundsError exception."""
        with pytest.raises(InsufficientFundsError):
            raise InsufficientFundsError("Not enough funds")

    def test_position_limit_error(self):
        """Test PositionLimitError exception."""
        with pytest.raises(PositionLimitError):
            raise PositionLimitError("Position limit exceeded")

    def test_order_rejected_error(self):
        """Test OrderRejectedError exception."""
        with pytest.raises(OrderRejectedError):
            raise OrderRejectedError("Order rejected")


class TestExecutionEngine:
    """Test ExecutionEngine class."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock external dependencies."""
        with patch('trading._execution_core.get_error_handler') as mock_eh, \
             patch('trading._execution_core.get_state_manager') as mock_sm, \
             patch('trading._execution_core.get_self_healing') as mock_sh, \
             patch('trading._execution_core.get_health_monitor') as mock_hm:
            
            mock_eh.return_value = MagicMock()
            mock_eh.return_value.register_circuit_breaker.return_value = MagicMock()
            
            mock_sm.return_value = MagicMock()
            mock_sm.return_value.initialize = AsyncMock()
            mock_sm.return_value.start_auto_save = AsyncMock()
            mock_sm.return_value.stop_auto_save = AsyncMock()
            mock_sm.return_value.get_state = AsyncMock(return_value=None)
            mock_sm.return_value.update_state = AsyncMock()
            
            mock_sh.return_value = MagicMock()
            
            mock_hm.return_value = MagicMock()
            mock_hm.return_value.register_health_check.return_value = MagicMock()
            mock_hm.return_value.start_monitoring = AsyncMock()
            mock_hm.return_value.stop_monitoring = AsyncMock()
            
            yield {
                'error_handler': mock_eh,
                'state_manager': mock_sm,
                'self_healing': mock_sh,
                'health_monitor': mock_hm,
            }

    def test_engine_initialization(self, mock_dependencies):
        """Test engine initializes correctly."""
        engine = ExecutionEngine()
        assert engine.config.mode == ExecutionMode.PAPER
        assert engine._balance == 100000.0
        assert engine._running is False

    def test_engine_with_custom_config(self, mock_dependencies):
        """Test engine with custom config."""
        config = ExecutionConfig(
            mode=ExecutionMode.PAPER,
            max_position_size_usd=25000.0
        )
        engine = ExecutionEngine(config=config)
        assert engine.config.max_position_size_usd == 25000.0

    def test_set_reality_auditor(self, mock_dependencies):
        """Test setting reality auditor."""
        engine = ExecutionEngine()
        mock_auditor = MagicMock()
        engine.set_reality_auditor(mock_auditor)
        assert engine._reality_auditor == mock_auditor

    def test_set_mev_defender(self, mock_dependencies):
        """Test setting MEV defender."""
        engine = ExecutionEngine()
        mock_defender = MagicMock()
        engine.set_mev_defender(mock_defender)
        assert engine._mev_defender == mock_defender

    def test_resolve_execution_mode_paper(self, mock_dependencies):
        """Test mode resolution for paper mode."""
        config = ExecutionConfig(mode=ExecutionMode.PAPER)
        engine = ExecutionEngine(config=config)
        assert engine._resolve_execution_mode() == ExecutionMode.PAPER

    def test_resolve_execution_mode_live_no_creds(self, mock_dependencies):
        """Test mode resolution for live without credentials."""
        config = ExecutionConfig(mode=ExecutionMode.LIVE)
        engine = ExecutionEngine(config=config)
        # Should fall back to PAPER without credentials
        assert engine._resolve_execution_mode() == ExecutionMode.PAPER

    def test_resolve_execution_mode_live_with_creds(self, mock_dependencies):
        """Test mode resolution for live with credentials."""
        config = ExecutionConfig(
            mode=ExecutionMode.LIVE,
            api_key="key",
            api_secret="secret"
        )
        engine = ExecutionEngine(config=config)
        assert engine._resolve_execution_mode() == ExecutionMode.LIVE

    def test_update_price(self, mock_dependencies):
        """Test price update."""
        engine = ExecutionEngine()
        engine.update_price("BTC/USD", 50000.0)
        assert engine._price_cache["BTC/USD"] == 50000.0

    def test_update_price_with_position(self, mock_dependencies):
        """Test price update updates position P&L."""
        engine = ExecutionEngine()
        
        # Add a position
        position = Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        engine._positions["BTC/USD"] = position
        
        engine.update_price("BTC/USD", 51000.0)
        
        assert position.current_price == 51000.0
        assert position.unrealized_pnl == 1000.0

    @pytest.mark.asyncio
    async def test_start_and_stop(self, mock_dependencies):
        """Test engine start and stop."""
        engine = ExecutionEngine()
        
        await engine.start()
        assert engine._running is True
        
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_submit_order_disabled_mode(self, mock_dependencies):
        """Test submitting order when execution is disabled."""
        config = ExecutionConfig(mode=ExecutionMode.DISABLED)
        engine = ExecutionEngine(config=config)
        
        with pytest.raises(ExecutionError, match="disabled"):
            await engine.submit_order(
                symbol="BTC/USD",
                side=OrderSide.BUY,
                quantity=1.0
            )

    @pytest.mark.asyncio
    async def test_submit_order_basic(self, mock_dependencies):
        """Test basic order submission."""
        engine = ExecutionEngine()
        engine._reality_auditor = None
        engine._mev_defender = None
        
        with patch('trading._execution_core.record_trading_tick') as mock_tick:
            mock_tick.return_value.__enter__ = MagicMock()
            mock_tick.return_value.__exit__ = MagicMock()
            
            order = await engine.submit_order(
                symbol="BTC/USD",
                side=OrderSide.BUY,
                quantity=1.0
            )
        
        assert order.symbol == "BTC/USD"
        assert order.side == OrderSide.BUY
        assert order.quantity == 1.0
