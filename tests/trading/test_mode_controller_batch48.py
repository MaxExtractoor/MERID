"""Tests for trading mode_controller module - Batch 48 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time

from trading.mode_controller import (
    TradingMode,
    TradeAction,
    SpectatorTrade,
    ModeChangeEvent,
    TradingModeController,
    get_trading_mode_controller,
)


class TestTradingMode:
    """Tests for TradingMode enum."""

    def test_mode_values(self):
        assert TradingMode.PAPER.value == "paper"
        assert TradingMode.LIVE.value == "live"
        assert TradingMode.HYBRID.value == "hybrid"
        assert TradingMode.AUTONOMOUS.value == "autonomous"


class TestTradeAction:
    """Tests for TradeAction enum."""

    def test_action_values(self):
        assert TradeAction.BUY.value == "buy"
        assert TradeAction.SELL.value == "sell"
        assert TradeAction.LONG.value == "long"
        assert TradeAction.SHORT.value == "short"
        assert TradeAction.CLOSE.value == "close"


class TestSpectatorTrade:
    """Tests for SpectatorTrade dataclass."""

    def test_trade_creation(self):
        trade = SpectatorTrade(
            trade_id="trade_123",
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            timestamp=time.time(),
            mode="paper",
        )
        assert trade.trade_id == "trade_123"
        assert trade.agent_id == "agent_1"
        assert trade.status == "open"
        assert trade.pnl == 0.0

    def test_trade_to_dict(self):
        trade = SpectatorTrade(
            trade_id="trade_123",
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            timestamp=1234567890.0,
            mode="paper",
        )
        result = trade.to_dict()
        assert result["trade_id"] == "trade_123"
        assert result["symbol"] == "BTC/USDT"


class TestModeChangeEvent:
    """Tests for ModeChangeEvent dataclass."""

    def test_event_creation(self):
        event = ModeChangeEvent(
            event_id="event_123",
            old_mode="paper",
            new_mode="live",
            changed_by="user",
            timestamp=time.time(),
            reason="Testing",
        )
        assert event.event_id == "event_123"
        assert event.old_mode == "paper"
        assert event.new_mode == "live"

    def test_event_to_dict(self):
        event = ModeChangeEvent(
            event_id="event_123",
            old_mode="paper",
            new_mode="live",
            changed_by="user",
            timestamp=1234567890.0,
        )
        result = event.to_dict()
        assert result["old_mode"] == "paper"
        assert result["new_mode"] == "live"


class TestTradingModeController:
    """Tests for TradingModeController class."""

    @pytest.fixture
    def controller(self):
        return TradingModeController()

    def test_initialization(self, controller):
        assert controller.mode == TradingMode.PAPER
        assert controller.mode_name == "paper"
        assert controller.is_paper is True
        assert controller.is_live is False
        assert controller.is_hybrid is False
        assert controller.is_autonomous is False

    def test_set_mode_success(self, controller):
        """Test successful mode change."""
        result = controller.set_mode("live", changed_by="test_user", reason="Testing live mode")
        
        assert result is True
        assert controller.mode == TradingMode.LIVE
        assert controller.is_live is True
        assert len(controller.get_mode_history()) == 1

    def test_set_mode_invalid(self, controller):
        """Test setting invalid mode."""
        result = controller.set_mode("invalid_mode")
        
        assert result is False
        assert controller.mode == TradingMode.PAPER  # Unchanged

    def test_set_mode_callback_error(self, controller):
        """Test mode change with callback that raises exception."""
        # Subscribe a callback that will raise an exception
        def bad_callback(event):
            raise Exception("Callback error")
        
        controller.subscribe(bad_callback)
        
        # Should not raise, just log error
        result = controller.set_mode("live")
        assert result is True

    def test_can_execute_live_paper_mode(self, controller):
        """Test live execution in paper mode."""
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "Paper mode" in reason

    def test_can_execute_live_hybrid_mode(self, controller):
        """Test live execution in hybrid mode."""
        controller.set_mode("hybrid")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "manual approval" in reason

    def test_can_execute_live_autonomous_symbol_not_allowed(self, controller):
        """Test autonomous mode with non-allowed symbol."""
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("UNKNOWN", 1000.0)
        assert can_execute is False
        assert "not in autonomous allowlist" in reason

    def test_can_execute_live_autonomous_position_too_large(self, controller):
        """Test autonomous mode with position exceeding limit."""
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 5000.0)
        assert can_execute is False
        assert "exceeds max" in reason

    def test_can_execute_live_autonomous_daily_trade_limit(self, controller):
        """Test autonomous mode with daily trade limit reached."""
        controller.set_mode("autonomous")
        controller._daily_stats["trades"] = 50  # At limit
        can_execute, reason = controller.can_execute_live("BTC/USDT", 100.0)
        assert can_execute is False
        assert "Daily trade limit" in reason

    def test_can_execute_live_autonomous_daily_volume_limit(self, controller):
        """Test autonomous mode with daily volume limit."""
        controller.set_mode("autonomous")
        controller._daily_stats["volume_usd"] = 9500.0
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "volume limit" in reason

    def test_can_execute_live_autonomous_daily_reset(self, controller):
        """Test autonomous mode daily stats reset after 24 hours."""
        controller.set_mode("autonomous")
        controller._daily_stats["last_reset"] = time.time() - 90000  # More than 24 hours
        controller._daily_stats["trades"] = 100  # Would normally block
        
        can_execute, reason = controller.can_execute_live("BTC/USDT", 100.0)
        assert can_execute is True
        assert controller._daily_stats["trades"] == 0  # Reset

    def test_record_trade(self, controller):
        """Test recording a trade."""
        trade = controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=0.1,
            price=50000.0,
            strategy="test_strategy",
            confidence=0.8,
            reasoning="Test trade",
        )
        
        assert trade.agent_id == "agent_1"
        assert trade.symbol == "BTC/USDT"
        assert trade.strategy == "test_strategy"
        assert controller._daily_stats["trades"] == 1

    def test_close_trade(self, controller):
        """Test closing a trade."""
        # First record a trade
        trade = controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=0.1,
            price=50000.0,
        )
        
        # Close it
        closed = controller.close_trade(trade.trade_id, 51000.0, 100.0)
        
        assert closed is not None
        assert closed.status == "closed"
        assert closed.exit_price == 51000.0
        assert closed.pnl == 100.0

    def test_close_trade_not_found(self, controller):
        """Test closing non-existent trade."""
        result = controller.close_trade("non_existent", 50000.0, 0.0)
        assert result is None

    def test_get_spectator_trades_with_filters(self, controller):
        """Test getting trades with filters."""
        # Record some trades
        controller.record_trade(agent_id="agent_1", symbol="BTC/USDT", action="buy", quantity=0.1, price=50000.0)
        controller.record_trade(agent_id="agent_2", symbol="ETH/USDT", action="sell", quantity=1.0, price=3000.0)
        
        # Filter by agent
        trades = controller.get_spectator_trades(agent_id="agent_1")
        assert len(trades) == 1
        assert trades[0].agent_id == "agent_1"
        
        # Filter by symbol
        trades = controller.get_spectator_trades(symbol="ETH/USDT")
        assert len(trades) == 1
        assert trades[0].symbol == "ETH/USDT"

    def test_get_spectator_trades_with_status_filter(self, controller):
        """Test getting trades with status filter."""
        trade = controller.record_trade(agent_id="agent_1", symbol="BTC/USDT", action="buy", quantity=0.1, price=50000.0)
        controller.close_trade(trade.trade_id, 51000.0, 100.0)
        
        # Get closed trades
        trades = controller.get_spectator_trades(status="closed")
        assert len(trades) == 1
        assert trades[0].status == "closed"

    def test_get_status(self, controller):
        """Test getting controller status."""
        status = controller.get_status()
        
        assert status["mode"] == "paper"
        assert status["is_paper"] is True
        assert "autonomous_limits" in status
        assert "daily_stats" in status

    def test_set_autonomous_limits(self, controller):
        """Test updating autonomous limits."""
        controller.set_autonomous_limits({"max_position_usd": 2000.0})
        
        assert controller._autonomous_limits["max_position_usd"] == 2000.0

    def test_subscribe_unsubscribe(self, controller):
        """Test subscribe and unsubscribe functionality."""
        def callback(event):
            pass
        
        controller.subscribe(callback)
        assert callback in controller._subscribers
        
        controller.unsubscribe(callback)
        assert callback not in controller._subscribers

    def test_unsubscribe_not_in_list(self, controller):
        """Test unsubscribing a callback that wasn't subscribed."""
        def callback(event):
            pass
        
        # Should not raise
        controller.unsubscribe(callback)


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_trading_mode_controller(self):
        # Reset singleton
        import trading.mode_controller as mc_module
        mc_module._controller = None
        
        controller1 = get_trading_mode_controller()
        controller2 = get_trading_mode_controller()
        
        assert controller1 is controller2
