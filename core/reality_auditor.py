"""
MERID Reality Auditor - Enforcement Engine

This sits between engines and UI to enforce truth discipline.

RESPONSIBILITIES:
1. Validate assertions
2. Enforce decay
3. Detect conflicts
4. Control UI visibility
5. Block execution if truth is insufficient
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from core.reality_registry import (
    RealityRegistry,
    get_reality_registry,
    AssertionDomain,
    AssertionStatus,
    UIVisibility,
    RealityAssertion,
    AssertionAlgebra,
)
from utils.logger import get_logger

logger = get_logger("core.reality_auditor")


@dataclass
class AuditResult:
    """Result of reality audit."""
    passed: bool
    reason: str
    blocking_assertions: List[str]
    warnings: List[str]


class RealityAuditor:
    """
    The enforcement engine that prevents UI from lying.
    
    This is the missing piece that fixes the representation failure.
    """
    
    def __init__(self, registry: Optional[RealityRegistry] = None):
        self.registry = registry or get_reality_registry()
        self.regime_entropy = 0.0  # Updated by regime classifier
        self.last_audit = time.time()
        
        logger.info("RealityAuditor initialized - truth enforcement active")
    
    def update_regime_entropy(self, entropy: float):
        """Update current regime entropy (0-1)."""
        self.regime_entropy = max(0.0, min(1.0, entropy))
        logger.info(f"Regime entropy updated: {self.regime_entropy:.3f}")
    
    def audit_loop(self):
        """
        Main audit loop - runs continuously.
        
        Updates all assertion statuses based on decay and expiration.
        """
        current_time = time.time()
        
        # Update all assertion statuses
        self.registry.update_assertion_status(current_time, self.regime_entropy)
        
        # Check for blindness condition
        is_blind, reason = self.registry.check_blindness_condition(current_time, self.regime_entropy)
        
        if is_blind:
            logger.warning(f"BLINDNESS MODE TRIGGERED: {reason}")
        
        self.last_audit = current_time
        
        return is_blind, reason
    
    def audit_ui_component(
        self,
        component_id: str,
        required_assertions: List[str],
        allow_conflict: bool = False,
        allow_expired: bool = False,
        min_confidence: float = 0.5,
    ) -> AuditResult:
        """
        Audit whether a UI component is allowed to render.
        
        CONSTITUTIONAL: This is the gate that prevents fake UI.
        """
        current_time = time.time()
        warnings = []
        blocking = []
        
        # Check if all required assertions exist
        assertions = []
        for assertion_id in required_assertions:
            assertion = self.registry.get_assertion(assertion_id)
            if assertion is None:
                blocking.append(assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Missing required assertion: {assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            assertions.append(assertion)
        
        # Check each assertion
        for assertion in assertions:
            # Check expiration
            if assertion.status == AssertionStatus.EXPIRED and not allow_expired:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion expired: {assertion.assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Check conflict
            if assertion.status == AssertionStatus.CONFLICTED and not allow_conflict:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion conflicted: {assertion.assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Check effective confidence
            effective = assertion.effective_confidence(current_time, self.regime_entropy)
            if effective < min_confidence:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion confidence too low: {effective:.3f} < {min_confidence}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Warnings for degraded state
            if assertion.status == AssertionStatus.DEGRADED:
                warnings.append(f"Assertion degraded: {assertion.assertion_id}")
            
            if effective < 0.7:
                warnings.append(f"Low confidence: {assertion.assertion_id} ({effective:.3f})")
        
        return AuditResult(
            passed=True,
            reason="All assertions valid",
            blocking_assertions=[],
            warnings=warnings,
        )
    
    def audit_execution_intent(
        self,
        intent_id: str,
        required_assertions: List[str],
        symbol: str,
        amount_usd: float,
    ) -> AuditResult:
        """
        Audit whether execution is allowed.
        
        STRICTER than UI audit - no exceptions.
        """
        current_time = time.time()
        warnings = []
        blocking = []
        
        # Check blindness mode first
        is_blind, blind_reason = self.registry.check_blindness_condition(current_time, self.regime_entropy)
        if is_blind:
            return AuditResult(
                passed=False,
                reason=f"BLINDNESS MODE: {blind_reason}",
                blocking_assertions=[],
                warnings=[],
            )
        
        # Get assertions
        assertions = []
        for assertion_id in required_assertions:
            assertion = self.registry.get_assertion(assertion_id)
            if assertion is None:
                return AuditResult(
                    passed=False,
                    reason=f"Missing required assertion: {assertion_id}",
                    blocking_assertions=[assertion_id],
                    warnings=[],
                )
            assertions.append(assertion)
        
        # Check execution eligibility using assertion algebra
        can_execute, reason = AssertionAlgebra.check_execution_eligibility(
            assertions,
            current_time,
            self.regime_entropy,
            threshold=0.6,  # Higher threshold for execution
        )
        
        if not can_execute:
            return AuditResult(
                passed=False,
                reason=reason,
                blocking_assertions=[a.assertion_id for a in assertions if not a.is_usable(current_time, self.regime_entropy, 0.6)],
                warnings=[],
            )
        
        return AuditResult(
            passed=True,
            reason="Execution allowed",
            blocking_assertions=[],
            warnings=warnings,
        )
    
    def get_system_state(self) -> Dict:
        """
        Get current system state for monitoring.
        
        This is what operators see.
        """
        current_time = time.time()
        
        # Get registry status
        registry_status = self.registry.get_registry_status(current_time, self.regime_entropy)
        
        # Check blindness
        is_blind, blind_reason = self.registry.check_blindness_condition(current_time, self.regime_entropy)
        
        # Determine system mode
        if is_blind:
            mode = "BLIND"
        elif self.regime_entropy > 0.5:
            mode = "DEGRADED"
        elif registry_status["conflicted_pct"] > 20:
            mode = "CONFLICTED"
        elif registry_status["valid_pct"] < 50:
            mode = "UNSTABLE"
        else:
            mode = "OPERATIONAL"
        
        return {
            "mode": mode,
            "regime_entropy": self.regime_entropy,
            "is_blind": is_blind,
            "blind_reason": blind_reason if is_blind else None,
            "registry_status": registry_status,
            "last_audit": self.last_audit,
            "execution_allowed": not is_blind and self.regime_entropy < 0.7,
        }
    
    def detect_self_deception(self) -> Dict:
        """
        Anti-self-deception metrics.
        
        Detects when MERID (or operators) are lying to themselves.
        """
        current_time = time.time()
        
        assertions = list(self.registry._assertions.values())
        if not assertions:
            return {
                "confidence_inflation": 0.0,
                "agreement_bias": 0.0,
                "narrative_comfort": 0.0,
            }
        
        # Confidence Inflation Index
        # (We'd need historical accuracy data for this - placeholder for now)
        claimed_confidence = sum(a.confidence_score for a in assertions) / len(assertions)
        confidence_inflation = claimed_confidence - 0.5  # Baseline assumption
        
        # Agreement Bias Detector
        # Check if assertions agree too easily (low conflict rate might be suspicious)
        conflicted = sum(1 for a in assertions if a.status == AssertionStatus.CONFLICTED)
        agreement_rate = 1.0 - (conflicted / len(assertions))
        agreement_bias = max(0.0, agreement_rate - 0.7)  # Suspiciously high agreement
        
        # Narrative Comfort Index
        # Check if system avoids uncertainty language
        degraded = sum(1 for a in assertions if a.status == AssertionStatus.DEGRADED)
        expired = sum(1 for a in assertions if a.status == AssertionStatus.EXPIRED)
        uncomfortable = (degraded + expired) / len(assertions)
        narrative_comfort = 1.0 - uncomfortable  # High = too comfortable
        
        return {
            "confidence_inflation": confidence_inflation,
            "agreement_bias": agreement_bias,
            "narrative_comfort": narrative_comfort,
            "warning": confidence_inflation > 0.3 or agreement_bias > 0.2 or narrative_comfort > 0.8,
        }


# Singleton instance
_auditor: Optional[RealityAuditor] = None


def get_reality_auditor() -> RealityAuditor:
    """Get the global reality auditor."""
    global _auditor
    if _auditor is None:
        _auditor = RealityAuditor()
    return _auditor
