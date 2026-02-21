"""
MERID Phase 0 Experiment API Endpoints

REST API for controlled trial with explicit constraints and validation.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from core.phase0_implementation import get_phase0_service
from utils.logger import get_logger

logger = get_logger("phase0_api")

router = APIRouter(prefix="/api/v1/phase0", tags=["phase0_experiment"])

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

class PreTrialExpectationRequest(BaseModel):
    model_id: str
    expected_manual_tier: str
    expected_manual_limits: Dict[str, float]
    expected_binding_thresholds: Dict[str, Any]
    rationale: str

# Phase 0 Experiment API Endpoints
@router.get("/experiment/status")
async def get_experiment_status():
    """Get current Phase 0 experiment status and progress."""
    try:
        service = get_phase0_service()
        status = service.get_experiment_status()
        
        return {
            "success": True,
            "status": status
        }
        
    except Exception as e:
        logger.error(f"Failed to get experiment status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/experiment/setup-expectations")
async def setup_pre_trial_expectations():
    """
    Set up pre-trial expectations for validation.
    
    What we would do manually today vs what we expect the system to recommend.
    """
    try:
        experiment = get_phase0_experiment()
        result = experiment.setup_pre_trial_expectations()
        
        return {
            "success": result["success"],
            "expectations": result.get("expectations"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to setup pre-trial expectations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/experiment/start")
async def start_trial():
    """
    Start the Phase 0 trial with hard constraints.
    
    Applies trial constraints and begins monitoring period.
    """
    try:
        service = get_phase0_service()
        
        # Use the two focused models from minimal scope
        models = ["crypto_prediction_agent_v1", "arbitrage_analyst_v2"]
        
        result = service.start_experiment(models)
        
        return {
            "success": result["success"],
            "experiment_id": result.get("experiment_id"),
            "constraints": result.get("constraints"),
            "initial_scorecards": result.get("initial_scorecards"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to start trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/experiment/weekly-decision")
async def record_weekly_decision(request: WeeklyDecisionRequest):
    """
    Record weekly governance decision for the trial.
    
    Captures system recommendation, human decision, and validation status.
    """
    try:
        service = get_phase0_service()
        result = service.record_weekly_decision(
            model_id=request.model_id,
            human_decision=request.human_decision,
            reason=request.decision_reason
        )
        
        if not result["success"]:
            logger.error(f"Service recording failed: {result.get('error')}")
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to record decision"))
        
        return {
            "success": result["success"],
            "decision": result.get("decision"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to record weekly decision: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/experiment/complete")
async def complete_trial():
    """
    Complete the trial and generate comprehensive results.
    
    Analyzes decisions vs expectations, contract test compliance,
    and provides policy change recommendations.
    """
    try:
        service = get_phase0_service()
        result = service.complete_experiment()
        
        return {
            "success": result["success"],
            "experiment_id": result.get("experiment_id"),
            "metrics": result.get("metrics"),
            "recommendations": result.get("recommendations"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to complete trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/weekly-decisions")
async def get_weekly_decisions(week_number: Optional[int] = Query(None), model_id: Optional[str] = Query(None)):
    """Get weekly decisions for the trial, optionally filtered by week or model."""
    try:
        service = get_phase0_service()
        decisions = service.get_weekly_decisions(week_number=week_number, model_id=model_id)
        
        return {
            "success": True,
            "decisions": decisions,
            "total_decisions": len(decisions)
        }
        
    except Exception as e:
        logger.error(f"Failed to get weekly decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/scorecard-template")
async def get_scorecard_template():
    """
    Get the standardized scorecard template.
    
    This is the lingua franca that all systems should speak.
    """
    try:
        template = {
            "model_id": "string",
            "timestamp": "ISO datetime",
            "metrics": {
                "brier_score": "float",
                "brier_skill_score": "float",
                "calibration_archetype": "string (PIT|TTC|BASE)",
                "n_events": "integer"
            },
            "governance": {
                "current_tier": "string (tier_1|tier_2|tier_3|tier_4|suspended)",
                "risk_limits": {
                    "max_position_size": "float",
                    "max_daily_volume": "float",
                    "max_leverage": "float",
                    "max_concentration": "float"
                },
                "suggested_action": "string (promote|demote|hold|suspend|retire)",
                "action_reason": "string",
                "confidence": "float (0.0-1.0)"
            },
            "safety": {
                "contract_tests": {
                    "negative_bss_tier_restriction": "boolean",
                    "degradation_alert_guarantee": "boolean",
                    "blindness_auto_promotion_block": "boolean",
                    "minimum_events_requirement": "boolean"
                },
                "all_passed": "boolean"
            },
            "human_review": {
                "status": "string (pending|approved|overridden)",
                "notes": "string|null"
            }
        }
        
        return {
            "success": True,
            "template": template,
            "usage": "This is the only payload type that should be used for governance communication"
        }
        
    except Exception as e:
        logger.error(f"Failed to get scorecard template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/constraints")
async def get_trial_constraints():
    """Get the hard constraints applied during the trial."""
    try:
        experiment = get_phase0_experiment()
        
        constraints = {
            "max_notional": experiment.constraints.max_notional,
            "tier_caps": experiment.constraints.tier_caps,
            "auto_execution_disabled": experiment.constraints.auto_execution_disabled,
            "trial_duration_weeks": experiment.constraints.trial_duration_weeks,
            "max_position_per_model": experiment.constraints.max_position_per_model,
            "max_daily_volume_per_model": experiment.constraints.max_daily_volume_per_model
        }
        
        return {
            "success": True,
            "constraints": constraints,
            "rationale": "Hard constraints ensure safe, controlled trial execution"
        }
        
    except Exception as e:
        logger.error(f"Failed to get trial constraints: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/validation-criteria")
async def get_validation_criteria():
    """Get the criteria used to validate system behavior during the trial."""
    try:
        criteria = {
            "decision_alignment_threshold": {
                "minimum": 0.7,
                "description": "70%+ alignment between system recommendations and human decisions"
            },
            "contract_test_compliance_threshold": {
                "minimum": 0.95,
                "description": "95%+ compliance with hard safety contracts"
            },
            "minimum_trial_duration": {
                "weeks": 4,
                "description": "At least 4 weeks of decisions for statistical significance"
            },
            "recent_compliance_requirement": {
                "weeks": 4,
                "description": "All contract tests must pass in the most recent 4 weeks"
            },
            "ready_to_scale_criteria": {
                "system_behavior_validated": True,
                "minimum_decisions": 8,
                "recent_contract_compliance": True
            }
        }
        
        return {
            "success": True,
            "validation_criteria": criteria,
            "message": "These criteria determine if the system is ready for scaling"
        }
        
    except Exception as e:
        logger.error(f"Failed to get validation criteria: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/dashboard")
async def get_experiment_dashboard():
    """Get comprehensive dashboard view of the Phase 0 experiment."""
    try:
        experiment = get_phase0_experiment()
        status = experiment.get_trial_status()
        
        # Get current scorecards
        scorecards = experiment.scope.get_all_scorecards()
        
        # Get contract test status
        contract_results = experiment.scope.run_contract_tests_all_models()
        
        # Calculate summary metrics
        total_decisions = len(experiment.weekly_decisions)
        recent_decisions = [
            dec for dec in experiment.weekly_decisions
            if (datetime.now(timezone.utc) - dec.timestamp).days <= 7
        ]
        
        # Calculate alignment rate
        if experiment.weekly_decisions:
            alignment_count = sum(
                1 for dec in experiment.weekly_decisions
                if dec.human_decision == dec.system_recommendation
            )
            alignment_rate = alignment_count / len(experiment.weekly_decisions)
        else:
            alignment_rate = 0.0
        
        # Calculate contract test compliance
        if experiment.weekly_decisions:
            compliance_count = sum(
                1 for dec in experiment.weekly_decisions
                if dec.contract_tests_passed
            )
            compliance_rate = compliance_count / len(experiment.weekly_decisions)
        else:
            compliance_rate = 0.0
        
        dashboard = {
            "experiment_status": status,
            "current_models": {
                "total_models": len(scorecards),
                "models": [
                    {
                        "model_id": sc.model_id,
                        "current_tier": sc.current_tier,
                        "brier_skill_score": sc.brier_skill_score,
                        "suggested_action": sc.suggested_action,
                        "contract_tests_passed": sc.contract_tests.get("all_passed", False),
                        "human_review_status": sc.human_review_status
                    }
                    for sc in scorecards
                ]
            },
            "trial_progress": {
                "total_decisions": total_decisions,
                "recent_decisions": len(recent_decisions),
                "decision_alignment_rate": alignment_rate,
                "contract_test_compliance_rate": compliance_rate,
                "validation_status": "ON_TRACK" if alignment_rate >= 0.7 and compliance_rate >= 0.95 else "NEEDS_ATTENTION"
            },
            "safety_status": {
                "contract_tests": contract_results,
                "all_tests_passed": all(
                    all(tests.values()) 
                    for tests in contract_results.values() 
                    if "error" not in tests
                ),
                "constraints_active": status.get("phase") == "active"
            },
            "next_actions": {
                "pre_trial": "Setup expectations and start trial" if status.get("phase") == "pre_trial" else None,
                "active": "Record weekly decisions and monitor compliance" if status.get("phase") == "active" else None,
                "post_trial": "Complete trial and analyze results" if status.get("phase") == "post_trial" else None,
                "completed": "Ready to scale governance system" if status.get("phase") == "completed" else None
            }
        }
        
        return {
            "success": True,
            "dashboard": dashboard
        }
        
    except Exception as e:
        logger.error(f"Failed to get experiment dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/expectations-vs-reality")
async def get_expectations_vs_reality():
    """
    Compare pre-trial expectations with actual trial results.
    
    This validates whether the system behaved as expected.
    """
    try:
        experiment = get_phase0_experiment()
        
        if not experiment.pre_trial_expectations:
            return {
                "success": False,
                "message": "No pre-trial expectations set up"
            }
        
        comparisons = []
        
        for expectation in experiment.pre_trial_expectations:
            model_id = expectation.model_id
            
            # Get actual results for this model
            model_decisions = [
                dec for dec in experiment.weekly_decisions
                if dec.model_id == model_id
            ]
            
            if model_decisions:
                # Get latest scorecard
                latest_decision = max(model_decisions, key=lambda x: x.timestamp)
                latest_scorecard = latest_decision.scorecard
                
                # Compare expectation vs reality
                comparison = {
                    "model_id": model_id,
                    "expected_tier": expectation.expected_manual_tier,
                    "actual_tier": latest_scorecard.current_tier,
                    "tier_match": expectation.expected_manual_tier == latest_scorecard.current_tier,
                    "expected_binding_thresholds": expectation.expected_binding_thresholds,
                    "actual_decisions": [
                        {
                            "week": dec.week_number,
                            "system_recommendation": dec.system_recommendation,
                            "human_decision": dec.human_decision,
                            "decision_reason": dec.decision_reason
                        }
                        for dec in model_decisions
                    ],
                    "rationale": expectation.rationale
                }
                
                # Analyze threshold binding
                binding_analysis = {}
                for threshold, expected_behavior in expectation.expected_binding_thresholds.items():
                    # Simple analysis - in production would be more sophisticated
                    binding_analysis[threshold] = {
                        "expected": expected_behavior,
                        "actual": "Analyzed from decisions",
                        "accurate": "Would need detailed analysis"
                    }
                
                comparison["threshold_binding_analysis"] = binding_analysis
                comparisons.append(comparison)
        
        return {
            "success": True,
            "comparisons": comparisons,
            "summary": {
                "total_models": len(comparisons),
                "accurate_tier_predictions": sum(1 for comp in comparisons if comp["tier_match"]),
                "total_expectations": len(experiment.pre_trial_expectations)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get expectations vs reality: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/experiment/scorecard-history/{model_id}")
async def get_scorecard_history(model_id: str):
    """
    Get the history of scorecards for a specific model.
    
    Shows how the governance state evolved over the trial.
    """
    try:
        experiment = get_phase0_experiment()
        
        if model_id not in experiment.scope.config.FOCUSED_MODELS:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not in trial scope")
        
        # Get all decisions for this model
        model_decisions = [
            dec for dec in experiment.weekly_decisions
            if dec.model_id == model_id
        ]
        
        # Sort by week
        model_decisions.sort(key=lambda x: x.week_number)
        
        history = {
            "model_id": model_id,
            "trial_period": {
                "start": experiment.trial_start_date.isoformat() if experiment.trial_start_date else None,
                "end": experiment.trial_end_date.isoformat() if experiment.trial_end_date else None
            },
            "scorecard_evolution": [
                {
                    "week": dec.week_number,
                    "timestamp": dec.timestamp.isoformat(),
                    "scorecard": dec.scorecard.to_dict(),
                    "system_recommendation": dec.system_recommendation,
                    "human_decision": dec.human_decision,
                    "decision_reason": dec.decision_reason,
                    "contract_tests_passed": dec.contract_tests_passed
                }
                for dec in model_decisions
            ],
            "summary": {
                "total_weeks": len(model_decisions),
                "alignment_rate": sum(
                    1 for dec in model_decisions
                    if dec.human_decision == dec.system_recommendation
                ) / len(model_decisions) if model_decisions else 0.0,
                "contract_test_compliance": sum(
                    1 for dec in model_decisions
                    if dec.contract_tests_passed
                ) / len(model_decisions) if model_decisions else 0.0
            }
        }
        
        return {
            "success": True,
            "history": history
        }
        
    except Exception as e:
        logger.error(f"Failed to get scorecard history for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
