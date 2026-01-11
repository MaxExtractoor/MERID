"""
Prediction Market Time-Exploit API Endpoints.

Provides API access to prediction market timing analysis and opportunities.
ALERT-ONLY MODE BY DEFAULT - High regulatory risk.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from prediction import (
    get_oracle_latency_detector,
    get_resolution_tracker,
    get_probability_decay_analyzer,
    get_time_exploit_scanner,
    get_cross_hedge_engine,
    ALERT_ONLY,
    EXECUTION_ENABLED,
)
from prediction.resolution_tracker import ResolutionEvent, MarketPlatform, ResolutionStatus
from prediction.probability_decay import ProbabilitySnapshot
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/prediction", tags=["prediction"])
logger = get_logger("web.api.prediction")


class ResolutionEventRequest(BaseModel):
    """Request to add a resolution event."""
    event_id: str
    platform: str
    market_id: str
    question: str
    scheduled_resolution: float
    category: str = ""
    yes_price: float = 0.5


class ProbabilitySnapshotRequest(BaseModel):
    """Request to record a probability snapshot."""
    market_id: str
    yes_price: float
    no_price: float
    volume_24h: float = 0.0
    liquidity: float = 0.0
    time_to_resolution_hours: float = 24.0


class MispricingAnalysisRequest(BaseModel):
    """Request to analyze mispricing."""
    market_id: str
    platform: str
    current_price: float
    hours_to_resolution: float


class HedgeProposalRequest(BaseModel):
    """Request to propose a cross-hedge."""
    prediction_platform: str
    prediction_market_id: str
    prediction_side: str
    prediction_quantity: float
    prediction_price: float
    category: str = ""


@router.get("/status")
async def get_prediction_status() -> Dict[str, Any]:
    """Get overall prediction engine status."""
    return {
        "alert_only": ALERT_ONLY,
        "execution_enabled": EXECUTION_ENABLED,
        "oracle_latency": get_oracle_latency_detector().get_status(),
        "resolution_tracker": get_resolution_tracker().get_status(),
        "probability_decay": get_probability_decay_analyzer().get_status(),
        "time_exploit_scanner": get_time_exploit_scanner().get_status(),
        "cross_hedge": get_cross_hedge_engine().get_status(),
    }


# ============================================
# ORACLE LATENCY ENDPOINTS
# ============================================

@router.get("/oracle/status")
async def get_oracle_status() -> Dict[str, Any]:
    """Get oracle latency detector status."""
    return get_oracle_latency_detector().get_status()


@router.post("/oracle/start")
async def start_oracle_detector(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start oracle latency detection."""
    detector = get_oracle_latency_detector()
    background_tasks.add_task(detector.start)
    return {"status": "starting"}


@router.post("/oracle/stop")
async def stop_oracle_detector() -> Dict[str, Any]:
    """Stop oracle latency detection."""
    await get_oracle_latency_detector().stop()
    return {"status": "stopped"}


@router.get("/oracle/profiles")
async def get_oracle_profiles() -> Dict[str, Any]:
    """Get all oracle latency profiles."""
    profiles = get_oracle_latency_detector().get_all_profiles()
    return {
        "count": len(profiles),
        "profiles": {k: v.to_dict() for k, v in profiles.items()},
    }


@router.get("/oracle/exploitable")
async def get_exploitable_oracles(min_window: float = 5.0) -> Dict[str, Any]:
    """Get oracles with exploitable latency windows."""
    exploitable = get_oracle_latency_detector().get_exploitable_oracles(min_window)
    return {
        "count": len(exploitable),
        "oracles": [p.to_dict() for p in exploitable],
    }


# ============================================
# RESOLUTION TRACKER ENDPOINTS
# ============================================

@router.get("/resolution/status")
async def get_resolution_status() -> Dict[str, Any]:
    """Get resolution tracker status."""
    return get_resolution_tracker().get_status()


