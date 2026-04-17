"""Comprehensive tests for trading/mode_controller.py - Coverage improvement."""

import pytest
import time
from unittest.mock import MagicMock, patch

from trading.mode_controller import (
    TradingMode, TradeAction, SpectatorTrade, ModeChangeEvent,
    TradingModeController, get_trading_mode_controller
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestTradingMode:
    """Test TradingMode enum."""

    def test_paper_mode(self):
        assert TradingMode.PAPER.value == "paper"

    def test_live_mode(self):
        assert TradingMode.LIVE.value == "live"

    def test_mock_mode(self):
        assert TradingMode.MOCK.value == "mock"


class TestTradeAction:
    """Test TradeAction enum."""

    def test_buy_action(self):
        assert TradeAction.BUY.value == "buy"

    def test_sell_action(self):
        assert TradeAction.SELL.value == "sell"

    def test_long_action(self):
        assert TradeAction.LONG.value == "long"

    def test_short_action(self):
        assert TradeAction.SHORT.value == "short"

    def test_close_action(self):
        assert TradeAction.CLOSE.value == "close"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestSpectatorTrade:
    """Test SpectatorTrade dataclass."""

    def test_creation(self):
        trade = SpectatorTrade(
            trade_id="trade_1",
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            timestamp=time.time(),
            mode="paper"
        )
        assert trade.trade_id == "trade_1"
        assert trade.status == "open"
        assert trade.pnl == 0.0

    def test_to_dict(self):
        trade = SpectatorTrade(
            trade_id="trade_1",
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            timestamp=time.time(),
            mode="paper"
        )
        data = trade.to_dict()
        assert data["trade_id"] == "trade_1"
        assert "timestamp" in data


class TestModeChangeEvent:
    """Test ModeChangeEvent dataclass."""

    def test_creation(self):
        event = ModeChangeEvent(
            event_id="evt_1",
            old_mode="paper",
            new_mode="live",
            changed_by="admin",
            timestamp=time.time()
        )
        assert event.old_mode == "paper"
        assert event.new_mode == "live"

    def test_to_dict(self):
        event = ModeChangeEvent(
            event_id="evt_1",
            old_mode="paper",
            new_mode="live",
            changed_by="admin",
            timestamp=time.time(),
            reason="Testing"
        )
        data = event.to_dict()
        assert data["event_id"] == "evt_1"
        assert data["reason"] == "Testing"


# =============================================================================
# TradingModeController Tests
# =============================================================================

class TestTradingModeControllerInit:
    """Test TradingModeController initialization."""

    @pytest.fixture(autouse=True)
    def reset_trade_mode(self):
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()
        yield
        _reset_for_tests()

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_init_defaults(self):
        controller = TradingModeController()
        assert controller.mode == TradingMode.PAPER
        assert controller.is_paper is True
        assert controller.is_live is False

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_mode_name_property(self):
        controller = TradingModeController()
        assert controller.mode_name == "paper"


class TestSetMode:
    """Test set_mode method."""

    @pytest.fixture(autouse=True)
    def reset_trade_mode(self):
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()
        yield
        _reset_for_tests()

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_valid(self):
        controller = TradingModeController()
        result = controller.set_mode("live", changed_by="test")
        assert result is True
        assert controller.mode == TradingMode.LIVE

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_invalid(self):
        controller = TradingModeController()
        result = controller.set_mode("invalid_mode")
        assert result is False
        assert controller.mode == TradingMode.PAPER

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_with_reason(self):
        # hybrid/autonomous are retired; test with valid mode transition
        controller = TradingModeController()
        result = controller.set_mode("mock", changed_by="admin", reason="Testing")
        assert result is True
        assert controller.mode == TradingMode.MOCK

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_logs_history(self):
        controller = TradingModeController()
        controller.set_mode("live", changed_by="test")
        history = controller.get_mode_history()
        assert len(history) == 1
        assert history[0].new_mode == "live"

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_notifies_subscribers(self):
        controller = TradingModeController()
        callback = MagicMock()
        controller.subscribe(callback)

        controller.set_mode("live", changed_by="test")

        callback.assert_called_once()

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_set_mode_handles_callback_error(self):
        controller = TradingModeController()
        callback = MagicMock(side_effect=Exception("Callback error"))
        controller.subscribe(callback)

        # Should not raise
        result = controller.set_mode("live", changed_by="test")
        assert result is True


class TestModeProperties:
    """Test mode property methods."""

    @pytest.fixture(autouse=True)
    def reset_trade_mode(self):
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()
        yield
        _reset_for_tests()

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_is_paper(self):
        controller = TradingModeController()
        assert controller.is_paper is True
        controller.set_mode("live")
        assert controller.is_paper is False

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_is_live(self):
        controller = TradingModeController()
        assert controller.is_live is False
        controller.set_mode("live")
        assert controller.is_live is True

    def test_is_live_autonomous(self):
        # autonomous mode is retired — skip
        pytest.skip("AUTONOMOUS mode retired in Season 5")

    def test_is_hybrid(self):
        # hybrid mode is retired — skip
        pytest.skip("HYBRID mode retired in Season 5")

    def test_is_autonomous(self):
        # autonomous mode is retired — skip
        pytest.skip("AUTONOMOUS mode retired in Season 5")


class TestCanExecuteLive:
    """Test can_execute_live method."""

    @pytest.fixture(autouse=True)
    def reset_trade_mode(self):
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()
        yield
        _reset_for_tests()

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_paper_mode_rejects(self):
        controller = TradingModeController()
        can_execute, reason = controller.can_execute_live("BTC/USDT", 100.0)
        assert can_execute is False
        assert "Paper mode" in reason

    def test_hybrid_mode_requires_approval(self):
        # hybrid mode is retired — skip
        pytest.skip("HYBRID mode retired in Season 5")

    def test_live_mode_allows(self):
        controller = TradingModeController()
        controller.set_mode("live")
        can_execute, reason = controller.can_execute_live("BTC/USDT", 100.0)
        assert can_execute is True

    def test_autonomous_symbol_not_allowed(self):
        # autonomous mode is retired — skip
        pytest.skip("AUTONOMOUS mode retired in Season 5")

    def test_autonomous_position_too_large(self):
        pytest.skip("AUTONOMOUS mode retired in Season 5")

    def test_autonomous_daily_trade_limit(self):
        pytest.skip("AUTONOMOUS mode retired in Season 5")

    def test_autonomous_daily_volume_limit(self):
        pytest.skip("AUTONOMOUS mode retired in Season 5")

    def test_autonomous_resets_daily_stats(self):
        pytest.skip("AUTONOMOUS mode retired in Season 5")


class TestRecordTrade:
    """Test record_trade method."""

    def test_record_trade_basic(self):
        controller = TradingModeController()
        trade = controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0
        )
        
        assert trade.agent_id == "agent_1"
        assert trade.symbol == "BTC/USDT"
        assert trade.status == "open"

    def test_record_trade_with_metadata(self):
        controller = TradingModeController()
        trade = controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0,
            strategy="momentum",
            confidence=0.85,
            reasoning="Strong uptrend",
            metadata={"venue": "binance"}
        )
        
        assert trade.strategy == "momentum"
        assert trade.confidence == 0.85
        assert trade.metadata["venue"] == "binance"

    def test_record_trade_updates_stats(self):
        controller = TradingModeController()
        initial_trades = controller._daily_stats["trades"]
        
        controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0
        )
        
        assert controller._daily_stats["trades"] == initial_trades + 1


