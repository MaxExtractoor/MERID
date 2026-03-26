"""Dependency Health Monitor - Track critical subsystem health for trading.

Monitors:
  - Kalshi WebSocket connection status and liveness
  - Market catalog freshness and availability
  - Execution pipeline readiness
  - Data feed staleness

Provides dependency health status for execution gate integration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.monitoring.dependency_health")


class DependencyStatus(str, Enum):
    """Dependency health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


@dataclass
class DependencyHealthCheck:
    """Health check result for a single dependency."""
    name: str
    status: DependencyStatus
    message: str = ""
    details: Optional[Dict[str, any]] = None
    last_check_ts: float = field(default_factory=time.time)
    stale_threshold_seconds: float = 60.0  # Consider check stale after this time

    @property
    def is_stale(self) -> bool:
        """Check if this health check is too old to trust."""
        return (time.time() - self.last_check_ts) > self.stale_threshold_seconds

    @property
    def is_healthy(self) -> bool:
        """Check if dependency is healthy."""
        return self.status == DependencyStatus.HEALTHY

    @property
    def is_critical(self) -> bool:
        """Check if dependency is in critical state (down or stale)."""
        return self.status == DependencyStatus.DOWN or self.is_stale


def check_kalshi_websocket_health() -> DependencyHealthCheck:
    """Check Kalshi WebSocket connection health.

    Returns:
        DependencyHealthCheck with current WebSocket status
    """
    try:
        from merid.event_venues.kalshi.ws_manager import get_ws_manager

        ws_manager = get_ws_manager()
        ws_client = ws_manager._ws_client

        if not ws_client:
            return DependencyHealthCheck(
                name="kalshi_websocket",
                status=DependencyStatus.DOWN,
                message="WebSocket client not initialized",
            )

        # Get WebSocket stats
        stats = ws_client.stats()
        connected = stats.get("connected", False)
        last_msg_ago = stats.get("last_msg_ago_s", float("inf"))
        reconnect_count = stats.get("reconnect_count", 0)
        seq_gaps = stats.get("seq_gaps", 0)
        errors_received = stats.get("errors_received", 0)

        # Determine status based on connection state and recent activity
        if not connected:
            status = DependencyStatus.DOWN
            message = "WebSocket disconnected"
        elif last_msg_ago > 120:  # No message in 2 minutes
            status = DependencyStatus.DEGRADED
            message = f"No messages received for {last_msg_ago:.0f}s"
        elif seq_gaps > 10:  # Too many sequence gaps
            status = DependencyStatus.DEGRADED
            message = f"High sequence gap count: {seq_gaps}"
        elif reconnect_count > 5:  # Frequent reconnections
            status = DependencyStatus.DEGRADED
            message = f"Frequent reconnections: {reconnect_count}"
        else:
            status = DependencyStatus.HEALTHY
            message = "WebSocket healthy and receiving messages"

        return DependencyHealthCheck(
            name="kalshi_websocket",
            status=status,
            message=message,
            details={
                "connected": connected,
                "last_msg_ago_s": last_msg_ago,
                "reconnect_count": reconnect_count,
                "seq_gaps": seq_gaps,
                "errors_received": errors_received,
                "uptime_s": stats.get("uptime_s", 0),
                "messages_received": stats.get("messages_received", 0),
            },
        )
    except Exception as exc:
        logger.debug("Kalshi WebSocket health check failed: %s", exc)
        return DependencyHealthCheck(
            name="kalshi_websocket",
            status=DependencyStatus.UNKNOWN,
            message=f"Health check error: {exc}",
        )


def check_market_catalog_health() -> DependencyHealthCheck:
    """Check market catalog freshness and availability.

    Returns:
        DependencyHealthCheck with current catalog status
    """
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        catalog = get_market_catalog()
        market_count = len(catalog._markets)
        last_refresh_ts = catalog._last_refresh_ts if hasattr(catalog, '_last_refresh_ts') else 0

        if market_count == 0:
            return DependencyHealthCheck(
                name="market_catalog",
                status=DependencyStatus.DOWN,
                message="Market catalog empty",
            )

        age_seconds = time.time() - last_refresh_ts if last_refresh_ts > 0 else float("inf")

        # Catalog should refresh every 5 minutes (300s)
        if age_seconds > 600:  # 10 minutes - stale
            status = DependencyStatus.DEGRADED
            message = f"Catalog stale: {age_seconds:.0f}s since last refresh"
        elif age_seconds > 360:  # 6 minutes - warning
            status = DependencyStatus.DEGRADED
            message = f"Catalog aging: {age_seconds:.0f}s since last refresh"
        else:
            status = DependencyStatus.HEALTHY
            message = f"{market_count} markets loaded"

        return DependencyHealthCheck(
            name="market_catalog",
            status=status,
            message=message,
            details={
                "market_count": market_count,
                "age_seconds": round(age_seconds, 1) if age_seconds != float("inf") else None,
                "last_refresh_ts": last_refresh_ts,
            },
        )
    except Exception as exc:
        logger.debug("Market catalog health check failed: %s", exc)
        return DependencyHealthCheck(
            name="market_catalog",
            status=DependencyStatus.UNKNOWN,
            message=f"Health check error: {exc}",
        )


def get_overall_dependency_health() -> Dict[str, any]:
    """Get overall dependency health status.

    Returns:
        dict with:
            - overall_status: "healthy" | "degraded" | "down"
            - kalshi_websocket: DependencyHealthCheck
            - market_catalog: DependencyHealthCheck
            - critical_issues: list of critical problems
    """
    ws_health = check_kalshi_websocket_health()
    catalog_health = check_market_catalog_health()

    checks = {
        "kalshi_websocket": ws_health,
        "market_catalog": catalog_health,
    }

    # Determine overall status
    critical_issues = []
    has_down = False
    has_degraded = False

    for name, check in checks.items():
        if check.status == DependencyStatus.DOWN:
            has_down = True
            critical_issues.append(f"{name}: {check.message}")
        elif check.status == DependencyStatus.DEGRADED:
            has_degraded = True
        elif check.is_stale:
            has_degraded = True
            critical_issues.append(f"{name}: health check stale")

    if has_down:
        overall_status = "down"
    elif has_degraded:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "overall_status": overall_status,
        "kalshi_websocket": {
            "status": ws_health.status.value,
            "message": ws_health.message,
            "details": ws_health.details,
        },
        "market_catalog": {
            "status": catalog_health.status.value,
            "message": catalog_health.message,
            "details": catalog_health.details,
        },
        "critical_issues": critical_issues,
        "timestamp": time.time(),
    }


def is_trading_ready() -> tuple[bool, list[str]]:
    """Check if all dependencies are ready for live trading.

    Returns:
        (ready, issues) where ready=True if safe to trade, issues=list of blocking problems
    """
    health = get_overall_dependency_health()
    issues = []

    # Check WebSocket
    ws_status = health["kalshi_websocket"]["status"]
    if ws_status == "down":
        issues.append("Kalshi WebSocket is down - cannot trade without live data")
    elif ws_status == "degraded":
        issues.append(f"Kalshi WebSocket degraded: {health['kalshi_websocket']['message']}")

    # Check catalog
    catalog_status = health["market_catalog"]["status"]
    if catalog_status == "down":
        issues.append("Market catalog unavailable - no markets to trade")

    # Overall status check
    if health["overall_status"] == "down":
        issues.append("Critical dependencies are down")

    ready = len(issues) == 0
    return ready, issues