@router.post("/resolution/start")
async def start_resolution_tracker(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start resolution tracking."""
    tracker = get_resolution_tracker()
    background_tasks.add_task(tracker.start)
    return {"status": "starting"}


@router.post("/resolution/stop")
async def stop_resolution_tracker() -> Dict[str, Any]:
    """Stop resolution tracking."""
    await get_resolution_tracker().stop()
    return {"status": "stopped"}


@router.post("/resolution/events")
async def add_resolution_event(request: ResolutionEventRequest) -> Dict[str, Any]:
    """Add an event to track."""
    try:
        platform = MarketPlatform(request.platform)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {request.platform}")
    
    event = ResolutionEvent(
        event_id=request.event_id,
        platform=platform,
        market_id=request.market_id,
        question=request.question,
        scheduled_resolution=request.scheduled_resolution,
        category=request.category,
        yes_price_at_schedule=request.yes_price,
        yes_price_current=request.yes_price,
    )
    
    get_resolution_tracker().add_event(event)
    return {"status": "added", "event": event.to_dict()}


@router.get("/resolution/events")
async def get_resolution_events() -> Dict[str, Any]:
    """Get all tracked events."""
    events = get_resolution_tracker().get_all_events()
    return {
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.get("/resolution/imminent")
async def get_imminent_resolutions(threshold_hours: float = 1.0) -> Dict[str, Any]:
    """Get events with imminent resolution."""
    events = get_resolution_tracker().get_imminent_events(threshold_hours)
    return {
        "count": len(events),
        "threshold_hours": threshold_hours,
        "events": [e.to_dict() for e in events],
    }


# ============================================
# PROBABILITY DECAY ENDPOINTS
# ============================================

@router.get("/decay/status")
async def get_decay_status() -> Dict[str, Any]:
    """Get probability decay analyzer status."""
    return get_probability_decay_analyzer().get_status()


@router.post("/decay/snapshot")
async def record_probability_snapshot(request: ProbabilitySnapshotRequest) -> Dict[str, Any]:
    """Record a probability snapshot."""
    snapshot = ProbabilitySnapshot(
        timestamp=__import__("time").time(),
        yes_price=request.yes_price,
        no_price=request.no_price,
        volume_24h=request.volume_24h,
        liquidity=request.liquidity,
        time_to_resolution_hours=request.time_to_resolution_hours,
    )
    
    get_probability_decay_analyzer().record_snapshot(request.market_id, snapshot)
    return {"status": "recorded", "market_id": request.market_id}


@router.post("/decay/analyze")
async def analyze_mispricing(request: MispricingAnalysisRequest) -> Dict[str, Any]:
    """Analyze potential mispricing."""
    signal = get_probability_decay_analyzer().analyze_mispricing(
        market_id=request.market_id,
        platform=request.platform,
        current_price=request.current_price,
        hours_to_resolution=request.hours_to_resolution,
    )
    
    if signal:
        return {"mispricing_detected": True, "signal": signal.to_dict()}
    return {"mispricing_detected": False, "message": "No significant mispricing detected"}


@router.get("/decay/curves")
async def get_decay_curves() -> Dict[str, Any]:
    """Get all fitted decay curves."""
    curves = get_probability_decay_analyzer().get_all_curves()
    return {
        "count": len(curves),
        "curves": {k: v.to_dict() for k, v in curves.items()},
    }


@router.get("/decay/signals")
async def get_mispricing_signals(min_strength: float = 0.0) -> Dict[str, Any]:
    """Get mispricing signals."""
    signals = get_probability_decay_analyzer().get_signals(min_strength)
    return {
        "count": len(signals),
        "signals": [s.to_dict() for s in signals],
    }


# ============================================
# TIME EXPLOIT SCANNER ENDPOINTS
# ============================================

@router.get("/exploit/status")
async def get_exploit_status() -> Dict[str, Any]:
    """Get time exploit scanner status."""
    return get_time_exploit_scanner().get_status()


@router.post("/exploit/start")
async def start_exploit_scanner(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start time exploit scanning."""
    scanner = get_time_exploit_scanner()
    background_tasks.add_task(scanner.start)
    return {"status": "starting", "alert_only": scanner._alert_only}


@router.post("/exploit/stop")
async def stop_exploit_scanner() -> Dict[str, Any]:
    """Stop time exploit scanning."""
    await get_time_exploit_scanner().stop()
    return {"status": "stopped"}


@router.get("/exploit/opportunities")
async def get_exploit_opportunities(active_only: bool = True) -> Dict[str, Any]:
    """Get detected exploit opportunities."""
    opportunities = get_time_exploit_scanner().get_opportunities(active_only)
    return {
        "count": len(opportunities),
        "alert_only": get_time_exploit_scanner()._alert_only,
        "opportunities": [o.to_dict() for o in opportunities],
    }


@router.post("/exploit/whitelist/platform")
async def whitelist_platform(platform: str) -> Dict[str, Any]:
    """Whitelist a platform for execution."""
    get_time_exploit_scanner().whitelist_platform(platform)
    return {"status": "whitelisted", "platform": platform}


@router.post("/exploit/whitelist/market")
async def whitelist_market(market_id: str) -> Dict[str, Any]:
    """Whitelist a market for execution."""
    get_time_exploit_scanner().whitelist_market(market_id)
    return {"status": "whitelisted", "market_id": market_id}


# ============================================
# CROSS-HEDGE ENDPOINTS
# ============================================

@router.get("/hedge/status")
async def get_hedge_status() -> Dict[str, Any]:
    """Get cross-hedge engine status."""
    return get_cross_hedge_engine().get_status()


@router.post("/hedge/enable")
async def enable_hedge_engine() -> Dict[str, Any]:
    """Enable cross-hedge engine."""
    get_cross_hedge_engine().enable()
    return {"status": "enabled"}


@router.post("/hedge/disable")
async def disable_hedge_engine() -> Dict[str, Any]:
    """Disable cross-hedge engine."""
    get_cross_hedge_engine().disable()
    return {"status": "disabled"}


@router.post("/hedge/propose")
async def propose_hedge(request: HedgeProposalRequest) -> Dict[str, Any]:
    """Propose a cross-hedge position."""
    position = get_cross_hedge_engine().propose_hedge(
        prediction_platform=request.prediction_platform,
        prediction_market_id=request.prediction_market_id,
        prediction_side=request.prediction_side,
        prediction_quantity=request.prediction_quantity,
        prediction_price=request.prediction_price,
        category=request.category,
    )
    
    if position:
        return {"status": "proposed", "position": position.to_dict()}
    return {"status": "rejected", "message": "Could not create hedge proposal"}


@router.get("/hedge/positions")
async def get_hedge_positions() -> Dict[str, Any]:
    """Get active hedge positions."""
    positions = get_cross_hedge_engine().get_active_positions()
    return {
        "count": len(positions),
        "total_exposure": get_cross_hedge_engine().get_total_exposure(),
        "positions": [p.to_dict() for p in positions],
    }


@router.post("/hedge/positions/{position_id}/activate")
async def activate_hedge_position(position_id: str) -> Dict[str, Any]:
    """Activate a proposed hedge position."""
    success = get_cross_hedge_engine().activate_position(position_id)
    if success:
        return {"status": "activated", "position_id": position_id}
    raise HTTPException(status_code=400, detail="Could not activate position")


@router.post("/hedge/positions/{position_id}/close")
async def close_hedge_position(position_id: str) -> Dict[str, Any]:
    """Close a hedge position."""
    success = get_cross_hedge_engine().close_position(position_id)
    if success:
        return {"status": "closed", "position_id": position_id}
    raise HTTPException(status_code=400, detail="Could not close position")


# ============================================
# START ALL COMPONENTS
# ============================================

@router.post("/start-all")
async def start_all_prediction_components(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start all prediction market components."""
    background_tasks.add_task(get_oracle_latency_detector().start)
    background_tasks.add_task(get_resolution_tracker().start)
    background_tasks.add_task(get_time_exploit_scanner().start)
    
    return {
        "status": "starting_all",
        "alert_only": ALERT_ONLY,
        "components": ["oracle_latency", "resolution_tracker", "time_exploit_scanner"],
    }


@router.post("/stop-all")
async def stop_all_prediction_components() -> Dict[str, Any]:
    """Stop all prediction market components."""
    await get_oracle_latency_detector().stop()
    await get_resolution_tracker().stop()
    await get_time_exploit_scanner().stop()
    
    return {"status": "stopped_all"}