class TestCloseTrade:
    """Test close_trade method."""

    def test_close_trade_success(self):
        controller = TradingModeController()
        trade = controller.record_trade(
            agent_id="agent_1",
            symbol="BTC/USDT",
            action="buy",
            quantity=1.0,
            price=50000.0
        )
        
        closed = controller.close_trade(trade.trade_id, exit_price=51000.0, pnl=1000.0)
        
        assert closed is not None
        assert closed.status == "closed"
        assert closed.exit_price == 51000.0
        assert closed.pnl == 1000.0

    def test_close_trade_not_found(self):
        controller = TradingModeController()
        result = controller.close_trade("nonexistent", exit_price=100.0, pnl=0.0)
        assert result is None


class TestGetSpectatorTrades:
    """Test get_spectator_trades method."""

    def test_get_trades_empty(self):
        controller = TradingModeController()
        trades = controller.get_spectator_trades()
        assert trades == []

    def test_get_trades_with_limit(self):
        controller = TradingModeController()
        for i in range(10):
            controller.record_trade(
                agent_id="agent_1",
                symbol="BTC/USDT",
                action="buy",
                quantity=1.0,
                price=50000.0
            )
        
        trades = controller.get_spectator_trades(limit=5)
        assert len(trades) == 5

    def test_get_trades_filter_by_agent(self):
        controller = TradingModeController()
        controller.record_trade(agent_id="agent_1", symbol="BTC", action="buy", quantity=1.0, price=100.0)
        controller.record_trade(agent_id="agent_2", symbol="BTC", action="buy", quantity=1.0, price=100.0)
        
        trades = controller.get_spectator_trades(agent_id="agent_1")
        assert len(trades) == 1
        assert trades[0].agent_id == "agent_1"

    def test_get_trades_filter_by_symbol(self):
        controller = TradingModeController()
        controller.record_trade(agent_id="agent_1", symbol="BTC", action="buy", quantity=1.0, price=100.0)
        controller.record_trade(agent_id="agent_1", symbol="ETH", action="buy", quantity=1.0, price=100.0)
        
        trades = controller.get_spectator_trades(symbol="BTC")
        assert len(trades) == 1
        assert trades[0].symbol == "BTC"

    def test_get_trades_filter_by_status(self):
        controller = TradingModeController()
        trade = controller.record_trade(agent_id="agent_1", symbol="BTC", action="buy", quantity=1.0, price=100.0)
        controller.close_trade(trade.trade_id, exit_price=110.0, pnl=10.0)
        controller.record_trade(agent_id="agent_1", symbol="ETH", action="buy", quantity=1.0, price=100.0)
        
        trades = controller.get_spectator_trades(status="closed")
        assert len(trades) == 1
        assert trades[0].status == "closed"


