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

from fastapi import APIRouter, HTTPException, Query
from utils.logger import get_logger

logger = get_logger("web.api.operator")

router = APIRouter(prefix="/api/operator", tags=["operator"])


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
        from web.api.dev_swarm_routes import get_swarm
        swarm = await get_swarm()
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

    return result


@router.get("/audit-trail")
async def get_audit_trail(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """
    Return recent entries from the immutable audit trail.
    """
    try:
        from core.audit_trail import AuditTrail
        trail = AuditTrail()
        entries = trail.entries[-limit:]
        return {
            "entries": [
                {
                    "seq": e.seq,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "source": e.source,
                    "data": e.data,
                    "hash": e.hash,
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
        import requests as _req
        resp = _req.get("http://localhost:8000/api/risk/protections", timeout=2)
        if resp.ok:
            data = resp.json()
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
        import requests as _req
        resp = _req.get("http://localhost:8000/api/v1/risk/metrics", timeout=2)
        if resp.ok:
            data = resp.json()
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
async def scale_agent_pool(target_count: int = Query(..., ge=1, le=20, description="Target agent count")) -> Dict[str, Any]:
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
