"""Regression tests for Agent Grid + Activity audit fixes.

Covers:
  1. KalshiTradingAgent.summary() includes config and performance data
  2. AgentPerformanceTracker._open_trades composite key (agent_id:market_id)
  3. record_close realized_edge is signed (not abs)
  4. record_outcome closes ALL matching trades for a settled market
  5. PaperSession._resolve_agent_name handles config names, agent_ids, canonical names
  6. PaperSession.record_fill accepts config-style and agent_id-style names
"""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ── 1. KalshiTradingAgent.summary() includes config + performance ──────

class TestTradingAgentSummary:
    """Verify summary() includes config and performance keys."""

    def _make_agent(self):
        """Create a minimal KalshiTradingAgent with mocked dependencies."""
        from merid.prediction.agent_grid_config import AgentConfig
        cfg = AgentConfig(
            name="BTC_15M",
            assets=["BTC"],
            timeframes=["fifteen_min"],
            category="crypto",
            archetype="directional",
        )
        with patch("merid.prediction.trading_agent.PredictionMarketModel"), \
             patch("merid.prediction.trading_agent.KalshiStrategy"), \
             patch("merid.prediction.trading_agent.PredictionMarketRisk"), \
             patch("merid.prediction.trading_agent.get_session_guard"), \
             patch("merid.prediction.trading_agent.get_venue_gate"):
            from merid.prediction.trading_agent import KalshiTradingAgent
            return KalshiTradingAgent(cfg)

    def test_summary_includes_config(self):
        agent = self._make_agent()
        s = agent.summary()
        assert "config" in s
        assert s["config"]["name"] == "BTC_15M"
        assert s["config"]["assets"] == ["BTC"]
        assert s["config"]["timeframes"] == ["fifteen_min"]
        assert s["config"]["category"] == "crypto"
        assert s["config"]["archetype"] == "directional"
        assert s["config"]["agent_id"] == "kalshi-btc_15m"

    def test_summary_includes_performance(self):
        agent = self._make_agent()
        s = agent.summary()
        # performance key always present (may be empty dict if tracker has no data)
        assert "performance" in s

    def test_summary_includes_heartbeat(self):
        agent = self._make_agent()
        s = agent.summary()
        assert "last_heartbeat_ts" in s


# ── 2. AgentPerformanceTracker composite key ───────────────────────────

class TestTrackerCompositeKey:
    """Verify _open_trades uses agent_id:market_id composite key."""

    def _make_tracker(self):
        from merid.prediction.agent_performance_tracker import AgentPerformanceTracker
        return AgentPerformanceTracker()

    def test_two_agents_same_market_no_overwrite(self):
        tracker = self._make_tracker()
        tracker.record_fill("agent-a", "MKT-1", "yes", 60, 5, 0.1, 0.8)
        tracker.record_fill("agent-b", "MKT-1", "no", 40, 3, 0.05, 0.7)

        # Both should exist in _open_trades
        assert "agent-a:MKT-1" in tracker._open_trades
        assert "agent-b:MKT-1" in tracker._open_trades
        assert len(tracker._open_trades) == 2

    def test_record_close_uses_composite_key(self):
        tracker = self._make_tracker()
        tracker.record_fill("agent-a", "MKT-1", "yes", 60, 5, 0.1, 0.8)
        tracker.record_fill("agent-b", "MKT-1", "no", 40, 3, 0.05, 0.7)

        # Close agent-a's trade — agent-b should remain
        tracker.record_close("agent-a", "MKT-1", 100, Decimal("2.00"))
        assert "agent-a:MKT-1" not in tracker._open_trades
        assert "agent-b:MKT-1" in tracker._open_trades

    def test_record_close_fallback_legacy_key(self):
        """If a trade was somehow keyed by market_id alone, close still finds it."""
        tracker = self._make_tracker()
        from merid.prediction.agent_performance_tracker import TradeRecord
        tracker._open_trades["MKT-LEGACY"] = TradeRecord(
            agent_id="agent-legacy",
            market_id="MKT-LEGACY",
            side="yes",
            entry_price_cents=50,
            contracts=2,
            entry_ts=time.time(),
            predicted_edge=0.1,
            confidence=0.8,
        )
        # Should find via fallback
        tracker.record_close("agent-legacy", "MKT-LEGACY", 100, Decimal("1.00"))
        assert "MKT-LEGACY" not in tracker._open_trades


# ── 3. record_close realized_edge is signed ────────────────────────────

class TestRealizedEdgeSigned:
    """Verify realized_edge is directional, not abs()."""

    def _make_tracker(self):
        from merid.prediction.agent_performance_tracker import AgentPerformanceTracker
        return AgentPerformanceTracker()

    def test_yes_winner_positive_edge(self):
        tracker = self._make_tracker()
        tracker.record_fill("a1", "MKT-1", "yes", 60, 5, 0.1, 0.8)
        tracker.record_close("a1", "MKT-1", 100, Decimal("2.00"))
        # YES bought at 60c, exited at 100c → edge = 0.40
        record = tracker._closed_trades[-1]
        assert record.realized_edge == pytest.approx(0.40, abs=0.01)

    def test_yes_loser_negative_edge(self):
        tracker = self._make_tracker()
        tracker.record_fill("a1", "MKT-2", "yes", 60, 5, 0.1, 0.8)
        tracker.record_close("a1", "MKT-2", 0, Decimal("-3.00"))
        # YES bought at 60c, exited at 0c → edge = -0.60
        record = tracker._closed_trades[-1]
        assert record.realized_edge == pytest.approx(-0.60, abs=0.01)

    def test_no_winner_positive_edge(self):
        tracker = self._make_tracker()
        tracker.record_fill("a1", "MKT-3", "no", 40, 5, 0.1, 0.8)
        tracker.record_close("a1", "MKT-3", 0, Decimal("2.00"))
        # NO bought at 40c, exited at 0c → edge = 0.40 (NO profits when price falls)
        record = tracker._closed_trades[-1]
        assert record.realized_edge == pytest.approx(0.40, abs=0.01)

    def test_no_loser_negative_edge(self):
        tracker = self._make_tracker()
        tracker.record_fill("a1", "MKT-4", "no", 40, 5, 0.1, 0.8)
        tracker.record_close("a1", "MKT-4", 100, Decimal("-3.00"))
        # NO bought at 40c, exited at 100c → edge = -0.60
        record = tracker._closed_trades[-1]
        assert record.realized_edge == pytest.approx(-0.60, abs=0.01)