class TestGetModeHistory:
    """Test get_mode_history method."""

    def test_get_history_empty(self):
        controller = TradingModeController()
        history = controller.get_mode_history()
        assert history == []

    def test_get_history_with_limit(self):
        controller = TradingModeController()
        for mode in ["live", "paper", "hybrid", "autonomous", "paper"]:
            controller.set_mode(mode)
        
        history = controller.get_mode_history(limit=3)
        assert len(history) == 3


class TestGetStatus:
    """Test get_status method."""

    @patch.dict("os.environ", {"MERID_TRADE_MODE": "paper", "MERID_ALLOW_LIVE_TRADES": "true"}, clear=True)
    def test_get_status(self):
        controller = TradingModeController()
        status = controller.get_status()

        assert status["mode"] == "paper"
        assert status["is_paper"] is True
        assert "autonomous_limits" in status
        assert "daily_stats" in status


class TestSetAutonomousLimits:
    """Test set_autonomous_limits method."""

    def test_update_limits(self):
        controller = TradingModeController()
        controller.set_autonomous_limits({"max_position_usd": 5000.0})
        
        assert controller._autonomous_limits["max_position_usd"] == 5000.0


class TestSubscription:
    """Test subscribe/unsubscribe methods."""

    def test_subscribe(self):
        controller = TradingModeController()
        callback = MagicMock()
        controller.subscribe(callback)
        
        assert callback in controller._subscribers

    def test_unsubscribe(self):
        controller = TradingModeController()
        callback = MagicMock()
        controller.subscribe(callback)
        controller.unsubscribe(callback)
        
        assert callback not in controller._subscribers

    def test_unsubscribe_not_found(self):
        controller = TradingModeController()
        callback = MagicMock()
        # Should not raise
        controller.unsubscribe(callback)


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetTradingModeController:
    """Test get_trading_mode_controller singleton."""

    def test_returns_same_instance(self):
        import trading.mode_controller as module
        module._controller = None
        
        ctrl1 = get_trading_mode_controller()
        ctrl2 = get_trading_mode_controller()
        
        assert ctrl1 is ctrl2

    def test_creates_instance(self):
        import trading.mode_controller as module
        module._controller = None
        
        controller = get_trading_mode_controller()
        
        assert isinstance(controller, TradingModeController)
