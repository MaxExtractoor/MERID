"""
OutcomeValidator - Layer 2: Reality Gap Calculation and Validation

Responsibilities:
- Calculate reality gaps between predictions and outcomes
- Validate outcomes against ground truth
- Detect conflicts and anomalies
- Provide validation confidence scores
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("reflection.validator")


class ValidationMethod(Enum):
    """Validation method used."""
    CONSENSUS = "consensus"
    ONCHAIN = "onchain"
    MARKET = "market"
    MANUAL = "manual"
    TIMEOUT = "timeout"


@dataclass
class ValidationResult:
    """Result of outcome validation."""
    validated: bool
    reality_gap: float  # 0.0-1.0, 0=perfect prediction
    validation_score: float  # 0.0-1.0, confidence in validation
    method: ValidationMethod
    evidence: Dict[str, Any]
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "validated": self.validated,
            "reality_gap": round(self.reality_gap, 4),
            "validation_score": round(self.validation_score, 4),
            "method": self.method.value,
            "evidence": self.evidence,
            "timestamp": self.timestamp
        }


class OutcomeValidator:
    """
    Validates agent predictions against reality.
    
    Features:
    - Multiple validation methods
    - Reality gap calculation
    - Confidence scoring
    - Anomaly detection
    """
    
    def __init__(self):
        self._validation_count = 0
        self._method_counts = {method: 0 for method in ValidationMethod}
        self._start_time = time.time()
        
        logger.info("OutcomeValidator initialized")
    
    def validate_consensus_outcome(
        self,
        prediction: str,
        actual_consensus: str,
        consensus_confidence: float,
        vote_distribution: Dict[str, int]
    ) -> ValidationResult:
        """
        Validate prediction against consensus outcome.
        
        Args:
            prediction: Agent's predicted outcome (accept/reject/abstain)
            actual_consensus: Actual consensus decision
            consensus_confidence: Consensus confidence score
            vote_distribution: Distribution of votes
        
        Returns:
            ValidationResult with reality gap
        """
        start = time.time()
        
        # Check if prediction matches consensus
        validated = prediction == actual_consensus
        
        # Calculate reality gap
        # Gap = 0 if perfect match, increases with mismatch severity
        if validated:
            # Perfect prediction
            reality_gap = 0.0
        elif prediction == "abstain":
            # Abstained when should have voted
            reality_gap = 0.5
        elif actual_consensus == "abstain":
            # Voted when consensus was abstain
            reality_gap = 0.3
        else:
            # Completely wrong (accept vs reject)
            reality_gap = 1.0
        
        # Validation score based on consensus strength
        total_votes = sum(vote_distribution.values())
        if total_votes > 0:
            winning_votes = vote_distribution.get(actual_consensus, 0)
            vote_strength = winning_votes / total_votes
            validation_score = (vote_strength + consensus_confidence) / 2
        else:
            validation_score = consensus_confidence
        
        result = ValidationResult(
            validated=validated,
            reality_gap=reality_gap,
            validation_score=validation_score,
            method=ValidationMethod.CONSENSUS,
            evidence={
                "prediction": prediction,
                "actual": actual_consensus,
                "consensus_confidence": consensus_confidence,
                "vote_distribution": vote_distribution,
                "total_votes": total_votes
            },
            timestamp=time.time()
        )
        
        self._validation_count += 1
        self._method_counts[ValidationMethod.CONSENSUS] += 1
        
        duration_ms = (time.time() - start) * 1000
        logger.debug(
            "Consensus validation: prediction=%s actual=%s validated=%s gap=%.3f (%.2fms)",
            prediction, actual_consensus, validated, reality_gap, duration_ms
        )
        
        return result
    
    def validate_market_outcome(
        self,
        predicted_direction: str,
        actual_price_change: float,
        confidence: float,
        timeframe_hours: float
    ) -> ValidationResult:
        """
        Validate market prediction against actual price movement.
        
        Args:
            predicted_direction: bullish/bearish/neutral
            actual_price_change: Actual price change percentage
            confidence: Agent's confidence in prediction
            timeframe_hours: Timeframe for validation
        
        Returns:
            ValidationResult with reality gap
        """
        start = time.time()
        
        # Determine actual direction
        if actual_price_change > 0.5:
            actual_direction = "bullish"
        elif actual_price_change < -0.5:
            actual_direction = "bearish"
        else:
            actual_direction = "neutral"
        
        # Check if prediction matches
        validated = predicted_direction == actual_direction
        
        # Calculate reality gap based on magnitude mismatch
        if validated:
            magnitude = abs(actual_price_change)
            expected_magnitude = 0.0 if predicted_direction == "neutral" else confidence * 10
            reality_gap = min(abs(magnitude - expected_magnitude) / 10, 1.0)
        else:
            # Wrong direction
            if predicted_direction == "neutral":
                reality_gap = min(abs(actual_price_change) / 10, 1.0)
            else:
                reality_gap = 1.0
        
        # Validation score based on data quality
        validation_score = 0.9 if timeframe_hours >= 24 else 0.7
        
        result = ValidationResult(
            validated=validated,
            reality_gap=reality_gap,
            validation_score=validation_score,
            method=ValidationMethod.MARKET,
            evidence={
                "predicted_direction": predicted_direction,
                "actual_direction": actual_direction,
                "price_change_pct": actual_price_change,
                "timeframe_hours": timeframe_hours
            },
            timestamp=time.time()
        )
        
        self._validation_count += 1
        self._method_counts[ValidationMethod.MARKET] += 1
        
        duration_ms = (time.time() - start) * 1000
        logger.debug(
            "Market validation: predicted=%s actual=%s change=%.2f%% gap=%.3f (%.2fms)",
            predicted_direction, actual_direction, actual_price_change, reality_gap, duration_ms
        )
        
        return result
    
    def validate_onchain_outcome(
        self,
        prediction: Dict[str, Any],
        actual_onchain_data: Dict[str, Any],
        verification_method: str
    ) -> ValidationResult:
        """
        Validate prediction against on-chain data.
        
        Args:
            prediction: Agent's prediction
            actual_onchain_data: Verified on-chain data
            verification_method: Method used to verify (block explorer, node, etc)
        
        Returns:
            ValidationResult with reality gap
        """
        start = time.time()
        
        # Compare prediction with actual data
        # This is a simplified version - real implementation would be more complex
        validated = prediction.get("outcome") == actual_onchain_data.get("outcome")
        
        # Calculate reality gap based on data match
        if validated:
            reality_gap = 0.0
        else:
            reality_gap = 0.8  # High gap for on-chain mismatch
        
        # High validation score for on-chain data
        validation_score = 0.95
        
        result = ValidationResult(
            validated=validated,
            reality_gap=reality_gap,
            validation_score=validation_score,
            method=ValidationMethod.ONCHAIN,
            evidence={
                "prediction": prediction,
                "actual_data": actual_onchain_data,
                "verification_method": verification_method
            },
            timestamp=time.time()
        )
        
        self._validation_count += 1
        self._method_counts[ValidationMethod.ONCHAIN] += 1
        
        duration_ms = (time.time() - start) * 1000
        logger.debug(
            "On-chain validation: validated=%s gap=%.3f method=%s (%.2fms)",
            validated, reality_gap, verification_method, duration_ms
        )
        
        return result
    
    def validate_timeout(
        self,
        age_seconds: float,
        timeout_threshold: float = 3600.0
    ) -> ValidationResult:
        """
        Mark prediction as expired due to timeout.
        
        Args:
            age_seconds: Age of prediction in seconds
            timeout_threshold: Timeout threshold
        
        Returns:
            ValidationResult marking as expired
        """
        reality_gap = 0.5  # Neutral gap for timeout
        validation_score = 0.3  # Low confidence - no actual validation
        
        result = ValidationResult(
            validated=False,
            reality_gap=reality_gap,
            validation_score=validation_score,
            method=ValidationMethod.TIMEOUT,
            evidence={
                "age_seconds": age_seconds,
                "timeout_threshold": timeout_threshold,
                "reason": "Prediction expired without validation"
            },
            timestamp=time.time()
        )
        
        self._validation_count += 1
        self._method_counts[ValidationMethod.TIMEOUT] += 1
        
        logger.debug(
            "Timeout validation: age=%.1fs threshold=%.1fs",
            age_seconds, timeout_threshold
        )
        
        return result
    
    def calculate_aggregate_reality_gap(
        self,
        validations: List[ValidationResult]
    ) -> float:
        """
        Calculate aggregate reality gap from multiple validations.
        
        Args:
            validations: List of validation results
        
        Returns:
            Weighted average reality gap
        """
        if not validations:
            return 0.5  # Neutral gap if no validations
        
        total_weight = 0.0
        weighted_gap = 0.0
        
        for validation in validations:
            weight = validation.validation_score
            total_weight += weight
            weighted_gap += validation.reality_gap * weight
        
        if total_weight == 0:
            return 0.5
        
        return weighted_gap / total_weight
    
    def detect_anomalies(
        self,
        validations: List[ValidationResult],
        threshold: float = 0.3
    ) -> List[str]:
        """
        Detect anomalies in validation results.
        
        Args:
            validations: List of validation results
            threshold: Threshold for anomaly detection
        
        Returns:
            List of anomaly descriptions
        """
        anomalies = []
        
        if not validations:
            return anomalies
        
        # Check for conflicting validations
        validated_count = sum(1 for v in validations if v.validated)
        invalidated_count = len(validations) - validated_count
        
        if validated_count > 0 and invalidated_count > 0:
            anomalies.append(
                f"Conflicting validations: {validated_count} validated, {invalidated_count} invalidated"
            )
        
        # Check for high variance in reality gaps
        gaps = [v.reality_gap for v in validations]
        if len(gaps) > 1:
            gap_variance = sum((g - sum(gaps)/len(gaps))**2 for g in gaps) / len(gaps)
            if gap_variance > threshold:
                anomalies.append(
                    f"High variance in reality gaps: {gap_variance:.3f}"
                )
        
        # Check for low validation scores
        low_score_count = sum(1 for v in validations if v.validation_score < 0.5)
        if low_score_count > len(validations) / 2:
            anomalies.append(
                f"Low validation confidence: {low_score_count}/{len(validations)} below 0.5"
            )
        
        return anomalies
    
    def get_stats(self) -> Dict[str, Any]:
        """Get validator statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "total_validations": self._validation_count,
            "validations_by_method": {
                method.value: count
                for method, count in self._method_counts.items()
            },
            "performance": {
                "uptime_seconds": round(uptime, 2),
                "validations_per_second": round(self._validation_count / uptime, 2) if uptime > 0 else 0
            }
        }
