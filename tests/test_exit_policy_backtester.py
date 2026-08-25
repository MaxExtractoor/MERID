"""Tests for Exit Policy Backtesting Framework.

Tests the systematic backtesting of exit policy parameters to optimize
risk-adjusted returns based on historical trade data.
"""

import pytest
from datetime import datetime, timezone
from merid.position_management.exit_policy_backtester import (
    ExitPolicyBacktester,
    BacktestResult,
    Trade,
    ExitParameter,
    get_exit_policy_backtester,
)


class TestTrade:
    """Test Trade dataclass."""
    
    def test_profit_calculation_yes(self):
        """Test profit calculation for YES side."""
        trade = Trade(
            entry_time=1000.0,
            entry_price_cents=50,
            exit_time=1500.0,
            exit_price_cents=60,
            side="yes",
            market_id="KXBTC15M-TEST"
        )
        
        assert trade.profit_cents == 10  # 60 - 50
        assert trade.hold_time_seconds == 500.0
    
    def test_profit_calculation_no(self):
        """Test profit calculation for NO side."""
        trade = Trade(
            entry_time=1000.0,
            entry_price_cents=50,
            exit_time=1500.0,
            exit_price_cents=40,
            side="no",
            market_id="KXBTC15M-TEST"
        )
        
        assert trade.profit_cents == 10  # 50 - 40
        assert trade.hold_time_seconds == 500.0
    
    def test_r_multiple_calculation(self):
        """Test R-multiple calculation."""
        trade = Trade(
            entry_time=1000.0,
            entry_price_cents=50,
            exit_time=1500.0,
            exit_price_cents=60,
            side="yes",
            market_id="KXBTC15M-TEST"
        )
        
        # 10c profit / 10c risk = 1.0R
        assert trade.r_multiple == 1.0


