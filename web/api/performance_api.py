"""
Performance Monitoring API for 15m Loop

Phase 4.4: Add performance monitoring and metrics

This module provides API endpoints for monitoring the performance
of the Kalshi 15m trading loop, including:
- Real-time cycle metrics
- Performance summaries
- Bottleneck analysis
- System health indicators
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from utils.logger import get_logger

logger = get_logger("web.performance_api")

# Create router
performance_router = APIRouter(prefix="/api/v1/performance", tags=["performance"])


class CycleMetricsResponse(BaseModel):
    """Response model for cycle metrics."""
    cycle_id: int
    duration_ms: float
    agent_processing_ms: float
    market_scanning_ms: float
    order_submission_ms: float
    risk_check_ms: float
    memory_usage_mb: float
    cpu_percent: float
    warnings: List[str] = Field(default_factory=list)
    timestamp: str


class PerformanceSummaryResponse(BaseModel):
    """Response model for performance summary."""
    total_cycles: int
    avg_cycle_duration_ms: float
    p95_cycle_duration_ms: float
    p99_cycle_duration_ms: float
    max_cycle_duration_ms: float
    min_cycle_duration_ms: float
    avg_memory_usage_mb: float
    max_memory_usage_mb: float
    avg_cpu_percent: float
    max_cpu_percent: float
    error_rate: float
    bottleneck_phase: str
    recommendations: List[str] = Field(default_factory=list)
    timestamp: str


class PerformanceExportResponse(BaseModel):
    """Response model for performance export."""
    summary: PerformanceSummaryResponse
    recent_cycles: List[CycleMetricsResponse]
    timestamp: str


class SystemHealthResponse(BaseModel):
    """Response model for system health."""
    loop_running: bool
    last_cycle_ts: Optional[str]
    last_cycle_duration_ms: Optional[float]
    error_count: int
    uptime_seconds: float
    memory_usage_mb: float
    cpu_percent: float
    status: str  # "healthy", "degraded", "critical"


@performance_router.get("/summary", response_model=PerformanceSummaryResponse)
async def get_performance_summary():
    """
    Get aggregated performance summary for the 15m loop.
    
    Returns:
        Performance summary with statistics and recommendations
    """
    try:
        from merid.performance.loop_profiler import get_loop_profiler
        
        profiler = get_loop_profiler()
        summary = profiler.get_performance_summary()
        
        return PerformanceSummaryResponse(
            total_cycles=summary.total_cycles,
            avg_cycle_duration_ms=summary.avg_cycle_duration_ms,
            p95_cycle_duration_ms=summary.p95_cycle_duration_ms,
            p99_cycle_duration_ms=summary.p99_cycle_duration_ms,
            max_cycle_duration_ms=summary.max_cycle_duration_ms,
            min_cycle_duration_ms=summary.min_cycle_duration_ms,
            avg_memory_usage_mb=summary.avg_memory_usage_mb,
            max_memory_usage_mb=summary.max_memory_usage_mb,
            avg_cpu_percent=summary.avg_cpu_percent,
            max_cpu_percent=summary.max_cpu_percent,
            error_rate=summary.error_rate,
            bottleneck_phase=summary.bottleneck_phase,
            recommendations=summary.recommendations,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to get performance summary: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get performance summary: {str(e)}")


@performance_router.get("/cycles", response_model=List[CycleMetricsResponse])
async def get_recent_cycles(
    count: int = Query(default=10, ge=1, le=100, description="Number of recent cycles to return")
):
    """
    Get metrics for recent cycles.
    
    Args:
        count: Number of recent cycles to return (1-100)
    
    Returns:
        List of cycle metrics
    """
    try:
        from merid.performance.loop_profiler import get_loop_profiler
        
        profiler = get_loop_profiler()
        cycles = profiler.get_recent_cycles(count)
        
        return [
            CycleMetricsResponse(
                cycle_id=cycle.cycle_id,
                duration_ms=cycle.duration_ms,
                agent_processing_ms=cycle.agent_processing_ms,
                market_scanning_ms=cycle.market_scanning_ms,
                order_submission_ms=cycle.order_submission_ms,
                risk_check_ms=cycle.risk_check_ms,
                memory_usage_mb=cycle.memory_usage_mb,
                cpu_percent=cycle.cpu_percent,
                warnings=cycle.warnings,
                timestamp=datetime.fromtimestamp(cycle.start_time, timezone.utc).isoformat()
            )
            for cycle in cycles
        ]
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to get recent cycles: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get recent cycles: {str(e)}")


@performance_router.get("/export", response_model=PerformanceExportResponse)
async def export_performance_data():
    """
    Export performance data for external monitoring.
    
    Returns:
        Complete performance data export
    """
    try:
        from merid.performance.loop_profiler import get_loop_profiler
        
        profiler = get_loop_profiler()
        data = profiler.export_metrics()
        
        # Convert summary
        summary_data = data["summary"]
        summary = PerformanceSummaryResponse(
            total_cycles=summary_data["total_cycles"],
            avg_cycle_duration_ms=summary_data["avg_duration_ms"],
            p95_cycle_duration_ms=summary_data["p95_duration_ms"],
            p99_cycle_duration_ms=summary_data["p99_duration_ms"],
            max_cycle_duration_ms=summary_data["max_duration_ms"],
            min_cycle_duration_ms=summary_data["min_duration_ms"],
            avg_memory_usage_mb=summary_data["avg_memory_mb"],
            max_memory_usage_mb=summary_data["max_memory_mb"],
            avg_cpu_percent=summary_data["avg_cpu_percent"],
            max_cpu_percent=summary_data["max_cpu_percent"],
            error_rate=summary_data["error_rate"],
            bottleneck_phase=summary_data["bottleneck_phase"],
            recommendations=summary_data["recommendations"],
            timestamp=data["timestamp"]
        )
        
        # Convert recent cycles
        recent_cycles = []
        for cycle_data in data["recent_cycles"]:
            recent_cycles.append(CycleMetricsResponse(
                cycle_id=cycle_data["cycle_id"],
                duration_ms=cycle_data["duration_ms"],
                agent_processing_ms=cycle_data["agent_processing_ms"],
                market_scanning_ms=cycle_data["market_scanning_ms"],
                order_submission_ms=cycle_data["order_submission_ms"],
                risk_check_ms=cycle_data["risk_check_ms"],
                memory_mb=cycle_data["memory_mb"],
                cpu_percent=cycle_data["cpu_percent"],
                warnings=cycle_data["warnings"],
                timestamp=data["timestamp"]
            ))
        
        return PerformanceExportResponse(
            summary=summary,
            recent_cycles=recent_cycles,
            timestamp=data["timestamp"]
        )
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to export performance data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to export performance data: {str(e)}")


@performance_router.get("/health", response_model=SystemHealthResponse)
async def get_system_health():
    """
    Get system health indicators.
    
    Returns:
        System health status
    """
    try:
        from merid.performance.loop_profiler import get_loop_profiler
        import psutil
        
        profiler = get_loop_profiler()
        cycles = profiler.get_recent_cycles(1)
        
        # Get loop status from main_15m_lean if available
        loop_running = False
        last_cycle_ts = None
        last_cycle_duration_ms = None
        error_count = 0
        uptime_seconds = 0.0
        
        try:
            # Try to get loop status from main_15m_lean app state
            # This would require access to the FastAPI app state
            # For now, we'll infer from recent cycles
            if cycles:
                loop_running = True
                last_cycle = cycles[0]
                last_cycle_ts = datetime.fromtimestamp(last_cycle.start_time, timezone.utc).isoformat()
                last_cycle_duration_ms = last_cycle.duration_ms
                error_count = last_cycle.error_count
                uptime_seconds = 0.0  # Would need to be tracked separately
        except Exception:
            pass
        
        # Get system metrics
        process = psutil.Process()
        memory_usage_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent()
        
        # Determine health status
        status = "healthy"
        if last_cycle_duration_ms and last_cycle_duration_ms > 2000:  # 2 seconds
            status = "degraded"
        if last_cycle_duration_ms and last_cycle_duration_ms > 5000:  # 5 seconds
            status = "critical"
        if error_count > 0:
            status = "degraded"
        if memory_usage_mb > 1000:  # 1GB
            status = "degraded"
        if cpu_percent > 90:
            status = "critical"
        
        return SystemHealthResponse(
            loop_running=loop_running,
            last_cycle_ts=last_cycle_ts,
            last_cycle_duration_ms=last_cycle_duration_ms,
            error_count=error_count,
            uptime_seconds=uptime_seconds,
            memory_usage_mb=memory_usage_mb,
            cpu_percent=cpu_percent,
            status=status
        )
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to get system health: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get system health: {str(e)}")


@performance_router.post("/reset")
async def reset_performance_data():
    """
    Reset performance history.
    
    Returns:
        Success confirmation
    """
    try:
        from merid.performance.loop_profiler import reset_loop_profiler
        
        reset_loop_profiler()
        
        return {"message": "Performance data reset successfully", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to reset performance data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reset performance data: {str(e)}")


@performance_router.post("/profiler/{action}")
async def control_profiler(action: str):
    """
    Control the profiler state.
    
    Args:
        action: Action to perform ("enable" or "disable")
    
    Returns:
        Success confirmation
    """
    try:
        from merid.performance.loop_profiler import get_loop_profiler
        
        profiler = get_loop_profiler()
        
        if action == "enable":
            profiler.enable()
            message = "Profiler enabled"
        elif action == "disable":
            profiler.disable()
            message = "Profiler disabled"
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Use 'enable' or 'disable'")
        
        return {"message": message, "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error("[PERFORMANCE-API] Failed to control profiler: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to control profiler: {str(e)}")
