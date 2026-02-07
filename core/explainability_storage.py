"""
Explainability Storage and Human Feedback Loop

Provides:
- Store explanations for all transition/payment/safe-mode events
- Progressive disclosure (concise summary + expert view)
- Consistency checking (align with logged state)
- Human feedback loop for explanation quality
"""

import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json

logger = logging.getLogger(__name__)


class ExplanationType(Enum):
    """Types of explanations."""
    TRADE_DECISION = "trade_decision"
    RISK_ACTION = "risk_action"
    STRATEGY_TRANSITION = "strategy_transition"
    PAYMENT_EXECUTION = "payment_execution"
    SAFE_MODE_TRIGGER = "safe_mode_trigger"
    DRIFT_MITIGATION = "drift_mitigation"
    GOVERNANCE_ACTION = "governance_action"
    AGENT_DECISION = "agent_decision"
    MODEL_PREDICTION = "model_prediction"
    ALERT_GENERATED = "alert_generated"


class DisclosureLevel(Enum):
    """Levels of explanation disclosure."""
    SUMMARY = "summary"
    STANDARD = "standard"
    DETAILED = "detailed"
    EXPERT = "expert"
    DEBUG = "debug"


class FeedbackType(Enum):
    """Types of human feedback."""
    ACCURACY = "accuracy"
    CLARITY = "clarity"
    COMPLETENESS = "completeness"
    USEFULNESS = "usefulness"
    CORRECTION = "correction"


class ConsistencyStatus(Enum):
    """Consistency check status."""
    CONSISTENT = "consistent"
    MINOR_DEVIATION = "minor_deviation"
    MAJOR_DEVIATION = "major_deviation"
    INCONSISTENT = "inconsistent"
    UNCHECKED = "unchecked"


@dataclass
class ExplanationContent:
    """Content for different disclosure levels."""
    summary: str = ""
    standard: str = ""
    detailed: str = ""
    expert: str = ""
    debug: str = ""
    
    metrics: Dict[str, Any] = field(default_factory=dict)
    replay_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Explanation:
    """A stored explanation."""
    explanation_id: str
    explanation_type: ExplanationType
    
    action_id: str
    action_type: str
    
    content: ExplanationContent
    
    inputs: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    decision_path: List[str] = field(default_factory=list)
    constraints_applied: List[str] = field(default_factory=list)
    expected_impact: Dict[str, Any] = field(default_factory=dict)
    
    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    strategy_id: Optional[str] = None
    
    consistency_status: ConsistencyStatus = ConsistencyStatus.UNCHECKED
    consistency_details: str = ""
    
    feedback_count: int = 0
    avg_feedback_score: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


@dataclass
class HumanFeedback:
    """Human feedback on an explanation."""
    feedback_id: str
    explanation_id: str
    
    feedback_type: FeedbackType
    score: float
    
    comment: str = ""
    correction: str = ""
    
    reviewer_id: str = ""
    reviewer_role: str = ""
    
    submitted_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ConsistencyCheck:
    """Result of a consistency check."""
    check_id: str
    explanation_id: str
    
    status: ConsistencyStatus
    
    logged_state: Dict[str, Any] = field(default_factory=dict)
    explained_state: Dict[str, Any] = field(default_factory=dict)
    
    deviations: List[str] = field(default_factory=list)
    deviation_score: float = 0.0
    
    checked_at: datetime = field(default_factory=datetime.utcnow)


