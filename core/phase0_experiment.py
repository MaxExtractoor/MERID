"""
MERID Phase 0 Experiment - Controlled Trial Implementation

Explicit 4-6 week trial with hard constraints, pre-trial expectations,
and scorecard standardization for governance validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json
from datetime import datetime, timedelta

from core.merid_minimal_scope import get_minimal_live_scope, GovernanceScorecard
from core.merid_governance import RiskTier
from utils.logger import get_logger

logger = get_logger("phase0_experiment")

class ExperimentPhase(Enum):
    """Phases of the Phase 0 experiment."""
    PRE_TRIAL = "pre_trial"
    ACTIVE = "active"
    POST_TRIAL = "post_trial"
    COMPLETED = "completed"

@dataclass
class TrialConstraints:
    """Hard constraints for the Phase 0 trial."""
    max_notional: float = 100000  # $100K max notional
    tier_caps: List[str] = field(default_factory=lambda: ["tier_2", "tier_3", "tier_4"])  # No Tier 1
    auto_execution_disabled: bool = True  # Recommendations only
    trial_duration_weeks: int = 6  # 6 weeks
    max_position_per_model: float = 50000  # $50K per model
    max_daily_volume_per_model: float = 200000  # $200K per model
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "max_notional": self.max_notional,
            "tier_caps": self.tier_caps,
            "auto_execution_disabled": self.auto_execution_disabled,
            "trial_duration_weeks": self.trial_duration_weeks,
            "max_position_per_model": self.max_position_per_model,
            "max_daily_volume_per_model": self.max_daily_volume_per_model
        }

@dataclass
class PreTrialExpectation:
    """Pre-trial expectations for validation."""
    model_id: str
    expected_manual_tier: str
    expected_manual_limits: Dict[str, float]
    expected_binding_thresholds: Dict[str, Any]
    rationale: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "model_id": self.model_id,
            "expected_manual_tier": self.expected_manual_tier,
            "expected_manual_limits": self.expected_manual_limits,
            "expected_binding_thresholds": self.expected_binding_thresholds,
            "rationale": self.rationale
        }

@dataclass
class WeeklyDecision:
    """Weekly governance decision record."""
    week_number: int
    model_id: str
    scorecard: GovernanceScorecard
    system_recommendation: str
    human_decision: Optional[str]
    decision_reason: Optional[str]
    contract_tests_passed: bool
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "week_number": self.week_number,
            "model_id": self.model_id,
            "scorecard": self.scorecard.to_dict(),
            "system_recommendation": self.system_recommendation,
            "human_decision": self.human_decision,
            "decision_reason": self.decision_reason,
            "contract_tests_passed": self.contract_tests_passed,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class TrialResults:
    """Results of the Phase 0 trial."""
    trial_id: str
    start_date: datetime
    end_date: datetime
    
    # Pre-trial expectations
    pre_trial_expectations: List[PreTrialExpectation]
    
    # Weekly decisions
    weekly_decisions: List[WeeklyDecision]
    
    # Post-trial analysis
    decision_alignment_rate: float
    contract_test_compliance_rate: float
    threshold_binding_analysis: Dict[str, Any]
    policy_change_recommendations: List[str]
    
    # Validation summary
    system_behavior_validated: bool
    ready_to_scale: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "trial_id": self.trial_id,
            "trial_period": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat()
            },
            "pre_trial_expectations": [exp.to_dict() for exp in self.pre_trial_expectations],
            "weekly_decisions": [dec.to_dict() for dec in self.weekly_decisions],
            "post_trial_analysis": {
                "decision_alignment_rate": self.decision_alignment_rate,
                "contract_test_compliance_rate": self.contract_test_compliance_rate,
                "threshold_binding_analysis": self.threshold_binding_analysis,
                "policy_change_recommendations": self.policy_change_recommendations
            },
            "validation_summary": {
                "system_behavior_validated": self.system_behavior_validated,
                "ready_to_scale": self.ready_to_scale
            }
        }

class Phase0Experiment:
    """
    MERID Phase 0 Experiment Implementation
    
    Controlled 4-6 week trial with explicit constraints and validation.
    """
    
    def __init__(self):
        self.scope = get_minimal_live_scope()
        self.constraints = TrialConstraints()
        self.current_phase = ExperimentPhase.PRE_TRIAL
        self.trial_start_date: Optional[datetime] = None
        self.trial_end_date: Optional[datetime] = None
        self.weekly_decisions: List[WeeklyDecision] = []
        self.pre_trial_expectations: List[PreTrialExpectation] = []
        
        # Trial configuration
        self.trial_id = f"phase0_trial_{datetime.now().strftime('%Y%m%d')}"
    
    def setup_pre_trial_expectations(self) -> Dict[str, Any]:
        """
        Set up pre-trial expectations for validation.
        
        What we would do manually today vs what we expect the system to recommend.
        """
        try:
            logger.info("Setting up pre-trial expectations")
            
            # Expectation for crypto_prediction_agent_v1
            crypto_expectation = PreTrialExpectation(
                model_id="crypto_prediction_agent_v1",
                expected_manual_tier="tier_3",
                expected_manual_limits={
                    "max_position_size": 20000,
                    "max_daily_volume": 80000,
                    "max_leverage": 1.2
                },
                expected_binding_thresholds={
                    "bss_threshold": "Expected to bind at 0.05 - model currently around 0.12",
                    "events_threshold": "Not binding - model has 150+ events",
                    "degradation_threshold": "Not binding unless performance drops 15%",
                    "reliability_threshold": "May bind if calibration drifts above 0.05"
                },
                rationale="Strong BSS (0.12) but limited history, conservative tier assignment"
            )
            
            # Expectation for arbitrage_analyst_v2
            arbitrage_expectation = PreTrialExpectation(
                model_id="arbitrage_analyst_v2",
                expected_manual_tier="tier_3",
                expected_manual_limits={
                    "max_position_size": 20000,
                    "max_daily_volume": 80000,
                    "max_leverage": 1.2
                },
                expected_binding_thresholds={
                    "bss_threshold": "May bind - model BSS around 0.08, close to 0.05 threshold",
                    "events_threshold": "Not binding - model has 120+ events",
                    "degradation_threshold": "Could bind if arbitrage opportunities dry up",
                    "reliability_threshold": "Likely binding - TTC calibration can drift"
                },
                rationale="Moderate BSS (0.08) with TTC archetype, needs more stability data"
            )
            
            self.pre_trial_expectations = [crypto_expectation, arbitrage_expectation]
            
            return {
                "success": True,
                "expectations": [exp.to_dict() for exp in self.pre_trial_expectations],
                "message": f"Pre-trial expectations set for {len(self.pre_trial_expectations)} models"
            }
            
        except Exception as e:
            logger.error(f"Failed to set up pre-trial expectations: {e}")
            return {"success": False, "error": str(e)}
    
    def start_trial(self) -> Dict[str, Any]:
        """
        Start the Phase 0 trial with hard constraints.
        
        Applies trial constraints and begins monitoring period.
        """
        try:
            logger.info(f"Starting Phase 0 trial: {self.trial_id}")
            
            # Set trial dates
            self.trial_start_date = datetime.now()
            self.trial_end_date = self.trial_start_date + timedelta(weeks=self.constraints.trial_duration_weeks)
            
            # Apply trial constraints
            self._apply_trial_constraints()
            
            # Update phase
            self.current_phase = ExperimentPhase.ACTIVE
            
            # Generate initial scorecards
            initial_scorecards = self.scope.get_all_scorecards()
            
            logger.info(f"Phase 0 trial started - Duration: {self.constraints.trial_duration_weeks} weeks")
            
            return {
                "success": True,
                "trial_id": self.trial_id,
                "trial_period": {
                    "start": self.trial_start_date.isoformat(),
                    "end": self.trial_end_date.isoformat(),
                    "duration_weeks": self.constraints.trial_duration_weeks
                },
                "constraints": self.constraints.to_dict(),
                "initial_scorecards": [sc.to_dict() for sc in initial_scorecards],
                "message": "Phase 0 trial started successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to start Phase 0 trial: {e}")
            return {"success": False, "error": str(e)}
    
    def _apply_trial_constraints(self) -> None:
        """Apply trial constraints to the governance system."""
        try:
            # Apply tier caps (no Tier 1 during trial)
            for model_id in self.scope.config.FOCUSED_MODELS:
                policy = self.scope.governance.policies.get(model_id)
                if policy:
                    current_tier = policy.current_tier
                    
                    # Cap at Tier 2 if currently Tier 1
                    if current_tier == RiskTier.TIER_1:
                        self.scope.governance.execute_governance_action(
                            model_id, 
                            self.scope.governance.GovernanceAction.DEMOTE
                        )
                        logger.info(f"Capped {model_id} at Tier 2 for trial")
                    
                    # Apply position limits
                    risk_limits = policy.risk_limits
                    risk_limits.max_position_size = min(
                        risk_limits.max_position_size,
                        self.constraints.max_position_per_model
                    )
                    risk_limits.max_daily_volume = min(
                        risk_limits.max_daily_volume,
                        self.constraints.max_daily_volume_per_model
                    )
                    
                    logger.info(f"Applied trial constraints to {model_id}")
            
        except Exception as e:
            logger.error(f"Failed to apply trial constraints: {e}")
    
    def record_weekly_decision(self, model_id: str, human_decision: str, decision_reason: str) -> Dict[str, Any]:
        """
        Record weekly governance decision for the trial.
        
        Captures system recommendation, human decision, and validation status.
        """
        try:
            if self.current_phase != ExperimentPhase.ACTIVE:
                raise ValueError("Trial is not currently active")
            
            # Get current scorecard
            scorecard = self.scope.generate_governance_scorecard(model_id)
            
            # Calculate week number
            if self.trial_start_date:
                week_number = ((datetime.now() - self.trial_start_date).days // 7) + 1
            else:
                week_number = 1
            
            # Record decision
            weekly_decision = WeeklyDecision(
                week_number=week_number,
                model_id=model_id,
                scorecard=scorecard,
                system_recommendation=scorecard.suggested_action,
                human_decision=human_decision,
                decision_reason=decision_reason,
                contract_tests_passed=scorecard.contract_tests.get("all_passed", False),
                timestamp=datetime.now()
            )
            
            self.weekly_decisions.append(weekly_decision)
            
            # Submit human review
            self.scope.submit_human_review(
                model_id=model_id,
                action=human_decision,
                notes=decision_reason,
                reviewer="phase0_trial"
            )
            
            logger.info(f"Recorded weekly decision for {model_id}: {human_decision} (system: {scorecard.suggested_action})")
            
            return {
                "success": True,
                "decision": weekly_decision.to_dict(),
                "message": f"Weekly decision recorded for {model_id}"
            }
            
        except Exception as e:
            logger.error(f"Failed to record weekly decision: {e}")
            return {"success": False, "error": str(e)}
    
    def get_trial_status(self) -> Dict[str, Any]:
        """Get current trial status and progress."""
        try:
            if self.current_phase == ExperimentPhase.PRE_TRIAL:
                return {
                    "phase": "pre_trial",
                    "status": "Trial not started",
                    "next_action": "Call start_trial() to begin"
                }
            
            elif self.current_phase == ExperimentPhase.ACTIVE:
                # Calculate progress
                if self.trial_start_date and self.trial_end_date:
                    total_days = (self.trial_end_date - self.trial_start_date).days
                    elapsed_days = (datetime.now() - self.trial_start_date).days
                    progress_pct = min(elapsed_days / total_days, 1.0)
                else:
                    progress_pct = 0.0
                
                # Get recent decisions
                recent_decisions = [
                    dec for dec in self.weekly_decisions
                    if (datetime.now() - dec.timestamp).days <= 7
                ]
                
                return {
                    "phase": "active",
                    "trial_id": self.trial_id,
                    "progress": {
                        "start_date": self.trial_start_date.isoformat(),
                        "end_date": self.trial_end_date.isoformat(),
                        "elapsed_days": elapsed_days,
                        "total_days": total_days,
                        "progress_pct": progress_pct
                    },
                    "constraints": self.constraints.to_dict(),
                    "recent_decisions": [dec.to_dict() for dec in recent_decisions],
                    "weekly_summary": {
                        "total_decisions": len(self.weekly_decisions),
                        "current_week": ((datetime.now() - self.trial_start_date).days // 7) + 1 if self.trial_start_date else 1,
                        "contract_test_compliance": sum(1 for dec in self.weekly_decisions if dec.contract_tests_passed) / len(self.weekly_decisions) if self.weekly_decisions else 0.0
                    }
                }
            
            elif self.current_phase == ExperimentPhase.POST_TRIAL:
                return {
                    "phase": "post_trial",
                    "status": "Trial completed, analysis in progress",
                    "next_action": "Call complete_trial() to generate final results"
                }
            
            else:
                return {
                    "phase": "completed",
                    "status": "Trial completed and analyzed"
                }
                
        except Exception as e:
            logger.error(f"Failed to get trial status: {e}")
            return {"error": str(e)}
    
    def complete_trial(self) -> Dict[str, Any]:
        """
        Complete the trial and generate comprehensive results.
        
        Analyzes decisions vs expectations, contract test compliance,
        and provides policy change recommendations.
        """
        try:
            logger.info(f"Completing Phase 0 trial: {self.trial_id}")
            
            if self.current_phase != ExperimentPhase.ACTIVE:
                raise ValueError("Trial is not currently active")
            
            # Update phase
            self.current_phase = ExperimentPhase.POST_TRIAL
            
            # Analyze results
            results = self._analyze_trial_results()
            
            # Update phase to completed
            self.current_phase = ExperimentPhase.COMPLETED
            
            logger.info(f"Phase 0 trial completed - Ready to scale: {results.ready_to_scale}")
            
            return {
                "success": True,
                "results": results.to_dict(),
                "message": "Phase 0 trial completed successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to complete trial: {e}")
            return {"success": False, "error": str(e)}
    
    def _analyze_trial_results(self) -> TrialResults:
        """Analyze trial results and generate recommendations."""
        try:
            # Calculate decision alignment rate
            alignment_count = sum(
                1 for dec in self.weekly_decisions
                if dec.human_decision == dec.system_recommendation
            )
            decision_alignment_rate = alignment_count / len(self.weekly_decisions) if self.weekly_decisions else 0.0
            
            # Calculate contract test compliance rate
            compliance_count = sum(
                1 for dec in self.weekly_decisions
                if dec.contract_tests_passed
            )
            contract_test_compliance_rate = compliance_count / len(self.weekly_decisions) if self.weekly_decisions else 0.0
            
            # Analyze threshold binding
            threshold_binding_analysis = self._analyze_threshold_binding()
            
            # Generate policy change recommendations
            policy_change_recommendations = self._generate_policy_recommendations()
            
            # Determine validation status
            system_behavior_validated = (
                decision_alignment_rate >= 0.7 and  # 70%+ alignment
                contract_test_compliance_rate >= 0.95  # 95%+ contract test compliance
            )
            
            ready_to_scale = (
                system_behavior_validated and
                len(self.weekly_decisions) >= 8 and  # At least 4 weeks of decisions
                all(dec.contract_tests_passed for dec in self.weekly_decisions[-4:])  # Recent compliance
            )
            
            return TrialResults(
                trial_id=self.trial_id,
                start_date=self.trial_start_date,
                end_date=self.trial_end_date,
                pre_trial_expectations=self.pre_trial_expectations,
                weekly_decisions=self.weekly_decisions,
                decision_alignment_rate=decision_alignment_rate,
                contract_test_compliance_rate=contract_test_compliance_rate,
                threshold_binding_analysis=threshold_binding_analysis,
                policy_change_recommendations=policy_change_recommendations,
                system_behavior_validated=system_behavior_validated,
                ready_to_scale=ready_to_scale
            )
            
        except Exception as e:
            logger.error(f"Failed to analyze trial results: {e}")
            raise
    
    def _analyze_threshold_binding(self) -> Dict[str, Any]:
        """Analyze which thresholds were binding during the trial."""
        try:
            binding_analysis = {
                "bss_threshold_binding": 0,
                "events_threshold_binding": 0,
                "degradation_threshold_binding": 0,
                "reliability_threshold_binding": 0,
                "most_binding_threshold": None,
                "threshold_effectiveness": {}
            }
            
            for model_id in self.scope.config.FOCUSED_MODELS:
                model_decisions = [dec for dec in self.weekly_decisions if dec.model_id == model_id]
                
                if model_decisions:
                    # Analyze binding patterns for this model
                    model_binding = {
                        "bss_threshold_binding": 0,
                        "events_threshold_binding": 0,
                        "degradation_threshold_binding": 0,
                        "reliability_threshold_binding": 0
                    }
                    
                    for decision in model_decisions:
                        scorecard = decision.scorecard
                        
                        # Check if BSS threshold was binding (system recommended hold due to low BSS)
                        if (decision.system_recommendation == "hold" and 
                            scorecard.brier_skill_score < 0.05):
                            model_binding["bss_threshold_binding"] += 1
                        
                        # Check if events threshold was binding
                        if (decision.system_recommendation == "hold" and 
                            scorecard.n_events < 100):
                            model_binding["events_threshold_binding"] += 1
                        
                        # Check if degradation triggered
                        if decision.decision_reason and "degradation" in decision.decision_reason.lower():
                            model_binding["degradation_threshold_binding"] += 1
                        
                        # Check if reliability issues
                        if decision.decision_reason and "reliability" in decision.decision_reason.lower():
                            model_binding["reliability_threshold_binding"] += 1
                    
                    binding_analysis["threshold_effectiveness"][model_id] = model_binding
            
            return binding_analysis
            
        except Exception as e:
            logger.error(f"Failed to analyze threshold binding: {e}")
            return {}
    
    def _generate_policy_recommendations(self) -> List[str]:
        """Generate policy change recommendations based on trial results."""
        try:
            recommendations = []
            
            # Analyze decision alignment
            alignment_count = sum(
                1 for dec in self.weekly_decisions
                if dec.human_decision == dec.system_recommendation
            )
            alignment_rate = alignment_count / len(self.weekly_decisions) if self.weekly_decisions else 0.0
            
            if alignment_rate < 0.7:
                recommendations.append(
                    f"Low alignment rate ({alignment_rate:.1%}) - consider adjusting BSS threshold from 0.05"
                )
            elif alignment_rate > 0.9:
                recommendations.append(
                    f"High alignment rate ({alignment_rate:.1%}) - consider increasing risk limits"
                )
            
            # Analyze contract test compliance
            compliance_count = sum(
                1 for dec in self.weekly_decisions
                if dec.contract_tests_passed
            )
            compliance_rate = compliance_count / len(self.weekly_decisions) if self.weekly_decisions else 0.0
            
            if compliance_rate < 1.0:
                recommendations.append(
                    f"Contract test compliance ({compliance_rate:.1%}) - investigate failed tests"
                )
            
            # Analyze threshold binding
            binding_analysis = self._analyze_threshold_binding()
            
            # Check for consistently binding thresholds
            for model_id, model_binding in binding_analysis.get("threshold_effectiveness", {}).items():
                if model_binding.get("bss_threshold_binding", 0) > 2:
                    recommendations.append(
                        f"BSS threshold consistently binding for {model_id} - consider adjustment"
                    )
                
                if model_binding.get("reliability_threshold_binding", 0) > 1:
                    recommendations.append(
                        f"Reliability issues detected for {model_id} - review calibration"
                    )
            
            # Check for ready-to-scale indicators
            if alignment_rate >= 0.8 and compliance_rate >= 0.95:
                recommendations.append("System behavior validated - ready to add third model")
                recommendations.append("Consider loosening tier caps to allow Tier 1")
                recommendations.append("Enable auto-execution for non-critical actions")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to generate policy recommendations: {e}")
            return ["Error generating recommendations"]

# Global Phase 0 experiment instance
_phase0_experiment = Phase0Experiment()

def get_phase0_experiment() -> Phase0Experiment:
    """Get the global Phase 0 experiment instance."""
    return _phase0_experiment
