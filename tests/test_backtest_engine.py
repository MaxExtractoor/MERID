"""Tests for backtesting engine."""

import pytest
from datetime import datetime, timedelta
from merid.backtesting.backtest_engine import (
    BacktestEngine,
    Trade,
    BacktestResult,
    run_simple_backtest
)


class TestTrade:
    """Test Trade dataclass."""
    
    def test_trade_pnl_calculation_buy(self):
        """Test PnL calculation for BUY trade."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=datetime.now() + timedelta(hours=1),
            asset="BTC",
            side="BUY",
            entry_price_cents=50,
            exit_price_cents=60,
            quantity=1,
            entry_reason="test"
        )
        
        assert trade.pnl_usd == 0.10  # 60c - 50c = 10c = $0.10
        assert trade.pnl_pct == 20.0  # (60-50)/50 * 100 = 20%
    
    def test_trade_pnl_calculation_sell(self):
        """Test PnL calculation for SELL trade."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=datetime.now() + timedelta(hours=1),
            asset="BTC",
            side="SELL",
            entry_price_cents=50,
            exit_price_cents=40,
            quantity=1,
            entry_reason="test"
        )
        
        assert trade.pnl_usd == 0.10  # (50-40) = 10c = $0.10 (profit on short)
        assert trade.pnl_pct == 20.0  # (50-40)/50 * 100 = 20%
    
    def test_trade_pnl_loss(self):
        """Test PnL calculation for losing trade."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=datetime.now() + timedelta(hours=1),
            asset="BTC",
            side="BUY",
            entry_price_cents=50,
            exit_price_cents=40,
            quantity=1,
            entry_reason="test"
        )
        
        assert trade.pnl_usd == -0.10  # 40c - 50c = -10c = -$0.10
        assert trade.pnl_pct == -20.0  # (40-50)/50 * 100 = -20%
    
    def test_trade_pnl_none_if_not_closed(self):
        """Test that PnL is None if trade is not closed."""
        trade = Trade(
            entry_time=datetime.now(),
            exit_time=None,
            asset="BTC",
            side="BUY",
            entry_price_cents=50,
            exit_price_cents=None,
            quantity=1,
            entry_reason="test"
        )
        
        assert trade.pnl_usd is None
        assert trade.pnl_pct is None
        assert trade.duration_seconds is None


class TestBacktestEngine:
    """Test BacktestEngine functionality."""
    
    def test_engine_initialization(self):
        """Test engine initialization."""
        engine = BacktestEngine(initial_capital_usd=1.00)
        
        assert engine.initial_capital_usd == 1.00
        assert engine.current_capital_usd == 1.00
        assert len(engine.trades) == 0
    
    def test_add_trade(self):
        """Test adding a trade."""
        engine = BacktestEngine()
        
        trade = engine.add_trade(
            entry_time=datetime.now(),
            asset="BTC",
            side="BUY",
            entry_price_cents=50,
            quantity=1,
            entry_reason="test"
        )
        
        assert len(engine.trades) == 1
        assert trade.asset == "BTC"
        assert trade.side == "BUY"
        assert trade.entry_price_cents == 50
        assert trade.exit_time is None
    
    def test_close_trade(self):
        """Test closing a trade."""
        engine = BacktestEngine()
        
        trade = engine.add_trade(
            entry_time=datetime.now(),
            asset="BTC",
            side="BUY",
            entry_price_cents=50,
            quantity=1,
            entry_reason="test"
        )
        
        engine.close_trade(
            trade=trade,
            exit_time=datetime.now() + timedelta(hours=1),
            exit_price_cents=60,
            exit_reason="target"
        )
        
        assert trade.exit_time is not None
        assert trade.exit_price_cents == 60
        assert trade.exit_reason == "target"
        assert engine.current_capital_usd == 1.10  # $1.00 + $0.10 profit
    
    def test_calculate_results_empty(self):
        """Test calculating results with no trades."""
        engine = BacktestEngine()
        result = engine.calculate_results()
        
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.total_pnl_usd == 0.0
    
    def test_calculate_results_winning_trades(self):
        """Test calculating results with winning trades."""
        engine = BacktestEngine()
        
        now = datetime.now()
        
        # Add winning trade
        trade1 = engine.add_trade(now, "BTC", "BUY", 50, 1, "test")
        engine.close_trade(trade1, now + timedelta(hours=1), 60, "target")
        
        trade2 = engine.add_trade(now + timedelta(hours=2), "ETH", "BUY", 30, 1, "test")
        engine.close_trade(trade2, now + timedelta(hours=3), 40, "target")
        
        result = engine.calculate_results()
        
        assert result.total_trades == 2
        assert result.winning_trades == 2
        assert result.losing_trades == 0
        assert result.win_rate == 1.0
        assert result.total_pnl_usd == 0.20  # $0.10 + $0.10
        assert result.total_pnl_pct == 20.0
    
    def test_calculate_results_mixed_trades(self):
        """Test calculating results with mixed wins and losses."""
        engine = BacktestEngine()
        
        now = datetime.now()
        
        # Winning trade
        trade1 = engine.add_trade(now, "BTC", "BUY", 50, 1, "test")
        engine.close_trade(trade1, now + timedelta(hours=1), 60, "target")
        
        # Losing trade
        trade2 = engine.add_trade(now + timedelta(hours=2), "ETH", "BUY", 30, 1, "test")
        engine.close_trade(trade2, now + timedelta(hours=3), 20, "stop")
        
        result = engine.calculate_results()
        
        assert result.total_trades == 2
        assert result.winning_trades == 1
        assert result.losing_trades == 1
        assert result.win_rate == 0.5
        assert result.total_pnl_usd == 0.0  # $0.10 - $0.10
    
    def test_calculate_max_drawdown(self):
        """Test max drawdown calculation."""
        engine = BacktestEngine()
        
        now = datetime.now()
        
        # Win to $1.10
        trade1 = engine.add_trade(now, "BTC", "BUY", 50, 1, "test")
        engine.close_trade(trade1, now + timedelta(hours=1), 60, "target")
        
        # Lose back to $1.00
        trade2 = engine.add_trade(now + timedelta(hours=2), "ETH", "BUY", 30, 1, "test")
        engine.close_trade(trade2, now + timedelta(hours=3), 20, "stop")
        
        # Lose further to $0.90
        trade3 = engine.add_trade(now + timedelta(hours=4), "DOGE", "BUY", 20, 1, "test")
        engine.close_trade(trade3, now + timedelta(hours=5), 10, "stop")
        
        result = engine.calculate_results()
        
        assert abs(result.max_drawdown_usd - 0.20) < 0.01  # Peak $1.10 to $0.90
        assert abs(result.max_drawdown_pct - 20.0) < 0.1
    
    def test_reset(self):
        """Test resetting the engine."""
        engine = BacktestEngine()
        
        trade = engine.add_trade(datetime.now(), "BTC", "BUY", 50, 1, "test")
        engine.close_trade(trade, datetime.now() + timedelta(hours=1), 60, "target")
        
        assert len(engine.trades) == 1
        assert engine.current_capital_usd == 1.10
        
        engine.reset()
        
        assert len(engine.trades) == 0
        assert engine.current_capital_usd == 1.00


class TestSimpleBacktest:
    """Test simple backtest function."""
    
    def test_run_simple_backtest(self):
        """Test running a simple backtest."""
        now = datetime.now()
        
        trades_data = [
            {
                "entry_time": now,
                "exit_time": now + timedelta(hours=1),
                "asset": "BTC",
                "side": "BUY",
                "entry_price_cents": 50,
                "exit_price_cents": 60,
                "quantity": 1,
                "entry_reason": "test",
                "exit_reason": "target"
            },
            {
                "entry_time": now + timedelta(hours=2),
                "exit_time": now + timedelta(hours=3),
                "asset": "ETH",
                "side": "BUY",
                "entry_price_cents": 30,
                "exit_price_cents": 40,
                "quantity": 1,
                "entry_reason": "test",
                "exit_reason": "target"
            }
        ]
        
        result = run_simple_backtest(trades_data, initial_capital_usd=1.00)
        
        assert result.total_trades == 2
        assert result.winning_trades == 2
        assert result.total_pnl_usd == 0.20
        assert result.total_pnl_pct == 20.0
    
    def test_run_simple_backtest_with_losses(self):
        """Test running a simple backtest with losses."""
        now = datetime.now()
        
        trades_data = [
            {
                "entry_time": now,
                "exit_time": now + timedelta(hours=1),
                "asset": "BTC",
                "side": "BUY",
                "entry_price_cents": 50,
                "exit_price_cents": 40,
                "quantity": 1,
                "entry_reason": "test",
                "exit_reason": "stop"
            }
        ]
        
        result = run_simple_backtest(trades_data, initial_capital_usd=1.00)
        
        assert result.total_trades == 1
        assert result.losing_trades == 1
        assert result.total_pnl_usd == -0.10
        assert result.total_pnl_pct == -10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
