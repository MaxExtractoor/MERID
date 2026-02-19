"""Tests for Kalshi Performance Comparator."""

import pytest

from merid.event_venues.kalshi.performance_comparator import (
    DEFAULT_THRESHOLDS,
    DegradationThresholds,
    PerformanceComparator,
    StageComparison,
    StageMetrics,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _metrics(
    trades: int = 100,
    wins: int = 60,
    losses: int = 40,
    gross_wins: float = 6000.0,
    gross_losses: float = 3000.0,
    fees: float = 200.0,
    net_pnl: float = 2800.0,
    hwm: float = 10000.0,
    max_dd: float = 500.0,
    trade_pnls: list = None,
) -> StageMetrics:
    return StageMetrics(
        total_trades=trades,
        winning_trades=wins,
        losing_trades=losses,
        gross_wins_cents=gross_wins,
        gross_losses_cents=gross_losses,
        fees_cents=fees,
        net_pnl_cents=net_pnl,
        high_water_mark_cents=hwm,
        max_drawdown_cents=max_dd,
        trade_pnls_cents=trade_pnls or [],
    )


# ── StageMetrics ─────────────────────────────────────────────────────

class TestStageMetrics:
    def test_win_rate(self):
        m = _metrics(wins=60, losses=40)
        assert m.win_rate_pct == pytest.approx(60.0)

    def test_profit_factor(self):
        m = _metrics(gross_wins=6000, gross_losses=3000)
        assert m.profit_factor == pytest.approx(2.0)

    def test_profit_factor_no_losses(self):
        m = _metrics(gross_wins=1000, gross_losses=0)
        assert m.profit_factor == float("inf")

    def test_profit_factor_no_trades(self):
        m = StageMetrics()
        assert m.profit_factor == 0.0

    def test_expectancy(self):
        m = _metrics(wins=60, losses=40, gross_wins=6000, gross_losses=3000)
        # wr=0.6, avg_win=100, avg_loss=75
        # exp = 0.6*100 - 0.4*75 = 60 - 30 = 30
        assert m.expectancy_cents == pytest.approx(30.0)

    def test_drawdown_pct(self):
        m = _metrics(hwm=10000, max_dd=500)
        assert m.drawdown_pct == pytest.approx(5.0)

    def test_sharpe_ratio_positive(self):
        # Consistent wins → positive Sharpe
        pnls = [45.0, 45.0, -55.0, 45.0, 45.0, -55.0, 45.0, 45.0, 45.0, -55.0]
        m = _metrics(trade_pnls=pnls)
        assert m.sharpe_ratio > 0

    def test_sharpe_ratio_zero_trades(self):
        m = _metrics(trade_pnls=[])
        assert m.sharpe_ratio == 0.0

    def test_sharpe_ratio_one_trade(self):
        m = _metrics(trade_pnls=[45.0])
        assert m.sharpe_ratio == 0.0

    def test_sharpe_ratio_all_same(self):
        m = _metrics(trade_pnls=[10.0, 10.0, 10.0])
        # Zero variance → 0
        assert m.sharpe_ratio == 0.0

    def test_sortino_ratio_positive(self):
        pnls = [45.0, 45.0, -55.0, 45.0, 45.0]
        m = _metrics(trade_pnls=pnls)
        assert m.sortino_ratio > 0

    def test_sortino_ratio_no_downside(self):
        pnls = [10.0, 20.0, 30.0]
        m = _metrics(trade_pnls=pnls)
        assert m.sortino_ratio == float("inf")

    def test_sortino_ratio_empty(self):
        m = _metrics(trade_pnls=[])
        assert m.sortino_ratio == 0.0

    def test_returns_volatility(self):
        pnls = [45.0, -55.0, 45.0, -55.0]
        m = _metrics(trade_pnls=pnls)
        assert m.returns_volatility_pct > 0

    def test_returns_volatility_empty(self):
        m = _metrics(trade_pnls=[])
        assert m.returns_volatility_pct == 0.0

    def test_calmar_ratio_positive(self):
        m = _metrics(net_pnl=2800, hwm=10000, max_dd=500)
        # total_return_pct = 2800/10000*100 = 28%, dd_pct = 500/10000*100 = 5%
        # calmar = 28 / 5 = 5.6
        assert m.calmar_ratio == pytest.approx(5.6)

    def test_calmar_ratio_no_drawdown(self):
        m = _metrics(net_pnl=1000, hwm=10000, max_dd=0)
        assert m.calmar_ratio == float("inf")

    def test_calmar_ratio_no_pnl_no_drawdown(self):
        m = _metrics(net_pnl=0, hwm=10000, max_dd=0)
        assert m.calmar_ratio == 0.0

    def test_to_dict(self):
        m = _metrics(trade_pnls=[45.0, -55.0, 45.0])
        d = m.to_dict()
        assert "win_rate_pct" in d
        assert "profit_factor" in d
        assert "expectancy_cents" in d
        assert "sharpe_ratio" in d
        assert "sortino_ratio" in d
        assert "returns_volatility_cents" in d
        assert "calmar_ratio" in d
        assert "net_pnl_usd" in d
        assert "max_drawdown_pct" in d


# ── Registration ─────────────────────────────────────────────────────

class TestRegistration:
    def test_register_stages(self):
        comp = PerformanceComparator()
        comp.register_backtest("BTC_HOURLY", _metrics())
        comp.register_paper("BTC_HOURLY", _metrics())
        comp.register_live("BTC_HOURLY", _metrics())
        assert "BTC_HOURLY" in comp.agents

    def test_register_from_dict(self):
        comp = PerformanceComparator()
        comp.register_from_dict("BTC_HOURLY", "backtest", {
            "total_trades": 100,
            "winning_trades": 60,
            "losing_trades": 40,
            "gross_wins_cents": 6000.0,
            "gross_losses_cents": 3000.0,
        })
        assert "BTC_HOURLY" in comp.agents

    def test_agents_property(self):
        comp = PerformanceComparator()
        comp.register_backtest("BTC_HOURLY", _metrics())
        comp.register_paper("ETH_HOURLY", _metrics())
        assert comp.agents == ["BTC_HOURLY", "ETH_HOURLY"]


# ── Comparison — no degradation ──────────────────────────────────────

class TestNoDegradation:
    def test_identical_stages_no_alerts(self):
        comp = PerformanceComparator()
        m = _metrics()
        comp.register_backtest("BTC_HOURLY", m)
        comp.register_paper("BTC_HOURLY", m)
        comp.register_live("BTC_HOURLY", m)
        report = comp.compare("BTC_HOURLY")
        assert report["alert_count"] == 0

    def test_slight_improvement_no_alerts(self):
        comp = PerformanceComparator()
        bt = _metrics(gross_wins=6000, gross_losses=3000)
        pp = _metrics(gross_wins=7000, gross_losses=3000)  # better PF
        comp.register_backtest("BTC_HOURLY", bt)
        comp.register_paper("BTC_HOURLY", pp)
        report = comp.compare("BTC_HOURLY")
        assert report["alert_count"] == 0


# ── Comparison — degradation detected ────────────────────────────────

class TestDegradation:
    def test_pf_drop_flagged(self):
        comp = PerformanceComparator()
        bt = _metrics(gross_wins=6000, gross_losses=3000)  # PF=2.0
        pp = _metrics(gross_wins=3500, gross_losses=3000)  # PF=1.17 (>20% drop)
        comp.register_backtest("BTC_HOURLY", bt)
        comp.register_paper("BTC_HOURLY", pp)
        report = comp.compare("BTC_HOURLY")
        assert report["alert_count"] > 0
        assert any("PF degraded" in a for a in report["alerts"])

    def test_expectancy_drop_flagged(self):
        comp = PerformanceComparator()
        pp = _metrics(wins=60, losses=40, gross_wins=6000, gross_losses=3000)
        lv = _metrics(wins=50, losses=50, gross_wins=3000, gross_losses=4000)
        comp.register_paper("BTC_HOURLY", pp)
        comp.register_live("BTC_HOURLY", lv)
        report = comp.compare("BTC_HOURLY")
        assert any("Expectancy" in a for a in report["alerts"])

    def test_negative_expectancy_flagged(self):
        comp = PerformanceComparator()
        pp = _metrics(wins=60, losses=40, gross_wins=6000, gross_losses=3000)
        lv = _metrics(wins=30, losses=70, gross_wins=2000, gross_losses=5000)
        comp.register_paper("BTC_HOURLY", pp)
        comp.register_live("BTC_HOURLY", lv)
        report = comp.compare("BTC_HOURLY")
        assert any("negative" in a.lower() for a in report["alerts"])

    def test_win_rate_drop_flagged(self):
        comp = PerformanceComparator()
        pp = _metrics(wins=70, losses=30)  # 70%
        lv = _metrics(wins=55, losses=45)  # 55% — 15pp drop
        comp.register_paper("BTC_HOURLY", pp)
        comp.register_live("BTC_HOURLY", lv)
        report = comp.compare("BTC_HOURLY")
        assert any("Win rate" in a for a in report["alerts"])

    def test_drawdown_increase_flagged(self):
        comp = PerformanceComparator()
        pp = _metrics(hwm=10000, max_dd=200)   # 2% DD
        lv = _metrics(hwm=10000, max_dd=1000)  # 10% DD — 8pp increase
        comp.register_paper("BTC_HOURLY", pp)
        comp.register_live("BTC_HOURLY", lv)
        report = comp.compare("BTC_HOURLY")
        assert any("Drawdown" in a for a in report["alerts"])


# ── Insufficient data ────────────────────────────────────────────────

class TestInsufficientData:
    def test_too_few_trades(self):
        comp = PerformanceComparator()
        bt = _metrics(trades=10, wins=6, losses=4)
        pp = _metrics(trades=10, wins=5, losses=5)
        comp.register_backtest("BTC_HOURLY", bt)
        comp.register_paper("BTC_HOURLY", pp)
        report = comp.compare("BTC_HOURLY")
        c = report["comparisons"]["backtest_vs_paper"]
        assert c["sufficient_data"] is False

    def test_missing_stage(self):
        comp = PerformanceComparator()
        comp.register_backtest("BTC_HOURLY", _metrics())
        report = comp.compare("BTC_HOURLY")
        # No paper or live → no comparisons
        assert len(report["comparisons"]) == 0


# ── Full report ──────────────────────────────────────────────────────

class TestFullReport:
    def test_full_report_structure(self):
        comp = PerformanceComparator()
        comp.register_backtest("BTC_HOURLY", _metrics())
        comp.register_paper("BTC_HOURLY", _metrics())
        comp.register_paper("ETH_HOURLY", _metrics())
        report = comp.full_report()
        assert report["total_agents"] == 2
        assert "BTC_HOURLY" in report["agents"]
        assert "ETH_HOURLY" in report["agents"]
        assert "recommendation" in report

    def test_no_alerts_recommendation(self):
        comp = PerformanceComparator()
        m = _metrics()
        comp.register_backtest("BTC_HOURLY", m)
        comp.register_paper("BTC_HOURLY", m)
        report = comp.full_report()
        assert report["total_alerts"] == 0
        assert "Safe to continue" in report["recommendation"]

    def test_many_alerts_recommendation(self):
        comp = PerformanceComparator()
        bt = _metrics(gross_wins=6000, gross_losses=3000)
        lv = _metrics(wins=30, losses=70, gross_wins=2000, gross_losses=5000, hwm=10000, max_dd=2000)
        for agent in ["BTC_HOURLY", "ETH_HOURLY", "SOL_15M"]:
            comp.register_backtest(agent, bt)
            comp.register_live(agent, lv)
        report = comp.full_report()
        assert report["total_alerts"] > 3
        assert "Significant" in report["recommendation"]


# ── Custom thresholds ────────────────────────────────────────────────

class TestCustomThresholds:
    def test_strict_thresholds(self):
        th = DegradationThresholds(pf_drop_pct=5.0, win_rate_drop_pp=3.0)
        comp = PerformanceComparator(thresholds=th)
        bt = _metrics(gross_wins=6000, gross_losses=3000)  # PF=2.0
        pp = _metrics(gross_wins=5500, gross_losses=3000)  # PF=1.83 (8.5% drop)
        comp.register_backtest("BTC_HOURLY", bt)
        comp.register_paper("BTC_HOURLY", pp)
        report = comp.compare("BTC_HOURLY")
        assert report["alert_count"] > 0  # Strict threshold catches small drop


# ── StageComparison ──────────────────────────────────────────────────

class TestStageComparison:
    def test_to_dict(self):
        c = StageComparison(from_stage="paper", to_stage="live")
        d = c.to_dict()
        assert d["from"] == "paper"
        assert d["to"] == "live"
        assert "alerts" in d
        assert "sufficient_data" in d
