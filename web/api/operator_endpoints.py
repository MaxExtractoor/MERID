"""Operator dashboard endpoints for kill switch, risk state, and agent activity."""

import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Track process start time for uptime calculation
_PROCESS_START = time.time()


def _get_recent_verdicts_count() -> int:
    """Return count of recent execution verdicts from the Kalshi order router."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        risk = get_kalshi_risk()
        state = risk.state
        return state.orders_this_hour + state.orders_this_minute
    except Exception:
        pass
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        sys = tracker.get_system_summary()
        return sys.get("total_fills", 0)
    except Exception:
        return 0

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
        
        return {
            "global_kill": risk_controller._global_kill,
            "state": risk_controller.state(),
            "can_trade": risk_controller.can_trade(),
            "kill_reason": risk_controller.get_kill_reason(),
            "kill_timestamp": risk_controller._kill_timestamp.isoformat() if risk_controller._kill_timestamp else None,
            "daily_pnl": risk_controller._daily_pnl,
            "daily_loss_limit": risk_controller.daily_loss_limit,
            "total_position_value": risk_controller._total_position_value,
            "max_position_value": risk_controller.max_position_value,
            "error_count": risk_controller._error_count,
            "error_threshold": risk_controller.error_threshold,
        }
    except Exception as e:
        logger.error(f"Failed to get kill switch status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get kill switch status: {str(e)}")


@router.post("/emergency-stop")
async def emergency_stop(request: EmergencyStopRequest) -> Dict[str, Any]:
    """Trigger emergency stop - immediately halts all trading."""
    try:
        from merid.risk.kill_switches import risk_controller
        
        risk_controller.emergency_stop(request.reason)
        
        logger.warning(f"EMERGENCY STOP triggered: {request.reason}")
        
        return {
            "status": "halted",
            "reason": request.reason,
            "timestamp": risk_controller._kill_timestamp.isoformat() if risk_controller._kill_timestamp else None,
            "can_trade": False,
        }
    except Exception as e:
        logger.error(f"Failed to trigger emergency stop: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger emergency stop: {str(e)}")


@router.post("/reset-kill-switch")
async def reset_kill_switch(request: KillSwitchResetRequest) -> Dict[str, Any]:
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

        # Sync live position notional from KalshiRiskManager so utilization is real
        live_notional = risk_controller._total_position_value
        live_daily_pnl = risk_controller._daily_pnl
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            krm = get_kalshi_risk()
            ks = krm.state
            if ks.total_notional_usd > 0:
                live_notional = float(ks.total_notional_usd)
                risk_controller._total_position_value = live_notional
            if ks.daily_pnl_usd != 0:
                live_daily_pnl = float(ks.daily_pnl_usd)
                risk_controller._daily_pnl = live_daily_pnl
        except Exception:
            pass

        state = {
            "kill_switch": {
                "active": risk_controller._global_kill,
                "reason": risk_controller.get_kill_reason(),
                "can_trade": risk_controller.can_trade(),
            },
            "pnl": {
                "daily_pnl": live_daily_pnl,
                "daily_loss_limit": risk_controller.daily_loss_limit,
                "limit_remaining": risk_controller.daily_loss_limit + live_daily_pnl,
                "utilization_pct": abs(live_daily_pnl / risk_controller.daily_loss_limit * 100) if risk_controller.daily_loss_limit else 0,
            },
            "position": {
                "total_value": live_notional,
                "max_allowed": risk_controller.max_position_value,
                "utilization_pct": (live_notional / risk_controller.max_position_value * 100) if risk_controller.max_position_value else 0,
            },
            "errors": {
                "count_1h": risk_controller._error_count,
                "threshold": risk_controller.error_threshold,
                "near_limit": risk_controller._error_count >= risk_controller.error_threshold * 0.8,
            },
            "limits": {
                "daily_loss_limit": risk_controller.daily_loss_limit,
                "max_position_value": risk_controller.max_position_value,
                "error_threshold": risk_controller.error_threshold,
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
                agents.append({
                    "agent_id": a.get("name", "unknown"),
                    "status": a.get("status", "idle"),
                    "tasks_completed": a.get("cycles", 0),
                    "latency_ms": round(a.get("avg_cycle_ms", 0), 1),
                    "errors": a.get("errors", 0),
                    "last_seen": a.get("last_cycle_ts", None),
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
                if a.get("status") in ("running", "active")
            )
            total_cycles = sum(a.get("cycles", 0) for a in grid_summary.get("agents", []))
            metrics = grid_summary.get("metrics", {})
            total_fills = metrics.get("total_fills", 0)
        except Exception as exc:
            logger.debug(f"Could not fetch agent grid status: {exc}")

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

        return {
            "mode": {
                "name": trading_mode,
                "is_paper": trading_mode in ("paper", "sim"),
                "is_live": is_live,
            },
            "portfolio": {
                "total_value": balance_usd,
                "unrealized_pnl": risk_controller._daily_pnl,
                "position_count": positions_count,
            },
            "swarm": {
                "agents": total_agents,
                "active_agents": active_agents,
                "active_tasks": active_agents,
                "total_tasks": total_cycles,
                "completed": total_fills,
                "failed": 0,
                "paused": False,
                "success_rate": (total_fills / total_cycles) if total_cycles > 0 else 0.0,
            },
            "system": {
                "uptime_s": uptime_s,
                "cpu_percent": cpu_pct,
                "memory_percent": memory_pct,
            },
            "guard": {
                "kill_switch_active": risk_controller._global_kill,
                "can_trade": risk_controller.can_trade(),
                "daily_pnl": risk_controller._daily_pnl,
                "daily_loss_limit": risk_controller.daily_loss_limit,
                "last_cqi": {},
                "domain_caps": {},
                "recent_verdicts_count": _get_recent_verdicts_count(),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get operator summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get operator summary: {str(e)}")


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
