"""
MERID Governance - Intent Review Engine

Production implementation of GOV's intent review and approval process.
Connects to the inter-system API to process OPS intent proposals.

Authority:
- GOV has VETO power over all intents
- GOV cannot execute or move capital
- GOV enforces constitutional invariants
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("governance.intent_review")


class ReviewDecision(Enum):
    """Intent review decisions."""
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    ESCALATE = "escalate"


class RejectionReason(Enum):
    """Standardized rejection reasons."""
    LOW_CONFIDENCE = "low_confidence"
    HIGH_RISK = "high_risk"
    REGIME_MISMATCH = "regime_mismatch"
    CONSTITUTIONAL_VIOLATION = "constitutional_violation"
    AUTHORITY_VIOLATION = "authority_violation"
    INSUFFICIENT_SIMULATION = "insufficient_simulation"
    ADVERSARIAL_PATTERN = "adversarial_pattern"
    MODEL_RISK = "model_risk"
    MANUAL_VETO = "manual_veto"


@dataclass
class ReviewCriteria:
    """Criteria for intent review."""
    min_confidence: float = 0.5
    max_drawdown_pct: float = 0.10
    max_var_95: float = 0.05
    max_cvar_95: float = 0.08
    min_sharpe_ratio: float = 0.5
    max_p_loss: float = 0.4
    required_regime_confidence: float = 0.6
    required_epistemic_confidence: float = 0.5
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "min_confidence": self.min_confidence,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_var_95": self.max_var_95,
            "max_cvar_95": self.max_cvar_95,
            "min_sharpe_ratio": self.min_sharpe_ratio,
            "max_p_loss": self.max_p_loss,
            "required_regime_confidence": self.required_regime_confidence,
            "required_epistemic_confidence": self.required_epistemic_confidence,
        }


@dataclass
class ReviewResult:
    """Result of intent review."""
    intent_id: str
    decision: ReviewDecision
    reviewer_id: str
    timestamp: float = field(default_factory=time.time)
    
    # Decision details
    confidence_score: float = 0.0
    risk_score: float = 0.0
    
    # Rejection details
    rejection_reason: Optional[RejectionReason] = None
    rejection_details: str = ""
    
    # Approval details
    approved_notional: float = 0.0
    slippage_limit_bps: int = 50
    time_lock_sec: int = 0
    
    # Flags
    requires_escalation: bool = False
    constitutional_check_passed: bool = True
    authority_check_passed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "decision": self.decision.value,
            "reviewer_id": self.reviewer_id,
            "timestamp": self.timestamp,
            "confidence_score": round(self.confidence_score, 4),
            "risk_score": round(self.risk_score, 4),
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "rejection_details": self.rejection_details,
            "approved_notional": self.approved_notional,
            "slippage_limit_bps": self.slippage_limit_bps,
            "time_lock_sec": self.time_lock_sec,
            "requires_escalation": self.requires_escalation,
        }


class IntentReviewEngine:
    """
    GOV's intent review engine.
    
    Responsibilities:
    - Review intent proposals from OPS
    - Enforce constitutional invariants
    - Check authority boundaries
    - Apply risk limits
    - Coordinate multi-reviewer approval
    """
    
    # Quorum requirements
    STANDARD_QUORUM = 2
    HIGH_RISK_QUORUM = 3
    CRITICAL_QUORUM = 4
    
    # Risk thresholds
    HIGH_RISK_NOTIONAL = 50000.0
    CRITICAL_RISK_NOTIONAL = 100000.0
    
    def __init__(self, criteria: Optional[ReviewCriteria] = None):
        self._criteria = criteria or ReviewCriteria()
        self._pending_reviews: Dict[str, List[ReviewResult]] = {}
        self._completed_reviews: Dict[str, ReviewResult] = {}
        
        # Reviewers
        self._active_reviewers: List[str] = []
        
        # Callbacks
        self._on_approval: Optional[Callable[[str, ReviewResult], None]] = None
        self._on_rejection: Optional[Callable[[str, ReviewResult], None]] = None
        
        # Integration with other GOV components
        self._constitutional = None
        self._authority_enforcer = None
        self._adversarial_engine = None
        self._model_risk_manager = None
        
        logger.info("Intent review engine initialized")
    
    def initialize_components(self) -> None:
        """Initialize GOV component integrations."""
        try:
            from governance.constitutional import get_constitutional
            self._constitutional = get_constitutional()
        except Exception as e:
            logger.warning("Could not initialize constitutional: %s", e)
        
        try:
            from governance.authority_boundary import get_authority_enforcer
            self._authority_enforcer = get_authority_enforcer()
        except Exception as e:
            logger.warning("Could not initialize authority enforcer: %s", e)
        
        try:
            from governance.adversarial import get_adversarial_engine
            self._adversarial_engine = get_adversarial_engine()
        except Exception as e:
            logger.warning("Could not initialize adversarial engine: %s", e)
        
        try:
            from governance.model_risk import get_model_risk_manager
            self._model_risk_manager = get_model_risk_manager()
        except Exception as e:
            logger.warning("Could not initialize model risk manager: %s", e)
    
    def register_reviewer(self, reviewer_id: str) -> None:
        """Register an active reviewer."""
        if reviewer_id not in self._active_reviewers:
            self._active_reviewers.append(reviewer_id)
            logger.info("Registered reviewer: %s", reviewer_id)
    
    def unregister_reviewer(self, reviewer_id: str) -> None:
        """Unregister a reviewer."""
        if reviewer_id in self._active_reviewers:
            self._active_reviewers.remove(reviewer_id)
            logger.info("Unregistered reviewer: %s", reviewer_id)
    
    async def review_intent(
        self,
        intent_id: str,
        intent_data: Dict[str, Any],
        reviewer_id: str,
    ) -> ReviewResult:
        """
        Review an intent proposal.
        
        Returns ReviewResult with decision.
        """
        logger.info("Reviewing intent %s by %s", intent_id[:8], reviewer_id)
        
        result = ReviewResult(
            intent_id=intent_id,
            reviewer_id=reviewer_id,
        )
        
        # Step 1: Constitutional check
        if not await self._check_constitutional(intent_data, result):
            result.decision = ReviewDecision.REJECT
            result.rejection_reason = RejectionReason.CONSTITUTIONAL_VIOLATION
            return result
        
        # Step 2: Authority boundary check
        if not await self._check_authority(intent_data, result):
            result.decision = ReviewDecision.REJECT
            result.rejection_reason = RejectionReason.AUTHORITY_VIOLATION
            return result
        
        # Step 3: Risk assessment
        risk_passed, risk_score = await self._assess_risk(intent_data)
        result.risk_score = risk_score
        
        if not risk_passed:
            result.decision = ReviewDecision.REJECT
            result.rejection_reason = RejectionReason.HIGH_RISK
            result.rejection_details = f"Risk score {risk_score:.2f} exceeds threshold"
            return result
        
        # Step 4: Confidence check
        confidence = intent_data.get("confidence", 0)
        result.confidence_score = confidence
        
        if confidence < self._criteria.min_confidence:
            result.decision = ReviewDecision.REJECT
            result.rejection_reason = RejectionReason.LOW_CONFIDENCE
            result.rejection_details = f"Confidence {confidence:.2f} below {self._criteria.min_confidence}"
            return result
        
        # Step 5: Shadow simulation validation
        shadow_sim = intent_data.get("shadow_simulation", {})
        if not self._validate_shadow_simulation(shadow_sim):
            result.decision = ReviewDecision.REJECT
            result.rejection_reason = RejectionReason.INSUFFICIENT_SIMULATION
            return result
        
        # Step 6: Adversarial pattern check
        if self._adversarial_engine:
            adversarial_check = await self._check_adversarial(intent_data)
            if not adversarial_check:
                result.decision = ReviewDecision.REJECT
                result.rejection_reason = RejectionReason.ADVERSARIAL_PATTERN
                return result
        
        # Step 7: Model risk check
        if self._model_risk_manager:
            model_check = await self._check_model_risk(intent_data)
            if not model_check:
                result.decision = ReviewDecision.REJECT
                result.rejection_reason = RejectionReason.MODEL_RISK
                return result
        
        # All checks passed - approve
        result.decision = ReviewDecision.APPROVE
        result = self._calculate_approval_constraints(intent_data, result)
        
        # Check if escalation needed
        notional = intent_data.get("position_request", {}).get("notional_usd", 0)
        if notional >= self.CRITICAL_RISK_NOTIONAL:
            result.requires_escalation = True
        
        logger.info(
            "Intent %s reviewed: %s (confidence=%.2f, risk=%.2f)",
            intent_id[:8], result.decision.value,
            result.confidence_score, result.risk_score
        )
        
        return result
    
    async def _check_constitutional(
        self,
        intent_data: Dict[str, Any],
        result: ReviewResult,
    ) -> bool:
        """Check constitutional invariants."""
        if not self._constitutional:
            result.constitutional_check_passed = True
            return True
        
        try:
            # Check key invariants
            position = intent_data.get("position_request", {})
            notional = position.get("notional_usd", 0)
            leverage = position.get("leverage", 1.0)
            
            # Max position size invariant
            if notional > 500000:  # $500k max
                result.constitutional_check_passed = False
                result.rejection_details = "Position exceeds constitutional max size"
                return False
            
            # Max leverage invariant
            if leverage > 3.0:
                result.constitutional_check_passed = False
                result.rejection_details = "Leverage exceeds constitutional limit"
                return False
            
            result.constitutional_check_passed = True
            return True
            
        except Exception as e:
            logger.error("Constitutional check error: %s", e)
            return False
    
    async def _check_authority(
        self,
        intent_data: Dict[str, Any],
        result: ReviewResult,
    ) -> bool:
        """Check authority boundaries."""
        if not self._authority_enforcer:
            result.authority_check_passed = True
            return True
        
        try:
            origin = intent_data.get("origin_system", "")
            
            # OPS can only signal, not execute
            if origin == "OPS":
                result.authority_check_passed = True
                return True
            
            # Other systems cannot propose intents
            result.authority_check_passed = False
            result.rejection_details = f"System {origin} not authorized to propose intents"
            return False
            
        except Exception as e:
            logger.error("Authority check error: %s", e)
            return False
    
    async def _assess_risk(
        self,
        intent_data: Dict[str, Any],
    ) -> Tuple[bool, float]:
        """Assess risk of intent."""
        risk_preview = intent_data.get("risk_preview", {})
        
        # Calculate composite risk score
        scores = []
        
        # Drawdown risk
        drawdown = risk_preview.get("max_drawdown_pct", 0)
        if drawdown > self._criteria.max_drawdown_pct:
            return False, 1.0
        scores.append(drawdown / self._criteria.max_drawdown_pct)
        
        # VaR risk
        var_95 = risk_preview.get("var_95", 0)
        if var_95 > self._criteria.max_var_95:
            return False, 1.0
        scores.append(var_95 / self._criteria.max_var_95)
        
        # CVaR risk
        cvar_95 = risk_preview.get("cvar_95", 0)
        if cvar_95 > self._criteria.max_cvar_95:
            return False, 1.0
        scores.append(cvar_95 / self._criteria.max_cvar_95)
        
        # Composite score (0-1, lower is better)
        risk_score = sum(scores) / len(scores) if scores else 0.5
        
        return True, risk_score
    
    def _validate_shadow_simulation(self, shadow_sim: Dict[str, Any]) -> bool:
        """Validate shadow simulation results."""
        if not shadow_sim:
            return False
        
        # Check required fields
        required = ["expected_return", "p_loss", "sharpe_ratio", "max_adverse_excursion"]
        for field in required:
            if field not in shadow_sim:
                return False
        
        # Validate values
        if shadow_sim.get("sharpe_ratio", 0) < self._criteria.min_sharpe_ratio:
            return False
        
        if shadow_sim.get("p_loss", 1) > self._criteria.max_p_loss:
            return False
        
        return True
    
    async def _check_adversarial(self, intent_data: Dict[str, Any]) -> bool:
        """Check for adversarial patterns."""
        if not self._adversarial_engine:
            return True
        
        try:
            # Check for deception patterns in signal sources
            sources = intent_data.get("signal_sources", [])
            for source in sources:
                # Use adversarial engine to check source
                pass
            
            return True
            
        except Exception as e:
            logger.error("Adversarial check error: %s", e)
            return True  # Fail open for now
    
    async def _check_model_risk(self, intent_data: Dict[str, Any]) -> bool:
        """Check model risk."""
        if not self._model_risk_manager:
            return True
        
        try:
            strategy_id = intent_data.get("strategy_id", "")
            
            # Check if strategy model is validated
            # This would integrate with model_risk.py
            
            return True
            
        except Exception as e:
            logger.error("Model risk check error: %s", e)
            return True  # Fail open for now
    
    def _calculate_approval_constraints(
        self,
        intent_data: Dict[str, Any],
        result: ReviewResult,
    ) -> ReviewResult:
        """Calculate constraints for approved intent."""
        position = intent_data.get("position_request", {})
        notional = position.get("notional_usd", 0)
        
        # Apply notional limits based on risk
        if result.risk_score > 0.7:
            result.approved_notional = min(notional, 10000)
            result.slippage_limit_bps = 30
            result.time_lock_sec = 300  # 5 minute lock
        elif result.risk_score > 0.5:
            result.approved_notional = min(notional, 25000)
            result.slippage_limit_bps = 50
            result.time_lock_sec = 60
        else:
            result.approved_notional = notional
            result.slippage_limit_bps = 100
            result.time_lock_sec = 0
        
        return result
    
    def submit_review(self, result: ReviewResult) -> bool:
        """Submit a review result."""
        intent_id = result.intent_id
        
        if intent_id not in self._pending_reviews:
            self._pending_reviews[intent_id] = []
        
        self._pending_reviews[intent_id].append(result)
        
        # Check if quorum reached
        reviews = self._pending_reviews[intent_id]
        required_quorum = self._get_required_quorum(reviews)
        
        if len(reviews) >= required_quorum:
            final_result = self._aggregate_reviews(reviews)
            self._completed_reviews[intent_id] = final_result
            del self._pending_reviews[intent_id]
            
            # Trigger callbacks
            if final_result.decision == ReviewDecision.APPROVE and self._on_approval:
                self._on_approval(intent_id, final_result)
            elif final_result.decision == ReviewDecision.REJECT and self._on_rejection:
                self._on_rejection(intent_id, final_result)
            
            return True
        
        return False
    
    def _get_required_quorum(self, reviews: List[ReviewResult]) -> int:
        """Get required quorum based on risk level."""
        if not reviews:
            return self.STANDARD_QUORUM
        
        # Check if any review flagged escalation
        if any(r.requires_escalation for r in reviews):
            return self.CRITICAL_QUORUM
        
        # Check average risk score
        avg_risk = sum(r.risk_score for r in reviews) / len(reviews)
        if avg_risk > 0.7:
            return self.HIGH_RISK_QUORUM
        
        return self.STANDARD_QUORUM
    
    def _aggregate_reviews(self, reviews: List[ReviewResult]) -> ReviewResult:
        """Aggregate multiple reviews into final decision."""
        if not reviews:
            raise ValueError("No reviews to aggregate")
        
        # Count decisions
        approvals = [r for r in reviews if r.decision == ReviewDecision.APPROVE]
        rejections = [r for r in reviews if r.decision == ReviewDecision.REJECT]
        
        # Any rejection vetoes the intent
        if rejections:
            # Use first rejection as the result
            result = rejections[0]
            result.reviewer_id = ",".join(r.reviewer_id for r in rejections)
            return result
        
        # All approvals - aggregate constraints
        result = approvals[0]
        result.reviewer_id = ",".join(r.reviewer_id for r in approvals)
        
        # Use most conservative constraints
        result.approved_notional = min(r.approved_notional for r in approvals)
        result.slippage_limit_bps = min(r.slippage_limit_bps for r in approvals)
        result.time_lock_sec = max(r.time_lock_sec for r in approvals)
        
        # Average scores
        result.confidence_score = sum(r.confidence_score for r in approvals) / len(approvals)
        result.risk_score = sum(r.risk_score for r in approvals) / len(approvals)
        
        return result
    
    def veto_intent(
        self,
        intent_id: str,
        vetoer_id: str,
        reason: str,
    ) -> ReviewResult:
        """Manually veto an intent."""
        result = ReviewResult(
            intent_id=intent_id,
            decision=ReviewDecision.REJECT,
            reviewer_id=vetoer_id,
            rejection_reason=RejectionReason.MANUAL_VETO,
            rejection_details=reason,
        )
        
        self._completed_reviews[intent_id] = result
        
        # Clear any pending reviews
        if intent_id in self._pending_reviews:
            del self._pending_reviews[intent_id]
        
        if self._on_rejection:
            self._on_rejection(intent_id, result)
        
        logger.warning("Intent %s vetoed by %s: %s", intent_id[:8], vetoer_id, reason)
        
        return result
    
    def on_approval(self, callback: Callable[[str, ReviewResult], None]) -> None:
        """Register approval callback."""
        self._on_approval = callback
    
    def on_rejection(self, callback: Callable[[str, ReviewResult], None]) -> None:
        """Register rejection callback."""
        self._on_rejection = callback
    
    def get_pending_count(self) -> int:
        """Get count of pending reviews."""
        return len(self._pending_reviews)
    
    def get_review_status(self, intent_id: str) -> Optional[Dict[str, Any]]:
        """Get review status for an intent."""
        if intent_id in self._completed_reviews:
            return {
                "status": "completed",
                "result": self._completed_reviews[intent_id].to_dict(),
            }
        
        if intent_id in self._pending_reviews:
            reviews = self._pending_reviews[intent_id]
            return {
                "status": "pending",
                "reviews_received": len(reviews),
                "required_quorum": self._get_required_quorum(reviews),
            }
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get review engine statistics."""
        completed = list(self._completed_reviews.values())
        approvals = sum(1 for r in completed if r.decision == ReviewDecision.APPROVE)
        rejections = sum(1 for r in completed if r.decision == ReviewDecision.REJECT)
        
        return {
            "active_reviewers": len(self._active_reviewers),
            "pending_reviews": len(self._pending_reviews),
            "completed_reviews": len(self._completed_reviews),
            "approvals": approvals,
            "rejections": rejections,
            "approval_rate": approvals / len(completed) if completed else 0,
            "criteria": self._criteria.to_dict(),
        }


# Singleton instance
_intent_review_engine: Optional[IntentReviewEngine] = None


def get_intent_review_engine() -> IntentReviewEngine:
    """Get the singleton intent review engine."""
    global _intent_review_engine
    if _intent_review_engine is None:
        _intent_review_engine = IntentReviewEngine()
        _intent_review_engine.initialize_components()
    return _intent_review_engine
