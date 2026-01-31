from __future__ import annotations

# Stage 4 Validation: common contracts for external reality validators.

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

ValidationStatus = Literal["confirmed", "failed", "pending", "error"]


@dataclass
class ValidatorVerdict:
    name: str
    status: ValidationStatus
    score: float
    details: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class BaseValidator:
    name: str = "base"
    weight: float = 1.0
    requires_metadata: bool = False

    async def validate(self, energy: Dict[str, Any], vote_result: Dict[str, Any]) -> ValidatorVerdict:
        """
        Base validation implementation.
        
        Args:
            energy: Energy data from the system
            vote_result: Vote result data
            
        Returns:
            ValidatorVerdict with validation results
        """
        # Default implementation - checks basic data integrity
        try:
            # Check if required fields are present
            if not energy or not vote_result:
                return self.failure("Missing required energy or vote result data")
            
            # Check energy data structure
            required_energy_fields = ["agent_id", "proposal_id", "energy_amount"]
            for field in required_energy_fields:
                if field not in energy:
                    return self.failure(f"Missing required energy field: {field}")
            
            # Check vote result structure
            required_vote_fields = ["vote", "confidence", "reasoning"]
            for field in required_vote_fields:
                if field not in vote_result:
                    return self.failure(f"Missing required vote field: {field}")
            
            # Validate energy amount is positive
            if energy.get("energy_amount", 0) <= 0:
                return self.failure("Energy amount must be positive")
            
            # Validate confidence is within bounds
            confidence = vote_result.get("confidence", 0)
            if not 0 <= confidence <= 1:
                return self.failure("Confidence must be between 0 and 1")
            
            # Basic validation passed
            return self.success(
                "Basic validation passed",
                score=0.8,  # Good but not perfect score
                evidence={
                    "energy_fields_present": all(field in energy for field in required_energy_fields),
                    "vote_fields_present": all(field in vote_result for field in required_vote_fields),
                    "energy_positive": energy.get("energy_amount", 0) > 0,
                    "confidence_valid": 0 <= confidence <= 1
                }
            )
            
        except Exception as e:
            return self.error(f"Validation error: {str(e)}")

    def pending(self, details: str, *, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "pending", 0.0, details, evidence or {})

    def failure(self, details: str, *, score: float = 0.0, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "failed", max(0.0, score), details, evidence or {})

    def success(self, details: str, *, score: float = 1.0, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "confirmed", min(1.0, score), details, evidence or {})

    def error(self, details: str, *, evidence: Dict[str, Any] | None = None) -> ValidatorVerdict:
        return ValidatorVerdict(self.name, "error", 0.0, details, evidence or {})
