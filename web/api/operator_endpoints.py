"""Operator dashboard endpoints for kill switch, risk state, and agent activity."""

import logging
import os
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Track process start time for uptime calculation
_PROCESS_START = time.time()


def _get_last_cqi() -> Dict[str, float]:
    """Return per-agent cycle count as a proxy CQI until confidence tracking is added."""
    try:
        from merid.prediction.agent_grid import get_agent_grid
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

def _require_operator_auth(request: Request) -> None:
    """Verify operator Bearer token for destructive actions.

    Token is read from ``MERID_OPERATOR_TOKEN`` env-var.
    If the env-var is unset the guard logs a warning and allows access
    (so dev/paper setups are not broken), but in production it MUST be set.
    """
    expected = os.getenv("MERID_OPERATOR_TOKEN", "")
    if not expected:
        logger.warning(
            "MERID_OPERATOR_TOKEN not set — operator endpoints are UNPROTECTED. "
            "Set this env-var in production."
        )
        return  # allow through in dev/paper

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing operator token")
    token = auth_header.split(" ", 1)[1]
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid operator token")


router = APIRouter(prefix="/api/v1/operator", tags=["operator"])

# Legacy /api/operator/ prefix router (no /v1/) — used by promotion/governance hooks
legacy_router = APIRouter(prefix="/api/operator", tags=["operator-legacy"])


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
    try:
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
    except Exception as e:
        logger.error(f"Failed to get kill switch status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get kill switch status: {str(e)}")


@router.post("/emergency-stop")
async def emergency_stop(request: EmergencyStopRequest, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Trigger emergency stop - immediately halts all trading."""
    try:
        from merid.risk.kill_switches import risk_controller
        
        risk_controller.emergency_stop(request.reason)
        
        logger.warning(f"EMERGENCY STOP triggered: {request.reason}")
        
        return {
            "status": "halted",
            "reason": request.reason,
            "timestamp": risk_controller.get_status().get("kill_timestamp"),
            "can_trade": False,
        }
    except Exception as e:
        logger.error(f"Failed to trigger emergency stop: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger emergency stop: {str(e)}")


@router.post("/reset-kill-switch")
async def reset_kill_switch(request: KillSwitchResetRequest, _auth: None = Depends(_require_operator_auth)) -> Dict[str, Any]:
    """Reset kill switch after resolution."""
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to reset kill switch")
    
    try:
        from merid.risk.kill_switches import risk_controller
        
        risk_controller.reset()
        
        logger.info("Kill switch reset - trading re-enabled")
        
        return {
            "status": "active",
            "can_trade": True,
            "message": "Kill switch reset successfully",
        }
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

        # Best-effort Redis health check
        redis_healthy = False
        redis_error = None
        try:
            import os
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            try:
                import redis.asyncio as redis
                r = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
                await r.ping()
                redis_healthy = True
            except Exception as redis_exc:
                redis_error = str(redis_exc)
        except ImportError:
            redis_error = "Redis client not installed"
        except Exception as health_exc:
            redis_error = str(health_exc)

        state = {
            "kill_switch": {
                "active": not _st["can_trade"],
                "reason": risk_controller.get_kill_reason(),
                "can_trade": _st["can_trade"],
            },
            "pnl": {
                "daily_pnl": live_daily_pnl,
                "daily_loss_limit": _st["daily_loss_limit"],
                "limit_remaining": _st["daily_loss_limit"] + live_daily_pnl,
                "utilization_pct": abs(live_daily_pnl / _st["daily_loss_limit"] * 100) if _st["daily_loss_limit"] else 0,
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
            },
            "limits": {
                "daily_loss_limit": _st["daily_loss_limit"],
                "max_position_value": _st["max_position_value"],
                "error_threshold": _st["error_threshold"],
            },
            "redis": {
                "healthy": redis_healthy,
                "error": redis_error,
                "degraded_services": [] if redis_healthy else ["settlement_persistence", "risk_analytics"],
            },
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
            from merid.prediction.agent_grid import get_agent_grid
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
                    "asset": a.get("asset", ""),
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
        except (ImportError, AttributeError, Exception):
            pass

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
            from merid.prediction.agent_grid import get_agent_grid
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
            pass
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
                "can_trade": risk_controller.can_trade(),
                "daily_pnl": _rc_st.get("daily_pnl", 0.0),
                "daily_loss_limit": risk_controller.daily_loss_limit,
                "last_cqi": _get_last_cqi(),
                "domain_caps": _get_domain_caps(),
                "recent_verdicts_count": _get_recent_verdicts_count(),
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
        from core.audit_trail import AuditTrail
        import datetime as _dt
        trail = AuditTrail()
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
            from merid.prediction.agent_grid import get_agent_grid
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
    try:
        from merid.prediction.agent_grid import get_agent_grid
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
        decisions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        decisions = decisions[:limit]
    except Exception as exc:
        logger.debug(f"Recent decisions fetch failed: {exc}")
    return {"decisions": decisions, "count": len(decisions)}


# ── Legacy /api/operator/ stubs (no /v1/) ─────────────────────────────



@legacy_router.get("/governance-status")
async def get_governance_status_legacy() -> Dict[str, Any]:
    """Governance status stub — not implemented in Kalshi-only mode."""
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
