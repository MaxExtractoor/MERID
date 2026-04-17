"""
SLO Monitoring API Endpoints
Provides SLO status, metrics, and compliance reporting for MERID services.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from core.slo_monitor import get_slo_monitor, SLOStatus
from web.api.auth import get_current_session

router = APIRouter(prefix="/api/v1/slo", tags=["slo"], dependencies=[Depends(get_current_session)])  # ZT6-01


# ── Response Models ────────────────────────────────────────────────────────

class SLOMetricResponse(BaseModel):
    """SLO metric response."""
    name: str
    description: str
    target_percent: float
    current_percent: float
    status: str
    window_minutes: int
    last_updated: datetime


class SLOResultResponse(BaseModel):
    """SLO evaluation result response."""
    slo_name: str
    status: str
    success_rate: float
    success_count: int
    total_count: int
    window_start: datetime
    window_end: datetime
    violation_count: int


class ViolationResponse(BaseModel):
    """SLO violation detail."""
    slo_name: str
    timestamp: datetime
    metadata: Dict


class SLOSummaryResponse(BaseModel):
    """Comprehensive SLO summary response."""
    overall_status: str
    evaluation_time: datetime
    slos: Dict[str, SLOResultResponse]
    recent_violations: List[ViolationResponse]


# ── API Endpoints ────────────────────────────────────────────────────────

@router.get("/status", response_model=SLOSummaryResponse)
async def get_slo_status():
    """
    Get comprehensive SLO status across all metrics.
    
    Returns overall compliance status and detailed metrics for:
    - API availability and latency
    - Order execution success rates  
    - Data freshness and completeness
    - System health and responsiveness
    """
    try:
        slo_monitor = get_slo_monitor()
        summary = slo_monitor.get_slo_summary()
        
        # Convert datetime objects safely
        raw_time = summary["evaluation_time"]
        if isinstance(raw_time, datetime):
            evaluation_time = raw_time
        else:
            evaluation_time = datetime.fromisoformat(raw_time)
        
        # Convert SLO results
        slos = {}
        for name, slo_data in summary["slos"].items():
            violation_count = (
                len(slo_data["violations"])
                if isinstance(slo_data.get("violations"), list)
                else int(slo_data.get("violations", 0))
            )
            
            slos[name] = SLOResultResponse(
                slo_name=name,
                status=slo_data["status"],
                success_rate=slo_data["success_rate"],
                success_count=slo_data["success_count"],
                total_count=slo_data["total_count"],
                window_start=datetime.now(timezone.utc),  # Would be calculated from actual window
                window_end=datetime.now(timezone.utc),
                violation_count=violation_count)
        
        # Convert recent violations
        recent_violations = []
        for violation in summary["recent_violations"]:
            recent_violations.append(ViolationResponse(
                slo_name=violation["slo_name"],
                timestamp=datetime.fromtimestamp(violation["timestamp"], tz=timezone.utc),
                metadata=violation["metadata"]
            ))
        
        return SLOSummaryResponse(
            overall_status=summary["overall_status"],
            evaluation_time=evaluation_time,
            slos=slos,
            recent_violations=recent_violations
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SLO status retrieval failed: {str(e)}")


@router.get("/metrics", response_model=List[SLOMetricResponse])
async def get_slo_metrics():
    """
    Get current SLO metric definitions and their latest values.
    
    Returns all configured SLOs with their current compliance status
    and target thresholds.
    """
    try:
        slo_monitor = get_slo_monitor()
        results = slo_monitor.evaluate_all_slos()
        
        metrics = []
        for slo_name, slo_metric in slo_monitor.slos.items():
            result = results.get(slo_name)
            
            metrics.append(SLOMetricResponse(
                name=slo_metric.name,
                description=slo_metric.description,
                target_percent=slo_metric.target_percent,
                current_percent=result.success_rate if result else 0.0,
                status=result.status.value if result else SLOStatus.UNKNOWN.value,
                window_minutes=slo_metric.window_minutes,
                last_updated=datetime.fromtimestamp(slo_metric.last_updated, tz=timezone.utc)
            ))
        
        return metrics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SLO metrics retrieval failed: {str(e)}")


@router.get("/evaluate/{slo_name}", response_model=SLOResultResponse)
async def evaluate_slo(slo_name: str):
    """
    Evaluate a specific SLO by name.
    
    Args:
        slo_name: Name of the SLO to evaluate
        
    Returns detailed compliance information for the requested SLO.
    """
    try:
        slo_monitor = get_slo_monitor()
        
        if slo_name not in slo_monitor.slos:
            raise HTTPException(status_code=404, detail=f"SLO '{slo_name}' not found")
        
        result = slo_monitor.evaluate_slo(slo_name)
        
        return SLOResultResponse(
            slo_name=result.slo_name,
            status=result.status.value,
            success_rate=result.success_rate,
            success_count=result.success_count,
            total_count=result.total_count,
            window_start=result.window_start,
            window_end=result.window_end,
            violation_count=len(result.violations)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SLO evaluation failed: {str(e)}")


@router.get("/violations", response_model=List[ViolationResponse])
async def get_slo_violations(
    hours: Optional[int] = Query(default=24, description="Hours of violations to return"),
    slo_name: Optional[str] = Query(default=None, description="Filter by specific SLO name")
):
    """
    Get recent SLO violations.
    
    Args:
        hours: Number of hours of violations to return (default: 24)
        slo_name: Optional filter for specific SLO violations
        
    Returns list of recent SLO violations with context.
    """
    try:
        slo_monitor = get_slo_monitor()
        
        # Filter violations by time and optional SLO name
        cutoff_time = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        violations = []
        
        for violation in slo_monitor.violation_log:
            if violation["timestamp"] < cutoff_time:
                continue
                
            if slo_name and violation["slo_name"] != slo_name:
                continue
                
            violations.append(ViolationResponse(
                slo_name=violation["slo_name"],
                timestamp=datetime.fromtimestamp(violation["timestamp"], tz=timezone.utc),
                metadata=violation["metadata"]
            ))
        
        # Sort by timestamp descending
        violations.sort(key=lambda v: v.timestamp, reverse=True)
        
        return violations
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Violation retrieval failed: {str(e)}")


@router.get("/health")
async def get_slo_health():
    """
    Simple health check for SLO monitoring system.
    
    Returns basic status of the SLO monitoring infrastructure.
    """
    try:
        slo_monitor = get_slo_monitor()
        overall_status = slo_monitor.get_overall_status()
        
        return {
            "status": "healthy",
            "slo_monitor_status": overall_status.value,
            "configured_slos": len(slo_monitor.slos),
            "total_violations": len(slo_monitor.violation_log),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
