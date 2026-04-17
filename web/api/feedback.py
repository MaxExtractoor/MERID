"""
MERID Feedback Loop API Endpoints

REST API for historical analysis, model validation, and real-time alerting
to tighten feedback loops around Brier-based governance.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone

from core.merid_feedback import get_merid_feedback_loop, AlertConfiguration
from core.merid_governance import CalibrationArchetype
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("feedback_api")

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Pydantic models for API
class HistoricalAnalysisRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    include_simulation: bool = True

class AlertConfigurationRequest(BaseModel):
    model_id: str
    enabled: bool = True
    alert_types: List[str] = Field(default=["promotion", "demotion", "degradation"])
    thresholds: Dict[str, float] = Field(default_factory=dict)
    notification_channels: List[str] = Field(default=["webhook"])
    cooldown_minutes: int = Field(default=60)

class ModelValidationRequest(BaseModel):
    top_n: int = Field(default=5, ge=1, le=20)
    bottom_n: int = Field(default=5, ge=1, le=20)
    days: int = Field(default=30, ge=1, le=365)

# Feedback Loop API Endpoints
@router.post("/historical/analyze")
async def analyze_historical_decisions(request: HistoricalAnalysisRequest):
    """
    Analyze historical decisions and compare governance recommendations with actual actions.
    
    Identifies where decisions diverge to tune thresholds and tiers.
    """
    try:
        feedback_loop = get_merid_feedback_loop()
        
        analysis = feedback_loop.analyze_historical_decisions(
            request.start_date, 
            request.end_date
        )
        
        return {
            "success": True,
            "analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"Failed to analyze historical decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/validate")
async def validate_top_bottom_models(request: ModelValidationRequest):
    """
    Validate top and bottom models through full archetype analysis.
    
    Walks models through PIT vs TTC vs BASE to validate recommendations.
    """
    try:
        feedback_loop = get_merid_feedback_loop()
        
        validation = feedback_loop.validate_top_models(
            top_n=request.top_n,
            bottom_n=request.bottom_n,
            days=request.days
        )
        
        return {
            "success": True,
            "validation": validation
        }
        
    except Exception as e:
        logger.error(f"Failed to validate models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/{model_id}/alerts/configure")
async def configure_model_alerts(model_id: str, request: AlertConfigurationRequest):
    """Configure real-time alerts for a model."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        config = AlertConfiguration(
            model_id=model_id,
            enabled=request.enabled,
            alert_types=request.alert_types,
            thresholds=request.thresholds,
            notification_channels=request.notification_channels,
            cooldown_minutes=request.cooldown_minutes
        )
        
        result = feedback_loop.configure_alerts(model_id, config)
        
        return {
            "success": result["success"],
            "configuration": result.get("configuration"),
            "message": result.get("message")
        }
        
    except Exception as e:
        logger.error(f"Failed to configure alerts for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/alerts/check")
