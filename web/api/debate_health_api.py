"""
Debate Health Dashboard API
Endpoints for monitoring debate system health and performance metrics.

All endpoints gracefully degrade in kalshi-only mode where the debate
orchestrator / store may not be running.
"""

from fastapi import APIRouter
from typing import Dict, List, Any
from datetime import datetime, timezone, timedelta
import statistics
import asyncio
import time

from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/debates/health", tags=["debate-health"])

_KALSHI_ONLY_STUB = {
    "note": "Debate subsystem inactive in kalshi-only profile",
    "healthy": True,
}


def _slo() -> Any:
    try:
        from core.slo_monitor import get_slo_monitor
        return get_slo_monitor()
    except Exception:
        return None


def _orchestrator() -> Any:
    try:
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        return get_debate_orchestrator()
    except Exception:
        return None


def _store() -> Any:
    try:
        from merid.prediction.debate import get_debate_store
        return get_debate_store()
    except Exception:
        return None


@router.get("/overview", response_model=Dict[str, Any])
async def get_debate_health_overview():
    """Overall debate system health. Returns a stub when the debate subsystem is inactive."""
    now = datetime.now(timezone.utc)
    orchestrator = _orchestrator()
    store = _store()

    if not orchestrator or not store:
        return {
            "timestamp": now.isoformat(),
            **_KALSHI_ONLY_STUB,
            "active_debates": {"count": 0, "symbols": [], "avg_participants": 0},
            "pending_invitations": 0,
            "recent_performance": {"debates_last_24h": 0, "avg_lift": 0.0, "total_lift": 0.0, "success_rate": 0.0},
            "quality_metrics": {"gate_failure_rate": 1.0, "invitation_success_rate": 1.0, "debate_quality_score": 1.0},
            "system_status": {"healthy": True},
        }

    try:
        active_debates = list(orchestrator.active_sessions.values())
        pending_invitations = sum(len(invites) for invites in orchestrator.pending_invitations.values())
        yesterday = now - timedelta(hours=24)

        recent_debates = [
            d for d in store.list_debates(limit=100)
            if d.closed_at and d.closed_at >= yesterday.timestamp()
        ]

        total_lift = sum(d.debate_lift or 0.0 for d in recent_debates)
        avg_lift = total_lift / len(recent_debates) if recent_debates else 0.0

        slo = _slo()
        def _slo_rate(key: str) -> float:
            if not slo:
                return 1.0
            m = slo.get_metric_summary(key)
            return m.get("success_rate", 1.0) if m else 1.0

        return {
            "timestamp": now.isoformat(),
            "active_debates": {
                "count": len(active_debates),
                "symbols": [d.symbol for d in active_debates],
                "avg_participants": (
                    statistics.mean([len(getattr(d, "participant_ids", [])) for d in active_debates])
                    if active_debates else 0
                ),
            },
            "pending_invitations": pending_invitations,
            "recent_performance": {
                "debates_last_24h": len(recent_debates),
                "avg_lift": avg_lift,
                "total_lift": total_lift,
                "success_rate": (
                    sum(1 for d in recent_debates if (d.debate_lift or 0) > 0.01) / len(recent_debates)
                    if recent_debates else 0
                ),
            },
            "quality_metrics": {
                "gate_failure_rate": _slo_rate("debate.gate_failure.rate"),
                "invitation_success_rate": _slo_rate("debate.invitation.success_rate"),
                "debate_quality_score": _slo_rate("debate.quality.score"),
            },
            "system_status": {
                "healthy": len(active_debates) < 50 and avg_lift >= 0.005 and _slo_rate("debate.gate_failure.rate") > 0.8
            },
        }
    except Exception as exc:
        logger.warning("debate_health_overview error: %s", exc)
        return {"timestamp": now.isoformat(), "error": str(exc), "healthy": False}


@router.get("/gate-failures", response_model=Dict[str, Any])
async def get_gate_failure_analysis():
    """Gate failure analysis. Returns empty summary when debate subsystem is inactive."""
    now = datetime.now(timezone.utc).isoformat()
    slo = _slo()
    if not slo:
        return {"timestamp": now, **_KALSHI_ONLY_STUB, "total_failures": 0, "failure_breakdown": {}, "failure_rate": 1.0}

    try:
        gate_failure_metrics = slo.get_metric_summary("debate.gate_failure.rate")
        qualified_shortage_metrics = slo.get_metric_summary("debate.qualified_candidates.shortage")

        failure_reasons = {}
        if gate_failure_metrics and "metadata" in gate_failure_metrics:
            failure_reasons = gate_failure_metrics["metadata"].get("failure_reasons", {})

        total_failures = sum(failure_reasons.values()) if failure_reasons else 0

        return {
            "timestamp": now,
            "total_failures": total_failures,
            "failure_breakdown": failure_reasons,
            "failure_rate": gate_failure_metrics.get("success_rate", 1.0) if gate_failure_metrics else 1.0,
            "qualified_shortage_rate": qualified_shortage_metrics.get("success_rate", 1.0) if qualified_shortage_metrics else 1.0,
            "recommendations": _generate_failure_recommendations(failure_reasons),
        }
    except Exception as exc:
        logger.warning("gate_failure_analysis error: %s", exc)
        return {"timestamp": now, "error": str(exc), "total_failures": 0, "failure_breakdown": {}}


