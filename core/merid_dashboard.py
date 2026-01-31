"""
MERID Brier Metrics Dashboard - Visualization Components

Dashboard views for Brier/BSS trends, calibration archetypes, and model governance.
Provides real-time visualization of model performance and promotion decisions.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import numpy as np
import json

from core.merid_metrics import get_merid_metrics, CalibrationArchetype
from core.brier_metrics_db import get_brier_db
from core.merid_governance import get_merid_governance, RiskTier
from utils.logger import get_logger

logger = get_logger("merid_dashboard")

@dataclass
class DashboardTimeSeries:
    """Time series data for dashboard visualization."""
    timestamps: List[str]
    values: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamps": self.timestamps,
            "values": self.values,
            "metadata": self.metadata
        }

@dataclass
class ModelPerformanceView:
    """Comprehensive model performance view for dashboard."""
    model_id: str
    model_name: str
    current_tier: str
    risk_limits: Dict[str, Any]
    
    # Time series data
    brier_score_ts: DashboardTimeSeries
    brier_skill_score_ts: DashboardTimeSeries
    reliability_ts: DashboardTimeSeries
    resolution_ts: DashboardTimeSeries
    uncertainty_ts: DashboardTimeSeries
    
    # Current metrics
    current_brier: float
    current_bss: float
    current_quality: str
    current_archetype: str
    
    # Calibration comparison
    raw_brier: Optional[float] = None
    calibrated_brier: Optional[float] = None
    calibration_improvement: Optional[float] = None
    
    # Governance status
    last_evaluation: Optional[Dict[str, Any]] = None
    promotion_eligibility: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "current_tier": self.current_tier,
            "risk_limits": self.risk_limits,
            "time_series": {
                "brier_score": self.brier_score_ts.to_dict(),
                "brier_skill_score": self.brier_skill_score_ts.to_dict(),
                "reliability": self.reliability_ts.to_dict(),
                "resolution": self.resolution_ts.to_dict(),
                "uncertainty": self.uncertainty_ts.to_dict()
            },
            "current_metrics": {
                "brier_score": self.current_brier,
                "brier_skill_score": self.current_bss,
                "quality_category": self.current_quality,
                "archetype": self.current_archetype
            },
            "calibration_comparison": {
                "raw_brier": self.raw_brier,
                "calibrated_brier": self.calibrated_brier,
                "improvement_pct": self.calibration_improvement
            },
            "governance": {
                "last_evaluation": self.last_evaluation,
                "promotion_eligibility": self.promotion_eligibility
            }
        }

@dataclass
class GovernanceDashboard:
    """Governance overview for dashboard."""
    total_models: int
    models_by_tier: Dict[str, int]
    recent_promotions: List[Dict[str, Any]]
    recent_demotions: List[Dict[str, Any]]
    pending_evaluations: List[Dict[str, Any]]
    
    # Risk exposure summary
    total_risk_exposure: float
    tier_exposure: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_models": self.total_models,
            "models_by_tier": self.models_by_tier,
            "recent_actions": {
                "promotions": self.recent_promotions,
                "demotions": self.recent_demotions
            },
            "pending_evaluations": self.pending_evaluations,
            "risk_exposure": {
                "total": self.total_risk_exposure,
                "by_tier": self.tier_exposure
            }
        }

class MERIDDashboard:
    """
    MERID Dashboard System
    
    Provides visualization data for Brier metrics, calibration archetypes,
    and governance decisions.
    """
    
    def __init__(self):
        self.db = get_brier_db()
        self.metrics = get_merid_metrics()
        self.governance = get_merid_governance()
    
    def get_model_performance_view(self, model_id: str, 
                                 days: int = 30) -> Optional[ModelPerformanceView]:
        """
        Get comprehensive performance view for a model.
        
        Includes time series, current metrics, calibration comparison, and governance status.
        """
        try:
            # Get model performance summary
            performance = self.db.get_model_performance_summary(model_id, days)
            
            if not performance["recent_aggregated_metrics"]:
                return None
            
            # Get governance policy
            policy = self.governance.policies.get(model_id)
            if not policy:
                # Register default policy
                policy = self.governance.register_model_policy(model_id)
            
            # Extract time series data
            recent_metrics = performance["recent_aggregated_metrics"]
            
            # Create time series
            brier_ts = DashboardTimeSeries(
                timestamps=[m["window_start"] for m in recent_metrics],
                values=[m["brier_score"] for m in recent_metrics],
                metadata={"unit": "Brier Score", "lower_is_better": True}
            )
            
            bss_ts = DashboardTimeSeries(
                timestamps=[m["window_start"] for m in recent_metrics],
                values=[m["brier_skill_score"] or 0.0 for m in recent_metrics],
                metadata={"unit": "Brier Skill Score", "higher_is_better": True}
            )
            
            reliability_ts = DashboardTimeSeries(
                timestamps=[m["window_start"] for m in recent_metrics],
                values=[m["reliability"] or 0.0 for m in recent_metrics],
                metadata={"unit": "Reliability", "lower_is_better": True}
            )
            
            resolution_ts = DashboardTimeSeries(
                timestamps=[m["window_start"] for m in recent_metrics],
                values=[m["resolution"] or 0.0 for m in recent_metrics],
                metadata={"unit": "Resolution", "higher_is_better": True}
            )
            
            uncertainty_ts = DashboardTimeSeries(
                timestamps=[m["window_start"] for m in recent_metrics],
                values=[m["uncertainty"] or 0.0 for m in recent_metrics],
                metadata={"unit": "Uncertainty", "contextual": True}
            )
            
            # Get current metrics
            current = recent_metrics[0]
            
            # Get calibration comparison
            calibration_comparison = self._get_calibration_comparison(model_id)
            
            # Get governance status
            promotion_eligibility = self.governance.evaluate_promotion_eligibility(model_id, days)
            last_evaluation = policy.evaluation_history[-1] if policy.evaluation_history else None
            
            return ModelPerformanceView(
                model_id=model_id,
                model_name=model_id,  # Could be enhanced with model registry
                current_tier=policy.current_tier.value,
                risk_limits=policy.risk_limits.to_dict(),
                brier_score_ts=brier_ts,
                brier_skill_score_ts=bss_ts,
                reliability_ts=reliability_ts,
                resolution_ts=resolution_ts,
                uncertainty_ts=uncertainty_ts,
                current_brier=current["brier_score"],
                current_bss=current["brier_skill_score"] or 0.0,
                current_quality=current["quality_category"],
                current_archetype=self._get_current_archetype(model_id),
                raw_brier=calibration_comparison.get("raw_brier"),
                calibrated_brier=calibration_comparison.get("calibrated_brier"),
                calibration_improvement=calibration_comparison.get("improvement_pct"),
                last_evaluation=last_evaluation,
                promotion_eligibility=promotion_eligibility
            )
            
        except Exception as e:
            logger.error(f"Failed to get performance view for {model_id}: {e}")
            return None
    
    def _get_calibration_comparison(self, model_id: str) -> Dict[str, Any]:
        """Get calibration comparison (raw vs calibrated)."""
        try:
            current_cal = self.db.get_current_calibration(model_id)
            
            if not current_cal:
                return {}
            
            return {
                "raw_brier": current_cal.get("brier_raw"),
                "calibrated_brier": current_cal.get("brier_cal"),
                "improvement_pct": current_cal.get("bss_vs_raw", 0.0) * 100,
                "method": current_cal.get("method"),
                "archetype": current_cal.get("archetype"),
                "version": current_cal.get("version")
            }
            
        except Exception as e:
            logger.error(f"Failed to get calibration comparison for {model_id}: {e}")
            return {}
    
    def _get_current_archetype(self, model_id: str) -> str:
        """Get current calibration archetype."""
        try:
            current_cal = self.db.get_current_calibration(model_id)
            return current_cal.get("archetype", "BASE") if current_cal else "BASE"
        except:
            return "BASE"
    
    def get_governance_dashboard(self, days: int = 7) -> GovernanceDashboard:
        """Get governance overview dashboard."""
        try:
            summary = self.governance.get_governance_summary()
            
            # Filter recent evaluations
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_evaluations = [
                eval for eval in summary["recent_evaluations"]
                if datetime.fromisoformat(eval["timestamp"]) > cutoff_date
            ]
            
            # Categorize actions
            promotions = [e for e in recent_evaluations if e["action"] == "promote"]
            demotions = [e for e in recent_evaluations if e["action"] in ["demote", "suspend"]]
            
            # Calculate risk exposure
            total_exposure = 0.0
            tier_exposure = {}
            
            for model_id, policy in self.governance.policies.items():
                tier = policy.current_tier.value
                limits = policy.risk_limits
                
                exposure = limits.max_position_size
                total_exposure += exposure
                tier_exposure[tier] = tier_exposure.get(tier, 0) + exposure
            
            return GovernanceDashboard(
                total_models=summary["total_models"],
                models_by_tier=summary["models_by_tier"],
                recent_promotions=promotions,
                recent_demotions=demotions,
                pending_evaluations=recent_evaluations[:10],  # Top 10 pending
                total_risk_exposure=total_exposure,
                tier_exposure=tier_exposure
            )
            
        except Exception as e:
            logger.error(f"Failed to get governance dashboard: {e}")
            return GovernanceDashboard(
                total_models=0,
                models_by_tier={},
                recent_promotions=[],
                recent_demotions=[],
                pending_evaluations=[],
                total_risk_exposure=0.0,
                tier_exposure={}
            )
    
    def get_archetype_comparison(self, model_id: str) -> Dict[str, Any]:
        """
        Get calibration archetype comparison for a model.
        
        Shows performance across PIT, TTC, and BASE archetypes.
        """
        try:
            archetype_performance = {}
            
            for archetype in CalibrationArchetype:
                # Get calibration for this archetype
                calibrations = self._get_archetype_calibrations(model_id, archetype)
                
                if calibrations:
                    # Get performance metrics for this archetype
                    performance = self._get_archetype_performance(model_id, archetype)
                    archetype_performance[archetype.value] = {
                        "latest_calibration": calibrations[-1],
                        "performance": performance,
                        "recommended_use": self._get_archetype_recommendation(archetype, performance)
                    }
            
            # Get current archetype
            current_archetype = self._get_current_archetype(model_id)
            
            return {
                "model_id": model_id,
                "current_archetype": current_archetype,
                "archetype_performance": archetype_performance,
                "recommendation": self._get_archetype_selection_recommendation(archetype_performance, current_archetype)
            }
            
        except Exception as e:
            logger.error(f"Failed to get archetype comparison for {model_id}: {e}")
            return {}
    
    def _get_archetype_calibrations(self, model_id: str, archetype: CalibrationArchetype) -> List[Dict[str, Any]]:
        """Get calibration history for a specific archetype."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM calibration_runs
                    WHERE model_id = ? AND archetype = ?
                    ORDER BY version DESC
                """, (model_id, archetype.value))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Failed to get archetype calibrations: {e}")
            return []
    
    def _get_archetype_performance(self, model_id: str, archetype: CalibrationArchetype) -> Dict[str, Any]:
        """Get performance metrics for a specific archetype."""
        try:
            # Get recent metrics for this archetype
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT window_start, brier_score, brier_skill_score, n_events
                    FROM forecast_metrics
                    WHERE model_id = ?
                    ORDER BY window_start DESC
                    LIMIT 10
                """, (model_id,))
                
                rows = cursor.fetchall()
                
                if not rows:
                    return {}
                
                recent_scores = [row["brier_score"] for row in rows]
                recent_bss = [row["brier_skill_score"] or 0.0 for row in rows]
                total_events = sum(row["n_events"] for row in rows)
                
                return {
                    "avg_brier_score": np.mean(recent_scores),
                    "avg_brier_skill_score": np.mean(recent_bss),
                    "latest_brier_score": recent_scores[0],
                    "latest_bss": recent_bss[0],
                    "total_events": total_events,
                    "stability": np.std(recent_scores) / np.mean(recent_scores) if np.mean(recent_scores) > 0 else 0
                }
                
        except Exception as e:
            logger.error(f"Failed to get archetype performance: {e}")
            return {}
    
    def _get_archetype_recommendation(self, archetype: CalibrationArchetype, performance: Dict[str, Any]) -> str:
        """Get recommendation for using a specific archetype."""
        if not performance:
            return "No data available"
        
        bss = performance.get("avg_brier_skill_score", 0)
        stability = performance.get("stability", 1.0)
        
        if archetype == CalibrationArchetype.PIT:
            if bss > 0.08 and stability < 0.3:
                return "Excellent for current market conditions - high skill, stable"
            elif bss > 0.05:
                return "Good for current conditions - moderate skill"
            else:
                return "Poor performance - consider other archetypes"
        
        elif archetype == CalibrationArchetype.TTC:
            if bss > 0.06 and stability < 0.4:
                return "Excellent for long-term decisions - stable, good skill"
            elif bss > 0.03:
                return "Good for baseline - moderate long-term performance"
            else:
                return "Poor long-term performance - use for reference only"
        
        else:  # BASE
            return "Use as baseline reference - not for active decisions"
    
    def _get_archetype_selection_recommendation(self, archetype_performance: Dict[str, str], 
                                             current_archetype: str) -> str:
        """Get overall archetype selection recommendation."""
        if not archetype_performance:
            return "Insufficient data for recommendation"
        
        # Find best performing archetype
        best_archetype = None
        best_bss = -1.0
        
        for archetype, data in archetype_performance.items():
            performance = data.get("performance", {})
            bss = performance.get("avg_brier_skill_score", 0)
            
            if bss > best_bss:
                best_bss = bss
                best_archetype = archetype
        
        if best_archetype == current_archetype:
            return f"Current archetype ({current_archetype}) is optimal - continue using"
        else:
            return f"Recommend switching from {current_archetype} to {best_archetype} for better performance"
    
    def get_reliability_diagram_data(self, model_id: str, days: int = 30) -> Dict[str, Any]:
        """Get reliability diagram data for a model."""
        try:
            # Get recent forecasts for reliability diagram
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT prob, outcome, weight
                    FROM forecasts
                    WHERE model_id = ? AND ts_resolved >= ?
                    AND outcome IS NOT NULL
                    ORDER BY ts_resolved DESC
                    LIMIT 1000
                """, (model_id, cutoff_date))
                
                rows = cursor.fetchall()
            
            if not rows:
                return {}
            
            # Extract data
            probs = np.array([row["prob"] for row in rows])
            outcomes = np.array([row["outcome"] for row in rows])
            weights = np.array([row["weight"] for row in rows])
            
            # Generate reliability diagram
            diagram_data = self.metrics.plot_reliability_diagram(
                outcomes, probs, n_bins=10, 
                title=f"Reliability Diagram - {model_id}"
            )
            
            return {
                "model_id": model_id,
                "period_days": days,
                "n_events": len(rows),
                "diagram": diagram_data
            }
            
        except Exception as e:
            logger.error(f"Failed to get reliability diagram for {model_id}: {e}")
            return {}
    
    def get_top_models_comparison(self, limit: int = 10, days: int = 30) -> List[Dict[str, Any]]:
        """Get comparison of top performing models."""
        try:
            # Get all models with recent performance
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT model_id FROM forecast_metrics
                    WHERE window_start >= ?
                    ORDER BY model_id
                """, (cutoff_date,))
                
                model_ids = [row["model_id"] for row in cursor.fetchall()]
            
            # Get performance for each model
            model_performances = []
            
            for model_id in model_ids[:limit]:  # Limit to top N
                performance_view = self.get_model_performance_view(model_id, days)
                if performance_view:
                    model_performances.append({
                        "model_id": model_id,
                        "brier_score": performance_view.current_brier,
                        "brier_skill_score": performance_view.current_bss,
                        "quality_category": performance_view.current_quality,
                        "tier": performance_view.current_tier,
                        "calibration_improvement": performance_view.calibration_improvement
                    })
            
            # Sort by Brier Skill Score
            model_performances.sort(key=lambda x: x["brier_skill_score"], reverse=True)
            
            return model_performances
            
        except Exception as e:
            logger.error(f"Failed to get top models comparison: {e}")
            return []

# Global dashboard instance
_merid_dashboard = MERIDDashboard()

def get_merid_dashboard() -> MERIDDashboard:
    """Get the global MERID dashboard instance."""
    return _merid_dashboard
