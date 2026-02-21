"""
Tests for paper trading order management functionality.

Tests cover:
- Order placement (market, limit, stop-loss)
- Order execution
- Position management
- Balance validation
- Risk controls
- Order history
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from trading.paper_trading import (
    PaperTradingEngine,
    PaperOrder,
    PaperPosition,
    PaperOrderStatus,
    PaperOrderType,
    get_paper_engine
)


@pytest.fixture
def mock_price_feed():
    """Mock the live price feed."""
    mock_feed = MagicMock()
    mock_feed.subscribe.return_value = None
    mock_feed.get_current_price.return_value = MagicMock(
        symbol="BTC/USDT",
        price=50000.0,
        volume=1000000.0,
        timestamp=time.time()
    )
    return mock_feed


@pytest.fixture
def paper_engine(mock_price_feed):
    """Create a fresh paper trading engine for each test."""
    with patch('data.live_price_feed.get_live_price_feed', return_value=mock_price_feed):
        engine = PaperTradingEngine(starting_balance=10000.0)
        # Set initial prices
        engine.current_prices = {
            "BTC/USDT": 50000.0,
            "BTC": 50000.0,
            "ETH/USDT": 3000.0,
            "ETH": 3000.0,
            "SOL/USDT": 100.0,
            "SOL": 100.0
        }
        yield engine


class TestOrderPlacement:
    """Test order placement functionality."""
    
    def test_place_market_order_success(self, paper_engine):
        """Test placing a successful market order."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.FILLED
        assert order.user_id == "test_user"
        assert order.asset == "BTC"
        assert order.side == "long"
        assert order.size_usd == 1000.0
        assert order.fill_price is not None
        assert order.fill_price > 0
    
    def test_place_limit_order(self, paper_engine):
        """Test placing a limit order."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="limit",
            price=49000.0
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.PENDING
        assert order.order_type == PaperOrderType.LIMIT
        assert order.price == 49000.0
        
        # Order should be in pending orders
        portfolio = paper_engine.get_portfolio("test_user")
        assert order.order_id in portfolio.orders
    
    def test_place_stop_loss_order(self, paper_engine):
        """Test placing a stop-loss order."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="short",
            size_usd=1000.0,
            order_type="stop_loss",
            stop_price=51000.0
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.PENDING
        assert order.order_type == PaperOrderType.STOP_LOSS
        assert order.stop_price == 51000.0
    
    def test_order_rejected_insufficient_balance(self, paper_engine):
        """Test order rejection due to insufficient balance."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=20000.0,  # More than starting balance
            order_type="market"
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.REJECTED
        
        # Balance should remain unchanged
        portfolio = paper_engine.get_portfolio("test_user")
        assert portfolio.current_balance == 10000.0
    
    def test_order_with_leverage(self, paper_engine):
        """Test order placement with leverage."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=5000.0,
            order_type="market",
            leverage=5
        )
        
        assert order is not None
        assert order.status == PaperOrderStatus.FILLED
        assert order.leverage == 5
        
        # With 5x leverage, only 1000 USD margin required
        portfolio = paper_engine.get_portfolio("test_user")
        assert portfolio.current_balance == 9000.0  # 10000 - 1000


class TestOrderExecution:
    """Test order execution logic."""
    
    def test_market_order_execution_with_slippage(self, paper_engine):
        """Test that market orders include slippage."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        # Long orders should have positive slippage (buy higher)
        assert order.fill_price > 50000.0
        assert order.fill_price <= 50000.0 * 1.01  # Max 1% slippage
    
    def test_short_order_execution(self, paper_engine):
        """Test short order execution."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="short",
            size_usd=1000.0,
            order_type="market"
        )
        
        assert order.status == PaperOrderStatus.FILLED
        assert order.side == "short"
        # Short orders should have negative slippage (sell lower)
        assert order.fill_price < 50000.0
    
    def test_limit_order_triggers_when_price_reached(self, paper_engine):
        """Test that limit orders trigger when price is reached."""
        # Place limit buy order below current price
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="limit",
            price=49000.0
        )
        
        assert order.status == PaperOrderStatus.PENDING
        
        # Update price to trigger limit order
        paper_engine.update_prices({"BTC": 48500.0, "BTC/USDT": 48500.0})
        
        # Order should now be filled
        portfolio = paper_engine.get_portfolio("test_user")
        assert order.order_id not in portfolio.orders
        assert order.status == PaperOrderStatus.FILLED
    
    def test_stop_loss_triggers_when_price_reached(self, paper_engine):
        """Test that stop-loss orders trigger when price is reached."""
        # Place stop-loss sell order above current price
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="short",
            size_usd=1000.0,
            order_type="stop_loss",
            stop_price=51000.0
        )
        
        assert order.status == PaperOrderStatus.PENDING
        
        # Update price to trigger stop-loss
        paper_engine.update_prices({"BTC": 51500.0, "BTC/USDT": 51500.0})
        
        # Order should now be filled
        portfolio = paper_engine.get_portfolio("test_user")
        assert order.order_id not in portfolio.orders
        assert order.status == PaperOrderStatus.FILLED