class ExplainabilityStorage:
    """
    Explainability Storage and Human Feedback System.
    
    Features:
    - Store explanations for all major actions
    - Progressive disclosure (summary → expert)
    - Consistency checking against logged state
    - Human feedback collection and aggregation
    - Explanation quality metrics
    """
    
    def __init__(self):
        self._explanations: Dict[str, Explanation] = {}
        self._feedback: List[HumanFeedback] = []
        self._consistency_checks: List[ConsistencyCheck] = []
        
        self._coverage_stats: Dict[str, int] = {t.value: 0 for t in ExplanationType}
        self._latency_samples: List[float] = []
        
        self._state_providers: Dict[str, Callable[[], Dict[str, Any]]] = {}
    
    def register_state_provider(
        self,
        provider_id: str,
        provider: Callable[[], Dict[str, Any]],
    ) -> None:
        """Register a state provider for consistency checking."""
        self._state_providers[provider_id] = provider
        logger.debug(f"Registered state provider '{provider_id}'")
    
    def store_explanation(
        self,
        explanation_type: ExplanationType,
        action_id: str,
        action_type: str,
        summary: str,
        standard: str = "",
        detailed: str = "",
        expert: str = "",
        debug: str = "",
        inputs: Optional[Dict[str, Any]] = None,
        features: Optional[Dict[str, Any]] = None,
        decision_path: Optional[List[str]] = None,
        constraints_applied: Optional[List[str]] = None,
        expected_impact: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        replay_data: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        ttl_hours: int = 720,
    ) -> Explanation:
        """Store an explanation for an action."""
        explanation_id = f"exp_{action_id}_{int(datetime.utcnow().timestamp())}"
        
        content = ExplanationContent(
            summary=summary,
            standard=standard or summary,
            detailed=detailed or standard or summary,
            expert=expert or detailed or standard or summary,
            debug=debug or expert or detailed or standard or summary,
            metrics=metrics or {},
            replay_data=replay_data or {},
        )
        
        explanation = Explanation(
            explanation_id=explanation_id,
            explanation_type=explanation_type,
            action_id=action_id,
            action_type=action_type,
            content=content,
            inputs=inputs or {},
            features=features or {},
            decision_path=decision_path or [],
            constraints_applied=constraints_applied or [],
            expected_impact=expected_impact or {},
            agent_id=agent_id,
            model_id=model_id,
            strategy_id=strategy_id,
            expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
        )
        
        self._explanations[explanation_id] = explanation
        self._coverage_stats[explanation_type.value] += 1
        
        logger.debug(f"Stored explanation '{explanation_id}' for action '{action_id}'")
        return explanation
    
    def get_explanation(
        self,
        explanation_id: str,
        disclosure_level: DisclosureLevel = DisclosureLevel.STANDARD,
    ) -> Optional[Dict[str, Any]]:
        """Get explanation at specified disclosure level."""
        if explanation_id not in self._explanations:
            return None
        
        exp = self._explanations[explanation_id]
        
        base = {
            "explanation_id": exp.explanation_id,
            "explanation_type": exp.explanation_type.value,
            "action_id": exp.action_id,
            "action_type": exp.action_type,
            "created_at": exp.created_at.isoformat(),
        }
        
        if disclosure_level == DisclosureLevel.SUMMARY:
            base["explanation"] = exp.content.summary
        elif disclosure_level == DisclosureLevel.STANDARD:
            base["explanation"] = exp.content.standard
            base["decision_path"] = exp.decision_path
        elif disclosure_level == DisclosureLevel.DETAILED:
            base["explanation"] = exp.content.detailed
            base["decision_path"] = exp.decision_path
            base["constraints_applied"] = exp.constraints_applied
            base["expected_impact"] = exp.expected_impact
        elif disclosure_level == DisclosureLevel.EXPERT:
            base["explanation"] = exp.content.expert
            base["decision_path"] = exp.decision_path
            base["constraints_applied"] = exp.constraints_applied
            base["expected_impact"] = exp.expected_impact
            base["inputs"] = exp.inputs
            base["features"] = exp.features
            base["metrics"] = exp.content.metrics
        elif disclosure_level == DisclosureLevel.DEBUG:
            base["explanation"] = exp.content.debug
            base["decision_path"] = exp.decision_path
            base["constraints_applied"] = exp.constraints_applied
            base["expected_impact"] = exp.expected_impact
            base["inputs"] = exp.inputs
            base["features"] = exp.features
            base["metrics"] = exp.content.metrics
            base["replay_data"] = exp.content.replay_data
            base["consistency_status"] = exp.consistency_status.value
            base["consistency_details"] = exp.consistency_details
        
        return base
    
    def get_explanation_for_action(
        self,
        action_id: str,
        disclosure_level: DisclosureLevel = DisclosureLevel.STANDARD,
    ) -> Optional[Dict[str, Any]]:
        """Get explanation for a specific action."""
        for exp in self._explanations.values():
            if exp.action_id == action_id:
                return self.get_explanation(exp.explanation_id, disclosure_level)
        return None
    
    def submit_feedback(
        self,
        explanation_id: str,
        feedback_type: FeedbackType,
        score: float,
        comment: str = "",
        correction: str = "",
        reviewer_id: str = "",
        reviewer_role: str = "",
    ) -> Optional[HumanFeedback]:
        """Submit human feedback on an explanation."""
        if explanation_id not in self._explanations:
            logger.warning(f"Explanation '{explanation_id}' not found")
            return None
        
        feedback = HumanFeedback(
            feedback_id=f"fb_{explanation_id}_{int(datetime.utcnow().timestamp())}",
            explanation_id=explanation_id,
            feedback_type=feedback_type,
            score=max(0.0, min(5.0, score)),
            comment=comment,
            correction=correction,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
        )
        
        self._feedback.append(feedback)
        
        exp = self._explanations[explanation_id]
        exp.feedback_count += 1
        exp.avg_feedback_score = (
            (exp.avg_feedback_score * (exp.feedback_count - 1) + score) / exp.feedback_count
        )
        
        logger.info(
            f"Feedback submitted for '{explanation_id}': "
            f"type={feedback_type.value}, score={score}"
        )
        return feedback
    
    def check_consistency(
        self,
        explanation_id: str,
        logged_state: Dict[str, Any],
    ) -> ConsistencyCheck:
        """Check explanation consistency against logged state."""
        if explanation_id not in self._explanations:
            return ConsistencyCheck(
                check_id=f"check_{int(datetime.utcnow().timestamp())}",
                explanation_id=explanation_id,
                status=ConsistencyStatus.UNCHECKED,
            )
        
        exp = self._explanations[explanation_id]
        
        explained_state = {
            "inputs": exp.inputs,
            "features": exp.features,
            "expected_impact": exp.expected_impact,
        }
        
        deviations = []
        deviation_score = 0.0
        
        for key in logged_state:
            if key in explained_state:
                if logged_state[key] != explained_state[key]:
                    deviations.append(f"Mismatch in '{key}'")
                    deviation_score += 0.2
        
        for key in explained_state:
            if key not in logged_state and explained_state[key]:
                deviations.append(f"Missing '{key}' in logged state")
                deviation_score += 0.1
        
        if deviation_score == 0:
            status = ConsistencyStatus.CONSISTENT
        elif deviation_score < 0.3:
            status = ConsistencyStatus.MINOR_DEVIATION
        elif deviation_score < 0.6:
            status = ConsistencyStatus.MAJOR_DEVIATION
        else:
            status = ConsistencyStatus.INCONSISTENT
        
        check = ConsistencyCheck(
            check_id=f"check_{explanation_id}_{int(datetime.utcnow().timestamp())}",
            explanation_id=explanation_id,
            status=status,
            logged_state=logged_state,
            explained_state=explained_state,
            deviations=deviations,
            deviation_score=deviation_score,
        )
        
        self._consistency_checks.append(check)
        
        exp.consistency_status = status
        exp.consistency_details = "; ".join(deviations) if deviations else "Consistent"
        
        logger.debug(
            f"Consistency check for '{explanation_id}': {status.value}, "
            f"deviations={len(deviations)}"
        )
        return check
    
    def get_coverage_metrics(self) -> Dict[str, Any]:
        """Get explanation coverage metrics."""
        total = sum(self._coverage_stats.values())
        
        by_type = {}
        for exp_type, count in self._coverage_stats.items():
            by_type[exp_type] = {
                "count": count,
                "percentage": count / total * 100 if total > 0 else 0,
            }
        
        return {
            "total_explanations": total,
            "by_type": by_type,
            "coverage_rate": total / max(1, len(self._explanations)) * 100,
        }
    
    def get_latency_metrics(self) -> Dict[str, Any]:
        """Get explanation latency metrics."""
        if not self._latency_samples:
            return {"message": "No latency samples recorded"}
        
        sorted_samples = sorted(self._latency_samples)
        n = len(sorted_samples)
        
        return {
            "samples": n,
            "avg_ms": sum(sorted_samples) / n,
            "p50_ms": sorted_samples[n // 2],
            "p95_ms": sorted_samples[int(n * 0.95)] if n >= 20 else sorted_samples[-1],
            "p99_ms": sorted_samples[int(n * 0.99)] if n >= 100 else sorted_samples[-1],
            "min_ms": sorted_samples[0],
            "max_ms": sorted_samples[-1],
        }
    
    def get_consistency_metrics(self) -> Dict[str, Any]:
        """Get consistency check metrics."""
        if not self._consistency_checks:
            return {"message": "No consistency checks performed"}
        
        by_status = {}
        for status in ConsistencyStatus:
            count = sum(1 for c in self._consistency_checks if c.status == status)
            by_status[status.value] = count
        
        total = len(self._consistency_checks)
        consistent = by_status.get("consistent", 0)
        
        return {
            "total_checks": total,
            "by_status": by_status,
            "consistency_rate": consistent / total * 100 if total > 0 else 0,
            "avg_deviation_score": (
                sum(c.deviation_score for c in self._consistency_checks) / total
                if total > 0 else 0
            ),
        }
    
    def get_feedback_metrics(self) -> Dict[str, Any]:
        """Get human feedback metrics."""
        if not self._feedback:
            return {"message": "No feedback received"}
        
        by_type = {}
        for fb_type in FeedbackType:
            feedbacks = [f for f in self._feedback if f.feedback_type == fb_type]
            if feedbacks:
                by_type[fb_type.value] = {
                    "count": len(feedbacks),
                    "avg_score": sum(f.score for f in feedbacks) / len(feedbacks),
                }
        
        total = len(self._feedback)
        avg_score = sum(f.score for f in self._feedback) / total
        
        corrections = sum(1 for f in self._feedback if f.correction)
        
        return {
            "total_feedback": total,
            "avg_score": avg_score,
            "by_type": by_type,
            "corrections_submitted": corrections,
            "correction_rate": corrections / total * 100 if total > 0 else 0,
        }
    
    def cleanup_expired(self) -> int:
        """Remove expired explanations."""
        now = datetime.utcnow()
        expired = [
            exp_id for exp_id, exp in self._explanations.items()
            if exp.expires_at and exp.expires_at < now
        ]
        
        for exp_id in expired:
            del self._explanations[exp_id]
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired explanations")
        
        return len(expired)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall explainability summary."""
        return {
            "total_explanations": len(self._explanations),
            "coverage": self.get_coverage_metrics(),
            "latency": self.get_latency_metrics(),
            "consistency": self.get_consistency_metrics(),
            "feedback": self.get_feedback_metrics(),
            "state_providers": list(self._state_providers.keys()),
        }


_storage: Optional[ExplainabilityStorage] = None


def get_explainability_storage() -> ExplainabilityStorage:
    """Get global ExplainabilityStorage instance."""
    global _storage
    if _storage is None:
        _storage = ExplainabilityStorage()
    return _storage
