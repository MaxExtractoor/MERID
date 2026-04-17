"""
Smoke tests for paper trading flow.

These tests exercise the full paper trading stack in memory,
verifying that mode controller, paper engine, and order flow work together.

Run with: pytest tests/smoke/ -m smoke -v
"""

import pytest
import time


@pytest.mark.smoke
class TestPaperTradingSmoke:
    """Smoke tests for paper trading integration."""

    def test_mode_controller_paper_mode(self):
        """Verify mode controller initializes in paper mode."""
        from trading.mode_controller import get_trading_mode_controller, TradingMode
        
        controller = get_trading_mode_controller()
        
        # Should be able to set paper mode
        result = controller.set_mode("paper", changed_by="smoke_test")
        assert result is True
        assert controller.mode == TradingMode.PAPER
        assert controller.is_paper is True
        assert controller.is_live is False

    def test_paper_engine_initialization(self):
        """Verify paper trading engine initializes correctly."""
        from trading.paper_trading import get_paper_engine
        
        engine = get_paper_engine()
        
        assert engine is not None
        assert engine.starting_balance == 10000.0
        assert isinstance(engine.portfolios, dict)
        assert isinstance(engine.current_prices, dict)

    def test_paper_order_placement(self):
        """Verify paper orders can be placed and filled."""
        from trading.paper_trading import get_paper_engine, PaperOrderStatus
        
        engine = get_paper_engine()
        
        # Set up a price
        engine.update_prices({"BTC/USDT": 50000.0, "BTC": 50000.0})
        
        # Place a market order
        order = engine.place_order(
            user_id="smoke_test_user",
            asset="BTC",
            side="long",
            size_usd=100.0,
            order_type="market",
            leverage=1,
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.FILLED
        assert order.fill_price > 0
        assert order.filled_size == 100.0

    def test_paper_portfolio_tracking(self):
        """Verify portfolio stats are tracked correctly."""
        from trading.paper_trading import get_paper_engine
        
        engine = get_paper_engine()
        user_id = f"smoke_test_{int(time.time())}"
        
        # Get initial portfolio
        portfolio = engine.get_portfolio(user_id)
        initial_balance = portfolio.current_balance
        
        # Set price and place order
        engine.update_prices({"ETH/USDT": 3000.0, "ETH": 3000.0})
        engine.place_order(
            user_id=user_id,
            asset="ETH",
            side="long",
            size_usd=500.0,
        )
        
        # Check stats
        stats = engine.get_portfolio_stats(user_id)
        
        assert stats["user_id"] == user_id
        assert stats["total_trades"] >= 1
        assert stats["open_positions"] >= 1
        assert stats["current_balance"] < initial_balance  # Margin deducted

    def test_paper_pnl_calculation(self):
        """Verify P&L is calculated on price changes."""
        from trading.paper_trading import get_paper_engine
        
        engine = get_paper_engine()
        user_id = f"pnl_test_{int(time.time())}"
        
        # Entry at 100
        engine.update_prices({"TEST/USDT": 100.0, "TEST": 100.0})
        engine.place_order(
            user_id=user_id,
            asset="TEST",
            side="long",
            size_usd=1000.0,
            leverage=1,
        )
        
        initial_stats = engine.get_portfolio_stats(user_id)
        
        # Price goes up 10%
        engine.update_prices({"TEST/USDT": 110.0, "TEST": 110.0})
        
        updated_stats = engine.get_portfolio_stats(user_id)
        
        # Should have ~10% gain on position (minus slippage)
        assert updated_stats["total_unrealized_pnl"] > initial_stats["total_unrealized_pnl"]

    def test_live_execution_blocked_in_paper_mode(self):
        """Verify live execution is blocked when in paper mode."""
        from trading.mode_controller import get_trading_mode_controller
        
        controller = get_trading_mode_controller()
        controller.set_mode("paper", changed_by="smoke_test")
        
        can_execute, reason = controller.can_execute_live("BTC/USDT", 1000.0)
        
        assert can_execute is False
        assert "paper" in reason.lower()

    def test_global_stats_aggregation(self):
        """Verify global stats aggregate across users."""
        from trading.paper_trading import get_paper_engine
        
        engine = get_paper_engine()
        
        # Get global stats
        stats = engine.get_global_stats()
        
        assert "accounts" in stats
        assert "equity" in stats
        assert "active_positions" in stats
        assert "positions" in stats
        assert isinstance(stats["positions"], list)


@pytest.mark.smoke
class TestModeControllerSmoke:
    """Smoke tests for mode controller transitions."""

    def test_mode_change_logging(self):
        """Verify mode changes are logged in history."""
        from trading.mode_controller import get_trading_mode_controller
        
        controller = get_trading_mode_controller()
        
        # Make a mode change
        controller.set_mode("paper", changed_by="smoke_test", reason="Testing")
        
        # History should have entries
        assert len(controller._mode_history) > 0
        
        last_event = controller._mode_history[-1]
        assert last_event.changed_by == "smoke_test"

    def test_invalid_mode_rejected(self):
        """Verify invalid mode names are rejected."""
        from trading.mode_controller import get_trading_mode_controller
        
        controller = get_trading_mode_controller()
        
        result = controller.set_mode("invalid_mode", changed_by="smoke_test")
        
        assert result is False
