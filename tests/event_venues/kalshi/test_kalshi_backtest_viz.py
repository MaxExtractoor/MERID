"""Tests for Kalshi Backtest Visualization."""

import pytest

from merid.event_venues.kalshi.backtest_viz import (
    BacktestViz,
    TradeRecord,
    equity_curve_data,
    pnl_distribution_data,
    regime_metrics,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _trades(n: int = 20, base_pnl: float = 10.0) -> list[TradeRecord]:
    """Generate n trades with alternating wins/losses."""
    trades = []
    for i in range(n):
        pnl = base_pnl if i % 3 != 0 else -base_pnl * 1.5
        trades.append(TradeRecord(ts=1000.0 + i * 60, pnl_cents=pnl))
    return trades


def _winning_trades(n: int = 10) -> list[TradeRecord]:
    return [TradeRecord(ts=1000.0 + i * 60, pnl_cents=50.0) for i in range(n)]


def _losing_trades(n: int = 10) -> list[TradeRecord]:
    return [TradeRecord(ts=1000.0 + i * 60, pnl_cents=-50.0) for i in range(n)]


# ── Equity curve ─────────────────────────────────────────────────────

class TestEquityCurve:
    def test_empty_trades(self):
        result = equity_curve_data([], initial_equity_cents=10000)
        assert result["trade_count"] == 0
        assert result["final_equity_cents"] == 10000

    def test_basic_curve(self):
        trades = _winning_trades(5)
        result = equity_curve_data(trades, initial_equity_cents=10000)
        assert result["trade_count"] == 5
        assert result["final_equity_cents"] == 10250  # 10000 + 5*50
        assert len(result["equity_usd"]) == 5

    def test_drawdown_tracking(self):
        trades = [
            TradeRecord(ts=1000, pnl_cents=100),
            TradeRecord(ts=1001, pnl_cents=-200),
            TradeRecord(ts=1002, pnl_cents=50),
        ]
        result = equity_curve_data(trades, initial_equity_cents=1000)
        assert result["max_drawdown_cents"] == 200

    def test_hwm_updates(self):
        trades = _winning_trades(3)
        result = equity_curve_data(trades, initial_equity_cents=1000)
        # HWM should increase with each win
        assert result["high_water_mark_cents"][-1] > result["high_water_mark_cents"][0]

    def test_equity_usd_conversion(self):
        trades = [TradeRecord(ts=1000, pnl_cents=500)]
        result = equity_curve_data(trades, initial_equity_cents=10000)
        assert result["equity_usd"][0] == 105.0  # (10000+500)/100


# ── PnL distribution ─────────────────────────────────────────────────

class TestPnLDistribution:
    def test_empty_trades(self):
        result = pnl_distribution_data([])
        assert result["trade_count"] == 0
        assert result["mean"] == 0

    def test_basic_distribution(self):
        trades = _trades(20)
        result = pnl_distribution_data(trades, bins=10)
        assert result["trade_count"] == 20
        assert len(result["counts"]) == 10
        assert sum(result["counts"]) == 20

    def test_all_positive(self):
        trades = _winning_trades(10)
        result = pnl_distribution_data(trades)
        assert result["positive_pct"] == 100.0
        assert result["negative_pct"] == 0.0
        assert result["mean"] == 50.0

    def test_all_negative(self):
        trades = _losing_trades(10)
        result = pnl_distribution_data(trades)
        assert result["positive_pct"] == 0.0
        assert result["negative_pct"] == 100.0

    def test_statistics(self):
        trades = _trades(50)
        result = pnl_distribution_data(trades)
        assert "mean" in result
        assert "median" in result
        assert "std" in result
        assert "skew" in result
        assert result["std"] > 0

    def test_single_value(self):
        trades = [TradeRecord(ts=1000, pnl_cents=100)]
        result = pnl_distribution_data(trades, bins=5)
        assert result["trade_count"] == 1
        assert result["mean"] == 100.0


# ── Regime metrics ───────────────────────────────────────────────────

class TestRegimeMetrics:
    def test_empty_trades(self):
        result = regime_metrics([])
        assert result["calm"]["trade_count"] == 0
        assert result["volatile"]["trade_count"] == 0

    def test_calm_regime(self):
        # Small, consistent PnLs → all calm
        trades = [TradeRecord(ts=1000 + i, pnl_cents=5.0) for i in range(30)]
        result = regime_metrics(trades, vol_threshold_cents=100.0)
        assert result["calm"]["trade_count"] > 0

    def test_volatile_regime(self):
        # Large swings → volatile
        trades = []
        for i in range(30):
            pnl = 500.0 if i % 2 == 0 else -500.0
            trades.append(TradeRecord(ts=1000 + i, pnl_cents=pnl))
        result = regime_metrics(trades, vol_threshold_cents=100.0, window_size=5)
        assert result["volatile"]["trade_count"] > 0

    def test_regime_pf_and_expectancy(self):
        trades = _trades(50)
        result = regime_metrics(trades, vol_threshold_cents=50.0)
        # At least one regime should have data
        total = result["calm"]["trade_count"] + result["volatile"]["trade_count"]
        assert total == 50

    def test_config_in_output(self):
        result = regime_metrics([], vol_threshold_cents=150.0, window_size=10)
        assert result["vol_threshold_cents"] == 150.0
        assert result["window_size"] == 10


# ── BacktestViz class ────────────────────────────────────────────────

class TestBacktestViz:
    def test_full_report(self):
        trades = _trades(30)
        viz = BacktestViz(trades, initial_equity_cents=10000)
        report = viz.full_report()
        assert "equity_curve" in report
        assert "pnl_distribution" in report
        assert "regime_breakdown" in report

    def test_equity_curve_method(self):
        trades = _winning_trades(5)
        viz = BacktestViz(trades, initial_equity_cents=10000)
        curve = viz.equity_curve()
        assert curve["final_equity_cents"] == 10250

    def test_pnl_distribution_method(self):
        trades = _trades(20)
        viz = BacktestViz(trades)
        dist = viz.pnl_distribution(bins=5)
        assert len(dist["counts"]) == 5

    def test_render_without_matplotlib(self):
        trades = _trades(10)
        viz = BacktestViz(trades)
        # render_to_file may or may not work depending on matplotlib
        # Just verify it doesn't crash
        result = viz.render_to_file("/dev/null")
        assert isinstance(result, bool)
