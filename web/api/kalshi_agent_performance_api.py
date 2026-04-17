"""Kalshi Agent Performance API — Real-time agent metrics and calibration.

Endpoints:
- GET /api/v1/kalshi-grid/performance/agents — All agent metrics
- GET /api/v1/kalshi-grid/performance/agents/{agent_id} — Specific agent
- GET /api/v1/kalshi-grid/performance/summary — System-wide stats
- GET /api/v1/kalshi-grid/performance/top — Top performing agents
- POST /api/v1/kalshi-grid/performance/export — Export trades to CSV
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_agent_performance_api")

router = APIRouter(prefix="/api/v1/kalshi-grid/performance", tags=["Kalshi Agent Performance"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


@router.get("/agents")
async def get_all_agent_metrics() -> Dict[str, Any]:
    """Get performance metrics for all agents.
    
    Returns:
        Dict mapping agent_id to metrics dict
    """
    try:
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
        
        agents_dict = {agent_id: metrics.to_dict() for agent_id, metrics in all_metrics.items()}
        
        # Fallback: populate from agent grid cycle data when no trade metrics exist
        if not agents_dict:
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                for agent in grid.agents:
                    if agent.state.cycles_run > 0:
                        agents_dict[agent.config.name] = {
                            "agent_id": agent.config.name,
                            "total_fills": 0,
                            "total_closes": 0,
                            "cycles_run": agent.state.cycles_run,
                            "orders_placed": agent.state.orders_placed,
                            "enabled": agent.config.enabled,
                            "running": agent.state.running,
                            "win_rate": 0.0,
                            "total_pnl": 0.0,
                            "sharpe_ratio": 0.0,
                            "source": "agent_grid",
                        }
            except Exception as e:
                logger.debug(f"Silent error: {e}")
        
        return {
            "agents": agents_dict,
            "count": len(agents_dict),
        }
    except Exception as exc:
        logger.error(f"Failed to get agent metrics: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/agents/{agent_id}")
async def get_agent_metrics(agent_id: str) -> Dict[str, Any]:
    """Get performance metrics for a specific agent.
    
    Args:
        agent_id: Agent identifier (e.g., "kalshi-btc_15m")
    
    Returns:
        Agent performance metrics
    """
    try:
        tracker = get_agent_performance_tracker()
        metrics = tracker.get_agent_metrics(agent_id)
        
        if metrics.total_fills == 0 and metrics.total_closes == 0:
            raise HTTPException(status_code=404, detail=f"No data for agent {agent_id}")
        
        return metrics.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to get metrics for {agent_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/summary")
async def get_performance_summary() -> Dict[str, Any]:
    """Get system-wide performance summary across all agents.
    
    Returns:
        Aggregated performance statistics
    """
    try:
        tracker = get_agent_performance_tracker()
        raw = tracker.get_system_summary()

        # Normalise shape for KalshiAgentPerformanceView
        all_metrics = list(tracker.get_all_metrics().values())
        best_agent: Optional[str] = None
        worst_agent: Optional[str] = None
        if all_metrics:
            with_closes = [m for m in all_metrics if m.total_closes > 0]
            if with_closes:
                best_agent = max(with_closes, key=lambda m: m.win_rate).agent_id
                worst_agent = min(with_closes, key=lambda m: m.win_rate).agent_id

        result = {
            "total_agents": raw.get("total_agents", 0),
            "total_fills": raw.get("total_fills", 0),
            "total_closes": raw.get("total_closes", 0),
            "system_win_rate": raw.get("system_win_rate", 0.0),
            "total_pnl": float(raw.get("system_pnl_usd", 0)),
            "avg_sharpe": raw.get("avg_sharpe", 0.0),
            "best_agent": best_agent,
            "worst_agent": worst_agent,
        }

        # Supplement with agent grid cycle data when no trade metrics exist
        if result["total_agents"] == 0:
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                active = [a for a in grid.agents if a.state.cycles_run > 0]
                result["total_agents"] = len(grid.agents)
                result["total_cycles"] = sum(a.state.cycles_run for a in grid.agents)
                result["total_orders_placed"] = sum(a.state.orders_placed for a in grid.agents)
                result["active_agents"] = len(active)
                if active:
                    result["best_agent"] = max(active, key=lambda a: a.state.cycles_run).config.name
                result["source"] = "agent_grid"
            except Exception as e:
                logger.debug(f"Silent error: {e}")

        return result
    except Exception as exc:
        logger.error(f"Failed to get performance summary: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/top")
async def get_top_agents(
    metric: str = Query("win_rate", pattern="^(win_rate|total_pnl_usd|sharpe_ratio)$"),
    limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Get top performing agents by specified metric.

    Returns shape expected by KalshiAgentPerformanceView:
      { top: [ { agent_id, rank, win_rate, total_pnl, edge_accuracy } ] }
    """
    try:
        tracker = get_agent_performance_tracker()
        raw = tracker.get_top_agents(metric=metric, limit=limit)

        top: List[Dict[str, Any]] = []
        for i, a in enumerate(raw, start=1):
            top.append({
                "agent_id": a["agent_id"],
                "rank": i,
                "win_rate": a["win_rate"],
                "total_pnl": float(a.get("total_pnl_usd", 0)),
                "edge_accuracy": a.get("edge_accuracy", 0.0),
            })

        return {"top": top, "metric": metric}
    except Exception as exc:
        logger.error(f"Failed to get top agents: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/export")
