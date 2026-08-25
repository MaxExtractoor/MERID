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
from pydantic import BaseModel, Field, field_validator

from fastapi import APIRouter, Query, Request, HTTPException
from utils.logger import get_logger


async def _with_timeout(fn, timeout: float = 5.0, fallback=None):
    """Run a sync function in a thread with a timeout guard.

    ERROR HANDLING IMPROVEMENT: Specific exception handling instead of broad Exception.
    - asyncio.TimeoutError: Function took too long to execute
    - RuntimeError: Thread execution errors
    - AttributeError: Function not callable or missing attributes
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except asyncio.TimeoutError:
        logger.debug(f"_with_timeout: Function timed out after {timeout}s")
        return fallback
    except RuntimeError as e:
        logger.warning(f"_with_timeout: Runtime error in thread execution: {e}")
        return fallback
    except (AttributeError, TypeError) as e:
        logger.warning(f"_with_timeout: Invalid function or parameters: {e}")
        return fallback

logger = get_logger("web.api.loop_api")

loop_api_router = APIRouter(prefix="/loop", tags=["loop"])


# ERROR STANDARDIZATION: Helper function for consistent error responses
def _standard_error_response(
    error_type: str,
    message: str,
    status_code: int = 500,
    details: str = None
) -> Dict[str, Any]:
    """Generate a standardized error response.

    This helper ensures consistent error response format across all endpoints.
    Used for backward compatibility with endpoints that return error dicts instead of HTTPException.

    Args:
        error_type: Category of error (e.g., "import_error", "runtime_error")
        message: Human-readable error message
        status_code: HTTP status code (for logging purposes)
        details: Additional error details (optional)

    Returns:
        Standardized error dictionary
    """
    response = {
        "error": message,
        "error_type": error_type,
        "status_code": status_code
    }
    if details:
        response["details"] = details
    return response


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
    """Get recent tick records from the in-memory buffer.

    ERROR HANDLING IMPROVEMENT: Specific exception handling with HTTPException.
    - ImportError: Tick log module not available (503 Service Unavailable)
    - AttributeError: Tick log instance missing required methods (500 Internal Server Error)
    - RuntimeError: Tick log internal error (500 Internal Server Error)
    """
    try:
        log = _tick_log()
        return {"ticks": log.recent(limit), "count": len(log.recent(limit))}
    except ImportError as e:
        logger.warning(f"tick_log_import_error: {e}")
        raise HTTPException(status_code=503, detail="Tick log module not available")
    except AttributeError as e:
        logger.warning(f"tick_log_attribute_error: {e}")
        raise HTTPException(status_code=500, detail="Tick log missing required methods")
    except RuntimeError as e:
        logger.warning(f"tick_log_runtime_error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@loop_api_router.get("/tick-log/summary")
def get_tick_log_summary() -> Dict[str, Any]:
    """Get aggregate tick stats (error rate, avg duration, plan counts).

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Tick log or session module not available
    - AttributeError: Missing required methods
    - RuntimeError: Internal error in tick log or session
    """
    try:
        log = _tick_log()
        result = log.summary()
        # Include operator session data
        try:
            result["session"] = _session().summary()
        except ImportError as exc:
            logger.debug("operation_session_import_suppressed", error=str(exc))
        except AttributeError as exc:
            logger.debug("operation_session_attribute_suppressed", error=str(exc))
        except RuntimeError as exc:
            logger.debug("operation_session_runtime_suppressed", error=str(exc))
        return result
    except ImportError as e:
        logger.warning(f"tick_log_summary_import_error: {e}")
        return {"ticks": 0, "error": "Tick log module not available"}
    except AttributeError as e:
        logger.warning(f"tick_log_summary_attribute_error: {e}")
        return {"ticks": 0, "error": "Tick log missing required methods"}
    except RuntimeError as e:
        logger.warning(f"tick_log_summary_runtime_error: {e}")
        return {"ticks": 0, "error": str(e)}


@loop_api_router.get("/execution/status")
def get_execution_status() -> Dict[str, Any]:
    """Execution loop status — running state, last tick, error count.

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Loop or guard module not available
    - RuntimeError: Internal error in loop or guard
    - AttributeError: Missing required methods
    """
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
    except ImportError as e:
        logger.warning(f"execution_status_import_error: {e}")
        return {"running": False, "error": "Loop or guard module not available"}
    except RuntimeError as e:
        logger.warning(f"execution_status_runtime_error: {e}")
        return {"running": False, "error": str(e)}
    except AttributeError as e:
        logger.warning(f"execution_status_attribute_error: {e}")
        return {"running": False, "error": "Loop or guard missing required methods"}


@loop_api_router.get("/session")
def get_operator_session_data() -> Dict[str, Any]:
    """Get operator session summary: domain execs, blocks, CQI history.

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Session module not available
    - AttributeError: Session missing required methods
    - RuntimeError: Session internal error
    """
    try:
        return _session().summary()
    except ImportError as e:
        logger.warning(f"session_import_error: {e}")
        return {"error": "Session module not available"}
    except AttributeError as e:
        logger.warning(f"session_attribute_error: {e}")
        return {"error": "Session missing required methods"}
    except RuntimeError as e:
        logger.warning(f"session_runtime_error: {e}")
        return {"error": str(e)}


@loop_api_router.get("/session/cqi-series")
def get_cqi_series(
    domain: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Get CQI time series, optionally filtered by domain.

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Session module not available
    - AttributeError: Session missing cqi_series method
    - RuntimeError: Session internal error
    """
    try:
        series = _session().cqi_series(domain=domain, limit=limit)
        return {"domain": domain, "points": series, "count": len(series)}
    except ImportError as e:
        logger.warning(f"cqi_series_import_error: {e}")
        return {"points": [], "count": 0, "error": "Session module not available"}
    except AttributeError as e:
        logger.warning(f"cqi_series_attribute_error: {e}")
        return {"points": [], "count": 0, "error": "Session missing cqi_series method"}
    except RuntimeError as e:
        logger.warning(f"cqi_series_runtime_error: {e}")
        return {"points": [], "count": 0, "error": str(e)}