# ── 4. record_outcome closes ALL matching trades ──────────────────────

class TestRecordOutcomeClosesAll:
    """Verify record_outcome settles all agents' trades on the same market."""

    def _make_tracker(self):
        from merid.prediction.agent_performance_tracker import AgentPerformanceTracker
        return AgentPerformanceTracker()

    def test_outcome_closes_two_agents(self):
        tracker = self._make_tracker()
        tracker.record_fill("agent-a", "MKT-X", "yes", 60, 5, 0.1, 0.8)
        tracker.record_fill("agent-b", "MKT-X", "no", 40, 3, 0.05, 0.7)

        # Market settles YES
        tracker.record_outcome("MKT-X", settled_yes=True, settlement_price_cents=100)

        # Both trades should be closed
        assert "agent-a:MKT-X" not in tracker._open_trades
        assert "agent-b:MKT-X" not in tracker._open_trades

        # agent-a (YES) should have won, agent-b (NO) should have lost
        a_metrics = tracker.get_agent_metrics("agent-a")
        b_metrics = tracker.get_agent_metrics("agent-b")
        assert a_metrics.total_closes >= 1
        assert b_metrics.total_closes >= 1


# ── 5. PaperSession._resolve_agent_name ───────────────────────────────

class TestPaperSessionNameResolution:
    """Verify _resolve_agent_name handles all naming conventions."""

    def _make_session(self):
        from merid.prediction.paper_session import PaperSession
        session = PaperSession.__new__(PaperSession)
        session._benchmark = PaperSession.__init__.__defaults__[0] if PaperSession.__init__.__defaults__ else None
        # Manually init to avoid singleton / persistence side effects
        from merid.prediction.paper_session import DEFAULT_BENCHMARK, DEFAULT_RISK_LIMITS
        session._benchmark = DEFAULT_BENCHMARK
        session._risk_limits = DEFAULT_RISK_LIMITS
        session._intervals = {}
        session._session_start = None
        session._session_id = None
        session._live_promoted = set()
        session.start_session("test-session")
        return session

    def test_canonical_name(self):
        session = self._make_session()
        assert session._resolve_agent_name("BTC_15M") == "BTC_15M"

    def test_canonical_hourly(self):
        session = self._make_session()
        assert session._resolve_agent_name("BTC_HOURLY") == "BTC_HOURLY"

    def test_config_name_1h_to_hourly(self):
        """Config uses BTC_1H but PaperSession uses BTC_HOURLY."""
        session = self._make_session()
        assert session._resolve_agent_name("BTC_1H") == "BTC_HOURLY"

    def test_agent_id_format(self):
        """agent_id is kalshi-btc_15m — should resolve to BTC_15M."""
        session = self._make_session()
        assert session._resolve_agent_name("kalshi-btc_15m") == "BTC_15M"

    def test_agent_id_hourly(self):
        """agent_id kalshi-btc_1h should resolve to BTC_HOURLY."""
        session = self._make_session()
        assert session._resolve_agent_name("kalshi-btc_1h") == "BTC_HOURLY"

    def test_agent_id_daily(self):
        session = self._make_session()
        assert session._resolve_agent_name("kalshi-eth_daily") == "ETH_DAILY"

    def test_unknown_agent_returns_none(self):
        session = self._make_session()
        assert session._resolve_agent_name("kalshi-zzz_99m") is None


# ── 6. PaperSession.record_fill accepts various name formats ──────────

class TestPaperSessionRecordFillNaming:
    """Verify record_fill works with config names and agent_ids."""

    def _make_session(self):
        from merid.prediction.paper_session import PaperSession, DEFAULT_BENCHMARK, DEFAULT_RISK_LIMITS
        session = PaperSession.__new__(PaperSession)
        session._benchmark = DEFAULT_BENCHMARK
        session._risk_limits = DEFAULT_RISK_LIMITS
        session._intervals = {}
        session._session_start = None
        session._session_id = None
        session._live_promoted = set()
        session.start_session("test-session")
        return session

    def test_record_fill_with_config_name(self):
        session = self._make_session()
        result = session.record_fill("BTC_15M", pnl_cents=50.0, won=True)
        assert result["accepted"] is True

    def test_record_fill_with_agent_id(self):
        session = self._make_session()
        result = session.record_fill("kalshi-btc_15m", pnl_cents=50.0, won=True)
        assert result["accepted"] is True

    def test_record_fill_with_config_1h_name(self):
        """Config BTC_1H should map to PaperSession BTC_HOURLY bucket."""
        session = self._make_session()
        result = session.record_fill("BTC_1H", pnl_cents=-20.0, won=False)
        assert result["accepted"] is True
        # Verify it went to BTC_HOURLY bucket
        interval = session._intervals["BTC_HOURLY"]
        assert interval.total_trades == 1

    def test_record_fill_unknown_agent_rejected(self):
        session = self._make_session()
        result = session.record_fill("kalshi-unknown_99m", pnl_cents=10.0)
        assert result["accepted"] is False