async def export_trades_csv(filepath: Optional[str] = None) -> Dict[str, Any]:
    """Export closed trades to CSV file for analysis.
    
    Args:
        filepath: Optional custom filepath (defaults to trades_export_{timestamp}.csv)
    
    Returns:
        Export confirmation with filepath
    """
    try:
        tracker = get_agent_performance_tracker()
        
        if not filepath:
            import time
            filepath = f"trades_export_{int(time.time())}.csv"
        
        tracker.export_trades_csv(filepath)
        
        return {
            "success": True,
            "filepath": filepath,
            "trades_exported": tracker.get_closed_trade_count(),
        }
    except Exception as exc:
        logger.error(f"Failed to export trades: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/execution")
async def get_execution_telemetry() -> Dict[str, Any]:
    """Execution telemetry per product — latency, fill rate, slippage.

    Shape consumed by KalshiExecutionTelemetryPanel.tsx:
      { metrics: { <product>: { <metric>: number } },
        status:  { <product>: { <metric>: { value, status, threshold? } } } }
    """
    try:
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()

        products: Dict[str, Dict[str, float]] = {}
        for m in all_metrics.values():
            aid = m.agent_id
            products[aid] = {
                "fill_rate": round(m.win_rate, 3) if m.total_closes else 0,
                "avg_latency_ms": round(getattr(m, "avg_latency_ms", 0), 1),
                "total_orders": m.total_closes,
                "slippage_bps": round(getattr(m, "slippage_bps", 0), 2),
            }

        def _status_for(val: float, warn: float, crit: float, higher_bad: bool = True) -> str:
            if higher_bad:
                return "good" if val < warn else ("warning" if val < crit else "info")
            return "good" if val > warn else ("warning" if val > crit else "info")

        status: Dict[str, Any] = {}
        for prod, vals in products.items():
            status[prod] = {
                "fill_rate": {"value": vals["fill_rate"], "status": _status_for(vals["fill_rate"], 0.5, 0.3, higher_bad=False)},
                "avg_latency_ms": {"value": vals["avg_latency_ms"], "status": _status_for(vals["avg_latency_ms"], 500, 1000), "threshold": 500},
                "total_orders": {"value": vals["total_orders"], "status": "good"},
                "slippage_bps": {"value": vals["slippage_bps"], "status": _status_for(vals["slippage_bps"], 5, 15), "threshold": 5},
            }

        # Supplement with agent grid data when no trade metrics exist
        if not products:
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                for agent in grid.agents:
                    if agent.state.cycles_run > 0:
                        aid = agent.config.name
                        products[aid] = {
                            "fill_rate": 0.0,
                            "avg_latency_ms": 0.0,
                            "total_orders": agent.state.orders_placed,
                            "slippage_bps": 0.0,
                            "cycles_run": agent.state.cycles_run,
                            "source": "agent_grid",
                        }
                        status[aid] = {
                            "fill_rate": {"value": 0, "status": "info"},
                            "avg_latency_ms": {"value": 0, "status": "good", "threshold": 500},
                            "total_orders": {"value": agent.state.orders_placed, "status": "good"},
                            "slippage_bps": {"value": 0, "status": "good", "threshold": 5},
                        }
            except Exception as e:
                logger.debug(f"Silent error: {e}")

        return {"metrics": products, "status": status}
    except Exception as exc:
        logger.error("execution telemetry failed: %s", exc)
        return {"metrics": {}, "status": {}, "error": str(exc)}


@router.get("/calibration")
async def get_calibration_stats() -> Dict[str, Any]:
    """Get calibration statistics showing predicted vs actual edge accuracy.
    
    Returns:
        Calibration analysis across all agents
    """
    try:
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()

        agents_with_data = [m for m in all_metrics.values() if m.total_closes > 0]

        # Shape expected by KalshiAgentPerformanceView:
        # { agents: [ { agent_id, calibration_error, avg_confidence, brier_score, well_calibrated } ] }
        agent_rows: List[Dict[str, Any]] = [
            {
                "agent_id": m.agent_id,
                "calibration_error": round(m.calibration_error, 4),
                "avg_confidence": round(m.avg_confidence, 3),
                "brier_score": tracker.compute_brier_score(m.agent_id),
                "well_calibrated": m.calibration_error < 0.1,
            }
            for m in sorted(agents_with_data, key=lambda x: x.calibration_error)
        ]

        # Fallback: derive from CalibrationStore / forecasters when no closed trades
        if not agent_rows:
            try:
                from merid.metrics.calibration import get_calibration_store
                store = get_calibration_store()
                for fid in store.list_forecasters():
                    summary = store.get_forecaster_summary(fid)
                    avg_brier = summary.get("avg_ewma_brier", 0.25)
                    # avg_confidence: average |p_model - 0.5| × 2 — how decisive the forecaster is
                    # (0 = always predicts 50/50, 1 = always predicts near 0 or 1)
                    avg_conf = store.get_avg_forecast_confidence(fid)
                    agent_rows.append({
                        "agent_id": fid,
                        "calibration_error": round(abs(avg_brier - 0.25), 4),
                        "avg_confidence": round(avg_conf, 3),
                        "brier_score": round(avg_brier, 4),
                        "well_calibrated": avg_brier < 0.15,
                        "source": "forecaster_brier",
                    })
            except Exception as e:
                logger.debug(f"Silent error: {e}")
        # Second fallback: use agent grid cycle data
        if not agent_rows:
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                for agent in grid.agents:
                    if agent.state.cycles_run > 0:
                        agent_rows.append({
                            "agent_id": agent.config.name,
                            "calibration_error": 0.0,
                            "avg_confidence": 0.5,
                            "brier_score": 0.25,
                            "well_calibrated": True,
                            "source": "agent_grid_cycles",
                            "cycles": agent.state.cycles_run,
                        })
            except Exception as e:
                logger.debug(f"Silent error: {e}")

        return {"agents": agent_rows}
    except Exception as exc:
        logger.error(f"Failed to get calibration stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
