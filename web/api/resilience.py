"""Resilience API — unified view of circuit breakers, bulkheads, and venue health.

Endpoints:
  GET /api/v1/resilience/status       — Full resilience snapshot (breakers + bulkheads + venue health)
  GET /api/v1/resilience/breakers     — Circuit breaker states only
  GET /api/v1/resilience/bulkheads    — Bulkhead utilization only
  GET /api/v1/resilience/venues       — Unified venue health (adapter + breaker + mode)
  GET /api/v1/resilience/metrics      — Prometheus exposition format for all resilience metrics
  POST /api/v1/resilience/breakers/{name}/reset — Reset a specific circuit breaker
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.resilience")

router = APIRouter(prefix="/api/v1/resilience", tags=["resilience"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Helpers ───────────────────────────────────────────────────────────

def _get_breaker_summaries() -> List[Dict[str, Any]]:
    """Collect circuit breaker stats from the resilience registry."""
    try:
        from merid.resilience.circuit_breaker import get_all_breakers
    except ImportError:
        return []

    breakers = get_all_breakers()
    return [b.get_stats() for b in breakers.values()]


def _get_bulkhead_summaries() -> List[Dict[str, Any]]:
    """Collect bulkhead stats from the resilience registry."""
    try:
        from merid.resilience.bulkhead import get_all_bulkheads
    except ImportError:
        return []

    bulkheads = get_all_bulkheads()
    result = []
    for name, bh in bulkheads.items():
        stats = bh.get_stats()
        result.append({
            "name": name,
            "active": stats.active_count,
            "max_concurrent": stats.max_concurrent,
            "queued": stats.queued_count,
            "max_queued": stats.max_queued,
            "total_accepted": stats.total_accepted,
            "total_rejected": stats.total_rejected,
            "avg_wait_ms": stats.avg_wait_ms,
        })
    return result


def _get_venue_health() -> List[Dict[str, Any]]:
    """Build unified venue health: adapter status + breaker state + mode.

    Combines data from:
    - Pipeline ModeManager (venue configs: mode, enabled, credentials)
    - Resilience CircuitBreaker registry (breaker state per venue)
    - Pipeline AdapterRegistry (adapter health_check)
    """
    venues: Dict[str, Dict[str, Any]] = {}

    # 1. Venue configs from ModeManager
    try:
        from merid.pipeline.mode_manager import get_mode_manager
        mm = get_mode_manager()
        for vc in mm.get_all_configs():
            d = vc.to_dict()
            venues[vc.venue] = {
                "venue": vc.venue,
                "domain": vc.domain,
                "mode": d["mode"],
                "enabled": d["enabled"],
                "has_credentials": d["has_credentials"],
                "breaker_state": "closed",
                "breaker_failures": 0,
                "adapter_status": "unknown",
                "health": "healthy",
            }
    except Exception as exc:
        logger.debug(f"Mode manager venues error (ignored): {exc}")

    # 2. Overlay circuit breaker state
    try:
        from merid.resilience.circuit_breaker import get_all_breakers
        for name, breaker in get_all_breakers().items():
            stats = breaker.get_stats()
            if name in venues:
                venues[name]["breaker_state"] = stats["state"]
                venues[name]["breaker_failures"] = stats["failure_count"]
            else:
                venues[name] = {
                    "venue": name,
                    "domain": "unknown",
                    "mode": "unknown",
                    "enabled": True,
                    "has_credentials": False,
                    "breaker_state": stats["state"],
                    "breaker_failures": stats["failure_count"],
                    "adapter_status": "unknown",
                    "health": "healthy",
                }
    except Exception as exc:
        logger.debug(f"Circuit breaker overlay error (ignored): {exc}")

    # 3. Compute overall health per venue
    for v in venues.values():
        if not v["enabled"]:
            v["health"] = "disabled"
        elif v["breaker_state"] == "open":
            v["health"] = "unhealthy"
        elif v["breaker_state"] == "half_open":
            v["health"] = "degraded"
        elif v["breaker_failures"] > 0:
            v["health"] = "degraded"
        else:
            v["health"] = "healthy"

    return list(venues.values())


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/status")
async def get_resilience_status() -> Dict[str, Any]:
    """Full resilience snapshot: breakers, bulkheads, venue health."""
    breakers = _get_breaker_summaries()
    bulkheads = _get_bulkhead_summaries()
    venue_health = _get_venue_health()

    # Aggregate health
    open_count = sum(1 for b in breakers if b["state"] == "open")
    degraded_count = sum(1 for v in venue_health if v["health"] == "degraded")
    unhealthy_count = sum(1 for v in venue_health if v["health"] == "unhealthy")

    if unhealthy_count > 0:
        overall = "unhealthy"
    elif degraded_count > 0 or open_count > 0:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_health": overall,
        "circuit_breakers": breakers,
        "bulkheads": bulkheads,
        "venue_health": venue_health,
        "summary": {
            "breakers_total": len(breakers),
            "breakers_open": open_count,
            "venues_total": len(venue_health),
            "venues_healthy": sum(1 for v in venue_health if v["health"] == "healthy"),
            "venues_degraded": degraded_count,
            "venues_unhealthy": unhealthy_count,
        },
    }


@router.get("/breakers")
async def get_breakers() -> Dict[str, Any]:
    """Circuit breaker states."""
    return {"circuit_breakers": _get_breaker_summaries()}


@router.get("/bulkheads")
async def get_bulkheads() -> Dict[str, Any]:
    """Bulkhead utilization."""
    return {"bulkheads": _get_bulkhead_summaries()}


@router.get("/venues")
async def get_venues() -> Dict[str, Any]:
    """Unified venue health view."""
    return {"venues": _get_venue_health()}


@router.post("/breakers/{name}/reset")
async def reset_breaker(name: str) -> Dict[str, Any]:
    """Reset a specific circuit breaker to CLOSED state."""
    try:
        from merid.resilience.circuit_breaker import get_all_breakers
    except ImportError:
        raise HTTPException(status_code=501, detail="Resilience module not available")

    breakers = get_all_breakers()
    if name not in breakers:
        raise HTTPException(status_code=404, detail=f"Circuit breaker '{name}' not found")

    breaker = breakers[name]
    old_state = breaker.state.value
    breaker.reset()

    logger.info(f"Circuit breaker '{name}' manually reset from {old_state} to closed")

    return {
        "ok": True,
        "name": name,
        "old_state": old_state,
        "new_state": "closed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics")
async def resilience_metrics() -> Response:
    """Prometheus exposition format for all resilience metrics.

    Includes circuit breaker, bulkhead, and risk metrics from the
    MetricsCollector. Scrape with:
        - job_name: merid_resilience
          metrics_path: /api/v1/resilience/metrics
          static_configs:
            - targets: ['localhost:8011']
    """
    try:
        from merid.resilience.metrics import get_metrics_text
        body = get_metrics_text()
    except ImportError:
        body = "# merid_resilience_available 0\n"

    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
