"""Tests for trading/mode_controller.py."""
import pytest
import time
from unittest.mock import Mock
from trading.mode_controller import (
    TradingMode, TradeAction, SpectatorTrade, ModeChangeEvent,
    TradingModeController, get_trading_mode_controller
)


class TestTradingMode:
    """Test TradingMode enum."""

    def test_mode_values(self):
        """Test TradingMode enum values."""
        assert TradingMode.PAPER.value == "paper"
        assert TradingMode.LIVE.value == "live"
        assert TradingMode.HYBRID.value == "hybrid"
        assert TradingMode.AUTONOMOUS.value == "autonomous"


class TestTradeAction:
    """Test TradeAction enum."""

    def test_action_values(self):
        """Test TradeAction enum values."""
        assert TradeAction.BUY.value == "buy"
        assert TradeAction.SELL.value == "sell"
        assert TradeAction.LONG.value == "long"
        assert TradeAction.SHORT.value == "short"
        assert TradeAction.CLOSE.value == "close"


class TestSpectatorTrade:
    """Test SpectatorTrade dataclass."""

    def test_creation(self):
        """Test SpectatorTrade creation."""
        trade = SpectatorTrade(
            trade_id="t1",
            agent_id="a1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            timestamp=time.time(),
            mode="paper"
        )
        assert trade.trade_id == "t1"
        assert trade.symbol == "BTC/USDT"
        assert trade.status == "open"

    def test_to_dict(self):
        """Test SpectatorTrade to_dict."""
        trade = SpectatorTrade(
            trade_id="t1", agent_id="a1", symbol="BTC/USDT",
            action="buy", quantity=1.0, price=50000.0,
            timestamp=1234567890.0, mode="paper"
        )
        d = trade.to_dict()
        assert d["trade_id"] == "t1"
        assert d["symbol"] == "BTC/USDT"


class TestModeChangeEvent:
    """Test ModeChangeEvent dataclass."""

    def test_to_dict(self):
        """Test ModeChangeEvent to_dict."""
        event = ModeChangeEvent(
            event_id="e1",
            old_mode="paper",
            new_mode="live",
            changed_by="user",
            timestamp=1234567890.0,
            reason="testing"
        )
        d = event.to_dict()
        assert d["old_mode"] == "paper"
        assert d["new_mode"] == "live"


class TestTradingModeController:
    """Test TradingModeController class."""

    def test_initialization(self):
        """Test controller initialization."""
        controller = TradingModeController()
        assert controller.mode == TradingMode.PAPER
        assert controller.is_paper is True
        assert controller.is_live is False

    def test_mode_properties(self):
        """Test mode property methods."""
        controller = TradingModeController()
        
        controller.set_mode("live")
        assert controller.is_live is True
        assert controller.mode_name == "live"
        
        controller.set_mode("hybrid")
        assert controller.is_hybrid is True
        
        controller.set_mode("autonomous")
        assert controller.is_autonomous is True

    def test_set_mode_valid(self):
        """Test setting valid mode."""
        controller = TradingModeController()
        result = controller.set_mode("live", changed_by="test", reason="testing")
        assert result is True
        assert controller.mode == TradingMode.LIVE

    def test_set_mode_invalid(self):
        """Test setting invalid mode returns False."""
        controller = TradingModeController()
        result = controller.set_mode("invalid")
        assert result is False
        assert controller.mode == TradingMode.PAPER

    def test_mode_change_history(self):
        """Test mode change is recorded in history."""
        controller = TradingModeController()
        controller.set_mode("live", changed_by="test")
        history = controller.get_mode_history()
        assert len(history) == 1
        assert history[0].new_mode == "live"


