"""Shared helpers to expose Kalshi venue health + reconciliation state."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from utils.logger import get_logger
from merid.settings import settings

logger = get_logger("web.api.kalshi_status")


async def get_kalshi_status() -> Optional[Dict[str, Any]]:
    """Gather Kalshi venue health, reconciliation, and breaker stats."""
    try:
        adapter = _get_kalshi_adapter_for_risk()
    except Exception as exc:
        logger.warning("kalshi_status_adapter_unavailable: %s", exc)
        return {
            "venue_health": {"healthy": False, "error_code": "adapter_unavailable"},
            "reconciliation": {
                "degraded": True,
                "severity": "unknown",
                "summary": "adapter unavailable",
            },
        }

    from merid.event_venues.kalshi.venue_adapter import KalshiVenueError

    try:
        health_raw = await adapter.get_health()
        venue_health: Dict[str, Any] = {
            "healthy": bool(health_raw.get("healthy", True)),
            "detail": health_raw,
            "error_code": _extract_error_code(health_raw.get("error")),
        }
    except KalshiVenueError as exc:
        logger.warning("kalshi_status_health_error: %s", exc)
        venue_health = {
            "healthy": False,
            "error_code": getattr(exc, "code", "health_check_failed"),
            "detail": exc.detail,
        }
    except Exception as exc:
        logger.warning("kalshi_status_health_unexpected: %s", exc)
        venue_health = {
            "healthy": False,
            "error_code": "unknown",
            "detail": {"error": str(exc)},
        }

    reconciliation = await _get_reconciliation_snapshot()

    breaker_stats: Dict[str, Any] = {}
    if hasattr(adapter, "get_health_stats"):
        try:
            stats = adapter.get_health_stats()
            breaker_stats = stats.get("circuit_breakers", {})
            venue_health.setdefault("detail", {}).setdefault("stats", {}).update(stats)
        except Exception as exc:
            logger.debug("kalshi_status_health_stats_error: %s", exc)

    return {
        "venue_health": venue_health,
        "reconciliation": reconciliation,
        "circuit_breakers": breaker_stats,
    }


async def _get_reconciliation_snapshot() -> Dict[str, Any]:
    """Return the latest reconciliation metadata if available."""
    try:
        from merid.reconciliation.kalshi_reconciler import get_kalshi_reconciler

        reconciler = get_kalshi_reconciler()
        report = reconciler.get_last_report()
        if report is None:
            return {
                "degraded": True,
                "severity": "unknown",
                "summary": "no reconciliation report yet",
            }

        age_seconds = time.time() - report.timestamp
        return {
            "degraded": report.degraded,
            "severity": report.severity,
            "summary": report.summary,
            "issue_count": len(report.issues),
            "degraded_reason": report.degraded_reason,
            "age_seconds": round(age_seconds, 1),
        }
    except Exception as exc:
        logger.warning("kalshi_status_reconciliation_error: %s", exc)
        return {
            "degraded": True,
            "severity": "unknown",
            "summary": f"reconciliation unavailable: {exc}",
        }


def _get_kalshi_adapter_for_risk():
    """Select Kalshi adapter - enhanced adapter removed, use standard adapter."""
    from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
    return get_kalshi_venue_adapter()


def _extract_error_code(error_field: Any) -> Optional[str]:
    if isinstance(error_field, dict):
        return error_field.get("code")
    if isinstance(error_field, str):
        return error_field
    return None
