"""Loop & Execution Guard API — surfaces MeridLoop, ExecutionGuard, TickLog, WSFeed.

Endpoints:
  GET  /api/v1/loop/status              — Loop running state + metrics
  GET  /api/v1/loop/tick-log            — Recent tick records
  GET  /api/v1/loop/tick-log/summary    — Aggregate tick stats
  GET  /api/v1/loop/guard/status        — Execution guard state (kill switch, CQI, caps)
  GET  /api/v1/loop/guard/verdicts      — Recent trade verdicts
  POST /api/v1/loop/guard/kill          — Activate global kill switch
  POST /api/v1/loop/guard/unkill        — Deactivate global kill switch
  POST /api/v1/loop/guard/domain-kill   — Activate per-domain kill switch
  POST /api/v1/loop/guard/domain-unkill — Deactivate per-domain kill switch
  GET  /api/v1/loop/ws-feed/status      — WebSocket price feed status
  GET  /api/v1/loop/live-feeds/status   — Live feed manager status
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query
from pydantic import BaseModel
from utils.logger import get_logger

logger = get_logger("web.api.loop_api")

loop_api_router = APIRouter(prefix="/api/v1/loop", tags=["loop"])


# ── Lazy imports ──────────────────────────────────────────────────────

def _loop():
    from merid.loop import get_merid_loop
    return get_merid_loop()

def _guard():
    from merid.execution_guard import get_execution_guard
    return get_execution_guard()

def _tick_log():
    from merid.tick_log import get_tick_log
    return get_tick_log()

def _session():
    from merid.tick_log import get_operator_session
    return get_operator_session()

def _ws_feed():
    from merid.signals.ws_price_feed import get_ws_feed_manager
    return get_ws_feed_manager()

def _live_feeds():
    from merid.signals.live_feeds import get_live_feed_manager
    return get_live_feed_manager()


# ── Loop status ───────────────────────────────────────────────────────

@loop_api_router.get("/status")
def get_loop_status() -> Dict[str, Any]:
    """Get MeridLoop running state, config, and metrics."""
    try:
        loop = _loop()
        return loop.status()
    except Exception as e:
        logger.warning(f"loop_status_error: {e}")
        return {"running": False, "error": str(e)}


# ── Tick log ──────────────────────────────────────────────────────────

@loop_api_router.get("/tick-log")
def get_tick_log_recent(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get recent tick records from the in-memory buffer."""
    try:
        log = _tick_log()
        return {"ticks": log.recent(limit), "count": len(log.recent(limit))}
    except Exception as e:
        logger.warning(f"tick_log_error: {e}")
        return {"ticks": [], "count": 0, "error": str(e)}


@loop_api_router.get("/tick-log/summary")
def get_tick_log_summary() -> Dict[str, Any]:
    """Get aggregate tick stats (error rate, avg duration, plan counts)."""
    try:
        log = _tick_log()
        result = log.summary()
        # Include operator session data
        try:
            result["session"] = _session().summary()
        except Exception:
            pass
        return result
    except Exception as e:
        logger.warning(f"tick_log_summary_error: {e}")
        return {"ticks": 0, "error": str(e)}


@loop_api_router.get("/session")
def get_operator_session_data() -> Dict[str, Any]:
    """Get operator session summary: domain execs, blocks, CQI history."""
    try:
        return _session().summary()
    except Exception as e:
        logger.warning(f"session_error: {e}")
        return {"error": str(e)}


@loop_api_router.get("/session/cqi-series")
def get_cqi_series(
    domain: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Get CQI time series, optionally filtered by domain."""
    try:
        series = _session().cqi_series(domain=domain, limit=limit)
        return {"domain": domain, "points": series, "count": len(series)}
    except Exception as e:
        logger.warning(f"cqi_series_error: {e}")
        return {"points": [], "count": 0, "error": str(e)}


# ── Execution guard ──────────────────────────────────────────────────

@loop_api_router.get("/guard/status")
def get_guard_status() -> Dict[str, Any]:
    """Get execution guard state: kill switch, CQI scores, domain caps."""
    try:
        guard = _guard()
        return guard.summary()
    except Exception as e:
        logger.warning(f"guard_status_error: {e}")
        return {"error": str(e)}


@loop_api_router.get("/guard/verdicts")
def get_guard_verdicts(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get recent trade verdicts (allowed/blocked decisions)."""
    try:
        guard = _guard()
        return {"verdicts": guard.recent_verdicts(limit), "count": len(guard.recent_verdicts(limit))}
    except Exception as e:
        logger.warning(f"guard_verdicts_error: {e}")
        return {"verdicts": [], "count": 0, "error": str(e)}


class KillSwitchRequest(BaseModel):
    reason: str = "operator"


@loop_api_router.post("/guard/kill")
def activate_kill_switch(req: KillSwitchRequest) -> Dict[str, Any]:
    """Activate the global kill switch — blocks ALL trade execution."""
    try:
        guard = _guard()
        guard.activate_kill_switch(req.reason)
        return {"success": True, "kill_switch_active": True, "reason": req.reason}
    except Exception as e:
        logger.error(f"kill_switch_activate_error: {e}")
        return {"success": False, "error": str(e)}


@loop_api_router.post("/guard/unkill")
def deactivate_kill_switch() -> Dict[str, Any]:
    """Deactivate the global kill switch — re-enables execution."""
    try:
        guard = _guard()
        guard.deactivate_kill_switch()
        return {"success": True, "kill_switch_active": False}
    except Exception as e:
        logger.error(f"kill_switch_deactivate_error: {e}")
        return {"success": False, "error": str(e)}


class DomainKillRequest(BaseModel):
    domain: str
    reason: str = "operator"


@loop_api_router.post("/guard/domain-kill")
def activate_domain_kill(req: DomainKillRequest) -> Dict[str, Any]:
    """Activate kill switch for a single domain."""
    try:
        guard = _guard()
        guard.activate_domain_kill_switch(req.domain, req.reason)
        return {"success": True, "domain": req.domain, "kill_switch_active": True}
    except Exception as e:
        logger.error(f"domain_kill_activate_error: {e}")
        return {"success": False, "error": str(e)}


class DomainUnkillRequest(BaseModel):
    domain: str


@loop_api_router.post("/guard/domain-unkill")
def deactivate_domain_kill(req: DomainUnkillRequest) -> Dict[str, Any]:
    """Deactivate kill switch for a single domain."""
    try:
        guard = _guard()
        guard.deactivate_domain_kill_switch(req.domain)
        return {"success": True, "domain": req.domain, "kill_switch_active": False}
    except Exception as e:
        logger.error(f"domain_kill_deactivate_error: {e}")
        return {"success": False, "error": str(e)}


# ── WS price feed ────────────────────────────────────────────────────

@loop_api_router.get("/ws-feed/status")
def get_ws_feed_status() -> Dict[str, Any]:
    """Get WebSocket price feed connection status and latest prices."""
    try:
        mgr = _ws_feed()
        return mgr.status()
    except Exception as e:
        logger.warning(f"ws_feed_status_error: {e}")
        return {"active": False, "error": str(e)}


# ── Live feeds ────────────────────────────────────────────────────────

@loop_api_router.get("/live-feeds/status")
def get_live_feeds_status() -> Dict[str, Any]:
    """Get live feed manager status (Finnhub, FRED, CoinGecko, Polygon)."""
    try:
        mgr = _live_feeds()
        return mgr.status()
    except Exception as e:
        logger.warning(f"live_feeds_status_error: {e}")
        return {"error": str(e)}