async def check_model_alerts(model_id: str):
    """Check if any alerts should be triggered for a model."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        alerts = feedback_loop.check_alerts(model_id)
        
        return {
            "success": True,
            "model_id": model_id,
            "alerts": alerts,
            "alert_count": len(alerts)
        }
        
    except Exception as e:
        logger.error(f"Failed to check alerts for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/archetype-validation")
async def get_archetype_validation(model_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get detailed archetype validation for a specific model."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        validation = feedback_loop._validate_model_archetypes(model_id, days)
        
        return {
            "success": True,
            "validation": validation.to_dict()
        }
        
    except Exception as e:
        logger.error(f"Failed to get archetype validation for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/feedback-overview")
async def get_feedback_overview():
    """Get overview of feedback loop analysis and alerting status."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Get alert configurations
        alert_configs = {
            model_id: config.to_dict() 
            for model_id, config in feedback_loop.alert_configs.items()
        }
        
        # Get recent alerts (sample)
        recent_alerts = []
        for model_id in list(feedback_loop.alert_configs.keys())[:5]:  # Sample 5 models
            alerts = feedback_loop.check_alerts(model_id)
            for alert in alerts:
                recent_alerts.append(alert)
        
        # Sort by timestamp
        recent_alerts.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
            "success": True,
            "overview": {
                "configured_models": len(alert_configs),
                "enabled_alerts": sum(1 for config in alert_configs.values() if config.enabled),
                "recent_alerts": recent_alerts[:10],  # Top 10 recent alerts
                "alert_types": list(set(
                    alert_type 
                    for config in alert_configs.values() 
                    for alert_type in config.alert_types
                ))
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get feedback overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/batch/check-all-alerts")
async def check_all_alerts(background_tasks: BackgroundTasks):
    """Trigger alert checking for all configured models."""
    try:
        background_tasks.add_task(run_batch_alert_check)
        
        return {
            "success": True,
            "message": "Batch alert checking started for all configured models"
        }
        
    except Exception as e:
        logger.error(f"Failed to start batch alert check: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/decision-history")
async def get_decision_history(model_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get decision history for a specific model."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Get governance policy
        from core.merid_governance import get_merid_governance
        governance = get_merid_governance()
        
        policy = governance.policies.get(model_id)
        if not policy:
            raise HTTPException(status_code=404, detail=f"No governance policy found for {model_id}")
        
        # Get evaluation history
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        recent_evaluations = [
            eval for eval in policy.evaluation_history
            if datetime.fromisoformat(eval["timestamp"]) > cutoff_date
        ]
        
        # Sort by timestamp
        recent_evaluations.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
            "success": True,
            "model_id": model_id,
            "decision_history": recent_evaluations,
            "total_evaluations": len(recent_evaluations),
            "period_days": days
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get decision history for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/insights/performance-gaps")
async def get_performance_gaps_insights(days: int = Query(default=30, ge=1, le=365)):
    """Get insights about performance gaps between top and bottom models."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Validate top and bottom models
        validation = feedback_loop.validate_top_models(top_n=3, bottom_n=3, days=days)
        
        insights = validation.get("insights", {})
        
        return {
            "success": True,
            "insights": insights,
            "validation_period_days": days
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance gaps insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/insights/threshold-recommendations")
async def get_threshold_recommendations():
    """Get threshold tuning recommendations based on historical analysis."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Analyze recent period for threshold recommendations
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        analysis = feedback_loop.analyze_historical_decisions(start_date, end_date)
        
        recommendations = analysis.get("threshold_recommendations", {})
        
        return {
            "success": True,
            "recommendations": recommendations,
            "analysis_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get threshold recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/models/{model_id}/simulate-governance")
async def simulate_governance_decisions(model_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Simulate governance decisions for a model over a period."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Get historical performance
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        historical_performance = feedback_loop._get_historical_performance(start_date, end_date)
        model_performance = [p for p in historical_performance if p["model_id"] == model_id]
        
        if not model_performance:
            raise HTTPException(status_code=404, detail=f"No performance data found for {model_id}")
        
        # Simulate decisions
        simulated_decisions = []
        for performance in model_performance:
            # Register temporary policy if needed
            governance = get_merid_governance()
            
            if model_id not in governance.policies:
                governance.register_model_policy(model_id)
            
            # Simulate evaluation
            evaluation = governance.evaluate_promotion_eligibility(model_id, days=30)
            
            simulated_decisions.append({
                "timestamp": performance["window_start"],
                "window_end": performance["window_end"],
                "performance": performance,
                "governance_evaluation": evaluation,
                "simulated_action": evaluation.get("action")
            })
        
        return {
            "success": True,
            "model_id": model_id,
            "simulation_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days
            },
            "simulated_decisions": simulated_decisions,
            "decision_summary": {
                "total_decisions": len(simulated_decisions),
                "promotion_recommendations": len([d for d in simulated_decisions if d["simulated_action"] == "promote"]),
                "demotion_recommendations": len([d for d in simulated_decisions if d["simulated_action"] == "demote"]),
                "hold_recommendations": len([d for d in simulated_decisions if d["simulated_action"] == "hold"])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to simulate governance for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/calibration-stability")
async def get_calibration_stability(model_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get calibration stability analysis for a model."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        # Get performance view
        dashboard = get_merid_feedback_loop().dashboard
        performance_view = dashboard.get_model_performance_view(model_id, days)
        
        if not performance_view:
            raise HTTPException(status_code=404, detail=f"No performance data found for {model_id}")
        
        # Calculate stability metrics
        brier_values = performance_view.brier_score_ts.values
        bss_values = performance_view.brier_skill_score_ts.values
        reliability_values = performance_view.reliability_ts.values
        
        stability_analysis = {
            "brier_score": {
                "values": brier_values,
                "mean": np.mean(brier_values),
                "std": np.std(brier_values),
                "coefficient_of_variation": np.std(brier_values) / np.mean(brier_values) if np.mean(brier_values) > 0 else 0,
                "trend": "improving" if brier_values[-1] < brier_values[0] else "degrading"
            },
            "brier_skill_score": {
                "values": bss_values,
                "mean": np.mean(bss_values),
                "std": np.std(bss_values),
                "coefficient_of_variation": np.std(bss_values) / np.mean(bss_values) if np.mean(bss_values) > 0 else 0,
                "trend": "improving" if bss_values[-1] > bss_values[0] else "degrading"
            },
            "reliability": {
                "values": reliability_values,
                "mean": np.mean(reliability_values),
                "std": np.std(reliability_values),
                "trend": "improving" if reliability_values[-1] < reliability_values[0] else "degrading"
            }
        }
        
        # Overall stability assessment
        overall_cv = np.mean([
            stability_analysis["brier_score"]["coefficient_of_variation"],
            stability_analysis["brier_skill_score"]["coefficient_of_variation"],
            stability_analysis["reliability"]["std"]
        ])
        
        stability_level = "stable" if overall_cv < 0.3 else "moderate" if overall_cv < 0.6 else "unstable"
        
        return {
            "success": True,
            "model_id": model_id,
            "analysis_period_days": days,
            "stability_analysis": stability_analysis,
            "overall_stability": {
                "level": stability_level,
                "coefficient_of_variation": overall_cv,
                "assessment": f"Model shows {stability_level} calibration stability"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get calibration stability for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Background Tasks
async def run_batch_alert_check():
    """Background task to check alerts for all configured models."""
    try:
        feedback_loop = get_merid_feedback_loop()
        
        all_alerts = []
        for model_id in feedback_loop.alert_configs.keys():
            try:
                alerts = feedback_loop.check_alerts(model_id)
                all_alerts.extend(alerts)
                
                # Log alerts
                for alert in alerts:
                    logger.info(f"Alert triggered for {model_id}: {alert['type']} - {alert['message']}")
                    
            except Exception as e:
                logger.error(f"Failed to check alerts for {model_id}: {e}")
        
        logger.info(f"Batch alert check completed: {len(all_alerts)} alerts triggered")
        
    except Exception as e:
        logger.error(f"Batch alert check failed: {e}")

# Alert Templates
@router.get("/templates/alert-configurations")
async def get_alert_configuration_templates():
    """Get available alert configuration templates."""
    try:
        templates = {
            "conservative": {
                "alert_types": ["promotion", "demotion", "degradation"],
                "thresholds": {
                    "promotion_bss": 0.12,
                    "demotion_bss": 0.02,
                    "degradation_threshold": 0.15,
                    "reliability_threshold": 0.08
                },
                "cooldown_minutes": 120
            },
            "standard": {
                "alert_types": ["promotion", "demotion", "degradation", "calibration_drift"],
                "thresholds": {
                    "promotion_bss": 0.10,
                    "demotion_bss": 0.0,
                    "degradation_threshold": 0.20,
                    "reliability_threshold": 0.10
                },
                "cooldown_minutes": 60
            },
            "aggressive": {
                "alert_types": ["promotion", "demotion", "degradation", "calibration_drift"],
                "thresholds": {
                    "promotion_bss": 0.08,
                    "demotion_bss": -0.02,
                    "degradation_threshold": 0.25,
                    "reliability_threshold": 0.12
                },
                "cooldown_minutes": 30
            }
        }
        
        return {
            "success": True,
            "templates": templates
        }
        
    except Exception as e:
        logger.error(f"Failed to get alert templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))
