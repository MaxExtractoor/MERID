"""Tests for trading mode controller - Batch 22 Coverage."""
import pytest
from unittest.mock import patch
import time

from trading.mode_controller import (
    TradingMode,
    TradeAction,
    SpectatorTrade,
    ModeChangeEvent,
    TradingModeController,
    get_trading_mode_controller
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
            agent_id="agent_456",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=45000.0,
            timestamp=time.time(),
            mode="paper"
        )
        assert trade.trade_id == "trade_123"
        assert trade.status == "open"
        assert trade.pnl == 0.0

    def test_trade_to_dict(self):
        trade = SpectatorTrade(
            trade_id="trade_123",
            agent_id="agent_456",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=45000.0,
            timestamp=1234567890.0,
            mode="paper"
        )
        d = trade.to_dict()
        assert d["trade_id"] == "trade_123"
        assert d["symbol"] == "BTC/USDT"


class TestModeChangeEvent:
    """Tests for ModeChangeEvent dataclass."""

    def test_event_creation(self):
        event = ModeChangeEvent(
            event_id="event_123",
            old_mode="paper",
            new_mode="live",
            changed_by="user",
            timestamp=time.time(),
            reason="Testing live mode"
        )
        assert event.old_mode == "paper"
        assert event.new_mode == "live"


class TestTradingModeController:
    """Tests for TradingModeController."""

    @pytest.fixture
    def controller(self):
        """Create fresh controller."""
        return TradingModeController()

    def test_initialization(self, controller):
        """Test controller initialization."""
        assert controller.mode == TradingMode.PAPER
        assert controller.is_paper is True
        assert controller.is_live is False

    def test_mode_properties(self, controller):
        """Test mode property getters."""
        assert controller.mode_name == "paper"
        assert controller.is_hybrid is False
        assert controller.is_autonomous is False

    def test_set_mode_valid(self, controller):
        """Test setting valid mode."""
        result = controller.set_mode("live", changed_by="test_user", reason="Testing")
        assert result is True
        assert controller.mode == TradingMode.LIVE
        assert len(controller._mode_history) == 1

    def test_set_mode_invalid(self, controller):
        """Test setting invalid mode."""
        result = controller.set_mode("invalid_mode")
        assert result is False
        assert controller.mode == TradingMode.PAPER  # Unchanged

    def test_set_mode_case_insensitive(self, controller):
        """Test mode setting is case insensitive."""
        result = controller.set_mode("LIVE")
        assert result is True
        assert controller.mode == TradingMode.LIVE

    def test_mode_change_event(self, controller):
        """Test mode change event is recorded."""
        controller.set_mode("hybrid", changed_by="user", reason="Switch to hybrid")
        
        history = controller.get_mode_history()
        assert len(history) == 1
        assert history[0].old_mode == "paper"
        assert history[0].new_mode == "hybrid"

    def test_can_execute_live_paper_mode(self, controller):
        """Test live execution blocked in paper mode."""
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "paper" in reason.lower()

    def test_can_execute_live_mode(self, controller):
        """Test live execution allowed in live mode."""
        controller.set_mode("live")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is True

    def test_can_execute_hybrid_mode_requires_approval(self, controller):
        """Test hybrid mode requires approval."""
        controller.set_mode("hybrid")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "approval" in reason.lower()

    def test_can_execute_autonomous_symbol_not_allowed(self, controller):
        """Test autonomous mode with disallowed symbol."""
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("XRP/USDT", 1000.0)
        assert can_execute is False
        assert "allowlist" in reason.lower()

    def test_can_execute_autonomous_position_too_large(self, controller):
        """Test autonomous mode with position exceeding limit."""
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 5000.0)
        assert can_execute is False
        assert "exceeds" in reason.lower()

    def test_record_trade(self, controller):
        """Test recording a trade."""
        trade = controller.record_trade(
            agent_id="agent_123",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=45000.0,
            strategy="test_strategy",
            confidence=0.85
        )
        
        assert trade.agent_id == "agent_123"
        assert trade.symbol == "BTC/USDT"
        assert len(controller._spectator_trades) == 1

    def test_record_trade_updates_stats(self, controller):
        """Test recording trade updates daily stats."""
        controller.record_trade(
            agent_id="agent_123",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=45000.0
        )
        
        assert controller._daily_stats["trades"] == 1
        assert controller._daily_stats["volume_usd"] == 45000.0

    def test_close_trade(self, controller):
        """Test closing a trade."""
        trade = controller.record_trade(
            agent_id="agent_123",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=45000.0
        )
        
        closed = controller.close_trade(trade.trade_id, exit_price=46000.0, pnl=1000.0)
        
        assert closed is not None
        assert closed.status == "closed"
        assert closed.pnl == 1000.0
        assert closed.exit_price == 46000.0

    def test_close_trade_not_found(self, controller):
        """Test closing non-existent trade."""
        result = controller.close_trade("non_existent", 46000.0, 1000.0)
        assert result is None

    def test_get_spectator_trades(self, controller):
        """Test getting spectator trades."""
        controller.record_trade("agent_1", "BTC/USDT", "buy", 1.0, 45000.0)
        controller.record_trade("agent_2", "ETH/USDT", "buy", 2.0, 3000.0)
        
        trades = controller.get_spectator_trades(limit=10)
        assert len(trades) == 2

    def test_get_spectator_trades_filter_agent(self, controller):
        """Test filtering trades by agent."""
        controller.record_trade("agent_1", "BTC/USDT", "buy", 1.0, 45000.0)
        controller.record_trade("agent_2", "ETH/USDT", "buy", 2.0, 3000.0)
        
        trades = controller.get_spectator_trades(agent_id="agent_1")
        assert len(trades) == 1
        assert trades[0].agent_id == "agent_1"

    def test_get_spectator_trades_filter_symbol(self, controller):
        """Test filtering trades by symbol."""
        controller.record_trade("agent_1", "BTC/USDT", "buy", 1.0, 45000.0)
        controller.record_trade("agent_1", "ETH/USDT", "buy", 2.0, 3000.0)
        
        trades = controller.get_spectator_trades(symbol="BTC/USDT")
        assert len(trades) == 1
        assert trades[0].symbol == "BTC/USDT"

    def test_get_status(self, controller):
        """Test getting controller status."""
        status = controller.get_status()
        
        assert "mode" in status
        assert "is_paper" in status
        assert "is_live" in status
        assert "autonomous_limits" in status
        assert "daily_stats" in status

    def test_set_autonomous_limits(self, controller):
        """Test setting autonomous limits."""
        controller.set_autonomous_limits({"max_position_usd": 2000.0})
        
        assert controller._autonomous_limits["max_position_usd"] == 2000.0

    def test_subscribe_unsubscribe(self, controller):
        """Test subscribing and unsubscribing."""
        callback = lambda x: None
        
        controller.subscribe(callback)
        assert callback in controller._subscribers
        
        controller.unsubscribe(callback)
        assert callback not in controller._subscribers

    def test_mode_change_notification(self, controller):
        """Test mode change notifications."""
        notifications = []
        
        def callback(event):
            notifications.append(event)
        
        controller.subscribe(callback)
        controller.set_mode("live")
        
        assert len(notifications) == 1
        assert notifications[0].new_mode == "live"


class TestGetTradingModeController:
    """Tests for singleton."""

    def test_singleton(self):
        """Test singleton pattern."""
        # Reset singleton for test
        import trading.mode_controller as mode_module
        mode_module._controller = None
        
        ctrl1 = get_trading_mode_controller()
        ctrl2 = get_trading_mode_controller()
        
        assert ctrl1 is ctrl2
