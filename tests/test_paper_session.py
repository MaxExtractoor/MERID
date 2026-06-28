"""Tests for merid.prediction.paper_session — Paper Session Runner.

LEGACY: This module tests PaperSession, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2).

Covers:
- Session lifecycle (start, resume, persistence)
- Fill recording and PnL tracking
- Error and circuit breaker recording
- Readiness benchmark checks
- Coverage metrics
- Paper→live promotion and demotion
- IntervalPnL computed properties
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.legacy

from merid.prediction.paper_session import (
    ASSET_CLUSTERS,
    CRYPTO_ASSETS,
    CRYPTO_TIMEFRAMES,
    DEFAULT_BENCHMARK,
    DEFAULT_RISK_LIMITS,
    IntervalPnL,
    PaperSession,
    ReadinessBenchmark,
    ReadinessVerdict,
    SessionRiskLimits,
    _CELL_BENCHMARKS,
    crypto_agent_names,
    get_benchmark_for,
    get_paper_session,
)


# ── Helpers ────────────────────────────────────────────────────────────

# Relaxed risk limits for tests that don't test risk governance
_RELAXED_RISK = SessionRiskLimits(
    max_daily_loss_cents=999999.0,
    max_weekly_loss_cents=999999.0,
    max_cluster_daily_loss_cents=999999.0,
    drawdown_warning_pct=999.0,
    drawdown_downsize_pct=999.0,
    drawdown_halt_pct=999.0,
)


@pytest.fixture
def session(tmp_path):
    """Create a fresh PaperSession with temp persistence and relaxed risk."""
    persist = tmp_path / "paper_session_state.json"
    with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
        s = PaperSession(risk_limits=_RELAXED_RISK)
        yield s


@pytest.fixture
def started_session(session):
    """Session that has been started."""
    session.start_session("test-session-001")
    return session


# ── crypto_agent_names ─────────────────────────────────────────────────

class TestCryptoAgentNames:
    def test_count(self):
        names = crypto_agent_names()
        assert len(names) == 20  # 5 assets × 4 timeframes

    def test_all_assets_covered(self):
        names = crypto_agent_names()
        for asset in CRYPTO_ASSETS:
            asset_names = [n for n in names if n.startswith(f"{asset}_")]
            assert len(asset_names) == 4, f"{asset} should have 4 timeframes"

    def test_all_timeframes_covered(self):
        names = crypto_agent_names()
        tf_labels = {"15M", "HOURLY", "DAILY", "WEEKLY"}
        for label in tf_labels:
            matching = [n for n in names if n.endswith(f"_{label}")]
            assert len(matching) == 5, f"{label} should cover 5 assets"

    def test_specific_names(self):
        names = crypto_agent_names()
        assert "BTC_15M" in names
        assert "ETH_HOURLY" in names
        assert "SOL_DAILY" in names
        assert "XRP_WEEKLY" in names
        assert "DOGE_15M" in names


# ── IntervalPnL ───────────────────────────────────────────────────────

class TestIntervalPnL:
    def test_win_rate_no_trades(self):
        i = IntervalPnL(asset="BTC", timeframe="15m", agent_name="BTC_15M")
        assert i.win_rate_pct == 0.0

    def test_win_rate_with_trades(self):
        i = IntervalPnL(
            asset="BTC", timeframe="15m", agent_name="BTC_15M",
            winning_trades=7, losing_trades=3,
        )
        assert i.win_rate_pct == 70.0

    def test_net_pnl_usd(self):
        i = IntervalPnL(
            asset="ETH", timeframe="1h", agent_name="ETH_HOURLY",
            net_pnl_cents=1500.0,
        )
        assert i.net_pnl_usd == 15.0

    def test_drawdown_pct(self):
        i = IntervalPnL(
            asset="SOL", timeframe="daily", agent_name="SOL_DAILY",
            high_water_mark_cents=1000.0, max_drawdown_cents=100.0,
        )
        assert i.drawdown_pct == 10.0

    def test_drawdown_pct_zero_hwm(self):
        i = IntervalPnL(asset="SOL", timeframe="daily", agent_name="SOL_DAILY")
        assert i.drawdown_pct == 0.0

    def test_error_rate(self):
        i = IntervalPnL(
            asset="XRP", timeframe="weekly", agent_name="XRP_WEEKLY",
            total_trades=100, errors=3,
        )
        assert i.error_rate_pct == 3.0

    def test_error_rate_no_trades(self):
        i = IntervalPnL(asset="XRP", timeframe="weekly", agent_name="XRP_WEEKLY")
        assert i.error_rate_pct == 0.0

    def test_to_dict(self):
        i = IntervalPnL(
            asset="DOGE", timeframe="15m", agent_name="DOGE_15M",
            total_trades=10, winning_trades=6, losing_trades=4,
            net_pnl_cents=500.0, gross_wins_cents=600.0, gross_losses_cents=100.0,
        )
        d = i.to_dict()
        assert d["asset"] == "DOGE"
        assert d["win_rate_pct"] == 60.0
        assert d["net_pnl_usd"] == 5.0
        assert "error_rate_pct" in d
        assert "expectancy_cents" in d
        assert "avg_win_cents" in d
        assert "avg_loss_cents" in d


# ── Session lifecycle ──────────────────────────────────────────────────

class TestSessionLifecycle:
    def test_start_creates_intervals(self, session):
        sid = session.start_session("test-001")
        assert sid == "test-001"
        assert session.is_active
        assert len(session._intervals) == 20

    def test_start_idempotent(self, session):
        sid1 = session.start_session("test-001")
        sid2 = session.start_session("test-002")
        assert sid1 == sid2  # Second call doesn't overwrite

    def test_session_hours(self, session):
        session.start_session()
        assert session.session_hours >= 0.0

    def test_not_active_before_start(self, session):
        assert not session.is_active
        assert session.session_hours == 0.0


# ── Fill recording ─────────────────────────────────────────────────────

class TestFillRecording:
    def test_record_winning_fill(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=100.0, fees_cents=7.0, won=True)
        interval = s._intervals["BTC_15M"]
        assert interval.total_trades == 1
        assert interval.winning_trades == 1
        assert interval.gross_pnl_cents == 100.0
        assert interval.fees_cents == 7.0
        assert interval.net_pnl_cents == 93.0

    def test_record_losing_fill(self, started_session):
        s = started_session
        s.record_fill("ETH_HOURLY", pnl_cents=-50.0, fees_cents=3.5, won=False)
        interval = s._intervals["ETH_HOURLY"]
        assert interval.total_trades == 1
        assert interval.losing_trades == 1
        assert interval.net_pnl_cents == -53.5

    def test_auto_detect_win(self, started_session):
        s = started_session
        s.record_fill("SOL_DAILY", pnl_cents=200.0)
        assert s._intervals["SOL_DAILY"].winning_trades == 1

    def test_auto_detect_loss(self, started_session):
        s = started_session
        s.record_fill("SOL_DAILY", pnl_cents=-100.0)
        assert s._intervals["SOL_DAILY"].losing_trades == 1

    def test_hwm_and_drawdown(self, started_session):
        s = started_session
        s.record_fill("BTC_DAILY", pnl_cents=500.0)
        s.record_fill("BTC_DAILY", pnl_cents=-200.0)
        interval = s._intervals["BTC_DAILY"]
        assert interval.high_water_mark_cents == 500.0
        assert interval.max_drawdown_cents == 200.0

    def test_multiple_fills_accumulate(self, started_session):
        s = started_session
        for _ in range(5):
            s.record_fill("DOGE_15M", pnl_cents=10.0, won=True)
        for _ in range(3):
            s.record_fill("DOGE_15M", pnl_cents=-5.0, won=False)
        interval = s._intervals["DOGE_15M"]
        assert interval.total_trades == 8
        assert interval.winning_trades == 5
        assert interval.losing_trades == 3

    def test_unknown_agent_ignored(self, started_session):
        s = started_session
        s.record_fill("UNKNOWN_AGENT", pnl_cents=100.0)
        assert "UNKNOWN_AGENT" not in s._intervals

    def test_first_and_last_trade_timestamps(self, started_session):
        s = started_session
        s.record_fill("XRP_WEEKLY", pnl_cents=50.0)
        interval = s._intervals["XRP_WEEKLY"]
        assert interval.first_trade_at is not None
        assert interval.last_trade_at is not None


# ── Error and CB recording ─────────────────────────────────────────────

class TestErrorRecording:
    def test_record_error(self, started_session):
        s = started_session
        s.record_error("BTC_15M")
        s.record_error("BTC_15M")
        assert s._intervals["BTC_15M"].errors == 2

    def test_record_circuit_breaker_trip(self, started_session):
        s = started_session
        s.record_circuit_breaker_trip("ETH_DAILY")
        assert s._intervals["ETH_DAILY"].circuit_breaker_trips == 1


# ── Readiness checks ──────────────────────────────────────────────────

class TestReadinessChecks:
    def test_not_ready_no_trades(self, started_session):
        verdict = started_session.check_readiness("BTC_15M")
        assert not verdict.ready
        assert verdict.checks["min_trades"] is False

    def test_not_ready_unknown_agent(self, started_session):
        verdict = started_session.check_readiness("NONEXISTENT")
        assert not verdict.ready
        assert "exists" in verdict.checks

    def test_ready_after_meeting_benchmarks(self, tmp_path):
        persist = tmp_path / "paper_session_state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            benchmark = ReadinessBenchmark(
                min_trades=10,
                min_win_rate_pct=40.0,
                max_error_rate_pct=10.0,
                min_session_hours=0.0,
                max_drawdown_pct=20.0,
                min_profit_factor=1.0,
                min_expectancy_cents=0.0,
                max_circuit_breaker_trips=0,
            )
            s = PaperSession(benchmark=benchmark)
            s.start_session()

            for _ in range(8):
                s.record_fill("BTC_15M", pnl_cents=50.0, won=True)
            for _ in range(4):
                s.record_fill("BTC_15M", pnl_cents=-20.0, won=False)

            # Use explicit benchmark override to bypass per-cell override for BTC_15M
            verdict = s.check_readiness("BTC_15M", benchmark_override=benchmark)
            assert verdict.checks["min_trades"] is True
            assert verdict.checks["win_rate"] is True
            assert verdict.checks["error_rate"] is True
            assert verdict.checks["expectancy"] is True
            assert verdict.checks["circuit_breaker"] is True
            assert verdict.ready is True

    def test_readiness_has_expectancy_check(self, started_session):
        """Verify the 8th gate (expectancy) is present."""
        verdict = started_session.check_readiness("BTC_15M")
        assert "expectancy" in verdict.checks

    def test_check_all_readiness(self, started_session):
        verdicts = started_session.check_all_readiness()
        assert len(verdicts) == 20
        assert all(not v.ready for v in verdicts.values())

    def test_verdict_to_dict(self, started_session):
        verdict = started_session.check_readiness("BTC_15M")
        d = verdict.to_dict()
        assert "agent_name" in d
        assert "ready" in d
        assert "checks" in d
        assert "details" in d


# ── Promotion / demotion ───────────────────────────────────────────────

class TestPromotion:
    def test_promote_fails_without_readiness(self, started_session):
        result = started_session.promote_to_live("BTC_15M")
        assert result["promoted"] is False
        assert "Readiness checks failed" in result["reason"]

    def test_promote_force(self, started_session):
        result = started_session.promote_to_live("BTC_15M", force=True)
        assert result["promoted"] is True
        assert started_session.is_live("BTC_15M")
        assert "BTC_15M" in started_session.live_agents

    def test_demote(self, started_session):
        started_session.promote_to_live("ETH_HOURLY", force=True)
        assert started_session.is_live("ETH_HOURLY")
        result = started_session.demote_to_paper("ETH_HOURLY")
        assert result["demoted"] is True
        assert not started_session.is_live("ETH_HOURLY")

    def test_demote_not_live(self, started_session):
        result = started_session.demote_to_paper("SOL_DAILY")
        assert result["demoted"] is True  # Idempotent


# ── Coverage metrics ───────────────────────────────────────────────────

class TestCoverageMetrics:
    def test_empty_coverage(self, started_session):
        cov = started_session.coverage_summary()
        assert cov["total_cells"] == 20
        assert cov["active_cells"] == 0
        assert cov["coverage_pct"] == 0.0

    def test_partial_coverage(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=10.0)
        s.record_fill("ETH_HOURLY", pnl_cents=20.0)
        s.record_fill("SOL_DAILY", pnl_cents=30.0)
        cov = s.coverage_summary()
        assert cov["active_cells"] == 3
        assert cov["coverage_pct"] == 15.0

    def test_by_asset_breakdown(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=100.0)
        s.record_fill("BTC_HOURLY", pnl_cents=200.0)
        cov = s.coverage_summary()
        assert cov["by_asset"]["BTC"]["active"] == 2
        assert cov["by_asset"]["BTC"]["total_trades"] == 2

    def test_by_timeframe_breakdown(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=100.0)
        s.record_fill("ETH_15M", pnl_cents=200.0)
        s.record_fill("SOL_15M", pnl_cents=50.0)
        cov = s.coverage_summary()
        assert cov["by_timeframe"]["15m"]["active"] == 3
        assert cov["by_timeframe"]["15m"]["total_trades"] == 3


# ── Summary ────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=100.0)
        summary = s.summary()
        assert summary["session_id"] == "test-session-001"
        assert summary["active"] is True
        assert "totals" in summary
        assert "coverage" in summary
        assert "readiness" in summary
        assert "intervals" in summary
        assert "benchmark" in summary
        assert "live_promoted" in summary

    def test_summary_totals(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=100.0, fees_cents=7.0)
        s.record_fill("ETH_HOURLY", pnl_cents=-50.0, fees_cents=3.5)
        s.record_error("ETH_HOURLY")
        totals = s.summary()["totals"]
        assert totals["trades"] == 2
        assert totals["errors"] == 1


# ── Persistence ────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_restore(self, tmp_path):
        persist = tmp_path / "paper_session_state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s1 = PaperSession()
            s1.start_session("persist-test")
            s1.record_fill("BTC_15M", pnl_cents=100.0, won=True)
            s1.record_fill("ETH_HOURLY", pnl_cents=-50.0, won=False)
            s1.promote_to_live("SOL_DAILY", force=True)

        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s2 = PaperSession()
            assert s2._session_id == "persist-test"
            assert s2._intervals["BTC_15M"].total_trades == 1
            assert s2._intervals["BTC_15M"].winning_trades == 1
            assert s2._intervals["ETH_HOURLY"].losing_trades == 1
            assert "SOL_DAILY" in s2._live_promoted

    def test_persist_file_created(self, tmp_path):
        persist = tmp_path / "paper_session_state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s = PaperSession()
            s.start_session()
            assert persist.exists()
            data = json.loads(persist.read_text())
            assert "intervals" in data
            assert "session_id" in data


# ── Expectancy ─────────────────────────────────────────────────────────

class TestExpectancy:
    def test_expectancy_no_trades(self):
        i = IntervalPnL(asset="BTC", timeframe="15m", agent_name="BTC_15M")
        assert i.expectancy_cents == 0.0

    def test_expectancy_all_wins(self):
        i = IntervalPnL(
            asset="BTC", timeframe="15m", agent_name="BTC_15M",
            winning_trades=10, losing_trades=0,
            gross_wins_cents=500.0, gross_losses_cents=0.0,
        )
        # win_rate=1.0, avg_win=50, loss_rate=0 → expectancy = 50
        assert i.expectancy_cents == 50.0

    def test_expectancy_mixed(self):
        i = IntervalPnL(
            asset="ETH", timeframe="1h", agent_name="ETH_HOURLY",
            winning_trades=6, losing_trades=4,
            gross_wins_cents=300.0, gross_losses_cents=200.0,
        )
        # wr=0.6, avg_win=50, lr=0.4, avg_loss=50
        # expectancy = 0.6*50 - 0.4*50 = 30 - 20 = 10
        assert abs(i.expectancy_cents - 10.0) < 0.01

    def test_expectancy_negative(self):
        i = IntervalPnL(
            asset="SOL", timeframe="15m", agent_name="SOL_15M",
            winning_trades=3, losing_trades=7,
            gross_wins_cents=90.0, gross_losses_cents=350.0,
        )
        # wr=0.3, avg_win=30, lr=0.7, avg_loss=50
        # expectancy = 0.3*30 - 0.7*50 = 9 - 35 = -26
        assert i.expectancy_cents < 0
        assert abs(i.expectancy_cents - (-26.0)) < 0.01

    def test_expectancy_usd(self):
        i = IntervalPnL(
            asset="BTC", timeframe="1h", agent_name="BTC_HOURLY",
            winning_trades=5, losing_trades=5,
            gross_wins_cents=1000.0, gross_losses_cents=500.0,
        )
        # wr=0.5, avg_win=200, avg_loss=100 → exp = 0.5*200 - 0.5*100 = 50c
        assert abs(i.expectancy_usd - 0.50) < 0.01

    def test_avg_win_loss(self):
        i = IntervalPnL(
            asset="XRP", timeframe="daily", agent_name="XRP_DAILY",
            winning_trades=4, losing_trades=6,
            gross_wins_cents=400.0, gross_losses_cents=300.0,
        )
        assert i.avg_win_cents == 100.0
        assert i.avg_loss_cents == 50.0


# ── Per-cell benchmark overrides ───────────────────────────────────────

class TestCellBenchmarks:
    def test_btc_hourly_has_override(self):
        b = get_benchmark_for("BTC_HOURLY")
        # Updated thresholds: PF 1.4→1.5, expectancy 15→18c (FIX-2)
        assert b.min_profit_factor == 1.5
        assert b.min_expectancy_cents == 18.0
        assert b.min_trades == 100

    def test_sol_15m_strictest(self):
        b = get_benchmark_for("SOL_15M")
        # Updated thresholds: PF 1.5→1.6, expectancy 20→22c (FIX-2)
        assert b.min_profit_factor == 1.6
        assert b.min_expectancy_cents == 22.0
        assert b.max_drawdown_pct == 5.0
        assert b.min_daily_trades == 30

    def test_fallback_to_default(self):
        b = get_benchmark_for("DOGE_WEEKLY")
        assert b is DEFAULT_BENCHMARK

    def test_readiness_uses_cell_override(self, tmp_path):
        """BTC_HOURLY should use its stricter PF=1.4 benchmark."""
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s = PaperSession(risk_limits=_RELAXED_RISK)
            s.start_session()
            for _ in range(60):
                s.record_fill("BTC_HOURLY", pnl_cents=10.0, won=True)
            for _ in range(40):
                s.record_fill("BTC_HOURLY", pnl_cents=-8.0, won=False)
            verdict = s.check_readiness("BTC_HOURLY")
            # PF = 600/320 ≈ 1.875 → passes 1.4
            assert verdict.checks["profit_factor"] is True
            # min_trades=100 and we have 100 → passes
            assert verdict.checks["min_trades"] is True


# ── Coverage gap alerts ────────────────────────────────────────────────

class TestCoverageGapAlerts:
    def test_all_gaps_when_no_trades(self, started_session):
        gaps = started_session.coverage_gap_alerts(min_daily_trades=10)
        assert len(gaps) == 20  # All cells under-utilised

    def test_no_gaps_when_sufficient_trades(self, tmp_path):
        persist = tmp_path / "paper_session_state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            b = ReadinessBenchmark(min_daily_trades=0)
            s = PaperSession(benchmark=b)
            s.start_session()
            for name in crypto_agent_names():
                for _ in range(50):
                    s.record_fill(name, pnl_cents=5.0)
            gaps = s.coverage_gap_alerts(min_daily_trades=1)
            # Session is very short but has many trades
            assert len(gaps) < 20

    def test_gap_sorted_by_deficit(self, started_session):
        s = started_session
        s.record_fill("BTC_15M", pnl_cents=10.0)  # 1 trade
        # ETH_15M has 0 trades
        gaps = s.coverage_gap_alerts(min_daily_trades=10)
        # Both should be in gaps, but ETH_15M has higher deficit
        agents_in_gaps = [g["agent"] for g in gaps]
        assert "ETH_15M" in agents_in_gaps

    def test_gap_uses_cell_benchmark(self, started_session):
        """SOL_15M has min_daily_trades=30 from its cell benchmark."""
        gaps = started_session.coverage_gap_alerts(min_daily_trades=5)
        sol_gap = next((g for g in gaps if g["agent"] == "SOL_15M"), None)
        assert sol_gap is not None
        # SOL_15M's cell benchmark has min_daily_trades=30, not the default 5
        assert sol_gap["expected"] > 0


# ── Health alerts ──────────────────────────────────────────────────────

class TestHealthAlerts:
    def test_no_alerts_when_healthy(self, started_session):
        s = started_session
        for _ in range(20):
            s.record_fill("BTC_15M", pnl_cents=50.0, won=True)
        for _ in range(5):
            s.record_fill("BTC_15M", pnl_cents=-10.0, won=False)
        alerts = s.health_alerts()
        btc_alerts = [a for a in alerts if a["agent"] == "BTC_15M"]
        assert len(btc_alerts) == 0  # PF > 1.1, expectancy > 0

    def test_low_pf_alert(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s = PaperSession(risk_limits=_RELAXED_RISK)
            s.start_session()
            for _ in range(5):
                s.record_fill("ETH_DAILY", pnl_cents=10.0, won=True)
            for _ in range(10):
                s.record_fill("ETH_DAILY", pnl_cents=-15.0, won=False)
            alerts = s.health_alerts()
            pf_alerts = [a for a in alerts if a["agent"] == "ETH_DAILY" and a["type"] == "low_profit_factor"]
            assert len(pf_alerts) == 1
            assert pf_alerts[0]["level"] == "critical"  # PF < 1.0

    def test_negative_expectancy_alert(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s = PaperSession(risk_limits=_RELAXED_RISK)
            s.start_session()
            for _ in range(3):
                s.record_fill("XRP_WEEKLY", pnl_cents=10.0, won=True)
            for _ in range(12):
                s.record_fill("XRP_WEEKLY", pnl_cents=-20.0, won=False)
            alerts = s.health_alerts()
            exp_alerts = [a for a in alerts if a["agent"] == "XRP_WEEKLY" and a["type"] == "negative_expectancy"]
            assert len(exp_alerts) == 1
            assert exp_alerts[0]["level"] == "critical"

    def test_skips_cells_with_few_trades(self, started_session):
        s = started_session
        # Only 5 trades — below the 10-trade minimum for alerts
        for _ in range(5):
            s.record_fill("DOGE_WEEKLY", pnl_cents=-100.0, won=False)
        alerts = s.health_alerts()
        doge_alerts = [a for a in alerts if a["agent"] == "DOGE_WEEKLY"]
        assert len(doge_alerts) == 0

    def test_alerts_sorted_critical_first(self, started_session):
        s = started_session
        # Create a critical alert (PF < 1.0)
        for _ in range(5):
            s.record_fill("ETH_DAILY", pnl_cents=10.0, won=True)
        for _ in range(10):
            s.record_fill("ETH_DAILY", pnl_cents=-15.0, won=False)
        # Create a warning (high error rate)
        for _ in range(20):
            s.record_fill("BTC_DAILY", pnl_cents=50.0, won=True)
        for _ in range(10):
            s.record_error("BTC_DAILY")
        alerts = s.health_alerts()
        if len(alerts) >= 2:
            levels = [a["level"] for a in alerts]
            # All criticals should come before warnings
            critical_indices = [i for i, l in enumerate(levels) if l == "critical"]
            warning_indices = [i for i, l in enumerate(levels) if l == "warning"]
            if critical_indices and warning_indices:
                assert max(critical_indices) < min(warning_indices)


# ── Promotion candidates ───────────────────────────────────────────────

class TestPromotionCandidates:
    def test_all_not_ready_initially(self, started_session):
        candidates = started_session.promotion_candidates()
        assert len(candidates) == 20
        assert all(c["tier"] == "not_ready" for c in candidates)

    def test_candidate_structure(self, started_session):
        candidates = started_session.promotion_candidates()
        c = candidates[0]
        assert "agent" in c
        assert "tier" in c
        assert "profit_factor" in c
        assert "expectancy_cents" in c
        assert "benchmark_pf" in c
        assert "verdict" in c

    def test_sorted_ready_first(self, tmp_path):
        persist = tmp_path / "paper_session_state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            b = ReadinessBenchmark(
                min_trades=5, min_win_rate_pct=0.0, max_error_rate_pct=100.0,
                min_session_hours=0.0, max_drawdown_pct=100.0,
                min_profit_factor=0.5, min_expectancy_cents=-999.0,
                max_circuit_breaker_trips=999,
            )
            s = PaperSession(benchmark=b)
            s.start_session()
            # Make DOGE_WEEKLY pass all checks
            for _ in range(10):
                s.record_fill("DOGE_WEEKLY", pnl_cents=100.0, won=True)
            candidates = s.promotion_candidates()
            # DOGE_WEEKLY should be first (ready tier)
            assert candidates[0]["agent"] == "DOGE_WEEKLY"
            assert candidates[0]["tier"] == "ready"


# ── Nightly report ─────────────────────────────────────────────────────

class TestNightlyReport:
    def test_report_structure(self, started_session):
        report = started_session.nightly_report()
        assert "timestamp" in report
        assert "session_hours" in report
        assert "candidates" in report
        assert "ready_count" in report
        assert "close_count" in report
        assert "health_alerts" in report
        assert "coverage_gaps" in report

    def test_report_counts(self, started_session):
        report = started_session.nightly_report()
        assert report["ready_count"] == 0
        assert len(report["candidates"]) == 20
        assert len(report["coverage_gaps"]) == 20  # All cells have 0 trades


# ── Daily loss cap ─────────────────────────────────────────────────────

class TestDailyLossCap:
    def test_halt_on_daily_loss(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(max_daily_loss_cents=100.0)
            s = PaperSession(risk_limits=rl)
            s.start_session()
            # Lose $1 total (100c) in one fill
            result = s.record_fill("BTC_15M", pnl_cents=-100.0, won=False)
            assert result["accepted"] is True
            assert s.is_halted("BTC_15M")
            # Next fill should be rejected
            result2 = s.record_fill("BTC_15M", pnl_cents=50.0, won=True)
            assert result2["accepted"] is False
            assert result2["reason"] == "cell_halted"

    def test_daily_counter_rolls(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(max_daily_loss_cents=500.0)
            s = PaperSession(risk_limits=rl)
            s.start_session()
            s.record_fill("ETH_HOURLY", pnl_cents=-200.0, won=False)
            interval = s._intervals["ETH_HOURLY"]
            assert interval.daily_loss_cents == 200.0
            assert interval.daily_reset_date is not None

    def test_winning_fills_dont_add_to_daily_loss(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(max_daily_loss_cents=500.0)
            s = PaperSession(risk_limits=rl)
            s.start_session()
            s.record_fill("SOL_DAILY", pnl_cents=100.0, won=True)
            assert s._intervals["SOL_DAILY"].daily_loss_cents == 0.0


# ── Weekly loss cap ────────────────────────────────────────────────────

class TestWeeklyLossCap:
    def test_halt_on_weekly_loss(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(
                max_daily_loss_cents=99999.0,  # high so daily doesn't trigger
                max_weekly_loss_cents=200.0,
                drawdown_warning_pct=999.0,    # suppress DD governance
                drawdown_downsize_pct=999.0,
                drawdown_halt_pct=999.0,
            )
            s = PaperSession(risk_limits=rl)
            s.start_session()
            s.record_fill("XRP_WEEKLY", pnl_cents=-100.0, won=False)
            assert not s.is_halted("XRP_WEEKLY")
            s.record_fill("XRP_WEEKLY", pnl_cents=-100.0, won=False)
            assert s.is_halted("XRP_WEEKLY")


# ── Cluster cap ────────────────────────────────────────────────────────

class TestClusterCap:
    def test_btc_eth_cluster_halt(self, tmp_path):
        """BTC + ETH losses combined should trigger cluster halt."""
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(
                max_daily_loss_cents=99999.0,
                max_weekly_loss_cents=99999.0,
                max_cluster_daily_loss_cents=300.0,
                drawdown_warning_pct=999.0,    # suppress DD governance
                drawdown_downsize_pct=999.0,
                drawdown_halt_pct=999.0,
            )
            s = PaperSession(risk_limits=rl)
            s.start_session()
            # BTC loses 200c across two cells
            s.record_fill("BTC_15M", pnl_cents=-100.0, won=False)
            s.record_fill("BTC_HOURLY", pnl_cents=-100.0, won=False)
            assert not s.is_halted("BTC_15M")
            # ETH loses 100c → cluster total = 300c → triggers
            s.record_fill("ETH_HOURLY", pnl_cents=-100.0, won=False)
            # All BTC and ETH cells should be halted
            assert s.is_halted("ETH_HOURLY")
            assert s.is_halted("BTC_15M")
            assert s.is_halted("BTC_HOURLY")
            # SOL should NOT be halted (different cluster)
            assert not s.is_halted("SOL_15M")

    def test_alt_basket_cluster(self):
        assert "SOL" in ASSET_CLUSTERS["ALT_BASKET"]
        assert "XRP" in ASSET_CLUSTERS["ALT_BASKET"]
        assert "DOGE" in ASSET_CLUSTERS["ALT_BASKET"]


# ── Drawdown governance ───────────────────────────────────────────────

class TestDrawdownGovernance:
    def test_downsize_at_threshold(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(
                max_daily_loss_cents=99999.0,
                max_weekly_loss_cents=99999.0,
                max_cluster_daily_loss_cents=99999.0,
                drawdown_downsize_pct=8.0,
                drawdown_halt_pct=12.0,
            )
            s = PaperSession(risk_limits=rl)
            s.start_session()
            # Build up HWM then draw down
            s.record_fill("DOGE_15M", pnl_cents=1000.0, won=True)
            # Now lose enough to hit 8% DD (80c of 1000c HWM)
            s.record_fill("DOGE_15M", pnl_cents=-80.0, won=False)
            assert s.is_downsized("DOGE_15M")
            assert not s.is_halted("DOGE_15M")
            assert s.get_size_factor("DOGE_15M") == rl.downsize_factor

    def test_halt_at_severe_drawdown(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(
                max_daily_loss_cents=99999.0,
                max_weekly_loss_cents=99999.0,
                max_cluster_daily_loss_cents=99999.0,
                drawdown_downsize_pct=8.0,
                drawdown_halt_pct=12.0,
            )
            s = PaperSession(risk_limits=rl)
            s.start_session()
            s.record_fill("DOGE_DAILY", pnl_cents=1000.0, won=True)
            # Lose 120c → 12% DD from 1000c HWM
            s.record_fill("DOGE_DAILY", pnl_cents=-120.0, won=False)
            assert s.is_halted("DOGE_DAILY")
            assert s.get_size_factor("DOGE_DAILY") == 0.0

    def test_warning_at_early_drawdown(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            rl = SessionRiskLimits(
                max_daily_loss_cents=99999.0,
                max_weekly_loss_cents=99999.0,
                max_cluster_daily_loss_cents=99999.0,
                drawdown_warning_pct=5.0,
                drawdown_downsize_pct=80.0,  # high so it doesn't trigger
                drawdown_halt_pct=90.0,
            )
            s = PaperSession(risk_limits=rl)
            s.start_session()
            s.record_fill("XRP_DAILY", pnl_cents=1000.0, won=True)
            result = s.record_fill("XRP_DAILY", pnl_cents=-50.0, won=False)
            # 5% DD → warning action
            assert result["accepted"] is True
            actions = result.get("risk_actions", [])
            warnings = [a for a in actions if a.get("type") == "drawdown_warning"]
            assert len(warnings) == 1


# ── Halt / unhalt controls ────────────────────────────────────────────

class TestHaltControls:
    def test_manual_halt(self, started_session):
        s = started_session
        assert s.halt_cell("BTC_15M", "testing")
        assert s.is_halted("BTC_15M")
        result = s.record_fill("BTC_15M", pnl_cents=100.0)
        assert result["accepted"] is False

    def test_unhalt(self, started_session):
        s = started_session
        s.halt_cell("ETH_HOURLY", "test")
        assert s.is_halted("ETH_HOURLY")
        s.unhalt_cell("ETH_HOURLY")
        assert not s.is_halted("ETH_HOURLY")
        assert not s.is_downsized("ETH_HOURLY")

    def test_unhalt_all(self, started_session):
        s = started_session
        s.halt_cell("BTC_15M")
        s.halt_cell("ETH_HOURLY")
        count = s.unhalt_all()
        assert count == 2
        assert not s.is_halted("BTC_15M")
        assert not s.is_halted("ETH_HOURLY")

    def test_halt_unknown_agent(self, started_session):
        assert not started_session.halt_cell("NONEXISTENT")

    def test_unhalt_unknown_agent(self, started_session):
        assert not started_session.unhalt_cell("NONEXISTENT")


# ── Size factor ────────────────────────────────────────────────────────

class TestSizeFactor:
    def test_normal_factor(self, started_session):
        assert started_session.get_size_factor("BTC_15M") == 1.0

    def test_halted_factor(self, started_session):
        started_session.halt_cell("BTC_15M")
        assert started_session.get_size_factor("BTC_15M") == 0.0

    def test_unknown_agent_factor(self, started_session):
        assert started_session.get_size_factor("NONEXISTENT") == 1.0


# ── Risk status ────────────────────────────────────────────────────────

class TestRiskStatus:
    def test_risk_status_structure(self, started_session):
        status = started_session.risk_status()
        assert "halted_cells" in status
        assert "halted_count" in status
        assert "downsized_cells" in status
        assert "clusters" in status
        assert "limits" in status
        assert "BTC_ETH" in status["clusters"]
        assert "ALT_BASKET" in status["clusters"]

    def test_risk_status_counts_halted(self, started_session):
        s = started_session
        s.halt_cell("BTC_15M")
        s.halt_cell("ETH_HOURLY")
        status = s.risk_status()
        assert status["halted_count"] == 2
        assert "BTC_15M" in status["halted_cells"]

    def test_cluster_utilization(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            # Use default risk limits so cluster cap is 10000c
            s = PaperSession(risk_limits=SessionRiskLimits(
                max_daily_loss_cents=999999.0,
                max_weekly_loss_cents=999999.0,
                max_cluster_daily_loss_cents=10000.0,
                drawdown_halt_pct=999.0,
                drawdown_downsize_pct=999.0,
                drawdown_warning_pct=999.0,
            ))
            s.start_session()
            s.record_fill("BTC_15M", pnl_cents=-100.0, won=False)
            status = s.risk_status()
            btc_eth = status["clusters"]["BTC_ETH"]
            assert btc_eth["daily_loss_cents"] == 100
            assert btc_eth["utilization_pct"] > 0


# ── Persistence of halt state ─────────────────────────────────────────

class TestHaltPersistence:
    def test_halt_survives_reload(self, tmp_path):
        persist = tmp_path / "state.json"
        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s1 = PaperSession()
            s1.start_session("halt-persist")
            s1.halt_cell("BTC_15M", "test halt")

        with patch("merid.prediction.paper_session._PERSIST_FILE", persist):
            s2 = PaperSession()
            assert s2._intervals["BTC_15M"].halted is True
            assert s2._intervals["BTC_15M"].halt_reason == "test halt"


# ── record_fill return value ─────────────────────────────────────────

class TestRecordFillReturn:
    def test_accepted_fill(self, started_session):
        result = started_session.record_fill("BTC_15M", pnl_cents=50.0)
        assert result["accepted"] is True
        assert "risk_actions" in result

    def test_unknown_agent_fill(self, started_session):
        result = started_session.record_fill("FAKE_AGENT", pnl_cents=50.0)
        assert result["accepted"] is False
        assert result["reason"] == "unknown_agent"


# ── Singleton ──────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_paper_session_returns_same_instance(self):
        import merid.prediction.paper_session as mod
        old = mod._session
        try:
            mod._session = None
            s1 = get_paper_session()
            s2 = get_paper_session()
            assert s1 is s2
        finally:
            mod._session = old
