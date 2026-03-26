"""Dependency Health API - Expose subsystem health status.

Provides REST endpoints for monitoring critical dependency health:
  - Kalshi WebSocket connection
  - Market catalog freshness
  - Overall system health

Used by monitoring dashboards and execution gate validation.
"""

from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger("web.api.dependency_health")

router = APIRouter(prefix="/api/v1/dependencies", tags=["dependencies"])


@router.get("/health")
async def get_dependency_health():
    """Get overall dependency health status.

    Returns:
        dict with:
            - overall_status: "healthy" | "degraded" | "down"
            - kalshi_websocket: WebSocket health details
            - market_catalog: Catalog health details
            - critical_issues: List of critical problems
            - timestamp: Check timestamp
    """
    from merid.monitoring.dependency_health import get_overall_dependency_health

    try:
        health = get_overall_dependency_health()
        return health
    except Exception as exc:
        logger.error("Failed to get dependency health: %s", exc)
        return {
            "overall_status": "unknown",
            "error": str(exc),
            "timestamp": 0,
        }


@router.get("/websocket")
async def get_websocket_health():
    """Get Kalshi WebSocket health details.

    Returns:
        dict with:
            - status: "healthy" | "degraded" | "down" | "unknown"
            - message: Human-readable status message
            - details: Connection statistics and performance metrics
    """
    from merid.monitoring.dependency_health import check_kalshi_websocket_health

    try:
        health = check_kalshi_websocket_health()
        return {
            "status": health.status.value,
            "message": health.message,
            "details": health.details,
            "is_healthy": health.is_healthy,
            "is_critical": health.is_critical,
            "last_check_ts": health.last_check_ts,
        }
    except Exception as exc:
        logger.error("Failed to check WebSocket health: %s", exc)
        return {
            "status": "unknown",
            "message": f"Health check error: {exc}",
            "is_healthy": False,
        }


@router.get("/catalog")
async def get_catalog_health():
    """Get market catalog health details.

    Returns:
        dict with:
            - status: "healthy" | "degraded" | "down" | "unknown"
            - message: Human-readable status message
            - details: Catalog size and freshness metrics
    """
    from merid.monitoring.dependency_health import check_market_catalog_health

    try:
        health = check_market_catalog_health()
        return {
            "status": health.status.value,
            "message": health.message,
            "details": health.details,
            "is_healthy": health.is_healthy,
            "is_critical": health.is_critical,
            "last_check_ts": health.last_check_ts,
        }
    except Exception as exc:
        logger.error("Failed to check catalog health: %s", exc)
        return {
            "status": "unknown",
            "message": f"Health check error: {exc}",
            "is_healthy": False,
        }


@router.get("/ready")
async def get_trading_readiness():
    """Check if system is ready for live trading.

    Returns:
        dict with:
            - ready: bool - True if safe to trade
            - issues: List of blocking issues
    """
    from merid.monitoring.dependency_health import is_trading_ready

    try:
        ready, issues = is_trading_ready()
        return {
            "ready": ready,
            "issues": issues,
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.error("Failed to check trading readiness: %s", exc)
        return {
            "ready": False,
            "issues": [f"Readiness check error: {exc}"],
        }


import time
