"""
MERID Governance Policies - Brier-Based Promotion and Risk Management

Concrete, enforceable policies for model promotion, de-promotion, and risk management
using the canonical Brier metrics system as the governance primitive.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import numpy as np
from datetime import datetime, timedelta

from core.merid_metrics import get_merid_metrics, CalibrationArchetype
from core.brier_metrics_db import get_brier_db
from utils.logger import get_logger

logger = get_logger("merid_governance")

class GovernanceAction(Enum):
    """Governance actions that can be taken on models."""
    PROMOTE = "promote"
    HOLD = "hold"
    DEMOTE = "demote"
    SUSPEND = "suspend"
    RETIRE = "retire"

class RiskTier(Enum):
    """Risk tiers for model sizing and limits."""
    TIER_1 = "tier_1"  # Highest trust, largest limits
    TIER_2 = "tier_2"  # High trust, large limits
    TIER_3 = "tier_3"  # Medium trust, moderate limits
    TIER_4 = "tier_4"  # Low trust, small limits
    SUSPENDED = "suspended"  # No live trading

@dataclass
class PromotionThresholds:
    """Thresholds for model promotion decisions."""
    # Primary Brier-based thresholds
    min_bss_vs_baseline: float = 0.05  # Minimum Brier Skill Score vs baseline
    min_bss_vs_climatology: float = 0.03  # Minimum BSS vs climatology
    min_events: int = 100  # Minimum resolved forecasts
    max_brier_degradation: float = 0.25  # Max relative Brier degradation
    
    # Quality thresholds
    min_quality_category: str = "Fair"  # Minimum quality category
    max_reliability: float = 0.05  # Maximum reliability (calibration error)
    min_resolution: float = 0.01  # Minimum resolution (discriminative power)
    
    # Stability thresholds
    min_consistency_windows: int = 3  # Consecutive windows meeting criteria
    max_volatility: float = 0.50  # Maximum Brier volatility (std/mean)
    
    # Archetype-specific thresholds
    pit_min_bss: float = 0.06  # Higher threshold for PIT (current conditions)
    ttc_min_bss: float = 0.04  # Lower threshold for TTC (long-run average)
    base_min_bss: float = 0.02  # Lowest threshold for BASE (benchmark)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "min_bss_vs_baseline": self.min_bss_vs_baseline,
            "min_bss_vs_climatology": self.min_bss_vs_climatology,
            "min_events": self.min_events,
            "max_brier_degradation": self.max_brier_degradation,
            "min_quality_category": self.min_quality_category,
            "max_reliability": self.max_reliability,
            "min_resolution": self.min_resolution,
            "min_consistency_windows": self.min_consistency_windows,
            "max_volatility": self.max_volatility,
            "pit_min_bss": self.pit_min_bss,
            "ttc_min_bss": self.ttc_min_bss,
            "base_min_bss": self.base_min_bss
        }

@dataclass
class RiskLimits:
    """Risk limits per tier."""
    max_position_size: float  # Maximum position size (USD)
    max_daily_volume: float   # Maximum daily trading volume
    max_leverage: float       # Maximum leverage ratio
    max_concentration: float  # Maximum concentration per market
    min_confidence: float     # Minimum confidence for trades
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "max_position_size": self.max_position_size,
            "max_daily_volume": self.max_daily_volume,
            "max_leverage": self.max_leverage,
            "max_concentration": self.max_concentration,
            "min_confidence": self.min_confidence
        }

@dataclass
class GovernancePolicy:
    """Complete governance policy for a model."""
    model_id: str
    current_tier: RiskTier
    promotion_thresholds: PromotionThresholds
    risk_limits: RiskLimits
    preferred_archetype: CalibrationArchetype
    last_evaluation: datetime
    evaluation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "model_id": self.model_id,
            "current_tier": self.current_tier.value,
            "promotion_thresholds": self.promotion_thresholds.to_dict(),
            "risk_limits": self.risk_limits.to_dict(),
            "preferred_archetype": self.preferred_archetype.value,
            "last_evaluation": self.last_evaluation.isoformat(),
            "evaluation_history": self.evaluation_history
        }

class MERIDGovernance:
    """
    MERID Governance Engine
    
    Enforces promotion, de-promotion, and risk management policies
    using canonical Brier metrics as the governance primitive.
    """
    
    def __init__(self):
        self.db = get_brier_db()
        self.metrics = get_merid_metrics()
        self.policies: Dict[str, GovernancePolicy] = {}
        
        # Default risk limits per tier
        self.default_risk_limits = {
            RiskTier.TIER_1: RiskLimits(
                max_position_size=1000000,  # $1M
                max_daily_volume=5000000,   # $5M
                max_leverage=3.0,
                max_concentration=0.3,
                min_confidence=0.6
            ),
            RiskTier.TIER_2: RiskLimits(
                max_position_size=500000,   # $500K
                max_daily_volume=2000000,   # $2M
                max_leverage=2.5,
                max_concentration=0.25,
                min_confidence=0.65
            ),
            RiskTier.TIER_3: RiskLimits(
                max_position_size=200000,   # $200K
                max_daily_volume=800000,    # $800K
                max_leverage=2.0,
                max_concentration=0.2,
                min_confidence=0.7
            ),
            RiskTier.TIER_4: RiskLimits(
                max_position_size=50000,    # $50K
                max_daily_volume=200000,    # $200K
                max_leverage=1.5,
                max_concentration=0.15,
                min_confidence=0.75
            ),
            RiskTier.SUSPENDED: RiskLimits(
                max_position_size=0,
                max_daily_volume=0,
                max_leverage=0,
                max_concentration=0,
                min_confidence=1.0
            )
        }
        
        # Default promotion thresholds
        self.default_thresholds = PromotionThresholds()
    
    def register_model_policy(self, model_id: str, 
                            preferred_archetype: CalibrationArchetype = CalibrationArchetype.PIT,
                            initial_tier: RiskTier = RiskTier.TIER_3,
                            custom_thresholds: Optional[PromotionThresholds] = None,
                            custom_limits: Optional[RiskLimits] = None) -> GovernancePolicy:
        """Register a governance policy for a model."""
        policy = GovernancePolicy(
            model_id=model_id,
            current_tier=initial_tier,
            promotion_thresholds=custom_thresholds or self.default_thresholds,
            risk_limits=custom_limits or self.default_risk_limits[initial_tier],
            preferred_archetype=preferred_archetype,
            last_evaluation=datetime.now()
        )
        
        self.policies[model_id] = policy
        logger.info(f"Registered governance policy for model {model_id} at tier {initial_tier.value}")
        
        return policy
    
    def evaluate_promotion_eligibility(self, model_id: str, 
                                     days: int = 30) -> Dict[str, Any]:
        """
        Evaluate if a model meets promotion criteria.
        
        Returns comprehensive evaluation with specific reasons for decisions.
        """
        if model_id not in self.policies:
            return {
                "eligible": False,
                "reason": "No governance policy registered",
                "action": GovernanceAction.HOLD.value,
                "recommendation": "Register governance policy first"
            }
        
        policy = self.policies[model_id]
        thresholds = policy.promotion_thresholds
        
        try:
            # Get recent performance metrics
            performance = self.db.get_model_performance_summary(model_id, days)
            
            if not performance["recent_aggregated_metrics"]:
                return {
                    "eligible": False,
                    "reason": "No recent performance data",
                    "action": GovernanceAction.HOLD.value,
                    "recommendation": "Wait for more resolved forecasts"
                }
            
            # Get current calibration
            current_cal = self.db.get_current_calibration(model_id)
            current_archetype = CalibrationArchetype(current_cal["archetype"]) if current_cal else CalibrationArchetype.BASE
            
            # Evaluate against thresholds
            evaluation = self._evaluate_thresholds(performance, thresholds, current_archetype)
            
            # Determine governance action
            action, recommendation = self._determine_action(evaluation, policy)
            
            # Update evaluation history
            evaluation_record = {
                "timestamp": datetime.now().isoformat(),
                "evaluation": evaluation,
                "action": action.value,
                "recommendation": recommendation,
                "current_tier": policy.current_tier.value,
                "preferred_archetype": policy.preferred_archetype.value,
                "current_archetype": current_archetype.value
            }
            
            policy.evaluation_history.append(evaluation_record)
            policy.last_evaluation = datetime.now()
            
            return {
                "model_id": model_id,
                "eligible": evaluation["meets_all_criteria"],
                "evaluation": evaluation,
                "action": action.value,
                "recommendation": recommendation,
                "current_tier": policy.current_tier.value,
                "risk_limits": policy.risk_limits.to_dict(),
                "evaluation_record": evaluation_record
            }
            
        except Exception as e:
            logger.error(f"Failed to evaluate promotion eligibility for {model_id}: {e}")
            return {
                "eligible": False,
                "reason": f"Evaluation error: {str(e)}",
                "action": GovernanceAction.HOLD.value,
                "recommendation": "Fix evaluation error"
            }
    
    def _evaluate_thresholds(self, performance: Dict[str, Any], 
                           thresholds: PromotionThresholds,
                           current_archetype: CalibrationArchetype) -> Dict[str, Any]:
        """Evaluate performance against promotion thresholds."""
        recent_metrics = performance["recent_aggregated_metrics"][0]  # Most recent
        
        # Extract metrics
        brier_score = recent_metrics["brier_score"]
        bss = recent_metrics["brier_skill_score"] or 0.0
        reliability = recent_metrics["reliability"] or 0.0
        resolution = recent_metrics["resolution"] or 0.0
        quality = recent_metrics["quality_category"]
        n_events = recent_metrics["n_events"]
        
        # Evaluate primary Brier criteria
        meets_bss_baseline = bss >= thresholds.min_bss_vs_baseline
        meets_bss_climatology = bss >= thresholds.min_bss_vs_climatology
        meets_events = n_events >= thresholds.min_events
        meets_quality = self._quality_meets_threshold(quality, thresholds.min_quality_category)
        meets_reliability = reliability <= thresholds.max_reliability
        meets_resolution = resolution >= thresholds.min_resolution
        
        # Evaluate archetype-specific BSS threshold
        archetype_bss_threshold = self._get_archetype_threshold(thresholds, current_archetype)
        meets_archetype_bss = bss >= archetype_bss_threshold
        
        # Evaluate stability (check multiple recent windows)
        meets_stability = self._evaluate_stability(performance["recent_aggregated_metrics"], thresholds)
        
        # Overall decision
        all_criteria = [
            meets_bss_baseline,
            meets_bss_climatology,
            meets_events,
            meets_quality,
            meets_reliability,
            meets_resolution,
            meets_archetype_bss,
            meets_stability
        ]
        
        meets_all_criteria = all(all_criteria)
        
        return {
            "meets_all_criteria": meets_all_criteria,
            "criteria_details": {
                "bss_vs_baseline": {
                    "meets": meets_bss_baseline,
                    "current": bss,
                    "threshold": thresholds.min_bss_vs_baseline,
                    "passed": meets_bss_baseline
                },
                "bss_vs_climatology": {
                    "meets": meets_bss_climatology,
                    "current": bss,
                    "threshold": thresholds.min_bss_vs_climatology,
                    "passed": meets_bss_climatology
                },
                "events": {
                    "meets": meets_events,
                    "current": n_events,
                    "threshold": thresholds.min_events,
                    "passed": meets_events
                },
                "quality": {
                    "meets": meets_quality,
                    "current": quality,
                    "threshold": thresholds.min_quality_category,
                    "passed": meets_quality
                },
                "reliability": {
                    "meets": meets_reliability,
                    "current": reliability,
                    "threshold": thresholds.max_reliability,
                    "passed": meets_reliability
                },
                "resolution": {
                    "meets": meets_resolution,
                    "current": resolution,
                    "threshold": thresholds.min_resolution,
                    "passed": meets_resolution
                },
                "archetype_bss": {
                    "meets": meets_archetype_bss,
                    "current": bss,
                    "threshold": archetype_bss_threshold,
                    "archetype": current_archetype.value,
                    "passed": meets_archetype_bss
                },
                "stability": {
                    "meets": meets_stability,
                    "passed": meets_stability
                }
            },
            "summary": {
                "total_criteria": len(all_criteria),
                "passed_criteria": sum(all_criteria),
                "failed_criteria": len(all_criteria) - sum(all_criteria)
            }
        }
    
    def _quality_meets_threshold(self, quality: str, min_quality: str) -> bool:
        """Check if quality category meets minimum threshold."""
        quality_order = ["No Skill", "Poor", "Fair", "Good", "Excellent"]
        quality_rank = quality_order.index(quality)
        min_rank = quality_order.index(min_quality)
        return quality_rank >= min_rank
    
    def _get_archetype_threshold(self, thresholds: PromotionThresholds, 
                                archetype: CalibrationArchetype) -> float:
        """Get archetype-specific BSS threshold."""
        if archetype == CalibrationArchetype.PIT:
            return thresholds.pit_min_bss
        elif archetype == CalibrationArchetype.TTC:
            return thresholds.ttc_min_bss
        else:  # BASE
            return thresholds.base_min_bss
    
    def _evaluate_stability(self, recent_metrics: List[Dict[str, Any]], 
                          thresholds: PromotionThresholds) -> bool:
        """Evaluate stability across multiple recent windows."""
        if len(recent_metrics) < thresholds.min_consistency_windows:
            return False
        
        # Check Brier score stability
        brier_scores = [m["brier_score"] for m in recent_metrics[:thresholds.min_consistency_windows]]
        brier_mean = np.mean(brier_scores)
        brier_std = np.std(brier_scores)
        
        if brier_mean == 0:
            return False
        
        volatility = brier_std / brier_mean
        return volatility <= thresholds.max_volatility
    
    def _determine_action(self, evaluation: Dict[str, Any], 
                         policy: GovernancePolicy) -> Tuple[GovernanceAction, str]:
        """Determine governance action based on evaluation."""
        if evaluation["meets_all_criteria"]:
            # Check for promotion
            if policy.current_tier == RiskTier.TIER_3 and evaluation["criteria_details"]["bss_vs_baseline"]["current"] > 0.10:
                return GovernanceAction.PROMOTE, "Promote to Tier 2 - Strong performance"
            elif policy.current_tier == RiskTier.TIER_2 and evaluation["criteria_details"]["bss_vs_baseline"]["current"] > 0.15:
                return GovernanceAction.PROMOTE, "Promote to Tier 1 - Excellent performance"
            else:
                return GovernanceAction.HOLD, "Maintain current tier - Meets criteria but not exceptional"
        else:
            # Check for de-promotion or suspension
            failed_criteria = [k for k, v in evaluation["criteria_details"].items() if not v["meets"]]
            
            if "events" in failed_criteria:
                return GovernanceAction.HOLD, "Insufficient data - wait for more events"
            elif "bss_vs_baseline" in failed_criteria and evaluation["criteria_details"]["bss_vs_baseline"]["current"] < 0:
                return GovernanceAction.SUSPEND, "Negative skill - suspend immediately"
            elif policy.current_tier == RiskTier.TIER_2:
                return GovernanceAction.DEMOTE, "Demote to Tier 3 - Performance degradation"
            elif policy.current_tier == RiskTier.TIER_1:
                return GovernanceAction.DEMOTE, "Demote to Tier 2 - Performance below Tier 1 standards"
            else:
                return GovernanceAction.HOLD, f"Address failed criteria: {', '.join(failed_criteria)}"
    
    def execute_governance_action(self, model_id: str, action: GovernanceAction) -> Dict[str, Any]:
        """Execute a governance action on a model."""
        if model_id not in self.policies:
            return {
                "success": False,
                "reason": "No governance policy registered",
                "action": action.value
            }
        
        policy = self.policies[model_id]
        old_tier = policy.current_tier
        
        if action == GovernanceAction.PROMOTE:
            if policy.current_tier == RiskTier.TIER_3:
                policy.current_tier = RiskTier.TIER_2
            elif policy.current_tier == RiskTier.TIER_2:
                policy.current_tier = RiskTier.TIER_1
            else:
                return {
                    "success": False,
                    "reason": f"Cannot promote from {policy.current_tier.value}",
                    "action": action.value
                }
        
        elif action == GovernanceAction.DEMOTE:
            if policy.current_tier == RiskTier.TIER_1:
                policy.current_tier = RiskTier.TIER_2
            elif policy.current_tier == RiskTier.TIER_2:
                policy.current_tier = RiskTier.TIER_3
            elif policy.current_tier == RiskTier.TIER_3:
                policy.current_tier = RiskTier.TIER_4
            else:
                return {
                    "success": False,
                    "reason": f"Cannot demote from {policy.current_tier.value}",
                    "action": action.value
                }
        
        elif action == GovernanceAction.SUSPEND:
            policy.current_tier = RiskTier.SUSPENDED
        
        elif action == GovernanceAction.RETIRE:
            # Remove from active service
            del self.policies[model_id]
            return {
                "success": True,
                "action": action.value,
                "old_tier": old_tier.value,
                "new_tier": "RETIRED",
                "message": f"Model {model_id} retired from service"
            }
        
        # Update risk limits for new tier
        policy.risk_limits = self.default_risk_limits[policy.current_tier]
        
        return {
            "success": True,
            "action": action.value,
            "old_tier": old_tier.value,
            "new_tier": policy.current_tier.value,
            "new_risk_limits": policy.risk_limits.to_dict(),
            "message": f"Model {model_id} {action.value}d from {old_tier.value} to {policy.current_tier.value}"
        }
    
    def get_model_risk_limits(self, model_id: str) -> Optional[RiskLimits]:
        """Get current risk limits for a model."""
        if model_id not in self.policies:
            return None
        return self.policies[model_id].risk_limits
    
    def get_governance_summary(self) -> Dict[str, Any]:
        """Get summary of all governed models."""
        summary = {
            "total_models": len(self.policies),
            "models_by_tier": {},
            "recent_evaluations": [],
            "pending_actions": []
        }
        
        # Count models by tier
        for tier in RiskTier:
            summary["models_by_tier"][tier.value] = sum(1 for p in self.policies.values() if p.current_tier == tier)
        
        # Recent evaluations
        for model_id, policy in self.policies.items():
            if policy.evaluation_history:
                latest = policy.evaluation_history[-1]
                summary["recent_evaluations"].append({
                    "model_id": model_id,
                    "timestamp": latest["timestamp"],
                    "action": latest["action"],
                    "recommendation": latest["recommendation"],
                    "tier": policy.current_tier.value
                })
        
        # Sort by timestamp
        summary["recent_evaluations"].sort(key=lambda x: x["timestamp"], reverse=True)
        
        return summary

# Global governance instance
_merid_governance = MERIDGovernance()

def get_merid_governance() -> MERIDGovernance:
    """Get the global MERID governance instance."""
    return _merid_governance
