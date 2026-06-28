"""
Sanity Dashboard API for Live Trading

Provides per-strip metrics and sanity checks for live trading monitoring.
Exposes endpoints for tracking:
- Per-strip signal counts and rejections
- Per-asset performance by strip
- Guardrail rejection counts by type
- Real-time system health metrics
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("web.api.sanity_dashboard")

router = APIRouter(prefix="/api/v1/sanity", tags=["sanity"])


# ── Data Models ────────────────────────────────────────────────────────────


class StripMetrics(BaseModel):
    """Metrics for a single trading strip."""
    strip_id: str
    timestamp: str
    asset: str
    signals_generated: int
    signals_scheduled: int
    signals_rejected: int
    rejection_reasons: Dict[str, int]  # e.g., {"price_floor": 5, "correlation": 2}
    avg_edge: float
    avg_confidence: float


class GuardrailStats(BaseModel):
    """Statistics for guardrail rejections."""
    guardrail_name: str
    rejection_count: int
    last_rejection_time: Optional[str]
    last_rejection_asset: Optional[str]
    last_rejection_reason: Optional[str]


class SystemHealth(BaseModel):
    """Overall system health metrics."""
    total_strips: int
    total_signals: int
    total_scheduled: int
    total_rejected: int
    rejection_rate: float
    avg_edge: float
    avg_confidence: float
    last_update: str


# ── In-Memory Store (for demo - would use Redis/DB in production) ─────────


class SanityDashboardStore:
    """In-memory store for sanity dashboard metrics."""
    
    def __init__(self):
        self._strip_metrics: Dict[str, StripMetrics] = {}
        self._guardrail_stats: Dict[str, GuardrailStats] = {}
        self._last_update: datetime = datetime.now(timezone.utc)
    
    def record_strip_metrics(self, metrics: StripMetrics) -> None:
        """Record metrics for a strip."""
        self._strip_metrics[metrics.strip_id] = metrics
        self._last_update = datetime.now(timezone.utc)
        logger.debug(f"Recorded strip metrics: {metrics.strip_id}")
    
    def record_guardrail_rejection(
        self,
        guardrail_name: str,
        asset: str,
        reason: str,
    ) -> None:
        """Record a guardrail rejection."""
        if guardrail_name not in self._guardrail_stats:
            self._guardrail_stats[guardrail_name] = GuardrailStats(
                guardrail_name=guardrail_name,
                rejection_count=0,
                last_rejection_time=None,
                last_rejection_asset=None,
                last_rejection_reason=None,
            )
        
        stats = self._guardrail_stats[guardrail_name]
        stats.rejection_count += 1
        stats.last_rejection_time = datetime.now(timezone.utc).isoformat()
        stats.last_rejection_asset = asset
        stats.last_rejection_reason = reason
        self._last_update = datetime.now(timezone.utc)
        
        logger.debug(f"Recorded guardrail rejection: {guardrail_name} for {asset}")
    
    def get_all_strip_metrics(self) -> List[StripMetrics]:
        """Get all strip metrics."""
        return list(self._strip_metrics.values())
    
    def get_guardrail_stats(self) -> List[GuardrailStats]:
        """Get all guardrail statistics."""
        return list(self._guardrail_stats.values())
    
    def get_system_health(self) -> SystemHealth:
        """Calculate overall system health."""
        strips = list(self._strip_metrics.values())
        
        if not strips:
            return SystemHealth(
                total_strips=0,
                total_signals=0,
                total_scheduled=0,
                total_rejected=0,
                rejection_rate=0.0,
                avg_edge=0.0,
                avg_confidence=0.0,
                last_update=self._last_update.isoformat(),
            )
        
        total_signals = sum(s.signals_generated for s in strips)
        total_scheduled = sum(s.signals_scheduled for s in strips)
        total_rejected = sum(s.signals_rejected for s in strips)
        
        rejection_rate = total_rejected / total_signals if total_signals > 0 else 0.0
        
        avg_edge = sum(s.avg_edge for s in strips) / len(strips) if strips else 0.0
        avg_confidence = sum(s.avg_confidence for s in strips) / len(strips) if strips else 0.0
        
        return SystemHealth(
            total_strips=len(strips),
            total_signals=total_signals,
            total_scheduled=total_scheduled,
            total_rejected=total_rejected,
            rejection_rate=rejection_rate,
            avg_edge=avg_edge,
            avg_confidence=avg_confidence,
            last_update=self._last_update.isoformat(),
        )


# Global store instance
_store = SanityDashboardStore()


def get_sanity_store() -> SanityDashboardStore:
    """Get the sanity dashboard store singleton."""
    return _store


# ── API Endpoints ───────────────────────────────────────────────────────────


@router.get("/health", response_model=SystemHealth)
async def get_system_health() -> SystemHealth:
    """Get overall system health metrics."""
    return _store.get_system_health()


@router.get("/strips", response_model=List[StripMetrics])
async def get_strip_metrics(
    limit: int = 100,
    asset: Optional[str] = None,
) -> List[StripMetrics]:
    """Get strip metrics, optionally filtered by asset.
    
    Args:
        limit: Maximum number of strips to return
        asset: Optional asset filter (e.g., "BTC", "ETH")
    """
    metrics = _store.get_all_strip_metrics()
    
    if asset:
        metrics = [m for m in metrics if m.asset == asset]
    
    # Return most recent strips first
    metrics.sort(key=lambda x: x.timestamp, reverse=True)
    
    return metrics[:limit]


@router.get("/guardrails", response_model=List[GuardrailStats])
async def get_guardrail_stats() -> List[GuardrailStats]:
    """Get guardrail rejection statistics."""
    return _store.get_guardrail_stats()


@router.post("/record-strip")
async def record_strip_metrics(metrics: StripMetrics) -> Dict[str, str]:
    """Record metrics for a strip (called by trading system)."""
    _store.record_strip_metrics(metrics)
    return {"status": "recorded", "strip_id": metrics.strip_id}


@router.post("/record-rejection")
async def record_guardrail_rejection(
    guardrail_name: str,
    asset: str,
    reason: str,
) -> Dict[str, str]:
    """Record a guardrail rejection (called by trading system)."""
    _store.record_guardrail_rejection(guardrail_name, asset, reason)
    return {"status": "recorded", "guardrail": guardrail_name}
