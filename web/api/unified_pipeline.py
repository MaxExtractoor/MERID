"""§5 Unified Pipeline API — Multi-domain observability, control plane.

Endpoints:
- GET  /api/v1/pipeline/summary          — Full pipeline summary (all domains)
- GET  /api/v1/pipeline/risk             — Global risk manager summary
- GET  /api/v1/pipeline/instruments      — Instrument registry summary
- GET  /api/v1/pipeline/venues           — All venue configs and health
- GET  /api/v1/pipeline/proposals        — Recent proposal history
- POST /api/v1/pipeline/domain/enable    — Enable a domain
- POST /api/v1/pipeline/domain/disable   — Disable a domain
- POST /api/v1/pipeline/domain/halt      — Halt a domain (kill switch)
- POST /api/v1/pipeline/domain/resume    — Resume a halted domain
- POST /api/v1/pipeline/venue/mode       — Set venue trading mode
- POST /api/v1/pipeline/venue/enable     — Enable a venue
- POST /api/v1/pipeline/venue/disable    — Disable a venue
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from merid.pipeline.mode_manager import ModeManager, TradingMode, get_mode_manager
from merid.pipeline.risk_manager import GlobalRiskManager, get_global_risk_manager
from merid.pipeline.instruments import get_instrument_registry
from merid.pipeline.adapter import get_adapter_registry
from merid.pipeline.router import TradeRouter

from utils.logger import get_logger

logger = get_logger("web.api.unified_pipeline")

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

# Lazy singletons
_router: Optional[TradeRouter] = None


def _get_router() -> TradeRouter:
    global _router
    if _router is None:
        _router = TradeRouter()
    return _router


# ── Request models ───────────────────────────────────────────────────

class DomainRequest(BaseModel):
    domain: str  # "prediction", "crypto", "equity", "macro"


class DomainHaltRequest(BaseModel):
    domain: str
    reason: str = ""


class VenueModeRequest(BaseModel):
    venue: str
    mode: str  # "sim", "paper", "live"


class VenueRequest(BaseModel):
    venue: str


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/summary")
async def pipeline_summary():
    """Full pipeline summary across all domains."""
    tr = _get_router()
    mm = get_mode_manager()
    rm = get_global_risk_manager()
    return {
        "router": tr.summary(),
        "risk": rm.summary(),
        "modes": mm.summary(),
    }


@router.get("/risk")
async def pipeline_risk():
    """Global risk manager summary."""
    return get_global_risk_manager().summary()


@router.get("/instruments")
async def pipeline_instruments():
    """Instrument registry summary."""
    reg = get_instrument_registry()
    return {
        "summary": reg.summary(),
        "instruments": [
            inst.to_dict() for inst in list(reg._instruments.values())[:100]
        ],
    }


@router.get("/venues")
async def pipeline_venues():
    """All venue configs and adapter status."""
    mm = get_mode_manager()
    ar = get_adapter_registry()
    mode_summary = mm.summary()
    adapter_summary = ar.summary()
    adapters_by_venue = {entry["venue"]: entry for entry in adapter_summary}
    venues = []
    for venue in mode_summary.get("venues", []):
        adapter = adapters_by_venue.get(venue["venue"], {})
        venues.append({
            **venue,
            "mode": str(venue["mode"]).upper(),
            "supports_trading": adapter.get("supports_trading", False),
            "adapter_registered": venue["venue"] in adapters_by_venue,
            "lastModeChange": None,
        })
    return {
        "mode_manager": mode_summary,
        "adapters": adapter_summary,
        "venues": venues,
    }


@router.get("/proposals")
async def pipeline_proposals(limit: int = 50):
    """Recent proposal history."""
    tr = _get_router()
    return {"proposals": tr.recent_proposals(limit=limit)}


# ── Domain control ───────────────────────────────────────────────────

@router.post("/domain/enable")
async def enable_domain(req: DomainRequest):
    mm = get_mode_manager()
    mm.enable_domain(req.domain)
    return {"status": "ok", "domain": req.domain, "enabled": True}


@router.post("/domain/disable")
async def disable_domain(req: DomainRequest):
    mm = get_mode_manager()
    mm.disable_domain(req.domain)
    return {"status": "ok", "domain": req.domain, "enabled": False}


@router.post("/domain/halt")
async def halt_domain(req: DomainHaltRequest):
    rm = get_global_risk_manager()
    rm.halt_domain(req.domain, req.reason or "Manual halt")
    try:
        from core.notifications import add_notification
        add_notification(
            type="risk", severity="critical",
            title=f"Domain Halted: {req.domain}",
            message=f"Trading domain '{req.domain}' halted — {req.reason or 'Manual halt'}",
            source="risk_manager",
        )
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))
    return {"status": "halted", "domain": req.domain, "reason": req.reason}


@router.post("/domain/resume")
async def resume_domain(req: DomainRequest):
    rm = get_global_risk_manager()
    rm.resume_domain(req.domain)
    try:
        add_notification(
            type="risk", severity="info",
            title=f"Domain Resumed: {req.domain}",
            message=f"Trading domain '{req.domain}' resumed — normal operations",
            source="risk_manager",
        )
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))
    return {"status": "resumed", "domain": req.domain}


# ── Venue control ────────────────────────────────────────────────────

@router.post("/venue/mode")
async def set_venue_mode(req: VenueModeRequest):
    mm = get_mode_manager()
    try:
        mode = TradingMode(req.mode.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid mode: {req.mode}. Use sim/paper/live.")
    try:
        mm.set_venue_mode(req.venue, mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "ok", "venue": req.venue, "mode": mode.value}


@router.post("/venue/enable")
async def enable_venue(req: VenueRequest):
    mm = get_mode_manager()
    mm.enable_venue(req.venue)
    return {"status": "ok", "venue": req.venue, "enabled": True}


@router.post("/venue/disable")
async def disable_venue(req: VenueRequest):
    mm = get_mode_manager()
    mm.disable_venue(req.venue)
    return {"status": "ok", "venue": req.venue, "enabled": False}


# ── Risk Context ────────────────────────────────────────────────────

@router.get("/risk-context")
async def pipeline_risk_context():
    """System-state risk context snapshot.

    Aggregates caps, CQI, drawdown, and exposure from ExecutionGuard,
    OperatorSession, GlobalRiskManager, and DrawdownGovernor.
    Returns derived size_scale_factor and approval_threshold_boost that
    consensus and risk checks use to adjust plan sizing and approval.
    """
    from merid.pipeline.risk_context import get_risk_context
    return get_risk_context().to_dict()
