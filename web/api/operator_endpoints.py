"""Operator dashboard endpoints for kill switch, risk state, and agent activity."""

from web.api.auth import get_current_session
from utils.logger import get_logger
import hashlib
import os
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = get_logger(__name__)

# Track process start time for uptime calculation
_PROCESS_START = time.time()

# Deferred security assertion: warn loudly if operator token is unset in production.
# Runs once on first request (not at import time) to avoid dotenv loading-order races.
_operator_token_checked = False

def _check_operator_token_once():
    global _operator_token_checked
    if _operator_token_checked:
        return
    _operator_token_checked = True
    _env = os.getenv("MERID_ENV", "development").lower()
    _token = os.getenv("MERID_OPERATOR_TOKEN", "")
    if not _token and _env not in ("development", "dev", "paper", "test"):
        logger.error(
            "SECURITY: MERID_OPERATOR_TOKEN is not set and MERID_ENV=%s. "
            "Operator endpoints (kill switch, emergency stop, trading mode) are UNPROTECTED. "
            "Set MERID_OPERATOR_TOKEN in your environment immediately.",
            _env,
        )
    elif _token and _token.endswith("_change_me_in_production") and _env not in ("development", "dev", "test"):
        logger.warning(
            "SECURITY: MERID_OPERATOR_TOKEN is still set to default placeholder and MERID_ENV=%s. "
            "Change it to a secure random value before production use.",
            _env,
        )


def _check_kalshi_15m_profile_guard(operation: str) -> None:
    """Guard to prevent operator actions that touch legacy systems in kalshi_crypto_15m_v2 profile.
    
    In kalshi_crypto_15m_v2 mode, certain operator actions that would start/stop legacy systems
    (swarm, sentiment, governance, non-Kalshi venues) are blocked to maintain isolation.
    
    Args:
        operation: Description of the operation being attempted
    
    Raises:
        HTTPException: If operation touches legacy systems in kalshi_crypto_15m_v2 mode
    """
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile != "kalshi_crypto_15m_v2":
        return  # Guard only applies to kalshi_crypto_15m_v2 profile
    
    # Check if operation touches legacy systems
    legacy_keywords = ["swarm", "sentiment", "governance", "debate", "augur", "polymarket", "defi", "sports", "macro"]
    operation_lower = operation.lower()
    
    for keyword in legacy_keywords:
        if keyword in operation_lower:
            logger.warning(
                f"[OPERATOR-GUARD] Blocked operation '{operation}' in kalshi_crypto_15m_v2 profile: "
                f"touches legacy system '{keyword}'"
            )
            raise HTTPException(
                status_code=403,
                detail=f"Operation '{operation}' is not available in kalshi_crypto_15m_v2 profile: "
                       f"touches legacy system '{keyword}'. The sealed 15m stack does not include {keyword} infrastructure."
            )


def _get_last_cqi() -> Dict[str, float]:
    """Return per-agent cycle count as a proxy CQI until confidence tracking is added."""
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        grid = get_agent_grid()
        return {
            a.config.name: float(getattr(a.state, "cycles_run", 0))
            for a in grid.agents
        }
    except Exception as _e:
        logger.debug("_get_agent_cycles skipped: %s", _e)
        return {}


def _get_domain_caps() -> Dict[str, Any]:
    """Return per-domain position cap utilization from KalshiRiskManager."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        krm = get_kalshi_risk()
        ks = krm.state
        cat_limits = krm.config.category_limits  # KalshiRiskConfig.category_limits
        caps: Dict[str, Any] = {}
        for cat, notional in ks.category_notional.items():
            cat_cfg = cat_limits.get(cat)
            limit = float(cat_cfg.max_notional_usd) if cat_cfg else 0.0
            caps[cat] = {
                "remaining_usd": max(0.0, limit - float(notional)),
                "kill": float(notional) >= limit if limit else False,
            }
        return caps
    except Exception as _e:
        logger.debug("_get_venue_caps skipped: %s", _e)
        return {}


def _get_recent_verdicts_count() -> int:
    """Return count of recent execution verdicts from the Kalshi order router."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        risk = get_kalshi_risk()
        state = risk.state
        return state.orders_this_hour + state.orders_this_minute
    except Exception as _e:
        logger.debug("_get_recent_verdicts_count kalshi_risk skipped: %s", _e)
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        sys = tracker.get_system_summary()
        return sys.get("total_fills", 0)
    except Exception as _e:
        logger.debug("_get_order_count tracker fallback skipped: %s", _e)
        return 0