class TestExitPolicyBacktester:
    """Test exit policy backtester."""
    
    def test_singleton_pattern(self):
        """Test that backtester is a singleton."""
        bt1 = get_exit_policy_backtester()
        bt2 = get_exit_policy_backtester()
        
        assert bt1 is bt2
    
    def test_load_historical_trades(self):
        """Test loading historical trades."""
        bt = ExitPolicyBacktester()
        
        trades = [
            Trade(
                entry_time=1000.0,
                entry_price_cents=50,
                exit_time=1500.0,
                exit_price_cents=60,
                side="yes",
                market_id="KXBTC15M-TEST1"
            ),
            Trade(
                entry_time=2000.0,
                entry_price_cents=40,
                exit_time=2500.0,
                exit_price_cents=35,
                side="no",
                market_id="KXBTC15M-TEST2"
            ),
        ]
        
        bt.load_historical_trades(trades)
        
        assert len(bt._trades) == 2
    
    def test_backtest_with_no_trades(self):
        """Test backtesting with no trades loaded."""
        bt = ExitPolicyBacktester()
        
        parameters = {
            ExitParameter.TIME_STOP_SECONDS: 900,
            ExitParameter.EDGE_DECAY_THRESHOLD: 0.0,
        }
        
        result = bt.backtest_parameters(parameters)
        
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.sharpe_ratio == 0.0
    
    def test_backtest_with_trades(self):
        """Test backtesting with historical trades."""
        bt = ExitPolicyBacktester()
        
        trades = [
            Trade(
                entry_time=1000.0,
                entry_price_cents=50,
                exit_time=1500.0,
                exit_price_cents=60,
                side="yes",
                market_id="KXBTC15M-TEST1"
            ),
            Trade(
                entry_time=2000.0,
                entry_price_cents=40,
                exit_time=2500.0,
                exit_price_cents=45,  # Changed to make this a loss
                side="no",
                market_id="KXBTC15M-TEST2"
            ),
        ]
        
        bt.load_historical_trades(trades)
        
        parameters = {
            ExitParameter.TIME_STOP_SECONDS: 900,
            ExitParameter.EDGE_DECAY_THRESHOLD: 0.0,
        }
        
        result = bt.backtest_parameters(parameters)
        
        assert result.total_trades == 2
        assert result.winning_trades == 1  # First trade profitable
        assert result.losing_trades == 1  # Second trade loss (40 - 45 = -5c)
        assert result.win_rate == 0.5
    
    def test_backtest_result_to_dict(self):
        """Test converting backtest result to dictionary."""
        parameters = {
            ExitParameter.TIME_STOP_SECONDS: 900,
            ExitParameter.EDGE_DECAY_THRESHOLD: 0.0,
        }
        
        result = BacktestResult(
            parameters=parameters,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=0.6,
            total_profit_cents=100,
            avg_profit_per_trade_cents=10.0,
            max_drawdown_cents=50,
            sharpe_ratio=1.5,
            avg_hold_time_seconds=300.0,
            profit_factor=2.0,
        )
        
        d = result.to_dict()
        
        assert d["total_trades"] == 10
        assert d["win_rate"] == 0.6
        assert d["sharpe_ratio"] == 1.5
        assert "parameters" in d
        assert d["parameters"]["time_stop_seconds"] == 900
    
    def test_grid_search(self):
        """Test grid search over parameter ranges."""
        bt = ExitPolicyBacktester()
        
        trades = [
            Trade(
                entry_time=1000.0,
                entry_price_cents=50,
                exit_time=1500.0,
                exit_price_cents=60,
                side="yes",
                market_id="KXBTC15M-TEST1"
            ),
        ]
        
        bt.load_historical_trades(trades)
        
        parameter_ranges = {
            ExitParameter.TIME_STOP_SECONDS: [600, 900, 1200],
            ExitParameter.EDGE_DECAY_THRESHOLD: [0.0, 0.5],
        }
        
        results = bt.grid_search(parameter_ranges)
        
        # Should have 3 * 2 = 6 combinations
        assert len(results) == 6
        
        # Results should be sorted by Sharpe ratio
        for i in range(len(results) - 1):
            assert results[i].sharpe_ratio >= results[i + 1].sharpe_ratio
    
    def test_count_combinations(self):
        """Test counting parameter combinations."""
        bt = ExitPolicyBacktester()
        
        parameter_ranges = {
            ExitParameter.TIME_STOP_SECONDS: [600, 900],
            ExitParameter.EDGE_DECAY_THRESHOLD: [0.0, 0.5, 1.0],
        }
        
        count = bt._count_combinations(parameter_ranges)
        
        assert count == 6  # 2 * 3
    
    def test_generate_combinations(self):
        """Test generating parameter combinations."""
        bt = ExitPolicyBacktester()
        
        parameter_ranges = {
            ExitParameter.TIME_STOP_SECONDS: [600, 900],
            ExitParameter.EDGE_DECAY_THRESHOLD: [0.0],
        }
        
        combinations = bt._generate_combinations(parameter_ranges)
        
        assert len(combinations) == 2
        
        # Check first combination
        assert combinations[0][ExitParameter.TIME_STOP_SECONDS] == 600
        assert combinations[0][ExitParameter.EDGE_DECAY_THRESHOLD] == 0.0
        
        # Check second combination
        assert combinations[1][ExitParameter.TIME_STOP_SECONDS] == 900
        assert combinations[1][ExitParameter.EDGE_DECAY_THRESHOLD] == 0.0
    
    def test_recommend_parameters_sharpe(self):
        """Test recommending parameters optimized for Sharpe ratio."""
        bt = ExitPolicyBacktester()
        
        # Create mock results
        results = [
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 600},
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
                win_rate=0.6,
                total_profit_cents=100,
                avg_profit_per_trade_cents=10.0,
                max_drawdown_cents=50,
                sharpe_ratio=1.5,
                avg_hold_time_seconds=300.0,
                profit_factor=2.0,
            ),
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 900},
                total_trades=10,
                winning_trades=5,
                losing_trades=5,
                win_rate=0.5,
                total_profit_cents=80,
                avg_profit_per_trade_cents=8.0,
                max_drawdown_cents=30,
                sharpe_ratio=2.0,  # Higher Sharpe
                avg_hold_time_seconds=400.0,
                profit_factor=1.5,
            ),
        ]
        
        best = bt.recommend_parameters(results, optimization_target="sharpe")
        
        assert best[ExitParameter.TIME_STOP_SECONDS] == 900  # Higher Sharpe
    
    def test_recommend_parameters_profit(self):
        """Test recommending parameters optimized for total profit."""
        bt = ExitPolicyBacktester()
        
        results = [
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 600},
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
                win_rate=0.6,
                total_profit_cents=100,  # Higher profit
                avg_profit_per_trade_cents=10.0,
                max_drawdown_cents=50,
                sharpe_ratio=1.5,
                avg_hold_time_seconds=300.0,
                profit_factor=2.0,
            ),
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 900},
                total_trades=10,
                winning_trades=5,
                losing_trades=5,
                win_rate=0.5,
                total_profit_cents=80,
                avg_profit_per_trade_cents=8.0,
                max_drawdown_cents=30,
                sharpe_ratio=2.0,
                avg_hold_time_seconds=400.0,
                profit_factor=1.5,
            ),
        ]
        
        best = bt.recommend_parameters(results, optimization_target="profit")
        
        assert best[ExitParameter.TIME_STOP_SECONDS] == 600  # Higher profit
    
    def test_recommend_parameters_win_rate(self):
        """Test recommending parameters optimized for win rate."""
        bt = ExitPolicyBacktester()
        
        results = [
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 600},
                total_trades=10,
                winning_trades=8,  # Higher win rate
                losing_trades=2,
                win_rate=0.8,
                total_profit_cents=100,
                avg_profit_per_trade_cents=10.0,
                max_drawdown_cents=50,
                sharpe_ratio=1.5,
                avg_hold_time_seconds=300.0,
                profit_factor=2.0,
            ),
            BacktestResult(
                parameters={ExitParameter.TIME_STOP_SECONDS: 900},
                total_trades=10,
                winning_trades=5,
                losing_trades=5,
                win_rate=0.5,
                total_profit_cents=80,
                avg_profit_per_trade_cents=8.0,
                max_drawdown_cents=30,
                sharpe_ratio=2.0,
                avg_hold_time_seconds=400.0,
                profit_factor=1.5,
            ),
        ]
        
        best = bt.recommend_parameters(results, optimization_target="win_rate")
        
        assert best[ExitParameter.TIME_STOP_SECONDS] == 600  # Higher win rate


if __name__ == "__main__":
    pytest.main([__file__, "-v"])