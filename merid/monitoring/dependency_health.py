"""Dependency health evaluation for external Kalshi subsystems.

Surfaces lightweight diagnostics for:
  - kalshi_websocket (real-time price/trade feed)
  - market_catalog (REST discovery cache)

Keeps the logic centralized so HTTP endpoints and system health checks
share the same classification rules.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class DependencyStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    DISABLED = "disabled"


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _get_ws_summary() -> Dict[str, Any]:
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge

        return get_ws_bridge().summary()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc), "running": False}


def _get_catalog_summary() -> Dict[str, Any]:
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        return get_market_catalog().summary()
    except Exception as exc:  # pragma: no cover - defensive
        return {"error": str(exc), "running": False}


def _ws_status(summary: Dict[str, Any], disabled: bool) -> Dict[str, Any]:
    """Classify Kalshi WebSocket health."""
    diagnostics: Dict[str, Any] = {}
    if disabled:
        return {
            "status": DependencyStatus.DISABLED.value,
            "diagnostics": {"reason": "disabled_via_env"},
        }

    running = bool(summary.get("running"))
    ws_client = summary.get("ws_client") or {}
    connected = bool(ws_client.get("connected"))
    last_msg = ws_client.get("last_msg_ago_s")
    messages = ws_client.get("messages_received", 0) or 0

    degraded_threshold = float(
        os.getenv("MERID_KALSHI_WS_STALE_DEGRADED_S", "90.0")
    )
    down_threshold = float(os.getenv("MERID_KALSHI_WS_STALE_DOWN_S", "240.0"))

    diagnostics.update(
        {
            "running": running,
            "connected": connected,
            "last_msg_ago_s": last_msg,
            "messages_received": messages,
            "reconnect_count": ws_client.get("reconnect_count"),
            "errors_received": ws_client.get("errors_received"),
            "queue_depth": summary.get("queue_depth"),
            "queue_max": summary.get("queue_max"),
        }
    )

    if not running:
        diagnostics["reason"] = "bridge_not_running"
        return {"status": DependencyStatus.DOWN.value, "diagnostics": diagnostics}

    if not connected:
        diagnostics["reason"] = "ws_not_connected"
        return {"status": DependencyStatus.DEGRADED.value, "diagnostics": diagnostics}

    if last_msg is None and messages == 0:
        diagnostics["reason"] = "no_messages_yet"
        return {"status": DependencyStatus.DEGRADED.value, "diagnostics": diagnostics}

    try:
        last_msg_age = float(last_msg or 0.0)
    except (TypeError, ValueError):
        last_msg_age = None

    if last_msg_age is not None:
        diagnostics["last_msg_ago_s"] = last_msg_age
        if last_msg_age > down_threshold:
            diagnostics["reason"] = "stale_ws_feed"
            diagnostics["threshold_s"] = down_threshold
            return {"status": DependencyStatus.DOWN.value, "diagnostics": diagnostics}
        if last_msg_age > degraded_threshold:
            diagnostics["reason"] = "stale_ws_feed"
            diagnostics["threshold_s"] = degraded_threshold
            return {
                "status": DependencyStatus.DEGRADED.value,
                "diagnostics": diagnostics,
            }

    diagnostics["reason"] = "ok"
    return {"status": DependencyStatus.HEALTHY.value, "diagnostics": diagnostics}


def _catalog_status(summary: Dict[str, Any], disabled: bool) -> Dict[str, Any]:
    """Classify market catalog health."""
    diagnostics: Dict[str, Any] = {}
    if disabled:
        return {
            "status": DependencyStatus.DISABLED.value,
            "diagnostics": {"reason": "disabled_via_env"},
        }

    market_count = summary.get("market_count", 0) or 0
    last_refresh_raw = summary.get("last_refresh")
    last_refresh = _parse_iso(last_refresh_raw)
    running = bool(summary.get("running"))
    diagnostics.update(
        {
            "running": running,
            "market_count": market_count,
            "last_refresh": last_refresh_raw,
            "refresh_count": summary.get("refresh_count"),
            "by_asset": summary.get("assets"),
            "by_timeframe": summary.get("timeframes"),
        }
    )

    if not last_refresh:
        diagnostics["reason"] = "no_refresh_seen"
        return {"status": DependencyStatus.DOWN.value, "diagnostics": diagnostics}

    age_s = max(0.0, time.time() - last_refresh.timestamp())
    diagnostics["age_s"] = age_s

    degraded_threshold = float(
        os.getenv("MERID_MARKET_CATALOG_STALE_DEGRADED_S", "900.0")
    )
    down_threshold = float(
        os.getenv("MERID_MARKET_CATALOG_STALE_DOWN_S", "1800.0")
    )

    if age_s > down_threshold:
        diagnostics.update({"reason": "catalog_stale", "threshold_s": down_threshold})
        return {"status": DependencyStatus.DOWN.value, "diagnostics": diagnostics}
    if age_s > degraded_threshold:
        diagnostics.update(
            {"reason": "catalog_stale", "threshold_s": degraded_threshold}
        )
        return {"status": DependencyStatus.DEGRADED.value, "diagnostics": diagnostics}

    if market_count <= 0:
        diagnostics["reason"] = "empty_catalog"
        return {"status": DependencyStatus.DEGRADED.value, "diagnostics": diagnostics}

    diagnostics["reason"] = "ok"
    return {"status": DependencyStatus.HEALTHY.value, "diagnostics": diagnostics}


def get_dependencies_health() -> Dict[str, Any]:
    """Return dependency health snapshot for operators."""
    ws_disabled = os.getenv("MERID_DISABLE_KALSHI_WS", "").lower() in ("1", "true")
    cat_disabled = os.getenv("MERID_DISABLE_MARKET_CATALOG", "").lower() in ("1", "true")

    ws = _ws_status(_get_ws_summary(), ws_disabled)
    catalog = _catalog_status(_get_catalog_summary(), cat_disabled)

    deps = {
        "kalshi_websocket": ws,
        "market_catalog": catalog,
    }

    statuses = {d["status"] for d in deps.values()}
    if statuses and statuses.issubset({DependencyStatus.DISABLED.value}):
        overall = DependencyStatus.DISABLED.value
    elif DependencyStatus.DOWN.value in statuses:
        overall = DependencyStatus.DOWN.value
    elif DependencyStatus.DEGRADED.value in statuses:
        overall = DependencyStatus.DEGRADED.value
    else:
        overall = DependencyStatus.HEALTHY.value

    return {
        "overall_status": overall,
        "dependencies": deps,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
