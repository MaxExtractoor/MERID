"""
Swarm API Routes

FastAPI endpoints for swarm health, stats, and monitoring.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Optional

from observability.swarm_telemetry import get_swarm_telemetry
from execution.execution_coordinator import get_execution_coordinator
# LEGACY REMOVAL: consensus.consensus_coordinator import removed - consensus module deleted
# from consensus.consensus_coordinator import get_consensus_coordinator
from agents.watchdog_agents import get_watchdog_coordinator
from schemas.swarm_events import TradingMode
from utils.logger import get_logger
from web.api.auth import get_current_session

logger = get_logger("web.api.swarm")

router = APIRouter(prefix="/api/v1/swarm", tags=["swarm"], dependencies=[Depends(get_current_session)])  # ZT6-01


@router.get("/stats")
async def get_swarm_stats() -> Dict:
    """
    Get current swarm statistics and health metrics.
    
    Returns:
        - swarm: Aggregate swarm metrics
        - agents: Per-agent health data
        - health_issues: Current health problems
    """
    try:
        telemetry = get_swarm_telemetry()
        stats = telemetry.get_stats_dict()
        swarm = stats.get("swarm", {})
        
        return {
            "swarm": {
                "active_agents": swarm.get("active_agents", 0),
                "total_agents": swarm.get("total_agents", 0),
                "participation_rate": swarm.get("participation_rate", 0.0),
                "opinions_per_minute": swarm.get("opinions_per_minute", 0.0),
                "consensus_per_minute": swarm.get("consensus_per_minute", 0.0),
                "consensus_success_rate": swarm.get("consensus_success_rate", 0.0),
                "avg_disagreement_rate": swarm.get("disagreement_rate", 0.0),
                "high_disagreement_count": 0,
                "pipeline_latency_ms": swarm.get("avg_pipeline_latency_ms", 0),
            },
            "agents": stats.get("agents", []),
            "health_issues": stats.get("health_issues", {}),
        }
    
    except Exception as e:
        logger.error(f"Failed to get swarm stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def get_swarm_health() -> Dict:
    """
    Get swarm health status.
    
    Returns overall health and any critical issues.
    """
    try:
        telemetry = get_swarm_telemetry()
        stats = telemetry.get_stats_dict()
        swarm = stats.get("swarm", {})
        
        # Determine overall health
        health_issues = stats.get("health_issues", {})
        critical_issues = [
            issue for issue in health_issues.values()
            if isinstance(issue, str) and ("critical" in issue.lower() or "offline" in issue.lower())
        ]
        
        if critical_issues:
            status = "critical"
        elif health_issues:
            status = "degraded"
        else:
            status = "healthy"
        
        return {
            "status": status,
            "active_agents": swarm.get("active_agents", 0),
            "total_agents": swarm.get("total_agents", 0),
            "participation_rate": swarm.get("participation_rate", 0.0),
            "issues": health_issues,
            "critical_count": len(critical_issues),
            "timestamp": time.time(),
        }
    
    except Exception as e:
        logger.error(f"Failed to get swarm health: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/execution/stats")
async def get_execution_stats() -> Dict:
    """
    Get execution coordinator statistics.
    
    Returns pending and executed trade counts.
    """
    try:
        execution = get_execution_coordinator()
        stats = execution.get_stats()
        
        return {
            "mode": stats.get("mode", "unknown"),
            "pending_trades": stats.get("pending_trades", 0),
            "executed_trades": stats.get("executed_trades", 0),
            "risk_checks_enabled": stats.get("risk_checks_enabled", False),
        }
    
    except Exception as e:
        logger.error(f"Failed to get execution stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consensus/stats")
async def get_consensus_stats() -> Dict:
    """
    Get consensus coordinator statistics.
    
    Returns consensus round counts and success rates.
    """
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.debug("Consensus stats disabled - consensus module deleted")
    return {
        "total_rounds": 0,
        "successful_rounds": 0,
        "timeout_rounds": 0,
        "vetoed_rounds": 0,
        "active_rounds": 0,
        "pending_opinions": 0,
        "message": "Consensus module deleted"
    }


@router.get("/watchdog/alerts")
async def get_watchdog_alerts() -> Dict:
    """
    Get recent watchdog alerts.
    
    Returns list of recent alerts from monitoring agents.
    """
    try:
        # This would need to be implemented in watchdog_agents.py
        # For now, return empty
        return {
            "alerts": [],
            "critical_count": 0,
            "warning_count": 0,
            "info_count": 0,
        }
    
    except Exception as e:
        logger.error(f"Failed to get watchdog alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mode")
async def get_trading_mode() -> Dict:
    """
    Get current trading mode.
    
    Returns the active trading mode (simulation/paper/live).
    """
    try:
        # Get from execution coordinator
        execution = get_execution_coordinator()
        stats = execution.get_stats()
        
        return {
            "mode": stats.get("mode", "simulation"),
            "live_authorized": stats.get("mode") == "live",
            "risk_checks_enabled": stats.get("risk_checks_enabled", False),
        }
    
    except Exception as e:
        logger.error(f"Failed to get trading mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/prometheus")
async def get_prometheus_metrics() -> str:
    """
    Get Prometheus-formatted metrics export.
    
    Returns metrics in Prometheus text format.
    """
    try:
        telemetry = get_swarm_telemetry()
        metrics = telemetry.get_prometheus_metrics()
        
        return metrics
    
    except Exception as e:
        logger.error(f"Failed to get Prometheus metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