class TestCanExecuteLive:
    """Test can_execute_live method."""

    def test_paper_mode_blocks(self):
        """Test paper mode blocks live execution."""
        controller = TradingModeController()
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "Paper mode" in reason

    def test_hybrid_mode_requires_approval(self):
        """Test hybrid mode requires approval."""
        controller = TradingModeController()
        controller.set_mode("hybrid")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        assert can_execute is False
        assert "manual approval" in reason

    def test_autonomous_symbol_not_allowed(self):
        """Test autonomous mode blocks non-allowed symbols."""
        controller = TradingModeController()
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("XYZ/USDT", 100.0)
        assert can_execute is False
        assert "not in autonomous allowlist" in reason

    def test_autonomous_position_too_large(self):
        """Test autonomous mode blocks large positions."""
        controller = TradingModeController()
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 5000.0)
        assert can_execute is False
        assert "exceeds max" in reason

    def test_autonomous_allows_valid(self):
        """Test autonomous mode allows valid trades."""
        controller = TradingModeController()
        controller.set_mode("autonomous")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 500.0)
        assert can_execute is True


class TestRecordAndCloseTrade:
    """Test record_trade and close_trade methods."""

    def test_record_trade(self):
        """Test recording a trade."""
        controller = TradingModeController()
        trade = controller.record_trade(
            agent_id="a1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0
        )
        assert trade.agent_id == "a1"
        assert trade.symbol == "BTC/USDT"
        assert trade.status == "open"

    def test_close_trade(self):
        """Test closing a trade."""
        controller = TradingModeController()
        trade = controller.record_trade(
            agent_id="a1", symbol="BTC/USDT",
            action="buy", quantity=1.0, price=50000.0,
            trade_id="t1"
        )
        closed = controller.close_trade("t1", exit_price=51000.0, pnl=1000.0)
        assert closed is not None
        assert closed.status == "closed"
        assert closed.pnl == 1000.0

    def test_close_nonexistent_trade(self):
        """Test closing nonexistent trade returns None."""
        controller = TradingModeController()
        result = controller.close_trade("nonexistent", 50000.0, 0.0)
        assert result is None


class TestGetSpectatorTrades:
    """Test get_spectator_trades method."""

    def test_filter_by_agent(self):
        """Test filtering trades by agent."""
        controller = TradingModeController()
        controller.record_trade("a1", "BTC/USDT", "buy", 1.0, 50000.0)
        controller.record_trade("a2", "ETH/USDT", "buy", 2.0, 3000.0)
        
        trades = controller.get_spectator_trades(agent_id="a1")
        assert len(trades) == 1
        assert trades[0].agent_id == "a1"

    def test_filter_by_symbol(self):
        """Test filtering trades by symbol."""
        controller = TradingModeController()
        controller.record_trade("a1", "BTC/USDT", "buy", 1.0, 50000.0)
        controller.record_trade("a1", "ETH/USDT", "buy", 2.0, 3000.0)
        
        trades = controller.get_spectator_trades(symbol="BTC/USDT")
        assert len(trades) == 1
        assert trades[0].symbol == "BTC/USDT"


class TestSubscriber:
    """Test subscriber functionality."""

    def test_subscribe_and_callback(self):
        """Test subscriber is called on mode change."""
        controller = TradingModeController()
        callback = Mock()
        controller.subscribe(callback)
        
        controller.set_mode("live")
        callback.assert_called_once()

    def test_unsubscribe(self):
        """Test unsubscribing removes callback."""
        controller = TradingModeController()
        callback = Mock()
        controller.subscribe(callback)
        controller.unsubscribe(callback)
        
        controller.set_mode("live")
        callback.assert_not_called()


class TestGetStatus:
    """Test get_status method."""

    def test_status_contains_required_fields(self):
        """Test status contains all required fields."""
        controller = TradingModeController()
        status = controller.get_status()
        assert "mode" in status
        assert "is_paper" in status
        assert "is_live" in status
        assert "autonomous_limits" in status
        assert "daily_stats" in status


class TestGetTradingModeController:
    """Test get_trading_mode_controller singleton."""

    def test_singleton(self):
        """Test get_trading_mode_controller returns singleton."""
        c1 = get_trading_mode_controller()
        c2 = get_trading_mode_controller()
        assert c1 is c2