@router.get("/agent-performance", response_model=Dict[str, Any])
async def get_agent_performance_summary():
    """Debate agent performance. Returns empty summary when debate subsystem is inactive."""
    now = datetime.now(timezone.utc)
    store = _store()
    if not store:
        return {"timestamp": now.isoformat(), **_KALSHI_ONLY_STUB, "total_active_agents": 0, "top_performers": []}

    try:
        last_week = now - timedelta(days=7)
        recent_debates = [d for d in store.list_debates(limit=200) if d.created_at >= last_week.timestamp()]

        agent_performance: Dict[str, Dict] = {}
        for debate in recent_debates:
            lift = debate.debate_lift or 0.0
            for agent_id in getattr(debate, "participant_ids", []):
                rec = agent_performance.setdefault(agent_id, {
                    "debates_participated": 0, "total_lift": 0.0, "avg_lift": 0.0, "success_rate": 0.0
                })
                rec["debates_participated"] += 1
                rec["total_lift"] += lift

        for agent_id, perf in agent_performance.items():
            n = perf["debates_participated"]
            if n:
                perf["avg_lift"] = perf["total_lift"] / n
                perf["success_rate"] = sum(
                    1 for d in recent_debates
                    if agent_id in getattr(d, "participant_ids", []) and (d.debate_lift or 0) > 0.01
                ) / n

        top_agents = sorted(agent_performance.items(), key=lambda x: x[1]["avg_lift"], reverse=True)[:10]

        return {
            "timestamp": now.isoformat(),
            "total_active_agents": len(agent_performance),
            "top_performers": [
                {"agent_id": aid, **perf} for aid, perf in top_agents
            ],
            "performance_distribution": {
                "high_performers": sum(1 for p in agent_performance.values() if p["avg_lift"] > 0.02),
                "moderate_performers": sum(1 for p in agent_performance.values() if 0.005 <= p["avg_lift"] <= 0.02),
                "low_performers": sum(1 for p in agent_performance.values() if p["avg_lift"] < 0.005),
            },
        }
    except Exception as exc:
        logger.warning("agent_performance_summary error: %s", exc)
        return {"timestamp": now.isoformat(), "error": str(exc), "total_active_agents": 0, "top_performers": []}


@router.get("/opportunities", response_model=List[Dict[str, Any]])
async def get_debate_opportunities():
    """Current debate opportunities. Returns empty list when debate subsystem is inactive."""
    orchestrator = _orchestrator()
    if not orchestrator:
        return []

    try:
        opportunity_symbols = await orchestrator.get_opportunity_symbols(limit=20)
        return [
            {"symbol": symbol, "disagreement_score": 0.0, "potential_lift": 0.0, "recommended": True}
            for symbol in opportunity_symbols
        ]
    except Exception as exc:
        logger.warning("debate_opportunities error: %s", exc)
        return []


@router.get("/sla-check", response_model=Dict[str, Any])
async def debate_sla_health_check():
    """SLA health check for debate system. Returns passing stub when debate subsystem is inactive."""
    sla_results: Dict[str, Any] = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "violations": [],
        "overall_score": 1.0,
    }

    orchestrator = _orchestrator()
    if not orchestrator:
        sla_results["note"] = "Debate subsystem inactive — SLA checks skipped"
        return sla_results

    try:
        # Check: Debate APIs response time (<2s)
        start = time.time()
        try:
            from web.api.debate_data_api import get_debate_alerts, get_debate_rollups
            await asyncio.wait_for(get_debate_alerts(days_back=1, tier="all", utilization_band="all", problems_only=False), timeout=2.0)
            await asyncio.wait_for(get_debate_rollups(group_by="team", days_back=7), timeout=2.0)
            latency_ms = (time.time() - start) * 1000
            passed = latency_ms < 2000
            sla_results["checks"]["debate_apis_latency_ms"] = {"status": "pass" if passed else "fail", "value": latency_ms, "sla_threshold": 2000}
            if not passed:
                sla_results["violations"].append(f"Debate APIs latency {latency_ms:.0f}ms > 2000ms SLA")
                sla_results["overall_score"] -= 0.3
        except asyncio.TimeoutError:
            sla_results["checks"]["debate_apis_latency_ms"] = {"status": "fail", "value": ">2000", "sla_threshold": 2000}
            sla_results["violations"].append("Debate APIs timeout")
            sla_results["overall_score"] -= 0.5

        # Clamp score
        sla_results["overall_score"] = max(0.0, sla_results["overall_score"])

        if sla_results["overall_score"] >= 0.8:
            sla_results["status"] = "healthy"
        elif sla_results["overall_score"] >= 0.5:
            sla_results["status"] = "degraded"
        else:
            sla_results["status"] = "critical"

    except Exception as exc:
        sla_results["status"] = "critical"
        sla_results["violations"].append(f"SLA check failed: {exc}")
        sla_results["overall_score"] = 0.0

    return sla_results


def _generate_failure_recommendations(failure_breakdown: Dict[str, int]) -> List[str]:
    recommendations = []
    if not failure_breakdown:
        return recommendations
    total = sum(failure_breakdown.values())
    if failure_breakdown.get("domain_violation", 0) / total > 0.1:
        recommendations.append("High domain violation rate — check agent data sources and domain tagging")
    if failure_breakdown.get("gate_failure", 0) / total > 0.5:
        recommendations.append("High gate failure rate — consider adjusting gate thresholds")
    if sum(v for k, v in failure_breakdown.items() if "accuracy" in k.lower()) > total * 0.3:
        recommendations.append("Many accuracy failures — review prediction models and training data")
    return recommendations
