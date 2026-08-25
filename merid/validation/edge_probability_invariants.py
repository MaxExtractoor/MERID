"""
Cross-Layer Invariants: Edge vs Model Probability Consistency

This module enforces invariants between edge calculations and model probabilities
to prevent misalignment between yes/no edge, model prob, and chosen side.

Key Invariants:
- If p_model > 0.5 and edge > 0: must not be short YES or long NO
- If p_model < 0.5 and edge < 0: must not be long YES
- Confidence must be monotonic in |p_model - 0.5| or |edge|
- No trade when |edge| < threshold but confidence is spuriously high

Usage::

    from merid.validation.edge_probability_invariants import (
        EdgeProbabilityInvariantChecker,
        check_edge_probability_consistency,
        check_confidence_monotonicity,
        check_edge_threshold_consistency
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.validation.edge_probability_invariants")


class EdgeProbabilityViolation(str, Enum):
    """Types of edge-probability violations."""
    EDGE_SIGN_MISMATCH = "edge_sign_mismatch"
    SIDE_PROBABILITY_MISMATCH = "side_probability_mismatch"
    CONFIDENCE_NOT_MONOTONIC = "confidence_not_monotonic"
    LOW_EDGE_HIGH_CONFIDENCE = "low_edge_high_confidence"
    INVALID_PROBABILITY_RANGE = "invalid_probability_range"
    INVALID_EDGE_RANGE = "invalid_edge_range"


@dataclass
class EdgeProbabilityCheckResult:
    """Result of edge-probability consistency check."""
    is_valid: bool
    violation_type: Optional[EdgeProbabilityViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class EdgeProbabilityInvariantChecker:
    """Checks edge vs model probability consistency invariants."""
    
    def __init__(self, min_edge_threshold: float = 0.01, min_confidence_threshold: float = 0.5):
        self.min_edge_threshold = min_edge_threshold
        self.min_confidence_threshold = min_confidence_threshold
    
    def check_edge_sign_consistency(
        self,
        p_model: float,
        edge: float,
        chosen_side: str,
    ) -> EdgeProbabilityCheckResult:
        """INVARIANT: Edge sign must be consistent with model probability and chosen side.
        
        For a Yes contract with true event probability p:
        - Model says p_model
        - Market price implies p_market = price_cents/100
        - Edge ≈ p_model - p_market
        
        Invariants:
        - If p_model > 0.5 and edge > 0: must not be short YES or long NO
        - If p_model < 0.5 and edge < 0: must not be long YES
        """
        context = {
            "p_model": p_model,
            "edge": edge,
            "chosen_side": chosen_side,
        }
        
        # Validate probability range
        if not (0.0 <= p_model <= 1.0):
            return EdgeProbabilityCheckResult(
                is_valid=False,
                violation_type=EdgeProbabilityViolation.INVALID_PROBABILITY_RANGE,
                message=f"Model probability out of range [0,1]: p_model={p_model}",
                context=context,
            )
        
        # Check edge sign consistency with model probability
        if p_model > 0.5 and edge > 0:
            # Model bullish, edge positive - should be long YES or short NO
            if chosen_side == "no" and edge > 0:
                # Long NO with positive edge on bullish model - violation
                return EdgeProbabilityCheckResult(
                    is_valid=False,
                    violation_type=EdgeProbabilityViolation.SIDE_PROBABILITY_MISMATCH,
                    message=f"p_model={p_model:.3f} > 0.5 and edge={edge:.3f} > 0, but chosen_side=NO (should be YES)",
                    context=context,
                )
        elif p_model < 0.5 and edge < 0:
            # Model bearish, edge negative - should be long NO or short YES
            if chosen_side == "yes" and edge < 0:
                # Long YES with negative edge on bearish model - violation
                return EdgeProbabilityCheckResult(
                    is_valid=False,
                    violation_type=EdgeProbabilityViolation.SIDE_PROBABILITY_MISMATCH,
                    message=f"p_model={p_model:.3f} < 0.5 and edge={edge:.3f} < 0, but chosen_side=YES (should be NO)",
                    context=context,
                )
        
        return EdgeProbabilityCheckResult(
            is_valid=True,
            violation_type=None,
            message="Edge sign consistent with model probability and chosen side",
            context=context,
        )
    
    def check_confidence_monotonicity(
        self,
        p_model: float,
        edge: float,
        confidence: float,
    ) -> EdgeProbabilityCheckResult:
        """INVARIANT: Confidence must be monotonic in |p_model - 0.5| or |edge|.
        
        No cases where low edge produces max confidence.
        """
        context = {
            "p_model": p_model,
            "edge": edge,
            "confidence": confidence,
        }
        
        # Validate confidence range
        if not (0.0 <= confidence <= 1.0):
            return EdgeProbabilityCheckResult(
                is_valid=False,
                violation_type=EdgeProbabilityViolation.INVALID_PROBABILITY_RANGE,
                message=f"Confidence out of range [0,1]: confidence={confidence}",
                context=context,
            )
        
        # Calculate distance from neutral
        prob_distance = abs(p_model - 0.5)
        edge_distance = abs(edge)
        
        # INVARIANT: High confidence requires significant edge or probability distance
        # If confidence is very high (>0.8), edge or prob_distance must be meaningful
        if confidence > 0.8:
            if edge_distance < 0.02 and prob_distance < 0.1:
                return EdgeProbabilityCheckResult(
                    is_valid=False,
                    violation_type=EdgeProbabilityViolation.CONFIDENCE_NOT_MONOTONIC,
                    message=f"Confidence={confidence:.3f} > 0.8 but edge_distance={edge_distance:.3f} < 0.02 and prob_distance={prob_distance:.3f} < 0.1",
                    context=context,
                )
        
        # INVARIANT: Very low edge should not produce high confidence
        if edge_distance < self.min_edge_threshold and confidence > self.min_confidence_threshold:
            return EdgeProbabilityCheckResult(
                is_valid=False,
                violation_type=EdgeProbabilityViolation.LOW_EDGE_HIGH_CONFIDENCE,
                message=f"Edge={edge:.3f} < threshold={self.min_edge_threshold} but confidence={confidence:.3f} > {self.min_confidence_threshold}",
                context=context,
            )
        
        return EdgeProbabilityCheckResult(
            is_valid=True,
            violation_type=None,
            message="Confidence monotonic with edge and probability distance",
            context=context,
        )
    
    def check_edge_threshold_consistency(
        self,
        edge: float,
        confidence: float,
        trade_emitted: bool,
    ) -> EdgeProbabilityCheckResult:
        """INVARIANT: No trade emitted when |edge| < threshold but confidence is spuriously high.
        
        This prevents the model from generating trades on insufficient edge.
        """
        context = {
            "edge": edge,
            "confidence": confidence,
            "trade_emitted": trade_emitted,
            "min_edge_threshold": self.min_edge_threshold,
        }
        
        if trade_emitted and abs(edge) < self.min_edge_threshold:
            return EdgeProbabilityCheckResult(
                is_valid=False,
                violation_type=EdgeProbabilityViolation.LOW_EDGE_HIGH_CONFIDENCE,
                message=f"Trade emitted with edge={edge:.3f} < threshold={self.min_edge_threshold} (confidence={confidence:.3f})",
                context=context,
            )
        
        return EdgeProbabilityCheckResult(
            is_valid=True,
            violation_type=None,
            message="Edge threshold consistent with trade emission",
            context=context,
        )
    
    def check_all_invariants(
        self,
        p_model: float,
        edge: float,
        confidence: float,
        chosen_side: str,
        trade_emitted: bool,
    ) -> List[EdgeProbabilityCheckResult]:
        """Run all edge-probability invariants."""
        results = []
        
        # Check edge sign consistency
        result = self.check_edge_sign_consistency(p_model, edge, chosen_side)
        results.append(result)
        
        # Check confidence monotonicity
        result = self.check_confidence_monotonicity(p_model, edge, confidence)
        results.append(result)
        
        # Check edge threshold consistency
        result = self.check_edge_threshold_consistency(edge, confidence, trade_emitted)
        results.append(result)
        
        return results


# Convenience functions for direct use

def check_edge_probability_consistency(
    p_model: float,
    edge: float,
    chosen_side: str,
) -> EdgeProbabilityCheckResult:
    """Check edge sign consistency with model probability and chosen side."""
    checker = EdgeProbabilityInvariantChecker()
    return checker.check_edge_sign_consistency(p_model, edge, chosen_side)


def check_confidence_monotonicity(
    p_model: float,
    edge: float,
    confidence: float,
) -> EdgeProbabilityCheckResult:
    """Check confidence monotonicity with edge and probability distance."""
    checker = EdgeProbabilityInvariantChecker()
    return checker.check_confidence_monotonicity(p_model, edge, confidence)


def check_edge_threshold_consistency(
    edge: float,
    confidence: float,
    trade_emitted: bool,
    min_edge_threshold: float = 0.01,
) -> EdgeProbabilityCheckResult:
    """Check edge threshold consistency with trade emission."""
    checker = EdgeProbabilityInvariantChecker(min_edge_threshold=min_edge_threshold)
    return checker.check_edge_threshold_consistency(edge, confidence, trade_emitted)


# Synthetic test data generator for invariant testing

def generate_synthetic_edge_probability_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for edge-probability invariants.
    
    Returns:
        List of test case dictionaries with controlled p_model, edge, confidence, etc.
    """
    test_cases = []
    
    # Valid cases
    test_cases.append({
        "p_model": 0.70,
        "edge": 0.15,
        "confidence": 0.85,
        "chosen_side": "yes",
        "trade_emitted": True,
        "expected_valid": True,
        "description": "Bullish model, positive edge, long YES - valid",
    })
    
    test_cases.append({
        "p_model": 0.30,
        "edge": -0.15,
        "confidence": 0.85,
        "chosen_side": "no",
        "trade_emitted": True,
        "expected_valid": True,
        "description": "Bearish model, negative edge, long NO - valid",
    })
    
    # Invalid cases (should trigger violations)
    test_cases.append({
        "p_model": 0.70,
        "edge": 0.15,
        "confidence": 0.85,
        "chosen_side": "no",
        "trade_emitted": True,
        "expected_valid": False,
        "description": "Bullish model, positive edge, but long NO - violation",
    })
    
    test_cases.append({
        "p_model": 0.30,
        "edge": -0.15,
        "confidence": 0.85,
        "chosen_side": "yes",
        "trade_emitted": True,
        "expected_valid": False,
        "description": "Bearish model, negative edge, but long YES - violation",
    })
    
    test_cases.append({
        "p_model": 0.52,
        "edge": 0.005,
        "confidence": 0.90,
        "chosen_side": "yes",
        "trade_emitted": True,
        "expected_valid": False,
        "description": "Low edge but high confidence - violation",
    })
    
    test_cases.append({
        "p_model": 0.51,
        "edge": 0.008,
        "confidence": 0.95,
        "chosen_side": "yes",
        "trade_emitted": True,
        "expected_valid": False,
        "description": "Trade emitted with edge below threshold - violation",
    })
    
    return test_cases