class TestPositionManagement:
    """Test position creation and management."""
    
    def test_position_created_after_order(self, paper_engine):
        """Test that a position is created after order execution."""
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        portfolio = paper_engine.get_portfolio("test_user")
        
        # Should have one position
        assert len(portfolio.positions) == 1
        
        # Get the position
        position_key = f"BTC_long_perp"
        assert position_key in portfolio.positions
        
        position = portfolio.positions[position_key]
        assert position.asset == "BTC"
        assert position.side == "long"
        assert position.size_usd == 1000.0
        assert position.entry_price == order.fill_price
    
    def test_multiple_orders_average_position(self, paper_engine):
        """Test that multiple orders average the position entry price."""
        # First order at current price (~50000)
        order1 = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        # Update price
        paper_engine.update_prices({"BTC": 52000.0, "BTC/USDT": 52000.0})
        
        # Second order at new price (~52000)
        order2 = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        portfolio = paper_engine.get_portfolio("test_user")
        position_key = f"BTC_long_perp"
        position = portfolio.positions[position_key]
        
        # Position size should be sum of both orders
        assert position.size_usd == 2000.0
        
        # Entry price should be weighted average
        expected_avg = (order1.fill_price * 1000 + order2.fill_price * 1000) / 2000
        assert abs(position.entry_price - expected_avg) < 0.01
    
    def test_close_position_realizes_pnl(self, paper_engine):
        """Test closing a position and realizing P&L."""
        # Open position
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        entry_price = order.fill_price
        
        # Update price to create profit
        new_price = entry_price * 1.10  # 10% gain
        paper_engine.update_prices({"BTC": new_price, "BTC/USDT": new_price})
        
        # Close position
        position_key = f"BTC_long_perp"
        pnl = paper_engine.close_position("test_user", position_key)
        
        # Should have positive P&L (approximately 10% of 1000 = 100)
        assert pnl is not None
        assert pnl > 0
        assert abs(pnl - 100.0) < 20.0  # Allow some variance for slippage
        
        # Position should be removed
        portfolio = paper_engine.get_portfolio("test_user")
        assert position_key not in portfolio.positions
        
        # Balance should be updated
        assert portfolio.current_balance > 10000.0  # Original + profit
    
    def test_close_position_with_loss(self, paper_engine):
        """Test closing a position with a loss."""
        # Open position
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        entry_price = order.fill_price
        
        # Update price to create loss
        new_price = entry_price * 0.90  # 10% loss
        paper_engine.update_prices({"BTC": new_price, "BTC/USDT": new_price})
        
        # Close position
        position_key = f"BTC_long_perp"
        pnl = paper_engine.close_position("test_user", position_key)
        
        # Should have negative P&L
        assert pnl is not None
        assert pnl < 0
        assert abs(pnl + 100.0) < 20.0  # Approximately -100
        
        # Balance should be reduced
        portfolio = paper_engine.get_portfolio("test_user")
        assert portfolio.current_balance < 10000.0


