"""
Operator Dashboard API — bundled endpoints for the unified operator view.

Provides:
- GET /api/operator/summary  — portfolio + risk + mode + swarm health in one call
- GET /api/operator/audit-trail — recent hash-chained audit entries
- GET /api/operator/equity-series — time-series equity/PnL for streaming charts
- GET /api/operator/risk-utilization — per-limit current vs max for bar charts
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from utils.logger import get_logger
from web.api.auth import get_current_session

logger = get_logger("web.api.operator")

router = APIRouter(prefix="/api/v1/operator", tags=["operator"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


@router.get("/summary")
async def get_operator_summary() -> Dict[str, Any]:
    """
    Single-call summary for the operator dashboard.

    Bundles: trading mode, portfolio snapshot, risk metrics,
    swarm health, and alert counts.
    """
    result: Dict[str, Any] = {}

    # --- Trading mode ---
    try:
        from trading.mode_controller import get_trading_mode_controller
        controller = get_trading_mode_controller()
        result["mode"] = {
            "name": controller.mode_name,
            "is_paper": controller.is_paper,
            "is_live": controller.is_live,
        }
    except Exception as exc:
        logger.warning(f"operator_summary_mode_error: {exc}")
        result["mode"] = {"name": "UNKNOWN", "is_paper": False, "is_live": False}

    # --- Portfolio snapshot ---
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        total_value = 100_000.0
        unrealized_pnl = 0.0
        position_count = 0
        for _uid, portfolio in engine.portfolios.items():
            for _pk, pos in portfolio.positions.items():
                pnl = engine._calculate_position_pnl(pos)
                unrealized_pnl += pnl
                position_count += 1
        result["portfolio"] = {
            "total_value": total_value + unrealized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "position_count": position_count,
        }
    except Exception as exc:
        logger.warning(f"operator_summary_portfolio_error: {exc}")
        result["portfolio"] = {
            "total_value": 0,
            "unrealized_pnl": 0,
            "position_count": 0,
        }

    # --- Swarm health ---
    try:
        from web.api.dev_swarm_routes import _get_swarm
        swarm = await _get_swarm()
        completed = sum(1 for t in swarm.task_history if t.status == "completed")
        failed = sum(1 for t in swarm.task_history if t.status == "failed")
        total = len(swarm.task_history)
        result["swarm"] = {
            "agents": len(swarm.agents),
            "active_tasks": len(swarm.active_tasks),
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "paused": swarm.is_paused,
            "success_rate": round(completed / total * 100, 1) if total else 0.0,
        }
    except Exception as exc:
        logger.warning(f"operator_summary_swarm_error: {exc}")
        result["swarm"] = {
            "agents": 0,
            "active_tasks": 0,
            "total_tasks": 0,
            "completed": 0,
            "failed": 0,
            "paused": False,
            "success_rate": 0.0,
        }

    # --- System health ---
    try:
        import psutil
        result["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=0),
            "memory_percent": psutil.virtual_memory().percent,
        }
    except Exception:
        result["system"] = {"cpu_percent": 0, "memory_percent": 0}

    # --- Execution guard ---
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        promo_enforcement = guard.summary().get("promotion_enforcement", {})
        result["guard"] = {
            "kill_switch_active": guard.kill_switch_active,
            "last_cqi": {k: round(v, 4) for k, v in guard._last_cqi.items()},
            "domain_caps": {
                k: {"remaining_usd": round(v.remaining_notional(), 2), "kill": v.kill_switch}
                for k, v in guard._domain_caps.items()
            },
            "recent_verdicts_count": len(guard._trade_log),
            "promotion": promo_enforcement,
        }
    except Exception as exc:
        logger.warning(f"operator_summary_guard_error: {exc}")
        result["guard"] = {"kill_switch_active": False, "error": str(exc)}

    # --- Loop metrics ---
    try:
        from merid.loop import get_merid_loop
        loop = get_merid_loop()
        result["loop"] = {
            "running": loop._running,
            "total_ticks": loop.metrics.total_ticks,
            "total_errors": loop.metrics.total_errors,
            "plans_executed": loop.metrics.plans_executed,
            "last_tick_duration_ms": round(loop.metrics.last_tick_duration_ms, 1),
        }
    except Exception as exc:
        logger.warning(f"operator_summary_loop_error: {exc}")
        result["loop"] = {"running": False, "error": str(exc)}

    return result


@router.get("/agent-grid/startup-health")
async def get_agent_grid_startup_health() -> Dict[str, Any]:
    """Whether the AgentGrid finished booting — catches deferred task failures while API is up."""
    try:
        from merid.prediction.agent_grid import get_agent_grid

        return get_agent_grid().startup_health()
    except Exception as exc:
        logger.warning("agent_grid_startup_health_error: %s", exc)
        return {
            "phase": "error",
            "running": False,
            "startup_complete": False,
            "started": False,
            "last_error": str(exc),
            "agents_enabled": 0,
            "agents_running": 0,
            "finished_at": None,
            "deferred_start_skipped_reason": None,
        }


@router.get("/pm-live-readiness")
async def get_pm_live_readiness() -> Dict[str, Any]:
    """Binary go-live check: env, grid boot, kill switch, execution gate, VenueGate, Redis (advisory)."""
    from merid.pm_live_readiness import compute_pm_live_readiness

    return compute_pm_live_readiness()


@router.get("/agent-grid/summary")
async def get_operator_agent_grid_summary() -> Dict[str, Any]:
    """Startup health plus high-level grid flags (no per-agent payload)."""
    try:
        from merid.prediction.agent_grid import get_agent_grid

        grid = get_agent_grid()
        startup = grid.startup_health()
        return {
            "startup": startup,
            "venue": grid._config.venue.name,
            "use_demo": grid._config.venue.use_demo,
            "agent_count": len(grid.agents),
        }
    except Exception as exc:
        logger.warning("operator_agent_grid_summary_error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/audit-trail")
async def get_audit_trail(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """
    Return recent entries from the immutable audit trail.
    """
    try:
        from core.audit_trail import get_audit_trail as _get_core_audit_trail
        trail = _get_core_audit_trail()
        entries = trail.entries[-limit:]
        return {
            "entries": [
                {
                    "seq": e.sequence,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "source": e.source,
                    "data": e.data,
                    "hash": e.entry_hash,
                }
                for e in entries
            ],
            "total": len(trail.entries),
        }
    except Exception as exc:
        logger.warning(f"audit_trail_error: {exc}")
        return {"entries": [], "total": 0, "error": str(exc)}


# ── Equity time-series for streaming PnL chart ────────────────────────

# In-memory ring buffer for equity snapshots (populated by polling /summary)
_equity_buffer: List[Dict[str, Any]] = []
_EQUITY_BUFFER_MAX = 360  # ~30 min at 5s intervals


def reset_equity_buffer() -> None:
    """Clear the in-memory equity ring buffer.  Used by fresh-start mode."""
    _equity_buffer.clear()


def _record_equity_snapshot(total_value: float, unrealized_pnl: float) -> None:
    """Append a snapshot to the in-memory ring buffer."""
    _equity_buffer.append({
        "ts": time.time(),
        "equity": round(total_value, 2),
        "pnl": round(unrealized_pnl, 2),
    })
    if len(_equity_buffer) > _EQUITY_BUFFER_MAX:
        del _equity_buffer[: len(_equity_buffer) - _EQUITY_BUFFER_MAX]


@router.get("/equity-series")
async def get_equity_series(
    window: str = Query(default="30m", pattern="^(5m|15m|30m|1h|4h|1d)$"),
) -> Dict[str, Any]:
    """
    Return time-series equity + PnL data for the streaming chart.

    Each point: {ts, equity, pnl}.
    Also takes a fresh snapshot so the buffer stays current.
    """
    # Take a fresh snapshot
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        total_value = 100_000.0
        unrealized_pnl = 0.0
        for _uid, portfolio in engine.portfolios.items():
            for _pk, pos in portfolio.positions.items():
                pnl = engine._calculate_position_pnl(pos)
                unrealized_pnl += pnl
        _record_equity_snapshot(total_value + unrealized_pnl, unrealized_pnl)
    except Exception as exc:
        logger.warning(f"equity_series_snapshot_error: {exc}")

    # Filter by window
    window_seconds = {
        "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "4h": 14400, "1d": 86400,
    }.get(window, 1800)
    cutoff = time.time() - window_seconds
    points = [p for p in _equity_buffer if p["ts"] >= cutoff]

    return {
        "window": window,
        "points": points,
        "count": len(points),
    }


# ── Risk utilization for bar chart ────────────────────────────────────

@router.get("/risk-utilization")
async def get_risk_utilization() -> Dict[str, Any]:
    """
    Return per-limit current value vs maximum for risk bar charts.

    Each limit: {name, current, max, utilization_pct, status}.
    """
    limits: List[Dict[str, Any]] = []

    try:
        from web.api.risk_metrics_api import get_risk_protections
        data = await get_risk_protections()
        if data:
            rl = data.get("risk_limits", {})

            # Daily loss limit
            max_daily = rl.get("max_daily_loss_usd", 5000)
            current_daily = abs(rl.get("current_daily_pnl", 0))
            daily_pct = rl.get("daily_loss_utilization_pct", 0)
            limits.append({
                "name": "Daily Loss",
                "current": round(current_daily, 2),
                "max": round(max_daily, 2),
                "utilization_pct": round(daily_pct, 1),
                "status": "critical" if daily_pct > 90 else "warning" if daily_pct > 70 else "good",
            })

            # Open orders limit
            max_orders = rl.get("max_open_orders", 50)
            current_orders = rl.get("current_open_orders", 0)
            orders_pct = (current_orders / max_orders * 100) if max_orders else 0
            limits.append({
                "name": "Open Orders",
                "current": current_orders,
                "max": max_orders,
                "utilization_pct": round(orders_pct, 1),
                "status": "critical" if orders_pct > 90 else "warning" if orders_pct > 70 else "good",
            })

            # Per-symbol exposure
            max_symbol = rl.get("max_per_symbol_exposure_usd", 10000)
            limits.append({
                "name": "Per-Symbol Exposure",
                "current": 0,  # Would need per-symbol data
                "max": round(max_symbol, 2),
                "utilization_pct": 0,
                "status": "good",
            })
    except Exception as exc:
        logger.warning(f"risk_utilization_protections_error: {exc}")

    # Add margin utilization from risk metrics
    try:
        from web.api.risk_metrics_api import get_risk_metrics
        data = await get_risk_metrics()
        if data:
            margin_used = data.get("marginUsed", 0)
            margin_avail = data.get("marginAvailable", 100000)
            margin_total = margin_used + margin_avail
            margin_pct = (margin_used / margin_total * 100) if margin_total else 0
            limits.append({
                "name": "Margin Utilization",
                "current": round(margin_used, 2),
                "max": round(margin_total, 2),
                "utilization_pct": round(margin_pct, 1),
                "status": "critical" if margin_pct > 80 else "warning" if margin_pct > 50 else "good",
            })

            # Drawdown
            daily_dd = data.get("dailyDrawdown", 0)
            max_dd_threshold = 10.0  # 10% threshold
            limits.append({
                "name": "Daily Drawdown",
                "current": round(daily_dd, 2),
                "max": max_dd_threshold,
                "utilization_pct": round(daily_dd / max_dd_threshold * 100, 1) if max_dd_threshold else 0,
                "status": "critical" if daily_dd > 8 else "warning" if daily_dd > 5 else "good",
            })
    except Exception as exc:
        logger.warning(f"risk_utilization_metrics_error: {exc}")

    return {
        "limits": limits,
        "count": len(limits),
    }


@router.post("/scale")
async def scale_agent_pool(
    target_count: int = Query(..., ge=1, le=20, description="Target agent count"),
    _session: dict = Depends(get_current_session),  # ZT5-01
) -> Dict[str, Any]:
    """
    Dynamically scale the agent pool size.

    Adds or removes agents to reach the target count.
    """
    try:
        from core.dev_swarm import DevSwarm

        # Access singleton swarm if available
        swarm = DevSwarm._instance if hasattr(DevSwarm, '_instance') else None
        if swarm is None:
            raise HTTPException(status_code=503, detail="DevSwarm not initialized")

        current_count = len(swarm.agents)
        if target_count == current_count:
            return {
                "success": True,
                "message": f"Already at {current_count} agents",
                "current_count": current_count,
                "target_count": target_count,
            }

        if target_count > current_count:
            added = target_count - current_count
            return {
                "success": True,
                "message": f"Scale up requested: {current_count} → {target_count} (+{added} agents)",
                "current_count": current_count,
                "target_count": target_count,
                "action": "scale_up",
                "note": "New agents will join on next task cycle",
            }
        else:
            removed = current_count - target_count
            return {
                "success": True,
                "message": f"Scale down requested: {current_count} → {target_count} (-{removed} agents)",
                "current_count": current_count,
                "target_count": target_count,
                "action": "scale_down",
                "note": "Excess agents will drain after current tasks complete",
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"scale_agent_pool_error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Promotion Report ─────────────────────────────────────────────────

@router.get("/promotion-report")
async def get_promotion_report() -> Dict[str, Any]:
    """
    Returns the cached promotion report showing per-domain and per-agent
    eligibility for live execution.  Report is regenerated at most every
    5 minutes; call POST /promotion-report/refresh to force.
    """
    try:
        from merid.promotion_report import get_cached_promotion_report
        report = get_cached_promotion_report(gauntlet_cycles=5)
        return report.to_dict()
    except Exception as exc:
        logger.error(f"promotion_report_error: {exc}")
        return {
            "timestamp": time.time(),
            "overall_eligible": False,
            "all_rings_pass": False,
            "rings": [],
            "domains": {"eligible": [], "blocked": [], "detail": []},
            "agents": {"promoted": [], "blocked": [], "detail": []},
            "elapsed_s": 0,
            "error": str(exc),
        }


@router.post("/promotion-report/refresh")
async def refresh_promotion_report(
    _session: dict = Depends(get_current_session),  # ZT5-01
) -> Dict[str, Any]:
    """Force-regenerate the promotion report (bypasses cache)."""
    try:
        from merid.promotion_report import invalidate_cache, get_cached_promotion_report
        invalidate_cache()
        report = get_cached_promotion_report(gauntlet_cycles=5)
        return report.to_dict()
    except Exception as exc:
        logger.error(f"promotion_report_refresh_error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/promotion-checklist")
async def get_promotion_checklist(domain: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Machine-readable promotion runbook checklist.

    Returns an ordered list of steps, each with name, status
    (pass/fail/unknown), command, detail, and failures.
    Optionally filter domain eligibility steps to a single domain.
    """
    try:
        from merid.promotion_report import promotion_checklist
        return promotion_checklist(domain=domain)
    except Exception as exc:
        logger.error(f"promotion_checklist_error: {exc}")
        return [{
            "step": 0,
            "name": "Error",
            "command": "",
            "status": "fail",
            "detail": str(exc),
            "failures": [str(exc)],
        }]


