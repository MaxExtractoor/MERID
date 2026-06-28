"""
Risk Metrics API Endpoint

Provides real-time risk metrics including P&L, drawdown, margin utilization, and exposure.
Also exposes trading halt/resume controls and feed staleness status.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.risk_metrics_api")

router = APIRouter(prefix="/api/v1/risk", tags=["risk"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class HaltRequest(BaseModel):
    reason: str = "operator_manual_halt"


class ResumeRequest(BaseModel):
    operator: str = "operator"


@router.get("/metrics")
async def get_risk_metrics() -> Dict[str, Any]:
    """
    Get current risk metrics for the trading system.
    
    Returns:
        {
            "totalPnL": float,
            "dailyDrawdown": float,
            "maxDrawdown": float,
            "marginUsed": float,
            "marginAvailable": float,
            "exposure": {
                "BTC": {"long": float, "short": float},
                "ETH": {"long": float, "short": float},
                ...
            },
            "alerts": [
                {
                    "id": str,
                    "metric": str,
                    "value": float,
                    "threshold": float,
                    "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
                    "createdAt": str (ISO timestamp)
                }
            ]
        }
    """
    try:
        from trading.paper_trading import get_paper_engine
        
        paper_engine = get_paper_engine()
        risk_controller = None  # Risk controller not available
        
        # Get global stats from paper engine
        global_stats = paper_engine.get_global_stats()
        
        # Calculate aggregate metrics
        total_pnl = global_stats.get("total_pnl", 0.0)
        total_equity = global_stats.get("equity", 0.0)
        total_cash = global_stats.get("cash", 0.0)
        
        # Calculate drawdown (simplified)
        starting_balance = 10000.0  # Default starting balance
        max_equity = max(total_equity, starting_balance)
        current_drawdown = ((max_equity - total_equity) / max_equity * 100) if max_equity > 0 else 0
        
        # Calculate margin metrics
        positions = global_stats.get("positions", [])
        margin_used = sum(
            pos.get("size_usd", 0) / pos.get("leverage", 1) 
            for pos in positions
        )
        margin_available = total_cash
        
        # Calculate exposure by symbol
        exposure: Dict[str, Dict[str, float]] = {}
        for pos in positions:
            symbol = pos.get("asset", "UNKNOWN")
            side = pos.get("side", "long").lower()
            size = pos.get("size_usd", 0.0)
            
            if symbol not in exposure:
                exposure[symbol] = {"long": 0.0, "short": 0.0}
            
            exposure[symbol][side] += size
        
        # Get risk alerts from risk controller
        alerts = []
        if risk_controller:
            # Check if kill switch is active
            if not risk_controller.can_trade():
                alerts.append({
                    "id": "kill_switch_active",
                    "metric": "trading_enabled",
                    "value": 0,
                    "threshold": 1,
                    "severity": "CRITICAL",
                    "createdAt": risk_controller.kill_switch_triggered_at.isoformat() if hasattr(risk_controller, 'kill_switch_triggered_at') else ""
                })
            
            # Check daily loss limit
            daily_pnl = risk_controller.daily_pnl if hasattr(risk_controller, 'daily_pnl') else 0
            daily_loss_limit = risk_controller.daily_loss_limit if hasattr(risk_controller, 'daily_loss_limit') else -1000
            if daily_pnl < daily_loss_limit * 0.8:  # 80% of limit
                alerts.append({
                    "id": "daily_loss_warning",
                    "metric": "daily_pnl",
                    "value": daily_pnl,
                    "threshold": daily_loss_limit,
                    "severity": "HIGH" if daily_pnl < daily_loss_limit else "MEDIUM",
                    "createdAt": ""
                })
        
        # Check drawdown alerts
        if current_drawdown > 15:
            alerts.append({
                "id": "drawdown_warning",
                "metric": "drawdown",
                "value": current_drawdown,
                "threshold": 15.0,
                "severity": "HIGH" if current_drawdown > 20 else "MEDIUM",
                "createdAt": ""
            })
        
        # Check margin utilization
        margin_total = margin_used + margin_available
        margin_util_pct = (margin_used / margin_total * 100) if margin_total > 0 else 0
        if margin_util_pct > 80:
            alerts.append({
                "id": "margin_utilization_warning",
                "metric": "margin_utilization",
                "value": margin_util_pct,
                "threshold": 80.0,
                "severity": "HIGH" if margin_util_pct > 90 else "MEDIUM",
                "createdAt": ""
            })
        
        return {
            "totalPnL": total_pnl,
            "dailyDrawdown": current_drawdown,
            "maxDrawdown": current_drawdown,  # Simplified - would track historical max
            "marginUsed": margin_used,
            "marginAvailable": margin_available,
            "exposure": exposure,
            "alerts": alerts
        }
        
    except Exception as e:
        logger.error(f"Failed to get risk metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/protections")
async def get_risk_protections() -> Dict[str, Any]:
    """
    Get current risk protection settings and status.
    
    Returns:
        {
            "killSwitchActive": bool,
            "dailyLossLimit": float,
            "dailyPnL": float,
            "maxDrawdownLimit": float,
            "currentDrawdown": float,
            "maxPositionSize": float,
            "maxLeverage": int
        }
    """
    try:
        # Risk controller not available - return defaults
        risk_controller = None
        
        if not risk_controller:
            return {
                "killSwitchActive": False,
                "dailyLossLimit": -1000.0,
                "dailyPnL": 0.0,
                "maxDrawdownLimit": 20.0,
                "currentDrawdown": 0.0,
                "maxPositionSize": 5000.0,
                "maxLeverage": 10
            }
        
        return {
            "killSwitchActive": not risk_controller.can_trade(),
            "dailyLossLimit": getattr(risk_controller, 'daily_loss_limit', -1000.0),
            "dailyPnL": getattr(risk_controller, 'daily_pnl', 0.0),
            "maxDrawdownLimit": getattr(risk_controller, 'max_drawdown_limit', 20.0),
            "currentDrawdown": 0.0,  # Would calculate from portfolio
            "maxPositionSize": getattr(risk_controller, 'max_position_size', 5000.0),
            "maxLeverage": getattr(risk_controller, 'max_leverage', 10)
        }
        
    except Exception as e:
        logger.error(f"Failed to get risk protections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Trading Halt / Resume ────────────────────────────────────────────


def _get_coordinator():
    """Lazy import to avoid circular deps at module load."""
    from core.automated_risk_controls import get_risk_coordinator
    return get_risk_coordinator()


def _get_staleness_monitor():
    from core.feed_staleness_monitor import get_feed_staleness_monitor
    return get_feed_staleness_monitor()


@router.post("/halt")
async def halt_trading(req: HaltRequest) -> Dict[str, Any]:
    """Operator-initiated trading halt."""
    try:
        coord = _get_coordinator()
        changed = coord.halt_manager.halt(req.reason)
        return {
            "halted": coord.halt_manager.is_halted,
            "reason": coord.halt_manager.halt_reason,
            "changed": changed,
        }
    except Exception as e:
        logger.error(f"Halt trading error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume")
async def resume_trading(req: ResumeRequest) -> Dict[str, Any]:
    """Operator-initiated trading resume."""
    try:
        coord = _get_coordinator()
        changed = coord.halt_manager.resume(req.operator)
        return {
            "halted": coord.halt_manager.is_halted,
            "changed": changed,
        }
    except Exception as e:
        logger.error(f"Resume trading error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/halt-status")
async def get_halt_status() -> Dict[str, Any]:
    """Get current trading halt status including history."""
    try:
        coord = _get_coordinator()
        return {
            "can_trade": coord.can_trade(),
            **coord.halt_manager.get_status(),
        }
    except Exception as e:
        logger.error(f"Halt status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/staleness")
async def get_feed_staleness() -> Dict[str, Any]:
    """Get per-feed staleness summary and paused instruments."""
    try:
        monitor = _get_staleness_monitor()
        summary = monitor.get_summary()
        if summary.get("total_feeds", 0) > 0:
            return summary
    except Exception as e:
        logger.debug(f"Feed staleness monitor unavailable: {e}")

    # Fallback: derive staleness from Kalshi signal feeds + live price feed
    import time as _t
    now = _t.time()
    feeds_info: List[Dict[str, Any]] = []
    stale_count = 0
    paused: Dict[str, str] = {}
    max_age_sec = 120  # 2min stale threshold for Kalshi signals

    try:
        from merid.signals.kalshi import get_kalshi_signal_engine
        eng = get_kalshi_signal_engine()
        last_ts = getattr(eng, "last_signal_ts", 0) or 0
        age = now - last_ts if last_ts else 999
        is_stale = age > max_age_sec
        if is_stale:
            stale_count += 1
            paused["kalshi_signals"] = f"stale {age:.0f}s"
        feeds_info.append({"name": "kalshi_signals", "last_update": int(last_ts * 1000), "stale": is_stale, "max_age_ms": max_age_sec * 1000, "age_sec": round(age, 1)})
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    try:
        from merid.signals.live_feeds import get_live_feed_manager
        mgr = get_live_feed_manager()
        for name, last_ts in getattr(mgr, "last_ingest_ts", {}).items():
            age = now - last_ts if last_ts else 999
            is_stale = age > 300  # 5min for external feeds
            if is_stale:
                stale_count += 1
                paused[name] = f"stale {age:.0f}s"
            feeds_info.append({"name": name, "last_update": int(last_ts * 1000), "stale": is_stale, "max_age_ms": 300000, "age_sec": round(age, 1)})
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        grid = get_agent_grid()
        if grid:
            total_cycles = sum(1 for a in grid._agents)  # LeanAgentGrid15m uses _agents
            running = len(grid._agents)  # LeanAgentGrid15m doesn't have per-agent running state
            feeds_info.append({"name": "agent_grid", "last_update": int(now * 1000), "stale": running == 0, "max_age_ms": 120000, "age_sec": 0, "detail": f"{running}/{len(grid._agents)} agents, {total_cycles} total cycles"})
            if running == 0:
                stale_count += 1
                paused["agent_grid"] = "no running agents"
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    return {"total_feeds": len(feeds_info), "stale_count": stale_count, "paused_instruments": paused, "feeds": feeds_info}


@router.post("/alerts/acknowledge-all")
async def acknowledge_all_alerts() -> Dict[str, Any]:
    """Acknowledge all active risk alerts."""
    from datetime import datetime, timezone
    return {"acknowledged": True, "count": 0, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/agents")
async def get_risk_agents() -> Dict[str, Any]:
    """Per-agent risk metrics — exposure, drawdown, PnL."""
    try:
        coord = _get_coordinator()
        status = coord.get_comprehensive_risk_status()
        agents = status.get("agent_risk", {})
        if agents:
            return {"agents": agents, "count": len(agents)}
    except Exception as e:
        logger.debug(f"risk_agents coordinator unavailable: {e}")

    # Fallback: derive from agent grid
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid
        grid = get_agent_grid()
        agents_data: List[Dict[str, Any]] = []
        if grid:
            for agent in grid._agents:  # LeanAgentGrid15m uses _agents
                cfg = agent.config
                agents_data.append({
                    "agent_id": cfg.name,
                    "asset": cfg.series_tickers[0] if cfg.series_tickers else "",
                    "timeframe": "15m",  # LeanAgent15m is always 15m
                    "running": cfg.enabled,
                    "cycles": 0,  # LeanAgent15m doesn't track cycles
                    "orders_placed": 0,  # LeanAgent15m doesn't track orders
                    "pnl": 0.0,
                    "drawdown_pct": 0.0,
                    "exposure_usd": 0.0,
                    "win_rate": 0.0,
                    "risk_score": "low",
                })
        return {"agents": agents_data, "count": len(agents_data)}
    except Exception as e2:
        logger.warning(f"risk_agents fallback: {e2}")
        return {"agents": [], "count": 0}


@router.get("/summary")
async def get_risk_summary() -> Dict[str, Any]:
    """
    Consolidated risk summary: halt status, protections, staleness, exposure.
    Single endpoint for the operator dashboard.
    """
    try:
        coord = _get_coordinator()
        monitor = _get_staleness_monitor()

        halt_status = coord.halt_manager.get_status()
        staleness = monitor.get_summary()

        # Portfolio risk from coordinator
        risk_status = coord.get_comprehensive_risk_status()

        return {
            "can_trade": coord.can_trade(),
            "halt": halt_status,
            "staleness": staleness,
            "portfolio_risk": risk_status.get("portfolio_risk", {}),
            "active_stops": risk_status.get("active_stops", {}),
            "monitoring_active": risk_status.get("monitoring_active", False),
        }
    except Exception as e:
        logger.error(f"Risk summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Per-Agent Risk Endpoints (RISK_AGENT_* constants) ───────────────────


@router.get("/agents/{agent_id}/drawdown-history")
async def get_agent_drawdown_history(agent_id: str) -> Dict[str, Any]:
    """Get drawdown history for a specific agent."""
    try:
        from merid.risk.agent_metrics import get_agent_metrics_tracker
        tracker = get_agent_metrics_tracker()
        history = tracker.get_drawdown_history(agent_id, limit=100)
        return {
            "agent_id": agent_id,
            "history": history,
            "count": len(history),
        }
    except Exception as e:
        logger.error(f"Agent drawdown history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}/equity-history")
async def get_agent_equity_history(agent_id: str) -> Dict[str, Any]:
    """Get equity history for a specific agent."""
    try:
        from merid.risk.agent_metrics import get_agent_metrics_tracker
        tracker = get_agent_metrics_tracker()
        history = tracker.get_equity_history(agent_id, limit=100)
        return {
            "agent_id": agent_id,
            "history": history,
            "count": len(history),
        }
    except Exception as e:
        logger.error(f"Agent equity history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}/metrics")
async def get_agent_metrics(agent_id: str) -> Dict[str, Any]:
    """Get detailed risk metrics for a specific agent."""
    try:
        from merid.risk.agent_metrics import get_agent_metrics_tracker
        tracker = get_agent_metrics_tracker()
        agent = tracker.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        return agent.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent metrics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
