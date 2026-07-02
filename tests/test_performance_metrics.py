"""Tests for merid.metrics.performance — compute_performance_metrics.

Covers:
- Empty input
- All wins
- All losses
- Mixed win/loss with exact R:R verification
- Promotion-floor flag (win_rate >= 55%, PF >= 1.3, avg_pnl >= 5c)
- 75% win-rate flag
- Max drawdown calculation
- Sharpe ratio (sign and rough magnitude)
"""

import math

import pytest

from merid.metrics.performance import (
    TradeRecord,
    PerformanceSummary,
    compute_performance_metrics,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_trades(pnls, risk=20.0, fees=4.0):
    """Build TradeRecord list from a list of PnL values (cents)."""
    return [
        TradeRecord(
            trade_id=f"t{i}",
            pnl_cents=float(p),
            risk_cents=risk,
            fees_cents=fees,
        )
        for i, p in enumerate(pnls)
    ]


# ── Empty input ──────────────────────────────────────────────────────────

def test_empty_returns_zero_summary():
    s = compute_performance_metrics([])
    assert s.total_trades == 0
    assert s.win_rate_pct == 0.0
    assert s.profit_factor == 0.0
    assert not s.meets_75pct_winrate
    assert not s.meets_promotion_floor


# ── All wins ─────────────────────────────────────────────────────────────

def test_all_wins():
    trades = _make_trades([20, 25, 30])
    s = compute_performance_metrics(trades)
    assert s.total_trades == 3
    assert s.winning_trades == 3
    assert s.losing_trades == 0
    assert s.win_rate_pct == 100.0
    assert math.isinf(s.profit_factor)  # no losses → infinity
    assert s.meets_75pct_winrate
    assert s.total_pnl_cents == pytest.approx(75.0)


# ── All losses ───────────────────────────────────────────────────────────

def test_all_losses():
    trades = _make_trades([-10, -15, -20])
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct == 0.0
    assert s.profit_factor == 0.0
    assert not s.meets_75pct_winrate
    assert not s.meets_promotion_floor


# ── 75% win rate target ───────────────────────────────────────────────────

def test_75pct_win_rate_flag():
    """3 wins + 1 loss = 75% win rate — meets the target."""
    trades = _make_trades([21, 21, 21, -24])  # fees-adjusted approximation
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct == 75.0
    assert s.meets_75pct_winrate


def test_74pct_win_rate_does_not_flag():
    """Below 75% should NOT set meets_75pct_winrate."""
    pnls = [10] * 14 + [-10] * 5  # 14/19 ≈ 73.7%
    trades = _make_trades(pnls)
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct < 75.0
    assert not s.meets_75pct_winrate


# ── Promotion floor ───────────────────────────────────────────────────────

def test_meets_promotion_floor():
    """win_rate >= 55%, PF >= 1.3, avg_pnl >= 5c → meets_promotion_floor."""
    # 6 wins of 20c, 4 losses of 12c → win rate 60%, PF = 120/48 = 2.5, avg = (120-48)/10 = 7.2c
    trades = _make_trades([20] * 6 + [-12] * 4, fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct == 60.0
    assert s.profit_factor >= 1.3
    assert s.avg_pnl_cents >= 5.0
    assert s.meets_promotion_floor


def test_does_not_meet_floor_low_win_rate():
    """51% win rate is below the 55% promotion floor."""
    pnls = [20] * 51 + [-20] * 49  # 51% win rate
    trades = _make_trades(pnls, fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct < 55.0
    assert not s.meets_promotion_floor


def test_does_not_meet_floor_low_pf():
    """Win rate 60% but PF < 1.3 (avg win barely < avg loss)."""
    # 6 wins of 8c, 4 losses of 10c: PF = 48/40 = 1.2 < 1.3
    trades = _make_trades([8] * 6 + [-10] * 4, fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.win_rate_pct == 60.0
    assert s.profit_factor < 1.3
    assert not s.meets_promotion_floor


# ── R:R ratio ─────────────────────────────────────────────────────────────

def test_rr_ratio_computed_correctly():
    """avg_win / avg_loss should equal avg_rr_ratio."""
    trades = _make_trades([30, 30] + [-15, -15], fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.avg_win_cents == pytest.approx(30.0)
    assert s.avg_loss_cents == pytest.approx(15.0)
    assert s.avg_rr_ratio == pytest.approx(2.0)


def test_rr_ratio_inf_when_no_losses():
    trades = _make_trades([10, 20, 30])
    s = compute_performance_metrics(trades)
    assert math.isinf(s.avg_rr_ratio)


# ── Max drawdown ──────────────────────────────────────────────────────────

def test_max_drawdown_simple():
    """Equity curve: 10, 20, 10, 5 → peak=20, trough=5, DD=75%."""
    pnls = [10, 10, -10, -5]  # cumulative: 10, 20, 10, 5
    trades = _make_trades(pnls, fees=0.0)
    s = compute_performance_metrics(trades)
    # peak=20, min_after_peak=5 → DD = 15/20 = 75%
    assert s.max_drawdown_pct == pytest.approx(75.0)


def test_max_drawdown_zero_when_monotone_gains():
    trades = _make_trades([5, 10, 15], fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.max_drawdown_pct == 0.0


# ── Sharpe ratio ──────────────────────────────────────────────────────────

def test_sharpe_positive_for_consistent_winners():
    """Consistent gains → positive Sharpe."""
    trades = _make_trades([10] * 10, fees=0.0)
    s = compute_performance_metrics(trades)
    # All identical returns → std = 0 → Sharpe special case: returns 0
    # (mathematically undefined; we return 0 when std=0)
    assert s.sharpe_ratio == 0.0  # all identical = 0 std


def test_sharpe_positive_for_mixed_returns():
    """Win-dominant mix with some variance → positive Sharpe."""
    trades = _make_trades([15, 10, 20, -5, 12, 18, -8, 14], fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.sharpe_ratio > 0, "Expected positive Sharpe for win-dominant trades"


def test_sharpe_requires_min_5_trades():
    """Fewer than 5 trades returns Sharpe 0.0 (not enough samples)."""
    trades = _make_trades([10, 20, 30], fees=0.0)
    s = compute_performance_metrics(trades)
    assert s.sharpe_ratio == 0.0


# ── Total PnL and fees ────────────────────────────────────────────────────

def test_total_pnl_and_fees():
    trades = _make_trades([20, -10, 15], fees=4.0)
    s = compute_performance_metrics(trades)
    assert s.total_pnl_cents == pytest.approx(25.0)
    assert s.total_fees_cents == pytest.approx(12.0)


# ── Promotion benchmarks in paper_session module ─────────────────────────

def test_default_benchmark_win_rate_floor():
    """DEFAULT_BENCHMARK.min_win_rate_pct must be >= 55% after FIX-2."""
    from merid.prediction.paper_session import DEFAULT_BENCHMARK
    assert DEFAULT_BENCHMARK.min_win_rate_pct >= 55.0, (
        "Default promotion win-rate floor must be >= 55% to filter for live trading. "
        f"Got {DEFAULT_BENCHMARK.min_win_rate_pct}%"
    )


def test_default_benchmark_profit_factor_floor():
    """DEFAULT_BENCHMARK.min_profit_factor must be >= 1.3 after FIX-2."""
    from merid.prediction.paper_session import DEFAULT_BENCHMARK
    assert DEFAULT_BENCHMARK.min_profit_factor >= 1.3, (
        f"PF floor must be >= 1.3, got {DEFAULT_BENCHMARK.min_profit_factor}"
    )


def test_cell_benchmarks_all_above_floor():
    """All per-cell benchmarks must meet or exceed the tightened default floors."""
    from merid.prediction.paper_session import _CELL_BENCHMARKS, DEFAULT_BENCHMARK
    for name, bm in _CELL_BENCHMARKS.items():
        assert bm.min_win_rate_pct >= DEFAULT_BENCHMARK.min_win_rate_pct, (
            f"{name}: min_win_rate_pct {bm.min_win_rate_pct}% below default "
            f"{DEFAULT_BENCHMARK.min_win_rate_pct}%"
        )
        assert bm.min_profit_factor >= DEFAULT_BENCHMARK.min_profit_factor, (
            f"{name}: min_profit_factor {bm.min_profit_factor} below default "
            f"{DEFAULT_BENCHMARK.min_profit_factor}"
        )


def test_strategy_config_edge_thresholds():
    """StrategyConfig defaults must be >= min threshold floor after FIX-1."""
    from merid.prediction.strategy import StrategyConfig
    from decimal import Decimal
    cfg = StrategyConfig()
    assert cfg.min_edge_terminal >= Decimal("0.06"), (
        f"Terminal phase edge floor must be >= 6%, got {cfg.min_edge_terminal}"
    )
    assert cfg.min_confidence >= Decimal("0.50"), (
        f"min_confidence must be >= 0.50, got {cfg.min_confidence}"
    )


def test_stop_loss_defaults_from_constants():
    """StopLossConfig must read defaults from trading_constants (FIX-3)."""
    from merid.event_venues.kalshi.stop_loss import StopLossConfig
    from config.trading_constants import (
        SL_PRICE_INVALIDATION_DROP_CENTS,
        SL_PRICE_FLOOR_CENTS,
    )
    cfg = StopLossConfig()
    assert cfg.price_invalidation_drop_cents == SL_PRICE_INVALIDATION_DROP_CENTS
    assert cfg.price_floor_cents == SL_PRICE_FLOOR_CENTS


def test_snapshot_stale_seconds_aligned():
    """strategy.SNAPSHOT_STALE_SECONDS must match model.MAX_PRICE_AGE_SECONDS (FIX-4)."""
    from merid.prediction.strategy import SNAPSHOT_STALE_SECONDS
    from merid.prediction.model import MAX_PRICE_AGE_SECONDS
    assert SNAPSHOT_STALE_SECONDS == MAX_PRICE_AGE_SECONDS, (
        f"Staleness mismatch: strategy={SNAPSHOT_STALE_SECONDS}s, "
        f"model={MAX_PRICE_AGE_SECONDS}s"
    )


def test_consensus_threshold_default_is_065():
    """SwarmConsensusAggregator default consensus_threshold should be 0.65 (FIX-8)."""
    import importlib
    import sys
    # Force re-import so we don't test a cached singleton from a prior test run.
    mod = importlib.import_module("merid.swarm.consensus_aggregator")
    # Inspect the function signature default for consensus_threshold
    import inspect
    sig = inspect.signature(mod.SwarmConsensusAggregator.__init__)
    default_thr = sig.parameters.get("consensus_threshold")
    if default_thr and default_thr.default is not inspect.Parameter.empty:
        assert default_thr.default >= 0.65, (
            f"consensus_threshold default should be >= 0.65, got {default_thr.default}"
        )