class TestOrderHistory:
    """Test order history and trade tracking."""
    
    def test_filled_orders_in_trade_history(self, paper_engine):
        """Test that filled orders appear in trade history."""
        # Place multiple orders
        paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        paper_engine.place_order(
            user_id="test_user",
            asset="ETH",
            side="short",
            size_usd=500.0,
            order_type="market"
        )
        
        portfolio = paper_engine.get_portfolio("test_user")
        
        # Should have 2 trades in history
        assert len(portfolio.trade_history) == 2
        assert portfolio.total_trades == 2
    
    def test_get_recent_trades(self, paper_engine):
        """Test getting recent trades across all users."""
        # Create trades for multiple users
        paper_engine.place_order(
            user_id="user1",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        paper_engine.place_order(
            user_id="user2",
            asset="ETH",
            side="short",
            size_usd=500.0,
            order_type="market"
        )
        
        # Get recent trades
        recent_trades = paper_engine.get_recent_trades(limit=10)
        
        assert len(recent_trades) == 2
        
        # Trades should be sorted by timestamp (most recent first)
        assert recent_trades[0]["timestamp"] >= recent_trades[1]["timestamp"]
    
    def test_pending_orders_not_in_trade_history(self, paper_engine):
        """Test that pending orders don't appear in trade history."""
        # Place a limit order (pending)
        paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="limit",
            price=49000.0
        )
        
        portfolio = paper_engine.get_portfolio("test_user")
        
        # Should have 0 trades in history
        assert len(portfolio.trade_history) == 0
        assert portfolio.total_trades == 0
        
        # But should have 1 pending order
        assert len(portfolio.orders) == 1


class TestPortfolioStats:
    """Test portfolio statistics and metrics."""
    
    def test_portfolio_stats_calculation(self, paper_engine):
        """Test portfolio statistics calculation."""
        # Open a position
        paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        
        stats = paper_engine.get_portfolio_stats("test_user")
        
        assert stats["starting_balance"] == 10000.0
        assert stats["current_balance"] == 9000.0  # 10000 - 1000 margin
        assert stats["total_position_value"] == 1000.0
        assert stats["open_positions"] == 1
        assert stats["total_trades"] == 1
    
    def test_win_rate_calculation(self, paper_engine):
        """Test win rate calculation."""
        # Win trade
        order1 = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        entry_price = order1.fill_price
        paper_engine.update_prices({"BTC": entry_price * 1.1, "BTC/USDT": entry_price * 1.1})
        paper_engine.close_position("test_user", "BTC_long_perp")
        
        # Lose trade
        order2 = paper_engine.place_order(
            user_id="test_user",
            asset="ETH",
            side="long",
            size_usd=1000.0,
            order_type="market"
        )
        entry_price2 = order2.fill_price
        paper_engine.update_prices({"ETH": entry_price2 * 0.9, "ETH/USDT": entry_price2 * 0.9})
        paper_engine.close_position("test_user", "ETH_long_perp")
        
        stats = paper_engine.get_portfolio_stats("test_user")
        
        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 1
        assert stats["win_rate_pct"] == 50.0
    
    def test_global_stats(self, paper_engine):
        """Test global statistics across all users."""
        # Create trades for multiple users
        paper_engine.place_order(user_id="user1", asset="BTC", side="long", size_usd=1000.0, order_type="market")
        paper_engine.place_order(user_id="user2", asset="ETH", side="short", size_usd=500.0, order_type="market")
        
        global_stats = paper_engine.get_global_stats()
        
        assert global_stats["accounts"] == 2
        assert global_stats["active_positions"] == 2
        assert global_stats["trades_24h"] == 2


class TestRiskControls:
    """Test risk control integration."""
    
    def test_order_rejected_by_risk_controller(self, paper_engine):
        """Test that orders are rejected when risk controller blocks trading."""
        # Mock risk controller that blocks trading
        mock_risk_ctrl = MagicMock()
        mock_risk_ctrl.can_trade.return_value = False
        
        with patch('trading.paper_trading._get_risk_controller', return_value=mock_risk_ctrl):
            order = paper_engine.place_order(
                user_id="test_user",
                asset="BTC",
                side="long",
                size_usd=1000.0,
                order_type="market"
            )
            
            assert order.status == PaperOrderStatus.REJECTED
            
            # Balance should remain unchanged
            portfolio = paper_engine.get_portfolio("test_user")
            assert portfolio.current_balance == 10000.0


class TestSingletonBehavior:
    """Test singleton pattern for paper trading engine."""
    
    def test_get_paper_engine_returns_singleton(self):
        """Test that get_paper_engine returns the same instance."""
        with patch('data.live_price_feed.get_live_price_feed'):
            engine1 = get_paper_engine()
            engine2 = get_paper_engine()
            
            assert engine1 is engine2
