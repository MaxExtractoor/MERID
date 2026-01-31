"""
MERID Governance Cadence API Endpoints

REST API for backtesting, live trials, and institutional governance cadence
for the complete closed-loop forecast governance system.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from core.merid_governance_cadence import (
    get_merid_governance_cadence, BacktestScenario, LiveTrialConfig,
    GovernanceCadence
)
from core.merid_governance import CalibrationArchetype
from utils.logger import get_logger

logger = get_logger("governance_cadence_api")

router = APIRouter(prefix="/api/v1/cadence", tags=["governance_cadence"])

# Pydantic models for API
class BacktestRequest(BaseModel):
    scenario: BacktestScenario
    start_date: datetime
    end_date: datetime
    custom_policies: Optional[Dict[str, Any]] = None

class LiveTrialRequest(BaseModel):
    trial_id: str
    model_ids: List[str]
    risk_cap_multiplier: float = Field(default=0.5, ge=0.1, le=1.0)
    auto_promotion_enabled: bool = Field(default=False)
    auto_demotion_enabled: bool = Field(default=False)
    alert_types: List[str] = Field(default=["promotion", "demotion", "degradation"])
    trial_duration_days: int = Field(default=30, ge=7, le=90)
    review_frequency_days: int = Field(default=7, ge=1, le=30)

class CadenceUpdateRequest(BaseModel):
    weekly_review: Optional[Dict[str, Any]] = None
    monthly_adjustment: Optional[Dict[str, Any]] = None
    quarterly_review: Optional[Dict[str, Any]] = None

# Governance Cadence API Endpoints
@router.post("/backtest/run")
async def run_governance_backtest(request: BacktestRequest):
    """
    Run offline "what-if" governance backtest.
    
    Replays governance engine on historical data and compares actual vs simulated decisions.
    """
    try:
        cadence = get_merid_governance_cadence()
        
        backtest = cadence.run_governance_backtest(
            scenario=request.scenario,
            start_date=request.start_date,
            end_date=request.end_date,
            custom_policies=request.custom_policies
        )
        
        return {
            "success": True,
            "backtest": backtest.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Failed to run governance backtest: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trials/start")
async def start_live_trial(request: LiveTrialRequest):
    """
    Start a controlled live governance trial.
    
    Picks narrow slice of strategies with tight risk caps and human-in-the-loop.
    """
    try:
        cadence = get_merid_governance_cadence()
        
        config = LiveTrialConfig(
            trial_id=request.trial_id,
            model_ids=request.model_ids,
            risk_cap_multiplier=request.risk_cap_multiplier,
            auto_promotion_enabled=request.auto_promotion_enabled,
            auto_demotion_enabled=request.auto_demotion_enabled,
            alert_types=request.alert_types,
            trial_duration_days=request.trial_duration_days,
            review_frequency_days=request.review_frequency_days
        )
        
        result = cadence.start_live_trial(config)
        
        return {
            "success": result["success"],
            "trial_id": request.trial_id,
            "configuration": result.get("configuration"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to start live trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trials/{trial_id}/status")
async def get_trial_status(trial_id: str):
    """Get status and progress of a live trial."""
    try:
        cadence = get_merid_governance_cadence()
        
        status = cadence.get_trial_status(trial_id)
        
        return {
            "success": True,
            "trial_id": trial_id,
            "status": status
        }
        
    except Exception as e:
        logger.error(f"Failed to get trial status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trials/{trial_id}/end")
async def end_trial(trial_id: str):
    """End a live trial and generate summary."""
    try:
        cadence = get_merid_governance_cadence()
        
        result = cadence.end_trial(trial_id)
        
        return {
            "success": result["success"],
            "trial_id": trial_id,
            "summary": result.get("summary"),
            "final_status": result.get("final_status")
        }
        
    except Exception as e:
        logger.error(f"Failed to end trial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trials")
async def list_active_trials():
    """List all active trials."""
    try:
        cadence = get_merid_governance_cadence()
        
        active_trials = []
        for trial_id, config in cadence.active_trials.items():
            status = cadence.get_trial_status(trial_id)
            active_trials.append({
                "trial_id": trial_id,
                "configuration": config.to_dict(),
                "status": status
            })
        
        return {
            "success": True,
            "active_trials": active_trials,
            "total_active": len(active_trials)
        }
        
    except Exception as e:
        logger.error(f"Failed to list active trials: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cadence")
async def get_governance_cadence():
    """Get current governance cadence configuration."""
    try:
        cadence = get_merid_governance_cadence()
        
        return {
            "success": True,
            "cadence": cadence.get_governance_cadence().to_dict()
        }
        
    except Exception as e:
        logger.error(f"Failed to get governance cadence: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/cadence")
async def update_governance_cadence(request: CadenceUpdateRequest):
    """Update governance cadence configuration."""
    try:
        cadence = get_merid_governance_cadence()
        
        updates = {}
        if request.weekly_review:
            updates["weekly_review"] = request.weekly_review
        if request.monthly_adjustment:
            updates["monthly_adjustment"] = request.monthly_adjustment
        if request.quarterly_review:
            updates["quarterly_review"] = request.quarterly_review
        
        result = cadence.update_governance_cadence(updates)
        
        return {
            "success": result["success"],
            "cadence": result.get("cadence"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to update governance cadence: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reviews/weekly")
async def run_weekly_review(background_tasks: BackgroundTasks):
    """Run weekly governance review process."""
    try:
        background_tasks.add_task(run_weekly_review_task)
        
        return {
            "success": True,
            "message": "Weekly governance review started"
        }
        
    except Exception as e:
        logger.error(f"Failed to start weekly review: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reviews/monthly")
async def run_monthly_adjustment(background_tasks: BackgroundTasks):
    """Run monthly governance adjustment process."""
    try:
        background_tasks.add_task(run_monthly_adjustment_task)
        
        return {
            "success": True,
            "message": "Monthly governance adjustment started"
        }
        
    except Exception as e:
        logger.error(f"Failed to start monthly adjustment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reviews/weekly/latest")
async def get_latest_weekly_review():
    """Get the latest weekly review results."""
    try:
        # In production, this would fetch from database
        # For now, return a sample result
        cadence = get_merid_governance_cadence()
        
        # Run a quick review to get current status
        review_results = cadence.run_weekly_review()
        
        return {
            "success": True,
            "review": review_results
        }
        
    except Exception as e:
        logger.error(f"Failed to get latest weekly review: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/reviews/monthly/latest")
async def get_latest_monthly_adjustment():
    """Get the latest monthly adjustment results."""
    try:
        cadence = get_merid_governance_cadence()
        
        # Run a quick adjustment to get current status
        adjustment_results = cadence.run_monthly_adjustment()
        
        return {
            "success": True,
            "adjustment": adjustment_results
        }
        
    except Exception as e:
        logger.error(f"Failed to get latest monthly adjustment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/backtest/scenarios")
async def get_backtest_scenarios():
    """Get available backtest scenarios."""
    try:
        scenarios = {
            "current_policies": {
                "name": "Current Policies",
                "description": "Test with current governance policies",
                "use_case": "Baseline comparison"
            },
            "conservative_policies": {
                "name": "Conservative Policies",
                "description": "Test with stricter thresholds and higher requirements",
                "use_case": "Risk-averse governance"
            },
            "aggressive_policies": {
                "name": "Aggressive Policies",
                "description": "Test with looser thresholds and faster promotions",
                "use_case": "Growth-focused governance"
            },
            "custom_policies": {
                "name": "Custom Policies",
                "description": "Test with user-defined policy parameters",
                "use_case": "Policy optimization"
            }
        }
        
        return {
            "success": True,
            "scenarios": scenarios
        }
        
    except Exception as e:
        logger.error(f"Failed to get backtest scenarios: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trials/templates")
async def get_trial_templates():
    """Get available trial configuration templates."""
    try:
        templates = {
            "conservative_trial": {
                "name": "Conservative Trial",
                "description": "Low-risk trial with tight controls",
                "risk_cap_multiplier": 0.25,
                "auto_promotion_enabled": False,
                "auto_demotion_enabled": False,
                "alert_types": ["degradation", "calibration_drift"],
                "trial_duration_days": 14,
                "review_frequency_days": 3
            },
            "standard_trial": {
                "name": "Standard Trial",
                "description": "Balanced trial with moderate controls",
                "risk_cap_multiplier": 0.5,
                "auto_promotion_enabled": False,
                "auto_demotion_enabled": False,
                "alert_types": ["promotion", "demotion", "degradation"],
                "trial_duration_days": 30,
                "review_frequency_days": 7
            },
            "aggressive_trial": {
                "name": "Aggressive Trial",
                "description": "Higher-risk trial with relaxed controls",
                "risk_cap_multiplier": 0.75,
                "auto_promotion_enabled": True,
                "auto_demotion_enabled": True,
                "alert_types": ["promotion", "demotion", "degradation", "calibration_drift"],
                "trial_duration_days": 60,
                "review_frequency_days": 14
            }
        }
        
        return {
            "success": True,
            "templates": templates
        }
        
    except Exception as e:
        logger.error(f"Failed to get trial templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/cadence-overview")
async def get_cadence_overview():
    """Get overview of governance cadence status and activities."""
    try:
        cadence = get_merid_governance_cadence()
        
        # Get current cadence
        governance_cadence = cadence.get_governance_cadence()
        
        # Get active trials
        active_trials = len(cadence.active_trials)
        
        # Get recent review status (simplified)
        latest_review = cadence.run_weekly_review()
        latest_adjustment = cadence.run_monthly_adjustment()
        
        return {
            "success": True,
            "overview": {
                "governance_cadence": governance_cadence.to_dict(),
                "active_trials": active_trials,
                "latest_weekly_review": {
                    "date": latest_review.get("review_date"),
                    "total_alerts": latest_review.get("alert_review", {}).get("total_alerts", 0),
                    "assessment": latest_review.get("alert_review", {}).get("assessment", "unknown")
                },
                "latest_monthly_adjustment": {
                    "date": latest_adjustment.get("adjustment_date"),
                    "optimizations": len(latest_adjustment.get("policy_optimization", {}).get("optimizations_applied", [])),
                    "tier_adjustments": latest_adjustment.get("tier_adjustments", {}).get("total_adjustments", 0)
                },
                "next_actions": {
                    "weekly_review_due": "Weekly review scheduled for next Monday",
                    "monthly_adjustment_due": "Monthly adjustment due at end of month",
                    "quarterly_review_due": "Quarterly review due in 45 days"
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get cadence overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backtest/compare-scenarios")
async def compare_backtest_scenarios(
    start_date: datetime,
    end_date: datetime,
    scenarios: List[BacktestScenario] = Query(default=[BacktestScenario.CURRENT_POLICIES])
):
    """Compare multiple backtest scenarios side by side."""
    try:
        cadence = get_merid_governance_cadence()
        
        comparison_results = {}
        
        for scenario in scenarios:
            try:
                backtest = cadence.run_governance_backtest(scenario, start_date, end_date)
                comparison_results[scenario.value] = backtest.to_dict()
            except Exception as e:
                logger.error(f"Failed to run backtest for {scenario.value}: {e}")
                comparison_results[scenario.value] = {"error": str(e)}
        
        # Generate comparison summary
        comparison_summary = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "scenarios_compared": len(comparison_results),
            "best_performing": None,
            "most_conservative": None,
            "most_aggressive": None
        }
        
        # Find best performing scenario
        valid_scenarios = {k: v for k, v in comparison_results.items() if "error" not in v}
        
        if valid_scenarios:
            # Best by Sharpe ratio
            best_scenario = max(valid_scenarios.items(), key=lambda x: x[1]["performance_metrics"]["sharpe_ratio"])
            comparison_summary["best_performing"] = best_scenario[0]
            
            # Most conservative (lowest max drawdown)
            most_conservative = min(valid_scenarios.items(), key=lambda x: x[1]["performance_metrics"]["max_drawdown"])
            comparison_summary["most_conservative"] = most_conservative[0]
            
            # Most aggressive (highest return)
            most_aggressive = max(valid_scenarios.items(), key=lambda x: x[1]["performance_metrics"]["return"])
            comparison_summary["most_aggressive"] = most_aggressive[0]
        
        return {
            "success": True,
            "comparison": comparison_results,
            "summary": comparison_summary
        }
        
    except Exception as e:
        logger.error(f"Failed to compare backtest scenarios: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Background Tasks
async def run_weekly_review_task():
    """Background task to run weekly governance review."""
    try:
        cadence = get_merid_governance_cadence()
        review_results = cadence.run_weekly_review()
        
        logger.info(f"Weekly review completed: {review_results.get('review_date')}")
        
        # In production, would store results in database and send notifications
        
    except Exception as e:
        logger.error(f"Weekly review task failed: {e}")

async def run_monthly_adjustment_task():
    """Background task to run monthly governance adjustment."""
    try:
        cadence = get_merid_governance_cadence()
        adjustment_results = cadence.run_monthly_adjustment()
        
        logger.info(f"Monthly adjustment completed: {adjustment_results.get('adjustment_date')}")
        
        # In production, would store results in database and send notifications
        
    except Exception as e:
        logger.error(f"Monthly adjustment task failed: {e}")

# Governance Playbook Endpoints
@router.get("/playbook")
async def get_governance_playbook():
    """Get the MERID governance playbook."""
    try:
        cadence = get_merid_governance_cadence()
        governance_cadence = cadence.get_governance_cadence()
        
        playbook = {
            "title": "MERID Model Governance Playbook",
            "version": governance_cadence.playbook_version,
            "last_updated": governance_cadence.last_updated.isoformat(),
            
            "governance_principles": [
                "All model promotions must pass Brier-based evaluation",
                "Risk limits are tier-based and automatically enforced",
                "Calibration archetypes are selected based on use case",
                "Decisions are validated through historical analysis",
                "Continuous improvement through feedback loops"
            ],
            
            "cadence": {
                "weekly": {
                    "purpose": "Monitor alert patterns and threshold recommendations",
                    "activities": governance_cadence.weekly_review["focus"],
                    "actions": governance_cadence.weekly_review["actions"],
                    "stakeholders": governance_cadence.weekly_review["stakeholders"]
                },
                "monthly": {
                    "purpose": "Optimize policies and adjust tiers based on performance",
                    "activities": governance_cadence.monthly_adjustment["focus"],
                    "actions": governance_cadence.monthly_adjustment["actions"],
                    "stakeholders": governance_cadence.monthly_adjustment["stakeholders"]
                },
                "quarterly": {
                    "purpose": "Strategic review and risk assessment",
                    "activities": governance_cadence.quarterly_review["focus"],
                    "actions": governance_cadence.quarterly_review["actions"],
                    "stakeholders": governance_cadence.quarterly_review["stakeholders"]
                }
            },
            
            "decision_criteria": {
                "promotion": {
                    "minimum_bss": 0.05,
                    "minimum_events": 100,
                    "quality_category": "Fair",
                    "consistency_windows": 3
                },
                "demotion": {
                    "negative_bss": True,
                    "performance_degradation": True,
                    "calibration_drift": True
                },
                "risk_tiers": {
                    "tier_1": {"max_position": "$1M", "leverage": "5x", "concentration": "30%"},
                    "tier_2": {"max_position": "$500K", "leverage": "2.5x", "concentration": "25%"},
                    "tier_3": {"max_position": "$200K", "leverage": "2x", "concentration": "20%"},
                    "tier_4": {"max_position": "$50K", "leverage": "1.5x", "concentration": "15%"}
                }
            },
            
            "escalation_procedures": {
                "alert_severity_high": {
                    "procedure": "Immediate review by risk committee",
                    "timeline": "Within 4 hours",
                    "stakeholders": ["risk_manager", "model_governor", "trading_desk_head"]
                },
                "performance_degradation": {
                    "procedure": "Model evaluation and potential demotion",
                    "timeline": "Within 24 hours",
                    "stakeholders": ["model_governor", "risk_manager"]
                },
                "governance_failure": {
                    "procedure": "Full governance review and policy adjustment",
                    "timeline": "Within 72 hours",
                    "stakeholders": ["governance_committee", "compliance", "executive_team"]
                }
            },
            
            "continuous_improvement": {
                "feedback_loops": [
                    "Historical decision analysis",
                    "Model validation through archetype testing",
                    "Real-time alerting and monitoring",
                    "Live trials with controlled risk"
                ],
                "optimimization_targets": [
                    "Improve decision accuracy to >85%",
                    "Reduce false positive alerts to <20%",
                    "Maintain portfolio Sharpe ratio >1.0",
                    "Keep max drawdown <15%"
                ]
            }
        }
        
        return {
            "success": True,
            "playbook": playbook
        }
        
    except Exception as e:
        logger.error(f"Failed to get governance playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
