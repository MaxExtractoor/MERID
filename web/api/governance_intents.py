"""
MERID Governance Intents API

Exposes GOV intent review engine via REST API for OPS and UI integration.
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from governance.intent_review import get_intent_review_engine
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.governance_intents")

router = APIRouter(
    prefix="/api/v1/governance", 
    tags=["governance"])


class IntentReviewRequest(BaseModel):
    """Request for intent review."""
    intent_id: str
    intent_data: Dict[str, Any]


class VetoRequest(BaseModel):
    """Request for manual veto."""
    reason: str


class IntentReviewResponse(BaseModel):
    """Response from intent review."""
    success: bool
    result: Dict[str, Any]


@router.post("/intent/review", response_model=IntentReviewResponse)
async def review_intent(
    payload: IntentReviewRequest,
    session: dict = Depends(get_current_session)):
    """
    Submit an intent for GOV review.
    
    This endpoint allows OPS or UI to submit trading intents for governance review.
    The review includes constitutional, risk, and authority checks.
    """
    try:
        engine = get_intent_review_engine()
        
        # Ensure origin_system is set to OPS for authority check
        intent_data = payload.intent_data.copy()
        intent_data["origin_system"] = "OPS"
        
        # Get reviewer ID from session
        reviewer_id = session.get("user_id", "system")
        
        # Submit intent for review
        result = await engine.review_intent(
            intent_id=payload.intent_id,
            intent_data=intent_data,
            reviewer_id=reviewer_id)
        
        # Submit to quorum system
        engine.submit_review(result)
        
        logger.info(f"Intent {payload.intent_id} reviewed: {result.decision.value}")
        
        return IntentReviewResponse(
            success=True,
            result=result.to_dict()
        )
        
    except Exception as e:
        logger.error(f"Intent review failed for {payload.intent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_governance_status():
    """
    Get current governance engine status and statistics.
    
    Returns information about pending reviews, approval rates,
    and current governance criteria.
    """
    try:
        engine = get_intent_review_engine()
        return engine.get_stats()
    except Exception as e:
        logger.error(f"Failed to get governance status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intent/{intent_id}/status")
async def get_intent_status(intent_id: str):
    """
    Get the current status of a specific intent review.
    
    Returns the aggregated review result if quorum is reached,
    or pending review status if still in progress.
    """
    try:
        engine = get_intent_review_engine()
        
        # Check if intent has final decision
        if intent_id in engine._completed_reviews:
            return {
                "intent_id": intent_id,
                "status": "completed",
                "result": engine._completed_reviews[intent_id].to_dict()
            }
        
        # Check if intent is pending
        if intent_id in engine._pending_reviews:
            reviews = engine._pending_reviews[intent_id]
            return {
                "intent_id": intent_id,
                "status": "pending",
                "required_quorum": engine._get_required_quorum(reviews),
                "reviews_submitted": len(reviews),
                "reviews": [r.to_dict() for r in reviews]
            }
        
        # Intent not found
        raise HTTPException(status_code=404, detail=f"Intent {intent_id} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get intent status for {intent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intent/{intent_id}/veto")
async def veto_intent(
    intent_id: str,
    payload: VetoRequest,
    session: dict = Depends(get_current_session)):
    """
    Manual veto of an intent by GOV.
    
    This allows manual override of any intent, regardless of quorum status.
    """
    try:
        engine = get_intent_review_engine()
        reviewer_id = session.get("user_id", "system")
        
        # Perform manual veto with reason
        result = engine.veto_intent(intent_id, reviewer_id, payload.reason)
        
        logger.warning(f"Intent {intent_id} manually vetoed by {reviewer_id}: {payload.reason}")
        
        return {
            "success": True,
            "intent_id": intent_id,
            "veto_by": reviewer_id,
            "reason": payload.reason,
            "result": result.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Failed to veto intent {intent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
