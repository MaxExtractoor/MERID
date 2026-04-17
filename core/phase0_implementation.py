"""
MERID Phase 0 Implementation Note

Thin implementation layers around existing Brier/governance stack.
This provides the concrete wiring for the Phase 0 experiment.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import json

from core.merid_minimal_scope import get_minimal_live_scope, GovernanceScorecard
from core.brier_metrics_db import get_brier_db
from core.phase0_db import get_phase0_db
from utils.logger import get_logger

logger = get_logger("phase0_implementation")

@dataclass
class Phase0ExperimentRecord:
    """Phase 0 experiment record for persistence."""
    experiment_id: str
    status: str  # not_started | active | completed
    start_at: Optional[datetime]
    end_at: Optional[datetime]
    constraints: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "constraints": self.constraints,
            "created_at": self.created_at.isoformat()
        }

@dataclass
class Phase0Expectation:
    """Pre-trial expectation for validation."""
    experiment_id: str
    model_id: str
    expected_manual_tier: str
    expected_manual_limits: Dict[str, float]
    expected_binding_thresholds: Dict[str, Any]
    rationale: str
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "model_id": self.model_id,
            "expected_manual_tier": self.expected_manual_tier,
            "expected_manual_limits": self.expected_manual_limits,
            "expected_binding_thresholds": self.expected_binding_thresholds,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat()
        }

@dataclass
class Phase0WeeklyDecision:
    """Weekly decision record for the trial."""
    experiment_id: str
    week_number: int
    model_id: str
    scorecard_snapshot: Dict[str, Any]  # Serialized GovernanceScorecard
    system_recommendation: str
    human_decision: str
    decision_reason: str
    contract_tests_passed: bool
    aligned: bool  # Whether human decision matches system recommendation
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "week_number": self.week_number,
            "model_id": self.model_id,
            "scorecard_snapshot": self.scorecard_snapshot,
            "system_recommendation": self.system_recommendation,
            "human_decision": self.human_decision,
            "decision_reason": self.decision_reason,
            "contract_tests_passed": self.contract_tests_passed,
            "aligned": self.aligned,
            "created_at": self.created_at.isoformat()
        }

class Phase0Service:
    """
    Thin Phase 0 service layer.
    
    Owns trial config, decision records, and metrics computation.
    Reuses existing Brier/governance stack.
    """
    
    def __init__(self):
        self.db = get_brier_db()
        self.phase0_db = get_phase0_db()
        self.scope = get_minimal_live_scope()
        
        # Initialize Phase 0 tables
        self.phase0_db.initialize_phase0_tables()
        
        # Phase 0 constraints (hard-coded for safety)
        self.constraints = {
            "max_notional": 100000,
            "tier_caps": ["tier_2", "tier_3", "tier_4"],
            "auto_execution_disabled": True,
            "trial_duration_weeks": 6,
            "max_position_per_model": 50000,
            "max_daily_volume_per_model": 200000
        }
        
        # Validation criteria
        self.validation_criteria = {
            "decision_alignment_threshold": 0.7,
            "contract_test_compliance_threshold": 0.95,
            "minimum_trial_duration_weeks": 4,
            "minimum_decisions": 8,
            "recent_compliance_weeks": 4
        }
    
    def start_experiment(self, models: List[str]) -> Dict[str, Any]:
        """Start Phase 0 experiment with given models."""
        try:
            experiment_id = f"phase0_{datetime.now().strftime('%Y%m%d')}"
            
            # Create experiment record
            experiment = Phase0ExperimentRecord(
                experiment_id=experiment_id,
                status="active",
                start_at=datetime.now(),
                end_at=datetime.now() + timedelta(weeks=self.constraints["trial_duration_weeks"]),
                constraints=self.constraints
            )
            
            # Store experiment (simplified - would use actual database)
            self._store_experiment(experiment)
            
            # Apply constraints to governance system
            self._apply_constraints(models)
            
            # Generate initial scorecards
            initial_scorecards = []
            for model_id in models:
                scorecard = self.scope.generate_governance_scorecard(model_id)
                initial_scorecards.append(scorecard.to_dict())
            
            logger.info(f"Phase 0 experiment started: {experiment_id}")
            
            return {
                "success": True,
                "experiment_id": experiment_id,
                "constraints": self.constraints,
                "initial_scorecards": initial_scorecards,
                "message": f"Phase 0 experiment started for {len(models)} models"
            }
            
        except Exception as e:
            logger.error(f"Failed to start experiment: {e}")
            return {"success": False, "error": str(e)}
    
    def record_weekly_decision(self, model_id: str, human_decision: str, reason: str) -> Dict[str, Any]:
        """Record weekly decision for the trial with enhanced error handling and recovery."""
        try:
            # Validate inputs
            if not model_id or not model_id.strip():
                return {"success": False, "error": "Model ID cannot be empty"}
            
            if not human_decision or not human_decision.strip():
                return {"success": False, "error": "Human decision cannot be empty"}
            
            if not reason or not reason.strip():
                return {"success": False, "error": "Decision reason cannot be empty"}
            
            # Validate human decision
            valid_decisions = ['promote', 'demote', 'hold', 'suspend', 'retire']
            if human_decision.lower() not in valid_decisions:
                return {
                    "success": False, 
                    "error": f"Invalid decision '{human_decision}'. Valid options: {', '.join(valid_decisions)}"
                }
            
            # Normalize decision to lowercase
            human_decision = human_decision.lower()
            
            # Get current experiment
            experiment = self._get_active_experiment()
            if not experiment:
                return {"success": False, "error": "No active experiment"}
            
            # Get current scorecard with enhanced error handling
            try:
                scorecard = self.scope.generate_governance_scorecard(model_id)
                scorecard_snapshot = scorecard.to_dict()
                system_recommendation = scorecard.suggested_action
                metrics_state = scorecard_snapshot.get("data_state", {}).get("metrics_state", "AVAILABLE")
                fallback_results = None
                logger.info(f"Generated full scorecard for {model_id}")
                
            except ValueError as e:
                error_msg = str(e)
                if "No performance data available" in error_msg or "No governance policy found" in error_msg:
                    logger.warning(
                        "phase0_missing_data_but_persisting",
                        model_id=model_id,
                        error=error_msg,
                    )
                    try:
                        scorecard_snapshot, fallback_results = self._build_minimal_scorecard_snapshot(model_id)
                        system_recommendation = scorecard_snapshot["governance"]["suggested_action"]
                        metrics_state = "MISSING"
                        logger.info(f"Created minimal scorecard for {model_id}")
                    except Exception as fallback_error:
                        logger.error(f"Failed to create minimal scorecard for {model_id}: {fallback_error}")
                        return {
                            "success": False, 
                            "error": f"Failed to generate scorecard and fallback failed: {fallback_error}"
                        }
                else:
                    logger.error(f"Unexpected error generating scorecard for {model_id}: {e}")
                    return {"success": False, "error": f"Scorecard generation failed: {error_msg}"}
            
            except Exception as e:
                logger.error(f"Unexpected error generating scorecard for {model_id}: {e}")
                return {"success": False, "error": f"Unexpected error: {str(e)}"}
            
            # Run contract tests with error handling
            try:
                contract_results = self.scope.contract_tests.run_all_contract_tests(model_id)
                contract_tests_passed = all(
                    result for result in contract_results.values() 
                    if isinstance(result, bool)
                )
                logger.info(f"Contract tests completed for {model_id}: {contract_tests_passed}")
            except Exception as e:
                logger.error(f"Contract tests failed for {model_id}: {e}")
                contract_results = {}
                contract_tests_passed = False
            
            # Calculate alignment
            alignment = (human_decision == system_recommendation)
            
            # Create weekly decision record
            try:
                weekly_decision = Phase0WeeklyDecision(
                    model_id=model_id,
                    week_number=self._get_current_week_number(),
                    human_decision=human_decision,
                    decision_reason=reason,
                    system_recommendation=system_recommendation,
                    alignment=alignment,
                    contract_tests_passed=contract_tests_passed,
                    scorecard_snapshot=scorecard_snapshot,
                    metrics_state=metrics_state,
                    fallback_results=fallback_results
                )
                logger.info(f"Created weekly decision record for {model_id}")
            except Exception as e:
                logger.error(f"Failed to create weekly decision record: {e}")
                return {"success": False, "error": f"Failed to create decision record: {str(e)}"}
            
            # Store decision with error handling
            try:
                self.decisions.append(weekly_decision)
                logger.info(f"Stored decision for {model_id}, total decisions: {len(self.decisions)}")
            except Exception as e:
                logger.error(f"Failed to store decision: {e}")
                return {"success": False, "error": f"Failed to store decision: {str(e)}"}
            
            # Update experiment metrics
            try:
                if experiment:
                    experiment.record_decision(weekly_decision)
                    logger.info(f"Updated experiment metrics for {model_id}")
            except Exception as e:
                logger.warning(f"Failed to update experiment metrics (non-critical): {e}")
            
            # Return success response
            return {
                "success": True,
                "decision": weekly_decision.to_dict(),
                "analysis": {
                    "model_id": model_id,
                    "system_recommendation": system_recommendation,
                    "human_decision": human_decision,
                    "alignment": alignment,
                    "contract_tests_passed": contract_tests_passed,
                    "metrics_state": metrics_state,
                    "fallback_used": fallback_results is not None
                }
            }
            
        except Exception as e:
            logger.error(f"Unexpected error in record_weekly_decision: {e}")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
    
    def _build_minimal_scorecard_snapshot(self, model_id: str) -> Tuple[Dict[str, Any], Dict[str, bool]]:
        """Create a minimal scorecard snapshot when performance data is missing."""
        policy = self.scope.governance.policies.get(model_id)
        if not policy:
            # Register policy if not found (fallback)
            logger.warning(f"Policy not found for {model_id}, registering fallback policy")
            from core.merid_governance import CalibrationArchetype, RiskTier
            preferred_archetype = self.scope.config.CALIBRATION_ARCHETYPES.get(model_id, CalibrationArchetype.PIT)
            policy = self.scope.governance.register_model_policy(
                model_id=model_id,
                preferred_archetype=preferred_archetype,
                initial_tier=RiskTier.TIER_3
            )
        
        contract_results = self.scope.contract_tests.run_all_contract_tests(model_id)
        snapshot = {
            "model_id": model_id,
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                "brier_score": None,
                "brier_skill_score": None,
                "calibration_archetype": policy.preferred_archetype.value,
                "n_events": 0,
                "has_performance_data": False
            },
            "governance": {
                "current_tier": policy.current_tier.value,
                "risk_limits": policy.risk_limits.to_dict(),
                "suggested_action": "hold",
                "action_reason": "No performance data available - conservative hold",
                "confidence": 0.0
            },
            "safety": {
                "contract_tests": contract_results,
                "all_passed": all(
                    result for result in contract_results.values() if isinstance(result, bool)
                )
            },
            "human_review": {
                "status": self.scope.human_reviews.get(model_id, {}).get("status", "pending"),
                "notes": self.scope.human_reviews.get(model_id, {}).get("notes")
            },
            "data_state": {
                "metrics_state": "MISSING"
            }
        }
        return snapshot, contract_results
    
    def compute_metrics(self) -> Dict[str, Any]:
        """Compute Phase 0 metrics: alignment, compliance, ready_to_scale."""
        try:
            experiment = self._get_active_experiment()
            if not experiment:
                return {"error": "No active experiment"}
            
            # Get all decisions for this experiment
            decisions = self._get_decisions(experiment.experiment_id)
            
            if not decisions:
                return {
                    "decision_alignment_rate": 0.0,
                    "contract_test_compliance_rate": 0.0,
                    "ready_to_scale": False,
                    "total_decisions": 0
                }
            
            # Calculate alignment rate
            aligned_count = sum(1 for d in decisions if d.aligned)
            decision_alignment_rate = aligned_count / len(decisions)
            
            # Calculate contract test compliance
            compliant_count = sum(1 for d in decisions if d.contract_tests_passed)
            contract_test_compliance_rate = compliant_count / len(decisions)
            
            # Check ready_to_scale criteria
            recent_decisions = [
                d for d in decisions
                if (datetime.now() - d.created_at).days <= (self.validation_criteria["recent_compliance_weeks"] * 7)
            ]
            
            recent_compliance = all(d.contract_tests_passed for d in recent_decisions) if recent_decisions else False
            
            ready_to_scale = (
                decision_alignment_rate >= self.validation_criteria["decision_alignment_threshold"] and
                contract_test_compliance_rate >= self.validation_criteria["contract_test_compliance_threshold"] and
                len(decisions) >= self.validation_criteria["minimum_decisions"] and
                recent_compliance
            )
            
            return {
                "decision_alignment_rate": decision_alignment_rate,
                "contract_test_compliance_rate": contract_test_compliance_rate,
                "ready_to_scale": ready_to_scale,
                "total_decisions": len(decisions),
                "recent_decisions": len(recent_decisions),
                "validation_criteria": self.validation_criteria
            }
            
        except Exception as e:
            logger.error(f"Failed to compute metrics: {e}")
            return {"error": str(e)}
    
    def complete_experiment(self) -> Dict[str, Any]:
        """Complete experiment and generate final analysis."""
        try:
            experiment = self._get_active_experiment()
            if not experiment:
                return {"success": False, "error": "No active experiment"}
            
            # Compute final metrics
            metrics = self.compute_metrics()
            
            # Mark as completed
            experiment.status = "completed"
            experiment.end_at = datetime.now()
            self._store_experiment(experiment)
            
            # Generate policy recommendations
            recommendations = self._generate_policy_recommendations(metrics)
            
            logger.info(f"Phase 0 experiment completed: {experiment.experiment_id}")
            
            return {
                "success": True,
                "experiment_id": experiment.experiment_id,
                "metrics": metrics,
                "recommendations": recommendations,
                "message": "Phase 0 experiment completed successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to complete experiment: {e}")
            return {"success": False, "error": str(e)}
    
    def get_experiment_status(self) -> Dict[str, Any]:
        """Get current experiment status."""
        try:
            experiment = self._get_active_experiment()
            
            if not experiment:
                return {
                    "status": "not_started",
                    "message": "No active experiment",
                    "constraints": self.constraints
                }
            
            # Get metrics
            metrics = self.compute_metrics()
            
            return {
                "status": experiment.status,
                "experiment_id": experiment.experiment_id,
                "trial_period": {
                    "start": experiment.start_at.isoformat(),
                    "end": experiment.end_at.isoformat(),
                    "duration_weeks": self.constraints["trial_duration_weeks"]
                },
                "constraints": experiment.constraints,
                "metrics": metrics,
                "message": f"Experiment {experiment.status}"
            }
            
        except Exception as e:
            logger.error(f"Failed to get experiment status: {e}")
            return {"error": str(e)}
    
    def get_weekly_decisions(self, week_number: Optional[int] = None, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get weekly decisions, optionally filtered."""
        try:
            experiment = self._get_active_experiment()
            if not experiment:
                return []
            
            decisions = self._get_decisions(experiment.experiment_id)
            
            # Apply filters
            if week_number:
                decisions = [d for d in decisions if d.week_number == week_number]
            
            if model_id:
                decisions = [d for d in decisions if d.model_id == model_id]
            
            return [d.to_dict() for d in decisions]
            
        except Exception as e:
            logger.error(f"Failed to get weekly decisions: {e}")
            return []
    
    def _apply_constraints(self, models: List[str]) -> None:
        """Apply Phase 0 constraints to governance system."""
        try:
            # This would integrate with your existing governance system
            # For now, just log the constraints being applied
            logger.info(f"Applying Phase 0 constraints to models: {models}")
            logger.info(f"Tier caps: {self.constraints['tier_caps']}")
            logger.info(f"Max notional: ${self.constraints['max_notional']}")
            logger.info(f"Auto-execution disabled: {self.constraints['auto_execution_disabled']}")
            
        except Exception as e:
            logger.error(f"Failed to apply constraints: {e}")
    
    def _generate_policy_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        """Generate policy recommendations based on trial results."""
        try:
            recommendations = []
            
            alignment_rate = metrics.get("decision_alignment_rate", 0.0)
            compliance_rate = metrics.get("contract_test_compliance_rate", 0.0)
            
            if alignment_rate >= 0.8 and compliance_rate >= 0.95:
                recommendations.append("System behavior validated - ready to add third model")
                recommendations.append("Consider loosening tier caps to allow Tier 1")
                recommendations.append("Enable auto-execution for non-critical actions")
            elif alignment_rate < 0.7:
                recommendations.append(f"Low alignment rate ({alignment_rate:.1%}) - consider adjusting BSS threshold")
            elif compliance_rate < 0.95:
                recommendations.append(f"Contract test compliance ({compliance_rate:.1%}) - investigate failed tests")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return ["Error generating recommendations"]
    
    # Database persistence methods
    def _store_experiment(self, experiment: Phase0ExperimentRecord) -> None:
        """Store experiment record."""
        experiment_data = {
            "experiment_id": experiment.experiment_id,
            "status": experiment.status,
            "start_at": experiment.start_at,
            "end_at": experiment.end_at,
            "constraints": json.dumps(experiment.constraints)
        }
        self.phase0_db.store_experiment(experiment_data)
    
    def _store_decision(self, decision: Phase0WeeklyDecision) -> None:
        """Store decision record."""
        decision_data = {
            "experiment_id": decision.experiment_id,
            "week_number": decision.week_number,
            "model_id": decision.model_id,
            "scorecard_snapshot": json.dumps(decision.scorecard_snapshot),
            "system_recommendation": decision.system_recommendation,
            "human_decision": decision.human_decision,
            "decision_reason": decision.decision_reason,
            "contract_tests_passed": decision.contract_tests_passed,
            "aligned": decision.aligned
        }
        self.phase0_db.store_weekly_decision(decision_data)
    
    def _get_active_experiment(self) -> Optional[Phase0ExperimentRecord]:
        """Get active experiment."""
        exp_data = self.phase0_db.get_active_experiment()
        if exp_data:
            return Phase0ExperimentRecord(
                experiment_id=exp_data["experiment_id"],
                status=exp_data["status"],
                start_at=exp_data["start_at"],
                end_at=exp_data["end_at"],
                constraints=json.loads(exp_data["constraints"])
            )
        return None
    
    def _get_decisions(self, experiment_id: str) -> List[Phase0WeeklyDecision]:
        """Get decisions for experiment."""
        decisions_data = self.phase0_db.get_weekly_decisions(experiment_id)
        return [
            Phase0WeeklyDecision(
                experiment_id=d["experiment_id"],
                week_number=d["week_number"],
                model_id=d["model_id"],
                scorecard_snapshot=json.loads(d["scorecard_snapshot"]),
                system_recommendation=d["system_recommendation"],
                human_decision=d["human_decision"],
                decision_reason=d["decision_reason"],
                contract_tests_passed=d["contract_tests_passed"],
                aligned=d["aligned"]
            )
            for d in decisions_data
        ]

# Global Phase 0 service instance
_phase0_service = Phase0Service()

def get_phase0_service() -> Phase0Service:
    """Get the global Phase 0 service instance."""
    return _phase0_service
