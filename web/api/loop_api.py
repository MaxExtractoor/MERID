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

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Query
from pydantic import BaseModel
from utils.logger import get_logger


async def _with_timeout(fn, timeout: float = 5.0, fallback=None):
    """Run a sync function in a thread with a timeout guard."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except asyncio.TimeoutError:
        return fallback
    except Exception:
        return fallback

logger = get_logger("web.api.loop_api")

loop_api_router = APIRouter(prefix="/loop", tags=["loop"])


# ── Lazy imports ──────────────────────────────────────────────────────

def _loop():
    try:
        # Try 15m loop first
        from merid.loop_15m import get_merid_loop_15m
        return get_merid_loop_15m()
    except ImportError:
        # LEGACY REMOVAL: Fallback to legacy loop removed for 15m stack separation
        # from merid.loop import get_merid_loop
        # return get_merid_loop()
        raise RuntimeError("15m loop not available and legacy loop fallback disabled for stack separation")

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
async def get_loop_status() -> Dict[str, Any]:
    """Get MeridLoop running state, config, and metrics."""
    def _fetch():
        loop = _loop()
        return loop.status()
    result = await _with_timeout(_fetch, timeout=5.0, fallback={"running": False, "error": "Loop status timed out (5s)"})
    return result


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
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))
        return result
    except Exception as e:
        logger.warning(f"tick_log_summary_error: {e}")
        return {"ticks": 0, "error": str(e)}


@loop_api_router.get("/execution/status")
def get_execution_status() -> Dict[str, Any]:
    """Execution loop status — running state, last tick, error count."""
    try:
        loop = _loop()
        s = loop.status()
        guard = _guard()
        gs = guard.summary()
        return {
            "running": s.get("running", False),
            "last_tick": s.get("last_tick"),
            "tick_count": s.get("tick_count", 0),
            "error_count": s.get("error_count", 0),
            "kill_switch_active": gs.get("kill_switch_active", False),
            "paused": s.get("paused", False),
        }
    except Exception as e:
        logger.warning(f"execution_status_error: {e}")
        return {"running": False, "error": str(e)}


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
        verdicts = guard.recent_verdicts(limit)
        if verdicts:
            return {"verdicts": verdicts, "count": len(verdicts)}
    except Exception as e:
        logger.debug(f"guard_verdicts guard unavailable: {e}")

    # Fallback: derive verdicts from consensus blocks
    # LEGACY REMOVAL: Consensus module deleted - consensus fallback disabled
    verdicts = []
    try:
        # from merid.prediction.consensus import get_prediction_consensus_store
        # _cs = get_prediction_consensus_store()
        # for op in _cs.list_opinions(limit=limit):
        #     prob = getattr(op, "probability", 0.5)
        #     conf = getattr(op, "confidence", 0.5)
        #     sym = getattr(op, "symbol", "")
        #     verdicts.append({
        #         "ts": str(getattr(op, "timestamp", "")),
        #         "ticker": sym,
        #         "action": "approve" if prob > 0.6 else ("reject" if prob < 0.4 else "hold"),
        #         "allowed": prob > 0.4,
        #         "reason": f"Opinion by {getattr(op, 'agent_id', '?')}: prob={prob:.0%}, conf={conf:.0%} on {sym}",
        #         "source": "consensus_opinion",
        #     })
        logger.debug("guard_verdicts consensus fallback disabled - consensus module deleted")
    except Exception as exc2:
        logger.debug(f"guard_verdicts consensus fallback disabled - consensus module deleted: {exc2}")

    # Also include agent cycle scan verdicts
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        import datetime as _dt
        grid = get_agent_grid()
        _now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        for agent in grid.agents:
            if agent.state.cycles_run > 0:
                verdicts.append({
                    "ts": _now,
                    "ticker": f"{agent.config.assets[0]}/*" if agent.config.assets else "",
                    "action": "scan",
                    "allowed": True,
                    "reason": f"{agent.config.name}: {agent.state.cycles_run} cycles, {agent.state.orders_placed} orders",
                    "source": "agent_grid",
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    verdicts.sort(key=lambda v: v.get("ts", ""), reverse=True)
    return {"verdicts": verdicts[:limit], "count": len(verdicts[:limit])}


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

@loop_api_router.get("/execution/toggle")
async def get_execution_toggle() -> Dict[str, Any]:
    """Get current execution toggle state (enabled/disabled)."""
    try:
        g = _guard()
        killed = getattr(g, "_global_kill_switch", False)
        return {
            "enabled": not killed,
            "can_trade": not killed,
            "kill_switch_active": killed,
            "kill_reason": getattr(g, "_global_kill_reason", ""),
        }
    except Exception as e:
        logger.debug(f"execution_toggle_error: {e}")
        return {"enabled": False, "can_trade": False, "error": str(e)}


@loop_api_router.get("/live-readiness")
async def get_live_readiness() -> Dict[str, Any]:
    """Check if the system is ready for live trading."""
    checks = {}
    ready = True

    # Check loop running (may block on singleton init)
    def _check_loop():
        loop = _loop()
        return loop.running if hasattr(loop, "running") else True
    loop_running = await _with_timeout(_check_loop, timeout=3.0, fallback=None)
    if loop_running is None:
        checks["loop_running"] = False
        ready = False
    else:
        checks["loop_running"] = loop_running

    # Check guard
    try:
        g = _guard()
        killed = getattr(g, "_global_kill_switch", False)
        checks["guard_active"] = not killed
        if killed:
            ready = False
    except Exception:
        checks["guard_active"] = False
        ready = False

    # Check WS feed
    try:
        ws = _ws_feed()
        ws_st = ws.status() if hasattr(ws, "status") else {}
        checks["ws_feed_connected"] = ws_st.get("active", False)
    except Exception:
        checks["ws_feed_connected"] = False

    # Check trade mode
    try:
        from trading.trade_mode import get_trade_mode
        mode = get_trade_mode()
        checks["trade_mode"] = mode.value
        checks["is_live"] = mode.value == "live"
    except Exception:
        checks["trade_mode"] = "unknown"
        checks["is_live"] = False

    return {"ready": ready, "checks": checks}


@loop_api_router.get("/live-feeds/status")
def get_live_feeds_status() -> Dict[str, Any]:
    """Get live feed manager status (Finnhub, FRED, CoinGecko, Polygon)."""
    try:
        mgr = _live_feeds()
        return mgr.status()
    except Exception as e:
        logger.warning(f"live_feeds_status_error: {e}")
        return {"error": str(e)}