_SAFE_ENVS = {"development", "dev", "test"}  # envs where unset token is tolerated


def _write_operator_audit(
    *,
    request: Request,
    action: str,
    reason: str,
    previous_state: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a structured operator-action entry to the audit trail.

    Extracts a redacted token fingerprint (first 16 hex chars of SHA-256) from
    the Authorization header so the entry is attributable without storing the
    raw credential.  Never raises — audit failures are logged but must not
    block the operator action itself.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        raw_token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else ""
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()[:16] if raw_token else "unauthenticated"
        actor_ip = request.client.host if request.client else ""
        from trading.audit_trail import record_operator_action
        record_operator_action(
            action=action,
            reason=reason,
            actor_token_hash=token_hash,
            actor_ip=actor_ip,
            previous_state=previous_state,
        )
    except Exception as _ae:
        logger.warning("Failed to write operator audit entry for %s: %s", action, _ae)


def _require_operator_auth(request: Request) -> None:
    """Verify operator Bearer token for destructive actions.

    Token is read from ``MERID_OPERATOR_TOKEN`` env-var.
    - In development/test: an unset token logs a warning and allows through.
    - In all other envs (paper, staging, production): an unset token returns
      HTTP 503 so misconfigured deployments fail loudly instead of silently
      exposing kill-switch and emergency-stop endpoints.
    - Single-user operator mode (MERID_SINGLE_USER_OPERATOR=1) bypasses token check.
    """
    # Single-user operator mode: bypass token check for local solo operation
    # SECURITY FIX (2026-08-11): single-user bypass is not permitted in live trading.
    if os.getenv("MERID_SINGLE_USER_OPERATOR") == "1":
        live_mode = (
            os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
            or os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live"
            or os.getenv("TRADING_ENABLED", "false").lower() in ("1", "true", "yes")
        )
        if live_mode:
            logger.critical(
                "SECURITY ALERT: operator endpoint single-user bypass blocked in live mode"
            )
            raise HTTPException(
                status_code=403,
                detail="Single-user operator bypass is prohibited in live trading.",
            )
        return
    
    expected = os.getenv("MERID_OPERATOR_TOKEN", "")
    if not expected:
        env = _MERID_ENV  # module-level, set at import time
        if env in _SAFE_ENVS:
            logger.warning(
                "MERID_OPERATOR_TOKEN not set — operator endpoints are UNPROTECTED. "
                "Set this env-var before going to paper/production."
            )
            return  # tolerated in dev/test only
        # Non-dev env with no token: fail loudly rather than silently expose
        logger.error(
            "MERID_OPERATOR_TOKEN not set in env=%s — refusing destructive operator action. "
            "Set MERID_OPERATOR_TOKEN to enable emergency-stop / kill-switch.",
            env,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Operator token not configured. "
                "Set MERID_OPERATOR_TOKEN environment variable before using destructive endpoints."
            ),
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing operator token")
    token = auth_header.split(" ", 1)[1]
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid operator token")


router = APIRouter(prefix="/api/v1/operator", tags=["operator"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Legacy /api/operator/ prefix router (no /v1/) — used by promotion/governance hooks
legacy_router = APIRouter(prefix="/api/operator", tags=["operator-legacy"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class EmergencyStopRequest(BaseModel):
    """Request to trigger emergency stop."""
    reason: str


class KillSwitchResetRequest(BaseModel):
    """Request to reset kill switch."""
    confirm: bool = True


# ── Kill Switch & Risk State Endpoints ────────────────────────────────


@router.get("/kill-switch-status")
async def get_kill_switch_status() -> Dict[str, Any]:
    """Get current kill switch and risk controller state."""
    _check_operator_token_once()
    import asyncio
    def _fetch():
        from merid.risk.kill_switches import risk_controller
        _st = risk_controller.get_status()
        _active = not _st["can_trade"]
        _reason = _st["kill_reason"]
        return {
            "active": _active,
            "reason": _reason,
            "global_kill": _active,
            "state": _st["state"],
            "can_trade": _st["can_trade"],
            "kill_reason": _reason,
            "kill_timestamp": _st["kill_timestamp"],
            "daily_pnl": _st["daily_pnl"],
            "daily_loss_limit": _st["daily_loss_limit"],
            "total_position_value": _st["position_value"],
            "max_position_value": _st["max_position_value"],
            "error_count": _st["error_count"],
            "error_threshold": _st["error_threshold"],
        }
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=5.0)
    except asyncio.TimeoutError:
        # FAIL-CLOSED: When we cannot verify kill switch state, assume active (blocked)
        return {"active": True, "can_trade": False, "error": "Kill switch status timed out (5s) — assuming BLOCKED"}
    except Exception as e:
        logger.error(f"Failed to get kill switch status: {e}")
        # FAIL-CLOSED: When kill switch check fails, assume active (blocked)
        return {"active": True, "can_trade": False, "error": f"Kill switch check failed: {str(e)} — assuming BLOCKED"}


@router.post("/emergency-stop")
async def emergency_stop(request_body: EmergencyStopRequest, request: Request, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Trigger emergency stop - immediately halts all trading."""
    try:
        from merid.risk.kill_switches import risk_controller

        prev_state = risk_controller.get_status()
        risk_controller.emergency_stop(request_body.reason)

        _write_operator_audit(
            request=request,
            action="emergency_stop",
            reason=request_body.reason,
            previous_state=prev_state,
        )

        logger.warning(f"EMERGENCY STOP triggered: {request_body.reason}")

        return {
            "status": "halted",
            "reason": request_body.reason,
            "timestamp": risk_controller.get_status().get("kill_timestamp"),
            "can_trade": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger emergency stop: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger emergency stop: {str(e)}")


@router.post("/reset-kill-switch")
async def reset_kill_switch(request_body: KillSwitchResetRequest, request: Request, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Reset kill switch after resolution."""
    if not request_body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to reset kill switch")

    try:
        from merid.risk.kill_switches import risk_controller

        prev_state = risk_controller.get_status()
        risk_controller.reset()

        _write_operator_audit(
            request=request,
            action="reset_kill_switch",
            reason=request_body.reason if hasattr(request_body, "reason") else "operator reset",
            previous_state=prev_state,
        )

        logger.info("Kill switch reset - trading re-enabled")

        return {
            "status": "active",
            "can_trade": True,
            "message": "Kill switch reset successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset kill switch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset kill switch: {str(e)}")


@router.get("/risk-state")
async def get_risk_state() -> Dict[str, Any]:
    """Get comprehensive risk state including limits and violations."""
    try:
        from merid.risk.kill_switches import risk_controller

        _st = risk_controller.get_status()
        live_notional = _st["position_value"]
        live_daily_pnl = _st["daily_pnl"]

        # Sync live position notional from KalshiRiskManager so utilization is real
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            krm = get_kalshi_risk()
            ks = krm.state
            if ks.total_notional_usd > 0:
                live_notional = float(ks.total_notional_usd)
            if ks.daily_pnl_usd != 0:
                live_daily_pnl = float(ks.daily_pnl_usd)
        except Exception as _e:
            logger.debug("kalshi_risk live state skipped: %s", _e)

        # Determine circuit breaker state from kill switch + error count
        if not _st["can_trade"]:
            cb_state, cb_color = "OPEN", "red"
        elif _st["error_count"] >= _st["error_threshold"] * 0.8:
            cb_state, cb_color = "HALF_OPEN", "yellow"
        else:
            cb_state, cb_color = "CLOSED", "green"

        # Resolve per-symbol cap and order limits from KalshiRiskConfig
        max_per_symbol = 5000.0
        max_open_orders = 30
        current_open_orders = 0
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr
            _krm = _gkr()
            max_per_symbol = float(_krm.config.max_single_order_notional_usd)
            max_open_orders = int(_krm.config.max_orders_per_minute)
            current_open_orders = int(_krm.state.orders_this_minute)
        except Exception as _e:
            logger.debug("kalshi_risk order limits skipped: %s", _e)

        # Get trading mode
        try:
            from trading.config.runtime import get_trading_runtime_config
            cfg = get_trading_runtime_config()
            tstate = cfg.get_state()
            mode = tstate.mode.value
            spectator = tstate.spectator_mode
        except Exception:
            mode = "offline"
            spectator = True

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat() + "Z"

        daily_loss_limit = _st["daily_loss_limit"]
        utilization = abs(live_daily_pnl / max(daily_loss_limit, 1) * 100)

        crypto_pm_feed: Dict[str, Any] = {}
        try:
            from merid.prediction.pm_spot_health import get_operator_pm_spot_block

            crypto_pm_feed = get_operator_pm_spot_block()
        except Exception as _pm_exc:
            logger.debug("crypto_pm_feed block skipped: %s", _pm_exc)

        state = {
            "timestamp": now,
            "circuit_breaker": {
                "state": cb_state,
                "state_color": cb_color,
                "error_count": _st["error_count"],
                "window_seconds": int(os.getenv("MERID_CB_WINDOW_SECONDS", "300")),
                "threshold": _st["error_threshold"],
                "last_error_at": None,
                "opened_at": _st.get("kill_timestamp"),
                "cooldown_seconds": int(os.getenv("MERID_CB_COOLDOWN_SECONDS", "60")),
                "half_open_successes": 0,
            },
            "lockdown": {
                "trading_suite_enabled": _st["can_trade"],
                "global_mode": mode,
                "spectator_mode": spectator,
                "lockdown_reason": risk_controller.get_kill_reason() if not _st["can_trade"] else None,
            },
            "risk_limits": {
                "max_daily_loss_usd": daily_loss_limit,
                "current_daily_pnl": live_daily_pnl,
                "daily_loss_utilization_pct": round(utilization, 1),
                "max_per_symbol_exposure_usd": max_per_symbol,
                "max_open_orders": max_open_orders,
                "current_open_orders": current_open_orders,
            },
            "recent_events": [],
            "kill_switch": {
                "active": not _st["can_trade"],
                "reason": risk_controller.get_kill_reason(),
                "can_trade": _st["can_trade"],
            },
            "pnl": {
                "daily_pnl": live_daily_pnl,
                "daily_loss_limit": daily_loss_limit,
                "limit_remaining": daily_loss_limit + live_daily_pnl,
                "utilization_pct": abs(live_daily_pnl / daily_loss_limit * 100) if daily_loss_limit else 0,
            },
            "position": {
                "total_value": live_notional,
                "max_allowed": _st["max_position_value"],
                "utilization_pct": (live_notional / _st["max_position_value"] * 100) if _st["max_position_value"] else 0,
            },
            "errors": {
                "count_1h": _st["error_count"],
                "threshold": _st["error_threshold"],
                "near_limit": _st["error_count"] >= _st["error_threshold"] * 0.8,
                "phase": _st.get("error_threshold_phase", "steady"),
                "execution_warm": _st.get("error_threshold_execution_warm", False),
                "startup_grace_seconds": _st.get("error_threshold_startup_grace_seconds", 0),
                "grace_seconds_remaining": _st.get("error_threshold_grace_seconds_remaining", 0.0),
            },
            "limits": {
                "daily_loss_limit": daily_loss_limit,
                "max_position_value": _st["max_position_value"],
                "error_threshold": _st["error_threshold"],
            },
            # Top-level convenience for UI (also in risk_controller.get_status / crypto_pm_feed.summary)
            "all_pm_assets_have_spot": bool(_st.get("all_pm_assets_have_spot", True)),
            "crypto_pm_feed": crypto_pm_feed,
        }

        return state

    except Exception as e:
        logger.error(f"Failed to get risk state: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get risk state: {str(e)}")


# ── Agent Activity Endpoints ───────────────────────────────────────────


@router.get("/agent-activity")
async def get_agent_activity() -> Dict[str, Any]:
    """Get real-time agent activity and task metrics from Kalshi agent grid."""
    try:
        agents: List[Dict[str, Any]] = []

        # Primary: Kalshi agent grid (live trading agents)
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            summary = grid.summary()
            for a in summary.get("agents", []):
                _running = a.get("running", False)
                agents.append({
                    "agent_id": a.get("name", "unknown"),
                    "status": "active" if _running else "idle",
                    "tasks_completed": a.get("cycles_run", a.get("cycles", 0)),
                    "latency_ms": round(a.get("avg_cycle_ms", 0), 1),
                    "errors": 1 if a.get("last_error") else 0,
                    "last_seen": a.get("last_cycle_at", a.get("last_cycle_ts", None)),
                    "asset": a.get("asset") or (a.get("config", {}).get("assets", [""])[0] if a.get("config", {}).get("assets") else "kalshi"),
                    "active_markets": len(a.get("active_tickers", [])),
                    "win_rate": round(a.get("win_rate", 0) * 100, 1),
                })
        except Exception as exc:
            logger.debug(f"Kalshi grid agent-activity fetch error: {exc}")

        # Secondary: legacy orchestrator cycle results (non-Kalshi agents)
        try:
            from merid.agents.orchestrator import get_recent_cycle_results
            cycles = get_recent_cycle_results(limit=1)
            if cycles:
                latest = cycles[0]
                for phase in latest.phases:
                    agents.append({
                        "agent_id": phase.phase,
                        "status": "active" if phase.agents_run > 0 else "idle",
                        "tasks_completed": phase.agents_run,
                        "latency_ms": phase.latency_ms,
                        "errors": len(phase.errors),
                        "last_seen": latest.timestamp.isoformat(),
                    })
        except (ImportError, AttributeError):
            pass  # optional module not available
        except Exception as exc:
            logger.warning("Agent phase introspection failed: %s", exc)

        active = sum(1 for a in agents if a["status"] in ("running", "active"))
        total_tasks = sum(a["tasks_completed"] for a in agents)

        return {
            "agents": agents,
            "total_agents": len(agents),
            "active_agents": active,
            "total_tasks_1h": total_tasks,
            "last_update": None if not agents else agents[0].get("last_seen"),
        }

    except Exception as e:
        logger.error(f"Failed to get agent activity: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get agent activity: {str(e)}")


@router.get("/summary")
async def get_operator_summary() -> Dict[str, Any]:
    """Get operator dashboard summary with all key metrics."""
    try:
        from merid.risk.kill_switches import risk_controller
        from merid.settings import settings

        # ── Trading mode ────────────────────────────────────────────
        trading_mode = settings.MERID_PM_TRADING_MODE
        is_live = (
            trading_mode == "live"
            and settings.MERID_PM_LIVE_ENABLED
            and settings.MERID_LIVE_TRADING_UNLOCKED
        )

        # ── Kalshi balance + positions ───────────────────────────────
        balance_usd = 0.0
        positions_count = 0
        try:
            from merid.execution.executors.kalshi import KalshiExecutor
            import asyncio as _asyncio
            if not hasattr(get_operator_summary, "_kalshi"):
                get_operator_summary._kalshi = KalshiExecutor()
            _kalshi = get_operator_summary._kalshi
            balance_data, positions_data = await _asyncio.gather(
                _kalshi.get_balance(),
                _kalshi.get_positions(),
                return_exceptions=True,
            )
            if isinstance(balance_data, dict):
                balance_usd = balance_data.get("usd_dollars", 0.0)
            if isinstance(positions_data, list):
                positions_count = len(positions_data)
        except Exception as exc:
            logger.debug(f"Could not fetch Kalshi portfolio data: {exc}")

        # ── Agent grid status ────────────────────────────────────────
        total_agents = 0
        active_agents = 0
        total_cycles = 0
        total_fills = 0
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            grid_summary = grid.summary()
            total_agents = grid_summary.get("agent_count", grid_summary.get("total_agents", 0))
            active_agents = sum(
                1 for a in grid_summary.get("agents", [])
                if a.get("running") or a.get("status") in ("running", "active")
            )
            total_cycles = sum(a.get("cycles_run", a.get("cycles", 0)) for a in grid_summary.get("agents", []))
            metrics = grid_summary.get("metrics", {})
            total_fills = metrics.get("total_fills", 0)
            total_errors = sum(1 for a in grid_summary.get("agents", []) if a.get("last_error"))
            grid_paused = not grid.is_running
        except Exception as exc:
            logger.debug(f"Could not fetch agent grid status: {exc}")
            total_errors = 0
            grid_paused = False

        # ── System metrics ───────────────────────────────────────────
        cpu_pct = 0.0
        memory_pct = 0.0
        uptime_s = time.time() - _PROCESS_START
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            memory_pct = psutil.virtual_memory().percent
        except ImportError:
            logger.debug("psutil not installed — CPU/memory metrics unavailable")
        except Exception as exc:
            logger.debug(f"psutil metrics unavailable: {exc}")

        _rc_st = risk_controller.get_status()
        return {
            "mode": {
                "name": trading_mode,
                "is_paper": trading_mode in ("paper", "sim"),
                "is_live": is_live,
            },
            "portfolio": {
                "total_value": balance_usd,
                "unrealized_pnl": _rc_st.get("daily_pnl", 0.0),
                "position_count": positions_count,
            },
            "swarm": {
                "agents": total_agents,
                "active_agents": active_agents,
                "active_tasks": active_agents,
                "total_tasks": total_cycles,
                "completed": total_fills,
                "failed": total_errors,
                "paused": grid_paused,
                "success_rate": (total_fills / total_cycles) if total_cycles > 0 else 0.0,
            },
            "system": {
                "uptime_s": uptime_s,
                "cpu_percent": cpu_pct,
                "memory_percent": memory_pct,
            },
            "guard": {
                "kill_switch_active": not _rc_st.get("can_trade", True),
                "can_trade": _rc_st.get("can_trade", True),
                "daily_pnl": _rc_st.get("daily_pnl", 0.0),
                "daily_loss_limit": risk_controller.daily_loss_limit,
                "last_cqi": _get_last_cqi(),
                "domain_caps": _get_domain_caps(),
                "recent_verdicts_count": _get_recent_verdicts_count(),
            },
            "loop": {
                "running": not grid_paused,
                "total_ticks": total_cycles,
                "total_errors": total_errors,
                "plans_executed": total_fills,
                "last_tick_duration_ms": 0,
            },
        }

    except Exception as e:
        logger.error(f"Failed to get operator summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get operator summary: {str(e)}")


# ── Audit Trail ───────────────────────────────────────────────────────


@router.get("/audit-trail")
async def get_operator_audit_trail(limit: int = 20) -> Dict[str, Any]:
    """Recent operator audit trail entries from core audit trail."""
    entries: List[Dict[str, Any]] = []
    try:
        from core.audit_trail import get_audit_trail as _get_core_audit_trail
        import datetime as _dt
        trail = _get_core_audit_trail()
        raw = trail.entries[-limit:]
        entries = [
            {
                "seq": e.sequence,
                "timestamp": _dt.datetime.fromtimestamp(
                    e.timestamp, tz=_dt.timezone.utc
                ).isoformat() if isinstance(e.timestamp, (int, float)) else str(e.timestamp),
                "event_type": e.event_type,
                "source": e.source,
                "hash": e.entry_hash,
            }
            for e in raw
        ]
    except Exception as exc:
        logger.debug(f"Core audit trail unavailable: {exc}")

    # Fallback: pull recent order events from agent grid as activity
    if not entries:
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            import datetime as _dt
            for agent in grid.agents:
                for o in agent.get_orders(5):
                    entries.append({
                        "seq": len(entries) + 1,
                        "timestamp": o.get("ts", ""),
                        "event_type": "ORDER_PLACED",
                        "source": agent.config.name,
                        "hash": "",
                    })
            entries = sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
        except Exception as exc:
            logger.debug(f"Agent grid audit fallback failed: {exc}")

    return {"entries": entries, "total": len(entries)}


# ── Trading Mode ───────────────────────────────────────────────────────


class TradingModeRequest(BaseModel):
    """Request to switch trading mode."""
    mode: str
    reason: str = "operator"


@router.post("/trading-mode")
async def set_trading_mode(request: TradingModeRequest, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Switch the system trading mode (paper/live/sim)."""
    allowed = {"paper", "live", "sim", "hybrid", "autonomous"}
    if request.mode not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid mode '{request.mode}'. Allowed: {allowed}")
    try:
        from merid.settings import settings
        settings.MERID_PM_TRADING_MODE = request.mode
        logger.warning(f"Trading mode switched to '{request.mode}' — reason: {request.reason}")

        # Reload VenueGate singleton so UA live orders reflect the new mode immediately.
        try:
            from merid.prediction.venue_gate import get_venue_gate
            get_venue_gate().reload()
        except Exception as _vge:
            logger.warning("VenueGate reload after mode change failed (non-fatal): %s", _vge)

        # Reset CT singleton so it re-reads mode config on next cycle.
        try:
            from merid.trading.kalshi_continuous_trader import reset_continuous_trader
            reset_continuous_trader()
        except Exception as _cte:
            logger.warning("CT reset failed (non-fatal): %s", _cte)

        return {
            "status": "ok",
            "mode": request.mode,
            "reason": request.reason,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to switch trading mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Guard Kill / Unkill ────────────────────────────────────────────────


class GuardKillRequest(BaseModel):
    """Request to activate or deactivate the guard kill switch."""
    reason: str = "operator"


@router.post("/guard/kill")
async def guard_kill(request: GuardKillRequest, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Activate the global kill switch via the operator guard."""
    try:
        from merid.risk.kill_switches import risk_controller
        risk_controller.emergency_stop(request.reason)
        logger.warning(f"Guard KILL activated — reason: {request.reason}")
        return {
            "status": "killed",
            "reason": request.reason,
            "can_trade": False,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Guard kill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/guard/unkill")
async def guard_unkill(request: GuardKillRequest, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Reset the global kill switch via the operator guard."""
    try:
        from merid.risk.kill_switches import risk_controller
        risk_controller.reset()
        logger.info(f"Guard UNKILL — trading re-enabled. Reason: {request.reason}")
        return {
            "status": "active",
            "reason": request.reason,
            "can_trade": True,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Guard unkill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── System Decisions ───────────────────────────────────────────────────


@router.get("/decisions/recent")
async def get_recent_decisions(limit: int = 10) -> Dict[str, Any]:
    """Recent agent decisions for the operator activity stream."""
    decisions: List[Dict[str, Any]] = []

    # 1) Agent grid signal log
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        grid = get_agent_grid()
        for agent in grid.agents:
            for sig in agent.get_signals(limit):
                decisions.append({
                    "agent": agent.config.name,
                    "type": sig.get("action", "signal"),
                    "confidence": min(1.0, abs(float(sig.get("ev_cents", sig.get("edge", 0)))) / 10.0),
                    "reasoning": f"ev={sig.get('ev_cents', sig.get('edge', ''))} ticker={sig.get('ticker', '')}",
                    "timestamp": sig.get("ts", ""),
                })
    except Exception as exc:
        logger.debug(f"Recent decisions signal_log: {exc}")

    # 2) Consensus blocks as decisions
    if len(decisions) < limit:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            _cs = get_prediction_consensus_store()
            for op in _cs.list_opinions(limit=limit):
                prob = getattr(op, "probability", 0.5)
                conf = getattr(op, "confidence", 0.5)
                decisions.append({
                    "agent": getattr(op, "agent_id", "consensus"),
                    "type": "consensus_opinion",
                    "confidence": conf,
                    "reasoning": f"prob={prob:.0%}, conf={conf:.0%} on {getattr(op, 'symbol', '')}",
                    "timestamp": str(getattr(op, "timestamp", "")),
                })
        except Exception as exc2:
            logger.debug(f"Recent decisions consensus_blocks: {exc2}")

    # 3) Debate outcomes as decisions
    if len(decisions) < limit:
        _check_kalshi_15m_profile_guard("debate outcomes")
        try:
            from merid.prediction.debate import get_debate_store
            store = get_debate_store()
            for debate in store.list_debates(limit=limit):
                decisions.append({
                    "agent": "debate-coordinator",
                    "type": "debate_outcome",
                    "confidence": getattr(debate, "post_debate_prob", 0.5),
                    "reasoning": f"Debate {debate.id[:12]} on {getattr(debate, 'symbol', '')} — {getattr(debate, 'status', 'unknown')} ({getattr(debate, 'rounds', 0)} rounds)",
                    "timestamp": str(getattr(debate, "created_at", "")),
                })
        except Exception as exc3:
            logger.debug(f"Recent decisions debate_store: {exc3}")

    # 4) Agent cycle activity as decisions
    if len(decisions) < limit:
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            import datetime as _dt
            _now = _dt.datetime.now(_dt.timezone.utc)
            for agent in grid.agents:
                if agent.state.cycles_run > 0:
                    decisions.append({
                        "agent": agent.config.name,
                        "type": "cycle_scan",
                        "confidence": 0.5,
                        "reasoning": f"Completed {agent.state.cycles_run} scan cycles, {agent.state.orders_placed} orders placed",
                        "timestamp": _now.isoformat(),
                    })
        except Exception as e:
            logger.debug(f"Silent error: {e}")

    decisions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"decisions": decisions[:limit], "count": len(decisions[:limit])}


# ── Legacy /api/operator/ stubs (no /v1/) ─────────────────────────────



@legacy_router.get("/governance-status")
async def get_governance_status_legacy() -> Dict[str, Any]:
    """Governance status stub — not implemented in Kalshi-only mode."""
    _check_kalshi_15m_profile_guard("governance status")
    return {
        "channels": [],
        "total_dispatches": 0,
        "recent_dispatches": [],
        "promotion_enforcement": {
            "enabled": False,
            "eligible_domains": [],
            "blocked_agents": [],
            "report_ts": time.time(),
            "sync_age_s": None,
            "stale": False,
        },
    }


@legacy_router.get("/promotion-log")
async def get_promotion_log_legacy(limit: int = 50) -> Dict[str, Any]:
    """Promotion log stub — not implemented in Kalshi-only mode."""
    return {"total_events": 0, "returned": 0, "events": []}


@legacy_router.get("/promotion-report")
async def get_promotion_report_legacy() -> Dict[str, Any]:
    """Promotion report stub — not implemented in Kalshi-only mode."""
    return {
        "timestamp": time.time(),
        "overall_eligible": False,
        "all_rings_pass": False,
        "rings": [],
        "domains": {"eligible": [], "blocked": [], "detail": []},
        "agents": {"promoted": [], "blocked": [], "detail": []},
        "elapsed_s": 0.0,
    }


@legacy_router.post("/promotion-report/refresh")
async def refresh_promotion_report_legacy() -> Dict[str, Any]:
    """Promotion report refresh stub."""
    return await get_promotion_report_legacy()


# ── Tick Timeline Endpoints ───────────────────────────────────────────


@router.get("/ticks")
async def get_recent_ticks(
    limit: int = 50,
) -> Dict[str, Any]:
    """Return recent tick summaries from the TickEventBus (last N ticks).

    Each entry is a TickSummary dict:
      tick_id, agent_id, ts, duration_ms, mode,
      markets_resolved, signals_evaluated,
      orders_submitted, fills_confirmed, error, ...
    """
    try:
        from merid.tick_events import get_tick_bus
        bus = get_tick_bus()
        summaries = bus.recent_summaries(min(limit, 200))
        return {
            "ticks": summaries,
            "count": len(summaries),
            "stats": bus.stats(),
        }
    except Exception as exc:
        logger.warning("get_recent_ticks error: %s", exc)
        return {"ticks": [], "count": 0, "error": str(exc)}


@router.get("/ticks/events")
async def get_recent_tick_events(
    limit: int = 100,
) -> Dict[str, Any]:
    """Return granular recent tick events (all event types, not just summaries).

    Useful for a fine-grained operator timeline.
    """
    try:
        from merid.tick_events import get_tick_bus
        bus = get_tick_bus()
        events = bus.recent_events(min(limit, 500))
        return {"events": events, "count": len(events)}
    except Exception as exc:
        logger.warning("get_recent_tick_events error: %s", exc)
        return {"events": [], "count": 0, "error": str(exc)}


@router.get("/ticks/stats")
async def get_tick_stats() -> Dict[str, Any]:
    """Return aggregate tick statistics: error rate, avg latency, order/fill totals."""
    try:
        from merid.tick_events import get_tick_bus
        return get_tick_bus().stats()
    except Exception as exc:
        logger.warning("get_tick_stats error: %s", exc)
        return {"error": str(exc)}
