"""
Kalshi-Only Shim Endpoints (Audit 2026-03-19)

All endpoints in this file are now backed by real implementations.
See docs/kalshi_wiring_todo.md for promotion status.

Removed shims (promoted or deleted as duplicates):
  - /reconciliation/run, /reconciliation/status → system_endpoints.py (duplicates)
  - /risk/downsize-all, DELETE /risk/kill-switch → risk_routes.py (promoted)
  - /system/pause-agents → system_endpoints.py (promoted)
  - /kalshi/lane/status → crypto_lanes_api.py GET /crypto/status (duplicate)
  - /lanes/{lane_id}/toggle → crypto_lanes_api.py POST /{lane_id}/toggle (duplicate)
  - /notifications/status → notification_api.py GET /status (duplicate)
  - /notifications/recent-alerts → notification_api.py GET /recent-alerts (duplicate)
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_shims")

router = APIRouter(tags=["kalshi-shims"])


# ── Error reporting ──────────────────────────────────────────────────
# Backed by core.error_store.FrontendErrorStore (SQLite, auto-rotating).

class ErrorReportPayload(BaseModel):
    """Frontend error report — persisted to SQLite error store."""
    timestamp: Optional[str] = Field(None, description="ISO-8601 when the error occurred")
    message: str = Field(..., description="Human-readable error message")
    stack: Optional[str] = Field(None, description="Stack trace if available")
    route: Optional[str] = Field(None, description="Frontend route where the error occurred")
    client_tag: Optional[str] = Field(None, description="Client build tag / version")


@router.post("/api/v1/errors/report")
async def errors_report(payload: ErrorReportPayload) -> Dict[str, Any]:
    """Accept and persist error reports from the frontend."""
    logger.info("frontend_error_report: route=%s msg=%s", payload.route, payload.message[:120])
    try:
        from core.error_store import record_frontend_error
        err = record_frontend_error(
            message=payload.message,
            timestamp=payload.timestamp,
            stack=payload.stack,
            route=payload.route,
            client_tag=payload.client_tag,
        )
        return {"accepted": True, "persisted": True, "error_id": err.id}
    except Exception as exc:
        logger.warning("error store write failed: %s", exc)
        return {"accepted": True, "persisted": False, "message": str(exc)}


@router.get("/api/v1/errors/recent")
async def errors_recent(
    limit: int = 50,
    since_ms: Optional[int] = None,
    route: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve recent frontend errors from the error store."""
    try:
        from core.error_store import get_error_store
        store = get_error_store()
        errors = store.list_errors(limit=limit, since_ms=since_ms, route=route)
        return {
            "errors": [e.to_dict() for e in errors],
            "count": len(errors),
            "source": "error_store",
        }
    except Exception as exc:
        logger.warning("error store read failed: %s", exc)
        return {"errors": [], "count": 0, "source": "error", "message": str(exc)}


@router.get("/api/v1/errors/stats")
async def errors_stats() -> Dict[str, Any]:
    """Aggregate stats for frontend error reports."""
    try:
        from core.error_store import get_error_store
        return get_error_store().get_stats()
    except Exception as exc:
        logger.warning("error store stats failed: %s", exc)
        return {"healthy": False, "error": str(exc)}


# ── Venues ──────────────────────────────────────────────────────────
# Layer 1: merid.venue_registry (high-level — enable/disable, async ops)
# Layer 2: trading.adapters.registry (low-level — health, latency)
# Layer 3: static Kalshi-only fallback

_VENUE_TYPE: Dict[str, str] = {
    "kalshi": "prediction_market",
    "paper": "paper_trading",
}

_VENUE_NAME: Dict[str, str] = {
    "kalshi": "Kalshi",
    "paper": "Paper Trading",
}


@router.get("/api/v1/venues")
async def list_venues() -> Dict[str, Any]:
    """List available trading venues from the venue registries.

    Tries the high-level VenueRegistry first (has enable/disable state),
    enriches with low-level adapter health, then falls back to a static
    Kalshi entry when neither registry is populated.
    """
    # Layer 1: high-level VenueRegistry
    try:
        from merid.venue_registry import get_venue_registry
        vr = get_venue_registry()
        venue_names = vr.list_venues(enabled_only=False)
        if venue_names:
            venues = []
            # Optionally enrich with low-level adapter health
            adapter_health: Dict[str, Any] = {}
            try:
                from trading.adapters.registry import list_adapters
                for vid, adapter in list_adapters().items():
                    h = adapter.get_health()
                    adapter_health[vid] = {
                        "latency_ms": h.latency_ms,
                        "last_error": h.last_error,
                        "adapter_status": h.status,
                    }
            except Exception as e:
                logger.debug(f"Silent error: {e}")

            for name in venue_names:
                extra = adapter_health.get(name, {})
                venues.append({
                    "id": name,
                    "name": _VENUE_NAME.get(name, name.title()),
                    "type": _VENUE_TYPE.get(name, "exchange"),
                    "enabled": vr.is_enabled(name),
                    "status": extra.get("adapter_status", "active" if vr.is_enabled(name) else "disabled"),
                    "supports_trading": True,
                    "latency_ms": extra.get("latency_ms"),
                    "last_error": extra.get("last_error"),
                })
            return {"venues": venues, "source": "venue_registry"}
    except Exception as exc:
        logger.debug("high-level venue registry unavailable: %s", exc)

    # Layer 2: low-level adapter registry only
    try:
        from trading.adapters.registry import list_adapters
        adapters = list_adapters()
        if adapters:
            venues = []
            for vid, adapter in adapters.items():
                health = adapter.get_health()
                venues.append({
                    "id": vid,
                    "name": _VENUE_NAME.get(vid, vid.title()),
                    "type": _VENUE_TYPE.get(vid, "exchange"),
                    "enabled": True,
                    "status": health.status,
                    "supports_trading": adapter.supports_trading,
                    "latency_ms": health.latency_ms,
                    "last_error": health.last_error,
                })
            return {"venues": venues, "source": "adapter_registry"}
    except Exception as exc:
        logger.debug("adapter registry unavailable: %s", exc)

    # Layer 3: static fallback
    return {
        "venues": [
            {
                "id": "kalshi",
                "name": "Kalshi",
                "type": "prediction_market",
                "enabled": True,
                "status": "active",
                "supports_trading": True,
                "latency_ms": None,
                "last_error": None,
            }
        ],
        "source": "static_fallback",
    }
