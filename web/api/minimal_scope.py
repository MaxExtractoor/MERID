"""
MERID Minimal Scope API Endpoints

REST API for focused deployment with contract tests and human-centered governance.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from core.merid_minimal_scope import get_minimal_live_scope, GovernanceScorecard
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("minimal_scope_api")

router = APIRouter(prefix="/api/v1/minimal", tags=["minimal_scope"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Pydantic models for API
class HumanReviewRequest(BaseModel):
    model_id: str
    action: str = Field(..., description="Human decision: promote, demote, suspend, hold, retire")
    notes: str = Field(..., description="Reason for decision")
    reviewer: str = Field(..., description="Person making the decision")

# Minimal Scope API Endpoints
@router.get("/scope")
async def get_minimal_scope_info():
    """Get information about the minimal live scope configuration."""
    try:
        scope = get_minimal_scope()
        
        return {
            "success": True,
            "scope": {
                "focused_models": scope.config.FOCUSED_MODELS,
                "calibration_archetypes": {
                    model_id: archetype.value 
                    for model_id, archetype in scope.config.CALIBRATION_ARCHETYPES.items()
                },
                "governance_template": scope.config.GOVERNANCE_TEMPLATE,
                "risk_limits": {
                    tier.value: limits 
                    for tier, limits in scope.config.RISK_LIMITS.items()
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get minimal scope info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scorecards")
async def get_all_governance_scorecards():
    """Get governance scorecards for all models in minimal scope."""
    try:
        scope = get_minimal_scope()
        scorecards = scope.get_all_scorecards()
        
        return {
            "success": True,
            "scorecards": [scorecard.to_dict() for scorecard in scorecards],
            "total_models": len(scorecards)
        }
        
    except Exception as e:
        logger.error(f"Failed to get governance scorecards: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scorecards/{model_id}")
async def get_model_governance_scorecard(model_id: str):
    """Get governance scorecard for a specific model."""
    try:
        scope = get_minimal_scope()
        
        if model_id not in scope.config.FOCUSED_MODELS:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not in minimal scope")
        
        scorecard = scope.generate_governance_scorecard(model_id)
        
        return {
            "success": True,
            "scorecard": scorecard.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Failed to get governance scorecard for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/human-review")
async def submit_human_review(request: HumanReviewRequest):
    """
    Submit human review for governance decision.
    
    Human-centered governance: system provides recommendations, humans make final decisions.
    """
    try:
        scope = get_minimal_scope()
        
        if request.model_id not in scope.config.FOCUSED_MODELS:
            raise HTTPException(status_code=404, detail=f"Model {request.model_id} not in minimal scope")
        
        result = scope.submit_human_review(
            model_id=request.model_id,
            action=request.action,
            notes=request.notes,
            reviewer=request.reviewer
        )
        
        return {
            "success": result["success"],
            "review": result.get("review"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to submit human review: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/human-reviews")
async def get_human_review_summary():
    """Get summary of human review patterns and alignment."""
    try:
        scope = get_minimal_scope()
        summary = scope.get_human_review_summary()
        
        return {
            "success": True,
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Failed to get human review summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/contract-tests")
async def run_contract_tests():
    """Run contract tests for all models in minimal scope."""
    try:
        scope = get_minimal_scope()
        results = scope.run_contract_tests_all_models()
        
        # Calculate overall status
        total_tests = 0
        passed_tests = 0
        
        for model_id, test_results in results.items():
            if "error" not in test_results:
                total_tests += len(test_results)
                passed_tests += sum(test_results.values())
        
        overall_status = "PASS" if passed_tests == total_tests else "FAIL"
        
        return {
            "success": True,
            "overall_status": overall_status,
            "test_summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "failed_tests": total_tests - passed_tests,
                "pass_rate": passed_tests / total_tests if total_tests > 0 else 0.0
            },
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Failed to run contract tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/contract-tests/{model_id}")
async def run_model_contract_tests(model_id: str):
    """Run contract tests for a specific model."""
    try:
        scope = get_minimal_scope()
        
        if model_id not in scope.config.FOCUSED_MODELS:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not in minimal scope")
        
        results = scope.contract_tests.run_all_contract_tests(model_id)
        
        if "error" in results:
            raise HTTPException(status_code=500, detail=results["error"])
        
        total_tests = len(results)
        passed_tests = sum(results.values())
        overall_status = "PASS" if passed_tests == total_tests else "FAIL"
        
        return {
            "success": True,
            "model_id": model_id,
            "overall_status": overall_status,
            "test_summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "failed_tests": total_tests - passed_tests,
                "pass_rate": passed_tests / total_tests if total_tests > 0 else 0.0
            },
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Failed to run contract tests for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/overview")
async def get_minimal_scope_dashboard():
    """Get dashboard overview for minimal scope deployment."""
    try:
        scope = get_minimal_scope()
        
        # Get scorecards
        scorecards = scope.get_all_scorecards()
        
        # Get contract test results
        contract_results = scope.run_contract_tests_all_models()
        
        # Get human review summary
        review_summary = scope.get_human_review_summary()
        
        # Calculate summary metrics
        total_models = len(scorecards)
        models_in_tier_1 = sum(1 for s in scorecards if s.current_tier == "tier_1")
        models_in_tier_2 = sum(1 for s in scorecards if s.current_tier == "tier_2")
        models_with_alerts = sum(1 for s in scorecards if not s.contract_tests.get("all_passed", True))
        
        # Calculate average metrics
        avg_bss = sum(s.brier_skill_score for s in scorecards) / len(scorecards) if scorecards else 0.0
        avg_events = sum(s.n_events for s in scorecards) / len(scorecards) if scorecards else 0.0
        
        return {
            "success": True,
            "deployment": {
                "scope": "minimal",
                "total_models": total_models,
                "models_by_tier": {
                    "tier_1": models_in_tier_1,
                    "tier_2": models_in_tier_2,
                    "tier_3": total_models - models_in_tier_1 - models_in_tier_2,
                    "tier_4": 0,
                    "suspended": 0
                }
            },
            "performance": {
                "avg_brier_skill_score": avg_bss,
                "avg_events": avg_events,
                "models_with_positive_bss": sum(1 for s in scorecards if s.brier_skill_score > 0)
            },
            "safety": {
                "contract_test_status": contract_results.get("overall_status", "UNKNOWN"),
                "models_with_alerts": models_with_alerts,
                "contract_test_summary": {
                    "total_tests": sum(len(r) for r in contract_results.values() if "error" not in r),
                    "passed_tests": sum(sum(v.values()) for r in contract_results.values() if "error" not in r),
                    "pass_rate": review_summary.get("summary", {}).get("alignment_rate", 0.0)
                }
            },
            "governance": {
                "human_review_summary": review_summary,
                "recent_recommendations": [
                    {
                        "model_id": s.model_id,
                        "suggested_action": s.suggested_action,
                        "confidence": s.confidence,
                        "human_status": s.human_review_status
                    }
                    for s in scorecards
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get minimal scope dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def minimal_scope_health():
    """Health check for minimal scope deployment."""
    try:
        scope = get_minimal_scope()
        
        # Basic health checks
        scorecards = scope.get_all_scorecards()
        contract_results = scope.run_contract_tests_all_models()
        
        # Determine health status
        total_models = len(scorecards)
        failed_contract_tests = sum(
            1 for results in contract_results.values()
            if "error" not in results and not all(results.values())
        )
        
        if failed_contract_tests > 0:
            health_status = "DEGRADED"
            health_message = f"{failed_contract_tests} models failing contract tests"
        elif total_models == 0:
            health_status = "WARNING"
            health_message = "No models in scope"
        else:
            health_status = "HEALTHY"
            health_message = f"All {total_models} models operating normally"
        
        return {
            "success": True,
            "health": {
                "status": health_status,
                "message": health_message,
                "models_in_scope": total_models,
                "contract_test_failures": failed_contract_tests,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Minimal scope health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Template endpoints for getting started
@router.get("/templates")
async def get_minimal_scope_templates():
    """Get templates for minimal scope configuration."""
    try:
        templates = {
            "model_selection": {
                "description": "Current minimal scope models",
                "models": [
                    {
                        "id": "crypto_prediction_agent_v1",
                        "domain": "crypto_prediction_markets",
                        "description": "Primary crypto prediction agent",
                        "archetype": "PIT"
                    },
                    {
                        "id": "arbitrage_analyst_v2",
                        "domain": "crypto_arbitrage",
                        "description": "Secondary crypto arbitrage agent",
                        "archetype": "TTC"
                    }
                ]
            },
            "governance_template": {
                "description": "Standard governance thresholds for minimal scope",
                "thresholds": {
                    "min_bss_vs_baseline": 0.05,
                    "min_events": 100,
                    "max_reliability": 0.05,
                    "min_consistency_windows": 3
                },
                "risk_limits": {
                    "tier_1": {"max_position": "$100K", "leverage": "2.0x"},
                    "tier_2": {"max_position": "$50K", "leverage": "1.5x"},
                    "tier_3": {"max_position": "$20K", "leverage": "1.2x"}
                }
            },
            "contract_tests": {
                "description": "Hard safety contracts for governance",
                "tests": [
                    {
                        "name": "negative_bss_tier_restriction",
                        "description": "Models with BSS < 0 cannot be in Tier 1-2",
                        "min_events": 100
                    },
                    {
                        "name": "degradation_alert_guarantee",
                        "description": "15% Brier degradation triggers alert",
                        "threshold": 0.15
                    },
                    {
                        "name": "blindness_auto_promotion_block",
                        "description": "No auto-promotion during Reality Auditor blindness"
                    },
                    {
                        "name": "minimum_events_requirement",
                        "description": "Tier 1: 200 events, Tier 2: 100 events"
                    }
                ]
            },
            "human_review_process": {
                "description": "Human-centered governance workflow",
                "steps": [
                    "1. System generates governance scorecard",
                    "2. Human reviews recommendation",
                    "3. Decision recorded (approve/override)",
                    "4. Override patterns analyzed for threshold tuning",
                    "5. System learns from human decisions"
                ]
            }
        }
        
        return {
            "success": True,
            "templates": templates
        }
        
    except Exception as e:
        logger.error(f"Failed to get minimal scope templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))
