"""Kalshi Agent Performance API — Real-time agent metrics and calibration.

Endpoints:
- GET /api/v1/kalshi-grid/performance/agents — All agent metrics
- GET /api/v1/kalshi-grid/performance/agents/{agent_id} — Specific agent
- GET /api/v1/kalshi-grid/performance/summary — System-wide stats
- GET /api/v1/kalshi-grid/performance/top — Top performing agents
- POST /api/v1/kalshi-grid/performance/export — Export trades to CSV
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_agent_performance_api")

router = APIRouter(prefix="/api/v1/kalshi-grid/performance", tags=["Kalshi Agent Performance"])


@router.get("/agents")
async def get_all_agent_metrics() -> Dict[str, Any]:
    """Get performance metrics for all agents.
    
    Returns:
        Dict mapping agent_id to metrics dict
    """
    try:
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
        
        return {
            "agents": {agent_id: metrics.to_dict() for agent_id, metrics in all_metrics.items()},
            "count": len(all_metrics),
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

        return {
            "total_agents": raw.get("total_agents", 0),
            "total_fills": raw.get("total_fills", 0),
            "total_closes": raw.get("total_closes", 0),
            "system_win_rate": raw.get("system_win_rate", 0.0),
            "total_pnl": float(raw.get("system_pnl_usd", 0)),
            "avg_sharpe": raw.get("avg_sharpe", 0.0),
            "best_agent": best_agent,
            "worst_agent": worst_agent,
        }
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

        return {"agents": agent_rows}
    except Exception as exc:
        logger.error(f"Failed to get calibration stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
