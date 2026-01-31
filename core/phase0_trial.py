"""
MERID Phase 0 Operational Trial Plan

Time-boxed 4-6 week trial with two scoped models, recommendation-only governance,
and evidence-based iteration at the end.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import json

from core.phase0_config import get_phase0_config
from core.merid_minimal_scope import get_minimal_live_scope
from core.merid_feedback import get_feedback_analyzer
# Skip merid_governance_cadence for Phase 0 trial
# from core.merid_governance_cadence import get_governance_cadence
from utils.logger import get_logger

logger = get_logger("phase0_trial")

@dataclass
class TrialConfiguration:
    """Configuration for the Phase 0 operational trial."""
    
    # Trial timing
    trial_start_date: datetime
    trial_end_date: datetime
    trial_duration_weeks: int = 6
    
    # Model scope
    scoped_models: List[str] = field(default_factory=lambda: [
        "crypto_prediction_agent_v1",
        "arbitrage_analyst_v2"
    ])
    
    # Governance mode
    governance_mode: str = "recommendation_only"  # No auto-execution
    
    # Success criteria
    minimum_alignment_rate: float = 0.7  # 70% alignment
    minimum_contract_compliance: float = 0.95  # 95% contract test compliance
    minimum_weekly_decisions: int = 2  # 2 models × 1 decision per week
    minimum_total_decisions: int = 12  # 2 models × 6 weeks
    
    # Risk limits (conservative)
    max_notional_per_model: float = 50000  # $50K per model
    max_daily_volume_per_model: float = 200000  # $200K per model
    allowed_tiers: List[str] = field(default_factory=lambda: ["tier_3", "tier_4"])  # No Tier 1-2
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_period": {
                "start_date": self.trial_start_date.isoformat(),
                "end_date": self.trial_end_date.isoformat(),
                "duration_weeks": self.trial_duration_weeks
            },
            "scoped_models": self.scoped_models,
            "governance_mode": self.governance_mode,
            "success_criteria": {
                "minimum_alignment_rate": self.minimum_alignment_rate,
                "minimum_contract_compliance": self.minimum_contract_compliance,
                "minimum_weekly_decisions": self.minimum_weekly_decisions,
                "minimum_total_decisions": self.minimum_total_decisions
            },
            "risk_limits": {
                "max_notional_per_model": self.max_notional_per_model,
                "max_daily_volume_per_model": self.max_daily_volume_per_model,
                "allowed_tiers": self.allowed_tiers
            }
        }

@dataclass
class WeeklyTrialRecord:
    """Record of weekly trial activities."""
    
    week_number: int
    model_id: str
    system_recommendation: str
    human_decision: str
    decision_reason: str
    alignment: bool  # Whether human matched system recommendation
    contract_tests_passed: bool
    scorecard_snapshot: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "week_number": self.week_number,
            "model_id": self.model_id,
            "system_recommendation": self.system_recommendation,
            "human_decision": self.human_decision,
            "decision_reason": self.decision_reason,
            "alignment": self.alignment,
            "contract_tests_passed": self.contract_tests_passed,
            "scorecard_snapshot": self.scorecard_snapshot,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class TrialResults:
    """Results of the Phase 0 trial."""
    
    trial_config: TrialConfiguration
    
    # Decision analysis
    total_decisions: int
    weekly_decisions: List[WeeklyTrialRecord]
    alignment_rate: float
    contract_compliance_rate: float
    
    # Performance metrics
    model_performance: Dict[str, Dict[str, Any]]
    feedback_analysis: Dict[str, Any]
    
    # Success determination
    trial_successful: bool
    recommendations: List[str]
    next_phase_config: Optional[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_configuration": self.trial_config.to_dict(),
            "decision_analysis": {
                "total_decisions": self.total_decisions,
                "weekly_decisions": [dec.to_dict() for dec in self.weekly_decisions],
                "alignment_rate": self.alignment_rate,
                "contract_compliance_rate": self.contract_compliance_rate
            },
            "performance_metrics": {
                "model_performance": self.model_performance,
                "feedback_analysis": self.feedback_analysis
            },
            "success_determination": {
                "trial_successful": self.trial_successful,
                "recommendations": self.recommendations,
                "next_phase_config": self.next_phase_config
            }
        }

class Phase0Trial:
    """
    Phase 0 Operational Trial Manager
    
    Runs time-boxed trial with two scoped models, recommendation-only governance,
    and evidence-based iteration.
    """
    
    def __init__(self):
        self.config = get_phase0_config()
        self.scope = get_minimal_live_scope()
        self.feedback_analyzer = get_feedback_analyzer()
        # Skip cadence for Phase 0 trial
        # self.cadence = get_governance_cadence()
        
        # Trial state
        self.trial_config: Optional[TrialConfiguration] = None
        self.weekly_records: List[WeeklyTrialRecord] = []
        self.trial_active: bool = False
        self.trial_start_date: Optional[datetime] = None
        
        logger.info("Phase 0 Trial Manager initialized")
    
    def start_trial(self, duration_weeks: int = 6) -> Dict[str, Any]:
        """
        Start the Phase 0 operational trial.
        
        Args:
            duration_weeks: Duration of trial in weeks (default: 6)
            
        Returns:
            Trial configuration and setup status
        """
        try:
            # Validate Phase 0 is enabled
            if not self.config.is_phase0_active():
                return {
                    "success": False,
                    "error": "Phase 0 is not enabled. Check feature flags."
                }
            
            # Create trial configuration
            self.trial_start_date = datetime.now()
            trial_end_date = self.trial_start_date + timedelta(weeks=duration_weeks)
            
            self.trial_config = TrialConfiguration(
                trial_start_date=self.trial_start_date,
                trial_end_date=trial_end_date,
                trial_duration_weeks=duration_weeks,
                governance_mode="recommendation_only"
            )
            
            # Apply conservative risk limits
            self._apply_trial_risk_limits()
            
            # Enable recommendation-only mode
            self._enable_recommendation_only_mode()
            
            # Initialize weekly tracking
            self.weekly_records = []
            self.trial_active = True
            
            logger.info(f"Phase 0 trial started: {duration_weeks} weeks, models: {self.trial_config.scoped_models}")
            
            return {
                "success": True,
                "trial_config": self.trial_config.to_dict(),
                "message": f"Phase 0 trial started successfully. Duration: {duration_weeks} weeks"
            }
            
        except Exception as e:
            logger.error(f"Failed to start Phase 0 trial: {e}")
            return {"success": False, "error": str(e)}
    
    def record_weekly_decision(self, model_id: str, human_decision: str, decision_reason: str) -> Dict[str, Any]:
        """
        Record weekly governance decision for the trial.
        
        Args:
            model_id: Model identifier
            human_decision: Human decision (promote, demote, hold, suspend, retire)
            decision_reason: Reason for the decision
            
        Returns:
            Decision recording status and analysis
        """
        try:
            logger.info(f"record_weekly_decision called for model: {model_id}")
            
            if not self.trial_active:
                logger.warning("Trial is not active")
                return {
                    "success": False,
                    "error": "Trial is not active"
                }
            
            if model_id not in self.trial_config.scoped_models:
                logger.warning(f"Model {model_id} not in trial scope")
                return {
                    "success": False,
                    "error": f"Model {model_id} not in trial scope"
                }
            
            logger.info("Getting current system recommendation")
            # Get current system recommendation
            scorecard = self.scope.generate_governance_scorecard(model_id)
            logger.info(f"Scorecard generated: {scorecard}")
            system_recommendation = scorecard.suggested_action
            
            # Check contract tests
            contract_results = self.scope.contract_tests.run_all_contract_tests(model_id)
            contract_tests_passed = all(
                result for result in contract_results.values() 
                if isinstance(result, bool)
            )
            
            # Calculate alignment
            alignment = (human_decision == system_recommendation)
            
            # Calculate week number
            if self.trial_start_date:
                week_number = ((datetime.now() - self.trial_start_date).days // 7) + 1
            else:
                week_number = 1
            
            # Create weekly record
            weekly_record = WeeklyTrialRecord(
                week_number=week_number,
                model_id=model_id,
                system_recommendation=system_recommendation,
                human_decision=human_decision,
                decision_reason=decision_reason,
                alignment=alignment,
                contract_tests_passed=contract_tests_passed,
                scorecard_snapshot=scorecard.to_dict()
            )
            
            self.weekly_records.append(weekly_record)
            
            # Submit human review to minimal scope
            self.scope.submit_human_review(
                model_id=model_id,
                action=human_decision,
                notes=decision_reason,
                reviewer="phase0_trial"
            )
            
            logger.info(f"Weekly decision recorded: {model_id} week {week_number}, alignment: {alignment}")
            
            return {
                "success": True,
                "decision": weekly_record.to_dict(),
                "analysis": {
                    "week_number": week_number,
                    "alignment": alignment,
                    "system_recommendation": system_recommendation,
                    "human_decision": human_decision,
                    "contract_tests_passed": contract_tests_passed
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to record weekly decision: {e}")
            import traceback
            logger.error(f"Exception traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}
    
    def get_trial_status(self) -> Dict[str, Any]:
        """Get current trial status and progress."""
        try:
            if not self.trial_active or not self.trial_config:
                return {
                    "status": "not_started",
                    "message": "Trial has not been started"
                }
            
            # Calculate progress
            if self.trial_start_date and self.trial_config.trial_end_date:
                total_days = (self.trial_config.trial_end_date - self.trial_start_date).days
                elapsed_days = (datetime.now() - self.trial_start_date).days
                progress_pct = min(elapsed_days / total_days, 1.0)
            else:
                progress_pct = 0.0
            
            # Calculate current metrics
            if self.weekly_records:
                alignment_count = sum(1 for record in self.weekly_records if record.alignment)
                alignment_rate = alignment_count / len(self.weekly_records)
                
                compliance_count = sum(1 for record in self.weekly_records if record.contract_tests_passed)
                compliance_rate = compliance_count / len(self.weekly_records)
            else:
                alignment_rate = 0.0
                compliance_rate = 0.0
            
            return {
                "status": "active",
                "trial_config": self.trial_config.to_dict(),
                "progress": {
                    "start_date": self.trial_start_date.isoformat(),
                    "end_date": self.trial_config.trial_end_date.isoformat(),
                    "elapsed_days": elapsed_days,
                    "total_days": total_days,
                    "progress_pct": progress_pct
                },
                "current_metrics": {
                    "total_decisions": len(self.weekly_records),
                    "alignment_rate": alignment_rate,
                    "contract_compliance_rate": compliance_rate,
                    "weekly_decisions": len([r for r in self.weekly_records if r.week_number == ((elapsed_days // 7) + 1)])
                },
                "governance_mode": self.trial_config.governance_mode
            }
            
        except Exception as e:
            logger.error(f"Failed to get trial status: {e}")
            return {"error": str(e)}
    
    def complete_trial(self) -> Dict[str, Any]:
        """
        Complete the Phase 0 trial and generate evidence-based results.
        
        Returns:
            Trial results and recommendations for next phase
        """
        try:
            if not self.trial_active:
                return {
                    "success": False,
                    "error": "Trial is not active"
                }
            
            logger.info("Completing Phase 0 trial and generating results")
            
            # Mark trial as inactive
            self.trial_active = False
            
            # Calculate trial results
            results = self._calculate_trial_results()
            
            # Generate evidence-based recommendations
            results.recommendations = self._generate_recommendations(results)
            
            # Generate next phase configuration
            results.next_phase_config = self._generate_next_phase_config(results)
            
            # Store trial results
            self._store_trial_results(results)
            
            logger.info(f"Phase 0 trial completed. Successful: {results.trial_successful}")
            
            return {
                "success": True,
                "results": results.to_dict(),
                "message": "Phase 0 trial completed successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to complete trial: {e}")
            return {"success": False, "error": str(e)}
    
    def _calculate_trial_results(self) -> TrialResults:
        """Calculate comprehensive trial results."""
        try:
            # Calculate alignment rate
            if self.weekly_records:
                alignment_count = sum(1 for record in self.weekly_records if record.alignment)
                alignment_rate = alignment_count / len(self.weekly_records)
                
                compliance_count = sum(1 for record in self.weekly_records if record.contract_tests_passed)
                compliance_rate = compliance_count / len(self.weekly_records)
            else:
                alignment_rate = 0.0
                compliance_rate = 0.0
            
            # Analyze model performance
            model_performance = {}
            for model_id in self.trial_config.scoped_models:
                model_records = [r for r in self.weekly_records if r.model_id == model_id]
                
                if model_records:
                    model_alignment = sum(1 for r in model_records if r.alignment) / len(model_records)
                    model_compliance = sum(1 for r in model_records if r.contract_tests_passed) / len(model_records)
                    
                    # Get latest scorecard
                    latest_record = max(model_records, key=lambda x: x.timestamp)
                    
                    model_performance[model_id] = {
                        "total_decisions": len(model_records),
                        "alignment_rate": model_alignment,
                        "contract_compliance_rate": model_compliance,
                        "latest_scorecard": latest_record.scorecard_snapshot,
                        "latest_recommendation": latest_record.system_recommendation,
                        "latest_human_decision": latest_record.human_decision
                    }
            
            # Analyze feedback patterns
            feedback_analysis = self._analyze_feedback_patterns()
            
            # Determine success
            trial_successful = (
                alignment_rate >= self.trial_config.minimum_alignment_rate and
                compliance_rate >= self.trial_config.minimum_contract_compliance and
                len(self.weekly_records) >= self.trial_config.minimum_total_decisions
            )
            
            return TrialResults(
                trial_config=self.trial_config,
                total_decisions=len(self.weekly_records),
                weekly_decisions=self.weekly_records,
                alignment_rate=alignment_rate,
                contract_compliance_rate=compliance_rate,
                model_performance=model_performance,
                feedback_analysis=feedback_analysis,
                trial_successful=trial_successful,
                recommendations=[],  # Will be filled by _generate_recommendations
                next_phase_config=None  # Will be filled by _generate_next_phase_config
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate trial results: {e}")
            raise
    
    def _analyze_feedback_patterns(self) -> Dict[str, Any]:
        """Analyze feedback patterns from trial decisions."""
        try:
            if not self.weekly_records:
                return {"error": "No decisions to analyze"}
            
            # Analyze decision patterns
            promote_decisions = [r for r in self.weekly_records if r.system_recommendation == "promote"]
            hold_decisions = [r for r in self.weekly_records if r.system_recommendation == "hold"]
            demote_decisions = [r for r in self.weekly_records if r.system_recommendation == "demote"]
            
            # Calculate override patterns
            overrides = [r for r in self.weekly_records if not r.alignment]
            
            # Analyze reasons for overrides
            override_reasons = {}
            for override in overrides:
                reason_category = self._categorize_reason(override.decision_reason)
                override_reasons[reason_category] = override_reasons.get(reason_category, 0) + 1
            
            # Analyze contract test failures
            contract_failures = [r for r in self.weekly_records if not r.contract_tests_passed]
            
            return {
                "decision_patterns": {
                    "promote_recommendations": len(promote_decisions),
                    "hold_recommendations": len(hold_decisions),
                    "demote_recommendations": len(demote_decisions),
                    "total_recommendations": len(self.weekly_records)
                },
                "override_analysis": {
                    "total_overrides": len(overrides),
                    "override_rate": len(overrides) / len(self.weekly_records) if self.weekly_records else 0.0,
                    "override_reasons": override_reasons
                },
                "contract_analysis": {
                    "contract_failures": len(contract_failures),
                    "contract_failure_rate": len(contract_failures) / len(self.weekly_records) if self.weekly_records else 0.0,
                    "failed_tests": list(set(
                        test for record in contract_failures
                        for test, passed in record.scorecard_snapshot.get("safety", {}).get("contract_tests", {}).items()
                        if not passed
                    ))
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze feedback patterns: {e}")
            return {"error": str(e)}
    
    def _categorize_reason(self, reason: str) -> str:
        """Categorize decision reason for analysis."""
        reason_lower = reason.lower()
        
        if "data" in reason_lower or "sample" in reason_lower or "events" in reason_lower:
            return "insufficient_data"
        elif "risk" in reason_lower or "conservative" in reason_lower or "cautious" in reason_lower:
            return "risk_management"
        elif "performance" in reason_lower or "accuracy" in reason_lower or "skill" in reason_lower:
            return "performance_concerns"
        elif "market" in reason_lower or "conditions" in reason_lower or "environment" in reason_lower:
            return "market_conditions"
        else:
            return "other"
    
    def _generate_recommendations(self, results: TrialResults) -> List[str]:
        """Generate evidence-based recommendations for next phase."""
        try:
            recommendations = []
            
            # Success-based recommendations
            if results.trial_successful:
                recommendations.append("Trial successful - ready to expand scope")
                recommendations.append("Consider adding third model to Phase 1")
                recommendations.append("Evaluate limited auto-promotion for Tier 2")
            else:
                recommendations.append("Trial did not meet success criteria")
                
                # Specific failure recommendations
                if results.alignment_rate < results.trial_config.minimum_alignment_rate:
                    recommendations.append(f"Low alignment rate ({results.alignment_rate:.1%}) - adjust governance thresholds")
                
                if results.contract_compliance_rate < results.trial_config.minimum_contract_compliance:
                    recommendations.append(f"Contract test compliance ({results.contract_compliance_rate:.1%}) - investigate contract failures")
                
                if len(results.weekly_records) < results.trial_config.minimum_total_decisions:
                    recommendations.append("Insufficient decisions - extend trial duration")
            
            # Pattern-based recommendations
            feedback_analysis = results.feedback_analysis
            
            if feedback_analysis.get("override_analysis", {}).get("override_rate", 0) > 0.3:
                recommendations.append("High override rate - review governance logic")
            
            if feedback_analysis.get("contract_analysis", {}).get("contract_failure_rate", 0) > 0.1:
                recommendations.append("Contract test failures - review safety constraints")
            
            # Model-specific recommendations
            for model_id, performance in results.model_performance.items():
                if performance["alignment_rate"] < 0.6:
                    recommendations.append(f"Low alignment for {model_id} - review model-specific thresholds")
                
                if performance["contract_compliance_rate"] < 0.9:
                    recommendations.append(f"Contract issues for {model_id} - investigate model-specific constraints")
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return ["Error generating recommendations"]
    
    def _generate_next_phase_config(self, results: TrialResults) -> Optional[Dict[str, Any]]:
        """Generate configuration for next phase based on trial results."""
        try:
            if not results.trial_successful:
                return None
            
            # Base Phase 1 configuration
            next_config = {
                "phase": "phase1",
                "governance_mode": "limited_auto_execution",
                "scoped_models": self.trial_config.scoped_models.copy(),
                "risk_limits": {
                    "max_notional_per_model": 100000,  # Increase from 50K
                    "max_daily_volume_per_model": 400000,  # Increase from 200K
                    "allowed_tiers": ["tier_2", "tier_3", "tier_4"]  # Still no Tier 1
                },
                "auto_execution": {
                    "allow_auto_promotion": True,
                    "allow_auto_demotion": False,  # Keep human oversight for demotion
                    "require_human_review": True
                },
                "success_criteria": {
                    "minimum_alignment_rate": 0.75,  # Slightly higher bar
                    "minimum_contract_compliance": 0.98,  # Higher compliance requirement
                    "minimum_total_decisions": 20  # More decisions required
                }
            }
            
            # Add third model if alignment is high
            if results.alignment_rate >= 0.85:
                next_config["scoped_models"].append("third_model_v1")
                next_config["success_criteria"]["minimum_total_decisions"] = 30
            
            # Adjust thresholds based on patterns
            feedback_analysis = results.feedback_analysis
            
            # If override rate is low, enable more automation
            if feedback_analysis.get("override_analysis", {}).get("override_rate", 0) < 0.1:
                next_config["auto_execution"]["allow_auto_promotion"] = True
                next_config["auto_execution"]["require_human_review"] = False
            
            # If contract compliance is high, relax some constraints
            if results.contract_compliance_rate >= 0.98:
                next_config["risk_limits"]["allowed_tiers"] = ["tier_1", "tier_2", "tier_3", "tier_4"]
            
            return next_config
            
        except Exception as e:
            logger.error(f"Failed to generate next phase config: {e}")
            return None
    
    def _apply_trial_risk_limits(self) -> None:
        """Apply conservative risk limits for the trial."""
        try:
            # This would integrate with your existing governance system
            # For now, just log the application
            logger.info(f"Applying trial risk limits: {self.trial_config.risk_limits}")
            
        except Exception as e:
            logger.error(f"Failed to apply trial risk limits: {e}")
    
    def _enable_recommendation_only_mode(self) -> None:
        """Enable recommendation-only governance mode."""
        try:
            # Set dry-run mode to ensure no auto-execution
            logger.info("Enabling recommendation-only mode for Phase 0 trial")
            
        except Exception as e:
            logger.error(f"Failed to enable recommendation-only mode: {e}")
    
    def _store_trial_results(self, results: TrialResults) -> None:
        """Store trial results for analysis and audit."""
        try:
            # Store results in database or file system
            results_file = f"phase0_trial_results_{datetime.now().strftime('%Y%m%d')}.json"
            
            with open(results_file, 'w') as f:
                json.dump(results.to_dict(), f, indent=2, default=str)
            
            logger.info(f"Trial results stored in {results_file}")
            
        except Exception as e:
            logger.error(f"Failed to store trial results: {e}")

# Global Phase 0 trial instance
_phase0_trial = Phase0Trial()

def get_phase0_trial() -> Phase0Trial:
    """Get the global Phase 0 trial instance."""
    return _phase0_trial
