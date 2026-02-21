"""Tests for Kalshi Monte Carlo Risk-of-Ruin Simulator."""

import pytest

from merid.event_venues.kalshi.ruin_simulator import (
    PathStats,
    RuinSimulator,
    SimulationResult,
)


# ── PathStats ────────────────────────────────────────────────────────

class TestPathStats:
    def test_to_dict(self):
        s = PathStats(fraction=0.25, n_paths=100, n_trades=50, ruin_count=5, ruin_pct=5.0)
        d = s.to_dict()
        assert d["fraction"] == 0.25
        assert d["ruin_pct"] == 5.0
        assert "terminal_mean" in d
        assert "sharpe_median" in d
        assert "sortino_median" in d
        assert "calmar_median" in d


# ── SimulationResult ─────────────────────────────────────────────────

class TestSimulationResult:
    def test_best_fraction_finds_candidate(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        r.results = [
            PathStats(fraction=1.0, n_paths=100, n_trades=50, ruin_pct=15.0, terminal_median=20000),
            PathStats(fraction=0.5, n_paths=100, n_trades=50, ruin_pct=3.0, terminal_median=15000),
            PathStats(fraction=0.25, n_paths=100, n_trades=50, ruin_pct=0.5, terminal_median=12000),
        ]
        best = r.best_fraction(max_ruin_pct=2.0)
        assert best == 0.25  # Only 0.25 has ruin < 2%

    def test_best_fraction_picks_highest_median(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        r.results = [
            PathStats(fraction=0.5, n_paths=100, n_trades=50, ruin_pct=1.0, terminal_median=15000),
            PathStats(fraction=0.25, n_paths=100, n_trades=50, ruin_pct=0.5, terminal_median=12000),
        ]
        best = r.best_fraction(max_ruin_pct=2.0)
        assert best == 0.5  # Both qualify, 0.5 has higher median

    def test_best_fraction_none_when_all_too_risky(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        r.results = [
            PathStats(fraction=1.0, n_paths=100, n_trades=50, ruin_pct=20.0),
        ]
        assert r.best_fraction(max_ruin_pct=2.0) is None

    def test_to_dict(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        d = r.to_dict()
        assert d["win_rate"] == 0.55
        assert "fractions" in d
        assert "best_fraction_2pct_ruin" in d


# ── RuinSimulator ────────────────────────────────────────────────────

class TestRuinSimulator:
    def test_basic_run(self):
        sim = RuinSimulator(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=3, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[0.25], n_paths=100, n_trades=50)
        assert len(result.results) == 1
        assert result.results[0].fraction == 0.25
        assert result.results[0].n_paths == 100

    def test_multiple_fractions(self):
        sim = RuinSimulator(seed=42)
        result = sim.run(fractions=[1.0, 0.5, 0.25], n_paths=50, n_trades=30)
        assert len(result.results) == 3
        fracs = [r.fraction for r in result.results]
        assert fracs == [1.0, 0.5, 0.25]

    def test_high_edge_low_ruin(self):
        # Very high win rate → ruin should be near zero
        sim = RuinSimulator(
            win_rate=0.80, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=0, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[0.25], n_paths=200, n_trades=100)
        assert result.results[0].ruin_pct < 5.0

    def test_no_edge_higher_ruin(self):
        # 50/50 with fees → should lose over time
        sim = RuinSimulator(
            win_rate=0.50, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=3, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[0.5], n_paths=200, n_trades=200)
        # With negative expectancy, ruin should be meaningful
        assert result.results[0].ruin_pct > 0 or result.results[0].terminal_median < 10_000

    def test_full_kelly_more_ruin_than_quarter(self):
        sim = RuinSimulator(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=3, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[1.0, 0.25], n_paths=500, n_trades=200)
        full = result.results[0]
        quarter = result.results[1]
        # Full Kelly should have higher or equal ruin than quarter Kelly
        assert full.ruin_pct >= quarter.ruin_pct or full.max_dd_median_pct >= quarter.max_dd_median_pct

    def test_terminal_equity_positive(self):
        sim = RuinSimulator(
            win_rate=0.60, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=2, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[0.25], n_paths=100, n_trades=50)
        assert result.results[0].terminal_mean > 0

    def test_drawdown_stats_populated(self):
        sim = RuinSimulator(seed=42)
        result = sim.run(fractions=[0.25], n_paths=100, n_trades=50)
        stats = result.results[0]
        assert stats.max_dd_mean_pct >= 0
        assert stats.max_dd_median_pct >= 0

    def test_default_fractions(self):
        sim = RuinSimulator(seed=42)
        result = sim.run(n_paths=20, n_trades=20)
        assert len(result.results) == 8  # default 8 fractions

    def test_compare_fractions(self):
        sim = RuinSimulator(seed=42)
        d = sim.compare_fractions(fractions=[0.5, 0.25], n_paths=50, n_trades=30)
        assert "fractions" in d
        assert len(d["fractions"]) == 2
        assert "best_fraction_2pct_ruin" in d

    def test_seed_reproducibility(self):
        sim1 = RuinSimulator(seed=123)
        sim2 = RuinSimulator(seed=123)
        r1 = sim1.run(fractions=[0.25], n_paths=50, n_trades=30)
        r2 = sim2.run(fractions=[0.25], n_paths=50, n_trades=30)
        assert r1.results[0].terminal_median == r2.results[0].terminal_median

    def test_risk_adjusted_metrics_populated(self):
        sim = RuinSimulator(
            win_rate=0.80, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=0, initial_equity=10_000, seed=42,
        )
        result = sim.run(fractions=[0.1], n_paths=100, n_trades=100)
        stats = result.results[0]
        # With very strong edge, Sharpe and Calmar should be positive
        assert stats.sharpe_median > 0
        assert stats.calmar_median > 0

    def test_optimize_for_sharpe(self):
        sim = RuinSimulator(
            win_rate=0.60, win_payout_cents=45, loss_amount_cents=55,
            fee_cents=2, initial_equity=10_000, seed=42,
        )
        d = sim.optimize_for_sharpe(
            min_sharpe=0.0, max_dd_pct=100.0,
            n_paths=50, n_trades=50, granularity=5,
        )
        assert "optimization" in d
        assert "best_fraction" in d["optimization"]
        assert len(d["fractions"]) == 5

    def test_compare_fractions_includes_sharpe(self):
        sim = RuinSimulator(seed=42)
        d = sim.compare_fractions(fractions=[0.25], n_paths=50, n_trades=50)
        assert "sharpe_median" in d["fractions"][0]
        assert "best_fraction_sharpe2_dd25" in d


class TestBestFractionForSharpe:
    def test_finds_qualifying_fraction(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        r.results = [
            PathStats(fraction=1.0, n_paths=100, n_trades=50, sharpe_median=1.5, max_dd_median_pct=30.0),
            PathStats(fraction=0.5, n_paths=100, n_trades=50, sharpe_median=2.5, max_dd_median_pct=15.0),
            PathStats(fraction=0.25, n_paths=100, n_trades=50, sharpe_median=3.0, max_dd_median_pct=8.0),
        ]
        best = r.best_fraction_for_sharpe(min_sharpe=2.0, max_dd_pct=20.0)
        assert best == 0.5  # Largest fraction meeting both targets

    def test_none_when_no_qualifying(self):
        r = SimulationResult(
            win_rate=0.55, win_payout_cents=45, loss_amount_cents=55,
            initial_equity=10000, ruin_threshold=2000, fee_cents=3,
        )
        r.results = [
            PathStats(fraction=0.5, n_paths=100, n_trades=50, sharpe_median=1.0, max_dd_median_pct=30.0),
        ]
        assert r.best_fraction_for_sharpe(min_sharpe=3.0) is None
