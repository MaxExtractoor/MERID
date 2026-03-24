"""Dependency health for LIVE surfaces: Kalshi WebSocket + market catalog."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/dependencies", tags=["dependency-health"])

# Tunables (can be overridden via env for ops experimentation)
WS_MAX_STALE_S = float(os.getenv("KALSHI_WS_MAX_STALE_S", "45"))
CATALOG_MAX_STALE_S = float(os.getenv("KALSHI_CATALOG_MAX_STALE_S", "300"))


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def _load_ws_summary() -> Dict[str, Any]:
    """Isolated import so tests can stub safely."""
    from merid.event_venues.kalshi.ws_bridge import get_ws_bridge

    return get_ws_bridge().summary()


def _load_catalog_summary() -> Dict[str, Any]:
    """Isolated import so tests can stub safely."""
    from merid.event_venues.kalshi.market_catalog import get_market_catalog

    return get_market_catalog().summary()


def _classify_ws(summary: Dict[str, Any]) -> Dict[str, Any]:
    running = bool(summary.get("running"))
    ws_client = summary.get("ws_client", {}) or {}
    connected = bool(ws_client.get("connected"))
    last_msg_age = ws_client.get("last_msg_ago_s")
    subscriptions = ws_client.get("subscriptions", summary.get("subscribed_tickers", 0))
    reconnects = ws_client.get("reconnect_count", summary.get("forward_errors", 0))
    events_forwarded = summary.get("events_forwarded", 0)

    issues = []
    if not running:
        issues.append("bridge_not_running")
    if running and not connected:
        issues.append("ws_not_connected")
    if running and connected:
        if last_msg_age is None:
            issues.append("no_messages_yet")
        elif last_msg_age > WS_MAX_STALE_S:
            issues.append("stale_stream")

    if not issues:
        status = "healthy"
    elif not running:
        status = "down"
    else:
        status = "degraded"

    return {
        "name": "kalshi_websocket",
        "status": status,
        "issues": issues,
        "detail": {
            "running": running,
            "connected": connected,
            "last_message_age_s": last_msg_age,
            "subscriptions": subscriptions,
            "reconnects": reconnects,
            "events_forwarded": events_forwarded,
            "queue_depth": summary.get("queue_depth"),
        },
    }


def _classify_catalog(summary: Dict[str, Any], now: float) -> Dict[str, Any]:
    market_count = int(summary.get("market_count", 0) or 0)
    last_refresh_raw = summary.get("last_refresh")
    last_refresh_ts = None
    try:
        if last_refresh_raw:
            last_refresh_dt = datetime.fromisoformat(str(last_refresh_raw))
            last_refresh_ts = last_refresh_dt.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        last_refresh_ts = None

    age_s = now - last_refresh_ts if last_refresh_ts else None
    categories = summary.get("categories", {})
    assets = summary.get("assets", {})
    timeframes = summary.get("timeframes", {})

    issues = []
    if market_count == 0:
        issues.append("empty_catalog")
    if age_s is None:
        issues.append("no_refresh_timestamp")
    elif age_s > CATALOG_MAX_STALE_S:
        issues.append("stale_catalog")

    if not issues:
        status = "healthy"
    elif market_count == 0 and (age_s is None or age_s > CATALOG_MAX_STALE_S):
        status = "down"
    else:
        status = "degraded"

    return {
        "name": "market_catalog",
        "status": status,
        "issues": issues,
        "detail": {
            "market_count": market_count,
            "last_refresh": last_refresh_raw,
            "age_seconds": age_s,
            "categories": categories,
            "assets": assets,
            "timeframes": timeframes,
            "refreshing": bool(summary.get("running")),
            "refresh_count": summary.get("refresh_count"),
        },
    }


def evaluate_dependencies() -> Dict[str, Any]:
    """Evaluate dependency health and produce an operator-friendly view."""
    now = time.time()
    deps = []

    if _bool_env("MERID_DISABLE_KALSHI_WS") or _bool_env("KALSHI_WS_DISABLED"):
        deps.append(
            {
                "name": "kalshi_websocket",
                "status": "disabled",
                "issues": [],
                "detail": {"reason": "explicitly_disabled"},
            }
        )
    else:
        try:
            deps.append(_classify_ws(_load_ws_summary()))
        except Exception as exc:
            deps.append(
                {
                    "name": "kalshi_websocket",
                    "status": "down",
                    "issues": ["probe_failed"],
                    "detail": {"error": str(exc)},
                }
            )

    if _bool_env("MERID_DISABLE_MARKET_CATALOG") or _bool_env("KALSHI_CATALOG_DISABLED"):
        deps.append(
            {
                "name": "market_catalog",
                "status": "disabled",
                "issues": [],
                "detail": {"reason": "explicitly_disabled"},
            }
        )
    else:
        try:
            deps.append(_classify_catalog(_load_catalog_summary(), now))
        except Exception as exc:
            deps.append(
                {
                    "name": "market_catalog",
                    "status": "down",
                    "issues": ["probe_failed"],
                    "detail": {"error": str(exc)},
                }
            )

    status_rank = {"healthy": 0, "disabled": 0, "degraded": 1, "down": 2, "unknown": 2}
    worst = max(deps, key=lambda d: status_rank.get(d.get("status", "unknown"), 2))
    overall_status = worst.get("status", "unknown")
    if overall_status == "disabled" and any(d["status"] == "healthy" for d in deps):
        overall_status = "healthy"

    return {
        "checked_at": now,
        "overall_status": overall_status,
        "dependencies": {d["name"]: d for d in deps},
    }


@router.get("/health")
async def dependency_health() -> Dict[str, Any]:
    """Public dependency health endpoint for dashboards and banners."""
    return evaluate_dependencies()
