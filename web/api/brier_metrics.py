"""
MERID Brier Metrics API Endpoints

REST API for Brier scoring, calibration, and forecast management.
Integrates with MERID's core metrics system as the canonical probability accuracy layer.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from core.merid_metrics import (
    MERIDMetrics, CalibrationMethod, CalibrationArchetype,
    BrierResult, CalibrationResult
)
from core.brier_metrics_db import get_brier_db
from utils.logger import get_logger

logger = get_logger("brier_metrics_api")

router = APIRouter(prefix="/api/v1/metrics", tags=["brier_metrics"])

# Pydantic models for API
class ForecastRecord(BaseModel):
    model_id: str
    market_id: str
    probability: float = Field(ge=0.0, le=1.0, description="Predicted probability")
    user_id: Optional[str] = None
    weight: float = Field(default=1.0, ge=0.0, description="Sample weight")

class ForecastResolution(BaseModel):
    forecast_id: int
    outcome: int = Field(ge=0, le=1, description="Actual outcome (0 or 1)")

class ModelRegistration(BaseModel):
    model_id: str
    name: str
    kind: str = Field(description="Model type: agent, strategy, ensemble, etc.")

class CalibrationRequest(BaseModel):
    model_id: str
    method: CalibrationMethod
    archetype: CalibrationArchetype = CalibrationArchetype.PIT
    feature_name: Optional[str] = None
    market_group: Optional[str] = None
    data_start: datetime
    data_end: datetime

class BrierEvaluationRequest(BaseModel):
    y_true: List[float] = Field(description="True outcomes (0/1)")
    y_pred: List[float] = Field(description="Predicted probabilities")
    weights: Optional[List[float]] = None
    baseline: Optional[List[float]] = None
    calibration_method: Optional[CalibrationMethod] = None
    n_bins: int = Field(default=10, ge=5, le=50)

class WindowMetricsRequest(BaseModel):
    model_id: str
    window_start: datetime
    window_end: datetime
    market_id: Optional[str] = None

# API Endpoints
@router.post("/models/register")
async def register_model(request: ModelRegistration):
    """Register a new model for Brier tracking."""
    try:
        db = get_brier_db()
        db.register_model(request.model_id, request.name, request.kind)
        
        return {
            "success": True,
            "model_id": request.model_id,
            "message": f"Model {request.model_id} registered successfully"
        }
    except Exception as e:
        logger.error(f"Failed to register model {request.model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/forecasts")
async def record_forecast(request: ForecastRecord):
    """Record a new forecast for Brier tracking."""
    try:
        db = get_brier_db()
        forecast_id = db.record_forecast(
            request.model_id,
            request.market_id,
            request.probability,
            request.user_id,
            request.weight
        )
        
        return {
            "success": True,
            "forecast_id": forecast_id,
            "model_id": request.model_id,
            "market_id": request.market_id,
            "probability": request.probability,
            "recorded_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to record forecast: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/forecasts/resolve")
async def resolve_forecast(request: ForecastResolution):
    """Resolve a forecast with its actual outcome."""
    try:
        db = get_brier_db()
        db.resolve_forecast(request.forecast_id, request.outcome)
        
        return {
            "success": True,
            "forecast_id": request.forecast_id,
            "outcome": request.outcome,
            "resolved_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to resolve forecast {request.forecast_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/evaluate")
async def evaluate_predictions(request: BrierEvaluationRequest):
    """
    Evaluate predictions using Brier scoring.
    
    This is the core evaluation endpoint that provides comprehensive
    Brier analysis including decomposition and calibration.
    """
    try:
        # Convert to numpy arrays
        y_true = np.array(request.y_true)
        y_pred = np.array(request.y_pred)
        
        if len(y_true) != len(y_pred):
            raise HTTPException(status_code=400, detail="y_true and y_pred must have same length")
        
        weights = np.array(request.weights) if request.weights else None
        baseline = np.array(request.baseline) if request.baseline else None
        
        # Validate inputs
        if not np.all((y_true == 0) | (y_true == 1)):
            raise HTTPException(status_code=400, detail="y_true must contain only 0 and 1")
        
        if not np.all((y_pred >= 0) & (y_pred <= 1)):
            raise HTTPException(status_code=400, detail="y_pred must be between 0 and 1")
        
        # Compute metrics
        metrics = get_merid_metrics()
        results = metrics.evaluate_model(
            y_true, y_pred, baseline, request.calibration_method, request.n_bins
        )
        
        return {
            "success": True,
            "evaluation": results,
            "metadata": {
                "n_events": len(y_true),
                "calibration_method": request.calibration_method.value if request.calibration_method else None,
                "n_bins": request.n_bins,
                "evaluated_at": datetime.now().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/calibration/train")
async def train_calibration(request: CalibrationRequest):
    """
    Train probability calibration for a model.
    
    Fits calibration parameters and stores them for production use.
    """
    try:
        db = get_brier_db()
        
        # Get training data from database
        with db.get_brier_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT prob, outcome, weight
                FROM forecasts
                WHERE model_id = ? AND ts_resolved >= ? AND ts_resolved <= ?
                AND outcome IS NOT NULL
            """, (request.model_id, request.data_start, request.data_end))
            
            rows = cursor.fetchall()
        
        if not rows:
            raise HTTPException(status_code=404, detail="No resolved forecasts found for training period")
        
        # Extract data
        y_pred = np.array([row["prob"] for row in rows])
        y_true = np.array([row["outcome"] for row in rows])
        weights = np.array([row["weight"] for row in rows])
        
        # Train calibration
        metrics = get_merid_metrics()
        calibrator = metrics.calibrate_probabilities(
            y_pred, y_true, request.method, request.archetype
        )
        
        # Save calibration
        cal_result = CalibrationResult(
            method=request.method,
            archetype=request.archetype,
            params=calibrator.params,
            brier_raw=calibrator.brier_raw,
            brier_cal=calibrator.brier_cal,
            bss_vs_raw=calibrator.bss_vs_raw,
            n_events=len(y_true),
            trained_on_start=request.data_start,
            trained_on_end=request.data_end,
            version=1  # Will be updated in DB
        )
        
        calib_run_id = db.save_calibration(
            request.model_id, cal_result, request.feature_name, request.market_group
        )
        
        return {
            "success": True,
            "calib_run_id": calib_run_id,
            "calibration": cal_result.to_dict(),
            "training_data": {
                "n_events": len(y_true),
                "period_start": request.data_start.isoformat(),
                "period_end": request.data_end.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calibration training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/calibration")
async def get_model_calibration(model_id: str, 
                               feature_name: Optional[str] = None,
                               market_group: Optional[str] = None):
    """Get current calibration parameters for a model."""
    try:
        db = get_brier_db()
        calibration = db.get_current_calibration(model_id, feature_name, market_group)
        
        if not calibration:
            raise HTTPException(status_code=404, detail="No calibration found for model")
        
        return {
            "success": True,
            "model_id": model_id,
            "calibration": calibration
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get calibration: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/metrics/window")
async def get_window_metrics(model_id: str,
                            window_start: datetime = Query(...),
                            window_end: datetime = Query(...),
                            market_id: Optional[str] = None):
    """Get aggregated Brier metrics for a time window."""
    try:
        db = get_brier_db()
        metrics = db.compute_window_metrics(model_id, window_start, window_end, market_id)
        
        if not metrics:
            raise HTTPException(status_code=404, detail="No forecasts found in window")
        
        return {
            "success": True,
            "model_id": model_id,
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
                "market_id": market_id
            },
            "metrics": metrics
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get window metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/metrics/streaming")
async def get_streaming_metrics(model_id: str,
                               market_group: Optional[str] = None,
                               days: int = Query(default=7, ge=1, le=90)):
    """Get streaming calibration metrics for recent days."""
    try:
        db = get_brier_db()
        metrics = db.get_streaming_metrics(model_id, market_group, days)
        
        return {
            "success": True,
            "model_id": model_id,
            "market_group": market_group,
            "period_days": days,
            "streaming_metrics": metrics
        }
    except Exception as e:
        logger.error(f"Failed to get streaming metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/performance")
async def get_model_performance(model_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get comprehensive performance summary for a model."""
    try:
        db = get_brier_db()
        summary = db.get_model_performance_summary(model_id, days)
        
        return {
            "success": True,
            "performance": summary
        }
    except Exception as e:
        logger.error(f"Failed to get performance summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reliability-diagram")
async def generate_reliability_diagram(request: BrierEvaluationRequest):
    """Generate reliability diagram data for visualization."""
    try:
        # Convert to numpy arrays
        y_true = np.array(request.y_true)
        y_pred = np.array(request.y_pred)
        
        if len(y_true) != len(y_pred):
            raise HTTPException(status_code=400, detail="y_true and y_pred must have same length")
        
        # Generate diagram data
        metrics = get_merid_metrics()
        diagram_data = metrics.plot_reliability_diagram(
            y_true, y_pred, request.n_bins, "Reliability Diagram"
        )
        
        return {
            "success": True,
            "diagram": diagram_data,
            "metadata": {
                "n_events": len(y_true),
                "n_bins": request.n_bins,
                "generated_at": datetime.now().isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate reliability diagram: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models/{model_id}/promote")
async def evaluate_promotion_eligibility(model_id: str,
                                      min_bss: float = Query(default=0.05, ge=0.0),
                                      min_events: int = Query(default=100, ge=10),
                                      days: int = Query(default=30, ge=1, le=90)):
    """
    Evaluate if a model meets promotion criteria.
    
    Uses Brier Skill Score and event count as primary gates for promotion.
    """
    try:
        db = get_brier_db()
        
        # Get recent performance
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with db.get_brier_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT brier_score, brier_skill_score, n_events, quality_category
                FROM forecast_metrics
                WHERE model_id = ? AND window_start >= ?
                ORDER BY window_start DESC
                LIMIT 1
            """, (model_id, cutoff_date))
            
            row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="No recent metrics found for model")
        
        # Evaluate criteria
        bss = row["brier_skill_score"] or 0.0
        n_events = row["n_events"]
        quality = row["quality_category"]
        
        meets_bss = bss >= min_bss
        meets_events = n_events >= min_events
        eligible = meets_bss and meets_events
        
        # Additional quality checks
        quality_good = quality in ["Excellent", "Good", "Fair"]
        
        return {
            "success": True,
            "model_id": model_id,
            "evaluation": {
                "eligible": eligible,
                "meets_bss_criteria": meets_bss,
                "meets_events_criteria": meets_events,
                "quality_acceptable": quality_good,
                "current_metrics": {
                    "brier_score": row["brier_score"],
                    "brier_skill_score": bss,
                    "n_events": n_events,
                    "quality_category": quality
                },
                "criteria": {
                    "min_bss": min_bss,
                    "min_events": min_events,
                    "evaluation_period_days": days
                },
                "recommendation": "PROMOTE" if eligible and quality_good else "HOLD"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Promotion evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/overview")
async def get_metrics_dashboard(days: int = Query(default=7, ge=1, le=30)):
    """Get dashboard overview of all models' Brier metrics."""
    try:
        db = get_brier_db()
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with db.get_brier_db_connection() as conn:
            cursor = conn.cursor()
            
            # Recent metrics for all models
            cursor.execute("""
                SELECT m.model_id, m.name, m.kind,
                       fm.brier_score, fm.brier_skill_score, fm.n_events,
                       fm.quality_category, fm.window_start
                FROM models m
                LEFT JOIN forecast_metrics fm ON m.model_id = fm.model_id
                WHERE fm.window_start >= ?
                ORDER BY fm.window_start DESC
            """, (cutoff_date,))
            
            rows = cursor.fetchall()
        
        # Group by model
        model_summary = {}
        for row in rows:
            model_id = row["model_id"]
            if model_id not in model_summary:
                model_summary[model_id] = {
                    "name": row["name"],
                    "kind": row["kind"],
                    "latest_metrics": None,
                    "metrics_count": 0
                }
            
            if model_summary[model_id]["latest_metrics"] is None:
                model_summary[model_id]["latest_metrics"] = {
                    "brier_score": row["brier_score"],
                    "brier_skill_score": row["brier_skill_score"],
                    "n_events": row["n_events"],
                    "quality_category": row["quality_category"],
                    "window_start": row["window_start"]
                }
            
            model_summary[model_id]["metrics_count"] += 1
        
        # Compute summary statistics
        all_bss = [row["brier_skill_score"] for row in rows if row["brier_skill_score"] is not None]
        all_brier = [row["brier_score"] for row in rows if row["brier_score"] is not None]
        
        summary_stats = {
            "total_models": len(model_summary),
            "models_with_metrics": len([m for m in model_summary.values() if m["latest_metrics"]]),
            "avg_brier_skill_score": np.mean(all_bss) if all_bss else None,
            "avg_brier_score": np.mean(all_brier) if all_brier else None,
            "period_days": days
        }
        
        return {
            "success": True,
            "summary": summary_stats,
            "models": model_summary,
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Dashboard overview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Background task for batch calibration updates
async def batch_calibration_update(background_tasks: BackgroundTasks):
    """Trigger batch calibration update for all models."""
    background_tasks.add_task(run_batch_calibration)
    return {"success": True, "message": "Batch calibration update started"}

async def run_batch_calibration():
    """Background task to update calibrations for all models."""
    try:
        db = get_brier_db()
        metrics = get_merid_metrics()
        
        # Get all models
        with db.get_brier_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT model_id FROM models")
            models = [row["model_id"] for row in cursor.fetchall()]
        
        # Update calibration for each model
        for model_id in models:
            try:
                # Get recent data for training
                data_end = datetime.now()
                data_start = data_end - timedelta(days=30)
                
                # Get training data
                with db.get_brier_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT prob, outcome, weight
                        FROM forecasts
                        WHERE model_id = ? AND ts_resolved >= ? AND ts_resolved <= ?
                        AND outcome IS NOT NULL
                    """, (model_id, data_start, data_end))
                    
                    rows = cursor.fetchall()
                
                if len(rows) >= 50:  # Minimum events for calibration
                    y_pred = np.array([row["prob"] for row in rows])
                    y_true = np.array([row["outcome"] for row in rows])
                    
                    # Train isotonic calibration
                    cal_result = metrics.calibrate_probabilities(
                        y_pred, y_true, CalibrationMethod.ISOTONIC, CalibrationArchetype.PIT
                    )
                    
                    # Save calibration
                    cal_result.trained_on_start = data_start
                    cal_result.trained_on_end = data_end
                    
                    db.save_calibration(model_id, cal_result)
                    logger.info(f"Updated calibration for model {model_id}")
                
            except Exception as e:
                logger.error(f"Failed to update calibration for {model_id}: {e}")
        
        logger.info("Batch calibration update completed")
        
    except Exception as e:
        logger.error(f"Batch calibration update failed: {e}")