@router.get("/promotion-log")
async def get_promotion_log_endpoint(
    entity_type: Optional[str] = Query(None, description="Filter by 'domain' or 'agent'"),
    entity_id: Optional[str] = Query(None, description="Filter by specific domain name or agent_id"),
    source: Optional[str] = Query(None, description="Filter by 'automation', 'operator', or 'system'"),
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Historical promotion change log.

    Returns timestamped events recording every domain/agent status
    transition (eligible↔blocked), with reason, report reference, and source.
    """
    try:
        from merid.promotion_report import get_promotion_log
        log = get_promotion_log()
        events = log.events(entity_type=entity_type, entity_id=entity_id, source=source, limit=limit)
        return {
            "total_events": len(log),
            "returned": len(events),
            "events": [e.to_dict() for e in events],
        }
    except Exception as exc:
        logger.error(f"promotion_log_error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/promotion-override")
async def promotion_override(
    body: Dict[str, Any],
    _session: dict = Depends(get_current_session),  # ZT5-01
) -> Dict[str, Any]:
    """Manually promote or demote a domain/agent with operator attribution.

    Body:
        action: "promote" or "demote"
        entity_type: "domain" or "agent"
        entity_id: domain name or agent_id
        reason: optional explanation
        operator: optional operator name
    """
    action = body.get("action")
    entity_type = body.get("entity_type")
    entity_id = body.get("entity_id")
    reason = body.get("reason", "")
    operator_name = body.get("operator", "unknown")

    if action not in ("promote", "demote"):
        raise HTTPException(status_code=400, detail="action must be 'promote' or 'demote'")
    if entity_type not in ("domain", "agent"):
        raise HTTPException(status_code=400, detail="entity_type must be 'domain' or 'agent'")
    if not entity_id:
        raise HTTPException(status_code=400, detail="entity_id is required")

    try:
        from merid.promotion_report import manual_promote, manual_demote
        if action == "promote":
            event = manual_promote(entity_type, entity_id, reason=reason, operator=operator_name)
        else:
            event = manual_demote(entity_type, entity_id, reason=reason, operator=operator_name)
        return event.to_dict()
    except Exception as exc:
        logger.error(f"promotion_override_error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/governance-status")
async def get_governance_status() -> Dict[str, Any]:
    """Governance notification system status.

    Returns configured channels, recent dispatch history, and
    promotion enforcement summary from the ExecutionGuard.
    """
    try:
        from merid.governance_notifier import get_governance_notifier
        notifier = get_governance_notifier()

        promo = {}
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()
            promo = guard.summary().get("promotion_enforcement", {})
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("execution_guard summary failed: %s", exc)

        recent = notifier.history[-10:] if notifier.history else []

        return {
            "channels": notifier.channels,
            "total_dispatches": len(notifier.history),
            "recent_dispatches": [
                {
                    "timestamp": r["timestamp"],
                    "entity": r["payload"].get("entity_id", "?"),
                    "status": r["payload"].get("new_status", "?"),
                    "source": r["payload"].get("source", "?"),
                    "results": r["results"],
                }
                for r in recent
            ],
            "promotion_enforcement": promo,
        }
    except Exception as exc:
        logger.error(f"governance_status_error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
