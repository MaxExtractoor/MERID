"""
MERID Phase 0 Operational Trial API Endpoints

REST API for time-boxed Phase 0 trial with recommendation-only governance
and evidence-based iteration.
"""

import sys
from web.api.auth import get_current_session
from utils.logger import get_logger
logger = get_logger("phase0_trial_api")

logger.info(f"=== PHASE0_TRIAL_API.PY LOADED === {sys.modules[__name__]}")
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional, Any
from datetime import datetime

from core.phase0_trial import get_phase0_trial
from core.phase0_config import get_phase0_config
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("phase0_trial_api")

logger.info(f"=== PHASE0_TRIAL_API.PY IMPORTS COMPLETE ===")
router = APIRouter(prefix="/api/v1/phase0/trial", tags=["phase0_trial"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

logger.info(f"=== PHASE0_TRIAL_API.PY ROUTER CREATED ===")
# Pydantic models for API
class WeeklyDecisionRequest(BaseModel):
    model_id: str
    human_decision: str = Field(..., description="Human decision: promote, demote, hold, suspend, retire")
    decision_reason: str = Field(..., description="Reason for the decision")
    
    @field_validator('human_decision')
    @classmethod
    def validate_decision(cls, v):
        valid_decisions = ['promote', 'demote', 'hold', 'suspend', 'retire']
        if v.lower() not in valid_decisions:
            raise ValueError(f"Invalid decision '{v}'. Valid options: {', '.join(valid_decisions)}")
        return v.lower()

class TrialStartRequest(BaseModel):
    duration_weeks: int = Field(6, description="Trial duration in weeks", ge=4, le=8)

# Phase 0 Trial API Endpoints
@router.post("/start")
async def start_trial(request: TrialStartRequest):
    """
    Start the Phase 0 operational trial.
    
    Time-boxed trial with two scoped models, recommendation-only governance.
    """
    try:
        config = get_phase0_config()
        
        # Validate Phase 0 is enabled
        if not config.is_phase0_active():
            raise HTTPException(
                status_code=400, 
                detail="Phase 0 is not enabled. Check feature flags."
            )
        
        trial = get_phase0_trial()
        result = trial.start_trial(duration_weeks=request.duration_weeks)
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to start trial"))
        
        return {
            "success": True,
            "trial": result["trial_config"],
            "message": result["message"],
            "next_steps": [
                "Record weekly decisions using /record-weekly-decision",
                "Monitor trial progress using /status",
                "Complete trial using /complete"
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/record-weekly-decision")
async def record_weekly_decision(request: WeeklyDecisionRequest):
    """
    Record weekly governance decision for the trial.
    
    Captures system recommendation vs human decision for alignment analysis.
    Enhanced with robust error handling and validation.
    """
    logger.info(f"Recording decision for model: {request.model_id}, decision: {request.human_decision}")
    
    try:
        # Validate trial is active
        trial = get_phase0_trial()
        if not trial:
            logger.error("No trial instance available")
            raise HTTPException(status_code=500, detail="Trial system not initialized")
        
        if not trial.is_trial_active():
            logger.warning("Attempted to record decision when trial is not active")
            raise HTTPException(status_code=400, detail="Trial is not active")
        
        # Validate model is in scope
        if request.model_id not in trial.scoped_models:
            logger.error(f"Model {request.model_id} not in trial scope")
            raise HTTPException(
                status_code=400, 
                detail=f"Model {request.model_id} not in trial scope. Available models: {trial.scoped_models}"
            )
        
        logger.info(f"Trial validation passed, recording decision...")
        
        # Record decision with enhanced error handling
        result = trial.record_weekly_decision(
            model_id=request.model_id,
            human_decision=request.human_decision,
            decision_reason=request.decision_reason
        )
        
        if not result.get("success", False):
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Decision recording failed: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        logger.info(f"Decision recorded successfully for {request.model_id}")
        
        return {
            "success": True,
            "decision": result["decision"],
            "analysis": result["analysis"],
            "message": f"Weekly decision recorded for {request.model_id}"
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error recording decision: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/status")
async def get_trial_status():
    """
    Get current trial status and progress.
    
    Returns trial configuration, progress metrics, and current alignment rates.
    """
    try:
        trial = get_phase0_trial()
        status = trial.get_trial_status()
        
        return {
            "success": True,
            "status": status
        }
        
    except Exception as e:
        logger.error(f"Failed to get trial status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/complete")
async def complete_trial():
    """
    Complete the Phase 0 trial and generate evidence-based results.
    
    Analyzes alignment, compliance, and generates recommendations for next phase.
    """
    try:
        trial = get_phase0_trial()
        result = trial.complete_trial()
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to complete trial"))
        
        return {
            "success": True,
            "results": result["results"],
            "message": "Phase 0 trial completed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/weekly-decisions")
async def get_weekly_decisions(week_number: Optional[int] = None, model_id: Optional[str] = None):
    """
    Get weekly decisions recorded during the trial.
    
    Optionally filtered by week number or model ID.
    """
    try:
        trial = get_phase0_trial()
        status = trial.get_trial_status()
        
        if status.get("status") != "active":
            raise HTTPException(status_code=400, detail="Trial is not active")
        
        # Get weekly decisions from trial
        weekly_decisions = trial.weekly_records
        
        # Apply filters
        if week_number:
            weekly_decisions = [d for d in weekly_decisions if d.week_number == week_number]
        
        if model_id:
            weekly_decisions = [d for d in weekly_decisions if d.model_id == model_id]
        
        return {
            "success": True,
            "decisions": [d.to_dict() for d in weekly_decisions],
            "total_decisions": len(weekly_decisions),
            "filters_applied": {
                "week_number": week_number,
                "model_id": model_id
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get weekly decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/alignment-analysis")
async def get_alignment_analysis():
    """
    Get alignment analysis between system recommendations and human decisions.
    
    Provides detailed breakdown of alignment patterns and override reasons.
    """
    try:
        trial = get_phase0_trial()
        status = trial.get_trial_status()
        
        if status.get("status") != "active":
            raise HTTPException(status_code=400, detail="Trial is not active")
        
        # Calculate alignment metrics
        weekly_decisions = trial.weekly_records
        
        if not weekly_decisions:
            return {
                "success": True,
                "analysis": {
                    "total_decisions": 0,
                    "alignment_rate": 0.0,
                    "message": "No decisions recorded yet"
                }
            }
        
        # Calculate overall alignment
        aligned_decisions = [d for d in weekly_decisions if d.alignment]
        alignment_rate = len(aligned_decisions) / len(weekly_decisions)
        
        # Calculate alignment by model
        model_alignment = {}
        for model_id in trial.trial_config.scoped_models:
            model_decisions = [d for d in weekly_decisions if d.model_id == model_id]
            if model_decisions:
                model_aligned = [d for d in model_decisions if d.alignment]
                model_alignment[model_id] = {
                    "total_decisions": len(model_decisions),
                    "aligned_decisions": len(model_aligned),
                    "alignment_rate": len(model_aligned) / len(model_decisions)
                }
        
        # Analyze override patterns
        overrides = [d for d in weekly_decisions if not d.alignment]
        override_patterns = {}
        for override in overrides:
            pattern = f"{override.system_recommendation}_to_{override.human_decision}"
            override_patterns[pattern] = override_patterns.get(pattern, 0) + 1
        
        return {
            "success": True,
            "analysis": {
                "overall_alignment": {
                    "total_decisions": len(weekly_decisions),
                    "aligned_decisions": len(aligned_decisions),
                    "alignment_rate": alignment_rate
                },
                "model_alignment": model_alignment,
                "override_patterns": override_patterns,
                "recent_trend": {
                    "last_5_decisions": [
                        {
                            "week": d.week_number,
                            "model": d.model_id,
                            "system": d.system_recommendation,
                            "human": d.human_decision,
                            "aligned": d.alignment
                        }
                        for d in weekly_decisions[-5:]
                    ]
                }
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get alignment analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/contract-compliance")
async def get_contract_compliance():
    """
    Get contract test compliance during the trial.
    
    Analyzes which contract tests were satisfied and identifies any failures.
    """
    try:
        trial = get_phase0_trial()
        status = trial.get_trial_status()
        
        if status.get("status") != "active":
            raise HTTPException(status_code=400, detail="Trial is not active")
        
        weekly_decisions = trial.weekly_records
        
        if not weekly_decisions:
            return {
                "success": True,
                "compliance": {
                    "total_decisions": 0,
                    "compliance_rate": 0.0,
                    "message": "No decisions recorded yet"
                }
            }
        
        # Calculate overall compliance
        compliant_decisions = [d for d in weekly_decisions if d.contract_tests_passed]
        compliance_rate = len(compliant_decisions) / len(weekly_decisions)
        
        # Analyze contract test failures
        failures = [d for d in weekly_decisions if not d.contract_tests_passed]
        failed_tests = {}
        for failure in failures:
            scorecard = failure.scorecard_snapshot
            contract_tests = scorecard.get("safety", {}).get("contract_tests", {})
            
            for test_name, passed in contract_tests.items():
                if not passed:
                    failed_tests[test_name] = failed_tests.get(test_name, 0) + 1
        
        # Compliance by model
        model_compliance = {}
        for model_id in trial.trial_config.scoped_models:
            model_decisions = [d for d in weekly_decisions if d.model_id == model_id]
            if model_decisions:
                model_compliant = [d for d in model_decisions if d.contract_tests_passed]
                model_compliance[model_id] = {
                    "total_decisions": len(model_decisions),
                    "compliant_decisions": len(model_compliant),
                    "compliance_rate": len(model_compliant) / len(model_decisions)
                }
        
        return {
            "success": True,
            "compliance": {
                "overall_compliance": {
                    "total_decisions": len(weekly_decisions),
                    "compliant_decisions": len(compliant_decisions),
                    "compliance_rate": compliance_rate
                },
                "model_compliance": model_compliance,
                "failed_tests": failed_tests,
                "recent_failures": [
                    {
                        "week": d.week_number,
                        "model": d.model_id,
                        "failed_tests": [
                            test for test, passed in d.scorecard_snapshot.get("safety", {}).get("contract_tests", {}).items()
                            if not passed
                        ]
                    }
                    for d in failures[-5:]  # Last 5 failures
                ]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get contract compliance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trial-summary")
async def get_trial_summary():
    """
    Get comprehensive trial summary for monitoring and reporting.
    
    Combines alignment, compliance, and progress metrics.
    """
    try:
        trial = get_phase0_trial()
        status = trial.get_trial_status()
        
        if status.get("status") != "active":
            raise HTTPException(status_code=400, detail="Trial is not active")
        
        # Get alignment analysis
        alignment_analysis = await get_alignment_analysis()
        compliance_analysis = await get_contract_compliance()
        
        # Combine metrics
        current_metrics = status.get("current_metrics", {})
        
        # Calculate success probability
        success_probability = 0.0
        if current_metrics:
            alignment_weight = 0.5
            compliance_weight = 0.3
            progress_weight = 0.2
            
            alignment_score = current_metrics.get("alignment_rate", 0.0)
            compliance_score = current_metrics.get("contract_compliance_rate", 0.0)
            progress_score = min(current_metrics.get("total_decisions", 0) / trial.trial_config.minimum_total_decisions, 1.0)
            
            success_probability = (
                alignment_score * alignment_weight +
                compliance_score * compliance_weight +
                progress_score * progress_weight
            )
        
        return {
            "success": True,
            "summary": {
                "trial_status": status,
                "alignment_analysis": alignment_analysis.get("analysis"),
                "compliance_analysis": compliance_analysis.get("compliance"),
                "success_probability": success_probability,
                "recommendations": [
                    "Continue recording weekly decisions",
                    "Monitor alignment rate trends",
                    "Ensure contract test compliance remains high",
                    "Review override patterns if alignment is low"
                ]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trial summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def trial_health():
    """
    Health check for Phase 0 trial system.
    
    Validates trial state, configuration, and system readiness.
    """
    try:
        config = get_phase0_config()
        trial = get_phase0_trial()
        
        # Check Phase 0 is enabled
        if not config.is_phase0_active():
            return {
                "status": "unhealthy",
                "issues": ["Phase 0 is not enabled"],
                "recommendations": ["Check feature flags: MERID_PHASE0_ENABLED, MERID_FEATURE_MINIMAL_SCOPE"]
            }
        
        # Check trial state
        trial_status = trial.get_trial_status()
        
        health_status = "healthy"
        issues = []
        
        if trial_status.get("status") == "not_started":
            health_status = "warning"
            issues.append("Trial has not been started")
        elif trial_status.get("status") == "active":
            # Check if trial is progressing
            current_metrics = trial_status.get("current_metrics", {})
            if current_metrics.get("total_decisions", 0) == 0:
                health_status = "warning"
                issues.append("No decisions recorded yet")
        else:
            health_status = "info"
            issues.append("Trial is not active")
        
        return {
            "status": health_status,
            "trial_status": trial_status.get("status"),
            "issues": issues,
            "configuration": {
                "phase0_enabled": config.enabled,
                "minimal_scope_enabled": config.minimal_scope_enabled,
                "human_review_required": config.human_review_required,
                "contract_enforced": config.contract_enforced,
                "dry_run": config.dry_run
            },
            "recommendations": [
                "Start trial if not started" if trial_status.get("status") == "not_started" else None,
                "Record weekly decisions" if current_metrics.get("total_decisions", 0) == 0 else None,
                "Monitor alignment and compliance" if trial_status.get("status") == "active" else None
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get trial health: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
