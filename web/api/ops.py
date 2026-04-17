"""
MERID-OPS API Endpoints

Operations & Intelligence Fabric API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/ops", tags=["ops"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.ops")


class RecordDataRequest(BaseModel):
    """Request to record data from a source."""
    source_id: str
    data_type: str
    value: Any
    latency_ms: float = 0.0


class RecordSignalRequest(BaseModel):
    """Request to record a signal."""
    signal_type: str
    source: str
    direction: str
    strength: float
    confidence: float
    symbols: List[str] = []


class RecordDomainSignalRequest(BaseModel):
    """Request to record a domain signal."""
    domain: str
    signal_type: str
    direction: str
    strength: float
    confidence: float
    source: str
    details: Dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════════
# DATA PROVENANCE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/provenance/status")
async def get_provenance_status() -> Dict[str, Any]:
    """Get data provenance tracker status."""
    from ops.data_provenance import get_provenance_tracker
    
    tracker = get_provenance_tracker()
    return tracker.get_status()


@router.get("/provenance/sources")
async def get_all_sources() -> Dict[str, Any]:
    """Get all tracked data sources."""
    
    tracker = get_provenance_tracker()
    return {"sources": tracker.get_all_sources()}


@router.get("/provenance/sources/{source_id}")
async def get_source(source_id: str) -> Dict[str, Any]:
    """Get a specific data source."""
    
    tracker = get_provenance_tracker()
    source = tracker.get_source(source_id)
    
    if not source:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")
    
    return source.to_dict()


@router.get("/provenance/low-trust")
async def get_low_trust_sources(threshold: float = 0.5) -> Dict[str, Any]:
    """Get sources below trust threshold."""
    
    tracker = get_provenance_tracker()
    low_trust = tracker.get_low_trust_sources(threshold)
    
    return {
        "threshold": threshold,
        "sources": [s.to_dict() for s in low_trust],
    }


@router.post("/provenance/record")
async def record_data(request: RecordDataRequest) -> Dict[str, Any]:
    """Record data from a source."""
    
    tracker = get_provenance_tracker()
    data_point = tracker.record_data(
        source_id=request.source_id,
        data_type=request.data_type,
        value=request.value,
        latency_ms=request.latency_ms,
    )
    
    if not data_point:
        raise HTTPException(status_code=400, detail=f"Unknown source: {request.source_id}")
    
    return data_point.to_dict()


@router.post("/provenance/failure")
async def record_failure(source_id: str, reason: str) -> Dict[str, Any]:
    """Record a source failure."""
    
    tracker = get_provenance_tracker()
    tracker.record_failure(source_id, reason)
    
    return {"recorded": True, "source_id": source_id}


# ═══════════════════════════════════════════════════════════════════
# SIGNAL ENTROPY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/entropy/status")
async def get_entropy_status() -> Dict[str, Any]:
    """Get signal entropy tracker status."""
    from ops.signal_entropy import get_entropy_tracker
    
    tracker = get_entropy_tracker()
    return tracker.get_status()


@router.get("/entropy/current")
async def get_current_entropy() -> Dict[str, Any]:
    """Get current entropy window."""
    
    tracker = get_entropy_tracker()
    window = tracker.calculate_current_entropy()
    
    return window.to_dict()


@router.get("/entropy/consensus")
async def get_direction_consensus() -> Dict[str, Any]:
    """Get signal direction consensus."""
    
    tracker = get_entropy_tracker()
    return tracker.get_direction_consensus()


@router.get("/entropy/diversity")
async def get_source_diversity() -> Dict[str, Any]:
    """Get signal source diversity."""
    
    tracker = get_entropy_tracker()
    return tracker.get_source_diversity()


@router.get("/entropy/echo-chamber")
async def check_echo_chamber() -> Dict[str, Any]:
    """Check for echo chamber condition."""
    
    tracker = get_entropy_tracker()
    is_echo, reason = tracker.detect_echo_chamber()
    
    return {
        "is_echo_chamber": is_echo,
        "reason": reason,
    }


@router.get("/entropy/trend")
async def get_entropy_trend(periods: int = 10) -> Dict[str, Any]:
    """Get entropy trend."""
    
    tracker = get_entropy_tracker()
    return tracker.get_entropy_trend(periods)


@router.get("/entropy/signals")
async def get_recent_signals(limit: int = 50) -> Dict[str, Any]:
    """Get recent signals."""
    
    tracker = get_entropy_tracker()
    return {"signals": tracker.get_recent_signals(limit)}


@router.post("/entropy/record")
async def record_signal(request: RecordSignalRequest) -> Dict[str, Any]:
    """Record a signal."""
    
    tracker = get_entropy_tracker()
    signal = tracker.record_signal(
        signal_type=request.signal_type,
        source=request.source,
        direction=request.direction,
        strength=request.strength,
        confidence=request.confidence,
        symbols=request.symbols,
    )
    
    return {
        "signal_id": signal.signal_id,
        "recorded": True,
    }


# ═══════════════════════════════════════════════════════════════════
# CONFLICT DETECTOR ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/conflicts/status")
async def get_conflict_status() -> Dict[str, Any]:
    """Get conflict detector status."""
    from ops.conflict_detector import get_conflict_detector
    
    detector = get_conflict_detector()
    return detector.get_status()


@router.get("/conflicts/active")
async def get_active_conflicts(
    min_severity: str = "low",
    max_age_seconds: float = 3600,
) -> Dict[str, Any]:
    """Get active conflicts."""
    from ops.conflict_detector import get_conflict_detector, ConflictSeverity
    
    try:
        severity = ConflictSeverity(min_severity)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid severity: {min_severity}")
    
    detector = get_conflict_detector()
    conflicts = detector.get_active_conflicts(severity, max_age_seconds)
    
    return {
        "conflicts": [c.to_dict() for c in conflicts],
        "count": len(conflicts),
    }


@router.get("/conflicts/alignment")
async def get_domain_alignment() -> Dict[str, Any]:
    """Get cross-domain alignment status."""
    
    detector = get_conflict_detector()
    return detector.get_domain_alignment()


@router.get("/conflicts/history")
async def get_conflict_history(limit: int = 50) -> Dict[str, Any]:
    """Get conflict history."""
    
    detector = get_conflict_detector()
    return {"conflicts": detector.get_conflicts(limit)}


@router.post("/conflicts/record")
async def record_domain_signal(request: RecordDomainSignalRequest) -> Dict[str, Any]:
    """Record a domain signal (may trigger conflict detection)."""
    from ops.conflict_detector import get_conflict_detector, Domain
    
    try:
        domain = Domain(request.domain)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid domain: {request.domain}")
    
    detector = get_conflict_detector()
    signal = detector.record_signal(
        domain=domain,
        signal_type=request.signal_type,
        direction=request.direction,
        strength=request.strength,
        confidence=request.confidence,
        source=request.source,
        details=request.details,
    )
    
    return {
        "recorded": True,
        "domain": domain.value,
        "direction": signal.direction,
    }


@router.post("/conflicts/resolve/{conflict_id}")
async def resolve_conflict(conflict_id: str, resolution: str) -> Dict[str, Any]:
    """Resolve a conflict."""
    
    detector = get_conflict_detector()
    success = detector.resolve_conflict(conflict_id, resolution)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Conflict not found: {conflict_id}")
    
    return {"resolved": True, "conflict_id": conflict_id}


# ═══════════════════════════════════════════════════════════════════
# COMBINED STATUS ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@router.get("/status")
async def get_ops_status() -> Dict[str, Any]:
    """Get combined OPS status."""
    
    provenance = get_provenance_tracker()
    entropy = get_entropy_tracker()
    conflicts = get_conflict_detector()
    
    entropy_window = entropy.calculate_current_entropy()
    
    return {
        "provenance": provenance.get_status(),
        "entropy": {
            "current": entropy_window.to_dict(),
            "is_healthy": entropy_window.is_healthy,
            "consensus": entropy.get_direction_consensus(),
        },
        "conflicts": conflicts.get_status(),
        "overall_health": {
            "provenance_ok": provenance.get_status()["avg_trust"] > 0.5,
            "entropy_ok": entropy_window.is_healthy,
            "conflicts_ok": conflicts.get_status()["critical_conflicts"] == 0,
        },
    }
