"""
Health endpoints for unified signal system daemons

Provides simple health checks for systemd/Docker monitoring
and operational status tracking.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import time

from utils.logger import get_logger

logger = get_logger("signals.health")

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/signals-daemon")
async def signals_daemon_health():
    """Health check for signals daemon"""
    try:
        from merid.signals.unified_orchestrator import get_unified_orchestrator
        
        orchestrator = get_unified_orchestrator()
        
        # Get recent processing results
        recent_results = orchestrator._processing_history[-5:] if orchestrator._processing_history else []
        last_run = recent_results[-1] if recent_results else None
        
        # Calculate health metrics
        current_time = time.time()
        last_run_time = last_run.timestamp if last_run else 0
        time_since_last_run = current_time - last_run_time
        
        # Health status based on recent activity
        is_healthy = (
            time_since_last_run < 300 and  # Last run within 5 minutes
            len(recent_results) > 0 and     # Have some history
            len(last_run.errors) < 5        # Not too many errors
        )
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": current_time,
            "last_run": last_run_time,
            "time_since_last_run_seconds": time_since_last_run,
            "recent_runs": len(recent_results),
            "last_run_errors": len(last_run.errors) if last_run else 0,
            "components": {
                "crypto_features": orchestrator._config.enable_crypto_features,
                "debate_integration": orchestrator._config.enable_debate_integration,
                "sentiment_integration": orchestrator._config.enable_sentiment_integration,
                "kalshi_generation": orchestrator._config.enable_kalshi_generation,
                "cqi_gating": orchestrator._config.enable_cqi_gating,
            }
        }
        
    except Exception as e:
        logger.error(f"Signals daemon health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": time.time(),
            "error": str(e)
        }


@router.get("/execution-daemon")
async def execution_daemon_health():
    """Health check for execution daemon"""
    try:
        from merid.signals.execution_bridge import get_signal_execution_bridge
        
        bridge = get_signal_execution_bridge()
        stats = bridge.get_execution_stats()
        
        # Calculate health metrics
        current_time = time.time()
        last_execution = bridge._execution_history[-1] if bridge._execution_history else None
        last_execution_time = last_execution.get("timestamp", 0) if last_execution else 0
        time_since_last_execution = current_time - last_execution_time
        
        # Health status based on recent activity
        is_healthy = (
            time_since_last_execution < 600 and  # Last execution within 10 minutes
            stats["total_executions"] >= 0        # Have execution history
        )
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": current_time,
            "last_execution": last_execution_time,
            "time_since_last_execution_seconds": time_since_last_execution,
            "execution_stats": stats,
            "config": {
                "min_confidence": bridge._config.min_confidence,
                "min_strength": bridge._config.min_strength,
                "max_notional": bridge._config.max_notional,
                "lookback_minutes": bridge._config.lookback_minutes,
            }
        }
        
    except Exception as e:
        logger.error(f"Execution daemon health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": time.time(),
            "error": str(e)
        }


@router.get("/system")
async def system_health():
    """Overall system health check"""
    try:
        signals_health = await signals_daemon_health()
        execution_health = await execution_daemon_health()
        
        # Overall system health
        signals_healthy = signals_health.get("status") == "healthy"
        execution_healthy = execution_health.get("status") == "healthy"
        
        overall_healthy = signals_healthy and execution_healthy
        
        return {
            "status": "healthy" if overall_healthy else "degraded",
            "timestamp": time.time(),
            "components": {
                "signals_daemon": signals_health,
                "execution_daemon": execution_health,
            },
            "summary": {
                "signals_healthy": signals_healthy,
                "execution_healthy": execution_healthy,
                "overall_healthy": overall_healthy,
            }
        }
        
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": time.time(),
            "error": str(e)
        }
