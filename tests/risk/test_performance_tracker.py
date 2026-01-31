"""Risk-core tests for analytics performance tracking."""

from __future__ import annotations

import time

import pytest

from analytics.performance import PerformanceTracker


pytestmark = pytest.mark.risk_core


def test_record_trade_updates_win_loss_metrics() -> None:
    tracker = PerformanceTracker()

    trade = tracker.record_trade(
        trade_id="t1",
        symbol="BTC",
        side="long",
        entry_price=10_000.0,
        exit_price=11_000.0,
        quantity=1.0,
        entry_time=time.time() - 60,
        exit_time=time.time(),
        agent_source="agent-alpha",
    )

    summary = tracker.get_summary()
    assert trade.pnl == pytest.approx(1000.0)
    assert summary["total_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["win_rate"] == pytest.approx(100.0)


def test_record_snapshot_tracks_drawdown() -> None:
    tracker = PerformanceTracker()
    tracker.record_snapshot(
        equity=120_000.0,
        balance=120_000.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        open_positions=0,
    )
    tracker.record_snapshot(
        equity=100_000.0,
        balance=100_000.0,
        unrealized_pnl=-5_000.0,
        realized_pnl=0.0,
        open_positions=1,
    )

    summary = tracker.get_summary()
    assert summary["max_drawdown"] > 0


def test_agent_performance_breakdown() -> None:
    tracker = PerformanceTracker()
    now = time.time()

    tracker.record_trade(
        trade_id="t1",
        symbol="ETH",
        side="long",
        entry_price=2_000.0,
        exit_price=2_100.0,
        quantity=1.0,
        entry_time=now - 120,
        exit_time=now - 60,
        agent_source="agent-beta",
    )
    tracker.record_trade(
        trade_id="t2",
        symbol="ETH",
        side="short",
        entry_price=2_200.0,
        exit_price=2_250.0,
        quantity=1.0,
        entry_time=now - 60,
        exit_time=now,
        agent_source="agent-beta",
    )

    agent_stats = tracker.get_agent_performance()["agent-beta"]
    assert agent_stats["total_trades"] == 2
    assert agent_stats["total_pnl"] == pytest.approx(50.0)
