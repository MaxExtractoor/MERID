"""Tests for system observability API: health endpoint, alert rules, SLO surface, store metrics.

Covers:
- Alert rule evaluation (firing vs not-firing states)
- Alert summary aggregation
- Observability endpoint structure
- Store metrics endpoint
- SLO endpoint
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from web.api.system_observability import (
    ALERT_RULES,
    CircuitBreakerOpenAlert,
    InstrumentStalenessAlert,
    NoActiveAgentsAlert,
    OpinionFreshnessAlert,
    RiskKillSwitchAlert,
    SignalMetricsCacheStaleAlert,
    SignalSLOBreachAlert,
    WSFeedDisconnectedAlert,
    evaluate_all_alerts,
)


# ── Alert Rule Tests ──────────────────────────────────────────────────

class TestSignalSLOBreachAlert:
    """Verify SLO breach alert fires correctly."""

    def test_not_firing_when_all_ok(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {"store": {"ok": True}, "arb": {"ok": True}}}
        }):
            alert = SignalSLOBreachAlert()
            result = alert.evaluate()
            assert result["firing"] is False
            assert result["name"] == "signal_slo_breach"

    def test_firing_when_subsystem_breached(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {
                "all_ok": False,
                "subsystems": {
                    "store": {"ok": True},
                    "live_feeds": {"ok": False},
                },
            }
        }):
            alert = SignalSLOBreachAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert "live_feeds" in result["detail"]["breached_subsystems"]

    def test_not_firing_when_cache_empty(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {}):
            alert = SignalSLOBreachAlert()
            result = alert.evaluate()
            assert result["firing"] is False


class TestOpinionFreshnessAlert:
    """Verify opinion freshness alert fires when opinions are stale."""

    def test_not_firing_when_fresh(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": False, "newest_age_s": 10.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = OpinionFreshnessAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_stale(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": True, "newest_age_s": 900.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = OpinionFreshnessAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["detail"]["newest_opinion_age_s"] == 900.0


class TestInstrumentStalenessAlert:
    """Verify instrument staleness alert fires when instruments are stale."""

    def test_not_firing_when_fresh(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "instruments": {"stale": False, "newest_refresh_age_s": 30.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = InstrumentStalenessAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_stale(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "instruments": {"stale": True, "newest_refresh_age_s": 600.0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = InstrumentStalenessAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "critical"


class TestNoActiveAgentsAlert:
    """Verify no-active-agents alert fires correctly."""

    def test_not_firing_when_agents_active(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"active_agents": 3, "total": 50},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = NoActiveAgentsAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_no_recent_agents(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"active_agents": 0, "total": 50},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = NoActiveAgentsAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "critical"

    def test_not_firing_when_store_empty(self):
        """Should not fire if there are no opinions at all (new system)."""
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"active_agents": 0, "total": 0},
        }
        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            alert = NoActiveAgentsAlert()
            result = alert.evaluate()
            assert result["firing"] is False


class TestSignalMetricsCacheStaleAlert:
    """Verify signal metrics cache staleness alert."""

    def test_not_firing_when_fresh(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {"data": True}), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()):
            alert = SignalMetricsCacheStaleAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_cache_empty(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {}), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", 0.0):
            alert = SignalMetricsCacheStaleAlert()
            result = alert.evaluate()
            assert result["firing"] is True

    def test_firing_when_cache_old(self):
        with patch("web.api.signal_layer_api._METRICS_CACHE", {"data": True}), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic() - 300):
            alert = SignalMetricsCacheStaleAlert()
            result = alert.evaluate()
            assert result["firing"] is True


# ── Alert Aggregation Tests ───────────────────────────────────────────

class TestAlertAggregation:
    """Verify evaluate_all_alerts aggregates correctly."""

    def _mock_new_alerts(self):
        """Return context managers that mock the 3+2+2+4+2 new alert rule backends to not-firing."""
        mock_ws_mgr = MagicMock()
        mock_ws_mgr.status.return_value = {"active": True, "connected": True, "message_count": 100}
        mock_debate_store = MagicMock()
        mock_debate_store.get_debate_metrics.return_value = {
            "active_debates": 2, "total_debates": 5, "avg_rounds": 3.0,
            "resolved_debates": 3, "avg_debate_lift": 0.02,
            "positive_lift_count": 2, "negative_lift_count": 1,
            "avg_disagreement_width": 0.08, "total_arguments": 15, "window_s": 3600.0,
        }
        mock_reward_engine = MagicMock()
        mock_reward_engine.get_reward_distribution.return_value = {
            "total_points": 200.0, "total_events": 20,
            "by_category": {"forecast": 100.0, "debate": 60.0, "code_quality": 40.0},
            "by_mechanism": {"accuracy": 100.0, "insight": 60.0, "stability": 40.0},
            "by_reward_type": {}, "window_seconds": 86400.0,
        }
        mock_reward_engine.get_gaming_indicators.return_value = {
            "suspects": [], "total_agents": 5, "agents_with_improvement": 3, "window_seconds": 86400.0,
        }
        mock_debugger = MagicMock()
        mock_debugger.get_cognitive_health.return_value = {
            "pct_surprised_with_updates": 100.0, "rigidity_count": 0,
            "hypothesis_flip_rate_per_day": 0.1, "flailing_count": 0,
            "active_hypotheses": 5, "broken_hypotheses": 0,
            "total_hypotheses": 5, "markets_covered": 3,
            "unique_owners": 2, "window_seconds": 604800.0,
        }
        return (
            patch("merid.resilience.circuit_breaker.get_all_breakers", return_value={}),
            patch("merid.risk.get_risk_status",
                  return_value={"can_trade": True, "state": "active", "daily_pnl": 0.0}),
            patch("merid.signals.ws_price_feed.get_ws_feed_manager", return_value=mock_ws_mgr),
            patch("merid.prediction.debate.get_debate_store", return_value=mock_debate_store),
            patch("merid.rewards.engine.get_reward_engine", return_value=mock_reward_engine),
            patch("merid.cognitive.reality_debugger.get_reality_debugger", return_value=mock_debugger),
        )

    def test_all_alerts_evaluated(self):
        """All registered alert rules should be evaluated."""
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": False, "newest_age_s": 5.0, "active_agents": 2, "total": 10},
            "instruments": {"stale": False, "newest_refresh_age_s": 10.0},
        }
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 10, "pct": 100.0},
        }
        p_cb, p_risk, p_ws, p_deb, p_rew, p_cog = self._mock_new_alerts()
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {}},
        }), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()), \
             patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             p_cb, p_risk, p_ws, p_deb, p_rew, p_cog:
            result = evaluate_all_alerts()

        assert "alerts" in result
        assert "summary" in result
        assert result["summary"]["total_rules"] == len(ALERT_RULES)
        assert result["summary"]["total_rules"] == 25
        assert "evaluated_at" in result

    def test_summary_status_ok_when_none_firing(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": False, "newest_age_s": 5.0, "active_agents": 2, "total": 10},
            "instruments": {"stale": False, "newest_refresh_age_s": 10.0},
        }
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 10, "pct": 100.0},
        }
        p_cb, p_risk, p_ws, p_deb, p_rew, p_cog = self._mock_new_alerts()
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {}},
        }), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()), \
             patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             p_cb, p_risk, p_ws, p_deb, p_rew, p_cog:
            result = evaluate_all_alerts()

        assert result["summary"]["status"] == "ok"
        assert result["summary"]["firing"] == 0

    def test_summary_status_critical_when_critical_firing(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": False, "newest_age_s": 5.0, "active_agents": 0, "total": 50},
            "instruments": {"stale": True, "newest_refresh_age_s": 600.0},
        }
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 10, "pct": 100.0},
        }
        p_cb, p_risk, p_ws, p_deb, p_rew, p_cog = self._mock_new_alerts()
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {}},
        }), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()), \
             patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             p_cb, p_risk, p_ws, p_deb, p_rew, p_cog:
            result = evaluate_all_alerts()

        assert result["summary"]["status"] == "critical"
        assert result["summary"]["critical"] >= 1

    def test_summary_status_warning_when_only_warnings(self):
        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "opinions": {"stale": True, "newest_age_s": 900.0, "active_agents": 2, "total": 10},
            "instruments": {"stale": False, "newest_refresh_age_s": 10.0},
        }
        mock_store.get_explainability_metrics.return_value = {
            "coverage": {"total": 10, "with_explanation": 10, "pct": 100.0},
        }
        p_cb, p_risk, p_ws, p_deb, p_rew, p_cog = self._mock_new_alerts()
        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {}},
        }), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()), \
             patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             p_cb, p_risk, p_ws, p_deb, p_rew, p_cog:
            result = evaluate_all_alerts()

        assert result["summary"]["status"] == "warning"
        assert result["summary"]["firing"] >= 1
        assert result["summary"]["critical"] == 0


class TestCircuitBreakerOpenAlert:
    """Verify circuit breaker open alert fires correctly."""

    def test_not_firing_when_all_closed(self):
        mock_breaker = MagicMock()
        mock_breaker.get_stats.return_value = {"state": "closed", "failure_count": 0}
        with patch("merid.resilience.circuit_breaker.get_all_breakers",
                    return_value={"kalshi": mock_breaker}):
            alert = CircuitBreakerOpenAlert()
            result = alert.evaluate()
            assert result["firing"] is False
            assert result["detail"]["total_breakers"] == 1

    def test_firing_when_breaker_open(self):
        mock_closed = MagicMock()
        mock_closed.get_stats.return_value = {"state": "closed"}
        mock_open = MagicMock()
        mock_open.get_stats.return_value = {"state": "open"}
        with patch("merid.resilience.circuit_breaker.get_all_breakers",
                    return_value={"kalshi": mock_closed, "binance": mock_open}):
            alert = CircuitBreakerOpenAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert "binance" in result["detail"]["open_venues"]
            assert result["severity"] == "critical"

    def test_not_firing_when_no_breakers(self):
        with patch("merid.resilience.circuit_breaker.get_all_breakers",
                    return_value={}):
            alert = CircuitBreakerOpenAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_graceful_on_import_error(self):
        alert = CircuitBreakerOpenAlert()
        with patch("merid.resilience.circuit_breaker.get_all_breakers",
                    side_effect=Exception("unavailable")):
            result = alert.evaluate()
            assert result["firing"] is False
            assert "error" in result["detail"]


class TestRiskKillSwitchAlert:
    """Verify risk kill switch alert fires correctly."""

    def test_not_firing_when_trading_allowed(self):
        with patch("merid.risk.get_risk_status",
                    return_value={"can_trade": True, "state": "active", "daily_pnl": 0.0}):
            alert = RiskKillSwitchAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_kill_switch_triggered(self):
        with patch("merid.risk.get_risk_status",
                    return_value={"can_trade": False, "state": "triggered",
                                  "kill_reason": "daily_loss", "daily_pnl": -500.0}):
            alert = RiskKillSwitchAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "critical"
            assert result["detail"]["kill_reason"] == "daily_loss"
            assert result["detail"]["daily_pnl"] == -500.0

    def test_graceful_on_error(self):
        with patch("merid.risk.get_risk_status", side_effect=Exception("unavailable")):
            alert = RiskKillSwitchAlert()
            result = alert.evaluate()
            assert result["firing"] is False
            assert "error" in result["detail"]


class TestWSFeedDisconnectedAlert:
    """Verify WS feed disconnected alert fires correctly."""

    def test_not_firing_when_connected(self):
        mock_mgr = MagicMock()
        mock_mgr.status.return_value = {"active": True, "connected": True, "message_count": 100}
        with patch("merid.signals.ws_price_feed.get_ws_feed_manager", return_value=mock_mgr):
            alert = WSFeedDisconnectedAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_firing_when_disconnected(self):
        mock_mgr = MagicMock()
        mock_mgr.status.return_value = {"active": False, "connected": False, "message_count": 0}
        with patch("merid.signals.ws_price_feed.get_ws_feed_manager", return_value=mock_mgr):
            alert = WSFeedDisconnectedAlert()
            result = alert.evaluate()
            assert result["firing"] is True
            assert result["severity"] == "warning"

    def test_not_firing_when_active_but_reconnecting(self):
        mock_mgr = MagicMock()
        mock_mgr.status.return_value = {"active": True, "connected": False, "message_count": 50}
        with patch("merid.signals.ws_price_feed.get_ws_feed_manager", return_value=mock_mgr):
            alert = WSFeedDisconnectedAlert()
            result = alert.evaluate()
            assert result["firing"] is False

    def test_graceful_on_error(self):
        with patch("merid.signals.ws_price_feed.get_ws_feed_manager",
                    side_effect=Exception("unavailable")):
            alert = WSFeedDisconnectedAlert()
            result = alert.evaluate()
            assert result["firing"] is False
            assert "error" in result["detail"]


# ── Alert Rule Structure Tests ────────────────────────────────────────

class TestAlertRuleStructure:
    """Verify all alert rules have correct structure."""

    def test_all_rules_have_required_fields(self):
        for rule in ALERT_RULES:
            assert hasattr(rule, "name")
            assert hasattr(rule, "severity")
            assert hasattr(rule, "description")
            assert rule.severity in ("critical", "warning", "info")

    def test_all_rules_return_valid_result(self):
        """Even with unavailable backends, rules should return valid dicts."""
        for rule in ALERT_RULES:
            result = rule.evaluate()
            assert "firing" in result
            assert "name" in result
            assert "severity" in result
            assert isinstance(result["firing"], bool)

    def test_rule_count(self):
        assert len(ALERT_RULES) == 28


# ── Endpoint Tests ────────────────────────────────────────────────────

class TestObservabilityEndpoints:
    """Verify endpoint response structure."""

    def test_observability_endpoint_structure(self):
        import asyncio
        from web.api.system_observability import system_observability

        mock_store = MagicMock()
        mock_store.get_store_metrics.return_value = {
            "instruments": {"total": 5, "by_status": {"active": 5}, "newest_refresh_age_s": 10.0, "stale": False},
            "opinions": {"total": 20, "last_1h": 5, "last_24h": 20, "active_agents": 2, "newest_age_s": 30.0, "stale": False},
            "resolved": {"total": 0},
            "plans": {},
        }

        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {}},
        }), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", time.monotonic()), \
             patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            result = asyncio.get_event_loop().run_until_complete(system_observability())

        assert "signal_metrics_slo" in result
        assert "consensus_store" in result
        assert "collaboration_health" in result
        assert "alerts" in result
        assert "timestamp" in result

    def test_slo_endpoint_structure(self):
        import asyncio
        from web.api.system_observability import system_slo

        with patch("web.api.signal_layer_api._METRICS_CACHE", {
            "_slo": {"all_ok": True, "subsystems": {"store": {"ok": True}}},
        }):
            result = asyncio.get_event_loop().run_until_complete(system_slo())

        assert "slo" in result
        assert "timestamp" in result
        assert result["slo"]["all_ok"] is True

    def test_alerts_endpoint_structure(self):
        import asyncio
        from web.api.system_observability import system_alerts

        with patch("web.api.signal_layer_api._METRICS_CACHE", {}), \
             patch("web.api.signal_layer_api._METRICS_CACHE_TS", 0.0):
            result = asyncio.get_event_loop().run_until_complete(system_alerts())

        assert "alerts" in result
        assert "summary" in result
        assert isinstance(result["alerts"], list)
