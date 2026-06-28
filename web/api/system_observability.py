"""System Observability API — unified health, SLOs, alerts, and store metrics.

Endpoints:
  GET /api/v1/system/observability     — Full system observability snapshot
  GET /api/v1/system/alerts            — Active alert conditions
  GET /api/v1/system/slo               — Signal metrics SLO status only
  GET /api/v1/prediction/consensus/store-metrics — Consensus store operational metrics

Aggregates signal metrics SLOs, consensus store health, and alert rules
into a single observable surface for monitoring and dashboards.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from utils.logger import get_logger

logger = get_logger("web.api.system_observability")

router = APIRouter(tags=["system-observability"])


# ── Alert rule definitions ────────────────────────────────────────────

class AlertRule:
    """A declarative alert rule that checks a condition and emits a status."""

    def __init__(self, name: str, severity: str, description: str):
        self.name = name
        self.severity = severity  # critical, warning, info
        self.description = description

    def evaluate(self) -> Dict[str, Any]:
        """Evaluate the rule. Returns {firing, severity, name, description, detail}."""
        raise NotImplementedError

    def safe_evaluate(self) -> Dict[str, Any]:
        """Evaluate with logging on exception — use at call sites instead of evaluate().

        On probe failure, returns firing=True at warning severity so the monitoring
        stack's own health is self-observable (probe errors are never silently healthy).
        """
        try:
            return self.evaluate()
        except Exception as _e:
            logger.warning("AlertRule %s probe failed: %s", self.name, _e)
            return {
                "firing": True,
                "severity": "warning",
                "name": self.name,
                "description": self.description,
                "detail": {"probe_error": str(_e), "original_severity": self.severity},
            }


class SignalSLOBreachAlert(AlertRule):
    """Fires when signal metrics SLO is breached."""

    def __init__(self):
        super().__init__(
            name="signal_slo_breach",
            severity="warning",
            description="One or more signal metric subsystems exceed their p95 latency SLO",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from web.api.signal_layer_api import _METRICS_CACHE
            slo = _METRICS_CACHE.get("_slo", {})
            all_ok = slo.get("all_ok", True)
            breached = []
            for name, status in slo.get("subsystems", {}).items():
                if not status.get("ok", True):
                    breached.append(name)
            return {
                "firing": not all_ok,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"breached_subsystems": breached} if breached else {},
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "SLO data unavailable"}}


class OpinionFreshnessAlert(AlertRule):
    """Fires when no new opinions have been submitted recently."""

    STALE_THRESHOLD_S = 600  # 10 minutes

    def __init__(self):
        super().__init__(
            name="opinion_freshness",
            severity="warning",
            description=f"No new prediction opinions in the last {self.STALE_THRESHOLD_S}s",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
            metrics = store.get_store_metrics()
            stale = metrics["opinions"]["stale"]
            age = metrics["opinions"]["newest_age_s"]
            return {
                "firing": stale,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"newest_opinion_age_s": age, "threshold_s": self.STALE_THRESHOLD_S},
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Store unavailable"}}


class InstrumentStalenessAlert(AlertRule):
    """Fires when instrument data hasn't been refreshed recently."""

    STALE_THRESHOLD_S = 300  # 5 minutes

    def __init__(self):
        super().__init__(
            name="instrument_staleness",
            severity="critical",
            description=f"Prediction instruments not refreshed in {self.STALE_THRESHOLD_S}s",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
            metrics = store.get_store_metrics()
            stale = metrics["instruments"]["stale"]
            age = metrics["instruments"]["newest_refresh_age_s"]
            return {
                "firing": stale,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"newest_refresh_age_s": age, "threshold_s": self.STALE_THRESHOLD_S},
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Store unavailable"}}


class NoActiveAgentsAlert(AlertRule):
    """Fires when no agents have submitted opinions in the last hour."""

    def __init__(self):
        super().__init__(
            name="no_active_agents",
            severity="critical",
            description="No agents have submitted prediction opinions in the last hour",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
            metrics = store.get_store_metrics()
            active = metrics["opinions"]["active_agents"]
            total = metrics["opinions"]["total"]
            # Only fire if there are opinions in the store but none recently
            firing = total > 0 and active == 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"active_agents_1h": active, "total_opinions": total},
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Store unavailable"}}


class SignalMetricsCacheStaleAlert(AlertRule):
    """Fires when the signal metrics cache hasn't been refreshed."""

    STALE_THRESHOLD_S = 120  # 2 minutes (TTL is 60s, so 2x is concerning)

    def __init__(self):
        super().__init__(
            name="signal_cache_stale",
            severity="warning",
            description=f"Signal metrics cache older than {self.STALE_THRESHOLD_S}s",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from web.api.signal_layer_api import _METRICS_CACHE, _METRICS_CACHE_TS
            import time as _time
            if not _METRICS_CACHE:
                return {"firing": True, "severity": self.severity, "name": self.name,
                        "description": self.description, "detail": {"reason": "Cache empty"}}
            age = _time.monotonic() - _METRICS_CACHE_TS
            return {
                "firing": age > self.STALE_THRESHOLD_S,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"cache_age_s": round(age, 1), "threshold_s": self.STALE_THRESHOLD_S},
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Cache unavailable"}}


class ExplanationCoverageLowAlert(AlertRule):
    """Fires when explanation coverage drops below threshold."""

    COVERAGE_THRESHOLD_PCT = 80.0  # Warn if <80% of opinions have explanations

    def __init__(self):
        super().__init__(
            name="explanation_coverage_low",
            severity="warning",
            description=f"Less than {self.COVERAGE_THRESHOLD_PCT}% of recent opinions have explanations",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
            metrics = store.get_explainability_metrics(window_s=3600.0)
            coverage = metrics["coverage"]
            total = coverage["total"]
            with_exp = coverage.get("with_explanation", 0)
            pct = coverage.get("pct", 0.0)
            firing = total > 0 and pct < self.COVERAGE_THRESHOLD_PCT
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "coverage_pct": pct,
                    "threshold_pct": self.COVERAGE_THRESHOLD_PCT,
                    "total_opinions": total,
                    "with_explanation": with_exp,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Explainability data unavailable"}}


class ExplanationMissingCriticalAlert(AlertRule):
    """Fires when opinions exist but none have explanations."""

    def __init__(self):
        super().__init__(
            name="explanation_missing_critical",
            severity="critical",
            description="Recent opinions exist but none have explanations attached",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
            metrics = store.get_explainability_metrics(window_s=3600.0)
            coverage = metrics["coverage"]
            total = coverage["total"]
            with_exp = coverage.get("with_explanation", 0)
            firing = total > 0 and with_exp == 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "total_opinions": total,
                    "with_explanation": with_exp,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Explainability data unavailable"}}


class CircuitBreakerOpenAlert(AlertRule):
    """Fires when any venue circuit breaker is in OPEN state."""

    def __init__(self):
        super().__init__(
            name="circuit_breaker_open",
            severity="critical",
            description="One or more venue circuit breakers are open (blocking requests)",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.resilience.circuit_breaker import get_all_breakers
            breakers = get_all_breakers()
            open_venues = []
            for name, breaker in breakers.items():
                stats = breaker.get_stats()
                if stats["state"] == "open":
                    open_venues.append(name)
            return {
                "firing": len(open_venues) > 0,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "open_venues": open_venues,
                    "total_breakers": len(breakers),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Breaker data unavailable"}}


class RiskKillSwitchAlert(AlertRule):
    """Fires when the risk controller kill switch has been triggered."""

    def __init__(self):
        super().__init__(
            name="risk_kill_switch",
            severity="critical",
            description="Risk controller kill switch is triggered — all trading halted",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.risk import get_risk_status
            status = get_risk_status()
            triggered = not status.get("can_trade", True)
            return {
                "firing": triggered,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "state": status.get("state", "unknown"),
                    "kill_reason": status.get("kill_reason", None),
                    "daily_pnl": status.get("daily_pnl", 0.0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Risk status unavailable"}}


class WSFeedDisconnectedAlert(AlertRule):
    """Fires when the WebSocket price feed is not connected."""

    def __init__(self):
        super().__init__(
            name="ws_feed_disconnected",
            severity="warning",
            description="WebSocket price feed is not connected — real-time prices unavailable",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.signals.ws_price_feed import get_ws_feed_manager
            mgr = get_ws_feed_manager()
            status = mgr.status()
            connected = status.get("connected", False)
            active = status.get("active", False)
            return {
                "firing": not connected and not active,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "active": active,
                    "connected": connected,
                    "message_count": status.get("message_count", 0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "WS feed unavailable"}}


class NoDebateActivityAlert(AlertRule):
    """Fires when no debates have occurred recently (possible herd behavior)."""

    MIN_DEBATES_THRESHOLD = 1  # At least 1 debate in the window

    def __init__(self):
        super().__init__(
            name="no_debate_activity",
            severity="warning",
            description="No debate sessions in the last hour — possible herd behavior",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.debate import get_debate_store
            store = get_debate_store()
            metrics = store.get_debate_metrics(window_s=3600.0)
            total = metrics["total_debates"]
            # Only fire if there are opinions being submitted but no debates
            firing = total < self.MIN_DEBATES_THRESHOLD
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "total_debates_1h": total,
                    "threshold": self.MIN_DEBATES_THRESHOLD,
                    "active_debates": metrics["active_debates"],
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Debate data unavailable"}}


class NegativeDebateLiftAlert(AlertRule):
    """Fires when debates are consistently making accuracy worse."""

    def __init__(self):
        super().__init__(
            name="negative_debate_lift",
            severity="warning",
            description="Debates are consistently reducing accuracy (negative debate lift)",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.debate import get_debate_store
            store = get_debate_store()
            metrics = store.get_debate_metrics(window_s=3600.0)
            resolved = metrics["resolved_debates"]
            neg_count = metrics["negative_lift_count"]
            # Fire if >50% of resolved debates have negative lift and at least 3 resolved
            firing = resolved >= 3 and neg_count > resolved / 2
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "resolved_debates": resolved,
                    "negative_lift_count": neg_count,
                    "avg_debate_lift": metrics["avg_debate_lift"],
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Debate data unavailable"}}


class DebateQualityGateHighSuppressionAlert(AlertRule):
    """Fires when the quality gate is suppressing too many debates."""

    SUPPRESSION_THRESHOLD = 0.80  # >80% suppressed = warning

    def __init__(self):
        super().__init__(
            name="debate_quality_gate_high_suppression",
            severity="warning",
            description="Quality gate is suppressing >80% of debates — threshold may be too high",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.debate import get_debate_store
            store = get_debate_store()
            metrics = store.get_debate_metrics(window_s=3600.0)
            total = metrics["total_debates"]
            if total < 3:
                return {"firing": False, "severity": self.severity, "name": self.name,
                        "description": self.description, "detail": {"total_debates": total, "reason": "too_few"}}
            # Estimate suppression from avg_disagreement_width vs typical threshold
            avg_disagreement = metrics.get("avg_disagreement_width", 0.0)
            firing = avg_disagreement < 0.03 and total >= 3
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "total_debates": total,
                    "avg_disagreement_width": avg_disagreement,
                    "threshold": 0.03,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Debate data unavailable"}}


class CalibrationDriftAlert(AlertRule):
    """Fires when agent calibration scores are consistently poor."""

    def __init__(self):
        super().__init__(
            name="calibration_drift",
            severity="warning",
            description="Agent calibration scores indicate systematic prediction bias",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.prediction.debate import get_debate_store
            store = get_debate_store()
            # Check calibration for agents with debate history
            import sqlite3
            with store._connect() as conn:
                agents = conn.execute(
                    "SELECT DISTINCT agent_id FROM pred_debate_args"
                ).fetchall()
            poor_count = 0
            total_checked = 0
            for row in agents[:20]:  # Check up to 20 agents
                cal = store.compute_calibration_score(row["agent_id"])
                if cal["calibration_score"] is not None:
                    total_checked += 1
                    if cal["calibration_score"] < 0.5:
                        poor_count += 1
            firing = total_checked >= 3 and poor_count > total_checked / 2
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "agents_checked": total_checked,
                    "poorly_calibrated": poor_count,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Calibration data unavailable"}}


class RewardContributionDriftAlert(AlertRule):
    """Fires when reward distribution is heavily skewed toward one category."""

    DOMINANCE_THRESHOLD = 0.85  # >85% of points from one category = warning

    def __init__(self):
        super().__init__(
            name="reward_contribution_drift",
            severity="warning",
            description="Reward distribution is heavily skewed — one category dominates >85% of points",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.rewards.engine import get_reward_engine
            engine = get_reward_engine()
            dist = engine.get_reward_distribution(window_s=86400.0)
            total = dist["total_points"]
            if total < 50:
                return {"firing": False, "severity": self.severity, "name": self.name,
                        "description": self.description, "detail": {"total_points": total, "reason": "too_few"}}
            by_cat = dist["by_category"]
            max_cat = max(by_cat.values()) if by_cat else 0
            dominance = max_cat / total if total > 0 else 0
            firing = dominance > self.DOMINANCE_THRESHOLD
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "total_points": total,
                    "dominance_ratio": round(dominance, 3),
                    "by_category": by_cat,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Reward engine unavailable"}}


class EngagementCollapseAlert(AlertRule):
    """Fires when reward event volume drops to near zero."""

    MIN_EVENTS_24H = 5  # fewer than 5 events in 24h = warning

    def __init__(self):
        super().__init__(
            name="engagement_collapse",
            severity="warning",
            description="Reward event volume has collapsed — fewer than 5 events in 24h",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.rewards.engine import get_reward_engine
            engine = get_reward_engine()
            dist = engine.get_reward_distribution(window_s=86400.0)
            event_count = dist["total_events"]
            firing = event_count < self.MIN_EVENTS_24H
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "events_24h": event_count,
                    "threshold": self.MIN_EVENTS_24H,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Reward engine unavailable"}}


class ConsensusRealityDriftAlert(AlertRule):
    """Fires when gaming indicators show high rewards with no improvement."""

    def __init__(self):
        super().__init__(
            name="consensus_reality_drift",
            severity="warning",
            description="Agents earning high rewards without demonstrated improvement — possible gaming",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.rewards.engine import get_reward_engine
            engine = get_reward_engine()
            indicators = engine.get_gaming_indicators(window_s=86400.0)
            suspects = indicators["suspects"]
            firing = len(suspects) > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "suspect_count": len(suspects),
                    "total_agents": indicators["total_agents"],
                    "suspects": suspects[:5],  # top 5
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Reward engine unavailable"}}


class DevSwarmInactivityAlert(AlertRule):
    """Fires when no dev swarm events (code_quality, dev_forecast, dev_debate) in 7 days."""

    WINDOW_S = 7 * 86400.0  # 7 days

    def __init__(self):
        super().__init__(
            name="dev_swarm_inactivity",
            severity="info",
            description="No dev swarm reward events (code quality, dev forecasts, dev debates) in 7 days",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.rewards.engine import get_reward_engine
            engine = get_reward_engine()
            dist = engine.get_reward_distribution(window_s=self.WINDOW_S)
            dev_categories = {"code_quality", "dev_forecast", "dev_debate"}
            dev_points = sum(
                dist["by_category"].get(cat, 0.0) for cat in dev_categories
            )
            firing = dev_points == 0 and dist["total_events"] > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "dev_points_7d": dev_points,
                    "total_events_7d": dist["total_events"],
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Reward engine unavailable"}}


# ── Sprint 10: Cognitive Layer alerts ─────────────────────────────────

class StaleHypothesisAlert(AlertRule):
    """Fires when a market has large forecast error and no hypothesis change after resolution."""

    def __init__(self):
        super().__init__(
            name="stale_hypothesis",
            severity="warning",
            description="Market has high Brier error but hypotheses haven't been updated since surprise",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.cognitive.reality_debugger import get_reality_debugger
            debugger = get_reality_debugger()
            health = debugger.get_cognitive_health()
            pct = health.get("pct_surprised_with_updates", 100.0)
            rigidity = health.get("rigidity_count", 0)
            firing = pct < 50.0 or rigidity > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "pct_surprised_with_updates": pct,
                    "rigidity_count": rigidity,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Cognitive layer unavailable"}}


class OverreactiveModelAlert(AlertRule):
    """Fires when a team flips hypotheses too frequently with no improvement in error."""

    def __init__(self):
        super().__init__(
            name="overreactive_model",
            severity="warning",
            description="Hypotheses are flipping too frequently without improving forecast accuracy",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.cognitive.reality_debugger import get_reality_debugger
            debugger = get_reality_debugger()
            health = debugger.get_cognitive_health()
            flip_rate = health.get("hypothesis_flip_rate_per_day", 0.0)
            flailing = health.get("flailing_count", 0)
            firing = flailing > 0 or flip_rate > 2.0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "hypothesis_flip_rate_per_day": flip_rate,
                    "flailing_count": flailing,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Cognitive layer unavailable"}}


# ── Sprint 11: Betting Layer alerts ──────────────────────────────────

class BettingHealthAlert(AlertRule):
    """Fires when betting pools are one-sided or settlement latency is high."""

    ONE_SIDED_THRESHOLD = 2  # more than 2 one-sided active pools = warning
    LATENCY_THRESHOLD_S = 300.0  # settlement latency > 5 min = warning

    def __init__(self):
        super().__init__(
            name="betting_health",
            severity="warning",
            description="Betting system health issue: one-sided pools or high settlement latency",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from web.api.betting import get_bookie_agent
            agent = get_bookie_agent()
            health = agent.get_betting_health()
            one_sided = health.get("one_sided_pools", 0)
            avg_latency = health.get("avg_settlement_latency_s", None)
            reasons = []
            if one_sided > self.ONE_SIDED_THRESHOLD:
                reasons.append(f"{one_sided} one-sided pools (threshold {self.ONE_SIDED_THRESHOLD})")
            if avg_latency is not None and avg_latency > self.LATENCY_THRESHOLD_S:
                reasons.append(f"avg settlement latency {avg_latency:.1f}s (threshold {self.LATENCY_THRESHOLD_S}s)")
            firing = len(reasons) > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "one_sided_pools": one_sided,
                    "avg_settlement_latency_s": avg_latency,
                    "reasons": reasons,
                    "active_pools": health.get("active_pools", 0),
                    "total_volume": health.get("total_volume", 0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Betting agent unavailable"}}


class BettingCoherenceAlert(AlertRule):
    """Fires when agent betting coherence is consistently low."""

    COHERENCE_THRESHOLD = 0.4  # avg coherence < 0.4 = warning
    MIN_BETS = 5  # need at least 5 bets with coherence data

    def __init__(self):
        super().__init__(
            name="betting_coherence",
            severity="warning",
            description="Agent betting coherence is low — bets misaligned with stated opinions",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from web.api.betting import get_bookie_agent
            agent = get_bookie_agent()
            # Collect coherence across all agents that have placed bets
            all_scores = []
            checked_agents = set()
            for pool in agent.pools.values():
                for bet in pool.bets:
                    if bet.user_id not in checked_agents:
                        checked_agents.add(bet.user_id)
                        report = agent.get_agent_coherence(bet.user_id)
                        if report["coherence_score"] is not None:
                            all_scores.append(report["coherence_score"])
            if len(all_scores) < 1:
                return {"firing": False, "severity": self.severity, "name": self.name,
                        "description": self.description, "detail": {"reason": "no_coherence_data"}}
            avg = sum(all_scores) / len(all_scores)
            total_bets_with_coherence = sum(
                1 for p in agent.pools.values()
                for b in p.bets
                if b.stated_probability is not None and b.implied_probability is not None
            )
            firing = avg < self.COHERENCE_THRESHOLD and total_bets_with_coherence >= self.MIN_BETS
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "avg_coherence": round(avg, 4),
                    "threshold": self.COHERENCE_THRESHOLD,
                    "agents_checked": len(all_scores),
                    "bets_with_coherence": total_bets_with_coherence,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Betting agent unavailable"}}


# ── Alert registry ────────────────────────────────────────────────────

# ── Sprint 12: Sports & Live Betting alerts ─────────────────────────

class LiveBettingLatencyAlert(AlertRule):
    """Fires when live betting P95 acceptance latency breaches SLO."""

    SLO_TARGET_MS = 300.0

    def __init__(self):
        super().__init__(
            name="live_betting_latency_breach",
            severity="critical",
            description="Live betting P95 acceptance latency exceeds SLO target",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.live_sports import get_sports_betting_manager
            mgr = get_sports_betting_manager()
            slo = mgr.betting_engine.get_slo_metrics()
            p95 = slo.get("p95_acceptance_latency_ms", 0.0)
            total = slo.get("total_bets", 0)
            firing = total >= 5 and p95 > self.SLO_TARGET_MS
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "p95_latency_ms": p95,
                    "slo_target_ms": self.SLO_TARGET_MS,
                    "total_bets": total,
                    "slo_breaches": slo.get("slo_breaches", 0),
                    "acceptance_rate": slo.get("acceptance_rate", 0.0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Sports betting manager unavailable"}}


class PricingDivergenceAlert(AlertRule):
    """Fires when platform lines diverge significantly from external odds."""

    DIVERGENCE_THRESHOLD = 0.10  # 10% average divergence

    def __init__(self):
        super().__init__(
            name="pricing_divergence",
            severity="warning",
            description="Platform pricing diverges significantly from external sportsbook odds",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.live_sports import get_sports_betting_manager
            mgr = get_sports_betting_manager()
            pricing = mgr.odds_engine.get_pricing_divergence()
            avg_div = pricing.get("avg_divergence", 0.0)
            lines_count = pricing.get("lines_count", 0)
            firing = lines_count >= 3 and avg_div > self.DIVERGENCE_THRESHOLD
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "avg_divergence": avg_div,
                    "max_divergence": pricing.get("max_divergence", 0.0),
                    "threshold": self.DIVERGENCE_THRESHOLD,
                    "lines_count": lines_count,
                    "stale_lines": pricing.get("stale_lines", 0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Sports betting manager unavailable"}}


class FeedStalenessAlert(AlertRule):
    """Fires when any odds feed provider is stale."""

    def __init__(self):
        super().__init__(
            name="feed_staleness",
            severity="warning",
            description="One or more odds feed providers are stale (no updates within threshold)",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.live_sports import get_sports_betting_manager
            mgr = get_sports_betting_manager()
            feed = mgr.odds_feed.get_feed_health()
            stale = feed.get("stale_providers", 0)
            total = feed.get("total_providers", 0)
            providers = feed.get("providers", {})
            stale_names = [n for n, p in providers.items() if p.get("is_stale")]
            firing = stale > 0 and total > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "stale_providers": stale,
                    "total_providers": total,
                    "stale_names": stale_names,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Sports betting manager unavailable"}}


class OddsAnomalyAlert(AlertRule):
    """Fires when the anomaly engine has unacknowledged high/critical anomalies."""

    def __init__(self):
        super().__init__(
            name="odds_anomaly",
            severity="warning",
            description="Unacknowledged high/critical anomalies detected in sports betting feeds",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.anomaly_detection import get_anomaly_engine
            engine = get_anomaly_engine()
            stats = engine.get_stats()
            high_count = stats.get("by_severity", {}).get("high", 0) + stats.get("by_severity", {}).get("critical", 0)
            unack = stats.get("unacknowledged", 0)
            firing = unack > 0 and high_count > 0
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "unacknowledged": unack,
                    "high_critical_count": high_count,
                    "total_anomalies": stats.get("total", 0),
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Anomaly engine unavailable"}}


class SportsDebateLiftAlert(AlertRule):
    """Fires when sports debate lift is consistently negative."""

    def __init__(self):
        super().__init__(
            name="sports_debate_lift_negative",
            severity="warning",
            description="Sports debates are consistently producing negative lift (worsening predictions)",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.sports_debate import get_sports_debate_coordinator
            coord = get_sports_debate_coordinator()
            stats = coord.get_stats()
            lift_stats = stats.get("lift_stats", {})
            avg_lift = lift_stats.get("avg_lift")
            total = lift_stats.get("total_debates", 0)
            positive_rate = lift_stats.get("positive_lift_rate", 1.0)
            firing = total >= 5 and avg_lift is not None and avg_lift < 0 and positive_rate < 0.4
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "avg_lift": avg_lift,
                    "positive_lift_rate": positive_rate,
                    "total_debates": total,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Sports debate coordinator unavailable"}}


class OddsCacheStalenessAlert(AlertRule):
    """Fires when the live odds cache has a high stale entry ratio."""

    def __init__(self):
        super().__init__(
            name="odds_cache_staleness",
            severity="warning",
            description="Live odds cache has a high ratio of stale entries",
        )
        self.STALE_RATIO_THRESHOLD = 0.5

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.betting.live_odds_cache import get_live_odds_cache_manager
            mgr = get_live_odds_cache_manager()
            stats = mgr.cache.get_stats()
            total = stats.get("total_entries", 0)
            stale = stats.get("stale_entries", 0)
            ratio = stale / total if total > 0 else 0.0
            firing = total >= 5 and ratio > self.STALE_RATIO_THRESHOLD
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "total_entries": total,
                    "stale_entries": stale,
                    "stale_ratio": round(ratio, 4),
                    "threshold": self.STALE_RATIO_THRESHOLD,
                },
            }
        except Exception as _e:
            return {"firing": True, "severity": "warning", "name": self.name,
                    "description": self.description, "detail": {"probe_error": str(_e), "error": "Odds cache manager unavailable"}}


class PnlDivergenceAlert(AlertRule):
    """Fires when paper engine PnL and risk module PnL disagree beyond threshold."""

    WARN_THRESHOLD_PCT = 5.0    # 5% divergence → warning
    CRIT_THRESHOLD_PCT = 15.0   # 15% divergence → critical

    def __init__(self):
        super().__init__(
            name="pnl_divergence",
            severity="warning",
            description="Paper engine PnL and risk module PnL diverge beyond threshold",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from trading.paper_trading import get_paper_engine
            engine = get_paper_engine()
            port = engine.get_portfolio_summary("default")
            paper_pnl = port.get("total_pnl", 0.0) + port.get("unrealized_pnl", 0.0)
        except ImportError:
            paper_pnl = None
        except (RuntimeError, AttributeError) as e:
            logger.debug("Paper PnL unavailable: %s", e)
            paper_pnl = None

        risk_pnl = None
        try:
            from web.api.system_endpoints import _real_pnl
            pnl_data = _real_pnl()
            risk_pnl = pnl_data.get("total_pnl", 0.0)
        except ImportError:
            logger.debug("PnL divergence probe: _real_pnl module unavailable")
        except (RuntimeError, AttributeError) as _pe:
            logger.debug("PnL divergence probe: _real_pnl unavailable: %s", _pe)

        if paper_pnl is None or risk_pnl is None:
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"error": "PnL sources unavailable for comparison"}}

        denom = max(abs(paper_pnl), abs(risk_pnl), 1.0)
        divergence_pct = abs(paper_pnl - risk_pnl) / denom * 100

        if divergence_pct >= self.CRIT_THRESHOLD_PCT:
            return {
                "firing": True, "severity": "critical", "name": self.name,
                "description": self.description,
                "detail": {
                    "paper_pnl": round(paper_pnl, 2),
                    "risk_pnl": round(risk_pnl, 2),
                    "divergence_pct": round(divergence_pct, 2),
                },
            }
        elif divergence_pct >= self.WARN_THRESHOLD_PCT:
            return {
                "firing": True, "severity": "warning", "name": self.name,
                "description": self.description,
                "detail": {
                    "paper_pnl": round(paper_pnl, 2),
                    "risk_pnl": round(risk_pnl, 2),
                    "divergence_pct": round(divergence_pct, 2),
                },
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description,
                "detail": {"divergence_pct": round(divergence_pct, 2)}}


class AgentConsecutiveFailureAlert(AlertRule):
    """Fires when any agent has exceeded the consecutive failure threshold."""

    FAILURE_THRESHOLD = 3

    def __init__(self):
        super().__init__(
            name="agent_consecutive_failures",
            severity="warning",
            description=f"An agent has failed {3}+ consecutive times",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from core.error_handling import get_agent_failure_counts
            counts = get_agent_failure_counts()
        except (ImportError, AttributeError):
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"error": "Agent failure tracking unavailable"}}

        failing_agents = {
            name: count for name, count in counts.items()
            if count >= self.FAILURE_THRESHOLD
        }

        if failing_agents:
            worst = max(failing_agents, key=failing_agents.get)
            sev = "critical" if failing_agents[worst] >= self.FAILURE_THRESHOLD * 2 else "warning"
            return {
                "firing": True, "severity": sev, "name": self.name,
                "description": self.description,
                "detail": {
                    "failing_agents": failing_agents,
                    "worst_agent": worst,
                    "worst_count": failing_agents[worst],
                },
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description, "detail": {"all_agents_ok": True}}


class ReconciliationDegradedAlert(AlertRule):
    """Fires when reconciliation reports deltas or has never run."""

    def __init__(self):
        super().__init__(
            name="reconciliation_degraded",
            severity="critical",
            description="Reconciliation has critical discrepancies or has not completed",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.reconciliation import get_last_report
            report = get_last_report()
        except ImportError:
            report = None
        except (RuntimeError, AttributeError) as e:
            logger.debug("Reconciliation report unavailable: %s", e)
            report = None

        if report is None:
            return {
                "firing": True, "severity": "warning", "name": self.name,
                "description": "No reconciliation report available yet",
                "detail": {"status": "never_run"},
            }

        # Kalshi merid ReconciliationReport (issues, severity)
        if hasattr(report, "issues") and not hasattr(report, "all_ok"):
            from merid.reconciliation.kalshi_reconciler import IssueSeverity
            issues = getattr(report, "issues", None) or []
            if not issues:
                snap = (getattr(report, "summary", "") or "")[:12]
                return {"firing": False, "severity": self.severity, "name": self.name,
                        "description": self.description,
                        "detail": {"status": "ok", "snapshot_hash": snap}}
            error_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
            delta_count = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
            sev = "critical" if error_count > 0 else "warning"
            snap = (getattr(report, "summary", "") or "")[:12]
            return {
                "firing": True, "severity": sev, "name": self.name,
                "description": self.description,
                "detail": {
                    "error_count": error_count,
                    "delta_count": delta_count,
                    "snapshot_hash": snap,
                },
            }

        # Legacy paper reconciliation report
        if not report.all_ok:
            error_count = sum(1 for c in report.checks if c.status.value == "error")
            delta_count = sum(1 for c in report.checks if c.status.value == "delta")
            sev = "critical" if error_count > 0 else "warning"
            return {
                "firing": True, "severity": sev, "name": self.name,
                "description": self.description,
                "detail": {
                    "error_count": error_count,
                    "delta_count": delta_count,
                    "snapshot_hash": report.snapshot_hash[:12],
                },
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description,
                "detail": {"status": "ok", "snapshot_hash": report.snapshot_hash[:12]}}


class WsChannelStaleAlert(AlertRule):
    """Fires when a WS channel is active but hasn't sent events recently.

    Market data ticks frequently, but news and agent_output are event-driven
    and may be quiet for extended periods. Per-channel thresholds avoid
    false positives on sparse channels.
    """

    # Per-channel staleness thresholds (seconds).
    # market_data ticks every few seconds; news/agent_output are event-driven.
    CHANNEL_THRESHOLDS: Dict[str, float] = {
        "market_data": 60.0,
        "news": 300.0,
        "agent_output": 300.0,
    }
    DEFAULT_THRESHOLD_S = 120.0  # Fallback for unknown channels

    def __init__(self):
        super().__init__(
            name="ws_channel_stale",
            severity="warning",
            description="A WebSocket channel is connected but has no recent events",
        )

    def _threshold_for(self, channel: str) -> float:
        return self.CHANNEL_THRESHOLDS.get(channel, self.DEFAULT_THRESHOLD_S)

    def evaluate(self) -> Dict[str, Any]:
        try:
            from web.api.live_stream import get_channel_freshness
            freshness = get_channel_freshness()
        except (ImportError, AttributeError):
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"error": "Channel freshness tracking unavailable"}}

        if not freshness:
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"status": "no_channels_tracked"}}

        stale_channels: Dict[str, float] = {}
        for channel, info in freshness.items():
            threshold = self._threshold_for(channel)
            if info["age_seconds"] >= threshold:
                stale_channels[channel] = info["age_seconds"]

        if stale_channels:
            worst = max(stale_channels, key=stale_channels.get)
            return {
                "firing": True, "severity": "warning", "name": self.name,
                "description": self.description,
                "detail": {
                    "stale_channels": {k: round(v, 1) for k, v in stale_channels.items()},
                    "worst_channel": worst,
                    "worst_age_s": round(stale_channels[worst], 1),
                    "thresholds": {ch: self._threshold_for(ch) for ch in freshness},
                },
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description,
                "detail": {"all_channels_fresh": True,
                           "channels_checked": len(freshness)}}


class ReconciliationStaleAlert(AlertRule):
    """Fires when reconciliation hasn't completed within the staleness threshold."""

    STALE_WARN_S = 300.0    # 5 min → warning
    STALE_CRIT_S = 600.0    # 10 min → critical

    def __init__(self):
        super().__init__(
            name="reconciliation_stale",
            severity="warning",
            description="Reconciliation has not completed recently",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.reconciliation import get_last_reconciliation_ts
            last_ts = get_last_reconciliation_ts()
        except (ImportError, AttributeError):
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"error": "Reconciliation module unavailable"}}

        if last_ts == 0.0:
            return {
                "firing": True, "severity": "warning", "name": self.name,
                "description": "Reconciliation has never completed",
                "detail": {"status": "never_run"},
            }

        import time
        age_s = time.time() - last_ts
        if age_s >= self.STALE_CRIT_S:
            return {
                "firing": True, "severity": "critical", "name": self.name,
                "description": self.description,
                "detail": {"age_seconds": round(age_s, 1),
                           "threshold_s": self.STALE_CRIT_S},
            }
        elif age_s >= self.STALE_WARN_S:
            return {
                "firing": True, "severity": "warning", "name": self.name,
                "description": self.description,
                "detail": {"age_seconds": round(age_s, 1),
                           "threshold_s": self.STALE_WARN_S},
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description,
                "detail": {"age_seconds": round(age_s, 1), "status": "fresh"}}


class AgentLatencySLOAlert(AlertRule):
    """Fires when any agent's P95 latency exceeds the SLO threshold."""

    P95_WARN_MS = 3000.0   # 3s → warning
    P95_CRIT_MS = 5000.0   # 5s → critical

    def __init__(self):
        super().__init__(
            name="agent_latency_slo",
            severity="warning",
            description="An agent's P95 latency exceeds the SLO threshold",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from agents.agent_framework import get_agent_registry
            registry = get_agent_registry()
            all_metrics = registry.get_all_metrics()
        except (ImportError, AttributeError):
            return {"firing": False, "severity": self.severity, "name": self.name,
                    "description": self.description,
                    "detail": {"error": "Agent registry unavailable"}}

        breaching: Dict[str, float] = {}
        for agent_id, metrics in all_metrics.items():
            if metrics.p95_latency_ms >= self.P95_WARN_MS:
                breaching[agent_id] = metrics.p95_latency_ms

        if breaching:
            worst = max(breaching, key=breaching.get)
            sev = "critical" if breaching[worst] >= self.P95_CRIT_MS else "warning"
            return {
                "firing": True, "severity": sev, "name": self.name,
                "description": self.description,
                "detail": {
                    "breaching_agents": {k: round(v, 1) for k, v in breaching.items()},
                    "worst_agent": worst,
                    "worst_p95_ms": round(breaching[worst], 1),
                    "threshold_warn_ms": self.P95_WARN_MS,
                    "threshold_crit_ms": self.P95_CRIT_MS,
                },
            }
        return {"firing": False, "severity": self.severity, "name": self.name,
                "description": self.description,
                "detail": {"all_agents_within_slo": True,
                           "agents_checked": len(all_metrics)}}


class WSSequenceGapAlert(AlertRule):
    """Fires when the Kalshi WebSocket has detected sequence gaps in the last window.

    A gap means messages were dropped between the client and server, invalidating
    the orderbook snapshot for affected markets.  New entries on gap'd markets
    use stale prices until a fresh snapshot arrives.
    """

    WINDOW_S = 60.0  # look back 60 seconds

    def __init__(self):
        super().__init__(
            name="ws_kalshi_seq_gap",
            severity="warning",
            description="Kalshi WebSocket sequence gap detected — orderbook cache invalidated, stale prices risk",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            bridge = get_bridge()
            ws = bridge._ws
            if ws is None or not bridge.is_running():
                return {
                    "firing": False,
                    "severity": self.severity,
                    "name": self.name,
                    "description": self.description,
                    "detail": {"status": "ws_not_running"},
                }
            stats = ws.stats()
            seq_gaps = stats.get("seq_gaps", 0)
            connected = stats.get("connected", False)
            consecutive_auth = getattr(ws, "_consecutive_auth_failures", 0)
            firing = seq_gaps > 0
            sev = "critical" if (seq_gaps > 10 or consecutive_auth >= 3) else "warning"
            return {
                "firing": firing,
                "severity": sev,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "seq_gaps_total": seq_gaps,
                    "connected": connected,
                    "consecutive_auth_failures": consecutive_auth,
                    "ob_cached_markets": stats.get("ob_cached_markets", 0),
                    "reconnect_count": stats.get("reconnect_count", 0),
                },
            }
        except ImportError:
            return {
                "firing": False,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"error": "Kalshi WS module unavailable"},
            }
        except (RuntimeError, AttributeError) as e:
            logger.debug("Kalshi WS stats unavailable: %s", e)
            return {
                "firing": False,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {"error": "Kalshi WS stats unavailable"},
            }


class NewsFeedHealthAlert(AlertRule):
    """Fires when news feed (Finnhub) is starved or returning zero data.

    This detects when:
    - API returns 0 articles (key issue, API problem, or wrong category)
    - API returns articles but none match our symbols (symbol filtering issue)
    - API hasn't been fetched in > 5 minutes (stale)
    - API has error state

    When news is dark, sentiment-dependent strategies may be flying blind.
    """

    STALE_THRESHOLD_S = 300  # 5 minutes
    ZERO_DATA_THRESHOLD = 3  # Fire after 3 consecutive zero-data fetches

    def __init__(self):
        super().__init__(
            name="news_feed_health",
            severity="warning",  # Warning by default; can escalate
            description="News feed (Finnhub) returning zero data or stale — sentiment signals may be degraded",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.signals.live_feeds import get_live_feed_manager
            mgr = get_live_feed_manager()
            health = mgr.get_feed_health()
            news = health.get("news", {})
            
            status = news.get("status", "unknown")
            configured = news.get("configured", False)
            last_fetch_age = news.get("last_fetch_age_s")
            api_count = news.get("api_articles_last_fetch", 0)
            ingested = news.get("ingested_last_fetch", 0)
            error = news.get("error")
            
            # Determine severity based on state
            firing = False
            sev = self.severity
            reason = None
            
            if not configured:
                # Not configured is info, not a firing alert
                return {
                    "firing": False,
                    "severity": "info",
                    "name": self.name,
                    "description": "Finnhub not configured — news feed disabled",
                    "detail": {"configured": False},
                }
            
            if status == "error":
                firing = True
                sev = "critical"
                reason = f"API error: {error}"
            elif status == "stale":
                firing = True
                sev = "warning"
                reason = f"No fetch in {last_fetch_age:.0f}s (threshold {self.STALE_THRESHOLD_S}s)"
            elif status == "zero_data":
                firing = True
                sev = "warning"
                reason = f"API returned 0 articles (check API key or category)"
            elif status == "no_matches":
                firing = True
                sev = "warning"  # Lower severity than zero_data
                reason = f"API returned {api_count} articles but 0 matched symbols"
            
            return {
                "firing": firing,
                "severity": sev,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "status": status,
                    "configured": configured,
                    "last_fetch_age_s": last_fetch_age,
                    "api_articles_last_fetch": api_count,
                    "ingested_last_fetch": ingested,
                    "error": error,
                    "reason": reason,
                },
            }
        except Exception as _e:
            return {
                "firing": True,
                "severity": "warning",
                "name": self.name,
                "description": self.description,
                "detail": {"probe_error": str(_e), "error": "Live feed manager unavailable"},
            }


class ReconciliationDriftAlert(AlertRule):
    """Fires when the periodic reconciliation run reports a drift or error."""

    def __init__(self):
        super().__init__(
            name="reconciliation_drift",
            severity="critical",
            description="Position/balance reconciliation detected drift or error — investigate immediately",
        )

    def evaluate(self) -> Dict[str, Any]:
        try:
            from merid.reconciliation import get_last_report
            report = get_last_report()
            if report is None:
                return {
                    "firing": False,
                    "severity": self.severity,
                    "name": self.name,
                    "description": self.description,
                    "detail": {"status": "no_report_yet"},
                }

            # Kalshi merid ReconciliationReport
            if hasattr(report, "issues") and not hasattr(report, "all_ok"):
                issues = getattr(report, "issues", None) or []
                all_ok = len(issues) == 0
                failed: List[str] = []
                for i in issues:
                    it = getattr(i, "issue_type", None)
                    iv = getattr(it, "value", it)
                    fid = getattr(i, "instrument_id", "") or ""
                    failed.append(f"{iv}:{fid}" if iv else (fid or "issue"))
                firing = not all_ok
                return {
                    "firing": firing,
                    "severity": self.severity,
                    "name": self.name,
                    "description": self.description,
                    "detail": {
                        "all_ok": all_ok,
                        "failed_checks": failed,
                        "portfolios_checked": getattr(report, "internal_position_count", 0),
                        "positions_checked": getattr(report, "venue_position_count", 0),
                        "timestamp": getattr(report, "timestamp", 0),
                    },
                }

            # Legacy paper reconciliation report (mocks / tests)
            firing = not report.all_ok
            failed = [
                c.name for c in getattr(report, "checks", [])
                if getattr(getattr(c, "status", None), "value", str(getattr(c, "status", ""))).lower() != "ok"
            ]
            return {
                "firing": firing,
                "severity": self.severity,
                "name": self.name,
                "description": self.description,
                "detail": {
                    "all_ok": report.all_ok,
                    "failed_checks": failed,
                    "portfolios_checked": report.portfolios_checked,
                    "positions_checked": report.positions_checked,
                    "timestamp": report.timestamp,
                },
            }
        except Exception as _e:
            return {
                "firing": True,
                "severity": "warning",
                "name": self.name,
                "description": self.description,
                "detail": {"probe_error": str(_e), "error": "Reconciliation report unavailable"},
            }


ALERT_RULES: List[AlertRule] = [
    SignalSLOBreachAlert(),
    OpinionFreshnessAlert(),
    InstrumentStalenessAlert(),
    NoActiveAgentsAlert(),
    SignalMetricsCacheStaleAlert(),
    CircuitBreakerOpenAlert(),
    RiskKillSwitchAlert(),
    WSFeedDisconnectedAlert(),
    ExplanationCoverageLowAlert(),
    ExplanationMissingCriticalAlert(),
    NoDebateActivityAlert(),
    NegativeDebateLiftAlert(),
    DebateQualityGateHighSuppressionAlert(),
    CalibrationDriftAlert(),
    RewardContributionDriftAlert(),
    EngagementCollapseAlert(),
    ConsensusRealityDriftAlert(),
    DevSwarmInactivityAlert(),
    StaleHypothesisAlert(),
    OverreactiveModelAlert(),
    BettingHealthAlert(),
    BettingCoherenceAlert(),
    LiveBettingLatencyAlert(),
    PricingDivergenceAlert(),
    FeedStalenessAlert(),
    OddsAnomalyAlert(),
    SportsDebateLiftAlert(),
    OddsCacheStalenessAlert(),
    PnlDivergenceAlert(),
    AgentConsecutiveFailureAlert(),
    ReconciliationDegradedAlert(),
    AgentLatencySLOAlert(),
    ReconciliationStaleAlert(),
    WsChannelStaleAlert(),
    WSSequenceGapAlert(),
    NewsFeedHealthAlert(),  # NEW: Detect Finnhub/news feed starvation
    ReconciliationDriftAlert(),
]


def evaluate_all_alerts() -> Dict[str, Any]:
    """Evaluate all alert rules and return summary."""
    results = []
    firing_count = 0
    critical_count = 0
    for rule in ALERT_RULES:
        result = rule.safe_evaluate()
        results.append(result)
        if result.get("firing"):
            firing_count += 1
            if result.get("severity") == "critical":
                critical_count += 1

    return {
        "alerts": results,
        "summary": {
            "total_rules": len(ALERT_RULES),
            "firing": firing_count,
            "critical": critical_count,
            "status": "critical" if critical_count > 0 else "warning" if firing_count > 0 else "ok",
        },
        "evaluated_at": time.time(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/api/v1/system/observability")
async def system_observability():
    """Full system observability snapshot: SLOs, store metrics, alerts."""
    # Signal metrics SLO
    signal_slo = {}
    try:
        from web.api.signal_layer_api import _METRICS_CACHE as _smc
        signal_slo = _smc.get("_slo", {})
    except ImportError:
        signal_slo = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Signal SLO unavailable: %s", e)
        signal_slo = {"error": "unavailable"}

    # Consensus store metrics
    store_metrics = {}
    try:
        from merid.prediction.consensus import get_prediction_consensus_store as _gpcs
        store_metrics = _gpcs().get_store_metrics()
    except ImportError:
        store_metrics = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Consensus store metrics unavailable: %s", e)
        store_metrics = {"error": "unavailable"}

    # Inference explainability
    explainability = {}
    try:
        from merid.prediction.consensus import get_prediction_consensus_store as _gpcs2
        explainability = _gpcs2().get_explainability_metrics(window_s=3600.0)
    except ImportError:
        explainability = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Explainability metrics unavailable: %s", e)
        explainability = {"error": "unavailable"}

    # Collaboration health (debate + teamwork)
    collaboration = {}
    try:
        from merid.prediction.debate import get_debate_store as _gds
        collaboration = _gds().get_debate_metrics(window_s=3600.0)
    except ImportError:
        collaboration = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Debate metrics unavailable: %s", e)
        collaboration = {"error": "unavailable"}

    # Debate tuning health (Sprint 8)
    debate_tuning = {}
    try:
        from merid.prediction.debate import get_debate_store as _gds2
        ds = _gds2()
        debate_tuning = {
            "leaderboard_decay_lambda": float(
                __import__("os").environ.get("MERID_LEADERBOARD_DECAY_LAMBDA", "0.0")
            ),
            "quality_gate_min_disagreement": 0.03,
        }
    except ImportError:
        debate_tuning = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Debate tuning unavailable: %s", e)
        debate_tuning = {"error": "unavailable"}

    # Reward engine health (Sprint 9)
    reward_engine = {}
    try:
        from merid.rewards.engine import get_reward_engine as _gre
        engine = _gre()
        reward_engine = {
            "metrics": engine.get_engine_metrics(),
            "distribution_24h": engine.get_reward_distribution(window_s=86400.0),
            "gaming_indicators": engine.get_gaming_indicators(window_s=86400.0),
        }
    except ImportError:
        reward_engine = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Reward engine unavailable: %s", e)
        reward_engine = {"error": "unavailable"}

    # Cognitive layer health (Sprint 10)
    cognitive_health = {}
    try:
        from merid.cognitive.reality_debugger import get_reality_debugger as _grd
        cognitive_health = _grd().get_cognitive_health(window_s=604800.0)
    except ImportError:
        cognitive_health = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Cognitive health unavailable: %s", e)
        cognitive_health = {"error": "unavailable"}

    # Betting layer health (Sprint 11)
    betting_health = {}
    try:
        from web.api.betting import get_bookie_agent as _gba
        betting_health = _gba().get_betting_health()
    except ImportError:
        betting_health = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Betting health unavailable: %s", e)
        betting_health = {"error": "unavailable"}

    # Sports & live betting health (Sprint 12)
    sports_betting_health = {}
    try:
        from merid.betting.live_sports import get_sports_betting_manager as _gsbm
        sports_betting_health = _gsbm().get_sports_health()
    except ImportError:
        sports_betting_health = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Sports betting health unavailable: %s", e)
        sports_betting_health = {"error": "unavailable"}

    # Alerts
    alerts = await run_in_threadpool(evaluate_all_alerts)

    # Real-data API fallback counts (PR-04)
    real_data_fallbacks: Dict[str, Any] = {}
    try:
        from web.api.real_data_endpoints import get_fallback_counts
        real_data_fallbacks = get_fallback_counts()
    except ImportError:
        real_data_fallbacks = {"error": "module_unavailable"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Fallback counts unavailable: %s", e)
        real_data_fallbacks = {"error": "unavailable"}

    return {
        "signal_metrics_slo": signal_slo,
        "consensus_store": store_metrics,
        "inference_explainability": explainability,
        "collaboration_health": collaboration,
        "debate_tuning_health": debate_tuning,
        "reward_engine_health": reward_engine,
        "cognitive_health": cognitive_health,
        "betting_health": betting_health,
        "sports_betting_health": sports_betting_health,
        "real_data_fallback_counts": real_data_fallbacks,
        "alerts": alerts,
        "timestamp": time.time(),
    }


@router.get("/api/v1/system/alerts")
async def system_alerts():
    """Active alert conditions across all monitored subsystems."""
    return await run_in_threadpool(evaluate_all_alerts)


@router.get("/api/v1/system/slo")
async def system_slo():
    """Signal metrics SLO status."""
    try:
        from web.api.signal_layer_api import _METRICS_CACHE as _smc2
        slo = _smc2.get("_slo", {})
        return {"slo": slo, "timestamp": time.time()}
    except ImportError:
        return {"slo": {}, "error": "module_unavailable", "timestamp": time.time()}
    except (RuntimeError, AttributeError) as e:
        logger.debug("SLO data unavailable: %s", e)
        return {"slo": {}, "error": "unavailable", "timestamp": time.time()}


@router.get("/api/v1/prediction/consensus/store-metrics")
async def consensus_store_metrics():
    """Operational metrics for the prediction consensus store."""
    try:
        from merid.prediction.consensus import get_prediction_consensus_store as _gpcs3
        return _gpcs3().get_store_metrics()
    except ImportError as exc:
        return {"error": f"module_unavailable: {exc}"}
    except (RuntimeError, AttributeError) as exc:
        logger.debug("Consensus store metrics unavailable: %s", exc)
        return {"error": str(exc)}