# ── Execution guard ──────────────────────────────────────────────────

@loop_api_router.get("/guard/status")
def get_guard_status() -> Dict[str, Any]:
    """Get execution guard state: kill switch, CQI scores, domain caps.

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Guard module not available
    - AttributeError: Guard missing required methods
    - RuntimeError: Guard internal error
    """
    try:
        guard = _guard()
        return guard.summary()
    except ImportError as e:
        logger.warning(f"guard_status_import_error: {e}")
        return {"error": "Guard module not available"}
    except AttributeError as e:
        logger.warning(f"guard_status_attribute_error: {e}")
        return {"error": "Guard missing required methods"}
    except RuntimeError as e:
        logger.warning(f"guard_status_runtime_error: {e}")
        return {"error": str(e)}


@loop_api_router.get("/guard/verdicts")
def get_guard_verdicts(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get recent trade verdicts (allowed/blocked decisions).

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Guard or agent grid module not available
    - AttributeError: Missing required methods
    - RuntimeError: Internal error in guard or agent grid
    """
    try:
        guard = _guard()
        verdicts = guard.recent_verdicts(limit)
        if verdicts:
            return {"verdicts": verdicts, "count": len(verdicts)}
    except ImportError as e:
        logger.debug(f"guard_verdicts_import_error: {e}")
    except AttributeError as e:
        logger.debug(f"guard_verdicts_attribute_error: {e}")
    except RuntimeError as e:
        logger.debug(f"guard_verdicts_runtime_error: {e}")

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
    except ImportError as exc2:
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
    except ImportError as e:
        logger.debug(f"guard_verdicts_agent_grid_import_error: {e}")
    except AttributeError as e:
        logger.debug(f"guard_verdicts_agent_grid_attribute_error: {e}")
    except RuntimeError as e:
        logger.debug(f"guard_verdicts_agent_grid_runtime_error: {e}")

    verdicts.sort(key=lambda v: v.get("ts", ""), reverse=True)
    return {"verdicts": verdicts[:limit], "count": len(verdicts[:limit])}


class KillSwitchRequest(BaseModel):
    """Request to activate the global kill switch.

    INPUT VALIDATION: Reason field is validated to prevent empty or overly long reasons.
    """
    reason: str = Field(
        default="operator",
        min_length=1,
        max_length=500,
        description="Reason for activating kill switch"
    )

    @field_validator('reason')
    def reason_must_not_be_whitespace(cls, v):
        if v.strip() == "":
            raise ValueError("Reason cannot be empty or whitespace")
        return v.strip()


@loop_api_router.post("/guard/kill")
def activate_kill_switch(req: KillSwitchRequest) -> Dict[str, Any]:
    """Activate the global kill switch — blocks ALL trade execution.

    ERROR HANDLING IMPROVEMENT: Specific exception handling with HTTPException.
    - ImportError: Guard module not available (503 Service Unavailable)
    - RuntimeError: Guard internal error (500 Internal Server Error)
    - ValueError: Invalid kill switch state (400 Bad Request)
    """
    try:
        guard = _guard()
        guard.activate_kill_switch(req.reason)
        return {"success": True, "kill_switch_active": True, "reason": req.reason}
    except ImportError as e:
        logger.error(f"kill_switch_activate_import_error: {e}")
        raise HTTPException(status_code=503, detail="Guard module not available")
    except RuntimeError as e:
        logger.error(f"kill_switch_activate_runtime_error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        logger.error(f"kill_switch_activate_value_error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@loop_api_router.post("/guard/unkill")
def deactivate_kill_switch() -> Dict[str, Any]:
    """Deactivate the global kill switch — re-enables execution.

    ERROR HANDLING IMPROVEMENT: Specific exception handling with HTTPException.
    - ImportError: Guard module not available (503 Service Unavailable)
    - RuntimeError: Guard internal error (500 Internal Server Error)
    - ValueError: Invalid kill switch state (400 Bad Request)
    """
    try:
        guard = _guard()
        guard.deactivate_kill_switch()
        return {"success": True, "kill_switch_active": False}
    except ImportError as e:
        logger.error(f"kill_switch_deactivate_import_error: {e}")
        raise HTTPException(status_code=503, detail="Guard module not available")
    except RuntimeError as e:
        logger.error(f"kill_switch_deactivate_runtime_error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        logger.error(f"kill_switch_deactivate_value_error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


class DomainKillRequest(BaseModel):
    """Request to activate kill switch for a single domain.

    INPUT VALIDATION: Domain and reason fields are validated.
    """
    domain: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Domain to kill (e.g., 'kalshi_crypto_15m')"
    )
    reason: str = Field(
        default="operator",
        min_length=1,
        max_length=500,
        description="Reason for activating domain kill switch"
    )

    @field_validator('domain')
    def domain_must_not_be_whitespace(cls, v):
        if v.strip() == "":
            raise ValueError("Domain cannot be empty or whitespace")
        return v.strip()

    @field_validator('reason')
    def reason_must_not_be_whitespace(cls, v):
        if v.strip() == "":
            raise ValueError("Reason cannot be empty or whitespace")
        return v.strip()


@loop_api_router.post("/guard/domain-kill")
def activate_domain_kill(req: DomainKillRequest) -> Dict[str, Any]:
    """Activate kill switch for a single domain.

    ERROR HANDLING IMPROVEMENT: Specific exception handling with HTTPException.
    - ImportError: Guard module not available (503 Service Unavailable)
    - RuntimeError: Guard internal error (500 Internal Server Error)
    - ValueError: Invalid domain or kill switch state (400 Bad Request)
    """
    try:
        guard = _guard()
        guard.activate_domain_kill_switch(req.domain, req.reason)
        return {"success": True, "domain": req.domain, "kill_switch_active": True}
    except ImportError as e:
        logger.error(f"domain_kill_activate_import_error: {e}")
        raise HTTPException(status_code=503, detail="Guard module not available")
    except RuntimeError as e:
        logger.error(f"domain_kill_activate_runtime_error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        logger.error(f"domain_kill_activate_value_error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


class DomainUnkillRequest(BaseModel):
    """Request to deactivate kill switch for a single domain.

    INPUT VALIDATION: Domain field is validated.
    """
    domain: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Domain to unkill (e.g., 'kalshi_crypto_15m')"
    )

    @field_validator('domain')
    def domain_must_not_be_whitespace(cls, v):
        if v.strip() == "":
            raise ValueError("Domain cannot be empty or whitespace")
        return v.strip()


@loop_api_router.post("/guard/domain-unkill")
def deactivate_domain_kill(req: DomainUnkillRequest) -> Dict[str, Any]:
    """Deactivate kill switch for a single domain.

    ERROR HANDLING IMPROVEMENT: Specific exception handling with HTTPException.
    - ImportError: Guard module not available (503 Service Unavailable)
    - RuntimeError: Guard internal error (500 Internal Server Error)
    - ValueError: Invalid domain or kill switch state (400 Bad Request)
    """
    try:
        guard = _guard()
        guard.deactivate_domain_kill_switch(req.domain)
        return {"success": True, "domain": req.domain, "kill_switch_active": False}
    except ImportError as e:
        logger.error(f"domain_kill_deactivate_import_error: {e}")
        raise HTTPException(status_code=503, detail="Guard module not available")
    except RuntimeError as e:
        logger.error(f"domain_kill_deactivate_runtime_error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        logger.error(f"domain_kill_deactivate_value_error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ── WS price feed ────────────────────────────────────────────────────

@loop_api_router.get("/ws-feed/status")
def get_ws_feed_status() -> Dict[str, Any]:
    """Get WebSocket price feed connection status and latest prices.

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: WS feed module not available
    - AttributeError: WS feed missing status method
    - RuntimeError: WS feed internal error
    """
    try:
        mgr = _ws_feed()
        return mgr.status()
    except ImportError as e:
        logger.warning(f"ws_feed_status_import_error: {e}")
        return {"active": False, "error": "WS feed module not available"}
    except AttributeError as e:
        logger.warning(f"ws_feed_status_attribute_error: {e}")
        return {"active": False, "error": "WS feed missing status method"}
    except RuntimeError as e:
        logger.warning(f"ws_feed_status_runtime_error: {e}")
        return {"active": False, "error": str(e)}


# ── Live feeds ────────────────────────────────────────────────────────

@loop_api_router.get("/execution/toggle")
async def get_execution_toggle() -> Dict[str, Any]:
    """Get current execution toggle state (enabled/disabled).

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Guard module not available
    - AttributeError: Guard missing required attributes
    - RuntimeError: Guard internal error
    """
    try:
        g = _guard()
        killed = getattr(g, "_global_kill_switch", False)
        return {
            "enabled": not killed,
            "can_trade": not killed,
            "kill_switch_active": killed,
            "kill_reason": getattr(g, "_global_kill_reason", ""),
        }
    except ImportError as e:
        logger.debug(f"execution_toggle_import_error: {e}")
        return {"enabled": False, "can_trade": False, "error": "Guard module not available"}
    except AttributeError as e:
        logger.debug(f"execution_toggle_attribute_error: {e}")
        return {"enabled": False, "can_trade": False, "error": "Guard missing required attributes"}
    except RuntimeError as e:
        logger.debug(f"execution_toggle_runtime_error: {e}")
        return {"enabled": False, "can_trade": False, "error": str(e)}


@loop_api_router.get("/live-readiness")
async def get_live_readiness(request: Request) -> Dict[str, Any]:
    """Check if the system is ready for live trading."""
    checks = {}
    ready = True

    # Check loop running (prefer the actual Kalshi15mLoop from app.state;
    # fall back to the legacy singleton accessor)
    def _check_loop():
        loop = getattr(request.app.state, "kalshi_15m_loop", None)
        if loop is not None:
            return bool(getattr(loop, "is_running", getattr(loop, "running", False)))
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
    except ImportError:
        checks["guard_active"] = False
        ready = False
    except AttributeError:
        checks["guard_active"] = False
        ready = False
    except RuntimeError:
        checks["guard_active"] = False
        ready = False

    # Check WS feed
    try:
        ws = _ws_feed()
        ws_st = ws.status() if hasattr(ws, "status") else {}
        checks["ws_feed_connected"] = ws_st.get("active", False)
    except ImportError:
        checks["ws_feed_connected"] = False
    except AttributeError:
        checks["ws_feed_connected"] = False
    except RuntimeError:
        checks["ws_feed_connected"] = False

    # Check trade mode
    try:
        from trading.trade_mode import get_trade_mode
        mode = get_trade_mode()
        checks["trade_mode"] = mode.value
        checks["is_live"] = mode.value == "live"
    except ImportError:
        checks["trade_mode"] = "unknown"
        checks["is_live"] = False
    except AttributeError:
        checks["trade_mode"] = "unknown"
        checks["is_live"] = False
    except RuntimeError:
        checks["trade_mode"] = "unknown"
        checks["is_live"] = False

    return {"ready": ready, "checks": checks}


@loop_api_router.get("/live-feeds/status")
def get_live_feeds_status() -> Dict[str, Any]:
    """Get live feed manager status (Finnhub, FRED, CoinGecko, Polygon).

    ERROR HANDLING IMPROVEMENT: Specific exception handling.
    - ImportError: Live feeds module not available
    - AttributeError: Live feeds missing status method
    - RuntimeError: Live feeds internal error
    """
    try:
        mgr = _live_feeds()
        return mgr.status()
    except ImportError as e:
        logger.warning(f"live_feeds_status_import_error: {e}")
        return {"error": "Live feeds module not available"}
    except AttributeError as e:
        logger.warning(f"live_feeds_status_attribute_error: {e}")
        return {"error": "Live feeds missing status method"}
    except RuntimeError as e:
        logger.warning(f"live_feeds_status_runtime_error: {e}")
        return {"error": str(e)}
