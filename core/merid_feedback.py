"""
MERID Feedback Loop Analysis - Historical Validation and Real-World Testing

Tightens feedback loops around Brier-based governance through historical analysis,
model validation, and real-world alerting for policy iteration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
from collections import defaultdict

from core.merid_metrics import get_merid_metrics, CalibrationArchetype
from core.merid_governance import get_merid_governance, GovernanceAction, RiskTier
from core.merid_dashboard import get_merid_dashboard
from core.brier_metrics_db import get_brier_db
from utils.logger import get_logger

logger = get_logger("merid_feedback")

class DecisionDivergenceType(Enum):
    """Types of decision divergence between governance and actual."""
    PROMOTION_MISSED = "promotion_missed"      # Should have promoted but didn't
    DEMOTION_MISSED = "demotion_missed"        # Should have demoted but didn't
    PREMATURE_PROMOTION = "premature_promotion"  # Promoted too early
    PREMATURE_DEMOTION = "premature_demotion"  # Demoted too early
    CORRECT_PROMOTION = "correct_promotion"    # Promoted correctly
    CORRECT_DEMOTION = "correct_demotion"      # Demoted correctly
    NO_ACTION_NEEDED = "no_action_needed"      # No action was appropriate

@dataclass
class HistoricalDecision:
    """Historical decision record for analysis."""
    timestamp: datetime
    model_id: str
    actual_action: Optional[GovernanceAction]
    governance_action: Optional[GovernanceAction]
    brier_score: float
    brier_skill_score: float
    tier_before: str
    tier_after: str
    divergence_type: DecisionDivergenceType
    impact_score: float  # Business impact of the decision
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "model_id": self.model_id,
            "actual_action": self.actual_action.value if self.actual_action else None,
            "governance_action": self.governance_action.value if self.governance_action else None,
            "brier_score": self.brier_score,
            "brier_skill_score": self.brier_skill_score,
            "tier_before": self.tier_before,
            "tier_after": self.tier_after,
            "divergence_type": self.divergence_type.value,
            "impact_score": self.impact_score,
            "context": self.context
        }

@dataclass
class ModelValidationReport:
    """Validation report for a specific model."""
    model_id: str
    validation_period: Tuple[datetime, datetime]
    
    # Performance metrics
    avg_brier_score: float
    avg_brier_skill_score: float
    calibration_stability: float
    
    # Archetype analysis
    archetype_performance: Dict[str, Dict[str, Any]]
    recommended_archetype: str
    current_archetype: str
    
    # Validation results
    governance_consistency: float  # How consistent governance decisions are
    prediction_accuracy: float     # How well predictions match outcomes
    risk_adjusted_return: float    # Risk-adjusted performance
    
    # Recommendations
    tier_recommendation: str
    archetype_recommendation: str
    threshold_adjustments: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "model_id": self.model_id,
            "validation_period": {
                "start": self.validation_period[0].isoformat(),
                "end": self.validation_period[1].isoformat()
            },
            "performance_metrics": {
                "avg_brier_score": self.avg_brier_score,
                "avg_brier_skill_score": self.avg_brier_skill_score,
                "calibration_stability": self.calibration_stability
            },
            "archetype_analysis": {
                "performance": self.archetype_performance,
                "recommended": self.recommended_archetype,
                "current": self.current_archetype
            },
            "validation_results": {
                "governance_consistency": self.governance_consistency,
                "prediction_accuracy": self.prediction_accuracy,
                "risk_adjusted_return": self.risk_adjusted_return
            },
            "recommendations": {
                "tier": self.tier_recommendation,
                "archetype": self.archetype_recommendation,
                "threshold_adjustments": self.threshold_adjustments
            }
        }

@dataclass
class AlertConfiguration:
    """Configuration for real-time governance alerts."""
    model_id: str
    enabled: bool
    alert_types: List[str]  # ["promotion", "demotion", "degradation", "calibration_drift"]
    thresholds: Dict[str, float]  # Custom thresholds for alerts
    notification_channels: List[str]  # ["email", "slack", "webhook"]
    cooldown_minutes: int = 60  # Minimum time between alerts
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "model_id": self.model_id,
            "enabled": self.enabled,
            "alert_types": self.alert_types,
            "thresholds": self.thresholds,
            "notification_channels": self.notification_channels,
            "cooldown_minutes": self.cooldown_minutes
        }

class MERIDFeedbackLoop:
    """
    MERID Feedback Loop Analysis System
    
    Tightens feedback loops around Brier-based governance through
    historical analysis, model validation, and real-world alerting.
    """
    
    def __init__(self):
        self.db = get_brier_db()
        self.metrics = get_merid_metrics()
        self.governance = get_merid_governance()
        self.dashboard = get_merid_dashboard()
        
        # Alert configurations
        self.alert_configs: Dict[str, AlertConfiguration] = {}
        self.last_alerts: Dict[str, datetime] = {}
        
        # Historical decisions for analysis
        self.historical_decisions: List[HistoricalDecision] = []
    
    def analyze_historical_decisions(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """
        Analyze historical decisions and compare governance recommendations with actual actions.
        
        Identifies where decisions diverge to tune thresholds and tiers.
        """
        try:
            # Get historical performance data
            historical_performance = self._get_historical_performance(start_date, end_date)
            
            # Simulate governance decisions for each time window
            simulated_decisions = self._simulate_governance_decisions(historical_performance)
            
            # Compare with actual decisions (if available)
            actual_decisions = self._get_actual_decisions(start_date, end_date)
            
            # Analyze divergences
            divergence_analysis = self._analyze_decision_divergences(
                simulated_decisions, actual_decisions
            )
            
            # Generate recommendations for threshold tuning
            threshold_recommendations = self._generate_threshold_recommendations(divergence_analysis)
            
            return {
                "analysis_period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                },
                "divergence_analysis": divergence_analysis,
                "threshold_recommendations": threshold_recommendations,
                "decision_accuracy": self._calculate_decision_accuracy(simulated_decisions, actual_decisions),
                "impact_assessment": self._assess_decision_impact(divergence_analysis)
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze historical decisions: {e}")
            return {"error": str(e)}
    
    def _get_historical_performance(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get historical performance data for analysis."""
        try:
            with self.db.get_brier_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT window_start, window_end, model_id,
                           brier_score, brier_skill_score, n_events,
                           reliability, resolution, uncertainty, quality_category
                    FROM forecast_metrics
                    WHERE window_start >= ? AND window_end <= ?
                    ORDER BY window_start, model_id
                """, (start_date, end_date))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Failed to get historical performance: {e}")
            return []
    
    def _simulate_governance_decisions(self, historical_performance: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Simulate what governance decisions would have been historically."""
        simulated_decisions = []
        
        for performance in historical_performance:
            model_id = performance["model_id"]
            
            # Register temporary policy for simulation
            if model_id not in self.governance.policies:
                self.governance.register_model_policy(model_id)
            
            # Simulate evaluation
            evaluation = self.governance.evaluate_promotion_eligibility(
                model_id, days=30  # Use 30-day window for evaluation
            )
            
            simulated_decisions.append({
                "timestamp": performance["window_start"],
                "model_id": model_id,
                "performance": performance,
                "governance_evaluation": evaluation,
                "simulated_action": evaluation.get("action")
            })
        
        return simulated_decisions
    
    def _get_actual_decisions(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get actual historical decisions (if available)."""
        # This would typically come from audit logs, decision records, or manual tracking
        # For now, we'll simulate some actual decisions for demonstration
        
        actual_decisions = []
        
        # Simulate some historical decisions based on performance patterns
        historical_performance = self._get_historical_performance(start_date, end_date)
        
        for performance in historical_performance:
            model_id = performance["model_id"]
            bss = performance["brier_skill_score"] or 0.0
            
            # Simulate actual decisions (in production, this would come from real records)
            if bss > 0.10:
                action = GovernanceAction.PROMOTE
            elif bss < 0.0:
                action = GovernanceAction.DEMOTE
            else:
                action = GovernanceAction.HOLD
            
            actual_decisions.append({
                "timestamp": performance["window_start"],
                "model_id": model_id,
                "actual_action": action,
                "performance": performance
            })
        
        return actual_decisions
    
    def _analyze_decision_divergences(self, simulated_decisions: List[Dict[str, Any]], 
                                    actual_decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze where simulated and actual decisions diverge."""
        divergences = defaultdict(list)
        
        # Create lookup for actual decisions
        actual_lookup = {
            (d["timestamp"], d["model_id"]): d for d in actual_decisions
        }
        
        for sim_decision in simulated_decisions:
            key = (sim_decision["timestamp"], sim_decision["model_id"])
            
            if key in actual_lookup:
                actual = actual_lookup[key]
                sim_action = sim_decision["simulated_action"]
                actual_action = actual["actual_action"]
                
                # Classify divergence type
                divergence_type = self._classify_divergence(sim_action, actual_action)
                
                if divergence_type != DecisionDivergenceType.NO_ACTION_NEEDED:
                    divergences[divergence_type.value].append({
                        "timestamp": sim_decision["timestamp"],
                        "model_id": sim_decision["model_id"],
                        "simulated_action": sim_action,
                        "actual_action": actual_action,
                        "performance": sim_decision["performance"],
                        "impact_score": self._calculate_impact_score(sim_decision["performance"])
                    })
        
        return {
            "total_divergences": sum(len(v) for v in divergences.values()),
            "divergence_by_type": dict(divergences),
            "divergence_rate": sum(len(v) for v in divergences.values()) / len(simulated_decisions) if simulated_decisions else 0
        }
    
    def _classify_divergence(self, simulated: str, actual: str) -> DecisionDivergenceType:
        """Classify the type of decision divergence."""
        if simulated == actual:
            if simulated in ["promote", "demote"]:
                return DecisionDivergenceType.CORRECT_PROMOTION if simulated == "promote" else DecisionDivergenceType.CORRECT_DEMOTION
            else:
                return DecisionDivergenceType.NO_ACTION_NEEDED
        
        # Determine divergence type
        if simulated == "promote" and actual != "promote":
            return DecisionDivergenceType.PROMOTION_MISSED
        elif simulated == "demote" and actual != "demote":
            return DecisionDivergenceType.DEMOTION_MISSED
        elif actual == "promote" and simulated != "promote":
            return DecisionDivergenceType.PREMATURE_PROMOTION
        elif actual == "demote" and simulated != "demote":
            return DecisionDivergenceType.PREMATURE_DEMOTION
        
        return DecisionDivergenceType.NO_ACTION_NEEDED
    
    def _calculate_impact_score(self, performance: Dict[str, Any]) -> float:
        """Calculate business impact score of a decision."""
        bss = performance["brier_skill_score"] or 0.0
        n_events = performance["n_events"]
        
        # Impact = BSS * sqrt(events) - higher BSS and more events = higher impact
        return bss * np.sqrt(n_events)
    
    def _generate_threshold_recommendations(self, divergence_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate recommendations for threshold tuning based on divergence analysis."""
        recommendations = {}
        
        divergence_by_type = divergence_analysis.get("divergence_by_type", {})
        
        # Analyze promotion missed divergences
        if "promotion_missed" in divergence_by_type:
            missed_promotions = divergence_by_type["promotion_missed"]
            
            # Calculate average BSS of missed promotions
            avg_bss = np.mean([d["impact_score"] for d in missed_promotions])
            
            # Recommend lowering BSS threshold
            recommendations["bss_threshold"] = {
                "current": 0.05,
                "recommended": max(0.02, avg_bss - 0.02),
                "reason": f"Lower threshold to catch models with avg BSS of {avg_bss:.3f}",
                "confidence": len(missed_promotions) / divergence_analysis.get("total_divergences", 1)
            }
        
        # Analyze premature promotions
        if "premature_promotion" in divergence_by_type:
            premature = divergence_by_type["premature_promotion"]
            
            # Calculate average BSS of premature promotions
            avg_bss = np.mean([d["impact_score"] for d in premature])
            
            # Recommend raising BSS threshold
            recommendations["bss_threshold"] = {
                "current": 0.05,
                "recommended": min(0.10, avg_bss + 0.02),
                "reason": f"Raise threshold to avoid premature promotions with avg BSS of {avg_bss:.3f}",
                "confidence": len(premature) / divergence_analysis.get("total_divergences", 1)
            }
        
        # Analyze event threshold
        all_divergences = []
        for divergences in divergence_by_type.values():
            all_divergences.extend(divergences)
        
        if all_divergences:
            # Check if many divergences have low event counts
            low_events = [d for d in all_divergences if d["performance"]["n_events"] < 100]
            
            if len(low_events) > len(all_divergences) * 0.3:  # 30% threshold
                recommendations["events_threshold"] = {
                    "current": 100,
                    "recommended": 50,
                    "reason": f"Lower threshold as {len(low_events)} divergences had < 100 events",
                    "confidence": len(low_events) / len(all_divergences)
                }
        
        return recommendations
    
    def _calculate_decision_accuracy(self, simulated: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> float:
        """Calculate overall decision accuracy."""
        if not simulated or not actual:
            return 0.0
        
        # Create lookup for actual decisions
        actual_lookup = {
            (d["timestamp"], d["model_id"]): d for d in actual
        }
        
        correct_decisions = 0
        total_decisions = 0
        
        for sim_decision in simulated:
            key = (sim_decision["timestamp"], sim_decision["model_id"])
            
            if key in actual_lookup:
                actual_action = actual_lookup[key]["actual_action"]
                sim_action = sim_decision["simulated_action"]
                
                if sim_action == actual_action:
                    correct_decisions += 1
                
                total_decisions += 1
        
        return correct_decisions / total_decisions if total_decisions > 0 else 0.0
    
    def _assess_decision_impact(self, divergence_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Assess the business impact of decision divergences."""
        divergences_by_type = divergence_analysis.get("divergence_by_type", {})
        
        impact_assessment = {
            "total_impact_score": 0.0,
            "missed_opportunities": 0.0,
            "premature_actions": 0.0,
            "recommendations": []
        }
        
        # Calculate impact of missed promotions
        if "promotion_missed" in divergences_by_type:
            missed = divergences_by_type["promotion_missed"]
            missed_impact = sum(d["impact_score"] for d in missed)
            impact_assessment["missed_opportunities"] = missed_impact
            impact_assessment["total_impact_score"] += missed_impact
            
            if missed_impact > 100:
                impact_assessment["recommendations"].append(
                    "High impact from missed promotions - consider lowering BSS threshold"
                )
        
        # Calculate impact of premature actions
        if "premature_promotion" in divergences_by_type:
            premature = divergences_by_type["premature_promotion"]
            premature_impact = sum(d["impact_score"] for d in premature)
            impact_assessment["premature_actions"] = premature_impact
            impact_assessment["total_impact_score"] += premature_impact
            
            if premature_impact > 50:
                impact_assessment["recommendations"].append(
                    "Significant impact from premature actions - consider raising thresholds"
                )
        
        return impact_assessment
    
    def validate_top_models(self, top_n: int = 5, bottom_n: int = 5, days: int = 30) -> Dict[str, Any]:
        """
        Validate top and bottom models through full archetype analysis.
        
        Walks models through PIT vs TTC vs BASE to validate recommendations.
        """
        try:
            # Get top and bottom models by BSS
            top_models = self.dashboard.get_top_models_comparison(limit=top_n, days=days)
            bottom_models = self.dashboard.get_top_models_comparison(limit=bottom_n, days=days)
            
            # Get bottom models (reverse the list)
            bottom_models = list(reversed(bottom_models))[:bottom_n]
            
            validation_results = {}
            
            # Validate top models
            for model in top_models:
                model_id = model["model_id"]
                validation = self._validate_model_archetypes(model_id, days)
                validation_results[f"top_{model_id}"] = validation
            
            # Validate bottom models
            for model in bottom_models:
                model_id = model["model_id"]
                validation = self._validate_model_archetypes(model_id, days)
                validation_results[f"bottom_{model_id}"] = validation
            
            # Generate overall insights
            insights = self._generate_validation_insights(validation_results)
            
            return {
                "validation_period_days": days,
                "top_models_count": len(top_models),
                "bottom_models_count": len(bottom_models),
                "validation_results": validation_results,
                "insights": insights
            }
            
        except Exception as e:
            logger.error(f"Failed to validate top/bottom models: {e}")
            return {"error": str(e)}
    
    def _validate_model_archetypes(self, model_id: str, days: int) -> ModelValidationReport:
        """Validate a model through full archetype analysis."""
        try:
            # Get archetype comparison
            archetype_comparison = self.dashboard.get_archetype_comparison(model_id)
            
            # Get performance view
            performance_view = self.dashboard.get_model_performance_view(model_id, days)
            
            if not performance_view:
                raise ValueError(f"No performance data for model {model_id}")
            
            # Calculate validation metrics
            avg_brier = performance_view.current_brier
            avg_bss = performance_view.current_bss
            
            # Calculate calibration stability
            brier_values = performance_view.brier_score_ts.values
            calibration_stability = np.std(brier_values) / np.mean(brier_values) if np.mean(brier_values) > 0 else 0
            
            # Get archetype performance
            archetype_performance = archetype_comparison.get("archetype_performance", {})
            
            # Determine recommended archetype
            recommended_archetype = self._determine_best_archetype(archetype_performance)
            
            # Calculate governance consistency
            governance_consistency = self._calculate_governance_consistency(model_id, days)
            
            # Generate recommendations
            tier_recommendation = self._recommend_tier(avg_bss, performance_view.current_tier)
            threshold_adjustments = self._recommend_threshold_adjustments(avg_bss, calibration_stability)
            
            return ModelValidationReport(
                model_id=model_id,
                validation_period=(datetime.now() - timedelta(days=days), datetime.now()),
                avg_brier_score=avg_brier,
                avg_brier_skill_score=avg_bss,
                calibration_stability=calibration_stability,
                archetype_performance=archetype_performance,
                recommended_archetype=recommended_archetype,
                current_archetype=archetype_comparison.get("current_archetype", "BASE"),
                governance_consistency=governance_consistency,
                prediction_accuracy=avg_bss,  # Use BSS as proxy for prediction accuracy
                risk_adjusted_return=avg_bss * 100,  # Simple risk-adjusted return metric
                tier_recommendation=tier_recommendation,
                archetype_recommendation=f"Switch to {recommended_archetype}",
                threshold_adjustments=threshold_adjustments
            )
            
        except Exception as e:
            logger.error(f"Failed to validate model {model_id}: {e}")
            raise
    
    def _determine_best_archetype(self, archetype_performance: Dict[str, Dict[str, Any]]) -> str:
        """Determine the best performing archetype."""
        best_archetype = "BASE"
        best_bss = -1.0
        
        for archetype, data in archetype_performance.items():
            performance = data.get("performance", {})
            bss = performance.get("avg_brier_skill_score", 0)
            
            if bss > best_bss:
                best_bss = bss
                best_archetype = archetype
        
        return best_archetype
    
    def _calculate_governance_consistency(self, model_id: str, days: int) -> float:
        """Calculate how consistent governance decisions have been."""
        try:
            policy = self.governance.policies.get(model_id)
            if not policy or not policy.evaluation_history:
                return 0.0
            
            # Get recent evaluations
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_evaluations = [
                eval for eval in policy.evaluation_history
                if datetime.fromisoformat(eval["timestamp"]) > cutoff_date
            ]
            
            if not recent_evaluations:
                return 0.0
            
            # Calculate consistency (how often recommendations align with actual actions)
            consistent_actions = 0
            for eval in recent_evaluations:
                if eval["recommendation"] in ["PROMOTE", "HOLD", "DEMOTE"]:
                    consistent_actions += 1
            
            return consistent_actions / len(recent_evaluations)
            
        except Exception as e:
            logger.error(f"Failed to calculate governance consistency for {model_id}: {e}")
            return 0.0
    
    def _recommend_tier(self, bss: float, current_tier: str) -> str:
        """Recommend tier based on BSS."""
        if bss > 0.15:
            return "Promote to Tier 1 - Excellent performance"
        elif bss > 0.10 and current_tier != "tier_1":
            return "Consider promotion - Strong performance"
        elif bss < 0.0:
            return "Demote or suspend - Negative skill"
        elif bss < 0.03 and current_tier != "tier_4":
            return "Consider demotion - Poor performance"
        else:
            return "Maintain current tier"
    
    def _recommend_threshold_adjustments(self, bss: float, stability: float) -> Dict[str, float]:
        """Recommend threshold adjustments based on performance."""
        adjustments = {}
        
        if bss > 0.15:
            # High performance - could tighten thresholds
            adjustments["min_bss_vs_baseline"] = 0.08
            adjustments["min_events"] = 150
        elif bss < 0.03:
            # Poor performance - could loosen thresholds
            adjustments["min_bss_vs_baseline"] = 0.03
            adjustments["min_events"] = 50
        
        if stability > 0.5:
            # High volatility - require more consistency
            adjustments["min_consistency_windows"] = 5
            adjustments["max_volatility"] = 0.3
        
        return adjustments
    
    def _generate_validation_insights(self, validation_results: Dict[str, ModelValidationReport]) -> Dict[str, Any]:
        """Generate insights from validation results."""
        insights = {
            "top_models_insights": [],
            "bottom_models_insights": [],
            "overall_patterns": [],
            "recommendations": []
        }
        
        # Analyze top models
        top_results = {k: v for k, v in validation_results.items() if k.startswith("top_")}
        bottom_results = {k: v for k, v in validation_results.items() if k.startswith("bottom_")}
        
        # Top models patterns
        top_archetypes = [r.current_archetype for r in top_results.values()]
        top_avg_bss = np.mean([r.avg_brier_skill_score for r in top_results.values()])
        
        if top_archetypes:
            most_common_archetype = max(set(top_archetypes), key=top_archetypes.count)
            insights["top_models_insights"].append(
                f"Top models predominantly use {most_common_archetype} archetype"
            )
        
        insights["top_models_insights"].append(
            f"Top models average BSS: {top_avg_bss:.3f}"
        )
        
        # Bottom models patterns
        bottom_archetypes = [r.current_archetype for r in bottom_results.values()]
        bottom_avg_bss = np.mean([r.avg_brier_skill_score for r in bottom_results.values()])
        
        if bottom_archetypes:
            most_common_archetype = max(set(bottom_archetypes), key=bottom_archetypes.count)
            insights["bottom_models_insights"].append(
                f"Bottom models predominantly use {most_common_archetype} archetype"
            )
        
        insights["bottom_models_insights"].append(
            f"Bottom models average BSS: {bottom_avg_bss:.3f}"
        )
        
        # Overall patterns
        if top_avg_bss > 0.10 and bottom_avg_bss < 0.05:
            insights["overall_patterns"].append(
                "Clear performance gap between top and bottom models"
            )
        
        # Recommendations
        if top_avg_bss > 0.12:
            insights["recommendations"].append(
                "Consider promoting top models to higher tiers with increased limits"
            )
        
        if bottom_avg_bss < 0.0:
            insights["recommendations"].append(
                "Review bottom models for potential demotion or retirement"
            )
        
        return insights
    
    def configure_alerts(self, model_id: str, config: AlertConfiguration) -> Dict[str, Any]:
        """Configure real-time alerts for a model."""
        try:
            self.alert_configs[model_id] = config
            
            return {
                "success": True,
                "model_id": model_id,
                "configuration": config.to_dict(),
                "message": f"Alerts configured for {model_id}"
            }
            
        except Exception as e:
            logger.error(f"Failed to configure alerts for {model_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def check_alerts(self, model_id: str) -> List[Dict[str, Any]]:
        """Check if any alerts should be triggered for a model."""
        try:
            if model_id not in self.alert_configs or not self.alert_configs[model_id].enabled:
                return []
            
            config = self.alert_configs[model_id]
            
            # Check cooldown
            if model_id in self.last_alerts:
                time_since_last = datetime.now() - self.last_alerts[model_id]
                if time_since_last.total_seconds() < config.cooldown_minutes * 60:
                    return []
            
            # Get current performance
            performance_view = self.dashboard.get_model_performance_view(model_id, days=7)
            
            if not performance_view:
                return []
            
            alerts = []
            
            # Check different alert types
            if "promotion" in config.alert_types:
                promotion_alert = self._check_promotion_alert(model_id, performance_view, config)
                if promotion_alert:
                    alerts.append(promotion_alert)
            
            if "demotion" in config.alert_types:
                demotion_alert = self._check_demotion_alert(model_id, performance_view, config)
                if demotion_alert:
                    alerts.append(demotion_alert)
            
            if "degradation" in config.alert_types:
                degradation_alert = self._check_degradation_alert(model_id, performance_view, config)
                if degradation_alert:
                    alerts.append(degradation_alert)
            
            if "calibration_drift" in config.alert_types:
                calibration_alert = self._check_calibration_alert(model_id, performance_view, config)
                if calibration_alert:
                    alerts.append(calibration_alert)
            
            # Update last alert time
            if alerts:
                self.last_alerts[model_id] = datetime.now()
            
            return alerts
            
        except Exception as e:
            logger.error(f"Failed to check alerts for {model_id}: {e}")
            return []
    
    def _check_promotion_alert(self, model_id: str, performance_view: Any, config: AlertConfiguration) -> Optional[Dict[str, Any]]:
        """Check if promotion alert should be triggered."""
        try:
            current_bss = performance_view.current_bss
            threshold = config.thresholds.get("promotion_bss", 0.10)
            
            if current_bss >= threshold:
                return {
                    "type": "promotion",
                    "model_id": model_id,
                    "severity": "info",
                    "message": f"Model eligible for promotion (BSS: {current_bss:.3f} >= {threshold:.3f})",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "current_bss": current_bss,
                        "threshold": threshold,
                        "current_tier": performance_view.current_tier
                    }
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check promotion alert: {e}")
            return None
    
    def _check_demotion_alert(self, model_id: str, performance_view: Any, config: AlertConfiguration) -> Optional[Dict[str, Any]]:
        """Check if demotion alert should be triggered."""
        try:
            current_bss = performance_view.current_bss
            threshold = config.thresholds.get("demotion_bss", 0.0)
            
            if current_bss <= threshold:
                return {
                    "type": "demotion",
                    "model_id": model_id,
                    "severity": "warning",
                    "message": f"Model requires demotion (BSS: {current_bss:.3f} <= {threshold:.3f})",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "current_bss": current_bss,
                        "threshold": threshold,
                        "current_tier": performance_view.current_tier
                    }
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check demotion alert: {e}")
            return None
    
    def _check_degradation_alert(self, model_id: str, performance_view: Any, config: AlertConfiguration) -> Optional[Dict[str, Any]]:
        """Check if degradation alert should be triggered."""
        try:
            # Check if Brier score has degraded significantly
            brier_values = performance_view.brier_score_ts.values
            
            if len(brier_values) < 2:
                return None
            
            current_brier = brier_values[0]
            previous_brier = brier_values[1]
            
            degradation_threshold = config.thresholds.get("degradation_threshold", 0.20)
            
            if previous_brier > 0:
                degradation_pct = (current_brier - previous_brier) / previous_brier
                
                if degradation_pct >= degradation_threshold:
                    return {
                        "type": "degradation",
                        "model_id": model_id,
                        "severity": "warning",
                        "message": f"Model performance degraded by {degradation_pct:.1%}",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "current_brier": current_brier,
                            "previous_brier": previous_brier,
                            "degradation_pct": degradation_pct,
                            "threshold": degradation_threshold
                        }
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check degradation alert: {e}")
            return None
    
    def _check_calibration_alert(self, model_id: str, performance_view: Any, config: AlertConfiguration) -> Optional[Dict[str, Any]]:
        """Check if calibration drift alert should be triggered."""
        try:
            # Check reliability (calibration error)
            reliability = performance_view.reliability_ts.values[-1] if performance_view.reliability_ts.values else 0.0
            
            reliability_threshold = config.thresholds.get("reliability_threshold", 0.10)
            
            if reliability >= reliability_threshold:
                return {
                    "type": "calibration_drift",
                    "model_id": model_id,
                    "severity": "info",
                    "message": f"Model calibration drift detected (reliability: {reliability:.3f} >= {reliability_threshold:.3f})",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "current_reliability": reliability,
                        "threshold": reliability_threshold,
                        "recommendation": "Consider retraining calibration"
                    }
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check calibration alert: {e}")
            return None

# Global feedback loop instance
_merid_feedback_loop = MERIDFeedbackLoop()

def get_merid_feedback_loop() -> MERIDFeedbackLoop:
    """Get the global MERID feedback loop instance."""
    return _merid_feedback_loop

def get_feedback_analyzer() -> MERIDFeedbackLoop:
    """Get the global feedback analyzer instance (alias for compatibility)."""
    return _merid_feedback_loop
